# Specification Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Initial validation passed for `/speckit.clarify` and `/speckit.plan`.

---

## Cross-Cutting Requirements Quality (Session 2026-05-24, Deep & Wide)

**Purpose**: Cross-cutting requirements-quality unit tests across completeness, clarity, consistency, acceptance criteria, dependencies/assumptions, and ambiguities/conflicts. Each item tests the spec's wording, not the implementation.

### Completeness

- [ ] CHK001 Are all functional requirements (FR-001 through FR-021) traceable to at least one user story or success criterion? [Completeness, Traceability]
- [ ] CHK002 Are all success criteria (SC-001 through SC-008) traceable to at least one functional requirement? [Traceability]
- [ ] CHK003 Are all Key Entities cross-referenced by at least one functional requirement? [Completeness]
- [ ] CHK004 Are the "standard templates" (FR-001) defined with full template schema (pane count, role per pane, label pattern, expected commands)? [Completeness, Gap, Spec §FR-001]
- [ ] CHK005 Are all attributes of each Key Entity enumerated, including required-vs-optional markers? [Completeness, Spec §Key Entities]
- [ ] CHK006 Is the lifecycle state transition graph fully enumerated (every valid transition from every state, not only the states themselves)? [Completeness, Gap, Spec §FR-007]
- [ ] CHK007 Are dependencies on FEAT-011 enumerated with specific contract surfaces (which endpoints, which event types)? [Completeness, Spec §Assumptions]
- [ ] CHK008 Are dependencies on FEAT-012 enumerated with specific UI affordances required? [Completeness, Spec §Assumptions]
- [ ] CHK009 Are dependencies on FEAT-003/004/006/007/008/009/010 enumerated where this feature reuses their surfaces (FR-004, FR-006, FR-008, FR-015)? [Completeness, Gap]
- [ ] CHK010 Are out-of-scope items in FR-018 enumerated exhaustively for FEAT-013? [Completeness]

### Clarity

- [ ] CHK011 Is the term "managed-created" used consistently and not interchangeably with "managed" or "AgentTower-created"? [Clarity, Consistency]
- [ ] CHK012 Is "pending-managed marker" defined with its lifecycle (when set, when cleared, where stored)? [Clarity, Gap, Spec §FR-014]
- [ ] CHK013 Is "fresh identity" (US3 AS-2) quantified — does it mean a new UUID, a new label, or both? [Clarity, Spec §FR-011]
- [ ] CHK014 Is "actionable diagnostic" (FR-016) quantified with required diagnostic fields? [Clarity, Ambiguity, Spec §FR-016]
- [ ] CHK015 Is "host-readable pane logs" (FR-006) defined with explicit conditions for what counts as host-readable? [Clarity, Spec §FR-006]
- [ ] CHK016 Is the boundary between "layout creation" and "pane creation" lifecycle states unambiguous (when does a layout transition from `creating` to `ready`)? [Clarity, Gap]
- [ ] CHK017 Are layout-level lifecycle states distinct from pane-level lifecycle states, or are they intentionally the same set? [Clarity, Gap, Spec §FR-007]
- [ ] CHK018 Is the term "operator" defined (e.g., who has socket access) or assumed to be self-evident? [Clarity, Gap]

### Consistency

- [ ] CHK019 Does FR-007's state list (`creating, ready, degraded, failed, removed`) match exactly the Key Entities Managed Pane state list? [Consistency]
- [ ] CHK020 Is every clarification recorded under "Session 2026-05-24" reflected in at least one downstream FR, SC, or Edge Case? [Consistency]
- [ ] CHK021 Are all edge cases listed in the Edge Cases section mapped to specific FRs that govern their resolution? [Consistency, Traceability]
- [ ] CHK022 Are there any conflicts between Clarifications answers and pre-existing FRs that the spec hasn't reconciled? [Conflict]
- [ ] CHK023 Is the spec's User Story numbering (US1/US2/US3) used consistently across Edge Cases and FRs? [Consistency]
- [ ] CHK024 Is the spec free of [NEEDS CLARIFICATION] markers or unresolved decisions? [Completeness]

### Acceptance Criteria Quality

- [ ] CHK025 Are SC-001's "under 2 minutes" and SC-003's "10 seconds" thresholds justified (why those values)? [Acceptance Criteria]
- [ ] CHK026 Is each SC objectively measurable without requiring implementation inspection? [Measurability]
- [ ] CHK027 Are the acceptance scenarios in US1/US2/US3 testable without requiring multi-host setup? [Measurability]
- [ ] CHK028 Are SC-006's "specific failed stage and recovery action visible to the operator" criteria measurable (which fields, which surface)? [Measurability, Spec §SC-006]

### Dependencies & Assumptions

- [ ] CHK029 Is the assumption "MVP authorization is socket-access based" testable as a negative requirement (no UID check, no per-container ACL)? [Measurability, Spec §Assumptions]
- [ ] CHK030 Is the assumption "each template declares its own pane count" backed by a corresponding FR or referenced template schema? [Dependency, Gap, Spec §Assumptions]
- [ ] CHK031 Is the dependency on durable storage (FR-020) listed in the Assumptions section as well as the FR? [Consistency, Dependency, Spec §FR-020]
- [ ] CHK032 Are the failure modes for tmux operations (kill-pane, create-pane, send-keys) enumerated and matched to lifecycle state transitions? [Coverage, Gap]

