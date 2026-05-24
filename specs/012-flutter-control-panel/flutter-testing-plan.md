# FEAT-012 Flutter Testing Plan

**Feature**: 012-flutter-control-panel  
**Branch**: `012-flutter-control-panel`  
**Date**: 2026-05-23  
**Scope**: Define the practical testing lanes for the AgentTower Flutter desktop app using the existing Flutter bench and shared Flutter infrastructure.

## What exists today

### AgentTower FEAT-012 app workspace

- App path: `/home/brett/projects/AgentTower-worktrees/012-flutter-control-panel/apps/control_panel`
- Present now:
  - `pubspec.yaml`
  - `.fvm/fvm_config.json`
  - `analysis_options.yaml`
  - `l10n.yaml`
  - `lib/`
  - `test/`
  - `integration_test/`
  - `test_harness/`
  - `tools/`
- Not present yet:
  - `windows/`
  - `macos/`
  - `linux/`
- Meaning:
  - T009 is still the gating prerequisite before real Flutter implementation work begins.

### Flutter bench infrastructure

- Repo path: `/home/brett/projects/workBenches/devBenches/flutterBench`
- Container stack is layered and already built:
  - `workbench-base:latest`
  - `dev-bench-base:latest`
  - `flutter-bench:latest`
- Shared infrastructure already running:
  - `shared-adb-server`
- Bench image facts verified from Docker:
  - `flutter-bench:latest` exists locally
  - Flutter in image: `3.44.0`
  - FVM in image: `4.1.0`

### Important constraints discovered

1. **The FEAT-012 app is pinned to Flutter 3.27 via FVM**, but the shared bench image currently has Flutter 3.44 installed globally.
2. **The `app.*` backend contract is host-only**.
   - FEAT-011 / architecture says any bench-container peer calling `app.*` must receive `host_only`.
   - That means the real desktop app cannot use a bench container as its final runtime environment for live-daemon integration.
3. **The current Flutter bench is a toolchain/devcontainer environment, not a native desktop-display container**.
   - Its `devcontainer.json` mounts `/workspace/projects` and Docker, but does not mount X11/Wayland display sockets.
   - So it is good for codegen, analysis, unit/widget/golden tests, and mock-daemon integration work.
   - It is not the right place for final "real desktop app talks to real host daemon" verification.

## Testing model

FEAT-012 needs **three separate test lanes**.

## Lane 1 — Containerized deterministic Flutter test lane

**Purpose**: Fast, repeatable developer test loop inside `flutterBench`.

**Use for**:
- T009 bootstrap
- dependency install
- code generation
- `flutter analyze`
- `dart format`
- unit tests
- widget tests
- golden tests
- integration tests against the mock daemon harness

**Do not use for**:
- real `app.*` integration against host `agenttowerd`
- final desktop runtime verification
- per-OS packaging validation

### Why this lane works

- `flutterBench` mounts host projects at `/workspace/projects`, so the AgentTower worktree is available inside the container.
- The image already contains Flutter and FVM.
- FEAT-012 already plans a Python mock daemon at:
  - `apps/control_panel/test_harness/mock_daemon/`
- The plan already defines this test stack:
  - `flutter_test`
  - `integration_test`
  - `alchemist`

### Required setup in this lane

1. Start `flutterBench`
   ```bash
   cd /home/brett/projects/workBenches/devBenches/flutterBench
   ./scripts/start-monster.sh
   ```

2. Enter the bench
   ```bash
   docker exec -it flutter-bench zsh
   ```

3. Switch to the FEAT-012 app
   ```bash
   cd /workspace/projects/AgentTower-worktrees/012-flutter-control-panel/apps/control_panel
   ```

4. Honor the FEAT-012 pin with FVM
   ```bash
   fvm install 3.27.0
   fvm use 3.27.0
   fvm flutter --version
   ```

5. Complete T009
   ```bash
   fvm flutter config --enable-windows-desktop --enable-macos-desktop --enable-linux-desktop
   fvm flutter create --platforms=windows,macos,linux .
   fvm flutter pub get
   fvm flutter gen-l10n
   ```

6. Foundational dev loop after T009
   ```bash
   fvm flutter analyze
   dart format --output=none --set-exit-if-changed .
   fvm flutter test
   fvm flutter test integration_test
   ```

### Deliverables for this lane

- T009 complete
- platform directories materialized
- mock daemon harness implemented
- base test pipeline green inside `flutterBench`

## Lane 2 — Host desktop + real daemon integration lane

**Purpose**: Verify the actual product shape:
- packaged local desktop app
- host-local `app.*` client
- real `agenttowerd`
- real bench containers
- real tmux panes

**This lane must run on the host OS, not inside `flutterBench`.**

### Why this lane is required

