# Implementation Plan: App Dashboard Extensions (v1.1)

**Branch**: `014-app-dashboard-extensions` | **Date**: 2026-05-24 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/014-app-dashboard-extensions/spec.md`

## Summary

FEAT-014 extends the FEAT-011 `app.dashboard` method as an **additive v1.1 minor** so the FEAT-012 desktop control panel can render pane state, agent state, route-skip friction, and a recommended next operator action against a real daemon.

The work splits into **three thin additive layers** inside the existing `src/agenttower/app_contract/` sub-package, plus one small helper in `src/agenttower/routing/`:

1. **State-bucket aggregators** in `app_contract/dashboard.py` — derive `counts.panes.by_state` (4-key `PaneState`) and `counts.agents.by_state` (5-key `AgentState`) from the same daemon-state rows that already back the v1.0 `counts.panes.{total,registered,unregistered}` fields, alongside the existing v1.0 `_pane_counts` / `_agent_counts` helpers. Bucket assignment uses the FEAT-004/011 semantics fixed by Clarifications Q1–Q3 (no new heuristics). The aggregators satisfy the cross-check invariants in FR-019 (post-R3) by construction (same row set, partitioned). (`view_models.py` is intentionally NOT used — that module is pure entity-row projection with no DB I/O; aggregators live alongside the v1.0 count helpers per analyze D-DRIFT-1 correction.)
2. **Route-skip telemetry** in a new module `src/agenttower/routing/skip_counter.py` — process-local ring buffer of FEAT-010 skip events (timestamped on insertion), with a fixed `300_000` ms sliding window (FR-008, Clarifications Q6). Populated by the FEAT-010 routing worker on each skip decision; read by `dashboard.py` per call. Cleared on daemon process exit (no persistence — Clarifications Q7).
3. **Recommendation engine** in a new module `src/agenttower/app_contract/recommendations.py` — a pure function over current daemon state that walks the fixed deterministic precedence list `subsystem_degraded → no_containers → no_panes_discovered → unadopted_panes_present → blocked_queue_drain → no_routes_configured → all_clear` and returns the first matching `RecommendedNextAction` (FR-010, Clarifications precedence note). Recomputed on every `app.dashboard` call (Clarifications Q8); no cache. Compute failure inside this module is caught at the dashboard boundary and surfaced as `recommended_next_action: null` with `recommended_next_action_refreshed_at: null` while the rest of the v1.1 payload still succeeds (FR-021).

Wiring:

- `app_contract/dashboard.py` (modified) — calls the three new helpers, assembles the additive v1.1 fields into the existing `app.dashboard` success envelope, and applies the FR-021 fallback wrapper around the recommendation call.
- `app_contract/versioning.py` (modified) — bumps the advertised contract version from `"1.0"` to `"1.1"` and widens the supported minor range maximum to include `1.1`. `capability_flags` remains `{}` (FR-015).
- No new SQLite table. No JSONL schema change. No new error code. No new closed-set value that wasn't already enumerated in the spec.

The legacy v1.0 fields on `app.dashboard` (`counts.panes.{total,registered,unregistered}`, `recents`, `hints[]`) remain bit-identical (FR-014). v1.0 clients ignore the new fields per FEAT-011's additive-minor rule (Clarifications Q10).

## Technical Context

**Language/Version**: Python 3.11+ (inherited from FEAT-011 daemon).
**Primary Dependencies**: existing daemon services — FEAT-003 (container discovery, container state vocabulary `active`/`inactive`/`degraded_scan`), FEAT-004 (pane discovery, `last_seen_at` semantics, scan success signal), FEAT-006 (agent registration, `role`/`capability`/`label` attributes used by `partially_configured` per Clarifications Q2), FEAT-007 (log attachment state — `log-attached`/`log-detached`), FEAT-010 (routing worker emits skip-decision events), FEAT-011 (`app.dashboard` method, dispatcher, host-only gate, envelope builder, contract version handshake). No new third-party Python dependencies.
**Storage**: In-memory only.
- New: route-skip ring buffer (process-local, cleared on daemon exit — see Research §RB).
- No new SQLite migration. No JSONL schema bump. No persisted recommendation history (FR-018).
- All other fields are derived per call from current FEAT-003/004/006/007/010 state.

**Testing**: pytest, same layout as FEAT-011 (`tests/integration/`, `tests/unit/`). FEAT-011's `app.dashboard` contract assertions live in `tests/unit/test_app_dashboard.py` (no `tests/contract/` directory in this repo); FEAT-014 follows that convention.
- Extend `tests/unit/test_app_dashboard.py` for the v1.1 fields, FR-019 cross-check invariants (post-R3 one-sided), FR-020 agent partition, FR-021 compute-failure null fallback, and the v1.0 envelope shape regression.
- Add `tests/unit/test_app_versioning.py` for the `1.0 → 1.1` advertisement bump and the "v1.1 daemon emits new fields to a v1.0 client" assertion (Clarifications Q10, FR-013).
- New `tests/unit/test_recommendations.py` — fixture states for all seven codes, adjacent-pair precedence (SC-003 (b)), compute-failure isolation (FR-021).
- New `tests/unit/test_skip_counter.py` — boundary arithmetic at `300_000` ms (FR-008), restart-resets-to-zero (US2 acceptance #3), ring-buffer overflow drop-oldest.
- Extend `tests/integration/test_story1_dashboard_bootstrap.py` for SC-002 (cold-start-to-dashboard ≤ 500 ms still holds with v1.1 fields) and SC-006 (no new I/O surface).

**Target Platform**: Linux primary; macOS/Windows host targets follow per FEAT-011 Assumptions. Daemon is host-side Python; client is out of scope (FEAT-012 territory).
**Project Type**: CLI daemon + structured-API façade — additive minor extension to an existing method (no new method, no new namespace).
**Performance Goals**: FEAT-011 dashboard latency budget (SC-002 cold-start-to-dashboard ≤ 500 ms; warm dashboard < 100 ms target) MUST still hold with the four new aggregations and the recommendation call. Per the cost model in Research §CO, expected additive cost is < 5 ms at the FEAT-011 fixture scale.
**Constraints**: Local-only (inherited FR-003 of FEAT-011 — no network listener). Host-only (inherited FR-042 — bench-container peers rejected). Additive-minor (FR-013/FR-014 — no v1.0 field removed, renamed, or retyped). No new capability flag (FR-015). No new error code (FR-021 surfaces compute failure as nulls inside a success envelope, not via a new error code). No new persisted state. No new background worker (the route-skip ring buffer is populated synchronously by the existing FEAT-010 routing worker on each skip decision).
**Scale/Scope**: Same fixture scale as FEAT-011 — ≤ 10 bench containers, ≤ 200 agents, ≤ 1k events / day, ≤ 100 routes, typical workstation. Ring buffer worst case `max_skips_per_second × 300_000 ms`; bounded with a hard cap per Research §RB.

## Constitution Check

*Gate: must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|---|---|---|
| **I. Local-First Host Control** | ✅ PASS | No new listener; the additive fields ride the existing host-only Unix-socket `app.dashboard` request path. No durable state outside the existing FEAT-001..010 stores. |
| **II. Container-First MVP** | ✅ PASS (with note) | FEAT-014 is post-MVP per the FEAT-012 dependency chain. Bucket vocabularies (`PaneState`, `AgentState`) describe state *of bench containers and the panes/agents inside them* — same MVP target. No host-only-tmux or Antigravity work introduced. |
| **III. Safe Terminal Input** | ✅ PASS | `app.dashboard` is read-only, side-effect-free (CHK010 in `api.md`). No new send-input path. Recommendation codes are advisory; the daemon does not auto-execute them. |
| **IV. Observable and Scriptable** | ✅ PASS | The feature *is* the observability surface improvement. CLI `agenttower dashboard` consumers gain the same v1.1 fields (the CLI uses the same service-layer aggregator helpers — same source-of-truth row set). No log-scraping introduced. |
| **V. Conservative Automation** | ✅ PASS | The recommendation is a *named code with operator-facing prose*, not an auto-action. FR-018 keeps customizable recommendation rules out of scope. Per Clarifications Q11, on compute failure both recommendation fields are `null` — daemon never invents a fallback recommendation. |

**Post-design re-check** (after Phase 1 below): unchanged — all gates remain green. No complexity-tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/014-app-dashboard-extensions/
├── plan.md              # This file
├── spec.md              # Feature specification (Clarifications §Session 2026-05-24, 12 Q/A + 5 notes)
├── research.md          # Phase 0 — open-question resolutions surfaced by checklist audit
├── data-model.md        # Phase 1 — entities, closed sets, aggregation rules
├── contracts/
│   ├── dashboard-v1_1.md   # Wire-level shape for the v1.1 additions on app.dashboard
│   └── closed-sets-v1_1.md # PaneState, AgentState, recommendation codes, target.kind v1.1 addition
├── quickstart.md        # Synthetic-client walkthrough exercising the v1.1 fields
├── checklists/          # 11 domain checklists (from /speckit.checklist max-coverage re-verify)
└── tasks.md             # Phase 2 — created by /speckit.tasks, NOT by this command
```

