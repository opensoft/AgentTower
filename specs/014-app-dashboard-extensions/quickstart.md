# Quickstart: Exercising App Dashboard Extensions (v1.1)

**Created**: 2026-05-24
**Plan**: [plan.md](./plan.md)
**Contracts**: [contracts/dashboard-v1_1.md](./contracts/dashboard-v1_1.md), [contracts/closed-sets-v1_1.md](./contracts/closed-sets-v1_1.md)

This walkthrough shows a synthetic NDJSON socket client exercising the v1.1 additive fields on `app.dashboard`, the FR-019 panes cross-check, and the FR-021 compute-failure null fallback. It mirrors the FEAT-011 quickstart pattern (no `agenttower` subprocess invocation; bare-metal socket client) and assumes the daemon is running locally with a v1.1 build.

## Prereqs

- Python 3.11+ environment with the FEAT-011 `tests/fixtures/app_synthetic_client.py` helper available.
- Local `agenttowerd` running, advertising contract version `1.1` (verify with `app.hello` — see Step 1).
- The daemon is seeded with the mixed-state fixture used by `tests/integration/test_story1_dashboard_bootstrap.py` (≥ 1 active container, ≥ 1 registered pane, ≥ 1 unadopted pane, ≥ 1 partially-configured agent, ≥ 1 log-detached agent).

## Step 1 — Handshake and confirm v1.1

```python
from tests.fixtures.app_synthetic_client import AppClient

with AppClient.connect() as c:
    hello = c.call("app.hello", {})
    assert hello["ok"]
    assert hello["result"]["daemon_app_contract_version"] == "1.1"
    assert hello["result"]["capability_flags"] == {}     # FR-015
    session_token = hello["result"]["app_session_token"]
```

**Expected**: `daemon_app_contract_version == "1.1"`. If the daemon still advertises `"1.0"`, FEAT-014 has not been deployed.

## Step 2 — Call `app.dashboard`, assert v1.1 envelope shape

```python
with AppClient.connect(token=session_token) as c:
    resp = c.call("app.dashboard", {})

result = resp["result"]
assert resp["app_contract_version"] == "1.1"

# v1.0 fields still present (FR-014)
panes_v1 = result["counts"]["panes"]
assert {"total", "registered", "unregistered"} <= panes_v1.keys()

# v1.1 panes.by_state — exactly 4 keys, all integers (closed set)
by_state = result["counts"]["panes"]["by_state"]
assert set(by_state.keys()) == {
    "discovered-and-unmanaged",
    "discovered-and-registered",
    "inactive-or-stale",
    "discovery-degraded",
}
assert all(isinstance(v, int) and v >= 0 for v in by_state.values())

# v1.1 agents.by_state — exactly 5 keys, all integers
agents_by_state = result["counts"]["agents"]["by_state"]
assert set(agents_by_state.keys()) == {
    "active", "inactive", "partially_configured",
    "log-attached", "log-detached",
}
assert all(isinstance(v, int) and v >= 0 for v in agents_by_state.values())

# v1.1 routes.recently_skipped_*
assert result["counts"]["routes"]["recently_skipped_window_ms"] == 300_000
assert result["counts"]["routes"]["recently_skipped_count"] >= 0

# v1.1 recommendation
rec = result["recommended_next_action"]
ts  = result["recommended_next_action_refreshed_at"]
assert (rec is None) == (ts is None)        # paired-null invariant (Research §FE)
```

**Expected**: All keys present, all counts non-negative integers, `recommended_next_action` and `_refreshed_at` nulled together if at all.

## Step 3 — Verify FR-019 panes cross-check

```python
by_state = result["counts"]["panes"]["by_state"]
panes_v1 = result["counts"]["panes"]

# Post-R3 one-sided invariants (FR-019, Clarifications §Session 2026-05-25-r3 Q1):
# `discovered-and-registered` can be STRICTLY LESS THAN v1.0 `registered` when a
# registered agent sits on an inactive or `degraded_scan` container — Research §PB
# routes that pane into `inactive-or-stale` / `discovery-degraded` rather than
# `discovered-and-registered`. The same gap shows up on the unregistered side.
assert by_state["discovered-and-registered"] <= panes_v1["registered"]
assert (
    by_state["discovered-and-unmanaged"]
    + by_state["inactive-or-stale"]
    + by_state["discovery-degraded"]
) >= panes_v1["unregistered"]
# Total-sum invariant — STRICT on the healthy path this walkthrough assumes
# (a populated, non-degraded daemon). It (and the Step 4 agent-partition
# equalities below) is SUSPENDED on the FR-025 aggregator-failure path, where
# by_state zero-fills while panes_v1["total"] stays nonzero; detect that case
# via recommended_next_action.code == "subsystem_degraded" before asserting.
assert sum(by_state.values()) == panes_v1["total"]
```

