# Data Model Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for the entities, closed sets, and aggregation rules introduced by v1.1.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Entity Definitions

- [X] CHK001 - Is each entity (`PaneState`, `AgentState`, `RecommendedNextAction`, `RecentlySkippedRoutesWindow`, `AppContractVersion`) defined with attributes, value type, and intended consumer? [Completeness, Spec §Key Entities]
- [X] CHK002 - Is the relationship between `PaneState` and the v1.0 panes count fields (`total`, `registered`, `unregistered`) explicitly stated as a derived view, not a parallel source of truth? [Clarity, Spec §FR-019]
- [X] CHK003 - Is the relationship between `AgentState` and `partially_configured` stated such that membership rules are unambiguous? [Clarity, Spec §FR-020]

## Closed-Set Discipline

- [X] CHK004 - Are all `PaneState` keys exhaustively listed and identical in FR-002, FR-019, Clarifications Q1, and US1 acceptance scenarios? [Consistency, Spec §FR-002, §FR-019, §Clarifications Q1]
- [X] CHK005 - Are all `AgentState` keys exhaustively listed and identical in FR-005, FR-020, and Clarifications Q2/Q3/Q5? [Consistency, Spec §FR-005, §FR-020]
- [X] CHK006 - Are the seven `recommended_next_action.code` values listed in the same canonical order in FR-010 and the Clarifications precedence note? [Consistency, Spec §FR-010, §Clarifications]
- [X] CHK007 - Are the `target.kind` closed-set values stated in one canonical location and merely referenced elsewhere, to prevent drift? [Consistency, Spec §FR-011]

## Aggregation & Cross-Field Rules

- [X] CHK008 - Is the panes cross-check stated as three discrete invariants (the `dar ≤ registered` and `dau+ios+dd ≥ unregistered` one-sided checks plus the strict four-bucket total-sum equality), each independently testable rather than a single compound rule? [Measurability, Spec §FR-019]
- [X] CHK009 - Is the agent partition rule stated such that an implementation choosing the wrong bucket would be caught by a fixture sum check? [Measurability, Spec §FR-020]
- [X] CHK010 - Are the conditions for `inactive-or-stale` ("container `inactive` OR `last_seen_at` predates most recent successful scan") clearly OR-joined, not AND? [Clarity, Spec §Clarifications Q1]
- [X] CHK011 - Is the priority rule defined when a pane qualifies for multiple buckets simultaneously (e.g., container is both `inactive` AND in `degraded_scan`)? [Gap, Spec §Clarifications Q1, §FR-002]
- [ ] CHK011a - Is the aggregator-failure value of each `by_state` bucket documented as an invariant (every key emits `0`, no error code, no null, recommendation = `subsystem_degraded`, counts not suppressed) so a fixture can assert the failure shape, per FR-025/FR-026? [Measurability, Spec §FR-025, §FR-026, Data Model §Derived Aggregations]

## Lifecycle & State Transitions

- [x] CHK012 - Are transitions between `PaneState` values described, or explicitly declared out of scope since this is a read-side derived view? [Coverage, Gap] [EDIT-applied: data-model.md §PaneState now has a Lifecycle "derived view, no transitions" statement]
- [x] CHK013 - Are transitions between `AgentState` values described, or explicitly declared derived purely from container state plus configuration completeness? [Coverage, Spec §FR-020] [EDIT-applied: data-model.md §AgentState now has a Lifecycle "derived view, no transitions" statement]
- [X] CHK014 - Is the lifecycle of `RecentlySkippedRoutesWindow` (insertion on FEAT-010 skip, expiration at window edge, reset on restart, AND last-known-state retention when the routing worker is stalled/crashed with `subsystem_degraded` emitted separately) described with matching precision? [Completeness, Spec §FR-008]
- [X] CHK015 - Is the lifecycle of `RecommendedNextAction` (recomputed per call, never persisted) stated such that a future "persisted history" requirement would clearly be out of scope? [Clarity, Spec §FR-018, §Clarifications Q8]

## Identity & Uniqueness

- [X] CHK016 - Is `target.id` uniqueness defined per `target.kind` (container id format, pane id format, agent id format, subsystem identifier format)? [Gap, Spec §FR-011]

## Volume & Scale Assumptions

- [X] CHK017 - Are there stated bounds on the number of panes, agents, or recent skip events the dashboard must handle without violating SC-006? [Gap, Spec §SC-006]
- [X] CHK018 - Is the in-memory ring-buffer max length for FEAT-010 skip events specified as a fixed bounded-memory cap (`MAXLEN = 10_000`, independent of the 300_000 ms window) with a stated worst-case memory bound? [Gap, Spec §FR-008, Data Model §RecentlySkippedRoutesWindow, Research §RB]

## Out-of-Scope Boundaries

- [X] CHK019 - Is "no persisted recommendation history" stated in both FR-018 and in the entity description so it cannot be re-introduced quietly? [Consistency, Spec §FR-018, §Key Entities]
- [X] CHK020 - Is "telemetry, not durable audit history" stated unambiguously for `RecentlySkippedRoutesWindow`? [Clarity, Spec §Clarifications, §Assumptions]

## Plan & Design Alignment (re-verify 2026-05-24)

- [X] CHK021 - Does data-model.md's entity list match the spec's §Key Entities list (no entity present in one but missing in the other)? [Consistency, Data Model, Spec §Key Entities]
- [X] CHK022 - Does data-model.md §PaneState's bucket-assignment priority match Research §PB verbatim? [Consistency, Data Model §PaneState, Research §PB]
- [X] CHK023 - Does data-model.md spell each invariant (FR-019 equalities, FR-020 partition, FR-006 orthogonality) in a form a unit test can convert to an assertion without interpretation? [Measurability, Data Model §Invariants]
- [X] CHK024 - Is the AgentState orthogonality note (log-state may overlap configuration state) stated identically in data-model.md §AgentState and dashboard-v1_1.md? [Consistency, Data Model §AgentState, Contracts dashboard-v1_1.md]
- [X] CHK025 - Does data-model.md §RecentlySkippedRoutesWindow name the constants `WINDOW_MS = 300_000` and `MAXLEN = 10_000` exactly (CONSTANT_CASE per M-CONST-CASE; not just descriptive phrases)? [Clarity, Data Model §RecentlySkippedRoutesWindow, Research §RB]
- [X] CHK026 - Does data-model.md's lifecycle section for each entity match the module-level lifecycle described in plan.md? [Consistency, Data Model §Lifecycle, Plan §Source Code]
- [X] CHK027 - Is the v1.1 emission rule ("daemon advertises 1.1 → emit fields regardless of client major") stated in data-model.md §AppContractVersion in the same words as Spec Clarifications Q10? [Consistency, Data Model §AppContractVersion, Spec §Clarifications Q10]

## Post-Remediation Audit (commit 457d5c2)

- [X] CHK028 - Does the bucket-priority chain now stated inline in FR-002 (`discovery-degraded` > `inactive-or-stale` > `discovered-and-registered` > `discovered-and-unmanaged`) match data-model.md §PaneState verbatim, with no character difference? [Consistency, Spec §FR-002, Data Model §PaneState]
- [X] CHK029 - Did the I1 rename (`RecentlySkippedRoutes Window` → `RecentlySkippedRoutesWindow`) propagate to every section that references the entity by name across data-model.md, dashboard-v1_1.md, plan.md, research.md? [Consistency, Data Model §RecentlySkippedRoutesWindow]
