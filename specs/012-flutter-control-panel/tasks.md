---
description: "Task list for FEAT-012 Flutter Desktop Control Panel"
---

# Tasks: Flutter Desktop Control Panel for Local Operator Workspaces

**Input**: Design documents from `/specs/012-flutter-control-panel/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Test tasks ARE included. plan.md establishes a per-US integration test plan (`apps/control_panel/integration_test/us[1-6]*.dart`) plus a Python mock-daemon harness (research R-17). Unit + widget + golden tests are also planned.

**Organization**: Tasks are grouped by user story. Each US phase delivers an independently shippable + independently testable slice.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

This is a multi-language monorepo (per plan.md §Structure Decision). Python sources at `src/agenttower/` are untouched. The Flutter app lives entirely under `apps/control_panel/`. All file paths in this document are repo-root-relative.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Bootstrap the Flutter app project so foundational + story work can begin.

- [X] T001 Create directory tree `apps/control_panel/{lib,assets,test,integration_test,test_harness,tools}` per plan.md §Project Structure.
- [X] T002 Create `apps/control_panel/pubspec.yaml` declaring Flutter SDK 3.27 stable, Dart 3.5+, and dependencies enumerated in plan.md §Primary Dependencies (flutter_riverpod 2.x, freezed, json_serializable, flutter_markdown, url_launcher, local_notifier, window_manager, path_provider, logger, flutter_localizations, intl, package_info_plus). Also add dev_dependencies: build_runner, freezed, json_serializable, flutter_lints, alchemist, integration_test. **Known bench deviation (2026-05-23):** the Phase 3 T009 `flutter create` step was run against bench-global Flutter 3.44.0 because `fvm install 3.27.0` was not viable in the bench (FVM clone path blocked by a bench-global git rewrite of `https://github.com/`). The `pubspec.yaml` pin remains 3.27 stable; T160 (added below) tracks re-pinning the bench. See `flutter-testing-plan.md` §"2026-05-23 execution notes" for full context.
- [X] T003 [P] Pin Flutter version via `apps/control_panel/.fvm/fvm_config.json` (research R-01) and document the FVM use in `apps/control_panel/README.md`.
- [X] T004 [P] Create `apps/control_panel/analysis_options.yaml` enabling `flutter_lints` and project-specific rule overrides (no implicit-dynamic, strict-inference).
- [X] T005 [P] Create `apps/control_panel/l10n.yaml` configuring ARB → Dart codegen (research R-08) with `arb-dir: assets/l10n`, `template-arb-file: en.arb`, `output-localization-file: app_localizations.dart`.
- [X] T006 [P] Create `apps/control_panel/assets/l10n/en.arb` (initial MVP locale) with stub keys for the FR-002 / FR-076 / FR-082 banner messages and the FR-009 Settings labels.
- [X] T007 [P] Create `apps/control_panel/assets/icons/` and source severity icons (info/warning/high/critical) per research R-15 palette.
- [X] T008 [P] Create `apps/control_panel/tools/{package_windows.ps1,package_macos.sh,package_linux.sh,release_feed_check.dart}` as stub scripts (final packaging logic lands in Phase 9; the files are placeholders so the structure is auditable).
- [X] T009 ⛔ **PHASE-BLOCKING OPERATOR ACTION** — Configure Flutter desktop targets (`flutter config --enable-windows-desktop --enable-macos-desktop --enable-linux-desktop`) and run `flutter create --platforms=windows,macos,linux .` from `apps/control_panel/` to materialize platform stubs. This session ran without Flutter SDK in the sandbox; the operator must run the two commands on a workstation with Flutter ≥ 3.27 installed. See `apps/control_panel/README.md` §Operator prerequisites for the exact command sequence. **Phases 2 → 9 cannot pass `flutter analyze` / `flutter test` without this step.** When you complete it, change the marker to `[X]` so Phase 3 unblocks cleanly.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented. Includes daemon connectivity, persistence, domain-model scaffolding, app shell, theme/density tokens, and the test harness.

**⚠️ CRITICAL**: No user story work can begin until Phase 2 is complete.

### Daemon connection (FR-001/002/003/004/005, FEAT-011 contract)

- [X] T010 Implement `apps/control_panel/lib/core/daemon/socket_client.dart` — Unix-socket client using `dart:io` `Socket.connect(InternetAddress(path, type: InternetAddressType.unix), 0)`. Enforce FEAT-011 FR-003a per-line caps (1 MiB request / 8 MiB response) and FR-003b framing strictness (UTF-8, `\n`-terminated, reject `\r` / `\x00` / trailing content). Research R-04. Satisfies FR-001 + FR-060 (refuses any non-local target — no host/port field is exposed anywhere in the client API).
- [X] T011 [P] Implement `apps/control_panel/lib/core/daemon/envelope.dart` — parser for `{ok, app_contract_version, result}` and `{ok, app_contract_version, error: {code, message, details}}` envelopes (FEAT-011 FR-033).
- [X] T012 [P] Implement `apps/control_panel/lib/core/daemon/errors.dart` — Dart sealed class with one variant per FEAT-011 27-entry closed-set error code. Map each to user-facing copy via i18n keys. Highlight `app_contract_major_unsupported` and `host_only` per `contracts/app-methods-consumed.md` §8.
- [X] T013 Implement `apps/control_panel/lib/core/daemon/session.dart` — session lifecycle: call `app.hello` on connect, hold token in-memory only (FR-003), re-bootstrap on socket close / daemon restart / contract-version change / explicit Retry.
- [X] T014 Implement `apps/control_panel/lib/core/daemon/app_client.dart` — typed wrappers for the bootstrap-level FEAT-011 methods (`app.preflight`, `app.hello`, `app.readiness`, `app.dashboard`); per-story method wrappers land in their respective phases.
- [X] T015 [P] Implement `apps/control_panel/lib/core/daemon/contract_version.dart` — minimum-required-version registry per surface (FR-002) + Riverpod `Provider<ContractCompat>` driving FR-002 banner + per-surface degradation state.

### Persistence (FR-003/061a/069/070/078/082)

- [X] T016 Implement `apps/control_panel/lib/core/persistence/paths.dart` — per-OS app-data directory resolution via `path_provider` `getApplicationSupportDirectory()` (research R-06): `~/.local/share/agenttower-control-panel/` (Linux), `~/Library/Application Support/agenttower-control-panel/` (macOS), `%LOCALAPPDATA%\agenttower-control-panel\` (Windows). Satisfies FR-061a per-OS-user isolation invariant — paths resolve per-user via OS conventions; no cross-user file access.
- [X] T017 Implement `apps/control_panel/lib/core/persistence/ux_state_repository.dart` — single owner of `ux-state.json` read/write (per data-model.md §3). Atomic write via `.tmp` + fsync + rename (research R-05). Debounced 250ms cadence + immediate flush on FR-082 close (with 500ms cap).
- [X] T018 [P] Implement `apps/control_panel/lib/core/persistence/migrations.dart` — forward-only `Migration {fromVersion, toVersion, transform}` framework per research R-21. Currently empty (schema_version = 1) but the framework MUST be present.
- [X] T019 [P] Implement `apps/control_panel/lib/core/persistence/compatibility.dart` — FR-070 "compatible app launch" check: same app major AND same `app_contract_version` major; on mismatch drop persisted UX state.
- [X] T020 [P] Implement `apps/control_panel/lib/core/persistence/corruption.dart` — corruption quarantine logic: rename `ux-state.json` to `ux-state.json.corrupt-<timestamp>` on parse failure (`contracts/ux-state.md` §2).

### Logging + diagnostics (FR-074, research R-07/R-18)

- [X] T021 [P] Implement `apps/control_panel/lib/core/logging/rotating_file_logger.dart` — `logger` 2.x with custom `RotatingFileOutput`: 5 files × 10 MiB at `<app-data>/agenttower-control-panel/logs/control-panel.log.<N>`. Capture levels error/warn/info; redact session tokens, prompt bodies, operator notes.
- [X] T022 [P] Implement `apps/control_panel/lib/core/logging/uncaught_error_handler.dart` — top-level `runZonedGuarded` writing uncaught exceptions to the rotating log (research R-18). No remote crash reporter.
- [X] T023 [P] Implement `apps/control_panel/lib/core/logging/latency_capture.dart` — log entries for any operator action exceeding 200 ms p95 (research R-14). Document the threshold in code constants.

### Settings + doctor (FR-009, research R-20)

- [X] T024 Implement `apps/control_panel/lib/core/config/settings_model.dart` — `Settings` freezed class with: daemonSocketPath, theme, density, notificationsGrouping, osNativeNotifications. Match data-model.md §2.1 SettingsValues. Satisfies FR-060 — the model deliberately omits any `host` or `port` field; only `daemonSocketPath` is configurable.
- [X] T025 Implement `apps/control_panel/lib/features/settings/settings_repository.dart` — load/save via the UX-state repository (T017).
- [X] T026 Implement `apps/control_panel/lib/features/settings/doctor.dart` — Riverpod `FutureProvider<DoctorReport>` fanning out the 6 FR-009 checks per research R-20: (1) socket reachable, (2) peer UID match, (3) `app_contract_version` satisfies surfaces, (4) app-data dir writable, (5) log file writable + not at cap, (6) OS-native notification permission (conditional on toggle).
- [X] T027 [P] Implement `apps/control_panel/lib/features/settings/diagnostics_bundle.dart` — "Copy diagnostics bundle" producing: doctor output + app version + `app_contract_version` + socket path + OS user + recent rotating log. No upload, no telemetry.

### Theme, density, a11y (FR-009/066/067)

- [X] T028 [P] Implement `apps/control_panel/lib/ui/theme/color_tokens.dart` — Light + Dark + System tokens with WCAG AA contrast per research R-15. Include severity palette (info/warning/high/critical) keyed against theme background.
- [X] T029 [P] Implement `apps/control_panel/lib/ui/theme/density_tokens.dart` — Comfortable + Compact row-height / padding tokens.
- [X] T030 [P] Implement `apps/control_panel/lib/ui/a11y/focus_utils.dart` — focus-order helpers, visible-focus decoration, modal trap-free focus utilities per FR-066.
- [X] T031 [P] Wire `apps/control_panel/lib/core/l10n/` codegen output to `MaterialApp` `localizationsDelegates` + `supportedLocales` (en only at MVP) per research R-08. Satisfies FR-067 — English-only at MVP, all user-facing strings routed through the i18n layer so adding a locale later is a translation drop-in.

### Notifications + shortcuts (FR-007/057/058/075)

- [X] T032 Implement `apps/control_panel/lib/core/notifications/grouping_rule.dart` — view-layer projection collapsing N ≥ 3 notifications sharing `event_class` + `agent_id` + severity ≤ warning within rolling 60s window per FR-057.
- [X] T033 [P] Implement `apps/control_panel/lib/core/notifications/os_native_dispatcher.dart` — `local_notifier` integration dispatching only high/critical severities when FR-058 toggle is enabled. Research R-10.
- [X] T034 [P] Implement `apps/control_panel/lib/core/shortcuts/shortcuts.dart` — `Shortcuts` widget binding Ctrl/Cmd+P (project switcher per FR-007) and Ctrl/Cmd+K (command palette per FR-075). Platform-aware key resolution.
- [X] T035 [P] Implement `apps/control_panel/lib/core/shortcuts/command_palette.dart` — `Ctrl/Cmd+K` palette supporting project-switch, workspace-switch, sub-view jump, doctor invocation, and (extensible) primary-action commands per FR-075 + research R-20.

### Update indicator (FR-068)

- [X] T036 [P] Implement `apps/control_panel/lib/core/update/release_feed_check.dart` — one HTTPS GET to `https://releases.opensoft.one/agenttower/control-panel/latest.json` per app launch via `dart:io` `HttpClient` (research R-12). Parse feed JSON; on failure stay silent. Surface "update available" indicator state via Riverpod `Provider<UpdateState>`.

