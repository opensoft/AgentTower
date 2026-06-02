# T153 — Cross-OS Manual Validation Runbook (FEAT-012)

> **Status: OPERATOR RUNBOOK** — fillable. This is the hands-on acceptance gate
> for FEAT-012. It cannot be automated (real daemon + real bench/tmux + human
> visual sign-off + signed installers on three OSes). The *logic* it confirms is
> already covered by the `integration_test/us1…us6` suite against the mock
> daemon; this runbook validates the **real packaged app on real hardware**.

**Task**: T153 · **Mirrors**: `quickstart.md` (US1 P1 slice) · **FRs**: FR-012,
013, 014, 015, 016, 017, 018, 019, 020, 021, 062, 064, 065, 009, 074, 061, 068,
SC-010 · **Release-gate add-ons**: T148 (packaging) + T178 (bundle id).

---

## 0. How to use this runbook

1. Do the **per-OS setup** (§2) on each of the three target OSes.
2. Run **§3 pre-flight**, then **§4 Steps 1–7** on that OS, ticking the boxes.
3. Run the **§5 packaging/trust checks** on that OS.
4. Fill the **§6 results matrix** for that OS.
5. When all three OSes show PASS (or a documented, accepted deviation), fill **§7**
   and mark T153 `[X]` in `tasks.md`.

Legend per check: **P** = pass · **F** = fail (file a bug) · **N/A** = not
applicable on this OS (note why).

---

## 1. Target matrix

| OS | Min version (per plan.md) | Installer format | Signing / trust surface |
|---|---|---|---|
| **Windows** | Windows 10 1809+ / Windows 11 | MSIX (sideload) | SmartScreen / "verified publisher" |
| **macOS** | macOS 13 (Ventura)+ | `.dmg`, notarized + hardened runtime | Gatekeeper / notarization |
| **Linux** | Ubuntu 22.04+ (glibc 2.35+) | `.AppImage` (+ unofficial `.deb`) | (no OS publisher gate) |

Reference machine for the perf budgets (per spec Assumptions): 8-core x86-64
≥3.0 GHz, 16 GB RAM, NVMe SSD, OS at idle, no concurrent background apps.

---

## 2. Per-OS one-time setup

### 2a. Stand up the backend (host side)

- [ ] `agenttowerd` installed and **running**, reachable at the OS-default socket.
  On Linux the desktop app's bootstrap (`main.dart` `_defaultDaemonSocketPath`)
  resolves, in order: `$DAEMON_SOCKET_PATH` (env override) →
  `$XDG_RUNTIME_DIR/opensoft/agenttower/agenttowerd.sock` (typically
  `/run/user/$UID/opensoft/agenttower/agenttowerd.sock`) →
  `${XDG_STATE_HOME:-$HOME/.local/state}/opensoft/agenttower/agenttowerd.sock`.
  This matches the CLI/daemon default (`src/agenttower/paths.py`). On Windows the
  AF_UNIX path is used (Windows 10 1803+).

> ⚠️ **Known socket-default inconsistency (needs a product decision — do NOT
> silently pick one during T153).** Three sources disagree on the *displayed/
> stored* default:
> - **App bootstrap** (`main.dart`): the XDG runtime/state path above — agrees
>   with the CLI/daemon.
> - **App Settings default** (`lib/features/settings/providers.dart:13`):
>   `'/var/run/agenttower/app.sock'` — does **not** match bootstrap or the CLI.
> - **Mounted-default** (`config_doctor/socket_resolve.py`):
>   `/run/agenttower/agenttowerd.sock`.
>
> For the T153 run, set `DAEMON_SOCKET_PATH` (or the Settings socket-path field)
> explicitly to the path `agenttowerd` is actually bound to, and record it in
> §6. File the `settings/providers.dart` default mismatch as a follow-up bug —
> it is out of scope for this runbook and for the T153 test-harness fixups.
- [ ] Docker Engine running with **≥1 bench container** active.
- [ ] The bench container has **≥1 live tmux pane hosting a real agent CLI**
  (Claude / Codex / Gemini / OpenCode) — needed for Step 3's classifiable events.
