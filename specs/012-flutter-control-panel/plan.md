# Implementation Plan: Flutter Desktop Control Panel for Local Operator Workspaces

**Branch**: `012-flutter-control-panel` | **Date**: 2026-05-23 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/012-flutter-control-panel/spec.md`

## Summary

FEAT-012 ships the first **end-user product surface** of AgentTower: a local Flutter desktop application for Windows, macOS, and Linux that turns `agenttowerd` into a usable operator product instead of a CLI-only daemon. The app is a **pure FEAT-011 client** — it talks only to the local Unix-socket `app.*` namespace, never opens a network socket, never scrapes human CLI output, and never invents or persists daemon-owned state.

The app is organized into three operator workspaces (Agent Operations, Project and Specs, Testing and Demo) plus shared notifications and settings. The first release is deliberately scoped to **adopt-existing-pane** workflows (managed pane creation deferred to FEAT-013) and to the existing FEAT-011 `app.*` method surface (32 methods, contract version 1.0).

Technical approach:

- **Flutter 3.27 stable** (Dart 3.5+) for the desktop UI, packaged as a single-window app per supported OS.
- **Riverpod 2.x** for state management; **freezed + json_serializable** for immutable domain models that mirror FEAT-011 response shapes.
- **Built-in `dart:io` `Socket.connect(InternetAddress(…, type: InternetAddressType.unix), …)`** for the daemon connection. Newline-delimited JSON per FEAT-011 FR-003a/b. No third-party RPC framework.
- **Local user-scoped config store** as a single JSON file at the OS-user app-data path (via `path_provider`), holding only UX state per FR-069. Session token in-memory only per FR-003. No domain-data caching.
- **`flutter_markdown`** for the in-app PRD/architecture/roadmap/feature-spec/OpenSpec-change document viewer (FR-079). External-open via `url_launcher`.
- **`local_notifier`** for cross-platform OS-native notifications (FR-058). Opt-in.
- **`window_manager`** for window geometry persistence (FR-069) and single-window invariant.
- **`logger`** for the rotating local log file (FR-074). No telemetry uploaded.
- **`flutter_localizations` + ARB files** for the i18n layer (FR-067) — English-only at MVP, layer in place for future locales.
- **Test stack**: `flutter_test` (unit + widget), `integration_test` (end-to-end against a Python mock-daemon harness over Unix socket), `alchemist` or `golden_toolkit` (golden tests for theme/density variants per FR-009 and a11y contrast per FR-066).

The app sits next to the existing Python sources in a new top-level `apps/control_panel/` directory so the daemon, CLI, and the desktop app each have their own build root.

## Technical Context

**Language/Version**: Dart 3.5+ on Flutter 3.27 stable (Flutter desktop targets Windows, macOS, Linux). Pinned via `apps/control_panel/.fvm/fvm_config.json` and `apps/control_panel/pubspec.yaml`.

**Primary Dependencies**:
- `flutter_riverpod` 2.x — state management and dependency injection.
- `freezed` + `freezed_annotation` + `json_serializable` + `json_annotation` — immutable models with code-generated `fromJson`/`toJson`/`copyWith`.
- `flutter_markdown` — in-app document rendering for FR-079.
- `url_launcher` — "Open externally" affordance + release-page link for FR-068 update indicator.
- `local_notifier` — cross-platform OS-native notifications for FR-058.
- `window_manager` — window geometry capture/restore for FR-069.
- `path_provider` — per-OS user app-data path resolution for FR-061a / FR-069 / FR-074.
- `logger` + `logger_flutter` — rotating local log file for FR-074.
- `flutter_localizations` + `intl` — i18n layer for FR-067 (English-only MVP).
- `package_info_plus` — installed app version display for FR-068.
- `clipboard` (built into `flutter/services`) — "Copy diagnostics bundle" affordance for FR-074.
- `dart:io` (built-in) — Unix-socket connection via `Socket.connect(InternetAddress(path, type: InternetAddressType.unix), 0)`.

No third-party RPC, gRPC, JSON-RPC, or networking framework. Newline-delimited JSON is hand-rolled to keep the dependency surface small and the wire-framing contract (FEAT-011 FR-003a/b) explicit.

**Storage**:
- **Local user-scoped UX state file**: single JSON file at `<app-data>/agenttower-control-panel/ux-state.json`. Holds the FR-069 enumerated set (window geometry, theme + density, notifications-grouping toggle, OS-native-notification toggle, last workspace, last sub-view per workspace, last project, per-view sort/filter, Settings values, onboarding milestone-completion state). Written via rename-after-write for atomicity.
- **Local rotating log directory**: `<app-data>/agenttower-control-panel/logs/` per FR-074; rotation policy 5 files × 10 MiB.
- **No SQLite, no domain-data cache, no embedded DB.** Daemon is authoritative for every entity in Key Entities except Workspace Selection (per FR-005, FR-069).
- **Session token never persisted** (FR-003).

**Testing**: `flutter_test` for unit + widget tests; `integration_test` for end-to-end flows running against a Python mock-daemon harness that speaks the FEAT-011 `app.*` contract over a temporary Unix socket; `alchemist` for golden tests across Light/Dark/System themes and Comfortable/Compact densities; a separate `a11y` test pass using `flutter_test`'s semantics tree to verify FR-066 labels and focus order. The mock-daemon harness lives at `apps/control_panel/test_harness/mock_daemon/` and is shared between Riverpod-provider unit tests and integration tests.

**Target Platform**:
- **Windows**: Windows 10 1809+ and Windows 11 — packaged as MSIX (sideload, no Microsoft Store at MVP).
- **macOS**: macOS 13 (Ventura)+ — packaged as `.dmg` with notarized + hardened-runtime signing.
- **Linux**: Ubuntu 22.04+ (and equivalent glibc 2.35+) — packaged as `.AppImage` plus an unofficial `.deb`. Snap/Flatpak deferred.

**Project Type**: Desktop application (single-window per FR-010 / Assumption). Single Flutter app talking to a single local `agenttowerd` per FR-001 / FR-060 / FR-061.

**Performance Goals** (from spec FR-062..FR-065 and SC-001..SC-013):
- Cold start to "operationally readable" Dashboard: ≤ 2 s (FR-062).
- First screenful on every list view (Containers, Panes, Agents, Events, Queue, Routes, Projects, Available Validation, Runs, Drift): ≤ 1 s at FEAT-011's default page size of 50 (FR-063).
- Live-update surfaces reflect a new daemon event within 2 s of daemon-side observation (FR-064).
- Adopt-existing-pane completion (submit → confirmed registered-agent state): ≤ 5 s (FR-065).
- Onboarding (launch → first registered agent + log + event + send): ≤ 10 minutes (SC-001).
- Validation run reaches `running` state: ≤ 2 s after trigger (SC-006).
- Demo Readiness summary update after a run resolves: ≤ 5 s (SC-007).
- Drift findings visible on project card: ≤ 60 s from daemon emission (SC-005).
- Daemon-outage transition: live surfaces flip to documented unavailable state within 2 s; revert to live within 5 s of daemon return (SC-010).
- Attention-queue interaction-stability window: 2 s since last operator interaction (FR-053).
- Operator can identify active driving master + current feature/change phase from card-level info alone (no drill-down): ≤ 5 s per project (SC-002).
- Generating a single-feature handoff with auto-filled context completes in ≤ 30 s from "open handoff flow" to "submitted"; Project Context section names repository, PRD, architecture, roadmap, and selected feature spec paths with no operator typing of paths (SC-003).
- For a feature range with at least one deferred and one merged intermediate item, the resolved work-item list shown in preview MUST exactly match the list embedded in the submitted prompt and explicitly call out excluded items (SC-004).
- Across ≥5 distinct daemon-side event classes producing attention-queue items, operator can correctly classify and navigate to the resolution surface for each class within 10 s using only the queue's icon + color treatment (SC-008).
- While the operator hovers over the attention queue, no item under the pointer changes position for ≥ 2 s (the FR-053 interaction-stability window), measured by automated UI interaction tests across 100 simulated live-update bursts (SC-008a).
- Onboarding's step completion rate (steps presented → steps completed) is ≥ 90% across the eight FR-010 milestones, measured across an internal Opensoft operator cohort (SC-011).
- ≥ 90% of new operators report on a post-onboarding survey that they could identify which agent is driving which feature for their primary project from card-level information alone (SC-012).

**Constraints**:
- **Local-only**: FR-001 / FR-060 / SC-009 — the app MUST NOT open a network socket. The only documented network-bound code path is FR-068's release-feed check (HTTPS GET, at most once per app launch); this is explicitly exempted in the spec.
- **Trust model**: Unix socket + same-host UID per FR-061, with per-OS-user isolation per FR-061a.
- **Wire-framing strictness** (per FEAT-011 FR-003a/b): UTF-8 only, `\n`-terminated, no `\r`/`\x00`, no trailing content; per-line request cap 1 MiB and response cap 8 MiB.
- **Session caps** (per FEAT-011): 8 concurrent app sessions process-wide on the daemon; the desktop app uses exactly one session at a time and re-bootstraps on reconnect per FR-003.
- **Pagination**: default 50, cap 200 per FEAT-011 FR-020a; the app uses virtualized infinite scroll with daemon cursors per FR-080.
- **No telemetry**: FR-074 — no diagnostics, no telemetry, no logs are uploaded anywhere. The release-feed check is the only outbound HTTPS request.
- **Accessibility baseline**: WCAG 2.1 AA-equivalent for keyboard navigation, focus order, semantic labels, and 4.5:1 contrast (FR-066). No certified screen-reader pass committed at MVP.

**Scale/Scope**:
- Concurrent projects per operator: ≤ ~5 (FR-024).
- Concurrent panes per workstation: ≤ ~10 bench containers × ~20 panes (matches FEAT-011 scale).
- Concurrent registered agents: ≤ ~200 (matches FEAT-011 scale).
- Event throughput: ≤ ~1k events / day per workstation (matches FEAT-011 scale).
- Routes: ≤ ~100 per workstation (matches FEAT-011 scale).
- Handoffs: open-ended record growth; queryable by project / master / feature-or-change / assignment-state / `created_at` date range per FR-045.

## Constitution Check

*Gate: must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|---|---|---|
| **I. Local-First Host Control** | ✅ PASS | FR-001 / FR-060 / SC-009 forbid network listeners and remote daemon targets. FR-061 reuses the FEAT-011 trust model (Unix socket + same-host UID). FR-061a adds per-OS-user isolation. The only outbound HTTPS code path is the FR-068 release-feed check, explicitly enumerated and exempted in FR-001 / SC-009. |
| **II. Container-First MVP** | ✅ PASS (with note) | First release is adopt-existing-pane only inside bench containers (FR-014 / FR-016 / Out of Scope). Managed pane creation, auto-launch of agent CLIs (Claude, Codex, etc.), and pane lifecycle operations beyond detach are deferred to FEAT-013. No host-only-tmux, Antigravity, or Python-thread-backend work is introduced. |
| **III. Safe Terminal Input** | ✅ PASS | Direct Send (FR-018) calls FEAT-011 `app.send_input` which rides the FEAT-009 safe prompt queue (FR-043). The app does not construct shell commands or interpolate raw prompt text. Helper-policy snapshot per FR-038a preserves auditability across handoffs. |
| **IV. Observable and Scriptable** | ✅ PASS (with note) | The constitution says "Every feature must be usable from the CLI." FEAT-012 introduces a GUI — but the GUI is **purely additive**. All FEAT-002..010 CLI methods remain unchanged and continue to expose the same operations. The FEAT-011 `app.*` namespace is also CLI-scriptable through `agenttower app.*` calls. No automation introduced by FEAT-012 is GUI-only; every operator action the app exposes is reproducible through `app.*` calls from a CLI or test harness. |
| **V. Conservative Automation** | ✅ PASS | The app surfaces daemon state and provides operator-driven actions. It does not decide workflows, choose master/slave assignments, auto-classify events, or auto-route. Helper-agent policy resolution (FR-038a) is operator-supplied or repo-supplied — no automatic policy synthesis. |

**Technical Constraints from constitution** — notes:

- "Primary implementation language is Python." FEAT-012 adds **Dart/Flutter as a second implementation language**, scoped strictly to the desktop client. The daemon, CLI, FEAT-011 backend, and all FEAT-001..010 code remain Python. The Flutter choice was made at the product level (recorded in `docs/product-sections-and-control-panel.md` and `docs/mvp-feature-sequence.md` §1.3 / §FEAT-012) and is treated as a fixed product attribute, similar to "desktop app for Windows, macOS, and Linux". Recorded under **Complexity Tracking** below.
- "MVP UI is CLI-only." (architecture.md §2) — FEAT-012 is explicitly the first post-MVP GUI. The architecture doc was authored when MVP was CLI-only; FEAT-012 is the recorded transition. No update to `architecture.md` is required as part of this plan; the spec for FEAT-012 carries the new commitment.

**Post-design re-check** (after Phase 1 below): unchanged — all five principle gates remain ✅. No new violations were introduced by the research, data-model, contracts, or quickstart artifacts. The three recorded notes under Complexity Tracking (Dart/Flutter as second language; post-MVP GUI; desktop-app data-directory namespace separation) carry through but no additional complexity entries are warranted.

## Project Structure

### Documentation (this feature)

```text
specs/012-flutter-control-panel/
├── plan.md              # This file
├── spec.md              # Feature specification (FR-001..FR-082 + FR-038a + FR-061a)
├── research.md          # Phase 0 — tech-choice resolutions
├── data-model.md        # Phase 1 — entity field/type/relationship/lifecycle detail
├── contracts/           # Phase 1 — daemon-facing and app-internal contracts
│   ├── app-methods-consumed.md   # Which FEAT-011 app.* methods this app uses
│   ├── ux-state.md               # JSON schema for the persisted UX state file
│   └── helper-policy.md          # FR-038a helper-policy field set + sourcing
├── quickstart.md        # Phase 1 — US1 walkthrough (adopt + operate first pane)
├── checklists/          # 18 domain-quality checklists (from /speckit.checklist)
├── clarify-questions.md             # Round 1 clarifications (already answered)
├── clarify-questions-f4-f7.md       # Round 2 clarifications (already answered)
├── codex-prompt-spec-quality-pass.md# Codex prompt for spec-quality-pass change (archived)
└── tasks.md             # Phase 2 — created by /speckit.tasks, NOT by this command
```

### Source Code (repository root)

FEAT-012 adds a **new top-level `apps/` directory** alongside the existing Python `src/agenttower/`. The Flutter app lives entirely under `apps/control_panel/` so the daemon, CLI, and the desktop app each have their own build root. **No existing Python module is renamed, deleted, or rewired.**

```text
apps/control_panel/
├── pubspec.yaml                          # Flutter dependencies + dart_constraints
├── pubspec.lock
├── analysis_options.yaml                 # Lint rules (lints + flutter_lints)
├── l10n.yaml                             # ARB → Dart codegen config (FR-067)
├── README.md                             # Build / run / package instructions
├── lib/
│   ├── main.dart                         # App entrypoint, ProviderScope, window setup
│   ├── app.dart                          # MaterialApp + routing + theme + locale wiring
│   ├── core/
│   │   ├── config/                       # FR-009 Settings model + JSON persistence (FR-069)
│   │   ├── daemon/                       # Unix socket client, app.* envelope, session lifecycle
│   │   │   ├── socket_client.dart        # Raw socket framing per FEAT-011 FR-003a/b
│   │   │   ├── app_client.dart           # app.* method wrappers (typed)
│   │   │   ├── session.dart              # app.hello / re-bootstrap / token in-memory only
│   │   │   ├── envelope.dart             # {ok, app_contract_version, result|error} parsing
│   │   │   └── errors.dart               # 27-entry FEAT-011 closed-set codes
│   │   ├── persistence/                  # ux-state.json read/write (atomic, schema-versioned)
│   │   ├── logging/                      # Rotating file logger per FR-074 (no telemetry)
│   │   ├── update/                       # FR-068 release-feed check + version-display state
│   │   ├── notifications/                # FR-057 grouping rule, FR-058 OS-native dispatch
│   │   ├── shortcuts/                    # FR-007 Ctrl/Cmd+P, FR-075 Ctrl/Cmd+K palette
│   │   └── l10n/                         # Generated Dart from ARB files
│   ├── domain/
│   │   ├── models/                       # freezed models mirroring FEAT-011 read-surface shapes
│   │   ├── lifecycles/                   # State-machine validators per FR-014/028/034/044/048
│   │   └── helper_policy/                # FR-038a snapshot + resolution
│   ├── features/
│   │   ├── agent_ops/                    # Workspace 1: dashboard, containers, panes, agents,
│   │   │                                 # events, queue, routes, health, attention queue
│   │   ├── project_specs/                # Workspace 2: projects, current work, specs, changes,
│   │   │                                 # drift, handoff flow, project removal
│   │   ├── testing_demo/                 # Workspace 3: available validation, runs, demo readiness
│   │   ├── notifications/                # Shared: panel, history, badges, OS-native integration
│   │   ├── settings/                     # Shared: Settings surface, doctor / preflight
│   │   ├── onboarding/                   # First-launch flow + Dashboard nudges (FR-010)
│   │   └── shell/                        # Top-level nav, project switcher, command palette,
│   │                                     # global banners, contract-version-incompatible state
│   ├── ui/
│   │   ├── theme/                        # Light + Dark + System tokens; Comfortable + Compact
│   │   ├── widgets/                      # Reusable card, badge, virtualized list, doc viewer
│   │   └── a11y/                         # Focus, semantic labels, contrast utilities (FR-066)
│   └── routing/                          # App-level routing + workspace + sub-view registry
├── assets/
│   ├── l10n/                             # ARB source (en.arb at MVP per FR-067)
│   └── icons/                            # Severity icons (FR-052), workspace nav icons
├── test/
│   ├── unit/                             # Riverpod provider tests, domain-model tests
│   ├── widget/                           # Widget tests per feature surface
│   ├── golden/                           # alchemist golden tests across theme/density variants
│   ├── perf/                             # Performance-budget tests (FR-062/063/064) + SC coverage map
│   ├── security/                         # Network-trace + subprocess-trace verification (SC-009)
│   └── helpers/                          # In-test mock-daemon, freezed fixture builders
├── integration_test/                     # End-to-end flows against the mock-daemon harness
│   ├── us1_adopt_and_operate.dart        # Mirrors US1 acceptance scenarios
│   ├── us2_project_and_master.dart       # Mirrors US2 acceptance scenarios
│   ├── us3_handoff_flow.dart             # Mirrors US3 + FR-072 failure tiers + FR-081 supersede
│   ├── us4_drift.dart                    # Mirrors US4 acceptance scenarios
│   ├── us5_validation_demo.dart          # Mirrors US5 acceptance scenarios
│   ├── us6_attention_notifications.dart  # Mirrors US6 + FR-053 stability + FR-057 grouping
│   ├── contract_version_skew.dart        # FR-002 banner + per-surface read-only mode
│   ├── runtime_states.dart               # FR-004 five-state distinction
│   └── persistence.dart                  # FR-069/FR-070/FR-076/FR-077 across-launch behavior
├── test_harness/
│   └── mock_daemon/                      # Python script that speaks FEAT-011 app.* over a
│                                         # temp Unix socket; CI-injectable fixtures
└── tools/
    ├── package_windows.ps1               # MSIX build script
    ├── package_macos.sh                  # .dmg + notarization script
    ├── package_linux.sh                  # .AppImage + .deb script
    └── release_feed_check.dart           # Standalone tool for testing FR-068 feed parsing