### Ambiguities & Conflicts

- [ ] CHK033 Is the predecessor_id field's behavior under multiple successive recreations (predecessor of predecessor) specified? [Coverage, Gap, Spec §FR-011]
- [ ] CHK034 Does the spec specify what happens if a recreated pane itself fails immediately — bounded recreate-chain depth, or unbounded? [Coverage, Gap]
- [ ] CHK035 Is the `promoted_from_adopted` reserved transition's eligible source-state set defined (which adopted-pane states are eligible)? [Gap, Spec §FR-007]
- [ ] CHK036 Are the relationships between layout-level state and pane-level state defined (e.g., a layout is `ready` iff all panes are `ready` or `degraded`)? [Gap]

---

## Cross-Cutting Post-Tasks Audit (Session 2026-05-24, after `/speckit.tasks`)

**Purpose**: Cross-cutting requirements-quality items that the post-tasks lens surfaces. Tasks.md now exists with 56 tasks (T001–T056); these items test the requirements-side completeness from the new vantage point.

- [ ] CHK037 Is every functional requirement FR-001..FR-024 reachable from at least one task in tasks.md (forward traceability)? [Traceability, Spec §FR vs Tasks]
- [ ] CHK038 Is every success criterion SC-001..SC-009 covered by either an explicit perf verification task or a test that asserts its bound? [Traceability, Spec §SC vs Tasks T054/T055/T056]
- [ ] CHK039 Are tasks-driven implementation footprints (sweep loop, recovery boot wiring, detail-surface fields) reflected back into the spec as testable acceptance shapes, or are they implementation-only? [Completeness, Spec §FR-022/FR-020/SC-009 vs Tasks]
- [ ] CHK040 Does the spec define what counts as an "operator-overridable" template/profile precisely enough for tasks.md to test the override resolution rule (FR-024)? [Clarity, Spec §FR-024 vs Tasks T008/T009/T017]
- [ ] CHK041 Is the spec's notion of "actionable diagnostic" (FR-013/FR-016) specified concretely enough that contract tests can assert the diagnostic content (code, message, hint fields)? [Measurability, Spec §FR-013/FR-016 vs Tasks T016/T036]
- [ ] CHK042 Does the spec's Edge Cases section list every concurrency / race / failure mode the task plan tests, or do tasks.md tests cover scenarios the spec hasn't named? [Consistency, Spec §Edge Cases vs Tasks T020/T051]
- [ ] CHK043 Is the launch-command profile schema specified clearly enough in spec.md/Assumptions/Research that the YAML loader test (in T009/T017) has unambiguous expectations? [Clarity, Spec §Assumptions vs Research §R9 vs Tasks T009]
- [ ] CHK044 Are the per-method idempotency semantics (FR-014; M1, M7) specified clearly enough for tests to assert "in-flight match" vs "completed match" vs "no key" branches independently? [Clarity, Spec §FR-014 vs Contracts §M1/M7 vs Tasks T016/T036]
- [x] CHK045 Does the spec carry enough detail about FEAT-011 `app.hello` capability_flags semantics to know whether `app.managed_*` needs to be declared there, or is the additive evolution rule sufficient? [Gap, Spec vs FEAT-011 contract] — **Resolved 2026-05-24**: same decision as tasks-readiness CHK048/CHK056 — `capability_flags` stays `{}`; the new `app.managed_*` methods are required FEAT-013 surfaces (not optional capabilities). Rationale in contracts/managed-methods.md §Versioning; tasks.md Notes forbids adding a `capability_flags` task.
- [ ] CHK046 Are user stories US1/US2/US3 acceptance scenarios specified at a level that maps 1:1 to integration tests in tasks.md (T021/T028/T041)? [Measurability, Spec §US vs Tasks]
- [ ] CHK047 Are tasks.md's existing-file modifications (T025/T031/T034/T047) covered by the spec only at the requirement level (FR-008 same-surfaces, FR-014 scan integration, FR-020 boot reconcile), or does the spec name the touched modules? [Consistency, Spec §FR vs Plan §Project Structure vs Tasks]
- [ ] CHK048 Does the spec specify whether the FR-022 TTL sweep itself is an operator-observable event, or is it daemon-internal only? [Clarity, Spec §FR-022 vs Contracts §Events]
- [ ] CHK049 Does spec.md make clear whether the SC-009 5-second visibility window includes the time to query the M3/M5 endpoint, or only the time for the daemon to populate the row? [Clarity, Spec §SC-009 vs Tasks T056]
- [ ] CHK050 Is the relationship between FR-014 pending-managed-marker idempotency (operation dedupe) and FR-019 per-container serialization (request ordering) explained clearly so tests can target each independently? [Clarity, Spec §FR-014 vs §FR-019 vs Tasks T019/T020]
- [ ] CHK051 Are all spec terms that have a code-level identifier (`predecessor_id`, `pending_marker_token`, `chain_depth`, `failed_stage`, `container_id`) introduced in spec.md before they're used in plan/data-model/contracts/tasks? [Consistency, Spec vs downstream]


