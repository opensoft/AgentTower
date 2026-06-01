# Phase 1 Data Model: App Dashboard Extensions (v1.1)

**Created**: 2026-05-24
**Plan**: [plan.md](./plan.md)

This file captures the v1.1 entities, closed-set vocabularies, and derived-aggregation rules. All entities are read-side projections over existing FEAT-003/004/006/007/010 state — no new SQLite table, no new JSONL stream, no new in-memory persistence beyond the route-skip ring buffer.

---

## Entity: `PaneState` (closed set)

**Purpose**: Group every pane row into one of four operationally-meaningful buckets for `counts.panes.by_state`.

**Cardinality on the wire**: closed set of exactly 4 string keys. Future v1.x minors may add keys (clients ignore unknown — FR-012); v1.x MUST NOT rename or remove keys.

**Keys** (hyphenated; Clarifications Q12):

| Key | Definition (Clarifications Q1) |
|---|---|
| `discovered-and-unmanaged` | A pane row exists, but no agent is registered for it. |
| `discovered-and-registered` | A pane row exists AND an agent is registered for it. (See Research §PR — agent's `partially_configured` status does NOT exclude the pane from this bucket.) |
| `inactive-or-stale` | A pane row whose owning container is in container state `inactive`, OR whose own `active` flag is unset (FEAT-004 reconciliation marks a pane inactive when it disappears while its container stays active), OR whose `last_seen_at` predates the most recent successful pane scan (this `last_seen_at` half is deferred until upstream scan-timestamp wiring lands). |
| `discovery-degraded` | A pane row whose owning container is in container state `degraded_scan`. |

**Bucket assignment priority** (Research §PB — first match wins):

1. `discovery-degraded`
2. `inactive-or-stale`
3. `discovered-and-registered`
4. `discovered-and-unmanaged`

**Invariants** (FR-019, post-R3):

- `discovered-and-registered` ≤ v1.0 `counts.panes.registered`. The gap, if any, equals the count of registered panes that the Research §PB priority rule routes to `inactive-or-stale` / `discovery-degraded` instead — i.e. panes whose container is `inactive`/`degraded_scan`, whose own `active` flag is unset (FEAT-004 reconciliation), or whose `last_seen_at` is stale.
- `discovered-and-unmanaged + inactive-or-stale + discovery-degraded` ≥ v1.0 `counts.panes.unregistered` (the opposite side of the same gap).
- Sum of all four == v1.0 `counts.panes.total` (strict — the partition is exhaustive).

The two cross-checks were loosened from strict equality to one-sided invariants in Clarifications §Session 2026-05-25-r3 Q1, after the MVP implementation surfaced the contradiction with §PB priority. The previous strict-equality wording held only for fixtures with every registered pane on an active container; mixed-state daemon fixtures expose the gap. The total-sum invariant remains strict.

**Lifecycle**: `PaneState` is a purely derived view computed once per `app.dashboard` request from the FEAT-003 / FEAT-004 service-layer accessors. PaneState has no state transitions and no per-instance persistence — there is no entity to "transition" between buckets; each call partitions the current row set anew. A pane that moves from one bucket to another between two consecutive `app.dashboard` calls is simply observed in a different bucket on the second call; nothing is logged or transitioned at the PaneState layer itself.

---

## Entity: `AgentState` (closed set)

**Purpose**: Group every registered-agent row into one of five buckets for `counts.agents.by_state`. Unlike `PaneState`, this set is **not** a strict partition — `log-attached`/`log-detached` are orthogonal to `active`/`inactive`/`partially_configured` (FR-006, FR-020).

**Keys** (hyphenated; Clarifications Q12):

| Key | Definition |
|---|---|
| `active` | Registered agent whose owning container's `state == "active"`, whose own `active` flag is set, AND whose config is complete (i.e., is not `partially_configured`). |
| `inactive` | Registered agent whose config is complete but which is not `active` — i.e., its owning container's `state ∈ {"inactive", "degraded_scan"}` OR its own `active` flag is unset (e.g., FEAT-006 cascaded it inactive when its bound pane went inactive). |
| `partially_configured` | Registered agent for which one or more of `role`, `capability`, `label` is missing/empty/`unknown`. Mutually exclusive with `active` and `inactive` — a partially-configured agent does NOT contribute to either of those buckets (Clarifications Q5, FR-020). |
| `log-attached` | Registered agent whose current log-attachment state (per FEAT-007) is attached. Orthogonal to the three buckets above — may co-occur with any of them. |
| `log-detached` | Registered agent whose current log-attachment state is detached. Orthogonal. |

**Invariants** (FR-020):

- `active + inactive + partially_configured` == total registered agents (strict partition).
- `log-attached + log-detached` == total registered agents (strict partition, but independent of the above).
- The sum of all five keys MAY exceed total agents (FR-006); the response MUST document this in `dashboard-v1_1.md`.

**Lifecycle**: `AgentState` is a purely derived view computed once per `app.dashboard` request from the FEAT-003 (container state) / FEAT-006 (registration + role/capability/label) / FEAT-007 (log attachment) service-layer accessors. AgentState has no state transitions and no per-instance persistence — each call partitions and computes the current agent rows anew. An agent that moves between buckets (e.g., from `partially_configured` to `active` when its `role` is set) is simply observed in a different bucket on the next call.

---

## Entity: `RecommendedNextAction`

**Purpose**: A single daemon-computed dashboard recommendation per `app.dashboard` call (Clarifications Q8 — recomputed every call, no cache).

**Wire shape** (FR-011):

```json
{
  "code":   "<closed_set_string>",
  "title":  "<string, ≤128 chars>",
  "detail": "<string, ≤512 chars> | null",
  "target": { "kind": "<closed_set_string>", "id": "<string>" } | null
}
```

**Closed set: `code`** (FR-010, evaluated top-to-bottom; first match wins):

1. `subsystem_degraded`
2. `no_containers`
3. `no_panes_discovered`
4. `unadopted_panes_present`
5. `blocked_queue_drain`
6. `no_routes_configured`
7. `all_clear`

**Closed set: `target.kind`** (FR-011 + Clarifications Q9 Option A): `container`, `pane`, `agent`, `route`, `message`, `event`, and the v1.1 addition `subsystem` (allowed values for `target.id` when `kind == "subsystem"` are defined in Research §SS).

**Target rule per code**:

| Code | `target` |
|---|---|
| `subsystem_degraded` | `{kind: "subsystem", id: <subsystem_name>}` when attributable; `null` otherwise (Research §SS). |
| `no_containers` | `null`. |
| `no_panes_discovered` | `{kind: "container", id: <first_active_container_id>}`; `null` when containers exist but none is active (best-effort, no resolvable container id — the `no_containers` branch at higher precedence already handles the zero-container case). |
| `unadopted_panes_present` | `{kind: "pane", id: <first_unadopted_pane_id>}` (first by FEAT-004 default ordering). |
| `blocked_queue_drain` | `{kind: "message", id: <oldest_blocked_queue_message_id>}`. |
| `no_routes_configured` | `null`. |
| `all_clear` | `null`. |

"First" means *deterministic-first by FEAT-011's normative orderings* (Research §CC).

**Compute-failure null fallback** (FR-021, Research §FE): if the recommendation function raises, both `recommended_next_action` and `recommended_next_action_refreshed_at` are `null` in the response envelope. The dashboard call still succeeds; no new error code is emitted. The daemon logs `app_dashboard_recommendation_compute_failed` at WARN. The null pathway lives in the **dashboard handler's** try/except (T020), NOT inside `compute_recommendation` itself — the function's return type is non-optional `RecommendedNextAction`; `all_clear` is the floor that always matches when no higher-precedence condition fires.

**Compute API** (added post-analyze M-T019-API — pins the Python surface so T016 tests and T019 implementation share one canonical contract):

The recommendation engine lives in `src/agenttower/app_contract/recommendations.py` and exposes four symbols:

| Symbol | Kind | Purpose |
|---|---|---|
| `RecommendationState` | `@dataclass(frozen=True)` | Pure input struct, keyword-only with defaults. Fields: `degraded_subsystems: tuple[str, ...] = ()` (caller-supplied; canonical-ordered internally via `PROBE_ORDER`), `container_count: int = 0`, `first_active_container_id: str \| None = None`, `pane_count: int = 0`, `first_unadopted_pane_id: str \| None = None`, `unadopted_pane_count: int = 0` (drives `{N}` template substitution for the `unadopted_panes_present` detail per `contracts/closed-sets-v1_1.md` §Per-code Templates), `oldest_blocked_message_id: str \| None = None`, `blocked_queue_count: int = 0` (drives `{N}` template substitution for the `blocked_queue_drain` detail), `route_count: int = 0`. |
| `RecommendedNextAction` | `@dataclass(frozen=True)` | Pure output struct matching the FR-011 wire shape: `code: str`, `title: str`, `detail: str \| None`, `target: dict \| None` (`{"kind": str, "id": str}` or `None`). |
| `PROBE_ORDER` | `Final[tuple[str, ...]]` | Re-export alias for `versioning.SUBSYSTEM_NAMES`. Used internally to canonicalize `degraded_subsystems` order so two callers passing differently-ordered tuples produce the same `target.id` per Research §CC. |
| `compute_recommendation(state)` | function | Signature: `compute_recommendation(state: RecommendationState) -> RecommendedNextAction`. Pure, no I/O, no cache. Walks the 7-code precedence list top-to-bottom; returns the first match. `all_clear` is the floor — the function never returns `None`. |

The dashboard handler (T020) is responsible for the state-building step (reading SQLite rows + readiness probes and packing them into a `RecommendationState`) AND for the try/except around `compute_recommendation`. The state-building step is INTENTIONALLY outside the recommendation module to keep `compute_recommendation` a pure function over its input dataclass, making it trivially testable (see T016 tests for the canonical fixture pattern).

**`{N}` gate + floor** (codex P2 / FR-025): `unadopted_panes_present` and `blocked_queue_drain` are gated on `count > 0 OR <id> is not None` (not `count` alone), and substitute `{N} = count if count > 0 else 1`. So at the reachable best-effort boundary where the count lookup degraded to `0` but the id query still returned a value (FR-025), the code still fires and `{N}` is floored to `1` — the wire prose never reads `"0 pane(s)"` / `"0 queue row(s)"`.

**`target.id` opacity** (FR-011, Clarifications R1 Q14): `target.id` values are opaque internal identifiers in FEAT-003 / FEAT-004 / FEAT-006 / FEAT-008 / FEAT-009 / FEAT-010 internal-id format (whichever corresponds to `target.kind`), or — for `target.kind == "subsystem"` — one of the FEAT-011 readiness probe names per Research §SS. They MUST NOT carry operator-readable display names, host metadata, paths, credentials, or PII. Clients render `target.id` opaquely or resolve it to a display name via separate `app.<entity>.detail` calls.

For `target.kind == "pane"` specifically, FEAT-004 exposes no opaque scalar pane id — pane identity is a 6-column composite PK that includes `tmux_socket_path` (a path) and `tmux_session_name` (operator free text), both of which FR-024 forbids on the wire. v1.1 therefore emits the pane's `tmux_pane_id` (`%N`) as `target.id`: it satisfies the opacity floor (no path/PII) but is **not** globally unique (a reused `%N` in a different session/window is a distinct pane per FEAT-004 FR-007), so it is best-effort-resolvable only. Minting a stable, unique, opaque pane surrogate over the FEAT-004 composite key — and a corresponding `app.pane.detail` resolution path — is deferred to a future minor; until then clients SHOULD treat a `pane` `target.id` as a hint, not a guaranteed-resolvable handle. (For `kind == "subsystem"` there is no `app.<entity>.detail` method; the probe-name `target.id` is the human-facing label and is rendered as-is.)

---

## Entity: `RecentlySkippedRoutesWindow`

**Purpose**: Process-local sliding-window count of recent FEAT-010 route-skip decisions, surfaced as `counts.routes.recently_skipped_count` with `counts.routes.recently_skipped_window_ms`.

**Storage**: in-memory `collections.deque(maxlen=10_000)` of monotonic-millisecond integers, owned by `src/agenttower/routing/skip_counter.py` (Research §RB).

**Lifecycle**:

- Insert: FEAT-010 routing worker calls `skip_counter.record_skip(now_ms)` synchronously on each skip decision.
- Read: `app_contract/dashboard.py` calls `skip_counter.count_in_window(now_ms)` once per `app.dashboard` request.
- Eviction: drop-oldest on insert when `maxlen` reached; expired entries (older than `window_ms`) are filtered out at read time (no background sweeper).
- Reset: cleared implicitly on daemon process exit; no explicit reset path (FR-008, Clarifications Q7).

**Constants** (Python module-level, CONSTANT_CASE per language convention; corrected per analyze M-CONST-CASE):

- `WINDOW_MS: Final[int] = 300_000` (5 minutes; Clarifications Q6 — fixed daemon-side, not client-tunable in v1.1). The wire field stays lowercase `recently_skipped_window_ms` per FR-007; only the Python module identifier is CONSTANT_CASE.
- `MAXLEN: Final[int] = 10_000` (Research §RB — bounded memory, ~400 KB worst case: 10_000 distinct large-int millisecond timestamps at ~32 B each + the deque block array). Sourced into `collections.deque(maxlen=MAXLEN)` at construction.

**Invariants** (FR-008):

- `count_in_window(now_ms)` returns a non-negative integer.
- Restart of the daemon process makes the first post-restart read return `0` (no persistence — Clarifications Q7).
- Skip events are counted iff `now_ms - 300_000 < entry_ms <= now_ms` (half-open interval `(now_ms - WINDOW_MS, now_ms]`). An entry at exactly the lower edge (`entry_ms == now_ms - 300_000`) is *not* counted (strict `>`, not `>=`); an entry recorded "in the future" relative to the read's independently sampled `now_ms` (a concurrent `record_skip` on the routing-worker thread) is also excluded by the `<= now_ms` upper clamp (Research §CW).

---

## Entity: `AppContractVersion` (v1.1)

**Wire surface**: extends FEAT-011's existing `app.hello` response and the `app_contract_version` envelope stamp.

| Field | v1.0 value | v1.1 value |
|---|---|---|
| `daemon_app_contract_version` | `"1.0"` | `"1.1"` |
| `supported_minor_range.max` (per FEAT-011 §versioning; nested `{min, max}` object of version **strings**) | `"1.0"` | `"1.1"` |
| `capability_flags` | `{}` | `{}` (unchanged — FR-015) |

A v1.1 daemon advertises `"1.1"` and emits the v1.1 additive fields on every `app.dashboard` response regardless of the calling client's `client_app_contract_major` (Clarifications Q10, FR-013).

---

## Derived Aggregations (read-time, per-call)

All aggregations below are computed once per `app.dashboard` request from the FEAT-003/004/006/007/010 service-layer accessors. No caching.

| Aggregation | Source | Output field |
|---|---|---|
| Pane-state buckets | Same row set as v1.0 panes counts, partitioned per `PaneState` priority rules | `counts.panes.by_state.{key}` × 4 |
| Agent-state buckets | FEAT-006 agent rows joined with FEAT-003 container state and FEAT-007 log-attachment state | `counts.agents.by_state.{key}` × 5 |
| Recently-skipped count | `skip_counter.count_in_window(now_ms)` | `counts.routes.recently_skipped_count`, `counts.routes.recently_skipped_window_ms` |
| Recommendation | `recommendations.compute_recommendation(state)` (Research §CO) | `recommended_next_action`, `recommended_next_action_refreshed_at` |
