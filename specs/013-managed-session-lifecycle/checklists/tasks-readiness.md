# Tasks Readiness Checklist: Managed Session Creation and Lifecycle

**Purpose**: Release-gate audit of tasks.md against spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md, and the constitution. Tests *whether tasks.md is well-formed and complete* — not whether the implementation works.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md) + [tasks.md](../tasks.md)
**Depth**: release gate. **Audience**: feature author + reviewer before `/speckit.implement`.
**Scope note**: The 15 prior deep-and-wide checklists (ux/api/data-model/security/performance/accessibility/error-handling/observability/integration/configuration/idempotency/testing-strategy/deployment/concurrency/plan-review/alignment-check/alignment-recheck/requirements) remain authoritative pre-tasks audits. This file adds the post-tasks lens.

## Task ↔ Requirement Coverage

- [ ] CHK001 Does every functional requirement FR-001..FR-024 map to at least one implementation task in tasks.md? [Traceability, Spec §FR vs Tasks §Phases 3-5]
- [ ] CHK002 Does every success criterion SC-001..SC-009 map to at least one task that makes the SC verifiable? [Traceability, Spec §SC vs Tasks]
- [ ] CHK003 Does every user-story acceptance scenario (US1.1-3, US2.1-3, US3.1-3) map to at least one integration test task? [Coverage, Spec §US vs Tasks T021/T028/T041]
- [ ] CHK004 Does every Edge Cases bullet in spec.md have a corresponding test task or implementation task? [Coverage, Spec §Edge Cases vs Tasks T051]
- [ ] CHK005 Does every Clarifications answer (across 3 sessions, 26 Q/A) translate into a task or is it absorbed into an existing FR's task? [Traceability, Spec §Clarifications vs Tasks]

## Task ↔ Contract Coverage

- [ ] CHK006 Does each of the 8 methods (M1–M8) in contracts/managed-methods.md have at least one implementation task and at least one contract test task? [Coverage, Contracts §M1-M8 vs Tasks]
- [ ] CHK007 Are all 9 new closed-set error codes in contracts/error-codes.md exercised by a test task? [Coverage, Contracts §error-codes vs Tasks T016/T036/T037/T040]
- [ ] CHK008 Does every lifecycle event type (12 in contracts/managed-methods.md §Events) have a wiring task that emits it from the right state-machine transition? [Coverage, Contracts §Events vs Tasks T014/T032]
- [ ] CHK009 Does the `promote_from_adopted` stub (M8) have both an implementation task (T045) and a test task (T040) confirming `not_implemented` shape? [Completeness, Spec §FR-018 vs Tasks T045/T040]
- [ ] CHK010 Is the state-machine recovery path (contracts/state-machine.md §Recovery) covered by a dedicated recovery task (T046) AND a visibility task (T049)? [Coverage, Contracts §state-machine vs Tasks T046/T049]

## Task ↔ Data Model Coverage

- [ ] CHK011 Does the SQLite migration runner task (T007) explicitly depend on the migration file task (T002)? [Sequencing, Tasks T002/T007]
- [ ] CHK012 Is the denormalized `container_id` column on `managed_pane` (T1 finding from earlier analyze) reflected in T002's DDL task description? [Completeness, Data-Model §DDL vs Tasks T002]
- [ ] CHK013 Are all CHECK constraints (state, failed_stage, chain_depth ≤ 16, pending_marker_token NULL outside creating) covered by at least one test? [Coverage, Data-Model §DDL vs Tasks T018/T036]
- [ ] CHK014 Is the partial unique index `(container_id, label) WHERE state IN (...)` exercised by a positive AND a negative test? [Coverage, Data-Model §DDL vs Tasks T016]
- [ ] CHK015 Does FR-021 indefinite audit retention have a task that wires the JSONL pipeline OR is it deliberately covered by reuse of FEAT-008 (no new task needed)? [Coverage, Spec §FR-021 vs Tasks T014]

## Task ↔ Quickstart Coverage

- [ ] CHK016 Does every step in quickstart.md §US1 walkthrough map to at least one implementation task? [Coverage, Quickstart §US1 vs Tasks T022-T025]
- [ ] CHK017 Does every step in quickstart.md §US2 walkthrough map to at least one implementation task? [Coverage, Quickstart §US2 vs Tasks T029-T034]
- [ ] CHK018 Does every step in quickstart.md §US3 walkthrough (remove, recreate, restart) map to implementation + test tasks? [Coverage, Quickstart §US3 vs Tasks T042-T049]
- [ ] CHK019 Does Polish task T052 (end-to-end quickstart walkthrough) cover the preconditions, the negative-path edge cases, AND the daemon-restart variant in quickstart.md? [Coverage, Quickstart vs Tasks T052]

## Task Format & Style

