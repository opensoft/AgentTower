# Swarm review fix plan

**Date:** 2026-05-24
**Source:** `swarm-review-2026-05-24.md` (88 findings: 10 CRITICAL, 24 HIGH, 22 MEDIUM, 18 LOW, 14 NIT)
**Strategy:** batches ordered by leverage. Batch 1 unblocks integration tests so subsequent batches are verifiable. Each batch is one commit, bench-verified before the next batch starts.

---

## Batch 1 — Decoder + harness + wire-shape (unblocks integration tests)

Closes CR-1, CR-2, CR-3, M-22, H-F1, H-E1, H-E2.

1. **CR-1.** Add `@JsonValue('snake_case')` to every multi-word enum value in `common_enums.dart`. Regenerate `.g.dart`. (~80 annotations on ~20 enums.)
2. **CR-2.** `mock_daemon_client.dart` — drop `ProcessStartMode.detachedWithStdio` → `ProcessStartMode.normal`.
3. **CR-3.** `app_client.dart::_list` — nest `extra` under `filters: {…}` per FEAT-011 §list-request-shape.
4. **M-22.** Rename `DriftEvidence.agentAgentId` → `agentId` (drop the `agent_agent_id` snake_case typo).
5. **H-F1.** `Project.driftSource: String?` → `DriftSource?`.
6. **H-E1.** Remove `agentList(projectId: ...)` parameter (not in v1.0 contract).
7. **H-E2.** Add `orderBy` to `_list` plumbing (optional; ship behind a default).

Verify: build_runner + analyze + integration tests (us2/us3/us4 must reach assertions).

## Batch 2 — Systemic FR-004 + FR-002 + FR-075 + FR-067 deferred

Closes CR-5, CR-6, CR-7. **CR-4 (i18n, ~200 strings) is deferred to its own dedicated PR** — too large to bundle and politically distinct (translation backlog).

1. **CR-6.** Extract `lib/ui/widgets/runtime_state_views.dart` with `OutageState`, `HealthyEmptyState`, `ContractIncompatState`, `DegradedState`, `ErrorState` widgets. Update the 8 Phase 4-6 surfaces to route through them.
2. **CR-7.** Add `lib/ui/widgets/contract_checked_button.dart` that consumes `runtimeStateProvider` and renders disabled-with-tooltip on `contractVersionIncompatible`. Replace mutation buttons across Phase 4-6.
3. **CR-5.** Add command-palette registrations to `project_specs/module.dart` (Add project, Remove project, Open handoff, Submit, Supersede, Drift transition, Repair, Retry delivery, refresh-current-view).
4. **CR-4 (i18n):** open a follow-up tasks.md entry — separate PR.

## Batch 3 — Feature-level CRITICALs + Phase 4 traceability

Closes CR-8, CR-9, CR-10, H-A1, H-A2, H-A3.

