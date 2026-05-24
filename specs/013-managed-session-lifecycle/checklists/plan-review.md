# Post-Plan Review Checklist: Managed Session Creation and Lifecycle

**Purpose**: Re-verify the spec + plan + research + data-model + contracts + quickstart **after** `/speckit.plan` has been run. Tests requirements-and-design-doc *quality*: did the plan close the gaps surfaced by the deep-and-wide round, are spec/plan/research/contracts mutually consistent, and did any new ambiguities slip in?
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md) + [plan.md](../plan.md)
**Depth**: Release gate. **Audience**: feature author + PR reviewer before `/speckit.tasks`.

This file is a single targeted audit, not another deep-and-wide refresh. It does not delete or restate the prior 15 checklists; it tests what the plan added on top of them.

## Spec ↔ Plan Traceability

- [ ] CHK001 Is every functional requirement FR-001..FR-021 referenced by at least one element of plan.md (Summary / Technical Context / Project Structure)? [Traceability, Spec §FR vs Plan §Summary]
- [ ] CHK002 Is every success criterion SC-001..SC-008 paired with a Technical Context Performance Goal or a contract-level guarantee? [Traceability, Spec §SC vs Plan §Technical Context]
- [ ] CHK003 Is every clarification (Session 2026-05-24 Q1–Q15) reflected in research.md, data-model.md, **or** contracts/? [Traceability, Spec §Clarifications]
- [ ] CHK004 Is every Edge Case bullet in spec.md addressed by a contract method, a state-machine transition, or a research decision? [Coverage, Spec §Edge Cases]
- [ ] CHK005 Does plan.md's Technical Context contain zero remaining `NEEDS CLARIFICATION` markers? [Completeness, Plan §Technical Context]

## Plan Internal Completeness

- [ ] CHK006 Does the Constitution Check table provide concrete evidence (specific FRs / files / decisions) for each of the five principles — not just "PASS"? [Completeness, Plan §Constitution Check]
- [ ] CHK007 Does the Project Structure section list every new module file with a one-line purpose AND identify each existing-module touch point? [Completeness, Plan §Project Structure]
- [ ] CHK008 Is the Summary's "additive layer" enumeration mutually consistent with the Project Structure module list (no orphan layers, no orphan modules)? [Consistency, Plan §Summary vs §Project Structure]
- [ ] CHK009 Is the Complexity Tracking section either fully justified or explicitly empty (not silently omitted)? [Completeness, Plan §Complexity Tracking]
- [ ] CHK010 Are FEAT dependencies enumerated with the **exact** reused surfaces (FEAT-002 dispatcher, FEAT-004 docker-exec channel, FEAT-006 register-self path, FEAT-007 log attach, FEAT-008 audit JSONL, FEAT-009 peer detection, FEAT-010 routes, FEAT-011 envelope/error registry)? [Completeness, Plan §Technical Context]

## Research Quality

- [ ] CHK011 Does each research item R1–R13 follow Decision / Rationale / Alternatives with at least one *real* alternative considered (not a strawman)? [Completeness, Research §R*]
- [ ] CHK012 Is the pending-marker representation (R1) safe against the in-pane process editing its own tmux pane title before registration completes? [Edge Case, Gap, Research §R1]
- [ ] CHK013 Is the 5-minute pending-marker TTL (R5) surfaced as a *measurable* system property (not only an internal sweep cadence)? [Measurability, Research §R5]
- [ ] CHK014 Is the recreate-chain depth bound of 16 (R4) justified relative to a realistic operator iteration workflow, not just a round number? [Clarity, Research §R4]
- [ ] CHK015 Is the per-container `asyncio.Lock` (R2) sufficient for the "remove + recreate" sequence, or is an additional per-pane lock needed for the predecessor → successor transition? [Coverage, Gap, Research §R2]
- [ ] CHK016 Are the launch-command argv decisions (R6) compatible with operator-supplied `working_dir` and `env` without re-opening a shell-interpolation hazard? [Consistency, Research §R6 vs Constitution §III]
- [ ] CHK017 Does research §R12's bench-container thin-client constraint refine — not contradict — spec §Assumptions' "MVP authorization is socket-access based"? [Consistency, Research §R12 vs Spec §Assumptions]

## Data-Model Fidelity