### Domain model scaffolding (data-model.md §1-3)

- [X] T037 Configure `build_runner` in `apps/control_panel/build.yaml` and verify `flutter pub run build_runner watch` generates freezed/json_serializable code into `*.freezed.dart` and `*.g.dart`. **Operator note:** any freezed-model field change (e.g. the Phase 3 review-fix-up rename of `QueueRow.queueRowId → messageId`, addition of `Pane.tmuxSocket`, change of `Pane.tmuxWindowIndex/PaneIndex` to `int`, rename of `Route.targetRule → target` + addition of `Route.template`) requires `dart run build_runner build --delete-conflicting-outputs` before `flutter analyze` / `flutter test` will compile. CI must include a build_runner step before the analyze/test invocations.
- [X] T038 [P] Implement `apps/control_panel/lib/domain/models/common_enums.dart` — shared enums referenced across entities (AgentRole, AgentState, MasterStatus, Stage, ExecutionStatus, AssignmentState, RunState, RunResult, DriftStatus, DriftSeverity, DriftSource, DriftConfidence, EntrypointType, BlockingLevel, DemoReadinessState, AttentionSeverity, NotificationSeverity, AttentionClass, HandoffMode, HandoffPriority, PolicySource, ResolvedExclusion, WorkItemKind, OnboardingMilestone, Workspace, ThemeMode, DensityMode, SortDirection). State values in prose use hyphenated form per FR-014; Dart enum variants use camelCase per Dart convention.
- [X] T039 [P] Implement `apps/control_panel/lib/domain/lifecycles/pane_state_validator.dart` — encode FR-014 transition matrix per data-model.md §1.4 as `bool isValidTransition(PaneState from, PaneState to)`.
- [X] T040 [P] Implement `apps/control_panel/lib/domain/lifecycles/drift_state_validator.dart` — encode FR-034 transition matrix per data-model.md §1.9.
- [X] T041 [P] Implement `apps/control_panel/lib/domain/lifecycles/handoff_state_validator.dart` — encode FR-044 transition matrix per data-model.md §1.6, including operator-vs-daemon authority rules.
- [X] T042 [P] Implement `apps/control_panel/lib/domain/lifecycles/validation_run_state_validator.dart` — encode FR-048 transition matrix per data-model.md §1.11, including "result meaningful only in terminal states".
- [X] T043 [P] Implement `apps/control_panel/lib/domain/lifecycles/feature_change_stage_validator.dart` — encode F7-b deferred-stage transition rule per data-model.md §1.5 (deferred → definition | spec_ready only).

### App shell (FR-002/004/006/007/082)

- [X] T044 Implement `apps/control_panel/lib/main.dart` — entrypoint: `ProviderScope` + `window_manager` window-geometry restore per research R-11 + immediate-close behavior per FR-082.
- [X] T045 Implement `apps/control_panel/lib/app.dart` — `MaterialApp.router` with theme/density wiring (T028/T029), locale wiring (T031), and the routing tree (T046).
- [X] T046 [P] Implement `apps/control_panel/lib/routing/router.dart` — workspace + sub-view registry; top-level routes for agent_ops / project_specs / testing_demo / settings per FR-006.
- [X] T047 [P] Implement `apps/control_panel/lib/features/shell/global_banner.dart` — FR-002 contract-version-incompatible banner (global) and FR-076 first-launch-project-not-resolved banner (non-blocking, per-project).
- [X] T048 [P] Implement `apps/control_panel/lib/features/shell/project_switcher.dart` — Ctrl/Cmd+P shortcut and visible UI affordance per FR-007.
- [X] T049 [P] Implement `apps/control_panel/lib/features/shell/runtime_state_provider.dart` — Riverpod `Provider<RuntimeState>` distinguishing the 5 FR-004 states (runtime-unreachable, contract-version-incompatible, runtime-healthy-empty, runtime-healthy-populated, runtime-degraded).

### Test harness (research R-17)

- [X] T050 Implement `apps/control_panel/test_harness/mock_daemon/server.py` — Python mock listening on a temp Unix socket, speaking FEAT-011 envelopes, parameterized by JSON fixture files. Supports per-test process spawn (no cross-test state).
- [X] T051 [P] Create `apps/control_panel/test_harness/mock_daemon/README.md` documenting fixture format + how integration tests invoke the harness.
- [X] T052 [P] Implement `apps/control_panel/test/helpers/mock_daemon_client.dart` — Dart-side helper that spawns the Python harness, connects, and exposes a typed API for tests.
- [X] T053 [P] Implement `apps/control_panel/test/helpers/fixture_builders.dart` — freezed-fixture builders for every data-model entity (Project, AdoptedAgent, Pane, Handoff, DriftSignal, ValidationEntrypoint, ValidationRun, Notification, AttentionItem, etc.). Default values + `.copyWith` per test scenario.

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel.

---

## Phase 3: User Story 1 - Adopt and operate existing agent panes (Priority: P1) 🎯 MVP

**Goal**: Operator launches the app, discovers existing tmux panes through it, adopts one into a registered agent (label/role/capability/log-attach), watches events flow in, sends a direct prompt, and creates a route — all without ever opening a terminal.

**Independent Test**: With `agenttowerd` running, a bench container present, and ≥1 live tmux pane, an operator can on a clean machine take the pane from "discovered but unmanaged" to "registered agent with attached log, observable events, a successful direct send, and ≥1 active route" — confirming each state transition via the corresponding view in the app.

### Tests for User Story 1 (per plan.md integration_test/)

- [X] T054 [P] [US1] Write integration test `apps/control_panel/integration_test/us1_adopt_and_operate.dart` covering US1 §1-§6 acceptance scenarios against the mock-daemon harness (T050). Assert SC-001 budget: full 8-milestone onboarding walk (launch → first registered agent + log + event + send + route) completes in ≤ 10 minutes on the mock daemon.
- [X] T055 [P] [US1] Write integration test `apps/control_panel/integration_test/runtime_states.dart` exercising the FR-004 five-state distinction on every US1 sub-view. Assert SC-010 budgets: on simulated daemon outage, every live-data surface transitions to its `runtime-unreachable` empty state within 2 s; after daemon return + "Retry connection", live state reverts within 5 s; no surface displays stale data labelled as live during the outage.
- [X] T056 [P] [US1] Write integration test `apps/control_panel/integration_test/contract_version_skew.dart` covering FR-002 global banner + per-surface read-only mode (US1 acceptance scenario added by F1 / spec-quality-pass).

### Domain models for US1