### Source Code (repository root)

FEAT-014 reuses the existing `src/agenttower/app_contract/` sub-package (created by FEAT-011) and adds **two new modules** plus **two existing-module edits**. No existing module is renamed, deleted, or rewired.

```text
src/agenttower/app_contract/
├── dashboard.py            # MODIFIED — adds two new private aggregators
│                           #   (_compute_pane_state_buckets, _compute_agent_state_buckets)
│                           #   alongside the existing v1.0 _pane_counts / _agent_counts
│                           #   helpers; reuses the same SQLite row-source the v1.0 counts
│                           #   use so FR-019's one-sided invariants (post-R3) hold by
│                           #   construction. Assembles v1.1 additive fields onto the
│                           #   existing success envelope; in US3 (T020) will also apply
│                           #   the FR-021 try/except fallback around the recommendation
│                           #   call to keep compute failure from propagating to the other
│                           #   v1.1 fields. (view_models.py is intentionally NOT modified
│                           #   — that module is for entity row projection, not count
│                           #   aggregation; correction per analyze D-DRIFT-1.)
├── recommendations.py      # NEW — pure function `compute_recommendation(state) ->
│                           #   RecommendedNextAction`. Exposes a 4-symbol public
│                           #   surface (post analyze M-T019-API): the
│                           #   `RecommendationState` input dataclass, the
│                           #   `RecommendedNextAction` output dataclass, the
│                           #   `PROBE_ORDER` module constant (alias for
│                           #   versioning.SUBSYSTEM_NAMES), and the function itself.
│                           #   Walks the 7-code precedence list top-to-bottom; returns
│                           #   the first match (never None — `all_clear` is the floor).
│                           #   No cache, no side effects, no I/O. Raises only on
│                           #   programmer error (TypeError / KeyError) — those are
│                           #   caught at the dashboard boundary (T020) and surfaced as
│                           #   null per FR-021.
└── versioning.py           # MODIFIED — advertised contract version 1.0 → 1.1; supported
                            #   minor range maximum widened to include 1.1; capability_flags
                            #   remains {} per FR-015.

