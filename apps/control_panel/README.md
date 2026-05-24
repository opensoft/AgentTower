# AgentTower Control Panel (`apps/control_panel/`)

The FEAT-012 Flutter desktop client for `agenttowerd`. Cross-platform
(Windows / macOS / Linux), single-window, pure FEAT-011 `app.*`
consumer — never opens a network socket (except the FR-068 release
feed), never scrapes CLI output, never invents domain state locally.

Part of [FEAT-012](../../specs/012-flutter-control-panel/spec.md).
This is the Dart/Flutter half of a multi-language monorepo. The
Python daemon + CLI sources stay at `src/agenttower/` (untouched by
FEAT-012).

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Flutter SDK | 3.27 stable (pin) | bench currently runs 3.44.0 as a documented Phase-3 deviation (T002) |
| Dart | 3.5+ (3.12 in bench) | tracked via Flutter SDK |
| Python 3 | 3.10+ | required for `test_harness/mock_daemon/server.py` (integration tests) |
| Xvfb | any | required for headless Linux integration tests |
| `libnotify-dev` + `libgtk-3-dev` + `ninja-build` + `cmake` | apt-current | Linux desktop build deps |

The repo ships an `.fvm/fvm_config.json` pinning Flutter 3.27. Use FVM
when local development is feasible; the in-bench toolchain (3.44.0)
is a documented exception tracked by T002 + T160.

## Build

```bash
# From apps/control_panel/
flutter pub get
dart run build_runner build --delete-conflicting-outputs
flutter analyze
flutter test --no-pub
flutter build linux --debug     # or macos / windows per platform
```

`build_runner` outputs (`*.freezed.dart`, `*.g.dart`,
`app_localizations*.dart`, per-platform `generated_plugin_registrant*`)
are gitignored — regenerate locally; CI runs the same step.

## Run (development)

```bash
flutter run -d linux \
  --dart-define=DAEMON_SOCKET_PATH=/var/run/agenttower/app.sock
```

The default daemon socket path is `/var/run/agenttower/app.sock` per
FEAT-011's host-daemon contract; override via the
`DAEMON_SOCKET_PATH` env-define for development against a custom
socket, or change it in Settings → Connection at runtime.

## Run integration tests (Xvfb on Linux)

```bash
# Single test
xvfb-run -a flutter test integration_test/us2_project_and_master.dart \
  -d linux --no-pub

# Whole suite (us1..us6 + runtime_states + contract_version_skew)
for f in integration_test/*.dart; do
  echo "=== $f ===" && xvfb-run -a flutter test "$f" -d linux --no-pub
done
```

Integration tests bring up a Python mock daemon via
`test_harness/mock_daemon/server.py`. The harness is the test's
child process (per swarm-review CR-2 repair); `python3` must be on
PATH.

## Packaging (per FR-068)

Per-OS packaging scripts live under `tools/`:

- `tools/package_windows.ps1` — MSIX (sideload, no Microsoft Store at MVP)
- `tools/package_macos.sh` — `.dmg` with notarized + hardened-runtime signing
- `tools/package_linux.sh` — `.AppImage` + unofficial `.deb`

T148 tracks the full packaging implementation; the stubs ship today
so the structure is auditable. Signed with the Opensoft daemon
code-signing CA per research R-13.

## Lint rules

The project uses `flutter_lints` (configured in `analysis_options.yaml`)
plus project-specific overrides: no implicit-dynamic, strict
type-inference. Phase-3 architectural notes (H3/M-A1/etc.) are
preserved as inline comments in the affected files; the
swarm-review (2026-05-24) added seven cross-cutting helpers — see
`lib/ui/widgets/README.md` for the catalog.

## Mock-daemon harness (`test_harness/mock_daemon/`)

`server.py` listens on a temp Unix socket and replies with fixture
JSON for the FEAT-011 `app.*` methods. Each integration test
constructs a fixture payload, hands it to
`MockDaemonClient.start(fixture:)`, and the test framework speaks
to the harness over the socket through the production
`DaemonSession`/`SocketClient` path.

`MockDaemonClient.stop()` uses `ProcessStartMode.normal` per
swarm-review CR-2 — `detachedWithStdio` made `kill`/`exitCode`
throw on every teardown.

## Project structure

| Path | Purpose |
|---|---|
| `lib/main.dart` | Entry point: `runApp(ProviderScope(child: AgentTowerControlPanel()))` |
| `lib/app.dart` | Root `MaterialApp` + theme + locale + router |
| `lib/core/daemon/` | `AppClient`, `DaemonSession`, envelope/error types |
| `lib/core/persistence/` | `UxStateRepository` (only file the app writes) |
| `lib/core/logging/` | Rotating log file, latency capture, uncaught error sink |
| `lib/core/shortcuts/` | Command-palette + keyboard-shortcut registry |
| `lib/core/notifications/` | Grouping rule + OS-native dispatcher (T032/T033) |
| `lib/core/update/` | FR-068 release-feed checker (sole permitted outbound) |
| `lib/domain/models/` | Daemon-mirror freezed models — never mutated locally |
| `lib/domain/lifecycles/` | FR-014/034/044/048 state validators |
| `lib/domain/severity.dart` | R-15 + R-22 severity color/icon/label triad helper |
| `lib/domain/master_qualification.dart` | FR-071 master-class lookup + envelope |
| `lib/features/agent_ops/` | US1 + attention queue + operator history surfaces |
| `lib/features/project_specs/` | US2 + US3 + US4 surfaces (projects, current work, specs, changes, drift, handoff flow) |
| `lib/features/testing_demo/` | US5 surfaces (available validation, runs, demo readiness) |
| `lib/features/notifications/` | US6 panel + history + badges + OS-native integration |
| `lib/features/settings/` | FR-009 Settings view + doctor + diagnostics bundle |
| `lib/features/shell/` | AppShell, global banner, runtime-state provider, version display |
| `lib/ui/widgets/` | Cross-cutting widgets — see `lib/ui/widgets/README.md` |

## Speckit + swarm-review trail

Implementation history lives under `specs/012-flutter-control-panel/`:

- `spec.md` — 83 FRs + 14 SCs
- `plan.md` — tech stack, architecture, cross-cutting widget conventions
- `tasks.md` — 170 task items (164 + 6 post-Phase-8 follow-ups)
- `data-model.md` — freezed model shapes + cross-cutting invariants
- `swarm-review-2026-05-24.md` — 88-finding multi-expert code review report
- `swarm-review-fix-plan.md` — batched remediation plan
- `flutter-testing-plan.md` — test-pyramid + bench-deviation notes

The spec is the source of truth for behavior; this README is the
source of truth for build / run / package mechanics.
