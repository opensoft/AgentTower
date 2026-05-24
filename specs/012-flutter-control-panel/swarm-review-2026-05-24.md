# Swarm code review — branch `012-flutter-control-panel`

**Date:** 2026-05-24
**Scope:** 20 commits ahead of `main`, ~27,607 insertions across 236 files (Phase 4 US2 + Phase 5 US3 + Phase 6 US4 + spec artifacts).
**Method:** 12 specialist reviewers spawned in parallel, each scoped to a distinct concern.

Reviewers:
1. Wire-protocol + FEAT-011 conformance
2. Freezed/JSON model correctness
3. Architecture + Riverpod patterns
4. FR traceability — Phase 4 (US2)
5. FR traceability — Phase 5 (US3)
6. FR traceability — Phase 6 (US4)
7. Local-first invariants + security
8. Accessibility / i18n / keyboard
9. Test discipline + fixture correctness
10. Lifecycle validators + state machines
11. Error handling + runtime states + UX polish
12. Performance budgets + code-quality polish

---

## CRITICAL (10) — must fix before merge

### CR-1. Enum `@JsonValue` annotations missing — most `fromJson` calls will throw
**Reviewers:** freezed-models · test-discipline (independently flagged)
**Files:** `lib/domain/models/common_enums.dart` (entire file) + every `.g.dart` it feeds
**Symptom:** `json_serializable` codegen emits identifier maps like `MasterStatus.waitingForInput: 'waitingForInput'`, but the wire format is snake_case (`waiting_for_input`). The `wireValue`/`fromWire` helpers are **dead code** — codegen never consults them. Every `fromJson` on a row containing a multi-word enum will throw `CheckedFromJsonException`.
**Confirmed affected enums:** `MasterStatus`, `AgentState` (partiallyConfigured/logAttached/logDetached), `PaneState` (all 4), `Stage` (specReady/mergeReady/driftRepair), `ExecutionStatus` (notStarted/atRisk), `RunState` (failedToStart), `DriftStatus` (newFinding→new, reviewNeeded, repairPlanned, acceptedAsBuilt), `DriftSource` (staticCheck, agentReview, operatorReport, testResult), `DriftScopeKind` (featureChange), `DriftEvidenceKind` (all multi-word), `EntrypointType`, `DemoReadinessState`, `AttentionClass`, `HandoffMode` (all), `PolicySource` (all), `OnboardingMilestone` (all), `Workspace` (all), `RuntimeStateKind` (all), `NotificationLifecycle` (inHistory), `HistoryEntryKind` (all multi-word).
**Why unit tests pass:** the 14 passing tests have zero `Fixtures.*` + `fromJson` round-trip coverage. Integration tests in this branch have **never been bench-executed** (the harness has its own CRITICAL — see CR-2). The bug surfaces the moment they run.
**Fix:** add `@JsonValue('wire_value')` to every value whose Dart identifier differs from the wire spelling, OR add `@JsonEnum(valueField: 'wireValue')` on each enum (Dart 2.17+ / json_serializable 6.x). Regenerate.

### CR-2. `MockDaemonClient.stop` is broken — integration tests cannot reach the assertions
**Reviewer:** test-discipline
**File:** `apps/control_panel/test/helpers/mock_daemon_client.dart:71` + :103-127
**Symptom:** harness launches with `ProcessStartMode.detachedWithStdio`; both `Process.kill` and `Process.exitCode` raise `Bad state: Process is detached` on detached processes. Every integration-test tearDown throws. Flagged in commit a591421 as a deferred Phase-2 harness bug; still unrepaired in Phases 5/6.
**Fix:** switch to `ProcessStartMode.normal` (the harness IS the child; detachment is unnecessary). SIGTERM + exitCode-wait then works as written.

### CR-3. `AppClient._list` splats filters at top level instead of nesting under `filters: {}`
**Reviewer:** wire-protocol
**File:** `apps/control_panel/lib/core/daemon/app_client.dart:705-728`
**Symptom:** per FEAT-011 `app-methods.md:169-177`, list-request shape is `{limit, cursor_next, order_by, filters: {…}}`. Current code spreads `extra` keys at top level. Every call passing filters (event `agent_id`, container `state`, the new Phase 5/6 handoff/drift filters) will be silently dropped at best, rejected with `validation_failed` at worst.
**Fix:** `params['filters'] = {...?extra}` rather than `...?extra` at top level.