- [ ] CHK020 Does every task in tasks.md start with `- [ ] T###`, then optional `[P]`, then optional `[USx]`, then a description containing at least one file path? [Format, Tasks]
- [ ] CHK021 Are Phase 1 (Setup), Phase 2 (Foundational), and Phase 6 (Polish) tasks unmarked by `[USx]` (per skill convention)? [Format, Tasks]
- [ ] CHK022 Are User-Story-phase tasks (Phases 3/4/5) all marked with the correct `[US1]` / `[US2]` / `[US3]` label? [Format, Tasks]
- [ ] CHK023 Are task IDs T001..T056 sequential with no gaps? [Format, Tasks]

## Task Sequencing & Dependencies

- [ ] CHK024 Does tasks.md's "Dependencies & Execution Order" section enumerate every cross-task dependency that would otherwise be implicit (T007→T002, T022→Phase 2, T029/T030→T022, T046/T047→T012, T050→T012)? [Completeness, Tasks §Dependencies]
- [ ] CHK025 Is Phase 2 (Foundational) explicitly called out as a BLOCKER for Phase 3-5? [Clarity, Tasks §Dependencies]
- [ ] CHK026 Does each phase have a documented "Checkpoint" that names the observable state after completion? [Completeness, Tasks §Phase checkpoints]
- [ ] CHK027 Are the 4 existing-file modifications (T025 dispatchers, T031 view models, T034 FEAT-004 scan, T047 daemon boot) flagged with explicit coordination notes? [Clarity, Tasks §Notes]

## Parallel Markers

- [ ] CHK028 Are tasks marked `[P]` actually file-disjoint with their phase peers (no two `[P]` tasks edit the same file)? [Consistency, Tasks]
- [ ] CHK029 Are non-`[P]` tasks within the same phase genuinely sequential (file overlap or hard ordering)? [Consistency, Tasks]
- [ ] CHK030 Are all 10 parallelizable Phase 2 tasks listed in the "Parallel Example: Phase 2 Foundational" block? [Completeness, Tasks §Parallel Example]

## Test Coverage (Contract + Integration)

- [ ] CHK031 Does each contract test file named in tasks.md correspond to a method or behavior in contracts/managed-methods.md? [Traceability, Tasks T016-T040]
- [ ] CHK032 Are negative-path tests written for every closed-set error code (`managed_session_name_conflict`, `managed_pane_protected_adopted`, `managed_pane_recreate_chain_too_deep`, etc.)? [Coverage, Tasks T016/T036/T037/T040]
- [ ] CHK033 Are concurrency tests written for FR-019 per-container serialization (T020) AND cross-container parallelism? [Coverage, Tasks T020]
- [ ] CHK034 Is the FR-014 pending-managed-marker × scan race covered by a contract test (T019)? [Coverage, Tasks T019]
- [ ] CHK035 Are tests written for the daemon-restart recovery path against BOTH the all-reattached and partial-reattach-failure scenarios (T038 + T039)? [Coverage, Tasks T038/T039]
- [x] CHK036 Is launch-profile YAML validation (invalid YAML, missing required fields, argv-shape violation per R9) covered by a dedicated test, or is it implicitly part of T017? [Coverage, Gap, Tasks T017 vs Plan §Launch profiles] — **Resolved 2026-05-24** by expanding T017 to a two-file parallel-safe test pair including a standalone `tests/contract/test_managed_launch_profiles.py`.
- [ ] CHK037 Is the YAML override merge precedence (operator file with same `name` wins, per FR-024) covered by an explicit test in T017? [Coverage, Tasks T017]

## Implementation Footprints

- [ ] CHK038 Is FR-022's TTL sweep loop (5-min cadence + boot-time GC) captured by an implementation task (T012 declares the helper; T050 wires the periodic task)? [Coverage, Spec §FR-022 vs Tasks T012/T050]
- [ ] CHK039 Is FR-020's detail-surface readability for recovery outcomes captured by an implementation task (T049) AND a test task (T039)? [Coverage, Spec §FR-020 vs Tasks T049/T039]
- [ ] CHK040 Is SC-009's ≤5s post-restart visibility budget covered by a perf verification task (T056)? [Coverage, Spec §SC-009 vs Tasks T056]
- [ ] CHK041 Is SC-008's ≤5s reattach budget covered by a perf verification task (T055)? [Coverage, Spec §SC-008 vs Tasks T055]
- [ ] CHK042 Is SC-001's ≤2min layout-create budget covered by a perf verification task (T054)? [Coverage, Spec §SC-001 vs Tasks T054]

## Cross-FEAT Integration