- [ ] CHK018 Does the SQLite DDL include CHECK constraints matching the closed-set `state` and `failed_stage` enums in both `managed_layout` and `managed_pane`? [Completeness, Data-Model §DDL]
- [ ] CHK019 Does the partial unique index on `(container_id, label)` correctly allow a recreated pane to reuse its predecessor's label after the predecessor enters `removed` or `failed`? [Edge Case, Data-Model §DDL]
- [ ] CHK020 Are required-vs-optional field markers explicit (NOT NULL / nullable) for every attribute in both entities? [Completeness, Data-Model §Entity field reference]
- [ ] CHK021 Are the layout-state derivation rules unambiguous for the zero-non-terminal-pane boundary (every pane `removed`)? [Clarity, Data-Model §ManagedLayout lifecycle]
- [ ] CHK022 Is the `chain_depth <= 16` CHECK constraint reconcilable with the service-side `>= 15` rejection rule (off-by-one boundary)? [Consistency, Data-Model §DDL vs Research §R4]
- [ ] CHK023 Is the `agent_id` FK direction (`managed_pane → agent`) consistent with FEAT-006 owning the agent table (no reverse-FK from agent to managed_pane)? [Consistency, Data-Model §DDL vs Plan §Technical Context]
- [ ] CHK024 Are the indexes (`ix_managed_layout_container_state`, `ix_managed_pane_layout_state`, etc.) aligned with the read access patterns described in contracts/managed-methods.md? [Completeness, Data-Model §DDL vs Contracts §M2..M5]

## Contract Fidelity

- [ ] CHK025 Does every method in managed-methods.md declare an explicit error-code list referencing only codes defined in error-codes.md (no undeclared codes)? [Consistency, Contracts §managed-methods vs §error-codes]
- [ ] CHK026 Is the `managed.layout.create` semantics ("response returns after row insertion, before tmux spawn completes") clearly described, including how the operator subsequently observes `ready`? [Clarity, Contracts §M1]
- [ ] CHK027 Is the lifecycle event catalog in managed-methods.md §Events 1:1 with the events listed in research §R11 (same set, same payload shape)? [Consistency, Contracts §Events vs Research §R11]
- [ ] CHK028 Is the `managed_pane_illegal_transition` error's `requested_action` field's value set enumerated (closed set of operator actions)? [Completeness, Gap, Contracts §error-codes]
- [ ] CHK029 Does the state-machine document distinguish operator-initiated transitions from daemon-initiated transitions (sweep, recovery) in the trigger column? [Clarity, Contracts §state-machine]
- [ ] CHK030 Is the `not_implemented` stub for `promote_from_adopted` reachable via both legacy `managed.*` and `app.managed_*` namespaces with identical response shapes? [Consistency, Contracts §M8]
- [ ] CHK031 Are the `idempotency_key` semantics (in-flight match vs completed match vs absent) consistent between `managed.layout.create` and `managed.pane.recreate`? [Consistency, Contracts §M1 vs §M7]

## Quickstart Adequacy

- [ ] CHK032 Does the quickstart cover at least one acceptance scenario from each of US1, US2, US3? [Coverage, Quickstart §US1/US2/US3 vs Spec §User Scenarios]
- [ ] CHK033 Does the quickstart exercise the daemon-restart recovery path with explicit pre- and post-restart observable state? [Coverage, Quickstart §US3 daemon restart]
- [ ] CHK034 Does the quickstart include negative-path edge cases (`managed_session_name_conflict`, recreate-chain-too-deep, adopted-pane protection)? [Coverage, Quickstart §Edge cases]
- [ ] CHK035 Are the quickstart's preconditions (YAML files, socket path, container availability) consistent with the constitution's `~/.config/opensoft/agenttower/` path conventions? [Consistency, Quickstart §Preconditions vs Constitution §Technical Constraints]

## Newly Introduced Gaps (from plan choices)