- [X] T057 [P] [US1] Implement `apps/control_panel/lib/domain/models/container.dart` — `Container` freezed class per data-model.md §1.16.
- [X] T058 [P] [US1] Implement `apps/control_panel/lib/domain/models/pane.dart` — `Pane` freezed class with PaneState enum + FR-014 transition reference per data-model.md §1.4.
- [X] T059 [P] [US1] Implement `apps/control_panel/lib/domain/models/adopted_agent.dart` — `AdoptedAgent` freezed class with role/capability/project_path/log_attachment/parent_agent_id/descendants_beyond_visible per data-model.md §1.2.
- [X] T060 [P] [US1] Implement `apps/control_panel/lib/domain/models/queue_row.dart` — `QueueRow` freezed class per data-model.md §1.16.
- [X] T061 [P] [US1] Implement `apps/control_panel/lib/domain/models/route.dart` — `Route` freezed class per data-model.md §1.16.
- [X] T062 [P] [US1] Implement `apps/control_panel/lib/domain/models/event.dart` — `Event` freezed class per data-model.md §1.16.

### Daemon-client extensions for US1 (contracts/app-methods-consumed.md §1-6)

- [X] T063 [US1] Extend `apps/control_panel/lib/core/daemon/app_client.dart` with `app.container.list/.detail`, `app.pane.list/.detail`, `app.agent.list/.detail`, `app.log_attachment.list/.detail`, `app.event.list/.detail`, `app.queue.list/.detail`, `app.route.list/.detail` typed wrappers.
- [X] T064 [US1] Extend `app_client.dart` with US1 mutations: `app.agent.register_from_pane`, `app.agent.update`, `app.log.attach`, `app.log.detach`, `app.send_input`, `app.queue.approve/.delay/.cancel`, `app.route.add/.remove/.update`, `app.scan.containers/.panes/.status`. Satisfies FR-005 — every mutation goes through `app.*` daemon methods; the app NEVER invents or mutates domain state locally.

### Agent Operations workspace (FR-011..FR-022)

- [X] T065 [US1] Implement `apps/control_panel/lib/features/agent_ops/dashboard/dashboard_view.dart` — FR-012 Dashboard (daemon reachability, contract version, container count, pane count by state, registered-agent count by state, blocked-queue count, recently-skipped-route count, recommended next action per FR-004 state).
- [X] T066 [P] [US1] Implement `apps/control_panel/lib/features/agent_ops/containers/containers_view.dart` — FR-013 Containers view (label, discovered status, project path).
- [X] T067 [US1] Implement `apps/control_panel/lib/features/agent_ops/panes/panes_view.dart` — FR-014 Panes view with the four-state vocabulary (discovered-and-unmanaged | discovered-and-registered | inactive/stale | discovery-degraded) and per-state next-action affordance.
- [X] T068 [US1] Implement `apps/control_panel/lib/features/agent_ops/panes/adopt_flow.dart` — FR-016 adopt-existing-pane form (label, role, capability, project_path, attach_log_now). Reject role/capability incompatible with discovered pane class. Calls `app.agent.register_from_pane`. ≤ 5 s budget per FR-065.
- [X] T069 [P] [US1] Implement `apps/control_panel/lib/features/agent_ops/agents/agents_view.dart` — FR-015 Agents view treating agent + current goal/task as primary unit; render parent/child sub-agent tree limited to 2 visible levels per data-model.md §1.2 with "+N descendants" affordance. Also implement `apps/control_panel/lib/features/agent_ops/agents/edit_agent.dart` (`EditAgentDialog`) wiring `AppClient.agentUpdate` so the operator can mutate label / role / capability / project_path per FR-015; honor "empty string clears" semantics for `label` / `project_path` and the closed-set rejection for `role` / `capability`.
- [X] T070 [P] [US1] Implement `apps/control_panel/lib/features/agent_ops/agents/log_attach_affordance.dart` — FR-017 log attach/detach available from Agents view and per-pane affordance.
- [X] T071 [US1] Implement `apps/control_panel/lib/features/agent_ops/agents/direct_send.dart` — FR-018 Direct Send (non-empty payload required, inline daemon response, no silent retry on failure). Uses optional `idempotency_key` per FEAT-011 FR-031a.
- [X] T072 [P] [US1] Implement `apps/control_panel/lib/features/agent_ops/events/events_view.dart` — FR-019 Events view in observed-at order with virtualized infinite scroll per FR-080 + "Jump to most recent" affordance.
- [X] T073 [P] [US1] Implement `apps/control_panel/lib/features/agent_ops/queue/queue_view.dart` — FR-020 Queue view with the 5-state vocabulary (queued | blocked | delivered | canceled | failed) and approve/delay/cancel actions on blocked + (cancel-only) on queued rows. Virtualized per FR-080.
- [X] T074 [P] [US1] Implement `apps/control_panel/lib/features/agent_ops/routes/routes_view.dart` — FR-021 Routes view with source scope, target rule, master rule, enabled state, recent skip explanation, explainability surface per FR-059.
- [X] T075 [P] [US1] Implement `apps/control_panel/lib/features/agent_ops/routes/add_route_flow.dart` — Add route form (source + event_class + target + master_rule). Calls `app.route.add`.
- [X] T076 [P] [US1] Implement `apps/control_panel/lib/features/agent_ops/health/health_view.dart` — FR-022 Health view with per-subsystem readiness (discovery, log attachment, classifier, queue, routing) + composite "degraded but usable" state + in-app explainability per FR-059.

### Onboarding (FR-010 + R-20)

- [X] T077 [US1] Implement `apps/control_panel/lib/features/onboarding/onboarding_flow.dart` — 8-milestone onboarding per FR-010 with automatically-detectable completion criteria (per F11). Each milestone observes the daemon state and self-completes when detected. Skippable from any step.
- [X] T078 [P] [US1] Implement `apps/control_panel/lib/features/onboarding/dashboard_nudges.dart` — incomplete-milestone nudges on the Dashboard per FR-010 + clarify Q24. Visually distinguished from the FR-012 recommended-next-action tile.
- [X] T079 [US1] Persist `OnboardingMilestone` completion state via the UX-state repository (per data-model.md §2.1 + contracts/ux-state.md §1).

### Trust-model first-launch statement (FR-061)

- [X] T080 [P] [US1] Implement `apps/control_panel/lib/features/onboarding/trust_model_statement.dart` — first-launch in-app statement of local-only trust (Unix socket + same-host UID per FR-061). Also reachable from Settings.

**Checkpoint**: Phase 3 source code lands. **Functional sign-off pending** the items captured in T160-T163 below — specifically (a) re-enabling the 4 FR-012 dashboard tiles after an upstream contract bump that extends FEAT-011 `app.dashboard` lands + bumping the daemon contract to 1.1 (T160; see T160 body for the explicit note that no such upstream artifact is filed in-tree yet), (b) extending T054 with a real SC-001 walk (T161), (c) extending T055 with real SC-010 outage/recovery measurements (T162), and (d) wiring an integration test for onboarding milestone auto-tick (T163). The Phase 3 wire surface IS aligned with FEAT-011 v1.0 per `app-methods.md` post-commit 888b7fc; Phase 4 work may proceed in parallel with T160-T163 since they do not block the US2-US6 implementation paths.

---

## Phase 4: User Story 2 - Re-orient to a project and see which master is driving which feature (Priority: P2)

**Goal**: Operator opens the app, sees projects as cards, distinguishes them at a glance, picks one, and on Current Work immediately sees the active feature + driving master + one-click links to PRD/architecture/roadmap/feature spec/OpenSpec change.

**Independent Test**: With ≥2 registered projects each carrying ≥1 active feature/change and an assigned master, operator can identify the driver per project, distinguish by card-level info, open ≥1 doc in one click from Current Work, and answer "which master is driving FEAT-N" without leaving the app.

### Tests for User Story 2

- [X] T081 [P] [US2] Write `apps/control_panel/integration_test/us2_project_and_master.dart` covering US2 §1-§5 acceptance scenarios (including the F1-added scenario for FR-076 first-launch project resolution).

### Domain models for US2

- [X] T082 [P] [US2] Implement `apps/control_panel/lib/domain/models/project.dart` — `Project` freezed class with the FR-025 attribute set per data-model.md §1.1. Include `primaryMasterAgentIds: List<String>` (capped at 2), `masterOverflowCount: int`, `subAgentCount: int` per the Round-2 finding F-A7. Satisfies FR-026 — Project identity uses the canonicalized repository absolute path (one project = one repository); worktrees and branches are subordinate context.
- [X] T083 [P] [US2] Implement `apps/control_panel/lib/domain/models/master_summary.dart` — `MasterSummary` freezed class with FR-030 attributes per data-model.md §1.3. Construct ONLY when the underlying AdoptedAgent satisfies FR-071 (role=master AND master-class capability).
- [X] T084 [P] [US2] Implement `apps/control_panel/lib/domain/models/feature_change_status.dart` — `FeatureChangeStatus` freezed class with FR-028 three-layer model per data-model.md §1.5. Stage enum includes `deferred` per F7-a; F7-b transition rule already in T043.

### Daemon-client extensions for US2

- [X] T085 [US2] Extend `app_client.dart` with anticipated FEAT-011 methods (per contracts/app-methods-consumed.md §3): `app.project.list/.detail/.add/.remove`, `app.feature_change.list/.detail`. Gate via FR-002 contract-version-incompatible degradation when methods are absent.
- [X] T086 [US2] Implement `apps/control_panel/lib/domain/master_qualification.dart` — fetch master-class capability set from daemon once per session; cache; use to gate MasterSummary construction per FR-071.

### Project + Specs workspace (FR-023..FR-032)

