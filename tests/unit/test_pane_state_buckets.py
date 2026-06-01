"""FEAT-014 T003 — Unit tests for the PaneState bucket aggregator.

Exercises ``agenttower.app_contract.dashboard._compute_pane_state_buckets``.

Maps to:

* FR-001 / FR-002 — every v1.1 PaneState key present.
* FR-003 — empty buckets emit integer ``0``, not omitted or ``null``.
* FR-019 — panes cross-check (sum == total) + Research §PR carve-out
  (partially_configured agents still register their pane).
* FR-025 — aggregator-failure path returns all-zero, never raises.
* Research §PB — bucket priority (degraded > stale > registered > unmanaged).
* US1 acceptance scenario #1 — 1 registered + 2 unadopted → {dau:2, dar:1, ios:0, dd:0}.

Every assertion is ``@pytest.mark.v1_1`` per tasks.md §Notes 'v1.1 marker rule'.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agenttower.app_contract.dashboard import (
    PANE_STATE_KEYS,
    _compute_pane_state_buckets,
)
from agenttower.state.schema import open_registry

from ._v11_fixture_helpers import seed_agent, seed_container, seed_pane


@pytest.fixture
def db_ctx(tmp_path: Path) -> Iterator[SimpleNamespace]:
    """Minimal ctx-shaped object: only ``state_conn`` is read by the helper.

    Yields (not returns) so the SQLite connection is explicitly closed on
    teardown, matching the repo norm (``test_state_schema.py`` etc.);
    ``tmp_path`` removes the on-disk file but not the live connection object.
    """
    state_db = tmp_path / "registry.db"
    conn, _status = open_registry(state_db, namespace_root=tmp_path)
    try:
        yield SimpleNamespace(state_conn=conn)
    finally:
        conn.close()


# ─── FR-002 / FR-003 — keys present, integer-typed ─────────────────────────


@pytest.mark.v1_1
def test_all_four_keys_present_when_empty(db_ctx: SimpleNamespace) -> None:
    """FR-002 / FR-003: every PaneState key present with integer ``0`` on empty DB."""
    result = _compute_pane_state_buckets(db_ctx)
    assert set(result.keys()) == set(PANE_STATE_KEYS)
    for key in PANE_STATE_KEYS:
        assert isinstance(result[key], int), f"{key} value is not int"
        assert result[key] == 0, f"{key} should be 0 on empty DB, got {result[key]}"


# ─── FR-025 — aggregator-failure fallback ─────────────────────────────────


@pytest.mark.v1_1
def test_fr025_fallback_no_state_conn() -> None:
    """FR-025: ctx without ``state_conn`` → all-zero, no exception."""
    result = _compute_pane_state_buckets(SimpleNamespace())
    assert result == {k: 0 for k in PANE_STATE_KEYS}


@pytest.mark.v1_1
def test_fr025_fallback_accessor_raises() -> None:
    """FR-025: if the SQLite accessor raises (e.g., missing tables), return all-zero."""

    class BrokenConn:
        def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("simulated FEAT-003 service-layer outage")

    result = _compute_pane_state_buckets(SimpleNamespace(state_conn=BrokenConn()))
    assert result == {k: 0 for k in PANE_STATE_KEYS}


@pytest.mark.v1_1
def test_fr025_second_half_failed_subsystems_collects_sqlite() -> None:
    """FR-025 second-half (codex P2 #3298870845): when the SQLite accessor
    raises AND a ``failed_subsystems`` set is supplied, the aggregator adds
    ``"sqlite"`` to it so the dashboard handler propagates it into
    ``degraded_subsystems`` and the recommendation fires
    ``subsystem_degraded``. Without this signal the spec gap (zero-filled
    buckets + healthy-looking recommendation) re-opens.
    """

    class BrokenConn:
        def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("simulated SQLite outage")

    failed: set[str] = set()
    result = _compute_pane_state_buckets(
        SimpleNamespace(state_conn=BrokenConn()), failed
    )
    assert result == {k: 0 for k in PANE_STATE_KEYS}
    assert failed == {"sqlite"}


@pytest.mark.v1_1
def test_fr025_no_state_conn_does_not_flag_subsystem() -> None:
    """FR-025 second-half boundary: a missing ``state_conn`` is a daemon
    bring-up signal (already covered by FEAT-011 ``probe_sqlite``), NOT a
    runtime aggregator failure — ``failed_subsystems`` is left untouched
    so the dashboard handler doesn't double-flag what readiness already
    flagged.
    """
    failed: set[str] = set()
    result = _compute_pane_state_buckets(SimpleNamespace(), failed)
    assert result == {k: 0 for k in PANE_STATE_KEYS}
    assert failed == set()


# ─── US1 acceptance scenario #1 ────────────────────────────────────────────


@pytest.mark.v1_1
def test_us1_acceptance_one_registered_two_unadopted(db_ctx: SimpleNamespace) -> None:
    """US1 acceptance #1: 1 registered + 2 unadopted panes on an active container
    → ``{dau: 2, dar: 1, ios: 0, dd: 0}``."""
    seed_container(db_ctx.state_conn, container_id="c1", active=1)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=0)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=1)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=2)
    seed_agent(db_ctx.state_conn, agent_id="a1", container_id="c1", pane_index=0)

    result = _compute_pane_state_buckets(db_ctx)
    assert result == {
        "discovered-and-unmanaged": 2,
        "discovered-and-registered": 1,
        "inactive-or-stale": 0,
        "discovery-degraded": 0,
    }


# ─── FR-019 — panes cross-check (post-R3 one-sided invariants) ─────────────


@pytest.mark.v1_1
def test_fr019_cross_check_sum_equals_total_panes(db_ctx: SimpleNamespace) -> None:
    """FR-019 strict-equality leg: sum of all four buckets == total panes
    (no double-counting). The total-sum invariant remained strict after R3."""
    seed_container(db_ctx.state_conn, container_id="c1", active=1)
    for i in range(5):
        seed_pane(db_ctx.state_conn, container_id="c1", pane_index=i)
    result = _compute_pane_state_buckets(db_ctx)
    assert sum(result.values()) == 5


@pytest.mark.v1_1
def test_fr019_loosened_invariant_registered_agent_on_inactive_container(
    db_ctx: SimpleNamespace,
) -> None:
    """FR-019 post-R3 ≤/≥ legs (Clarifications §Session 2026-05-25-r3 Q1
    Option B): when a registered agent sits on an inactive container, the
    Research §PB priority rule routes its pane to ``inactive-or-stale``
    instead of ``discovered-and-registered``. This drives the loosened
    one-sided invariants:

    - ``dar < v1.0 registered`` (strict gap)
    - ``dau + ios + dd > v1.0 unregistered`` (mirror gap)
    - total-sum == total panes (still strict)

    Without this test the pre-R3 strict-equality path is the only one
    exercised — see swarm code-review M1.
    """
    from agenttower.app_contract.dashboard import _pane_counts  # local: keep import scope tight

    # Active container with 1 unadopted pane → contributes 1 dau, 1 unregistered.
    seed_container(db_ctx.state_conn, container_id="c-act", active=1)
    seed_pane(db_ctx.state_conn, container_id="c-act", pane_index=0)

    # Inactive container with 1 pane + 1 registered agent → §PB sends pane
    # to ios, BUT v1.0 _pane_counts still flags it as "registered" because
    # the agent row exists with active=1.
    seed_container(db_ctx.state_conn, container_id="c-ina", active=0)
    seed_pane(db_ctx.state_conn, container_id="c-ina", pane_index=0)
    seed_agent(
        db_ctx.state_conn,
        agent_id="a-on-ina",
        container_id="c-ina",
        pane_index=0,
    )

    by_state = _compute_pane_state_buckets(db_ctx)
    v1_0 = _pane_counts(db_ctx)

    # The gap: v1.0 sees the agent on c-ina as a "registered" pane (count=1),
    # but §PB routes that pane to ios; dar therefore goes to 0, not 1.
    assert by_state["discovered-and-registered"] == 0
    assert by_state["inactive-or-stale"] == 1
    assert by_state["discovered-and-unmanaged"] == 1
    assert by_state["discovery-degraded"] == 0
    assert v1_0["registered"] == 1
    assert v1_0["unregistered"] == 1
    assert v1_0["total"] == 2

    # FR-019 post-R3 invariants — STRICTLY one-sided in this fixture:
    assert by_state["discovered-and-registered"] < v1_0["registered"], (
        "FR-019 ≤ leg should be strict here (registered agent on inactive container)"
    )
    assert (
        by_state["discovered-and-unmanaged"]
        + by_state["inactive-or-stale"]
        + by_state["discovery-degraded"]
        > v1_0["unregistered"]
    ), "FR-019 ≥ leg should be strict here (mirror of the dar gap)"
    assert sum(by_state.values()) == v1_0["total"], (
        "FR-019 total-sum invariant stays strict (R3 did not loosen this)"
    )


# ─── Research §PB — bucket priority ────────────────────────────────────────


@pytest.mark.v1_1
def test_research_pb_priority_inactive_container_wins_over_unmanaged(
    db_ctx: SimpleNamespace,
) -> None:
    """Research §PB: a pane on an inactive container goes to ``inactive-or-stale``,
    NOT ``discovered-and-unmanaged`` (priority: stale > unmanaged)."""
    seed_container(db_ctx.state_conn, container_id="c-act", active=1)
    seed_container(db_ctx.state_conn, container_id="c-ina", active=0)
    seed_pane(db_ctx.state_conn, container_id="c-act", pane_index=0)
    seed_pane(db_ctx.state_conn, container_id="c-ina", pane_index=0)

    result = _compute_pane_state_buckets(db_ctx)
    assert result["inactive-or-stale"] == 1, "pane on inactive container should be in ios"
    assert result["discovered-and-unmanaged"] == 1, "pane on active container w/o agent → dau"
    assert result["discovered-and-registered"] == 0
    assert result["discovery-degraded"] == 0


@pytest.mark.v1_1
def test_inactive_pane_on_active_container_is_stale_not_unmanaged(
    db_ctx: SimpleNamespace,
) -> None:
    """codex P2 — a pane whose own ``active`` flag is unset (FEAT-004
    reconciliation marked it inactive when it disappeared) on an *active*
    container belongs in ``inactive-or-stale``, not
    ``discovered-and-unmanaged``. Guards the regression where the ios query
    keyed only off ``c.active`` and let ``p.active = 0`` panes fall through
    to the adopt-me ``dau`` bucket."""
    seed_container(db_ctx.state_conn, container_id="c-act", active=1)
    # Active pane (→ dau, no agent) + an inactive pane on the SAME active
    # container (→ ios via p.active=0).
    seed_pane(db_ctx.state_conn, container_id="c-act", pane_index=0, active=1)
    seed_pane(db_ctx.state_conn, container_id="c-act", pane_index=1, active=0)

    result = _compute_pane_state_buckets(db_ctx)
    assert result["inactive-or-stale"] == 1, "p.active=0 pane → stale even on active container"
    assert result["discovered-and-unmanaged"] == 1, "the active no-agent pane stays dau"
    assert result["discovered-and-registered"] == 0
    assert result["discovery-degraded"] == 0
    assert sum(result.values()) == 2, "partition stays exhaustive over both panes"


@pytest.mark.v1_1
def test_inactive_pane_with_active_agent_is_stale_not_registered(
    db_ctx: SimpleNamespace,
) -> None:
    """codex P2 follow-on — a ``p.active = 0`` pane with an active agent on an
    active container is ``inactive-or-stale`` (§PB priority outranks
    registered), NOT ``discovered-and-registered``; the ``p.active = 1`` guard
    on the dar query is what keeps the two buckets disjoint."""
    seed_container(db_ctx.state_conn, container_id="c1", active=1)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=0, active=0)
    seed_agent(db_ctx.state_conn, agent_id="a1", container_id="c1", pane_index=0)

    result = _compute_pane_state_buckets(db_ctx)
    assert result["inactive-or-stale"] == 1
    assert result["discovered-and-registered"] == 0, "p.active=0 keeps it out of dar"
    assert result["discovered-and-unmanaged"] == 0
    assert sum(result.values()) == 1


@pytest.mark.v1_1
def test_first_unadopted_pane_id_skips_stale_panes(db_ctx: SimpleNamespace) -> None:
    """codex P2 — the ``unadopted_panes_present`` target must be an
    *adoptable* (active) pane, never a ``p.active = 0`` stale pane on an
    active container. ``_first_unadopted_pane_id`` must skip stale panes so
    the recommendation stays consistent with the ``inactive-or-stale``
    bucket."""
    from agenttower.app_contract.dashboard import _first_unadopted_pane_id

    seed_container(db_ctx.state_conn, container_id="c1", active=1)
    # Only pane is stale (p.active=0) and unadopted → not adoptable.
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=0, active=0)
    assert _first_unadopted_pane_id(db_ctx) is None, "stale pane must not be a target"

    # Add an active unadopted pane → that one becomes the deterministic target.
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=1, active=1)
    assert _first_unadopted_pane_id(db_ctx) == "%1"


# ─── Research §PR — partially_configured agent still registers pane ────────


@pytest.mark.v1_1
def test_research_pr_partially_configured_agent_still_registers_pane(
    db_ctx: SimpleNamespace,
) -> None:
    """Research §PR / FR-019 carve-out: an agent with role='unknown' (a
    ``partially_configured`` AgentState bucket per Clarifications Q2) still
    puts its pane in ``discovered-and-registered``. The pane bucket is
    determined by ``agents.active = 1``, NOT agent configuration completeness.
    """
    seed_container(db_ctx.state_conn, container_id="c1", active=1)
    seed_pane(db_ctx.state_conn, container_id="c1", pane_index=0)
    seed_agent(
        db_ctx.state_conn,
        agent_id="a1",
        container_id="c1",
        pane_index=0,
        # Partially-configured: role='unknown' triggers it per Clarifications Q2.
        role="unknown",
    )

    result = _compute_pane_state_buckets(db_ctx)
    assert result["discovered-and-registered"] == 1, (
        "partially_configured agent should still register its pane (FR-019 carve-out)"
    )
    assert result["discovered-and-unmanaged"] == 0