- [x] CHK036 Is the 5-minute pending-marker TTL (R5) reflected as either an FR addition or a documented assumption in spec.md, not only in research? [Gap, Research §R5 vs Spec §Assumptions] — **Resolved 2026-05-24** by spec FR-022 (post-plan review). Implementation footprint (sweep loop) deferred to `/speckit.tasks`.
- [x] CHK037 Are the operator-facing implications of the depth-16 recreate-chain bound (R4) surfaced in spec.md (e.g., as an FR or success criterion), not only in contracts/error-codes? [Gap, Research §R4 vs Spec §FR] — **Resolved 2026-05-24** by spec FR-023.
- [x] CHK038 Are the YAML configuration paths (R8/R9) referenced from spec §Assumptions, not only in research/plan? [Completeness, Research §R8/R9 vs Spec §Assumptions] — **Resolved 2026-05-24** by spec §Assumptions YAML-paths bullet + FR-024.
- [x] CHK039 Is the absence of a "cancel in-flight create-layout" operation explicitly listed as out-of-scope in spec §FR-018, not only mentioned implicitly in M6/R2? [Completeness, Gap, Spec §FR-018] — **Resolved 2026-05-24** by spec FR-018 amendment.
- [x] CHK040 Is the `failed_stage` taxonomy (R7) reflected in spec.md as part of FR-013 ("identify the failed stage"), or does the spec stay at the abstract "failed stage" wording? [Consistency, Research §R7 vs Spec §FR-013] — **Resolved 2026-05-24** by spec FR-013 inline enum (also rippled into SC-006 in alignment-cleanup session).
- [x] CHK041 Is the daemon-restart `recovery_reattach` failed_stage outcome reachable from any operator surface (event, list, detail), or only as an internal log entry? [Completeness, Gap, Research §R13 §Recovery vs Contracts §Events] — **Resolved 2026-05-24** by spec FR-020 amendment + SC-009. Implementation footprint (detail-surface fields, post-restart visibility ≤ 5s) deferred to `/speckit.tasks`.

> **Amendment note 2026-05-24 (alignment cleanup):** CHK036–CHK041 closed by post-plan spec edits. Per spec §Clarifications "Session 2026-05-24 (alignment cleanup)" Q3, the implementation work implied by FR-022 (sweep loop), FR-020 (recovery outcomes in detail surface), and SC-009 (5-second post-restart visibility) is to be captured as tasks by `/speckit.tasks`; these requirements are not blocked, but their CHK closure here is a requirements-quality close, not an implementation-complete close.

## Cross-Document Terminology Consistency

- [ ] CHK042 Is "operator" used canonically across plan.md, research.md, data-model.md, contracts/*.md, and quickstart.md (per Q15)? [Consistency, Spec §Clarifications Q15]
- [ ] CHK043 Are the state enum spellings (`creating`, `ready`, `degraded`, `failed`, `removed`) identical across spec, plan, data-model, state-machine, and contracts (no `Creating` / `READY` drift)? [Consistency]
- [ ] CHK044 Are the new closed-set error code spellings identical across data-model.md, contracts/managed-methods.md, and contracts/error-codes.md (e.g., `managed_session_name_conflict` not `session_name_conflict`)? [Consistency]
- [ ] CHK045 Is the `failed_stage` enum spelled identically across data-model.md, state-machine.md, and research §R7 (e.g., `pane_create` vs `pane-create` vs `pane_create_failed`)? [Consistency]

## Test-Plan Alignment

- [ ] CHK046 Does the `tests/contract/` list in plan.md cover every method in managed-methods.md (M1–M8)? [Coverage, Plan §Project Structure vs Contracts §managed-methods]
- [ ] CHK047 Does the `tests/integration/` list in plan.md cover every User Story (US1/US2/US3) and the Edge Cases section? [Coverage]
- [ ] CHK048 Does the test plan include a failure-injection harness for partial-failure and restart-recovery flows (callable from the contract-test layer)? [Coverage, Plan §Testing]
- [ ] CHK049 Are the test fixtures (`managed_template_fixtures`, `managed_clock`, `managed_tmux_recorder`) sufficient to exercise the FR-019 serializer FIFO without race conditions in CI? [Measurability, Plan §Project Structure]

## Constitution Re-Check Coverage

- [ ] CHK050 Does the Principle III evidence specifically reference the argv-first launch decision (R6) and the `shlex.quote` fallback path? [Completeness, Plan §Constitution Check]
- [ ] CHK051 Does the Principle IV evidence list both CLI (`managed.*`) and app (`app.managed_*`) parity, plus SQLite + JSONL durability? [Completeness, Plan §Constitution Check]
- [ ] CHK052 Does the Principle II evidence rule out host-only-tmux, Antigravity, mailbox adapters, and Python-thread backends? [Completeness, Plan §Constitution Check]
- [ ] CHK053 Is the post-design Constitution re-check called out explicitly (not merely implied by "unchanged")? [Clarity, Plan §Constitution Check]
