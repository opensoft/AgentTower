# Alignment Check: Post-Clarify-2 Spec Elements vs Downstream Artifacts

**Purpose**: After the post-plan-review clarification session (Spec §Clarifications "Session 2026-05-24 (post-plan review)") added **FR-022, FR-023, FR-024, SC-009** and extended **FR-013, FR-018, FR-020, §Assumptions**, verify that every downstream artifact (plan.md, research.md, data-model.md, contracts/*, quickstart.md, plan-review.md) is still aligned. Each item tests *requirements-document alignment*, not implementation.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md) — Session 2026-05-24 (post-plan review)
**Depth**: release gate. **Audience**: feature author before `/speckit.tasks`.

## FR-013 alignment (`failed_stage` closed enum promoted into FR)

- [ ] CHK001 Does plan.md reference the closed `failed_stage` enum (or FR-013 by ID) somewhere in Technical Context or Constitution Check evidence? [Consistency, Spec §FR-013 vs Plan]
- [ ] CHK002 Do research §R7's enum values match FR-013's inline closed set verbatim (no spelling drift, no extras)? [Consistency, Spec §FR-013 vs Research §R7]
- [ ] CHK003 Does data-model.md's `failed_stage` CHECK constraint enumerate the same six values as FR-013 (in both `managed_layout` and `managed_pane`)? [Consistency, Spec §FR-013 vs Data-Model §DDL]
- [ ] CHK004 Do contracts/managed-methods.md M3 / M5 detail-response shapes include `failed_stage` with canonical values from FR-013? [Consistency, Spec §FR-013 vs Contracts §M3/M5]
- [ ] CHK005 Do contracts/state-machine.md transition triggers reference each FR-013 enum value at least once across the trigger column? [Consistency, Spec §FR-013 vs Contracts §state-machine]

## FR-018 alignment (cancel-in-flight create explicitly out-of-scope)

- [ ] CHK006 Is "cancellation of in-flight layout creation" called out as out-of-scope in plan.md (Summary, Technical Context, or Constitution Check)? [Coverage, Spec §FR-018 vs Plan]
- [ ] CHK007 Does contracts/managed-methods.md §M6 (or a sibling note) acknowledge cancel-in-flight is unsupported and reference FR-018? [Consistency, Spec §FR-018 vs Contracts §M6]
- [ ] CHK008 Does research §R2 align with FR-018's explicit out-of-scope (not only "reserved for a later feature")? [Consistency, Spec §FR-018 vs Research §R2]

## FR-020 alignment (recovery outcomes readable from list/detail surface)

- [ ] CHK009 Do contracts/managed-methods.md M3 (or M5) response shapes demonstrate how a recovery outcome surfaces (e.g., `failed_stage = "recovery_reattach"` in a sample)? [Consistency, Spec §FR-020 vs Contracts §M3/M5]
- [ ] CHK010 Does data-model.md describe that recovery outcome is visible via the same detail surface used for normal operation (not only via events)? [Coverage, Spec §FR-020 vs Data-Model]
- [ ] CHK011 Does quickstart.md's daemon-restart section show the operator reading recovery outcomes from list/detail (not only via the audit log)? [Coverage, Spec §FR-020 vs Quickstart]
- [ ] CHK012 Does contracts/state-machine.md's Recovery section reference the visibility of recovery outcomes from a read surface? [Coverage, Spec §FR-020 vs Contracts §state-machine]

## FR-022 alignment (5-minute pending-marker TTL sweep)

- [ ] CHK013 Does plan.md Technical Context describe the 5-minute sweep as a measurable system property and tie it to FR-022 (by ID or by behavior)? [Consistency, Spec §FR-022 vs Plan]
- [ ] CHK014 Does research §R5 produce the same TTL value (5 min) and sweep cadence (boot + 60 s) as FR-022 mandates? [Consistency, Spec §FR-022 vs Research §R5]
- [ ] CHK015 Does data-model.md show that a swept pending-managed pane transitions to `failed` with `failed_stage = pane_create` (no tmux pane) or `failed_stage = registration` (pane exists but never registered)? [Consistency, Spec §FR-022 vs Data-Model + §FR-013]
- [ ] CHK016 Does contracts/state-machine.md's `creating → failed` transition row name the FR-022 TTL sweep as a trigger, distinct from registration failure? [Consistency, Spec §FR-022 vs Contracts §state-machine]

## FR-023 alignment (recreate-chain depth bound 16)

- [ ] CHK017 Does plan.md Constraints / Scale section reference FR-023 or the depth-16 bound? [Consistency, Spec §FR-023 vs Plan]
- [ ] CHK018 Does data-model.md's `chain_depth` CHECK constraint match FR-023's "maximum depth of 16" wording exactly (off-by-one consistent with R4's `>= 15` rejection rule)? [Consistency, Spec §FR-023 vs Data-Model §DDL vs Research §R4]
- [ ] CHK019 Does contracts/error-codes.md `managed_pane_recreate_chain_too_deep` reference FR-023 and include the bound (16) in its details schema? [Consistency, Spec §FR-023 vs Contracts §error-codes]
- [ ] CHK020 Does contracts/state-machine.md's Recreate Semantics section reference FR-023's bound? [Consistency, Spec §FR-023 vs Contracts §state-machine]
- [ ] CHK021 Does quickstart.md's edge-cases table list the recreate-chain-too-deep scenario with FR-023 reference? [Coverage, Spec §FR-023 vs Quickstart]

## FR-024 alignment (operator YAML override capability)

- [ ] CHK022 Does plan.md (Summary, Technical Context, or Constitution Check evidence) reference FR-024 and the canonical YAML paths? [Consistency, Spec §FR-024 vs Plan]
- [ ] CHK023 Do research §R8/R9 enumerate the same canonical paths as spec §Assumptions (no path drift)? [Consistency, Spec §Assumptions vs Research §R8/R9]
- [ ] CHK024 Does quickstart.md's Preconditions section reference the operator-overridable YAML paths per FR-024 (not just example file contents)? [Consistency, Spec §FR-024 vs Quickstart]
- [ ] CHK025 Do contracts/error-codes.md `managed_template_not_found` / `managed_launch_command_not_found` descriptions reference FR-024's override-resolution rule (operator file with same name wins)? [Consistency, Spec §FR-024 vs Contracts §error-codes]

## SC-009 alignment (recovery visible within 5s of socket-ready)

- [ ] CHK026 Does plan.md Performance Goals list SC-009 alongside SC-001 / SC-003 / SC-008? [Completeness, Spec §SC-009 vs Plan]
- [ ] CHK027 Does quickstart.md's daemon-restart section state SC-009's 5-second visibility window explicitly (not just SC-008's reattach window)? [Coverage, Spec §SC-009 vs Quickstart]
- [ ] CHK028 Do contracts/managed-methods.md M3 (or §Events) describe the readability path within the SC-009 time bound? [Consistency, Spec §SC-009 vs Contracts §M3]
- [ ] CHK029 Does the test plan in plan.md (`tests/contract/` or `tests/integration/`) include coverage for SC-009 readability post-restart? [Coverage, Spec §SC-009 vs Plan §Project Structure]

## §Assumptions alignment (new YAML-paths bullet)

- [ ] CHK030 Does plan.md (Technical Context or Constitution Check) reference the new §Assumptions bullet naming the two YAML paths? [Consistency, Spec §Assumptions vs Plan]
- [ ] CHK031 Are the canonical paths in §Assumptions identical (character-for-character) to those in research §R8/R9 and quickstart preconditions? [Consistency, Spec §Assumptions vs Research §R8/R9 vs Quickstart]

## Cross-cutting traceability

- [ ] CHK032 Is the "Session 2026-05-24 (post-plan review)" Clarifications block cross-referenced from plan.md (e.g., "see §Clarifications post-plan review for FR-022/023/024 origin")? [Traceability, Spec §Clarifications vs Plan]
- [ ] CHK033 Are FR-022 / FR-023 / FR-024 / SC-009 each traceable to at least one user story or acceptance scenario, or are they explicitly system-level requirements only (with that rationale stated)? [Traceability, Spec §FR/SC vs §User Scenarios]
- [ ] CHK034 Are plan-review.md CHK036–CHK041 now markable as resolved by the post-clarify-2 spec amendments alone (no remaining code-level dependency)? [Coverage, Plan-Review vs Spec amendments]
- [ ] CHK035 Is the spec's FR numbering still contiguous (FR-001..FR-024 with no gaps) after the amendments? [Consistency, Spec §FR]
- [ ] CHK036 Is the spec's SC numbering still contiguous (SC-001..SC-009 with no gaps) after the amendments? [Consistency, Spec §SC]
- [ ] CHK037 Are the new closed-set error codes referenced in error-codes.md (`managed_pane_recreate_chain_too_deep`) **only** triggered by FR-023, or do their `details` schemas also need updating to reflect FR-022's TTL-driven failures? [Coverage, Gap, Spec §FR-022/023 vs Contracts §error-codes]
- [ ] CHK038 Is there any conflict between FR-013's inline `failed_stage` enum and the legacy text "specific failed stage" used elsewhere in spec.md (Edge Cases, SC-006)? [Conflict, Spec §FR-013 vs Spec §Edge Cases / §SC-006]