- [X] T087 [P] [US2] Implement `apps/control_panel/lib/features/project_specs/projects/projects_view.dart` — FR-023/FR-024 Projects view as cards (not a table) sized for ~5 projects.
- [X] T088 [US2] Implement `apps/control_panel/lib/features/project_specs/projects/project_card.dart` — FR-025 card with every required attribute (name, repository path, repo state badge, active branch/worktree badge, active feature/change, current phase/status, current driving master, compact master strip up to 2 + overflow, sub-agent count, last activity, validation badge + last run age, drift badge + source + age, attention summary, unread notification count, quick actions).
- [X] T089 [P] [US2] Implement `apps/control_panel/lib/features/project_specs/projects/add_project.dart` — explicit "Add Project" action per Assumption: project registration model. Calls `app.project.add`.
- [X] T090 [P] [US2] Implement `apps/control_panel/lib/features/project_specs/projects/remove_project.dart` — FR-077 confirmation-gated remove; clears project-scoped UI persistence (last sub-view + sort/filter per FR-078); daemon data untouched.
- [X] T091 [US2] Implement `apps/control_panel/lib/features/project_specs/current_work/current_work_view.dart` — FR-027 Current Work view with active feature/change, driving master, workflow phase, recent activity, one-click links to PRD/architecture/roadmap/feature spec/OpenSpec change paths (document open behavior per FR-079).
- [X] T092 [US2] Implement `apps/control_panel/lib/features/project_specs/current_work/driving_master_indicator.dart` — FR-029 "agent X is driving FEAT-N under handoff H" indicator on every feature surface, with one-click navigation to master summary + handoff record. Handles multi-driver conflict display.
- [X] T093 [P] [US2] Implement `apps/control_panel/lib/features/project_specs/specs/specs_view.dart` — FR-031 Specs view (project-first, then feature). Document list/panel uses FR-079 markdown rendering.
- [X] T094 [P] [US2] Implement `apps/control_panel/lib/features/project_specs/changes/changes_view.dart` — FR-032 Changes view for OpenSpec-side proposed/active changes; FR-079 document rendering.
- [X] T095 [P] [US2] Implement `apps/control_panel/lib/ui/widgets/markdown_viewer.dart` — `flutter_markdown` viewer per research R-09 + FR-079. Safe-markdown subset (HTML disabled, `javascript:` / `data:` URLs rejected). "Open externally" affordance via `url_launcher`.

### First-launch project resolution (FR-076)

- [X] T096 [US2] Implement `apps/control_panel/lib/features/project_specs/projects/first_launch_resolution.dart` — restore persisted last-active project if it still resolves (registered with daemon OR inferable from current adopted agent's `project_path`); otherwise land on Projects view with no selection and FR-076 non-blocking banner.

**Checkpoint**: Project navigation, project cards, current work, specs/changes viewing all work. Operator can re-orient across projects.

---

## Phase 5: User Story 3 - Generate, preview, and submit a master-driving handoff prompt (Priority: P3)

**Goal**: Operator puts a master to work on features/changes by stepping through master → project → work-item selection → mode → auto-fill → preview → notes → submit. The handoff is a durable, reviewable object delivered via FEAT-009 safe prompt queue.

**Independent Test**: With a registered master and a project with ≥1 feature spec, operator can complete the full handoff flow and afterwards see (a) the prompt arriving at the target master via the queue and (b) a durable handoff record in `submitted` (or `accepted`) state.

### Tests for User Story 3

- [X] T097 [P] [US3] Write `apps/control_panel/integration_test/us3_handoff_flow.dart` covering US3 §1-§6 + FR-072 failure tiers + FR-081 supersede scenarios (the F1-added scenarios for handoff failure and supersede). Assert SC-003 budget: single-feature handoff with auto-filled context completes from "open handoff flow" to "submitted" in ≤ 30 s on the mock daemon. Assert SC-004: for a feature range with ≥1 deferred + ≥1 merged intermediate item, the resolved-list shown in preview matches byte-for-byte the resolved-list embedded in the submitted prompt (snapshot diff). **The SC-003 assertion MUST drive real taps end-to-end (open handoff modal → pick feature → tick auto-fill checkbox → preview → submit) and measure the wall-clock elapsed across that sequence** — do not ship the vacuous "pump widget, assert elapsed < 30 s" pattern that the post-Phase-3 review flagged on T054/T055 and required T161/T162 follow-ups to repair.

### Domain models for US3

- [X] T098 [P] [US3] Implement `apps/control_panel/lib/domain/models/handoff.dart` — `Handoff` freezed class per data-model.md §1.6 with `handoffId` (post-submit) / `draftId` (pre-submit), `deliveryStatus` (FR-072(b)), `failureContext` (FR-072(a)), `supersededByHandoffId` + `supersedesHandoffId`.
- [X] T099 [P] [US3] Implement `apps/control_panel/lib/domain/models/resolved_work_item.dart` — `ResolvedWorkItem` + `ResolvedExclusion` enum per data-model.md §1.7. Render excluded items as `FEAT-N (excluded: deferred)` / `FEAT-N (excluded: merged)` per F7-c.
- [X] T100 [P] [US3] Implement `apps/control_panel/lib/domain/helper_policy/helper_policy.dart` — `HelperPolicy` + `HelperPolicySnapshot` freezed classes per data-model.md §1.8 + FR-038a + contracts/helper-policy.md.

### Daemon-client extensions for US3

- [X] T101 [US3] Extend `app_client.dart` with anticipated FEAT-011 methods: `app.handoff.list/.detail/.draft/.preview/.submit/.cancel/.supersede`, `app.helper_policies.list/.resolve`. Per R-19 caveat, gate via FR-002 degradation when missing.

### Handoff prompt flow (FR-036..FR-045 + FR-038a + FR-072 + FR-081)

- [X] T102 [US3] Implement `apps/control_panel/lib/features/project_specs/handoff/handoff_flow.dart` — multi-step flow per FR-036 (master → project → work-item → mode in order). Input validation per master qualification (FR-071), project resolution, feature existence. Satisfies FR-037 — optional inputs (priority, deadline, helper-policy override, operator notes) are accepted alongside the required FR-036 inputs.
- [X] T103 [P] [US3] Implement `apps/control_panel/lib/features/project_specs/handoff/feature_range_resolver.dart` — FR-039 canonical `FEAT-N..FEAT-M` range syntax per F8 (inclusive both ends; ascending numeric order regardless of input order). Annotate excluded `deferred` / `merged` items per F7-c.
- [X] T104 [P] [US3] Implement `apps/control_panel/lib/features/project_specs/handoff/auto_fill_context.dart` — FR-038 auto-fill: project/repo identity, active branch/worktree, PRD path, architecture, roadmap, selected feature spec paths, OpenSpec change paths, current stage/status/subphase, known drift state, current validation state, allowed helper-agent defaults (via FR-038a), repo workflow rules.
- [X] T105 [P] [US3] Implement `apps/control_panel/lib/features/project_specs/handoff/helper_policy_resolver.dart` — per FR-038a + contracts/helper-policy.md: call `app.helper_policies.list` at flow entry + `app.helper_policies.resolve` at submission. Per-handoff override scope only. Surface `policy_source = repo_override` when daemon resolves a repo file.
- [X] T106 [US3] Implement `apps/control_panel/lib/features/project_specs/handoff/prompt_skeleton.dart` — sectioned prompt body in FR-040 order: Assignment, Project Context, Workflow Instruction, Helper-Agent Policy, Success Criteria, Stopping and Escalation Rules. Regenerate body on mode change while preserving operator notes (FR-040).
- [X] T107 [P] [US3] Implement `apps/control_panel/lib/features/project_specs/handoff/preview_view.dart` — preview surface with sectioned prompt + auto-filled context view + operator-notes editor. Reject edits to skeleton sections with inline explanation per FR-041.
- [X] T108 [US3] Implement `apps/control_panel/lib/features/project_specs/handoff/submit_flow.dart` — calls `app.handoff.submit`. Persists durable record per FR-042. Delivery via FEAT-009 safe prompt queue per FR-043. Handles three FR-072 failure tiers: (a) submission failure → stays `drafted` + error attached; (b) delivery failure → stays `submitted` + delivery-failure indicator + "Retry delivery" action; (c) offline master → held `submitted` until reconnect.
- [X] T109 [P] [US3] Implement `apps/control_panel/lib/features/project_specs/handoff/supersede_flow.dart` — FR-081 supersede: prior handoff → `superseded`, new handoff records `supersededByHandoffId`. Does NOT auto-cancel prior queue rows; operator-facing warning at supersede time.
- [X] T110 [P] [US3] Implement `apps/control_panel/lib/features/project_specs/handoff/handoff_list_view.dart` — query handoffs by project / master / feature/change / assignment state + date-range on `created_at` per FR-045.
- [X] T111 [P] [US3] Implement `apps/control_panel/lib/features/project_specs/handoff/handoff_detail_view.dart` — render the handoff record (state model independent from feature/change lifecycle per FR-044), supersede chain, delivery status, helper-policy snapshot (FR-042).

**Checkpoint**: Operator can complete a full handoff lifecycle. US1 + US2 + US3 all work independently.

---

## Phase 6: User Story 4 - See and act on drift signals for a project (Priority: P3)

**Goal**: Operator opens Drift, sees findings with status / source / severity / confidence / age / scope / summary / evidence / recommended action, walks them through the lifecycle, and can launch a drift-repair handoff that pre-fills the affected feature(s).

**Independent Test**: With ≥1 project having a drift finding, operator can render the finding with the documented fields, drill in, launch a drift-repair handoff (pre-fills feature + `drift_repair` mode + drift signal id), and walk new → review_needed → confirmed → repair_planned → resolved with the project-card drift badge updating accordingly.

### Tests for User Story 4

- [X] T112 [P] [US4] Write `apps/control_panel/integration_test/us4_drift.dart` covering US4 §1-§5 acceptance scenarios. Assert SC-005 budget: after the mock daemon emits a new drift finding for a project, the project card's drift badge updates within 60 s. **The SC-005 assertion MUST observe the actual badge transition (poll `find.text` or watch the badge widget's Riverpod state) within the 60 s window** — do not ship a pump-and-assert-elapsed shape; see the T054/T055 cautionary precedent + T161/T162 below.

