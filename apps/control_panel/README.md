# AgentTower Flutter Desktop Control Panel

Local-first desktop operator UI for `agenttowerd`. Part of [FEAT-012](../../specs/012-flutter-control-panel/spec.md).

This is the Dart/Flutter half of a multi-language monorepo. The Python daemon + CLI sources stay at `src/agenttower/` (untouched by FEAT-012).

## Status

**Phase 1 (Setup) in progress.** Tasks T001–T008 done in this commit; T009 (`flutter create --platforms=...`) requires the operator to run with the Flutter SDK installed. See **Operator prerequisites** below.

Tracking: `../../specs/012-flutter-control-panel/tasks.md` (159 tasks across 9 phases).

## Operator prerequisites

Before running tasks T010+ you must complete T009 — bootstrapping Flutter's per-OS platform stubs:

```bash
# 1. Install Flutter 3.27 stable per research R-01.
#    Recommended: use FVM (fvm.app) so the pin in .fvm/fvm_config.json takes effect.
#    Otherwise install via https://docs.flutter.dev/get-started/install
#    and ensure `flutter --version` reports ≥ 3.27.0.

# 2. From this directory:
cd apps/control_panel

# 3. Enable desktop targets (once per machine):
flutter config --enable-windows-desktop --enable-macos-desktop --enable-linux-desktop

# 4. Materialize per-OS platform stubs:
flutter create --platforms=windows,macos,linux .

# 5. Fetch dependencies + generate ARB-based localizations:
flutter pub get
flutter gen-l10n

# 6. Codegen for freezed/json_serializable (runs after Phase 2 starts producing models):
flutter pub run build_runner watch --delete-conflicting-outputs
```

After step 4, the directories `windows/`, `macos/`, `linux/` will exist alongside `lib/`. Then Phase 2 (Foundational) implementation can begin.

## Project layout

```
apps/control_panel/
├── pubspec.yaml                          # Dependencies (T002 ✓)
├── .fvm/fvm_config.json                  # Flutter version pin (T003 ✓)
├── analysis_options.yaml                 # Lints (T004 ✓)
├── l10n.yaml                             # i18n codegen config (T005 ✓)
├── README.md                             # This file (T003 ✓)
├── lib/                                  # Dart source (Phase 2 onward)
├── assets/
│   ├── l10n/                             # ARB source — en.arb stub (T006 ✓)
│   └── icons/                            # Severity + nav icons (T007 ✓)
├── test/                                 # Unit + widget + golden tests (Phase 2+)
├── integration_test/                     # End-to-end against mock daemon (Phase 2+)
├── test_harness/
│   └── mock_daemon/                      # Python mock daemon (T050+)
└── tools/                                # Per-OS packaging scripts (T008 ✓ stubs)
```

## Build / run

After completing operator prerequisites above:

```bash
# Run in debug:
flutter run -d linux       # Linux desktop
flutter run -d macos       # macOS desktop
flutter run -d windows     # Windows desktop

# Build release artifacts:
flutter build linux --release
flutter build macos --release
flutter build windows --release

# Per-OS packaging (after release build):
./tools/package_linux.sh    # AppImage + .deb
./tools/package_macos.sh    # .dmg + notarization
./tools/package_windows.ps1 # MSIX
```

## Tests

```bash
flutter test                                # unit + widget + golden
flutter test integration_test               # end-to-end against mock daemon
```

Mock daemon lives at `test_harness/mock_daemon/server.py` (Python, see research R-17).

## Lints + format

```bash
flutter analyze
dart format --output=none --set-exit-if-changed .
```

## See also

- `../../specs/012-flutter-control-panel/spec.md` — feature requirements (82 FRs + FR-038a + FR-061a)
- `../../specs/012-flutter-control-panel/plan.md` — technical context + Constitution Check
- `../../specs/012-flutter-control-panel/research.md` — 42 tech-choice decisions (R-01..R-42)
- `../../specs/012-flutter-control-panel/data-model.md` — entity definitions
- `../../specs/012-flutter-control-panel/contracts/` — FEAT-011 method consumption + ux-state schema + helper-policy contract
- `../../specs/012-flutter-control-panel/tasks.md` — 159 implementation tasks
- `../../specs/012-flutter-control-panel/quickstart.md` — US1 walkthrough