### CR-4. FR-067 systemic violation — ~200 hardcoded English strings, none localized
**Reviewer:** a11y/i18n
**Files:** every Phase 4-6 widget under `lib/features/project_specs/**` + `lib/ui/widgets/markdown_viewer.dart`
**Symptom:** zero `AppLocalizations`/`context.l10n` references anywhere in scope. The localization layer exists (`lib/core/l10n/app_localizations_en.dart` has appTitle, banner strings, settings sections) but Phase 4-6 widgets bypass it entirely. Spec FR-067: "ALL user-facing strings MUST route through a single localization layer."
**Fix scope:** one PR adds ~200 keys to `app_localizations_en.arb`, wires `AppLocalizations.delegate` in `app.dart`, replaces every `Text('literal')` in scope.

### CR-5. FR-075 systemic violation — no Phase 4-6 actions registered with the command palette
**Reviewer:** a11y/i18n
**Files:** every Phase 4-6 feature; `lib/core/shortcuts/command_palette.dart` (infra) is intact
**Symptom:** `Ctrl+K`/`Cmd+K` opens an empty palette. None of Add project, Remove project, Open handoff flow, Submit, Supersede, Open Drift detail, Transition drift, Repair, Retry delivery, Refresh, Workspace-switch are registered.
**Fix:** each feature module's `register*()` adds `commandRegistryProvider.notifier.register(...)` entries for its primary actions.

### CR-6. FR-004 5-state coverage missing on 8 of 9 Phase 4-6 surfaces
**Reviewer:** error-handling
**Files:** `current_work_view.dart`, `specs_view.dart`, `changes_view.dart`, `handoff_list_view.dart`, `handoff_detail_view.dart`, `drift_view.dart`, `drift_detail_view.dart`, `drift_repair_handoff_launch.dart`. Only `projects_view.dart:31` partially covers it (handles `runtimeUnreachable`, ignores `contractVersionIncompatible`/`runtimeDegraded`/`runtimeHealthyEmpty`).
**Symptom:** when the daemon is unreachable each view renders a raw `'Failed to load X: $err'` instead of the canonical FR-004 outage UX.
**Fix:** extract `_OutageState` + `_HealthyEmpty` widgets into `lib/ui/widgets/runtime_state_views.dart`; route every live-data view through them.

### CR-7. FR-002 mutation-disable invariant globally violated on contract-incompatible
**Reviewer:** error-handling
**Files:** every mutation surface — Add/Remove project, Submit handoff, Retry delivery, Drift transition, Supersede, etc.
**Symptom:** when the runtime is `contractVersionIncompatible` all mutation buttons remain enabled and fail at the round-trip with `Transition failed: $e`. Spec is explicit: "RENDERS mutation buttons but disables them with inline explanation tooltip — never hidden."
**Fix:** introduce a `ContractCheckedButton` / `Mutationgate` that consults `runtimeStateProvider`; replace every `FilledButton`/`IconButton`/`PopupMenuItem` that triggers a mutation.

### CR-8. R-15 severity palette ignored — likely WCAG-AA contrast failures
**Reviewers:** a11y · Phase 6 traceability
**Files:** `lib/features/project_specs/drift/drift_view.dart:120-132` + `project_card.dart` chips
**Symptom:** `_severityColor` maps critical→`colorScheme.error`, high→`colorScheme.tertiary`, warning→`colorScheme.secondary`, info→`colorScheme.primary` — then paints `colorScheme.onPrimary` as foreground over those backgrounds. `onPrimary` is the correct foreground only over `primary`; on `error/tertiary/secondary` contrast is undefined and likely drops below WCAG-AA 4.5:1. The project ships `ColorTokens.severityInfo/Warning/High/Critical` (`lib/ui/theme/color_tokens.dart:59-66`) explicitly tuned for R-15 — never consumed. R-22 redundancy (icon+text+color) is also missing: severity text label never appears in the drift row.
**Fix:** extract `domain/severity.dart` returning `{color, icon, label}`; consume in `drift_view`/`project_card`/`drift_detail`.