### Domain models for US4

- [X] T113 [P] [US4] Implement `apps/control_panel/lib/domain/models/drift_signal.dart` — `DriftSignal` freezed class per data-model.md §1.9 with full FR-033 attributes + FR-034 lifecycle states.

### Daemon-client extensions for US4

- [X] T114 [US4] Extend `app_client.dart` with: `app.drift.list/.detail/.transition`.

### Drift surface (FR-033..FR-035)

- [X] T115 [US4] Implement `apps/control_panel/lib/features/project_specs/drift/drift_view.dart` — FR-033 Drift list with status, source, severity, confidence, age, scope, summary, recommended action, supporting evidence, linked refs. Uses severity palette from research R-15. Virtualized per FR-080.
- [X] T116 [US4] Implement `apps/control_panel/lib/features/project_specs/drift/drift_detail_view.dart` — per-finding detail with evidence rendering (markdown via T095) and "Repair this drift" action per FR-035.
- [X] T117 [P] [US4] Implement `apps/control_panel/lib/features/project_specs/drift/drift_transition.dart` — operator-driven `app.drift.transition` calls per FR-034. Uses T040 validator to prevent illegal transitions.
- [X] T118 [P] [US4] Implement `apps/control_panel/lib/features/project_specs/drift/drift_repair_handoff_launch.dart` — pre-fills handoff flow with affected feature(s), `drift_repair` mode, drift signal id as context. Depends on US3 handoff flow (T102).

**Checkpoint**: Drift surface live + drift-repair handoff launch wired. US1+US2+US3+US4 all work independently.

---

## Phase 7: User Story 5 - See available validation, run it, and judge demo readiness (Priority: P3)

**Goal**: Operator opens Testing and Demo, sees validation entrypoints grouped by scope, triggers runs, watches state transitions, reads a current demo readiness summary that answers "can I demo this branch now?".

**Independent Test**: With a project exposing ≥2 validation entrypoints (≥1 required, ≥1 recommended), operator can list them, trigger one, see the run progress queued → running → completed, see it in run history, and read a demo readiness summary that reflects the latest result with at least one recommended-next-run or blocking-finding entry.

### Tests for User Story 5

- [X] T119 [P] [US5] Write `apps/control_panel/integration_test/us5_validation_demo.dart` covering US5 §1-§5 acceptance scenarios.

### Domain models for US5

- [X] T120 [P] [US5] Implement `apps/control_panel/lib/domain/models/validation_entrypoint.dart` — `ValidationEntrypoint` freezed class per data-model.md §1.10 (label, type, scope, description, blocking_level, estimated_duration, enabled).
- [X] T121 [P] [US5] Implement `apps/control_panel/lib/domain/models/validation_run.dart` — `ValidationRun` freezed class per data-model.md §1.11 with state/result/timestamps/summary/artifacts/triggered_by/linked refs.
- [X] T122 [P] [US5] Implement `apps/control_panel/lib/domain/models/demo_readiness_summary.dart` — `DemoReadinessSummary` freezed class per data-model.md §1.12 with overall_state / summary / blocking_findings / recommended_next_runs / recent_run_ids / linked_feature_ids. Encode the "at most at_risk if any required entrypoint has not run" invariant.

### Daemon-client extensions for US5

- [X] T123 [US5] Extend `app_client.dart` with: `app.validation.entrypoint.list/.detail`, `app.validation.run.list/.detail/.trigger/.cancel`, `app.demo_readiness.detail`.

### Testing & Demo workspace (FR-046..FR-051)

- [X] T124 [P] [US5] Implement `apps/control_panel/lib/features/testing_demo/available_validation/available_validation_view.dart` — FR-046/FR-047 grouped by scope; each card shows label, type, scope, description, blocking level, estimated duration, enabled state.
- [X] T125 [US5] Implement `apps/control_panel/lib/features/testing_demo/available_validation/trigger_run.dart` — entrypoint-card "Run" action calling `app.validation.run.trigger`. ≤ 2 s to `running` state per SC-006. Satisfies FR-049 trigger half — execution is invoked through the daemon; the app NEVER executes runners locally.
- [X] T126 [P] [US5] Implement `apps/control_panel/lib/features/testing_demo/runs/runs_view.dart` — FR-048 Runs view with the 5-state vocabulary + 5-result vocabulary; virtualized per FR-080.
- [X] T127 [P] [US5] Implement `apps/control_panel/lib/features/testing_demo/runs/cancel_run.dart` — cancel `running` / `queued` runs via `app.validation.run.cancel`. Uses T042 validator. Satisfies FR-049 cancel half — cancellation is invoked through the daemon; the app does NOT terminate any local subprocess.
- [X] T128 [US5] Implement `apps/control_panel/lib/features/testing_demo/demo_readiness/demo_readiness_view.dart` — FR-050 overall state + summary + blocking findings + recommended next runs + recent run refs. Updates within 5 s of a run resolving per SC-007.
- [X] T129 [P] [US5] Implement `apps/control_panel/lib/features/testing_demo/demo_readiness/readiness_computation.dart` — local rendering helper that respects the FR-050 "at most at_risk if required entrypoint missing" invariant when displaying.

**Checkpoint**: Testing & Demo workspace live. US1..US5 all work independently.

---

## Phase 8: User Story 6 - Operator attention queue, notifications, and notification history (Priority: P3)

**Goal**: Operator uses attention queue, notifications panel, notification history as day-to-day signal-over-noise UX. Attention queue is stable while interacting. Grouped notifications per FR-057. OS-native integration per FR-058.

**Independent Test**: With a session producing ≥3 distinct actionable items and ≥3 notifications, operator can distinguish attention queue / notifications panel / notification history by contents and behaviors; click an attention item and arrive at its resolution surface; acknowledge a notification and see it move to history; observe that the queue does not reorder under the pointer while interacting.

### Tests for User Story 6

- [X] T130 [P] [US6] Write `apps/control_panel/integration_test/us6_attention_notifications.dart` covering US6 §1-§5 + the F1-added FR-057 grouping rule scenario. Include SC-008a stability test (100 simulated live-update bursts with synthetic hover pattern; bursts spaced ≥ 500 ms apart, varying severity, mixed `agent_id`s so the test exercises realistic load rather than degenerate same-tick bursts; no position change under pointer for ≥ 2 s). Cadence requirement added per /speckit-analyze Round 6 F8.

### Domain models for US6

- [X] T131 [P] [US6] Implement `apps/control_panel/lib/domain/models/attention_item.dart` — `AttentionItem` freezed class with `ResolutionTarget` sealed class (queueRow | healthSubsystem | driftFinding | validationRun) per data-model.md §1.13.
- [X] T132 [P] [US6] Implement `apps/control_panel/lib/domain/models/notification.dart` — `Notification` freezed class per data-model.md §1.14 carrying the fields the FR-057 grouping rule keys on.
- [X] T133 [P] [US6] Implement `apps/control_panel/lib/domain/models/operator_history_entry.dart` — `OperatorHistoryEntry` freezed class per data-model.md §1.15 with parent/sub-agent rollup per FR-055.

### Daemon-client extensions for US6

- [X] T134 [US6] Extend `app_client.dart` with: `app.attention.list/.detail`, `app.notification.list/.history/.acknowledge`, `app.operator_history.list`.

### Attention queue (FR-052..FR-055)

- [X] T135 [US6] Implement `apps/control_panel/lib/features/agent_ops/attention/attention_queue_view.dart` — FR-052 actionable-items queue with icon (class) + color (severity) + age + one-line summary. Default sort severity-then-age.
- [X] T136 [US6] Implement `apps/control_panel/lib/features/agent_ops/attention/interaction_stability.dart` — FR-053 2-second interaction-stability window. Defer reorders / item changes while operator hovers / clicks / presses keys on the queue.
- [X] T137 [P] [US6] Implement `apps/control_panel/lib/features/agent_ops/attention/resolution_navigation.dart` — FR-054 click → resolution surface dispatch per `ResolutionTarget` variant.
- [X] T138 [P] [US6] Implement `apps/control_panel/lib/features/agent_ops/attention/operator_history_view.dart` — FR-055 durable operator history rolled up by agent with sub-agents nested.

### Notifications panel + history (FR-008/056/057/058)

