# Alignment Recheck: Post-Alignment-Cleanup Verification

**Purpose**: After the alignment-cleanup clarification round (Spec §Clarifications "Session 2026-05-24 (alignment cleanup)"), verify the 5 edits landed correctly, flag any items still open from `alignment-check.md` round 1 that were NOT addressed, and surface any new gaps introduced by the cleanup edits themselves.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md) — Sessions "post-plan review" + "alignment cleanup"
**Depth**: release gate. **Audience**: feature author before `/speckit.tasks`.

## Verify alignment-cleanup edits applied (sanity check)

- [ ] CHK001 Does spec.md SC-006 reference "FR-013 closed set" rather than the abstract "specific failed stage" wording? [Consistency, Spec §SC-006 vs §FR-013]
- [ ] CHK002 Do FR-022, FR-023, FR-024, SC-009 each carry an inline `(traces to USx)` annotation matching the alignment-cleanup Q2 decision? [Traceability, Spec §FR-022/023/024 §SC-009]
- [ ] CHK003 Does spec.md contain a `### Session 2026-05-24 (alignment cleanup)` sub-session under `## Clarifications` with five Q/A bullets? [Completeness, Spec §Clarifications]
- [ ] CHK004 Does plan.md carry a Provenance blockquote citing BOTH `Session 2026-05-24 (post-plan review)` AND `Session 2026-05-24 (alignment cleanup)`? [Traceability, Plan §Summary]
- [ ] CHK005 Are plan-review.md CHK036–CHK041 marked `[x]` with per-item "Resolved 2026-05-24" annotations? [Completeness, Plan-Review §Newly Introduced Gaps]
- [ ] CHK006 Does plan-review.md include an amendment note flagging FR-022 / FR-020 / SC-009 implementation footprint for `/speckit.tasks`? [Completeness, Plan-Review]

## New gaps introduced by the alignment-cleanup edits

- [ ] CHK007 Are the new `(traces to USx)` annotations consistent with the rest of the FR/SC list — should ALL FRs and SCs carry similar annotations for parity, or were FR-022/023/024 and SC-009 explicitly the only system-level ones needing disambiguation? [Consistency, Gap, Spec §FR/SC]
- [ ] CHK008 If only the new system-level FRs/SCs carry the annotation, is the asymmetry documented (e.g., a note in §Clarifications "alignment cleanup" Q2 explaining why FR-001..FR-021 do NOT need it)? [Clarity, Gap, Spec §Clarifications]

## Still-outstanding items from alignment-check.md round 1

These items were flagged "Likely failing" in alignment-check.md but were NOT in scope of the alignment-cleanup clarify round (which only handled the 5 "Worth investigating" judgment calls). They remain open as cross-doc wording edits.

- [ ] CHK009 Does plan.md Summary explicitly name "cancel in-flight create" as out-of-scope, or rely only on the FR-018 reference? [Coverage, Spec §FR-018 vs Plan] (alignment-check.md CHK006 — still open)
- [ ] CHK010 Does research §R2 use "out of scope" wording aligned with FR-018, instead of "reserved for a later feature"? [Consistency, Spec §FR-018 vs Research §R2] (alignment-check.md CHK008 — still open)
- [ ] CHK011 Does contracts/managed-methods.md §M3 sample response include a `recovery_reattach` `failed_stage` example, or only the general `failed_stage` field? [Consistency, Spec §FR-020 vs Contracts §M3] (alignment-check.md CHK009 — still open)
- [ ] CHK012 Does quickstart.md US3 daemon-restart section show the recovery-failure read path (not only the all-ready outcome)? [Coverage, Spec §FR-020 vs Quickstart] (alignment-check.md CHK011 — still open)
- [ ] CHK013 Does contracts/state-machine.md Recovery section reference visibility from the M3 / M5 detail surface? [Coverage, Spec §FR-020 vs Contracts §state-machine] (alignment-check.md CHK012 — still open)
- [ ] CHK014 Does plan.md Technical Context cite FR-022 / FR-023 / FR-024 by ID anywhere (not only behaviorally)? [Consistency, Spec §FR-022/023/024 vs Plan] (alignment-check.md CHK013 / CHK017 / CHK022 — still open)
- [ ] CHK015 Does contracts/error-codes.md `managed_template_not_found` / `managed_launch_command_not_found` reference the FR-024 override-resolution rule (operator file with same `name` wins)? [Consistency, Spec §FR-024 vs Contracts §error-codes] (alignment-check.md CHK025 — still open)
- [ ] CHK016 Does plan.md Performance Goals list SC-009 ≤ 5s alongside SC-001 / SC-003 / SC-008? [Completeness, Spec §SC-009 vs Plan] (alignment-check.md CHK026 — still open)
- [ ] CHK017 Does quickstart.md restart section cite SC-009 by ID and name the 5-second visibility window? [Coverage, Spec §SC-009 vs Quickstart] (alignment-check.md CHK027 — still open)
- [ ] CHK018 Does plan.md `tests/contract/` or `tests/integration/` list include coverage for SC-009 readability post-restart? [Coverage, Spec §SC-009 vs Plan §Project Structure] (alignment-check.md CHK029 — still open)

## Forward-pointing tasks queued for /speckit.tasks (from alignment-cleanup Q3)

- [ ] CHK019 Will the FR-022 pending-managed marker sweep loop be captured as an implementation task by `/speckit.tasks` (per the plan-review.md amendment note)? [Coverage, Spec §FR-022]
- [ ] CHK020 Will the FR-020 detail-surface readability (recovery outcome fields in M3/M5 response shapes) be captured as an implementation task by `/speckit.tasks`? [Coverage, Spec §FR-020]
- [ ] CHK021 Will the SC-009 ≤ 5-second post-restart visibility test be captured for `/speckit.tasks`? [Coverage, Spec §SC-009]

## Cross-doc traceability under both Clarifications sessions

- [ ] CHK022 Does research.md cite the post-plan and alignment-cleanup Clarifications sessions as the documented origin of FR-022/023/024/SC-009 + the SC-006 rewording? [Traceability, Research vs Spec §Clarifications]
- [ ] CHK023 Does data-model.md acknowledge the FR-022 TTL behavior with a note in the recovery / pending-managed marker section? [Coverage, Spec §FR-022 vs Data-Model]
- [ ] CHK024 Are the SC-009 5-second budget and the FR-022 5-minute TTL consistent with each other — different time horizons, no overlap or conflict? [Consistency, Spec §FR-022 vs §SC-009]