### CR-9. FR-035 "Repair this drift" is a SnackBar nudge, not a launch
**Reviewers:** Phase 6 traceability · error-handling
**File:** `lib/features/project_specs/drift/drift_detail_view.dart:97-122`
**Symptom:** the button calls `_onRepair` which shows a SnackBar instructing the operator to *go* to Current Work; the existing `DriftRepairHandoffLauncher.launch(...)` is never called. Even when it would be called, the launcher does not actually pre-fill `HandoffMode.driftRepair` — it shows a second SnackBar nudging the operator to pick it manually (`handoff_flow.dart:49` defaults to `engineeringExecution`). FR-035 mandates pre-fill of affected feature(s), `drift_repair` mode, and the drift signal id.
**Fix:** wire `_onRepair` to `DriftRepairHandoffLauncher.launch`; add an `initialMode` parameter to `openHandoffFlow` / `HandoffFlow` and thread it through.

### CR-10. FR-025 + SC-002 violation — current phase/status not surfaced on the project card
**Reviewer:** Phase 4 traceability
**Files:** `project_card.dart:168-191` (renders only `'Active: $id'`); `lib/domain/models/project.dart:24-50` and `data-model.md §1.1` both omit the field from the Project freezed shape
**Symptom:** SC-002's 5-second card-only attribution **cannot be met** today — the operator must drill into Current Work to see stage / execution-status / phase. Same applies to FR-029's canonical driver sentence: the card shows `Driver: <id>` only, not the "X is driving FEAT-N under handoff H" attribution that DrivingMasterIndicator renders inside Current Work.
**Fix:** add `currentFeatureChangePhase` (and `currentDrivingHandoffId`) to `Project` and the daemon row; render both on the card.

---

## HIGH (24)

### Phase 4 / US2

- **H-A1. FR-076 first-launch banner is dead code.** `FirstLaunchResolution.run` + `firstLaunchOutcomeProvider` have **zero consumers** in `lib/`. `global_banner.dart:18-19` early-returns unless `kind == contractVersionIncompatible` — the FR-076 branch promised in its docstring is unimplemented. On launch the app never restores last-active-project, never shows the unresolved-project banner, and never attempts adopted-agent inference.
- **H-A2. `_DocLinks._docPathsFor` is a hardcoded stub** returning `{'PRD': null, 'Architecture': null, …}` regardless of payload. FR-027's one-click links to PRD/architecture/roadmap/feature spec/OpenSpec change render as five disabled chips with no operator-visible explanation.
- **H-A3. Specs view does not filter to features; Changes view filter is fragile** (`!displayId.startsWith('FEAT-')` swallows any prefix outside `FEAT-`/`CHG-`).
- **H-A4. FR-078 sort/filter persistence not implemented** for any Phase-4 list view.

### Phase 5 / US3

- **H-B1. T097 violated — `us3_handoff_flow.dart` sidesteps the widget tree entirely.** Zero `tester.tap`/`enterText`/`pumpWidget` calls; no Stopwatch, no 30-s budget assertion. Exactly the "vacuous pump-and-assert" shape T097 explicitly forbids.
- **H-B2. SC-004 byte-for-byte assertion is tautological.** Same `previewText` variable passed to both "preview" and "submit-time" sides; the daemon-side fixture hardcodes a different `generated_prompt_text` and the test never observes that mismatch.
- **H-B3. FR-037 deadline + helper-policy override missing from UI.** `_deadline` and `_operatorOverrideOfPolicyId` are declared state but never bound to any widget — permanently null at submission.
- **H-B4. FR-042 fields missing from submit payload.** `_serializeDraft` omits `operator_label`, `selected_work_items`, `linked_feature_ids`, `linked_change_ids`. The Handoff freezed class marks these required; submission relies on daemon back-fill and `Handoff.fromJson` will throw if absent.
- **H-B5. FR-045 list filters partial.** `HandoffListQuery` carries 6 dimensions, but `HandoffListView` UI exposes only `assignmentState`. Project/master/feature-change/date-range filters are missing.
- **H-B6. FR-072(c) offline-master state not named in UI.** Chip renders `Delivery: pending` regardless of whether the master is offline or queued-but-imminent.
- **H-B7. FR-038a degraded path is silent.** When `helperPolicyResolve` throws, `degradedSnapshot()` silently substitutes a `policyId: 'unset'` snapshot. Operator has no visual indication; the handoff ships with the placeholder policy.
- **H-B8. `HandoffStateValidator` is dead code in Phase 5.** Zero call sites in handoff feature; supersede/cancel paths bypass it.
- **H-B9. `supersede_flow.dart` doesn't check prior `assignmentState`.** Per FR-044, supersede is only legal from `submitted`/`accepted`. Operator can click on any state; daemon rejects after round-trip.
- **H-B10. FR-072(a) failure context lives in widget `setState`, not in a daemon-persisted `drafted` Handoff.** Navigation away loses the draft and the failure context entirely; `failureContext` model is unused on submission-failure path.
- **H-B11. FR-039 production bug: empty catalog → every range id becomes fake `(excluded: deferred)`.** `handoff_flow.dart:223` passes `catalog: const []` so the resolver brands every legitimate id as deferred. Resolver fabrication of `deferred` for unknown ids is also semantically wrong (could be `unknown`/`not_found`).