- [ ] FEAT-011's `app_contract_version` **major** matches the app's expected major.

### 2b. Build + sign + install the desktop app

Build the **signed installer** for the OS (per `apps/control_panel/README.md`
§Packaging). **The packaging scripts live under `apps/control_panel/tools/` and
MUST be run with `apps/control_panel/` as the working directory** (they resolve
the Flutter build output relative to cwd). Run `cd apps/control_panel` first, or
prefix each invocation, e.g. `cd apps/control_panel && FLUTTER=flutter327 bash
tools/package_linux.sh`.

- **Windows** (PowerShell): from `apps\control_panel\`, run
  `tools\package_windows.ps1` → MSIX. Sign with the Opensoft daemon
  code-signing CA (do **not** use `SKIP_SIGNING=1` for the release-gate run).
- **macOS**: from `apps/control_panel/`, run `tools/package_macos.sh` → `.dmg`,
  **notarized + hardened runtime** (do **not** use `SKIP_NOTARIZATION=1` for
  the release-gate run).
- **Linux**: from `apps/control_panel/`, run `tools/package_linux.sh` →
  `.AppImage` (+ `.deb`). See §2c for the Linux build prerequisites.

- [ ] Installer built without errors.
- [ ] Installed the app from the installer (not `flutter run`) — this is what
  ships, so it's what's under test.
- [ ] First-launch onboarding is **not** yet completed (fresh `ux-state.json`),
  or re-entered from Settings. To reset: delete
  `<app-data>/agenttower-control-panel/ux-state.json`.

### 2c. Linux build prerequisites + troubleshooting (bench-confirmed 2026-06-02)

- [ ] **`libnotify-dev` installed** — the Linux desktop build links against
  `/usr/lib/x86_64-linux-gnu/libnotify.so` (transitively via `local_notifier`).
  Without it the GTK build fails at link time. Install:
  `sudo apt-get install -y libnotify-dev`. (Add this to the flutter-bench image
  setup so CI doesn't rediscover it.)
- [ ] **Build dir not root-owned.** A prior root-owned
  `apps/control_panel/build/linux/...` tree (left by an earlier bench Docker
  session) blocks CMake writes with a permission error. Fix before building:
  `sudo chown -R "$USER:$USER" apps/control_panel/build/linux` — or wipe it:
  `rm -rf apps/control_panel/build/linux`.
- [ ] `appimagetool` on PATH **if** producing the `.AppImage` (the bench lacks
  it; the `.deb` path does not need it — see §5).
- [ ] **Clear stale tmux sockets before `scan --panes`.** Prior smoke sessions
  can leave dead tmux sockets behind, which makes `agenttower scan --panes`
  return `ok: true` but **degraded**. This is an environment artifact, not an
  app defect — clean up the orphaned sockets (`tmux kill-server` in the bench,
  or remove the stale `$TMUX_TMPDIR`/`/tmp/tmux-*` entries) and re-scan for a
  clean run.

---

## 3. Pre-flight (run before launching the app, each OS)

```bash
# Daemon reachable. There is NO `agenttower preflight` command on this branch;
# the app calls `app.preflight` over the socket internally. From the CLI, use:
agenttower status --json          # daemon reachability over the local socket
agenttower config doctor --json   # closed-set FEAT-005 diagnostic checks

# At least one bench container
docker ps --filter "name=bench" --format "table {{.Names}}\t{{.Status}}"