- [X] T139 [US6] Implement `apps/control_panel/lib/features/notifications/notifications_panel.dart` — FR-008/FR-056 notifications panel. Apply the FR-057 grouping rule (T032) as a view-layer projection.
- [X] T140 [P] [US6] Implement `apps/control_panel/lib/features/notifications/notification_history_view.dart` — FR-056 history surface; processed → history.
- [X] T141 [P] [US6] Implement `apps/control_panel/lib/features/notifications/badges.dart` — FR-025/FR-056 unread notification count badges at project-card level + global level.
- [X] T142 [US6] Implement `apps/control_panel/lib/features/notifications/os_native_integration.dart` — wire T033 OS-native dispatcher: fires only for high/critical severities, only when the FR-058 toggle is enabled.

**Checkpoint**: Attention queue + notifications + history live. All 6 user stories work independently.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Wrap-up tasks that span multiple stories or finalize release readiness.

- [X] T143 Wire FR-009 Settings surface aggregating every entry: daemon socket path, contract version display, notifications grouping toggle, OS-native notification integration toggle, theme (Light/Dark/System), density (Comfortable/Compact), "Open log folder" + "Copy diagnostics bundle" affordances, doctor / preflight action. Settings is reachable from any workspace + command palette.
- [X] T144 [P] Hook doctor (T026) into the command palette (T035) per research R-20 so it's invokable via Ctrl/Cmd+K.
- [X] T145 [P] Hook diagnostics bundle (T027) into Settings (T143) + command palette (T035).
- [X] T146 [P] Implement `apps/control_panel/lib/features/shell/version_display.dart` — FR-068 installed app version display on Dashboard + Settings, "update available" indicator linking to release page (driven by T036).
- [X] T147 Implement `apps/control_panel/lib/features/shell/quit_handler.dart` — FR-082 immediate-close behavior; trigger FR-069 flush-before-exit via T017. **Status (verified 2026-05-24 / analyze D1):** already landed in `lib/main.dart:117-143` as `_ShutdownListener` (registered via `windowManager.addListener` at line 81). Calls `uxState.flushBeforeExit()` → `session.dispose()` → `logger.close()` → `windowManager.destroy()`, each best-effort with try/catch per FR-082's "close regardless" rule. No separate `quit_handler.dart` file needed.
- [ ] T148 [P] Implement per-OS packaging in `apps/control_panel/tools/package_windows.ps1` (MSIX), `tools/package_macos.sh` (DMG + notarization + hardened runtime), `tools/package_linux.sh` (AppImage + .deb) per research R-13.
- [ ] T149 [P] Write unit tests under the existing module-based test layout (`test/core/<area>/` and `test/features/<feature>/`, matching the home directory of the code under test — same convention as `test/core/daemon/app_client_test.dart` and `test/features/registry_test.dart`) covering: lifecycle validators (T039-T043) at `test/core/lifecycle/`, envelope parser (T011) at `test/core/daemon/`, error code mapping (T012) at `test/core/daemon/`, UX-state repository (T017) at `test/core/ux_state/` including atomic-write + migration + corruption-quarantine paths, helper-policy resolver (T105) at `test/features/handoff/` including FEAT-011 v1.0 absence fallback (per contracts/helper-policy.md §6). Path-layout aligned with existing convention per /speckit-analyze Round 5 T-N1 (avoid creating a parallel `test/unit/` tree that would compete with the module-based layout).
- [ ] T150 [P] Write widget tests under the existing module-based test layout (alongside the unit tests for each feature), placed by code home: project card rendering (T088) at `test/features/project_specs/widget_project_card_test.dart` with zero/one/two/overflow masters, attention queue (T135) at `test/features/agent_ops/attention/widget_attention_queue_test.dart` for icon+color combinations, severity badges (T028) at `test/ui/widgets/widget_severity_visuals_test.dart` across themes, markdown viewer (T095) at `test/ui/widgets/widget_markdown_viewer_test.dart` for the safe-markdown subset. Path-layout aligned with existing convention per /speckit-analyze Round 5 T-N1 (avoid creating a parallel `test/widget/` tree).
- [ ] T151 [P] Write golden tests in `apps/control_panel/test/golden/` (alchemist) for: Light/Dark/System themes × Comfortable/Compact densities × every workspace top-level view, ensuring FR-066 WCAG AA contrast and FR-009 density consistency. The `test/golden/` directory is alchemist convention and will be created as part of this task (it does not exist yet — that is not drift, just unrealized future structure, per /speckit-analyze Round 5 T-N1).
- [X] T152 Write `apps/control_panel/README.md` covering: build / run / packaging instructions per OS, mock-daemon harness usage, FVM pin, lint rules. Mirrors plan.md §Project Structure overview.
- [ ] T153 Run the `specs/012-flutter-control-panel/quickstart.md` validation against the integrated app + real `agenttowerd` on each supported OS (Windows, macOS, Linux). Record outcomes against each acceptance-check table.

### Verification tasks (added per /speckit-analyze Round 1)

- [ ] T154 [P] Performance verification suite in `apps/control_panel/test/perf/perf_budgets_test.dart` asserting (a) FR-062 cold-start-to-Dashboard p95 ≤ 2 s, (b) FR-063 first-screenful render p95 ≤ 1 s for every FR-063 list view (Containers, Panes, Agents, Events, Queue, Routes, Projects, Available Validation, Runs, Drift) at FEAT-011 default page-size 50, (c) **manual-refresh round-trip** propagation p95 ≤ 2 s from `ref.invalidate` to in-app render. **Note (post-Phase-8 analyze A1, 2026-05-24):** the FR-064 wording was originally "live-update propagation" but no SSE/WebSocket subscription exists yet; T167 below tracks the daemon-side streaming work. Until T167 lands, T154(c) measures manual-refresh round-trip, not push propagation. Closes analyze findings C1+C2+C3.
- [ ] T155 Network-trace + subprocess-trace verification in `apps/control_panel/test/security/no_network_no_cli_scrape_test.dart`: run full-workspace exercise under packet capture (assert zero outbound packets except to `releases.opensoft.one`) AND under process trace (assert no subprocess invocation of the `agenttower` CLI). Closes analyze finding C4 / SC-009.
- [ ] T156 CLI non-regression smoke in `tests/integration/test_feat012_cli_noop.py` (Python, lives next to existing FEAT-002..010 tests) — assert FEAT-002..010 CLI methods produce byte-identical output before and after the desktop-app build is installed. Closes analyze finding Const2.
- [ ] T157 [P] Codebase audit in `apps/control_panel/tools/audit_no_local_mutation.dart` (or `scripts/`) — static-analysis pass asserting that every mutation in `apps/control_panel/lib/` originates from `core/daemon/app_client.dart` surface (no UI code constructs `app.*` requests directly, no UI code mutates daemon-owned model state). Closes analyze finding C12 / FR-005 invariant.
- [X] T158 [P] Annotate non-buildable Success Criteria in `apps/control_panel/test/perf/sc_coverage_map.md` (a doc, not test code): explicitly mark SC-002, SC-008, SC-011, SC-012, SC-013 as user-study or post-launch-survey items deferred to internal Opensoft operator cohort evaluation; reference Assumptions in spec.md. Document SC-006/007/008a as covered by T125/T128/T130, SC-001 by T054 (extended), SC-003/004 by T097 (extended), SC-005 by T112 (extended), SC-009 by T155, SC-010 by T055 (extended). Closes analyze findings C6 + C11.
- [X] T159 [P] Update SC coverage references in `specs/012-flutter-control-panel/tasks.md` final footer to reflect post-fix counts (no functional change; documentation-only counter sync).

### Post-Phase-3 review follow-ups (added 2026-05-24)