### Phase 6 / US4

- **H-C1. FR-035 mode never pre-filled** — `openHandoffFlow` accepts no `initialMode`, defaults to `engineeringExecution`. SnackBar tells operator to pick drift_repair manually.
- **H-C2. SC-005 60-second budget assertion missing.** No Stopwatch, no `pumpUntil`, no badge-transition observation anywhere in `us4_drift.dart`. T112 explicitly forbade this anti-pattern.
- **H-C3. R-15 redundancy (FR-066) violated** — drift row shows severity color + icon but no text label; colorblind operators get incomplete signal.

### Security / Local-first

- **H-D1. Daemon-supplied `evidence.url` launched without scheme allowlist** (`drift_detail_view.dart:187`). A `javascript:`/`data:`/`file:///etc/shadow` URL in evidence would launch.
- **H-D2. `Uri.file(e.filePath!)` opens arbitrary daemon-supplied path** (`drift_detail_view.dart:197-199`). No path containment, no confirmation modal. Worst-case: `/etc/shadow`, `~/.ssh/id_rsa`, executable `.desktop` file.
- **H-D3. `_DocLinks._openExternal` lacks scheme allowlist** (`current_work_view.dart:219-227`). Currently dormant because doc paths are null stubs; will fire on every doc chip once the daemon resolution method lands.

### Wire-protocol

- **H-E1. `agentList(projectId: ...)` will be rejected by daemon.** Per `app-methods.md:203` the v1.0 agent filter set is `{role, capability, container_id, log_attached}` — `project_id` is **not** accepted. Phase-3 code; carried forward unchanged.
- **H-E2. `_list` never sends `order_by`.** Coverage gap; locks every list view into the daemon default.

### Models

- **H-F1. `Project.driftSource` typed `String?` instead of `DriftSource?`** (`project.dart:40` vs data-model.md §1.1 line 37). Codegen accepts any string; UI can't pattern-match the documented variants.

### Architecture

- **H-G1. `MasterSummary.tryFromAgent` is documented but never implemented.** Doc tells callers to use it; only the freezed factory + `fromJson` exist. FR-071 invariant is unenforced.
- **H-G2. `masterClassCapabilities` degraded path is silent.** Empty-set return on registry failure causes every agent to silently fail the qualification check; no banner, no log entry. Operators see Master rows disappear with no signal.
- **H-G3. `_withAsOf` helper duplicated across 4 files with subtle divergence.** Three of four only check `as_of`; agent_ops also checks `asOf`. Double-stamping on the divergent path.
- **H-G4. `selectedProjectIdProvider` race during project removal.** `selectedProjectProvider` watches `projectDetailProvider(id).future` until id is reset to null; the daemon removes it first, so a mid-fetch detail call can throw `not_found` before the reset propagates.

### Performance

- **H-P1. `TextEditingController` recreated in `build()`** (`handoff_flow.dart:142`). Cursor resets every keystroke, controller leaked. Flagged by 4 separate reviewers.
- **H-P2. `HandoffFlow.initState` does not pre-resolve `initialPrimaryWorkItem`.** Preview affordance gated on `_resolved.isEmpty`; operator MUST type before they can proceed — defeats SC-003's pre-fill scenario.

---

## MEDIUM (22)