# At least one tmux pane in the bench container
docker exec -u "$USER" <bench-container> tmux list-panes
```

> **Windows note**: in native PowerShell `$USER` won't resolve — replace it with
> the explicit Windows username matching the bench container's UID, or run the
> docker commands from inside WSL2.

- [ ] **Win**  - [ ] **macOS**  - [ ] **Linux**  — all three pre-flight commands succeed.

If any fail, fix the prerequisite first (the app's doctor surfaces the same checks).

---

## 4. Procedure — Steps 1–7

Run every step on each OS. Tick **P/F/N-A** per OS in the small table after each step.

### Step 1 — Launch + bootstrap (US1 §1)
1. Launch from the OS launcher / Start menu / Spotlight (the **installed** app).
2. On first launch: onboarding opens at "Daemon reachable"; that milestone
   self-completes when `app.hello` returns (no click).
3. Verify on the Dashboard: `daemon: Healthy`; contract version shown; container
   count + pane-count-by-state + agent count visible; recommended action "Adopt a pane".

| Acceptance (FR) | Win | macOS | Linux |
|---|---|---|---|
| Dashboard `daemon: Healthy` (FR-012) |  |  |  |
| ≥1 container shown (FR-013) |  |  |  |
| ≥1 pane `discovered-and-unmanaged` (FR-014) |  |  |  |
| "Adopt a pane" prominent (FR-012) |  |  |  |
| **Dashboard readable ≤ 2 s** — stopwatch launch→readable (FR-062) | _s | _s | _s |

> **Note on the 4 dashboard tiles**: until FEAT-014 (contract 1.1) merges + T160b
> lands, the pane-by-state / agent-by-state / recently-skipped-route /
> recommended-action tiles are **omitted by design** at contract 1.0 (per the
> FR-012 contract-gated clause). Record "omitted (contract 1.0)" — **not** a fail.

### Step 2 — Adopt a pane (US1 §2)
1. Agent Operations → Panes → **Adopt** on the unmanaged pane.
2. Fill: `label` (e.g. `claude-master-1`), `role` = **master** (needed for Step 5),
   `capability` (match the pane class), `project_path`, `attach_log_now` = **true**.
3. Submit (`app.agent.register_from_pane`).

| Acceptance (FR) | Win | macOS | Linux |
|---|---|---|---|
| Pane → `discovered-and-registered` (FR-014) |  |  |  |
| New agent in Agents view (FR-015) |  |  |  |
| Log attachment `active` (FR-017) |  |  |  |
| **Submit → registered ≤ 5 s** (FR-065) | _s | _s | _s |
| Incompatible role/capability → inline validation error (FR-016) |  |  |  |

### Step 3 — Watch events flow (US1 §3)
1. Go to Events (or the per-agent activity panel).
2. In the bench pane, make the agent produce output (e.g. prompt Claude; let it respond).

| Acceptance (FR) | Win | macOS | Linux |
|---|---|---|---|
| Events in `observed_at` order (FR-019) |  |  |  |
| **New event visible ≤ 2 s** of classification (FR-064) | _s | _s | _s |
| Agent "last meaningful activity" advances (FR-030/064) |  |  |  |

### Step 4 — Direct send (US1 §4)
1. Agent detail → **Direct Send** → non-empty payload (e.g. `Hello from the desktop app`) → submit (`app.send_input`).

| Acceptance (FR) | Win | macOS | Linux |
|---|---|---|---|
| Empty payload rejected client-side (FR-018) |  |  |  |
| Daemon response shown inline (FR-018) |  |  |  |
| No silent retry on failure (FR-018) |  |  |  |
| Resulting event links back to the send (FR-019) |  |  |  |

### Step 5 — Route management (US1 §5)
1. Agent Operations → Routes → **Add route**: `source` = the master, `event_class`
   = one produced in Step 3, `target` = a peer agent (adopt another pane if needed),
   `master_rule` = default. Submit (`app.route.add`).
2. Trigger a matching event; check Queue.

| Acceptance (FR) | Win | macOS | Linux |
|---|---|---|---|
| Form refuses missing fields (FR-021) |  |  |  |
| Route shows `enabled, healthy` (FR-021) |  |  |  |
| Matching event → new `queued` row in Queue (FR-020) |  |  |  |

### Step 6 — Daemon-outage handling (US1 §6)
1. Stop the daemon: `pkill -f agenttowerd` (Linux/macOS) / `Stop-Process -Name
   agenttowerd -Force` (Windows).
2. Verify outage handling, then restart (`agenttowerd &` / `Start-Process
   agenttowerd`) and click **Retry connection**.

| Acceptance (SC-010 / FR-004) | Win | macOS | Linux |
|---|---|---|---|
| **Outage detected ≤ 2 s** (health flips) | _s | _s | _s |
| Each live view shows its `runtime-unreachable` state (not a spinner) |  |  |  |
| `Retry connection` affordance present |  |  |  |
| **Recovery ≤ 5 s** after daemon return | _s | _s | _s |
| No stale data labelled as live during outage |  |  |  |

### Step 7 — Settings doctor + diagnostics (FR-009 / FR-074)
1. Settings → **Run doctor** (or `Ctrl/Cmd+K → "Run doctor"`).
2. **Copy diagnostics bundle**.

| Acceptance (FR) | Win | macOS | Linux |
|---|---|---|---|
| Doctor names all 6 checks (socket, peer UID, contract, app-data writable, log writable+size, OS-notif perm) (FR-009) |  |  |  |
| Each check shows pass/fail + latency + failure explanation (FR-009) |  |  |  |
| Diagnostics bundle has all 5 fields (doctor output, app version, contract version, socket path, OS user) + recent log (FR-074) |  |  |  |
| **No telemetry** — network trace during bundle action shows 0 outbound packets (FR-074/SC-009) |  |  |  |
| **Attach the generated diagnostics bundle to the T153 record** for this OS |  |  |  |

---

## 5. Packaging & trust checks (release-gate; per T148 + T178)

> **Two distinct Linux bars — do not conflate them:**
> - **Bench `.deb` smoke** (achievable in flutter-bench, *not* the release gate):
>   `cd apps/control_panel && FLUTTER=flutter327 bash tools/package_linux.sh`
>   produces a `.deb`; install it and smoke-launch under `xvfb-run`. GTK/ATK
>   warnings under Xvfb are expected and do not by themselves count as a FAIL.
>   This proves the bundle builds + installs + launches headless — it is **not**
>   sufficient to mark the Linux column PASS.
> - **Full Linux release gate** (required to PASS the Linux column): the signed
>   **`.AppImage`** built with `appimagetool`, installed and launched on a real
>   (non-Xvfb) Linux desktop, with the §5 bundle-id + trust-statement checks.
>   The bench cannot do this (`appimagetool` absent), so the Linux release-gate
>   row is **operator-verified on real hardware**, like macOS/Windows signing.

| Check | Win | macOS | Linux |
|---|---|---|---|
| Installs from the **signed** installer cleanly | |  |  |
| OS trust prompt shows **Opensoft** as publisher (not a generic/placeholder) — Gatekeeper (macOS) / SmartScreen (Win) | |  | N/A |
| **Bundle id is `one.opensoft.agenttower.control_panel`** — NOT `com.example.*` (T178) | |  |  |
| In-app version (Dashboard + Settings) matches the installer version (FR-068) | |  |  |
| FR-061 local-only trust statement appears on first launch + in Settings | |  |  |
| Linux only: `dpkg-deb -I <deb>` shows `Package`/`Depends`/maintainer with no `com.example` substring | N/A | N/A |  |

> Bundle-id verification (per OS): Win → `windows/runner/Runner.rc` +
> `AppxManifest`; macOS → `PRODUCT_BUNDLE_IDENTIFIER`; Linux → `APPLICATION_ID`
> in `linux/CMakeLists.txt` and the installed `.desktop` file.

---

## 6. Results matrix (fill per OS)

| OS | Steps 1–7 | §5 packaging/trust | Overall | Tester / date | Diagnostics bundle attached |
|---|---|---|---|---|---|
| Windows | __ / 7 PASS | PASS / FAIL | PASS / FAIL | | [ ] |
| macOS | __ / 7 PASS | PASS / FAIL | PASS / FAIL | | [ ] |
| Linux | __ / 7 PASS | PASS / FAIL | PASS / FAIL | | [ ] |

**Deviations / known-omissions accepted** (e.g. "4 dashboard tiles omitted at
contract 1.0 — expected, tracked by #34"):

- 2026-06-02: Linux **automated/headless** evidence captured (see §9) — daemon
  status + config doctor + scans + Flutter integration smoke + installed-`.deb`
  native-window launch all pass. Linux row stays **not PASS** pending the human
  visual sign-off (Steps 1–7) + signed `.AppImage` on a real desktop.
- …

---

## 7. Recording the outcome

When all three OSes are PASS (or every FAIL has a filed bug + an accepted
deviation note):

1. Save this filled runbook (commit it, or attach to the T153 tracking issue if
   one exists).
2. Attach the three diagnostics bundles (one per OS).
3. Mark **T153 `[X]`** in `specs/012-flutter-control-panel/tasks.md` and update the
   spec.md status line (operator-validation item closed).
4. If any FAIL surfaced a real defect, file it and link it here before sign-off.

> If you ran a partial pass (e.g. Linux only), record which OSes are done and
> leave T153 open until all three are covered — the gate is **all three OSes**.

---

## 8. Tooling note — how to drive each OS

- **Linux (flutter-bench):** use **`xvfb-run` + native window inspection inside
  flutter-bench** — run the integration smoke under `xvfb-run`, build/install
  the `.deb`, launch it under Xvfb and inspect the native GTK window (title,
  process liveness, stderr). This is the right tool for the headless Linux bench.
- **Windows:** Computer Use is appropriate for Windows desktop apps (real
  Win10/11 desktop, SmartScreen, native window UX).
- **macOS:** a real macOS desktop session (Gatekeeper, notarization, visual UX).
- Do **not** use Computer Use for the Linux lane — it targets Windows desktop
  apps; the Xvfb + native-window-inspection path above is the bench-correct tool.

---

## 9. Validation evidence log (append-only; partial runs welcome)

Record every partial or full run here with a date. Partial runs improve the
T153 evidence trail but do **not** flip the §6 matrix to PASS — that still needs
the full signed installer + human visual sign-off per OS.

### 2026-06-02 — Linux flutter-bench partial (automated/headless; NOT a visual sign-off)

Tooling: `xvfb-run` + native window inspection inside flutter-bench (per §8).
Daemon left running afterward for follow-up testing.

| Check | Result |
|---|---|
| Daemon preflight / `agenttower status` | ✅ alive on the shared AgentTower socket |
| `agenttower config doctor` | ✅ passed (only expected `not_in_tmux` **info** checks) |
| `agenttower scan --containers` | ✅ passed |
| `agenttower scan --panes` | ⚠️ `ok: true` but **degraded** — stale tmux sockets left by prior smoke sessions (environment artifact, not an app defect; see §2c cleanup) |
| Flutter Linux integration smoke (`integration_test/us1_smoke_walk.dart`, `-d linux` under Xvfb) | ✅ passed |
| Installed `.deb` launch smoke | ✅ real native window titled **"AgentTower Control Panel"**; process stayed alive; only GTK/ATK warnings on stderr |
| `dpkg-deb` bundle-id / package metadata | ✅ `agenttower-control-panel` 0.1.0, id `one.opensoft.agenttower.control_panel`, no `com.example` |

**Still outstanding (T153 remains OPEN):**
- Linux **human visual UX** sign-off (Steps 1–7 ticked by a person on a real
  desktop) and the **signed `.AppImage`** release-gate row (§5).
- **Windows** and **macOS** entirely — signed installers + trust prompts +
  visual UX on their proper desktop environments.