- [ ] CHK043 Is each FEAT-* dependency named in plan.md §Technical Context (FEAT-002, FEAT-003, FEAT-004, FEAT-006, FEAT-007, FEAT-008, FEAT-009, FEAT-010, FEAT-011) touched by at least one explicit integration task? [Coverage, Plan §Technical Context vs Tasks]
- [ ] CHK044 Does T034 (FEAT-004 scan update) explicitly state which FEAT-004 file to modify and what formatter change is required? [Clarity, Tasks T034]
- [ ] CHK045 Does T029 (FEAT-006 registration wiring) name the exact import / call site? [Clarity, Tasks T029]
- [ ] CHK046 Does T030 (FEAT-007 log attach wiring) name the exact import / call site? [Clarity, Tasks T030]
- [ ] CHK047 Does T025 (dispatcher registration) cover BOTH the FEAT-002 dispatcher (legacy CLI) AND the FEAT-011 app_contract dispatcher? [Completeness, Tasks T025]
- [x] CHK048 Does FEAT-011's `app.hello` capability_flags response need to advertise the new `app.managed_*` methods, or is the additive evolution rule sufficient? [Gap, Spec §FEAT-011 contract vs Tasks] — **Resolved 2026-05-24**: `capability_flags` stays `{}`. The new methods are required surfaces of FEAT-013 (not optional capabilities) and reach clients via FEAT-011's additive-evolution rule. Contracts §Versioning corrected; tasks.md Notes calls this out so no `capability_flags` task is added.

## Constitution Re-Check in Tasks

- [ ] CHK049 Do tasks honor Principle I (local-first): no task introduces a network listener or extends the socket scope? [Constitution, Tasks]
- [ ] CHK050 Do tasks honor Principle III (safe terminal input): T011 (tmux_create) is argv-first, and no implementation task uses `send-keys` for first-line launch commands? [Constitution, Tasks T011]
- [ ] CHK051 Do tasks honor Principle IV (observable + scriptable): every operator action has both a `managed.*` CLI task AND an `app.managed_*` app task? [Constitution, Tasks T023/T024/T048]
- [ ] CHK052 Do tasks honor Principle V (conservative automation): no task auto-classifies failures, auto-recreates, or auto-promotes adopted panes? [Constitution, Tasks]

## Edge Cases Coverage

- [ ] CHK053 Are all 9 Edge Cases bullets covered by tests in T051 (test_managed_edge_cases.py)? [Coverage, Spec §Edge Cases vs Tasks T051]
- [ ] CHK054 Is the "bench container disappears mid-creation" edge case covered by an explicit test? [Coverage, Spec §Edge Cases vs Tasks T051]
- [ ] CHK055 Is the "multiple layout creation requests target same container at the same time" case covered by T020 + T051? [Coverage, Spec §Edge Cases vs Tasks T020/T051]

## New Gaps Surfaced by Tasks

- [x] CHK056 Does tasks.md need a task to update the FEAT-011 `app.hello` capability_flags response, OR is the additive-evolution rule sufficient without changes? [Gap, Tasks] — **Resolved 2026-05-24**: No task is added. Tasks.md Notes explicitly forbids it; rationale recorded in contracts/managed-methods.md §Versioning. Same decision as CHK048.
- [x] CHK057 Is there a task to add the `app.managed_*` methods to the documented method list in CLAUDE.md or the project README? [Gap, Tasks vs Docs] — **Resolved 2026-05-24** by expanding T053 to (a) include the full method list in `docs/managed-sessions.md`, and (b) extend `docs/app-contract-client-guide.md` (FEAT-011's existing client-facing method-list surface) with a pointer to the new `app.managed_*` methods. Inspection confirmed README.md and CLAUDE.md do not carry method lists and need no update.
- [x] CHK058 Is the SQLite migration's failure-on-second-run case (idempotent `CREATE TABLE IF NOT EXISTS`) explicitly tested, or covered by T007 only? [Coverage, Gap, Tasks T007] — **Resolved 2026-05-24** by extending T007 with an explicit idempotency requirement (DDL uses `IF NOT EXISTS` per data-model.md) plus a smoke check inside `migration.py` (or `tests/contract/test_managed_migration.py`) asserting the second run (a) does not raise, (b) leaves `schema_version` at the new value, (c) introduces zero row mutations.
- [x] CHK059 Does T053 (`docs/managed-sessions.md`) include the canonical YAML paths from §Assumptions and at least one example template + launch profile? [Coverage, Tasks T053] — **Resolved 2026-05-24** by expanding T053 to require the canonical paths verbatim from spec §Assumptions, at least one example managed-template YAML (matching the built-in `1m+2s` shape), and at least one example launch-command-profile YAML (matching the `LaunchCommandProfile` schema in data-model.md).
- [x] CHK060 Should the launch_profiles.py loader also have a standalone contract test, separate from the template loader test (T017)? [Coverage, Gap] — **Resolved 2026-05-24** (same edit as CHK036) by adding `tests/contract/test_managed_launch_profiles.py` as a parallel sibling of `tests/contract/test_managed_templates.py` inside T017.