- **M-1.** Drift "Transition" `PopupMenuButton.child = FilledButton.icon(onPressed: null)` swallows taps; menu never opens (`drift_transition.dart:41-45`). Confirmed by 2 reviewers.
- **M-2.** `_serializeDraft` `helper_policy_snapshot` round-trip will fail at integration time due to CR-1 (`policy_source: 'baked_default'`).
- **M-3.** `app.handoff.preview` exposed in client but never called from preview UI — preview is rendered client-side from `PromptSkeleton`, bypassing daemon dry-run validation.
- **M-4.** `RemoveProjectDialog` confirmation copy omits repo path that the spec clarify round explicitly required.
- **M-5.** `AddProjectDialog` "absolute path" check is shallow — does not reject `..`, trailing whitespace, `~`, or relative segments mid-string.
- **M-6.** FR-040 "Operator Notes" rendered as an unspec'd 7th section after Stopping & Escalation; FR-040 specifies exactly 6 sections "in this order."
- **M-7.** `featureRangeResolver._parsePoint` compiles RegExp per call (twice per `resolve()`); should be `static final`.
- **M-8.** `PromptSkeleton.render()` runs on every `HandoffPreviewView` rebuild; should be memoized.
- **M-9.** `FeatureRangeResolver.resolve` runs on every keystroke; should debounce.
- **M-10.** `Projects` view uses eager `Wrap` — FR-080 violation at 50+ project scale.
- **M-11.** FR-064 live-update gap unscheduled. Code comments cite T155 as the follow-up; T155 is the network-trace test, not live-update polish. No task wires streaming subscriptions.
- **M-12.** Latency instrumentation (`LatencyCapture`) plumbed but never invoked in any Phase 4-6 mutation surface. FR-074 200ms p95 log will have a hole.
- **M-13.** SnackBar errors expose raw `e.toString()` Dart class names everywhere. Need `humanizeDaemonError` helper.
- **M-14.** `supersedeHandoff` silently passes empty `priorHandoffId` when both ids are null; no defense-in-depth.
- **M-15.** `markdown_viewer.dart` `_allowedSchemes` includes `file:` — daemon-supplied markdown body can embed `[ssh key](file:///home/op/.ssh/id_rsa)`.
- **M-16.** `_redactedKeys` denylist (`rotating_file_logger.dart:47-53`) does not include `generated_prompt_text`. Defense-in-depth gap if a future log site stringifies a submit envelope.
- **M-17.** Drift transition `_onSelected` does not re-check `DriftStateValidator.isValidTransition` before calling daemon; menu filter is the only client gate.
- **M-18.** `handoff_detail_view` does not auto-refresh on delivery-status change. Manual refresh only.
- **M-19.** `supersedeHandoff` is orphan UI wiring — no widget calls it.
- **M-20.** `dashboard` does not range-guard `recent_limit` (contract caps `[1, 50]`).
- **M-21.** `sendInput` does not enforce 16 KiB canonical-JSON payload cap from the contract.
- **M-22.** `DriftEvidence.agentAgentId` field auto-renames to `agent_agent_id` via `build.yaml` snake_case rename — almost certainly a typo for `agent_id`. Wire payloads will never match.

---

## LOW (18)

- L-1. `_severityIcon` info vs warning both use `info`/`info_outline` family — colorblind operators get insufficient differentiation.
- L-2. `RemoveProjectDialog` half-clear risk: daemon succeeds → local clear succeeds → rollback impossible if intermediate step throws.
- L-3. `_severityColor` non-text contrast (3:1) at 14px icon size needs human contrast verification under both `ColorTokens.light()` and `dark()`.
- L-4. `Stepper` widget a11y limitations — focus does not auto-advance to first input of next step.
- L-5. `EdgeInsets.all(16)`/`all(24)` hardcoded everywhere — `visualDensity` from R-24 is not honored on bespoke Padding/Container chrome.
- L-6. Pull-to-refresh present in Phase 3 surfaces, absent in every Phase 4-6 list.
- L-7. `current_work_view._open*` SnackBar stubs underline text as if clickable then pop a SnackBar; should be tooltip + non-underlined.
- L-8. `_formatTime` ignores locale and timezone — bench operators across timezones see local-time stamps.
- L-9. `Quick-actions` on card menu omit "Run validation" enumerated in FR-025.
- L-10. `evidence.agentAgentId` is dropped silently in the detail view even after the typo fix.
- L-11. `handoff_detail_view._statusBar` evidence loop is bounded but eager — fine for now.
- L-12. `_DocLinks` duplicate `featureChangeDetailProvider` fetch — parent already loaded the same FC; should pass down.
- L-13. `_workItemExpr` should drive from controller listener after H-P1 fix.
- L-14. `MarkdownViewer._showRejected` echoes full unsanitised href in SnackBar; should truncate.
- L-15. `add_project.dart:99` regex accepts `C:/foo` (forward slash) but Windows canonicalizer expects `C:\foo`. Add hint.
- L-16. `drift_transition.dart` controller in `_promptNote` is allocated then dropped (no dispose).
- L-17. `RepoStateKind`/`DriftScopeKind`/`DriftEvidenceKind` have `fromWire(orElse:)` for forward-compat; `HandoffDeliveryStatusKind` does not. Inconsistent.
- L-18. `handoffSupersede` invalidates `handoffDetailProvider(priorHandoff.handoffId ?? '')` — empty-string family key is a useless cache entry.

