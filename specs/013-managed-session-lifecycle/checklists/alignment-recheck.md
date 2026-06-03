# Alignment Recheck: Post-Alignment-Cleanup Verification

**Purpose**: After the alignment-cleanup clarification round (Spec §Clarifications "Session 2026-05-24 (alignment cleanup)"), verify the 5 edits landed correctly, flag any items still open from `alignment-check.md` round 1 that were NOT addressed, and surface any new gaps introduced by the cleanup edits themselves.
**Created**: 2026-05-24
**Closed**: 2026-05-25 (walk after `e3af4d0`)
**Feature**: [spec.md](../spec.md) — Sessions "post-plan review" + "alignment cleanup"
**Depth**: release gate. **Audience**: feature author before `/speckit.tasks`.

## Verify alignment-cleanup edits applied (sanity check)

- [x] CHK001 Does spec.md SC-006 reference "FR-013 closed set" rather than the abstract "specific failed stage" wording? [Consistency] — Spec SC-006: "A failed or partial layout creation produces a `degraded` (recoverable) or `failed` (non-recoverable) state with a `failed_stage` from the FR-013 closed set and a recovery action visible to the operator."
- [x] CHK002 Do FR-022, FR-023, FR-024, SC-009 each carry an inline `(traces to USx)` annotation matching the alignment-cleanup Q2 decision? [Traceability] — Verified: FR-022 (traces to US3), FR-023 (traces to US3), FR-024 (traces to US1), FR-025 (traces to US1), FR-026 (traces to US1), FR-027 (traces to US3), SC-009 (traces to US3).
- [x] CHK003 Does spec.md contain a `### Session 2026-05-24 (alignment cleanup)` sub-session under `## Clarifications` with five Q/A bullets? [Completeness] — Verified: 5 Q/A bullets covering (a) plan.md back-reference, (b) US traceability, (c) plan-review CHK036–CHK041 closure, (d) FR-022 TTL no new error code, (e) SC-006 rewording.
- [x] CHK004 Does plan.md carry a Provenance blockquote citing BOTH `Session 2026-05-24 (post-plan review)` AND `Session 2026-05-24 (alignment cleanup)`? [Traceability] — Plan §Provenance: "FR-022 ... originated from spec §Clarifications 'Session 2026-05-24 (post-plan review)'; their traceability to user stories was confirmed in spec §Clarifications 'Session 2026-05-24 (alignment cleanup)'." (Also cites pre-implement walk for FR-025/026/027.)
- [x] CHK005 Are plan-review.md CHK036–CHK041 marked `[x]` with per-item "Resolved 2026-05-24" annotations? [Completeness] — Verified: all 6 items ticked with explicit dates in the bullet body.
- [x] CHK006 Does plan-review.md include an amendment note flagging FR-022 / FR-020 / SC-009 implementation footprint for `/speckit.tasks`? [Completeness] — "Amendment note 2026-05-24 (alignment cleanup): CHK036–CHK041 closed by post-plan spec edits. Per spec §Clarifications 'Session 2026-05-24 (alignment cleanup)' Q3, the implementation work implied by FR-022 (sweep loop), FR-020 (recovery outcomes in detail surface), and SC-009 (5-second post-restart visibility) is to be captured as tasks by `/speckit.tasks`."

## New gaps introduced by the alignment-cleanup edits

- [x] CHK007 Are the new `(traces to USx)` annotations consistent with the rest of the FR/SC list — should ALL FRs and SCs carry similar annotations for parity, or were FR-022/023/024 and SC-009 explicitly the only system-level ones needing disambiguation? [Consistency, Gap] — Spec §Clarifications alignment-cleanup Q2 documents the rule: "The inline `(traces to USx)` annotation is reserved for these system-level requirements that lacked obvious US affinity at write-time; FR-001..FR-021 and SC-001..SC-008 do not carry the annotation by convention because their US affinity is evident from their text." Annotation now also applied to FR-025/026/027 from the pre-implement walk.
- [x] CHK008 If only the new system-level FRs/SCs carry the annotation, is the asymmetry documented (e.g., a note in §Clarifications "alignment cleanup" Q2 explaining why FR-001..FR-021 do NOT need it)? [Clarity, Gap] — Same Q2 above documents the asymmetry explicitly with the "by convention because their US affinity is evident from their text" rationale.

## Still-outstanding items from alignment-check.md round 1

These items were flagged "Likely failing" in alignment-check.md but were NOT in scope of the alignment-cleanup clarify round (which only handled the 5 "Worth investigating" judgment calls). They remain open as cross-doc wording edits.

