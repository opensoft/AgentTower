# Quickstart — FEAT-012 Flutter Desktop Control Panel

**Audience**: Implementation engineers and integration testers building or validating FEAT-012.
**Mirrors**: User Story 1 (P1) — "Adopt and operate existing agent panes from the desktop". Establishes the minimum viable end-to-end slice the app must deliver.
**Date**: 2026-05-23
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Data model**: [data-model.md](./data-model.md) | **Contracts**: [contracts/](./contracts/)

This quickstart walks the US1 acceptance scenarios end-to-end against a running `agenttowerd` and a single live tmux pane in a bench container. By the end, the operator has gone from "discovered but unmanaged pane" to "registered agent with attached log, observable events, a successful direct send, and at least one active route" — all without ever opening a terminal or invoking the `agenttower` CLI.

## Prerequisites

### Host environment

- A POSIX or Windows workstation with Docker Engine running and one or more bench containers active.
- `agenttowerd` installed, running, and reachable at the OS-default socket path (`/run/user/$UID/agenttower/agenttowerd.sock` on Linux/macOS; equivalent AF_UNIX path on Windows 10 1803+).
- A bench container with at least one live tmux pane hosting an AI agent CLI (Claude, Codex, Gemini, or OpenCode).
- FEAT-001..FEAT-011 implemented and FEAT-011's `app_contract_version` major matching the desktop app's expected major.

### Desktop app

- A built/installed copy of the FEAT-012 desktop control panel for the current OS (see `apps/control_panel/README.md` for build instructions).
- First-launch onboarding has NOT been completed (or has been re-entered from Settings); otherwise skip to US1 §1 below.

### Verification commands (run before launching the app)

```bash
# Confirm daemon is reachable
agenttower preflight                   # FEAT-002 CLI preflight (sanity-only; the app calls app.preflight separately)

# Confirm at least one bench container
docker ps --filter "name=bench" --format "table {{.Names}}\t{{.Status}}"

# Confirm at least one tmux pane in the bench container
docker exec -u "$USER" <bench-container> tmux list-panes
```

> **Windows note**: the `docker exec -u "$USER" …` command works under WSL2 (where `$USER` resolves) but in native PowerShell, replace `$USER` with the explicit Windows username matching the bench-container's expected UID, or run the docker commands from inside WSL2.

If any of these fail, fix the prerequisite condition before continuing — the app's first-launch onboarding will surface the same checks via FR-009's doctor.

## Step 1 — Launch + bootstrap (US1 §1)