---

## NIT (14)

- N-1. `_projectProvidersRef` "unused-import dodge" in `handoff_flow.dart:313-314` and `drift_repair_handoff_launch.dart:58`. Drop the import.
- N-2. `module.dart:43-46` declares `project_specs/drift` contract minimum with a comment that says it lands in Phase 6 — but drift IS registered there now (stale comment).
- N-3. Phase-2 "stub-removed" tombstone comments in `fixture_builders.dart` can be deleted.
- N-4. `_buildUs4Fixture` `Map.from(drift)..['status']` reads more clearly than spread literal.
- N-5. `_DropdownButtonFormField.initialValue` name is misleading but functionally correct — Flutter 3.27+ rename. (Performance reviewer claim of bug rejected after verification.)
- N-6. `_serializeDraft` could use a `..toJson()` extension for symmetry.
- N-7. `changes_view.dart` filter via `!displayId.startsWith('FEAT-')` documented as fragile; track until daemon `kind` field.
- N-8. `_legalNextStates` static helper could move onto `DriftStateValidator` as `nextStates(from)`.
- N-9. Terminal-state chip in `drift_transition.dart` could add a tooltip ("No further transitions allowed per FR-034").
- N-10. `MarkdownViewer` "Open externally" `TextButton.icon` lacks `tooltip:` / `Semantics.label` for icon-only fallback.
- N-11. SnackBar messages are not dismissible-with-keyboard (no `action:`).
- N-12. `card.dart` `PopupMenuButton` with 6 items will exceed 8 in Phases 7/8; consider submenu.
- N-13. `_severityIcon` + `_severityColor` palette logic in `drift_view.dart` is duplicated in `drift_detail_view.dart` `_Chip` — extract `DriftSeverityChip`.
- N-14. `helperPolicyResolver.resolve` mutates caller-owned `raw` map; use `_withAsOf` spread pattern.

---

## Verified-clean checks

Independently validated and no violation found:
- **FR-001 outbound prohibition:** only `release_feed_check.dart` performs network I/O; HTTPS scheme enforced in constructor; `followRedirects = false`; silent-fail per R-42.
- **FR-001 file-reads:** every `File(`/`Directory(`/`readAsString` hit is inside `core/persistence/`, `core/logging/`, or `features/settings/doctor.dart`. No feature/domain code reads from disk.
- **FR-003 session-token non-persistence:** `_sessionToken` is heap-only, nulled in `teardown()`, never serialised. Logger redacts the key.
- **FR-003a/b framing strictness:** per-line caps + UTF-8 strict mode intact after Phase 4-6 additions.
- **FR-005 daemon-authoritative:** no Phase 4-6 code invents domain state locally; in-memory handoff drafts are acceptable per data-model.md §2.1.
- **FR-069 persistence scope:** `clearProjectScopedState` writes only the FR-069 enumerated keys.
- **FR-079 markdown HTML disabled:** `flutter_markdown 0.7.4` default `extensionSet` does not include `InlineHtmlSyntax`; no `--enable-html` flag passed.
- **Idempotency keys:** every Phase 4-6 mutation method auto-stamps `idempotency_key` via `MutationKeys.fresh()` and accepts caller-provided keys for retry semantics. Read-only methods correctly omit them.
- **Envelope unwrapping:** all `_detail` and mutation calls correctly route through `_unwrapRow`; documented exceptions (`sendInput`, `scan.*`) use `_unwrapResult`.
- **Validator parity (T040-T043):** Pane, Drift, Validation-run, Handoff, FeatureChange-stage validators all encode the FR-spec'd transition matrices correctly. The problem is non-use (H-B8), not correctness.
- **FR-043 queue delivery:** no direct-send path; submission goes through `app.handoff.submit` and the daemon owns delivery.
- **FR-081 supersede record-only:** confirmation copy is explicit; no queue cancellation code path.
- **`HandoffListQuery`/`DriftListQuery` `==`/`hashCode`:** both implement correctly, all fields included; Riverpod `.family` autoDispose works.
- **Async `context.mounted` guards:** every `await`-then-`context` site in Phase 4-6 properly guards or uses `State.mounted`.
- **FR-080 virtualization:** Specs, Changes, Handoff List, Drift View all use `ListView.builder` (lazy). Only Projects view is eager (M-10).
- **Module bootstrap pattern:** Phase 4's `registerProjectSpecs()` mirrors Phase 3's `registerAgentOps()` shape-for-shape.