src/agenttower/routing/
└── skip_counter.py         # NEW — process-local sliding-window ring buffer of FEAT-010
                            #   skip decisions. Public surface:
                            #     record_skip(now_ms: int) -> None  (called by routing worker)
                            #     count_in_window(now_ms: int) -> int  (called by dashboard.py)
                            #     window_ms: int  (constant = 300_000)
                            #   Cleared implicitly on daemon process exit.

tests/unit/
├── test_app_dashboard.py        # EXTENDED — v1.1 field presence, FR-019 cross-check
│                                #   (post-R3 one-sided), FR-020 agent partition,
│                                #   FR-021 null-on-compute-failure, v1.0 envelope-shape
│                                #   regression. (Same file FEAT-011 ships dashboard
│                                #   contract assertions in; no separate tests/contract/
│                                #   in this repo — correction per analyze D-DRIFT-2.)
├── test_app_versioning.py       # NEW — 1.0 → 1.1 advertised; v1.0 client receives
│                                #   v1.1 fields and ignores them (US4 acceptance #1).
├── test_recommendations.py      # NEW — fixture states for all 7 codes; SC-003 (a) degraded
│                                #   precedence; SC-003 (b) adjacent-pair (no_containers
│                                #   beating no_panes_discovered) to demonstrate first-match,
│                                #   not just top-of-list; programmer-error path raises
│                                #   but doesn't reach the wire.
├── test_skip_counter.py         # NEW — boundary at 300_000 ms (in / out / exactly at edge),
│                                #   restart-resets-to-zero (US2 acceptance #3),
│                                #   drop-oldest on overflow.
├── test_pane_state_buckets.py   # NEW — bucket assignment per Clarifications Q1; priority
│                                #   when a pane qualifies for multiple buckets (data-model §PS).
└── test_agent_state_buckets.py  # NEW — partition rule per FR-020; orthogonality of
                                 #   log-attached/log-detached per FR-006.

tests/integration/
└── test_story1_dashboard_bootstrap.py  # EXTENDED — SC-002 latency still ≤ 500 ms with
                                        #   v1.1 fields; SC-006 no new I/O surface; one
                                        #   end-to-end fixture per User Story acceptance #1
                                        #   (US1, US2, US3 first scenario).
```

**Test file naming note**: The `test_story1_dashboard_bootstrap.py` filename is preserved from FEAT-011 for continuity with that feature's per-story test convention. Under FEAT-014 the file houses one end-to-end acceptance scenario per user story (US1, US2, US3) plus the cross-cutting SC-002 latency and SC-006 no-new-I/O assertions — i.e., the "story1" in the filename refers to FEAT-011's Story 1 (the dashboard-bootstrap journey), not to FEAT-014's US1. A future feature minor may rename to `test_acceptance_scenarios.py` once FEAT-011's per-story pattern diverges further; for now the rename would cascade through multiple speckit task references and is deferred.

**Structure Decision**: Reuse FEAT-011's `app_contract/` sub-package; add two narrowly-scoped modules and edit two existing modules. The route-skip ring buffer lives under `routing/` (FEAT-010's home) rather than under `app_contract/` because its writer is the routing worker and its lifecycle is process-wide, not request-scoped — it just happens to be *read* by the dashboard. This placement keeps `app_contract/` purely a façade over service-layer state and avoids inversion (the dashboard shouldn't be the canonical home of a routing-layer counter).

## Complexity Tracking

No constitution violations; this table is intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| _(none)_  | —          | —                                   |
