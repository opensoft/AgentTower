# Data Model Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for the entities, closed sets, and aggregation rules introduced by v1.1.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Entity Definitions

- [ ] CHK001 - Is each entity (`PaneState`, `AgentState`, `RecommendedNextAction`, `RecentlySkippedRoutes Window`, `App Contract Version`) defined with attributes, value type, and intended consumer? [Completeness, Spec §Key Entities]
- [ ] CHK002 - Is the relationship between `PaneState` and the v1.0 panes count fields (`total`, `registered`, `unregistered`) explicitly stated as a derived view, not a parallel source of truth? [Clarity, Spec §FR-019]
- [ ] CHK003 - Is the relationship between `AgentState` and `partially_configured` stated such that membership rules are unambiguous? [Clarity, Spec §FR-020]

## Closed-Set Discipline

- [ ] CHK004 - Are all `PaneState` keys exhaustively listed and identical in FR-002, FR-019, Clarifications Q1, and US1 acceptance scenarios? [Consistency, Spec §FR-002, §FR-019, §Clarifications Q1]
- [ ] CHK005 - Are all `AgentState` keys exhaustively listed and identical in FR-005, FR-020, and Clarifications Q2/Q3/Q5? [Consistency, Spec §FR-005, §FR-020]
- [ ] CHK006 - Are the seven `recommended_next_action.code` values listed in the same canonical order in FR-010 and the Clarifications precedence note? [Consistency, Spec §FR-010, §Clarifications]
- [ ] CHK007 - Are the `target.kind` closed-set values stated in one canonical location and merely referenced elsewhere, to prevent drift? [Consistency, Spec §FR-011]

## Aggregation & Cross-Field Rules

- [ ] CHK008 - Is the panes cross-check stated as three discrete equalities (each independently testable) rather than a single compound rule? [Measurability, Spec §FR-019]
- [ ] CHK009 - Is the agent partition rule stated such that an implementation choosing the wrong bucket would be caught by a fixture sum check? [Measurability, Spec §FR-020]
- [ ] CHK010 - Are the conditions for `inactive-or-stale` ("container `inactive` OR `last_seen_at` predates most recent successful scan") clearly OR-joined, not AND? [Clarity, Spec §Clarifications Q1]
- [ ] CHK011 - Is the priority rule defined when a pane qualifies for multiple buckets simultaneously (e.g., container is both `inactive` AND in `degraded_scan`)? [Gap, Spec §Clarifications Q1, §FR-002]

## Lifecycle & State Transitions

- [ ] CHK012 - Are transitions between `PaneState` values described, or explicitly declared out of scope since this is a read-side derived view? [Coverage, Gap]
- [ ] CHK013 - Are transitions between `AgentState` values described, or explicitly declared derived purely from container state plus configuration completeness? [Coverage, Spec §FR-020]
- [ ] CHK014 - Is the lifecycle of `RecentlySkippedRoutes Window` (insertion on FEAT-010 skip, expiration at window edge, reset on restart) described with matching precision? [Completeness, Spec §FR-008]
- [ ] CHK015 - Is the lifecycle of `RecommendedNextAction` (recomputed per call, never persisted) stated such that a future "persisted history" requirement would clearly be out of scope? [Clarity, Spec §FR-018, §Clarifications Q8]

## Identity & Uniqueness

- [ ] CHK016 - Is `target.id` uniqueness defined per `target.kind` (container id format, pane id format, agent id format, subsystem identifier format)? [Gap, Spec §FR-011]

## Volume & Scale Assumptions

- [ ] CHK017 - Are there stated bounds on the number of panes, agents, or recent skip events the dashboard must handle without violating SC-006? [Gap, Spec §SC-006]
- [ ] CHK018 - Is the in-memory ring buffer size for FEAT-010 skip events specified (worst-case skips/second × 300_000 ms)? [Gap, Spec §FR-008]

## Out-of-Scope Boundaries

- [ ] CHK019 - Is "no persisted recommendation history" stated in both FR-018 and in the entity description so it cannot be re-introduced quietly? [Consistency, Spec §FR-018, §Key Entities]
- [ ] CHK020 - Is "telemetry, not durable audit history" stated unambiguously for `RecentlySkippedRoutes Window`? [Clarity, Spec §Clarifications, §Assumptions]

## Plan & Design Alignment (re-verify 2026-05-24)

- [ ] CHK021 - Does data-model.md's entity list match the spec's §Key Entities list (no entity present in one but missing in the other)? [Consistency, Data Model, Spec §Key Entities]
- [ ] CHK022 - Does data-model.md §PaneState's bucket-assignment priority match Research §PB verbatim? [Consistency, Data Model §PaneState, Research §PB]
- [ ] CHK023 - Does data-model.md spell each invariant (FR-019 equalities, FR-020 partition, FR-006 orthogonality) in a form a unit test can convert to an assertion without interpretation? [Measurability, Data Model §Invariants]
- [ ] CHK024 - Is the AgentState orthogonality note (log-state may overlap configuration state) stated identically in data-model.md §AgentState and dashboard-v1_1.md? [Consistency, Data Model §AgentState, Contracts dashboard-v1_1.md]
- [ ] CHK025 - Does data-model.md §RecentlySkippedRoutesWindow name the constants `window_ms = 300_000` and `maxlen = 10_000` exactly (not just descriptive phrases)? [Clarity, Data Model §RecentlySkippedRoutesWindow, Research §RB]
- [ ] CHK026 - Does data-model.md's lifecycle section for each entity match the module-level lifecycle described in plan.md? [Consistency, Data Model §Lifecycle, Plan §Source Code]
- [ ] CHK027 - Is the v1.1 emission rule ("daemon advertises 1.1 → emit fields regardless of client major") stated in data-model.md §AppContractVersion in the same words as Spec Clarifications Q10? [Consistency, Data Model §AppContractVersion, Spec §Clarifications Q10]