1. Launch the app from the OS launcher / Start menu / Spotlight.
2. The app window opens at the persisted geometry (or OS-default-centered on first launch). FR-062 budget: Dashboard becomes operationally readable within **2 seconds**.
3. **Expected first-launch behavior** (no prior `ux-state.json`):
   - Onboarding overlay appears at "Step 1: Daemon reachable" (FR-010).
   - The first milestone (`daemon_reachable`) completes automatically the moment `app.hello` returns success — no operator click needed (per F11 / FR-010's "automatically-detectable completion criterion").
4. **Expected subsequent-launch behavior** (existing `ux-state.json`):
   - Onboarding is skipped if all 8 milestones are already complete.
   - Otherwise, completed milestones stay complete; incomplete ones appear as Dashboard nudges (per Q24 / FR-010).
5. **Verify**:
   - Dashboard shows `daemon: Healthy` (FR-012).
   - Contract version is displayed (FR-002 / FR-009).
   - Container count, pane count by state, and registered-agent count are visible (FR-012).
   - Recommended next action is "Adopt a pane" (FR-012's runtime-healthy-empty / runtime-healthy-populated state).

### Acceptance check (US1 §1)

| Property | Source | Pass criterion |
|---|---|---|
| Daemon health visible | FR-012 | Dashboard renders `daemon: Healthy` |
| ≥1 container shown | FR-013 | Containers view non-empty |
| ≥1 pane in `discovered-and-unmanaged` state | FR-014 | Panes view non-empty with the four-state vocabulary |
| Obvious next action | FR-012 | Dashboard surfaces "Adopt a pane" prominently |
| Dashboard readable in ≤ 2 s | FR-062 | Stopwatch the launch-to-Dashboard delta |

## Step 2 — Adopt a pane (US1 §2)

1. Navigate to **Agent Operations → Panes** (or press `Ctrl/Cmd+P` to open the project switcher and confirm no project is required for this step).
2. Locate the pane in `discovered-and-unmanaged` state. Click **Adopt** on its row.
3. The Adopt form (FR-016) requires:
   - `label` — a human-readable name for the agent (e.g. `claude-master-1`).
   - `role` — `master`, `slave`, or `shell`. For US1 §5 (route creation), pick `master`.
   - `capability` — `claude`, `codex`, `gemini`, `opencode`, `shell`, etc. Must match the pane's discovered class.
   - `project_path` — the absolute path inside the container for the project the agent is operating on.
   - `attach_log_now` — boolean. For US1 §3 below, set to `true`.
4. Submit. The app calls `app.agent.register_from_pane` (per `contracts/app-methods-consumed.md` §4) and the FR-065 budget gives the daemon ≤ **5 seconds** to confirm.
5. **Verify** (US1 §2):
   - Pane transitions to `discovered-and-registered` in the Panes view.
   - A new agent appears in the Agents view (FR-015).
   - A log attachment appears in `active` state on the new agent (FR-017).
   - The app navigates to a view that confirms all four state changes (the Agent detail or Dashboard recent-activity tile).

### Acceptance check (US1 §2)

| Property | Source | Pass criterion |
|---|---|---|
| Pane state transitions | FR-014 | Row's badge flips from `discovered-and-unmanaged` to `discovered-and-registered` |
| Agent appears | FR-015 | Agents view contains a new row with the label/role/capability supplied |
| Log attachment active | FR-017 | Per-agent attachment badge reads `active` |
| Single round-trip ≤ 5 s | FR-065 | Stopwatch submit → confirmed-registered-agent state |
| Validation: role + pane class | FR-016 | Submitting an incompatible role/capability returns the daemon's validation error inline |

## Step 3 — Watch events flow (US1 §3)

1. From the new agent's detail surface, navigate to **Events** (or stay on the per-agent recent-activity panel).
2. In the bench container, run something in the adopted pane that produces classifiable output (e.g. paste a prompt into the Claude CLI and let it respond).
3. **Verify**:
   - Events appear in the Events view in `observed_at` order (FR-019).
   - The agent's "last meaningful activity" timestamp on its summary updates within FR-064's **2-second** live-update budget.
   - Each event row links back to its source agent.

### Acceptance check (US1 §3)

| Property | Source | Pass criterion |
|---|---|---|
| Events render in observed-at order | FR-019 | Newer rows appear above older rows by default |
| Live-update budget | FR-064 | Within 2 s of daemon-side classification, the event is visible in the view |
| Agent activity stamp updates | FR-030, FR-064 | Agent's "last meaningful activity" advances on each new event |

## Step 4 — Direct send (US1 §4)

1. From the agent's detail surface, click **Direct Send**.
2. Enter a non-empty payload (e.g. `Hello from the desktop app`).
3. Submit. The app calls `app.send_input` with the payload and an optional `idempotency_key` (per FEAT-011 FR-031a).
4. **Verify**:
   - The daemon's response renders inline (FR-018: success or daemon error displayed; no silent retry).
   - The agent's recent-activity tile shows the send.
   - Any resulting classified event appears in the Events view linked back to the send.

### Acceptance check (US1 §4)

| Property | Source | Pass criterion |
|---|---|---|
| Payload required | FR-018 | Empty payload submission is rejected client-side |
| Daemon response inline | FR-018 | Success ack or `validation_failed` / `permission_denied` etc. shown inline |
| No silent retry on failure | FR-018 | Failure path does NOT auto-retry; operator may retry manually |
| Send → event linkage | FR-019 | The resulting event row's "source" links back to the send |

## Step 5 — Route management (US1 §5)

1. Navigate to **Agent Operations → Routes**.
2. Click **Add route**. The form (FR-021) requires:
   - `source` — the adopted agent from Step 2 (the master).
   - `event_class` — choose an event class produced by the agent in Step 3.
   - `target` — a peer agent (adopt another pane via Step 2 if needed; or specify by id if one already exists).
   - `master_rule` — `default master rule` for US1 §5.
3. Submit. The app calls `app.route.add`.
4. **Verify**:
   - The route appears in Routes view with state `enabled, healthy` (FR-021).
   - A subsequent matching event causes a queue row to be created against the target.
   - Navigate to **Queue**; the new row appears in the `queued` state (FR-020 five-state vocabulary).

### Acceptance check (US1 §5)

| Property | Source | Pass criterion |
|---|---|---|
| Route added with required fields | FR-021 | Form refuses to submit with missing fields |
| Route surfaced as `enabled, healthy` | FR-021 | Routes view shows the new route in the healthy state |
| Matching event creates queue row | FR-020 | After triggering a matching event, Queue view shows a new row |

## Step 6 — Daemon-outage handling (US1 §6)

This step requires a deliberate failure to test resilience.

1. In a separate terminal, stop `agenttowerd`:
   ```bash
   pkill -f agenttowerd      # Linux/macOS
   ```
   On Windows (PowerShell):
   ```powershell
   Stop-Process -Name agenttowerd -Force
   ```
   Or use Task Manager → find `agenttowerd.exe` → End Task.
2. **Verify**:
   - The global health indicator switches to `Daemon unreachable` within FR-064's **2 seconds**.
   - Every view that depends on live data displays its FR-004 documented `runtime-unreachable` empty state (NOT a generic spinner or generic error).
   - The Dashboard offers a `Retry connection` affordance.
3. Restart the daemon:
   ```bash
   agenttowerd &            # Linux/macOS
   ```
   On Windows (PowerShell):
   ```powershell
   Start-Process agenttowerd
   ```
4. Click `Retry connection`. The app calls `app.hello` to re-bootstrap (FR-003).
5. **Verify**:
   - Within SC-010's **5 seconds**, all surfaces revert to live state.
   - No surface shows stale data labelled as live during the outage.

### Acceptance check (US1 §6)

| Property | Source | Pass criterion |
|---|---|---|
| Outage detected ≤ 2 s | SC-010 | Health indicator flips within 2 s of socket close |
| Per-surface unavailable state | FR-004 / Edge Cases | Each live-data view renders its documented `runtime-unreachable` placeholder |
| Recovery ≤ 5 s | SC-010 | After daemon return, live state restored within 5 s |
| No stale-as-live | SC-010 | During outage, no view shows pre-outage data labelled as current |

## Step 7 — Settings doctor (FR-009)

1. Navigate to **Settings**.
2. Click **Run doctor** (or invoke from the command palette via `Ctrl/Cmd+K → "Run doctor"` per FR-075 + R-20).
3. **Verify** the doctor runs the six FR-009-enumerated checks in parallel where independent and produces:
   - Per-check pass/fail badge.
   - Per-check latency in ms.
   - Per-check explanation on failure.
4. Confirm `Copy diagnostics bundle` produces a clipboard-or-file bundle that includes:
   - The doctor output verbatim.
   - The current app version (per FR-068).
   - The current `app_contract_version`.
   - The daemon socket path.
   - The active OS user.
   - The rotating log file's most recent contents.

### Acceptance check (FR-009 + FR-074)

| Property | Source | Pass criterion |
|---|---|---|
| Doctor enumerates all 6 checks | FR-009 | Output names all six (socket, peer UID, contract version, app-data writability, log writability + size, OS notification permission) |
| Diagnostics bundle complete | FR-074 | Bundle contains all five enumerated fields |
| No telemetry leaks | FR-074 / SC-009 | Network trace during the bundle action shows zero outbound packets |

## End of US1 quickstart

After Steps 1–7 the operator has exercised the entire P1 surface: adopt → register → log attach → events → direct send → route → outage handling → doctor + diagnostics. This is the **shippable slice** the spec calls out as the absolute minimum value of FEAT-012. Subsequent user stories (US2 Projects, US3 Handoff flow, US4 Drift, US5 Testing and Demo, US6 Attention queue + notifications) build on this same foundation and each has its own integration-test entry under `apps/control_panel/integration_test/` (per `plan.md` §Project Structure).

## Common failure modes & first-aid

| Symptom | Likely cause | Fix |
|---|---|---|
| Dashboard shows `runtime-unreachable` on launch | Daemon not running or wrong socket path | `agenttowerd` status; Settings → daemon socket path → Run doctor |
| Banner says `contract-version-incompatible` | Daemon's `app_contract_version` major differs from app's expected major | Upgrade app or daemon to match majors; FR-068 indicator helps surface the upgrade |
| Adopt fails with `validation_failed` | Role/capability incompatible with discovered pane class (FR-016) | Pick a role/capability that matches the pane (e.g. don't set `claude` capability on a shell pane) |
| Events view stuck at "no events" after Step 4 send | Daemon classifier subsystem degraded | Health view → check classifier subsystem; doctor will flag |
| `Copy diagnostics bundle` produces empty bundle | Rotating log directory not writable | Doctor check #4 will flag; usually permissions on `<app-data>/agenttower-control-panel/logs/` |
| Window appears off-screen on second launch | Persisted geometry references a now-disconnected monitor | Delete `<app-data>/agenttower-control-panel/ux-state.json` or use Settings → Reset persisted UX state |

## Next steps after this quickstart passes

- Run the per-US integration tests under `apps/control_panel/integration_test/` against the mock-daemon harness (no live daemon required).
- Walk US2..US6 quickstart-style: each user story has matching acceptance scenarios in `spec.md` that drive a similar checklist.
- Hand the spec to `/speckit-tasks` to generate the implementation task list (this is the recommended next Spec Kit command after planning).