These five tasks close the HIGH + MEDIUM findings from the post-Phase-3 `/speckit.analyze` audit. They are NOT blocking for Phases 4-8 (US2-US6 implementation paths don't depend on them) but MUST land before final FEAT-012 sign-off.

- [ ] T160 [P] **Re-enable suppressed FR-012 dashboard tiles + bump contract version.** When the upstream contract bump that extends FEAT-011 `app.dashboard` with `counts.panes.by_state` / `counts.agents.by_state` / `counts.routes.recently_skipped_count` / `recommended_next_action` lands (no such upstream artifact exists yet — neither `specs/014-*` nor any `openspec/changes/extend-app-dashboard-fields-for-feat012` is filed in-tree as of /speckit-analyze Round 6, 2026-05-25; T160 cannot start until one is filed and archived), (a) update `ContractRegistry.declare('agent_ops/dashboard', ...)` in `apps/control_panel/lib/features/agent_ops/module.dart` from `ContractVersion(1, 0)` to `ContractVersion(1, 1)`, (b) un-comment + wire the 4 TODO-marked tiles in `apps/control_panel/lib/features/agent_ops/dashboard/dashboard_view.dart` against the new fields, (c) extend `Fixtures.dashboardResult` in `apps/control_panel/test/helpers/fixture_builders.dart` with optional params for the new fields, (d) update the mock daemon README's `app.dashboard` fixture example, (e) re-pin the bench to Flutter 3.27 stable (the Phase 3 T009 deviation noted in T002) using a fresh `fvm install` once the bench's git-rewrite issue is resolved — this re-pin MUST include downgrading `apps/control_panel/pubspec.yaml` from `intl: ^0.20.2` back to `intl: ^0.19.0` (the documented 3.27 baseline per `flutter-testing-plan.md:154`) plus any other deps that transitively bumped past the 3.27/Dart 3.6 SDK floor during the 3.44 detour; delete `pubspec.lock` and re-resolve. Closes analyze finding C1 + C4.
- [ ] T161 [P] **Extend T054 with a real SC-001 walk.** Rewrite `apps/control_panel/integration_test/us1_adopt_and_operate.dart` to actually drive the 8-milestone walk (containers list → pane discovery → adopt → register agent → log attach → direct send → route add) via `tester.tap` + `tester.pumpAndSettle` between each step, then assert the wall-clock elapsed against the SC-001 ≤ 10 minute budget. The current shape pumps the widget + asserts an unmeasured budget — vacuous per the post-Phase-3 analyze C2 finding. Tap-driving requires the build_runner-generated freezed files (see T037 operator note) and `MockDaemonClient` + `Fixtures` for each post-mutation state transition.
- [ ] T162 [P] **Extend T055 with real SC-010 outage/recovery measurements.** Rewrite `apps/control_panel/integration_test/runtime_states.dart` to (a) start the mock-daemon harness + bootstrap the session, (b) kill the mock daemon process mid-flight and assert every live-data surface transitions to the documented `runtime-unreachable` empty state within 2 s (FR-004 + SC-010), (c) re-spawn the mock daemon + tap "Retry connection" and assert live state reverts within 5 s, (d) assert no surface displays stale data labelled as live during the outage. The current rewrite preserves only the `ContractCompat.compute` matrix test — the wall-clock budgets are unmeasured. Closes analyze finding C2.
- [ ] T163 [P] **Onboarding milestone auto-tick integration test.** Write `apps/control_panel/integration_test/us1_onboarding_autotick.dart` driving each of the 8 milestones through its trigger condition (mock-daemon emits a container → `benchContainerCheck` ticks; emits a pane → `paneDiscoveryCheck` ticks; etc.) and assert the milestone enters `onboardingProgressProvider`'s persisted set within one pump tick. Verifies the post-Phase-3 `OnboardingProgressNotifier` `ref.watch` wiring (review fix C9) cannot silently regress. Closes analyze finding M2.
- [ ] T164 [P] **Write widget tests for the 12 Phase 3 US1 surfaces** under `apps/control_panel/test/features/agent_ops/` (existing module-based layout — same convention as `test/features/registry_test.dart`; aligned with /speckit-analyze Round 5 T-N1) covering: dashboard_view (with + without runtime-unreachable + with all-zero counts), containers_view (empty + populated + load-error), panes_view (per-PaneState row variants + adopt button visibility), adopt_flow (validation + submit + per-error rendering), agents_view (tree depth + descendants overflow), direct_send (empty-payload guard + send-success snack), log_attach_affordance (attach/detach + busy state), events_view (jump-to-most-recent + empty), queue_view (action visibility per state + delay-on-queued correctness post-H8 fix), routes_view (toggle + remove + recent-skip explanation rendering), add_route_flow (template/target submit), health_view (per-state coloring + hints). Each test pumps with `ProviderScope` + override stubs for `appClientProvider`. Closes analyze finding H13 (deferred from Block D in the review fix-up).

### Verification tasks (added per /speckit-analyze Round 2, post-Phase-8 / swarm-review)

- [ ] T165 [P] **FR-067 i18n sweep — replace ~200 hardcoded English strings.** Audit every Phase 4-8 widget under `apps/control_panel/lib/features/project_specs/**`, `lib/features/agent_ops/attention/**`, `lib/features/notifications/**`, `lib/features/testing_demo/**`, `lib/ui/widgets/markdown_viewer.dart`. Extend `apps/control_panel/assets/l10n/en.arb` with one key per hardcoded `Text('literal')` / `Tooltip(message: '...')` / `SnackBar(content: Text('...'))` / `AppBar(title: Text('...'))` (~200 total). Wire each call-site to `AppLocalizations.of(context)!.<key>` so adding a new locale becomes a translation + config change with no source-code edits. The localization delegate is already configured in `app.dart` (commented out pending the first sweep) — uncomment + add `AppLocalizations.delegate` after the keys land. Closes swarm-review **CR-4**. **Why now:** FR-067 is unmet in production; this is the single biggest documentation finding from the swarm review.
- [ ] T166 [US3] **FR-072(a) drafted-row daemon-coordination.** Currently `submitHandoff` constructs a `Handoff` only from the success row, so on submission failure the operator's draft lives only in `_HandoffFlowState` widget state — navigating away loses the draft + failure context. FR-072(a) requires that the handoff "remain in `drafted` with the daemon error attached". This requires the daemon to accept `app.handoff.draft` (write-through pre-submission persistence) so the `Handoff.failureContext` field can be populated server-side and survive widget tear-down. Coordinate with FEAT-011 (or a new FEAT-N change proposal) before implementing the client side. Closes swarm-review **H-B10**.
- [ ] T167 [P] **FR-064 live-update streaming.** Replace the `ref.invalidate(...)` manual-refresh strategy with daemon-side event subscriptions (SSE or WebSocket inside the existing Unix-socket framing) so live surfaces reflect daemon-side events within the FR-064 2 s budget. Wire into every Phase 4-8 list provider (`projectList`, `featureChangeList`, `handoffList`, `driftList`, `validationRunList`, `attentionList`, `notificationList`). T154(c) currently measures manual-refresh round-trip only (per analyze A1); T167's landing flips T154(c) to measure push propagation. Closes swarm-review **M-11** and **analyze C3**. **Daemon dependency:** requires FEAT-011 v1.x to expose a streaming subscription method — coordinate with FEAT-011 before client-side implementation.
- [ ] T168 [P] [US3] **Rewrite `us3_handoff_flow.dart` for SC-003 real-tap walk.** The current integration test bypasses the widget tree entirely (drives `submitHandoff` against a `ProviderContainer` directly). T097 explicitly forbade that pattern. Drive `tester.tap` + `tester.enterText` to walk: open project → tap "Open handoff flow" → enter range → tap mode → tap Preview → tap Submit. Start a `Stopwatch` at the first tap; assert `< 30 s` at the Submit assertion. Closes swarm-review **H-B1**.
- [ ] T169 [P] [US3] **Rewrite us3 SC-004 byte-for-byte assertion to be non-tautological.** Today the same `previewText` string is passed to both sides of the equality. Replace with two independent `PromptSkeleton.render()` invocations (one from the preview surface, one captured at submit time) and assert byte equality. Additionally mirror the submitted `generated_prompt_text` into the mock-daemon row so the daemon round-trip is observable + diff-able. Closes swarm-review **H-B2**.
- [ ] T170 [P] [US4] **Add SC-005 60-second wall-clock budget to `us4_drift.dart`.** T112 explicitly required observing the actual badge transition within the 60 s window. The current test asserts data-flow only. Use `tester.pumpUntil(timeout: const Duration(seconds: 60))` watching the project-card drift badge widget; emit a drift transition from the mock daemon mid-test; assert the badge text updates before the timeout. Closes swarm-review **H-C2**.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies; start immediately.
- **Foundational (Phase 2)**: depends on Setup. BLOCKS all user-story phases.
- **User Stories (Phases 3-8)**: all depend on Foundational. After Foundational completes, US1..US6 can proceed in parallel where staffing allows. Story-internal dependencies:
  - **US1 (Phase 3)**: T077/T078/T079 (onboarding) depend on T067/T068 (Panes view + adopt flow) and T071 (Direct Send) and T065 (Dashboard).
  - **US2 (Phase 4)**: T086 (master qualification) depends on T083 (MasterSummary model). T088 (project card) depends on T082 (Project model) + T083.
  - **US3 (Phase 5)**: T102+T106+T107+T108 depend on T098+T099+T100 (handoff/resolved-work-item/helper-policy models). T103 depends on T084 (FeatureChangeStatus enum). T108 depends on T101 (daemon-client extension). T109 depends on T108.
  - **US4 (Phase 6)**: T118 (drift-repair handoff launch) depends on US3 T102 (handoff flow).
  - **US5 (Phase 7)**: independent of US3/US4 model-wise. T125+T127+T128 depend on T123 (daemon-client extension).
  - **US6 (Phase 8)**: T136 (interaction stability) depends on T135 (attention queue view). T139 (notifications panel) consumes T032 (grouping rule from Phase 2).
- **Polish (Phase 9)**: depends on user-story completions where named (T144 ⇐ T026 + T035; T145 ⇐ T027 + T143 + T035; T146 ⇐ T036; T147 ⇐ T017; T153 ⇐ all earlier phases).

### MVP scope (minimum shippable)

**Phase 1 + Phase 2 + Phase 3 (US1).** This delivers the absolute-minimum US1 P1 slice: launch → adopt → log → events → direct send → route. Onboarding, doctor, diagnostics, and the trust-model first-launch statement are included in US1's phase because they wrap the same workflow. The MVP is shippable without US2..US6 and is a strict-superset replacement for the equivalent FEAT-002..010 CLI workflow.

After MVP ships, deliver US2 next (project navigation), then US3 (handoff flow), then US4..US6 in any order based on operator demand.

### Parallel execution examples

Once Phase 2 (Foundational) is complete, the following groups can run in parallel:

- **Phase 3 (US1) initial parallel batch**: T054 + T055 + T056 (tests) || T057 + T058 + T059 + T060 + T061 + T062 (models).
- **Phase 4 (US2) initial parallel batch**: T081 (tests) || T082 + T083 + T084 (models).
- **Phase 5 (US3) initial parallel batch**: T097 (tests) || T098 + T099 + T100 (models).
- **Phase 9 (Polish) parallel batch**: T144 + T145 + T146 + T148 + T149 + T150 + T151 (all [P]).

Within a single user-story phase, the [P]-marked tasks against distinct file paths can run in parallel; non-[P] tasks (e.g. T068 adopt flow depending on T067 panes view) must be serialized.

---

## Implementation Strategy

1. **Get to MVP fast.** Complete Phases 1 → 2 → 3 in that order. The MVP delivers operator-visible value (adopt + operate first pane from the desktop) and validates the entire daemon-connection + persistence + onboarding stack.
2. **Validate MVP independently.** Walk `specs/012-flutter-control-panel/quickstart.md` end-to-end against a real `agenttowerd` + bench container. Pass = MVP shippable.
3. **Incremental delivery.** US2..US6 each ship as their own increment in priority order. Every checkpoint is an "operator-visible value" milestone.
4. **Polish the seams, not the centre.** Polish phase (Phase 9) is for cross-cutting concerns; do NOT defer story-specific polish into Phase 9.
5. **Tests grow with stories.** Each US has its own integration test file (T054 / T081 / T097 / T112 / T119 / T130) that mirrors that story's acceptance scenarios. Run them after each story phase completes. The mock-daemon harness (T050) is the shared substrate.
6. **Watch the spec-quality-pass items.** The Round-2 Tier-2 and Tier-3 findings (F-A3..F-A20 from `checklists/alignment.md`) are NOT in this task list. Surface them as plan v2 work or address opportunistically during implementation.

---

**Total tasks**: 172 (T001..T172, updated 2026-05-25 per /speckit-analyze Round 5 — added T172 for the bench-verified analyze regression gate finding T-N2)
**Tasks per phase**: Phase 1 (9) + Phase 2 (44) + Phase 3 US1 (27) + Phase 4 US2 (16) + Phase 5 US3 (15) + Phase 6 US4 (7) + Phase 7 US5 (11) + Phase 8 US6 (13) + Phase 9 (30 — comprises 11 base tasks T143-T153, plus 6 verification tasks T154-T159 from /speckit-analyze Round 1, 5 post-Phase-3 review follow-ups T160-T164 from /speckit-analyze Round 4, 6 post-Phase-8 follow-ups T165-T170 from /speckit-analyze Round 2 covering CR-4 i18n / H-B10 drafted-row / M-11 streaming / H-B1+B2+C2 test rewrites, 1 post-Round-4 task T171 for FR-058 OS-native dispatch wiring, and 1 post-Round-5 task T172 for the bench-verified analyze regression gate; 11+6+5+6+1+1=30).
**Parallel tasks**: 121 marked [P].
**Story-labelled tasks**: 92 across US1..US6.

**Verification-task coverage** (added per /speckit-analyze Round 1):
- Performance: T154 covers FR-062 + FR-063 + FR-064 budgets.
- Security: T155 covers SC-009 (no non-local socket + no CLI subprocess scrape).
- CLI non-regression: T156 covers Const2 (constitution principle IV).
- Architectural invariant: T157 covers FR-005 (no local invent/mutate; all mutations via `app.*`).
- Success-criteria documentation: T158 produces `sc_coverage_map.md` annotating SC-002/008/011/012/013 as user-study or post-launch-survey items and tracing all other SCs to specific tasks.
- Extended integration tests: T054 asserts SC-001 (extension to come in T161 — current shape is vacuous per the post-Phase-3 analyze), T055 asserts SC-010 (extension to come in T162 — current shape covers only the `ContractCompat.compute` matrix), T097 asserts SC-003+SC-004 (T097 description now mandates real tap-driving — see post-fix M1), T112 asserts SC-005 (same — see post-fix M1).

**Post-Phase-3 review follow-ups** (added per /speckit-analyze Round 4, 2026-05-24):
- T160 re-enables suppressed FR-012 dashboard tiles + bumps `agent_ops/dashboard` contract version after an upstream contract bump that extends FEAT-011 `app.dashboard` lands (no such upstream artifact is filed in-tree yet — see T160 body for details). Also handles re-pinning the bench Flutter to 3.27 (T002 known deviation), including the `intl ^0.19.0` downgrade.
- T161 extends T054 with a real SC-001 walk.
- T162 extends T055 with real SC-010 outage/recovery measurements.
- T163 wires the integration test for onboarding milestone auto-tick (post-Phase-3 C9 fix).
- T164 writes widget tests for the 12 Phase 3 US1 surfaces (deferred from Block D in the review fix-up because freezed codegen had to land first).

**Post-Phase-8 follow-ups** (added per /speckit-analyze Round 2, 2026-05-24):
- T165 (CR-4) — FR-067 i18n sweep replacing ~200 hardcoded English strings across Phase 4-8 widgets.
- T166 (H-B10) — FR-072(a) drafted-row daemon-coordination; requires `app.handoff.draft` FEAT-011 extension.
- T167 (M-11) — FR-064 live-update streaming subscriptions; requires daemon-side streaming method.
- T168 (H-B1) — rewrite us3 SC-003 to drive real taps + Stopwatch end-to-end.
- T169 (H-B2) — rewrite us3 SC-004 byte-for-byte invariant to be non-tautological.
- T170 (H-C2) — add SC-005 60-second wall-clock budget to us4_drift.dart.

**Blocked-on-external-FEAT** (added per /speckit-analyze Round 3, 2026-05-24 / A1):
- T160 — blocked on an upstream contract bump that extends FEAT-011 `app.dashboard` with `counts.panes.by_state` / `counts.agents.by_state` / `counts.routes.recently_skipped_count` / `recommended_next_action`. **No upstream artifact is filed in-tree as of /speckit-analyze Round 6 (2026-05-25)** — neither `specs/014-*` nor any `openspec/changes/extend-app-dashboard-fields-for-feat012/`. T160 cannot start until that upstream change is filed and archived. Status reflected in this footer because the task itself cannot be unblocked from inside FEAT-012.
- T166 — blocked on FEAT-011 v1.x extension exposing `app.handoff.draft` so FR-072(a) drafted-row persistence can be wired client-side without losing operator context on widget tear-down.
- T167 — blocked on FEAT-011 v1.x extension exposing a streaming subscription method (SSE inside the Unix-socket framing, or equivalent). Until it lands, `ref.invalidate(...)` polling is the live-update strategy and T154(c) measures manual-refresh round-trip, not push propagation.

These three are the only tasks whose progress depends on changes outside the FEAT-012 worktree. File an upstream artifact (either a new `specs/0NN-*` feature or an openspec change) for T160's `app.dashboard` extension; open coordination changes against FEAT-011 for T166 + T167 when ready to unblock.

**Post-Round-4-analyze follow-up** (added per /speckit-analyze Round 4, 2026-05-24 / C-N1):
- [ ] T171 [P] **OS-native dispatch on incoming notifications (FR-058 wiring).** `OsNativeIntegration.consider(notification, enabled: ...)` is defined in `lib/features/notifications/os_native_integration.dart` but has zero callers — Settings persists the FR-058 `osNativeNotifications` toggle but the dispatcher never fires when new notifications arrive. **Implement now using a polling-diff strategy** (Riverpod listener on `notificationListProvider` that diffs the current snapshot against the previous snapshot to identify newly-arrived `incoming`-lifecycle notifications) and call `osNativeIntegrationProvider.consider(notification, enabled: settings.osNativeNotifications)` for each. The dispatcher's internal de-dup + severity-gate handles the rest. **Upgrade path when T167 streaming lands:** swap the polling-diff producer for the streaming subscription's "newly-arrived" events; the consumer side and dispatcher remain unchanged. (T167 is itself blocked on FEAT-011 v1.x, so polling-diff is the production strategy until that lands — not a temporary fallback.) Closes Round-4 analyze C-N1.

**Post-Round-5-analyze follow-up** (added per /speckit-analyze Round 5, 2026-05-25 / T-N2):
- [ ] T172 [P] **Bench-verified analyze regression gate.** Add `apps/control_panel/tools/bench_verify.sh` that runs inside the flutter-bench Docker container: `flutter pub get && dart run build_runner build --delete-conflicting-outputs && flutter analyze --fatal-errors && flutter test test/core test/features`. The script exits 0 only when all four steps pass; non-zero on any failure. Wire into the T154-T157 verification suite (or a standalone CI workflow) so language-API drift (e.g. the Riverpod 2.x vs 3.x `ref.mounted` mismatch fixed in commit `8e8e629`) is caught at PR time rather than at packaging (T148) or post-merge. Closes Round-5 analyze T-N2.

**Post-Round-4 bench-verification fix** (2026-05-25 / commit `8e8e629`, per /speckit-analyze Round 5 / D-N1):
Restoring the flutter-bench `/workspace/projects` mount (the original mount was lost when the bench container was recycled; recovery required using the host path `/home/brett/projects` rather than the sandbox-visible `/workspace/projects` — see `memory/reference_flutter_bench.md`) surfaced a pre-existing Riverpod-2.x API mismatch in `lib/features/onboarding/onboarding_provider.dart`: the `build()` method's post-build microtask used `ref.mounted`, which is a Riverpod 3.x-only getter; this project pins Riverpod 2.x. Fix swapped to `ref.onDispose` + a local `_disposed` flag. Pre-existing from Phase 3 baseline (commit `888b7fc`); not surfaced by any of the four prior /speckit-analyze rounds (those audit spec artifacts, not Dart source) and not surfaced by T157 (FR-005 invariant audit, scope is UI-side mutation paths only). T172 above is the regression gate that would have caught this. No new task required — fix shipped directly.