```

**Structure Decision**: This is a multi-language monorepo. The existing Python sources at `src/agenttower/` (daemon, CLI, FEAT-001..011) are unchanged. The Flutter desktop app lives entirely under `apps/control_panel/` with its own `pubspec.yaml`, lints, build outputs, and test suite. Cross-cutting documentation (PRD, architecture, MVP feature sequence) lives at `docs/` and is referenced from both languages. One FEAT-012 task (T156, CLI non-regression smoke) lands in the existing Python test tree at `tests/integration/test_feat012_cli_noop.py` because it asserts the Python-implemented FEAT-002..010 CLI surfaces produce byte-identical output before and after the desktop-app build is installed; this is the only FEAT-012 task that lives outside `apps/control_panel/`.

## Complexity Tracking

> Constitution Check is overall green, but three notes warrant explicit recording:

| Violation / Tension | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Dart/Flutter added as a second implementation language (constitution names Python as the primary language) | The product decision to ship a Flutter desktop app is recorded in `docs/product-sections-and-control-panel.md` §1.3 and `docs/mvp-feature-sequence.md` §FEAT-012. Flutter is the cheapest practical path to a single codebase that ships on Windows, macOS, and Linux with native window + OS notification integration. | Continuing CLI-only (no GUI) would not deliver the FEAT-012 product. Building a Python-based GUI (PySide / Tk / Toga) would carry per-OS packaging complexity worse than Flutter's mature desktop pipeline and is not aligned with the product decision. Building a web-based control panel would violate FR-001 / FR-060 / SC-009 (no network listener) and add a browser-trust-model surface the project explicitly rejected (Out of Scope). |
| First post-MVP GUI surface (architecture.md §2: "MVP UI is CLI-only") | The architecture doc was authored when MVP was CLI-only; the FEAT-012 spec explicitly is the post-MVP transition. The constraint was a scoping decision for the daemon-and-CLI MVP, not a forever rule. The CLI and `app.*` surfaces remain authoritative and scriptable; the GUI is additive. | Deferring the GUI further would not change the spec's commitment. Treating the GUI as a follow-on patch to FEAT-011 (no separate spec) would lose the operator-facing requirements clarity that FR-001..FR-082 + FR-038a / FR-061a captured. |
| Desktop-app durable files use the `agenttower-control-panel` data-directory namespace, separate from the daemon's `agenttower` namespace under `~/.config/opensoft/agenttower/` / `~/.local/state/opensoft/agenttower/` / `~/.cache/opensoft/agenttower/` (constitution Technical Constraints). The desktop app persists UX state at `<app-data>/agenttower-control-panel/ux-state.json` and rotating logs at `<app-data>/agenttower-control-panel/logs/` per research R-06. | The desktop app is a separate process owned by a separate code surface (`apps/control_panel/` in Dart, not `src/agenttower/` in Python). Sharing the daemon's namespace would conflate ownership and complicate per-OS-user isolation (FR-061a). The chosen namespace is the OS-blessed per-OS-user application-data location resolved via `path_provider.getApplicationSupportDirectory()`. | Putting the file under `~/.local/state/opensoft/agenttower/control-panel-ux-state.json` (rejected because it implies daemon ownership and the daemon would have to know to ignore it). Putting it under the constitution-named `~/.config/opensoft/agenttower/` (rejected because that path is for daemon config that the operator may have already populated; co-location risks accidental override). |