The FEAT-011 contract is explicit:
- `app.*` is host-only
- bench-container peers are rejected with `host_only`

So even if the app binary can be built inside a container, **the real integration test must be run from the host desktop environment**.

### Use for

- US1 quickstart validation
- host socket reachability
- real `app.hello` / `app.preflight` / `app.dashboard`
- adopt pane flow
- log attach flow
- events / queue / routes against real daemon state
- doctor / diagnostics behavior against real workstation state
- daemon outage / reconnect behavior

### Required setup in this lane

1. Run `agenttowerd` on host
2. Ensure at least one bench container with tmux panes exists
3. Launch the Flutter desktop app from the host OS
4. Execute:
   - `specs/012-flutter-control-panel/quickstart.md`

### Minimum acceptance slice for this lane

- Dashboard healthy
- container visible
- pane visible as unmanaged
- adopt pane succeeds
- agent appears
- log attachment active
- event flow visible
- direct send succeeds
- route create succeeds
- queue row appears
- daemon outage switches to `runtime-unreachable`
- reconnect recovers cleanly

## Lane 3 — Native packaging and installer lane

**Purpose**: Verify FEAT-012 as a distributable desktop product.

**This lane is per-OS and host-native.**

### Use for

- `flutter build linux --release`
- `flutter build macos --release`
- `flutter build windows --release`
- packaging scripts in `apps/control_panel/tools/`
- installer smoke
- version display / release-feed behavior

### Why this lane is separate

Packaging and signing are OS-native concerns:
- Linux: AppImage / `.deb`
- macOS: `.dmg` + notarization
- Windows: MSIX

These should not be conflated with the containerized developer loop.

## Recommended implementation order

### Phase A — Make the bench useful immediately

1. Complete T009 inside `flutterBench` using FVM 3.27
2. Verify:
   - `windows/`, `macos/`, `linux/` exist
   - `pub get` succeeds
   - `gen-l10n` succeeds
3. Record the exact working commands in `apps/control_panel/README.md` if they differ in the bench

### Phase B — Build the deterministic test substrate

1. Implement:
   - `apps/control_panel/test_harness/mock_daemon/server.py`
2. Stand up initial tests:
   - unit tests
   - widget tests
   - one integration test proving the app can talk to the mock daemon over a Unix socket
3. Wire CI-grade local commands:
   ```bash
   fvm flutter analyze
   fvm flutter test
   fvm flutter test integration_test
   ```

### Phase C — Prove host-real integration

1. Run the app from host Linux first
2. Use real `agenttowerd`
3. Use real bench container + tmux panes
4. Execute the US1 quickstart end to end
5. Only after Linux host passes, expand to:
   - Windows host
   - macOS host

### Phase D — Add packaging smoke

1. Verify release builds per OS
2. Run package scripts
3. Smoke:
   - install
   - launch
   - bootstrap
   - Settings / version / diagnostics

## Gaps to close

These are the concrete gaps between current state and a real testing pipeline:

1. **T009 is still open**
   - no platform stubs yet

2. **No test harness implementation yet**
   - `apps/control_panel/test_harness/` exists but is not populated

3. **No real Flutter tests yet**
   - test directories are present but not populated

4. **Version drift between bench-global Flutter and FEAT-012 pin**
   - bench global = 3.44.0
   - FEAT-012 pin = 3.27.0
   - fix by using FVM inside the bench for AgentTower work

5. **No display-capable container path for true desktop runtime**
   - not needed for Lane 1
   - host runtime covers Lane 2
   - only add display mounts to `flutterBench` later if you explicitly want containerized Linux desktop smoke

## Concrete test plan

### Immediate next steps

1. Start `flutterBench`
2. Enter it and switch to `apps/control_panel`
3. Use FVM to install/use `3.27.0`
4. Complete T009
5. Run:
   ```bash
   fvm flutter pub get
   fvm flutter gen-l10n
   fvm flutter analyze
   ```

### After T009

6. Implement the mock daemon harness
7. Add the first three tests:
   - envelope parser unit test
   - socket client unit test against fixture daemon
   - one integration test for bootstrap/dashboard

### After first tests are green

8. Run the FEAT-012 app from the host OS against real `agenttowerd`
9. Execute the US1 quickstart
10. Record failures as implementation tasks, not infrastructure speculation

## Bottom line

Use the existing Flutter bench for **development, codegen, and deterministic tests**.

Do **not** use the Flutter bench as the final runtime for the real AgentTower app, because FEAT-011 explicitly makes `app.*` **host-only** for container peers.

So the correct testing strategy is:

1. **Container lane** for Flutter toolchain + mock-daemon tests
2. **Host lane** for real desktop app + real `agenttowerd` + real bench/tmux flows
3. **Per-OS packaging lane** for installers and release smoke