**Expected**: all three invariants hold. They are enforced *by construction* in `dashboard.py` (same row set, partitioned per Research §PB priority).

## Step 4 — Verify FR-020 agent partition

```python
agents_by_state = result["counts"]["agents"]["by_state"]
agents_total    = result["counts"]["agents"]["total"]

# Configuration partition is strict (FR-020)
assert (
    agents_by_state["active"]
    + agents_by_state["inactive"]
    + agents_by_state["partially_configured"]
) == agents_total

# Log-attachment partition is independent (FR-006)
assert (
    agents_by_state["log-attached"]
    + agents_by_state["log-detached"]
) == agents_total

# Sum of all five MAY exceed total (orthogonality)
assert sum(agents_by_state.values()) >= agents_total
```

**Expected**: both strict partitions hold; the orthogonality assertion documents the legal overlap.

## Step 5 — Inspect the recommendation precedence

For each fixture state in `tests/unit/test_recommendations.py` the recommendation code is deterministic:

| Fixture seeded | Expected `recommended_next_action.code` |
|---|---|
| Healthy daemon, no problems | `all_clear` |
| Healthy daemon, no routes | `no_routes_configured` |
| Healthy daemon, no routes, queue has blocked row | `blocked_queue_drain` |
| Healthy daemon, no routes, blocked queue, panes discovered but unadopted | `unadopted_panes_present` |
| Healthy daemon, containers present but zero panes discovered | `no_panes_discovered` |
| Healthy daemon, zero containers | `no_containers` |
| Any of the above, plus a subsystem degraded | `subsystem_degraded` |

This is SC-003 in observable form: the higher-precedence code wins regardless of how many lower-precedence conditions are simultaneously true. The first four rows above stack genuinely-coexisting conditions; the last three are *independent minimal states*, because `unadopted_panes_present` (requires `pane_count > 0`), `no_panes_discovered` (`pane_count == 0`), and `no_containers` (`container_count == 0`) are mutually exclusive and cannot be stacked. SC-003 (b) specifically requires the adjacent-pair check (`no_containers` beats `no_panes_discovered`), which `tests/unit/test_recommendations.py` exercises directly.

## Step 6 — Force compute failure (negative path, FR-021)

A test fixture that monkeypatches `agenttower.app_contract.recommendations.compute_recommendation` to raise drives the FR-021 compute-failure pathway. (Breaking a *state-builder accessor* does NOT reach this path: per FR-025 the v1.1 aggregators catch their own failures, return all-zeros, and flip the recommendation to `subsystem_degraded` — a non-null result — rather than raising.) The try/except boundary lives in **the dashboard handler** (`dashboard.py::app_dashboard`), NOT inside `compute_recommendation` itself — the recommendation function is pure and its return type is non-optional `RecommendedNextAction`; the wire-null pathway is the dashboard's responsibility per Research §FE. Calling `app.dashboard` with the monkeypatch active:

```python
result = c.call("app.dashboard", {})["result"]
assert result["recommended_next_action"]                  is None
assert result["recommended_next_action_refreshed_at"]     is None

# Rest of the v1.1 payload is unaffected (FR-021)
assert "by_state" in result["counts"]["panes"]
assert "by_state" in result["counts"]["agents"]
assert "recently_skipped_count" in result["counts"]["routes"]
```

**Expected**: both recommendation fields nulled, every other v1.1 field still populated and well-typed. The daemon's stderr/log contains a single `WARN` entry with the event name `app_dashboard_recommendation_compute_failed` (Research §FE).

## Step 7 — Verify v1.0 client compatibility (US4)

```python
# A "v1.0 client" is a caller that only inspects the v1.0 keys and never
# accesses anything under `by_state`, `recently_skipped_*`, or `recommended_*`.
# The daemon still emits those fields; the client simply doesn't read them.
v1_only = AppClient.connect(token=session_token).call("app.dashboard", {})["result"]
assert v1_only["counts"]["panes"]["total"]      >= 0
assert v1_only["counts"]["panes"]["registered"] >= 0
# No error, no contract violation, no surprise behavior.
```

This is the assertion from US4 acceptance #1: a v1.1 daemon emitting unknown-to-v1.0 fields does not break a v1.0 client's reads.

## What this quickstart deliberately does NOT cover

- Pushing skip events into the ring buffer manually (FEAT-010 routing worker does this; see `tests/unit/test_skip_counter.py` for direct exercise).
- Performance assertions (SC-002 / SC-006 are covered by `tests/integration/test_story1_dashboard_bootstrap.py`).
- Versioning regressions (covered by the new `tests/unit/test_app_versioning.py` — T021; no `tests/contract/` directory in this repo).

These belong in the structured test suite, not the operator-facing walkthrough.