---

## Top-priority fix sequence (one PR each)

| # | PR | Scope | Closes |
|---|---|---|---|
| 1 | **enum serialization** — add `@JsonValue` to every multi-word enum, regenerate | `common_enums.dart` + 11 `.g.dart` files | CR-1 (unblocks every integration test) |
| 2 | **wire-shape filters** — nest under `filters: {}` in `_list` | `app_client.dart:705-728` + tests | CR-3 |
| 3 | **harness repair** — `ProcessStartMode.normal` in `MockDaemonClient` | `mock_daemon_client.dart:71` | CR-2 |
| 4 | **localization sweep** — wire `AppLocalizations` + ~200 keys | every Phase 4-6 widget + `app_localizations_en.arb` | CR-4 |
| 5 | **command-palette registration** — feature-module-side registrations | each `module.dart` | CR-5 |
| 6 | **runtime-state widgets** — extract `_OutageState` / `_HealthyEmpty`; route 8 surfaces | `ui/widgets/runtime_state_views.dart` + 8 views | CR-6 |
| 7 | **mutation-gate** — `ContractCheckedButton` consuming `runtimeStateProvider` | new widget + every mutation site | CR-7 |
| 8 | **severity palette** — `domain/severity.dart` + `ColorTokens` consumer | drift_view, project_card, drift_detail | CR-8 |
| 9 | **FR-035 launch wire-up** — call `DriftRepairHandoffLauncher` + `initialMode` parameter | drift_detail_view + handoff_flow + openHandoffFlow | CR-9 |
| 10 | **Project.currentPhase** — add field to model + daemon row + card render | project.dart + card + data-model.md | CR-10 |
| 11 | **integration-test rewrite (us3)** — drive real taps, Stopwatch, SC-003 budget | us3_handoff_flow.dart | H-B1 + H-B2 |
| 12 | **integration-test rewrite (us4)** — pump-until badge transition, 60s budget | us4_drift.dart | H-C2 |
| 13 | **FR-076 wiring** — render banner; resolve in main.dart boot path | global_banner + main.dart | H-A1 |
| 14 | **scheme-allowlist sweep** — extract `safe_url_launcher.dart`; use in drift + current_work | drift_detail_view + current_work_view | H-D1 + H-D2 + H-D3 |

After this list, the remaining HIGH/MEDIUM items can be batched per-feature.

---

## Headline numbers

- **10 CRITICAL** — 4 systemic blockers (enum codegen, FR-067 i18n, FR-075 palette, FR-004 5-state coverage), 3 wire-shape (filters splat, mutation-gate, `Fixtures` harness), 3 feature-specific (`Repair this drift`, FR-076 banner, FR-025 phase).
- **24 HIGH**, **22 MEDIUM**, **18 LOW**, **14 NIT** — total **88 findings** across 12 reviewers.
- Strongest cross-reviewer signal: **CR-1 (enum codegen)** independently surfaced by 2 reviewers; **TextEditingController in build()** by 4; **`_projectProvidersRef` smell** by 5; **`SupersedeFlow` gaps** by 3.
- All `Verified-clean` items (16) are infrastructure that survived Phase 4-6 additions intact.

The branch is **not merge-ready**. Recommend running the top-10 PRs (which collectively unblock the integration tests and address the systemic FR violations) before any further phase work or `/speckit.analyze` re-run.