1. **CR-8.** Extract `lib/domain/severity.dart` returning `{color, icon, label, semanticDescription}` per severity, consuming `ColorTokens`. Update `drift_view._severityColor/_severityIcon`, `project_card._DriftChip/_AttentionChip`, `drift_detail._Chip`.
2. **CR-9.** Wire `drift_detail_view._onRepair` to `DriftRepairHandoffLauncher.launch`. Add `initialMode` param to `openHandoffFlow` and `HandoffFlow`. Default to `engineeringExecution`; override to `driftRepair` from launcher.
3. **CR-10.** Add `currentFeatureChangePhase: WorkflowPhase?` and `currentDrivingHandoffId: String?` to `Project`. Update `data-model.md §1.1`. Render both on `ProjectCard._activeFeatureRow` and `_drivingMasterRow`.
4. **H-A1.** Wire `FirstLaunchResolution.run` into `main.dart` boot path; render banner from `firstLaunchOutcomeProvider` in `global_banner.dart`.
5. **H-A2.** Document `_DocLinks._docPathsFor` daemon-method dependency loudly (add a visible "Document resolution pending FEAT-011 v1.x" banner on Current Work) until the daemon method lands.
6. **H-A3.** Add `kind` field detection in Specs/Changes filtering (fall back to displayId prefix only when daemon doesn't supply kind).

## Batch 4 — Phase 5 HIGHs

Closes H-B3, H-B4, H-B5, H-B6, H-B7, H-B8, H-B9, H-B11. (H-B1, H-B2, H-B10, H-C2 → Batch 6 test rewrites; H-B10 daemon-coordination → defer with tracked task.)

1. **H-B3.** Add `showDatePicker` for deadline + helper-policy override dropdown driven by `HelperPolicyResolver.list()` in `handoff_flow._step5Optional`.
2. **H-B4.** Fix `_serializeDraft` to include `operator_label`, `selected_work_items`, `linked_feature_ids`, `linked_change_ids`.
3. **H-B5.** Surface project/master/feature-change/date-range filters in `HandoffListView` UI (data plumbing already in `HandoffListQuery`).
4. **H-B6.** Detect offline-master state explicitly when `assignmentState == submitted && deliveryStatus.kind == pending && targetMasterAgent.state != active`; render dedicated chip.
5. **H-B7.** Surface FR-038a degraded path inline on preview + step 5: banner naming the missing method, disable policy override picker.
6. **H-B8 + H-B9.** Import `HandoffStateValidator` in `supersede_flow.dart`; gate `_SupersedeConfirmDialog` on `priorHandoff.assignmentState ∈ {submitted, accepted}`; show disabled-with-reason otherwise.
7. **H-B11.** `handoff_flow._resolveRange` — fetch the daemon catalog via `featureChangeListProvider(projectId)` and pass it to the resolver (or surface "no catalog available" when daemon returns nothing).
8. **H-B10.** Add tasks.md follow-up "FR-072(a) drafted-row persistence requires daemon API extension (app.handoff.draft)." Skip in this PR.

## Batch 5 — Security + architecture + performance HIGHs

Closes H-D1, H-D2, H-D3, H-G1, H-G2, H-G3, H-G4, H-P1, H-P2, M-15, M-16.

1. **H-D1/D2/D3 + M-15.** Extract `lib/ui/widgets/safe_url_launcher.dart` with explicit allowlist (`http`/`https`/`mailto` only — drop `file:`). Use in `drift_detail_view`, `current_work_view._DocLinks`, `markdown_viewer`. File paths require a containment check or a confirmation modal.
2. **H-G1.** Add `MasterSummary.tryFromAgent(agent, masterClassCapabilities)` factory; route every construction site through it.
3. **H-G2.** Surface `masterClassCapabilities.isEmpty` as a degraded state with operator notice (banner or log entry).
4. **H-G3.** Extract `lib/core/json_utils.dart#withAsOfDefault` consumed by all 4 callers.
5. **H-G4.** Reset `selectedProjectIdProvider` BEFORE the `appClient.projectRemove` call in `remove_project._submit`.
6. **H-P1.** `handoff_flow.dart` — hoist `TextEditingController` to `late final` member field; dispose in `dispose`.
7. **H-P2.** `handoff_flow.initState` — call `_resolveRange()` after seeding `_workItemExpr` from `widget.initialPrimaryWorkItem`.
8. **M-16.** Add `generated_prompt_text` to `_redactedKeys` in `rotating_file_logger.dart`.

## Batch 6 — Test rewrites

Closes H-B1, H-B2, H-C2.

1. **H-B1 + H-B2.** Rewrite `us3_handoff_flow.dart` to:
   - `pumpWidget(AgentTowerControlPanel)`, navigate to `/project_specs/projects`, tap a project card, tap Open Handoff.
   - Drive the Stepper via `tester.tap` + `tester.enterText`.
   - Stopwatch from "open handoff modal" to "submit" → assert `< 30 s` per SC-003.
   - For SC-004: render `PromptSkeleton.render()` twice and assert byte-equality; also assert mock-daemon `app.handoff.submit` received the same `generated_prompt_text` string.
2. **H-C2.** Rewrite `us4_drift.dart` to:
   - Poll the project-card drift badge widget after mock-daemon emits a new finding.
   - Assert badge transition within 60 s via `tester.pumpUntil(timeout: 60s)`.

## Batch 7 — Remaining MEDIUMs

Cherry-pick highest ROI: M-1, M-3, M-4, M-5, M-6, M-7, M-8, M-9, M-10, M-11 (tasks.md entry only), M-12, M-13, M-14, M-17, M-18, M-19, M-20, M-21.

Skip M-2 (closed transitively by Batch 1). Defer M-5 polish to NIT batch.

## Batch 8 — LOWs and NITs (polish commit)

Single commit consolidating L-1..L-18 and N-1..N-14, skipping any superseded by earlier batches. Includes deletion of `_projectProvidersRef` tombstones and updating stale comments.

## Out-of-scope / explicit defers

- **CR-4 i18n sweep** — separate PR (~200 string moves; not appropriate to bundle).
- **H-B10 FR-072(a) drafted-row persistence** — requires `app.handoff.draft` daemon method; tasks.md follow-up.
- **M-11 FR-064 live-update streaming** — requires daemon SSE/WebSocket support; tasks.md follow-up.
- **All Phase 7 (US5 validation) + Phase 8 (US6 attention queue)** — out of scope for this fix sprint.

## Verification cadence

After each batch:
1. `flutter pub get` (if pubspec changed)
2. `dart run build_runner build --delete-conflicting-outputs`
3. `flutter analyze` — must report 0 errors / 0 new warnings in modified files
4. `flutter test` — unit/widget suite must pass
5. Commit with finding-id citations in the message body.

Integration test verification (us2/us3/us4 via Xvfb) deferred until Batch 6 because Batches 1-5 substantially rewrite the surfaces under test.
