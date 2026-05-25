# Alignment Check: Post-Clarify-2 Spec Elements vs Downstream Artifacts

**Purpose**: After the post-plan-review clarification session (Spec §Clarifications "Session 2026-05-24 (post-plan review)") added **FR-022, FR-023, FR-024, SC-009** and extended **FR-013, FR-018, FR-020, §Assumptions**, verify that every downstream artifact (plan.md, research.md, data-model.md, contracts/*, quickstart.md, plan-review.md) is still aligned. Each item tests *requirements-document alignment*, not implementation.
**Created**: 2026-05-24
**Closed**: 2026-05-25 (walk after `e3af4d0`)
**Feature**: [spec.md](../spec.md) — Session 2026-05-24 (post-plan review)
**Depth**: release gate. **Audience**: feature author before `/speckit.tasks`.

## FR-013 alignment (`failed_stage` closed enum promoted into FR)

- [x] CHK001 Does plan.md reference the closed `failed_stage` enum (or FR-013 by ID) somewhere in Technical Context or Constitution Check evidence? [Consistency] — Plan §Performance Goals: "FR-013 per-stage timeout 30s with 2x transient retry"; Constitution Check Principle IV row: "closed-set error code + `failed_stage` enum + recovery hint per FR-013 / FR-016".
- [x] CHK002 Do research §R7's enum values match FR-013's inline closed set verbatim (no spelling drift, no extras)? [Consistency] — Both enumerate the same 6 tokens: `pane_create`, `launch_command`, `registration`, `log_attach`, `tmux_kill`, `recovery_reattach`.
- [x] CHK003 Does data-model.md's `failed_stage` CHECK constraint enumerate the same six values as FR-013 (in both `managed_layout` and `managed_pane`)? [Consistency] — Both tables include `CHECK (failed_stage IS NULL OR failed_stage IN ('pane_create','launch_command','registration','log_attach','tmux_kill','recovery_reattach'))`.
- [x] CHK004 Do contracts/managed-methods.md M3 / M5 detail-response shapes include `failed_stage` with canonical values from FR-013? [Consistency] — M3 sample shows `"failed_stage": null` for healthy pane + `"failed_stage": "log_attach"` for degraded + recovery-variant `"failed_stage": "recovery_reattach"`. M5 returns the same per-pane fields as M3 (single-pane detail) and inherits the field.
- [x] CHK005 Do contracts/state-machine.md transition triggers reference each FR-013 enum value at least once across the trigger column? [Consistency] — `pane_create` (creating→failed); `launch_command` (creating→degraded); `registration` (creating→failed); `log_attach` (creating→degraded); `tmux_kill` (implicit in remove triggers; `failed_stage` not set on remove); `recovery_reattach` (Recovery section). All 6 surfaced.

## FR-018 alignment (cancel-in-flight create explicitly out-of-scope)

- [x] CHK006 Is "cancellation of in-flight layout creation" called out as out-of-scope in plan.md (Summary, Technical Context, or Constitution Check)? [Coverage] — Plan §Summary: "**Out of scope for MVP**: non-tmux backends, semantic task planning, cross-host orchestration, adopted-to-managed pane promotion, and cancellation of in-flight layout creation (per spec §FR-018)."
- [x] CHK007 Does contracts/managed-methods.md §M6 (or a sibling note) acknowledge cancel-in-flight is unsupported and reference FR-018? [Consistency] — M6 Errors: "managed_pane_illegal_transition if the pane is in `creating` — operator must wait or use the in-progress cancel (out of scope MVP)."
- [x] CHK008 Does research §R2 align with FR-018's explicit out-of-scope (not only "reserved for a later feature")? [Consistency] — R2: "cancellation of an in-flight create is **out of scope for MVP** per spec §FR-018 (may be revisited in a later feature)."

## FR-020 alignment (recovery outcomes readable from list/detail surface)

- [x] CHK009 Do contracts/managed-methods.md M3 (or M5) response shapes demonstrate how a recovery outcome surfaces (e.g., `failed_stage = "recovery_reattach"` in a sample)? [Consistency] — M3 "Sample variant — recovery_reattach failure (FR-020 / SC-009)" shows the exact JSON shape with `failed_stage: "recovery_reattach"`.
- [x] CHK010 Does data-model.md describe that recovery outcome is visible via the same detail surface used for normal operation (not only via events)? [Coverage] — state-machine.md §Recovery: "Operator visibility of recovery outcomes (FR-020 / SC-009): After step 5, every recovered managed-layout and managed-pane row is readable via the standard `app.managed_layout_detail` (M3) and `app.managed_pane_detail` (M5) surfaces."
- [x] CHK011 Does quickstart.md's daemon-restart section show the operator reading recovery outcomes from list/detail (not only via the audit log)? [Coverage] — Quickstart §US3 daemon restart: "Within ~5s of the socket becoming ready (SC-008 target): `{method: app.managed_layout_detail, layout_id: ...}`. ... **No operator action was required.** SC-009 mandates this readability within 5 seconds of the socket becoming ready — no log inspection required, the detail surface alone tells the whole recovery story."
- [x] CHK012 Does contracts/state-machine.md's Recovery section reference the visibility of recovery outcomes from a read surface? [Coverage] — Same quote as CHK010 above.

## FR-022 alignment (5-minute pending-managed marker TTL sweep)

- [x] CHK013 Does plan.md Technical Context describe the 5-minute sweep as a measurable system property and tie it to FR-022 (by ID or by behavior)? [Consistency] — Plan §Performance Goals: "FR-022 pending-managed marker TTL 5 minutes with periodic 60s sweep (research §R5)".
- [x] CHK014 Does research §R5 produce the same TTL value (5 min) and sweep cadence (boot + 60 s) as FR-022 mandates? [Consistency] — R5: "5 minutes" + "Daemon boot (FR-020 reconciliation runs before the socket starts accepting requests)" + "A periodic 60-second sweep".
- [x] CHK015 Does data-model.md show that a swept pending-managed pane transitions to `failed` with `failed_stage = pane_create` (no tmux pane) or `failed_stage = registration` (pane exists but never registered)? [Consistency] — data-model.md DDL §Notes bullet: "FR-022 TTL sweep: managed_pane rows that linger in `state = 'creating'` for more than 5 minutes are transitioned to `failed` by `pending_marker.sweep()` (boot-time + 60s periodic) with `failed_stage = 'pane_create'` if no tmux pane backs the row, else `failed_stage = 'registration'`."
- [x] CHK016 Does contracts/state-machine.md's `creating → failed` transition row name the FR-022 TTL sweep as a trigger, distinct from registration failure? [Consistency] — state-machine.md pane transitions table row: "`creating` | `failed` | Pending-managed marker TTL exceeded (5 minutes per FR-022, research §R5) and pane never observed | Daemon-initiated sweep task; `failed_stage = 'pane_create'` if no tmux pane backs the row, else `'registration'`" — explicitly distinct from the "tmux new-session/split-window failed OR FEAT-006 registration errored" row.

## FR-023 alignment (recreate-chain depth bound 16)

- [x] CHK017 Does plan.md Constraints / Scale section reference FR-023 or the depth-16 bound? [Consistency] — Plan §Constraints: "Recreate-chain depth bounded at 16 (FR-023, research §R4)".
- [x] CHK018 Does data-model.md's `chain_depth` CHECK constraint match FR-023's "maximum depth of 16" wording exactly (off-by-one consistent with R4's `>= 15` rejection rule)? [Consistency] — DDL: `chain_depth INTEGER NOT NULL DEFAULT 0 CHECK (chain_depth >= 0 AND chain_depth <= 16) -- FR-023 bound`. Off-by-one consistent: service rejects when predecessor.chain_depth >= 15 (R4), so new row max = 15; CHECK permits up to 16 inclusive (never reached, but bound name "16" matches FR-023 wording).
- [x] CHK019 Does contracts/error-codes.md `managed_pane_recreate_chain_too_deep` reference FR-023 and include the bound (16) in its details schema? [Consistency] — Heading updated 2026-05-25 to `### managed_pane_recreate_chain_too_deep (FR-023, R4)`; details schema: `{"predecessor_pane_id": "string", "predecessor_chain_depth": 15, "limit": 16}`.
- [x] CHK020 Does contracts/state-machine.md's Recreate Semantics section reference FR-023's bound? [Consistency] — state-machine.md §Recreate semantics, step 1: "Service validates `predecessor.chain_depth < 16` else `managed_pane_recreate_chain_too_deep` (FR-023, R4)" — FR-023 added 2026-05-25.
- [x] CHK021 Does quickstart.md's edge-cases table list the recreate-chain-too-deep scenario with FR-023 reference? [Coverage] — Quickstart §Edge cases row: "Recreate chain hits depth 16 (FR-023, R4)" — FR-023 added 2026-05-25.

## FR-024 alignment (operator YAML override capability)

- [x] CHK022 Does plan.md (Summary, Technical Context, or Constitution Check evidence) reference FR-024 and the canonical YAML paths? [Consistency] — Plan §Constraints: "Operator template / launch-profile overrides are loaded from canonical YAML paths under `~/.config/opensoft/agenttower/` (FR-024)." Plan §Provenance also cites FR-024 origin.
- [x] CHK023 Do research §R8/R9 enumerate the same canonical paths as spec §Assumptions (no path drift)? [Consistency] — Spec: `~/.config/opensoft/agenttower/managed_templates/*.yaml` + `…/launch_commands/*.yaml`. R8: `~/.config/opensoft/agenttower/managed_templates/*.yaml`. R9: `~/.config/opensoft/agenttower/launch_commands/*.yaml`. Character-for-character identical.
- [x] CHK024 Does quickstart.md's Preconditions section reference the operator-overridable YAML paths per FR-024 (not just example file contents)? [Consistency] — Quickstart §Preconditions: "Two operator YAML config files exist: `~/.config/opensoft/agenttower/launch_commands/claude-master.yaml`...". Path is named, not just the file content.
- [x] CHK025 Do contracts/error-codes.md `managed_template_not_found` / `managed_launch_command_not_found` descriptions reference FR-024's override-resolution rule (operator file with same name wins)? [Consistency] — Both codes carry a "Resolution order (per FR-024): operator override file with the same `name` wins over the built-in default" bullet.

## SC-009 alignment (recovery visible within 5s of socket-ready)

- [x] CHK026 Does plan.md Performance Goals list SC-009 alongside SC-001 / SC-003 / SC-008? [Completeness] — Plan §Performance Goals: "SC-001 ... SC-003 ... SC-008 ... SC-009 post-restart recovery-outcome visibility ≤ 5s via M3/M5 detail surfaces (no log inspection required)".
- [x] CHK027 Does quickstart.md's daemon-restart section state SC-009's 5-second visibility window explicitly (not just SC-008's reattach window)? [Coverage] — Quickstart §US3 daemon restart: "SC-009 mandates this readability within 5 seconds of the socket becoming ready — no log inspection required, the detail surface alone tells the whole recovery story."
- [x] CHK028 Do contracts/managed-methods.md M3 (or §Events) describe the readability path within the SC-009 time bound? [Consistency] — state-machine.md §Recovery names the M3/M5 surfaces explicitly: "SC-009 mandates this be observable within 5 seconds of socket-ready." M3 sample variant demonstrates the response shape.
- [x] CHK029 Does the test plan in plan.md (`tests/contract/` or `tests/integration/`) include coverage for SC-009 readability post-restart? [Coverage] — Plan §Project Structure: `test_managed_recovery_visibility.py # SC-009 ≤5s post-restart visibility via M3/M5 detail surfaces (recovery_reattach failed_stage readable without log inspection)`.

## §Assumptions alignment (new YAML-paths bullet)

- [x] CHK030 Does plan.md (Technical Context or Constitution Check) reference the new §Assumptions bullet naming the two YAML paths? [Consistency] — Plan §Constraints names both paths; Constitution Check Principle I evidence: "Operator templates and launch profiles live under `~/.config/opensoft/agenttower/` (matches the constitution's path conventions — research §R8/R9)."
- [x] CHK031 Are the canonical paths in §Assumptions identical (character-for-character) to those in research §R8/R9 and quickstart preconditions? [Consistency] — Verified: `~/.config/opensoft/agenttower/managed_templates/*.yaml` and `~/.config/opensoft/agenttower/launch_commands/*.yaml` appear character-for-character identical in spec §Assumptions, research §R8/§R9, and quickstart §Preconditions.

## Cross-cutting traceability

- [x] CHK032 Is the "Session 2026-05-24 (post-plan review)" Clarifications block cross-referenced from plan.md (e.g., "see §Clarifications post-plan review for FR-022/023/024 origin")? [Traceability] — Plan §Provenance blockquote: "FR-022 (5-min pending-managed marker TTL), FR-023 (recreate-chain depth ≤ 16), FR-024 (operator YAML overrides), and SC-009 (post-restart visibility ≤ 5s) originated from spec §Clarifications 'Session 2026-05-24 (post-plan review)'."
- [x] CHK033 Are FR-022 / FR-023 / FR-024 / SC-009 each traceable to at least one user story or acceptance scenario, or are they explicitly system-level requirements only (with that rationale stated)? [Traceability] — Spec §Clarifications alignment-cleanup Q2 maps each: FR-022 / FR-023 / SC-009 → US3; FR-024 → US1. Inline `(traces to USx)` annotations carry the link.
- [x] CHK034 Are plan-review.md CHK036–CHK041 now markable as resolved by the post-clarify-2 spec amendments alone (no remaining code-level dependency)? [Coverage] — Plan-review.md CHK036–CHK041 already marked `[x]` with the alignment-cleanup amendment note that distinguishes requirements-side close from the implementation-task footprint captured by tasks.md.
- [x] CHK035 Is the spec's FR numbering still contiguous (FR-001..FR-024 with no gaps) after the amendments? [Consistency] — Spec now reaches FR-027 (pre-implement walk added FR-025/026/027); contiguous FR-001..FR-027 with no gaps.
- [x] CHK036 Is the spec's SC numbering still contiguous (SC-001..SC-009 with no gaps) after the amendments? [Consistency] — Verified: SC-001..SC-009 contiguous.
- [x] CHK037 Are the new closed-set error codes referenced in error-codes.md (`managed_pane_recreate_chain_too_deep`) **only** triggered by FR-023, or do their `details` schemas also need updating to reflect FR-022's TTL-driven failures? [Coverage, Gap] — Spec §Clarifications alignment-cleanup Q4 settled this: FR-022 TTL-driven failures do **not** mint a new error code; the operator-facing signal is the pane's `failed` state plus `failed_stage` from the FR-013 closed set. `managed_pane_recreate_chain_too_deep` is FR-023-only.
- [x] CHK038 Is there any conflict between FR-013's inline `failed_stage` enum and the legacy text "specific failed stage" used elsewhere in spec.md (Edge Cases, SC-006)? [Conflict] — Spec §Clarifications alignment-cleanup Q5 resolved this: SC-006 now reads "with a `failed_stage` from the FR-013 closed set" — no duplicate enum, no conflict.

---

## Walk closure (2026-05-25)

38/38 items satisfied. Three small cross-reference improvements applied in-place to close strict `FR-023` mentions where the docs previously cited `R4` only:

1. **contracts/error-codes.md** — `managed_pane_recreate_chain_too_deep` heading now `(FR-023, R4)`.
2. **contracts/state-machine.md** — Recreate semantics step 1 now cites `(FR-023, R4)`.
3. **quickstart.md** — Edge-cases row now cites `(FR-023, R4)`.

These were not blocking gaps (R4 traces to FR-023 through research.md), but explicit FR cross-refs are cheaper for reviewers than the single hop.