- [x] CHK009 Does plan.md Summary explicitly name "cancel in-flight create" as out-of-scope, or rely only on the FR-018 reference? [Coverage] (alignment-check.md CHK006) — Plan §Summary: "**Out of scope for MVP**: non-tmux backends, semantic task planning, cross-host orchestration, adopted-to-managed pane promotion, and cancellation of in-flight layout creation (per spec §FR-018)." Both named explicitly and FR-018 referenced.
- [x] CHK010 Does research §R2 use "out of scope" wording aligned with FR-018, instead of "reserved for a later feature"? [Consistency] (alignment-check.md CHK008) — R2: "cancellation of an in-flight create is **out of scope for MVP** per spec §FR-018 (may be revisited in a later feature)." Both phrases present; "out of scope" is the operative wording.
- [x] CHK011 Does contracts/managed-methods.md §M3 sample response include a `recovery_reattach` `failed_stage` example, or only the general `failed_stage` field? [Consistency] (alignment-check.md CHK009) — M3 "Sample variant — recovery_reattach failure (FR-020 / SC-009)" shows the full response with `failed_stage: "recovery_reattach"` and per-pane recovery state.
- [x] CHK012 Does quickstart.md US3 daemon-restart section show the recovery-failure read path (not only the all-ready outcome)? [Coverage] (alignment-check.md CHK011) — Quickstart §US3 daemon-restart has both the happy path and the "If reattach failed for a pane" sample with `failed_stage: "recovery_reattach"`.
- [x] CHK013 Does contracts/state-machine.md Recovery section reference visibility from the M3 / M5 detail surface? [Coverage] (alignment-check.md CHK012) — state-machine.md §Recovery: "After step 5, every recovered managed-layout and managed-pane row is readable via the standard `app.managed_layout_detail` (M3) and `app.managed_pane_detail` (M5) surfaces."
- [x] CHK014 Does plan.md Technical Context cite FR-022 / FR-023 / FR-024 by ID anywhere (not only behaviorally)? [Consistency] (alignment-check.md CHK013 / CHK017 / CHK022) — Plan §Performance Goals: "FR-022 pending-managed marker TTL 5 minutes…"; §Constraints: "Recreate-chain depth bounded at 16 (FR-023, research §R4)" + "operator template/launch-profile overrides… (FR-024)". All three IDs cited.
- [x] CHK015 Does contracts/error-codes.md `managed_template_not_found` / `managed_launch_command_not_found` reference the FR-024 override-resolution rule (operator file with same `name` wins)? [Consistency] (alignment-check.md CHK025) — Both codes carry: "Resolution order (per FR-024): operator override file with the same `name` wins over the built-in default…"
- [x] CHK016 Does plan.md Performance Goals list SC-009 ≤ 5s alongside SC-001 / SC-003 / SC-008? [Completeness] (alignment-check.md CHK026) — Plan §Performance Goals: "SC-001 layout-create p95 ≤ 120s … SC-003 log-attach failure visible ≤ 10s … SC-008 daemon-restart reattach ≤ 5s … SC-009 post-restart recovery-outcome visibility ≤ 5s via M3/M5 detail surfaces".
- [x] CHK017 Does quickstart.md restart section cite SC-009 by ID and name the 5-second visibility window? [Coverage] (alignment-check.md CHK027) — "SC-009 mandates this readability within 5 seconds of the socket becoming ready — no log inspection required, the detail surface alone tells the whole recovery story."
- [x] CHK018 Does plan.md `tests/contract/` or `tests/integration/` list include coverage for SC-009 readability post-restart? [Coverage] (alignment-check.md CHK029) — Plan §Project Structure: `test_managed_recovery_visibility.py # SC-009 ≤5s post-restart visibility via M3/M5 detail surfaces (recovery_reattach failed_stage readable without log inspection)`.

## Forward-pointing tasks queued for /speckit.tasks (from alignment-cleanup Q3)

- [x] CHK019 Will the FR-022 pending-managed marker sweep loop be captured as an implementation task by `/speckit.tasks` (per the plan-review.md amendment note)? [Coverage] — Captured as T012 (helper) + T050 (60s periodic wiring); tasks.md §Phase 6 polish.
- [x] CHK020 Will the FR-020 detail-surface readability (recovery outcome fields in M3/M5 response shapes) be captured as an implementation task by `/speckit.tasks`? [Coverage] — Captured as T049 (impl: "Implement detail-surface readability for recovery outcomes in `view_models.py` and the M3/M5 response shapes") + T039 (test: "covering SC-009 (recovery outcome readable from `app.managed_layout_detail` and `app.managed_pane_detail`…)").
- [x] CHK021 Will the SC-009 ≤ 5-second post-restart visibility test be captured for `/speckit.tasks`? [Coverage] — Captured as T039 (functional) + T056 (perf SLA verification: "Verify SC-009 (≤5s post-restart recovery-outcome visibility from detail surface) is measurable in `test_managed_recovery_visibility.py`").

## Cross-doc traceability under both Clarifications sessions

- [x] CHK022 Does research.md cite the post-plan and alignment-cleanup Clarifications sessions as the documented origin of FR-022/023/024/SC-009 + the SC-006 rewording? [Traceability] — research.md header: "**Spec back-reference**: Origin of FR-022 / FR-023 / FR-024 / SC-009 is spec §Clarifications 'Session 2026-05-24 (post-plan review)'; user-story traceability + SC-006 rewording are recorded in spec §Clarifications 'Session 2026-05-24 (alignment cleanup)'."
- [x] CHK023 Does data-model.md acknowledge the FR-022 TTL behavior with a note in the recovery / pending-managed marker section? [Coverage] — data-model.md DDL §Notes bullet on FR-022 TTL sweep + ManagedPane field reference for `pending_marker_token` cites "FR-022 TTL sweep target".
- [x] CHK024 Are the SC-009 5-second budget and the FR-022 5-minute TTL consistent with each other — different time horizons, no overlap or conflict? [Consistency] — Different horizons: FR-022's 5-min TTL bounds *creating-state residue* in normal operation; SC-009's 5-sec budget bounds *recovery-outcome visibility* after daemon restart. The two budgets never overlap in scope (one is steady-state, one is cold-start). SC-009 self-states "Begins after SC-008's reattach phase completes; SC-008 and SC-009 are sequential, not parallel, so the worst-case cold-start observability budget is SC-008 + SC-009 ≤ 10 seconds" — explicit sequencing.

---

## Walk closure (2026-05-25)

24/24 items satisfied. No edits required during this walk — every item was already addressed by prior alignment commits (`ca67caf`, `817fb48`, `a0ab4a0`, `e7f2c89`, `bad699a`, `39dbb5f`, `e3af4d0`) and verified clean by `/speckit.analyze` Pass 15.
