# FEAT-012 Flutter Control Panel — Handoff to flutter-bench Claude

**Created:** 2026-06-14
**From:** review/analysis session (worktree `012-flutter-control-panel`)
**To:** the Claude running inside the **flutter-bench** container (the one with a
real Flutter toolchain + the `/workspace/projects` mount + a live `agenttowerd`)
**Branch:** `012-flutter-control-panel` (feature worktree; main branch is `main`)
**Goal of this handoff:** close out the **4 remaining open tasks** so a PR to
`main` can be opened cleanly. All code-review findings are already resolved —
what's left is one manual-validation gate (yours to drive on the bench) and three
upstream-blocked tasks (yours to confirm-and-defer, not implement here).

---

## 1. Where the feature stands

- **180 / 184 tasks done (98%).** No PR is open yet.
- **Every deep-review finding is closed and bench-verified.** Do **not** re-open
  the review backlog; it is complete. The 4 open tasks below are *not* review
  findings.
- Working tree at handoff time: one stray edit to
  `apps/control_panel/tools/package_windows.ps1` and a `.claude/dashboard.md.tmp`
  scratch file. Review/clean these before committing anything.

### What the deep reviews were (history, for context — all CLOSED)

| Review | Findings | Resolution |
|--------|----------|------------|
| **Swarm review 2026-05-24** (`specs/012-flutter-control-panel/swarm-review-2026-05-24.md`) — 12 specialist reviewers, 20 commits / ~27.6k LOC | 88 total: **10 CRIT / 24 HIGH / 22 MED / 18 LOW / 14 NIT** | Fixed via Batches 1–8 (`swarm-review-fix-plan.md`); commits `99bf95d`→`fc1127e` |
| **Swarm review 2026-06-01** (second deep pass over the source tree) | 1 CRITICAL daemon-transport bug + **16 HIGH / ~34 MED / ~41 LOW** across 39 files | `6032866` (transport one-request-per-connection), `4acd1c3` (39-file batch), `02c8e17` (H-G3 `json_utils` dedup) |
| **Codex spec-quality pass** (`codex-prompt-spec-quality-pass.md`) | 12 Tier-1 spec/data-model/testability gaps | Historical — closed via archived OpenSpec change `spec-quality-pass-feat-012` |
| **`/speckit-analyze` Rounds 2–15** | dozens of cross-artifact findings (drove tasks T172–T183) | Round 15 clean: 0 crit/high, 0 constitution violations, 3 doc nits fixed (`a13fe0d`) |

**Highest-signal CRITICALs that were fixed** (verify they're still green if you
touch nearby code): enum `@JsonValue` wire-format mismatch (CR-1, was throwing on
every multi-word-enum `fromJson`); broken integration-test harness
(`MockDaemonClient.stop` on a detached process, CR-2); `app_client._list`
splatting filters at top level instead of under `filters: {}` (CR-3); the
one-request-per-connection daemon transport bug (June wave); and the recurring
FR-067 i18n over-claim, finally closed all-`lib/` in T183.

**Takeaway for you:** the code is in good shape. Your job is validation + a clean
PR, not another remediation sprint.

---

## 2. The 4 open tasks and how to close each

### T153 — Cross-OS manual validation sign-off  ⭐ (the only one you can actually finish on the bench)

**Status:** 🟠 Linux has *partial automated/headless* evidence; no human visual
sign-off on any OS yet.

**Runbook (authoritative):**
`specs/012-flutter-control-panel/T153-manual-validation-runbook.md` — drive
Steps 1–7 (§4), the packaging/trust checks (§5), fill the §6 results matrix, and
append to the §9 evidence log.

**Already done on the Linux bench (2026-06-02, logged in §9):**
- `agenttower status` / `config doctor` (only expected `not_in_tmux` infos) /
  `scan --containers` pass.
- `scan --panes` returns `ok:true` but **degraded** by stale tmux sockets — an
  **environment artifact**, not an app defect (clean per §2c before re-scanning).
- `integration_test/us1_smoke_walk.dart` passes under Xvfb (`-d linux`).
- Installed `.deb` opens a real native window titled "AgentTower Control Panel"
  and stays alive (GTK/ATK warnings only); `dpkg-deb` metadata is id-clean
  (`one.opensoft.agenttower.control_panel`, no `com.example`).

**What still blocks T153 (do these on the bench):**
1. **Linux human visual UX sign-off** — a person ticks Steps 1–7 on a real
   desktop session (not headless Xvfb). This is the realistic next win.
2. **Signed `.AppImage`** release-gate row (§5). The bench lacks `appimagetool`
   on PATH — install it first; the `.deb` path does **not** need it.
3. **Windows + macOS entirely** — signed installers + OS trust prompts + visual
   UX on their native desktops. These likely need real Win/macOS hosts, not the
   Linux bench. If the bench can't reach those, record what you *can* and flag
   Win/macOS as the residual that gates final PR sign-off (or that the team
   accepts as a documented post-merge validation item — a product call).

**Linux build prerequisites (bench-confirmed; §2c) — set these before building:**
- `sudo apt-get install -y libnotify-dev` (Linux desktop build links
  `libnotify.so` via `local_notifier`; missing → link-time failure).
- If `apps/control_panel/build/linux` is root-owned from a prior Docker session:
  `sudo chown -R "$USER:$USER" apps/control_panel/build/linux` or
  `rm -rf apps/control_panel/build/linux`.
- Clear stale tmux sockets before `scan --panes` (`tmux kill-server` in the
  bench, or remove orphaned `/tmp/tmux-*`).
- Note: there is **no** `agenttower preflight` CLI on this branch — the app calls
  `app.preflight` over the socket internally; from the CLI use
  `agenttower status --json` + `agenttower config doctor --json`.

**Definition of done for T153:** §6 matrix filled per OS, §9 evidence appended,
and the task either checked off (full sign-off achieved) or its checkbox left
open with an explicit, dated note on exactly which OS/visual rows remain and who
owns them.

---

### T160b — Re-enable suppressed FR-012 dashboard tiles  🔴 upstream-blocked

**Do not implement the client edit yet — it is gated on an upstream merge.**

- Blocked on **FEAT-014 (`014-app-dashboard-extensions`)**, an additive
  app-contract **v1.1** minor. It is **fully implemented (27/27 tasks) but NOT
  yet merged to `main`** — `main` still emits only v1.0 `app.dashboard` fields.
- Tracked: **[opensoft/AgentTower#34](https://github.com/opensoft/AgentTower/issues/34)**.
- **Your action:** confirm FEAT-014 is still unmerged (`git log main` /
  `gh pr list`). If it has since merged and the daemon ships contract 1.1, you
  *can* land the small client edit now: in
  `apps/control_panel/lib/features/agent_ops/module.dart` bump
  `ContractRegistry.declare('agent_ops/dashboard', …)` from `ContractVersion(1,0)`
  → `(1,1)`; un-comment + wire the 4 TODO-marked tiles in
  `…/agent_ops/dashboard/dashboard_view.dart`; extend
  `Fixtures.dashboardResult` in `test/helpers/fixture_builders.dart`; update the
  mock-daemon README `app.dashboard` example. Otherwise leave it deferred.

---

### T166 — FR-072(a) drafted-row daemon persistence  🔴 upstream-blocked

- Needs a FEAT-011 v1.x **`app.handoff.draft`** method (write-through
  pre-submission persistence) so a submission-failure draft + `failureContext`
  survives widget tear-down server-side.
- Coordination vehicle: proposed **FEAT-015**; tracked
  **[opensoft/AgentTower#35](https://github.com/opensoft/AgentTower/issues/35)**.
  Seed text in `specs/012-flutter-control-panel/upstream-feat011-extension-draft.md` §b.
- **Your action:** none on this branch — confirm the issue is still open and
  leave deferred. Do not build a client-only workaround.

---

### T167 — FR-064 live-update streaming  🔴 upstream-blocked

- Needs a FEAT-011 v1.x **streaming subscription** (`app.events.subscribe`,
  SSE-style frames inside the existing Unix-socket framing) to replace the
  `ref.invalidate(...)` manual-refresh strategy and hit the FR-064 2 s budget.
- Coordination vehicle: proposed **FEAT-015**; tracked
  **[opensoft/AgentTower#36](https://github.com/opensoft/AgentTower/issues/36)**.
  Seed text in `upstream-feat011-extension-draft.md` §c.
- Note: the FR-058 OS-native notification dispatcher (T171) already ships a
  production **polling-diff** producer (1 s foreground / 5 s background) — that is
  the intended strategy *until* T167 lands, not a temporary hack. When streaming
  lands, only the producer swaps; the consumer + dispatcher are unchanged.
- **Your action:** none on this branch — confirm the issue is still open and
  leave deferred.

---

## 3. Pre-PR cleanup checklist

Before opening the PR to `main`:

1. **Clean the working tree.** Review the `package_windows.ps1` edit — keep it if
   intentional (it's part of the Windows packaging path T148/T178), revert if it
   was scratch. Remove `.claude/dashboard.md.tmp`. Confirm `.claude/` scratch
   isn't being committed (prior commit `02e94ed` untracked session scratch —
   keep it that way).
2. **Green gates** (run in the bench, per the runbook §verification cadence):
   - `flutter analyze` → 0 errors / 0 new warnings on touched files.
   - `dart run build_runner build --delete-conflicting-outputs` if any
     model/codegen changed.
   - `flutter test test/features` — note the **known** pre-existing baseline:
     the `test/ui` `alert(1)` raw-HTML markdown test is a pre-existing failure
     (stash-proven `+0 -1`), unrelated to FEAT-012. Don't let it block the PR,
     but call it out in the PR body.
   - `integration_test/us1_smoke_walk.dart` under Xvfb passes.
3. **Decide the T153 disposition** (see its DoD above) — the PR body must state
   plainly which OS visual sign-offs are complete vs. deferred, so reviewers
   aren't misled into thinking cross-OS validation is finished when only Linux
   automated evidence exists.
4. **Confirm the 3 upstream deferrals** (#34/#35/#36) are still open and
   accurately described in `tasks.md` lines ~490–496; the PR body should link
   them as the reason T160b/T166/T167 ship deferred rather than done.

## 4. Suggested PR framing

- **Title:** `FEAT-012: Flutter control panel (Phases 3–9) — review-clean, cross-OS validation in progress`
- **Body must include:**
  - "All deep-review findings (2× swarm + Codex + 15 analyze rounds) resolved."
  - The T153 matrix state (Linux automated ✅, Linux visual / Win / macOS = the
    explicit residual).
  - The 3 upstream-blocked tasks with issue links and why they're deferred (not
    incomplete work — they need daemon-side features that don't exist on `main`).
  - The one known unrelated pre-existing test failure (`alert(1)` markdown).
- End the PR body with the standard Claude Code attribution line.

---

## 5. Pointers

- Plan / tech context: `specs/012-flutter-control-panel/plan.md`
- Tasks (source of truth, statuses + the upstream-issue table): `specs/012-flutter-control-panel/tasks.md`
- Spec + FRs: `specs/012-flutter-control-panel/spec.md`
- Review docs: `swarm-review-2026-05-24.md`, `swarm-review-fix-plan.md`, `codex-prompt-spec-quality-pass.md`
- Validation runbook: `T153-manual-validation-runbook.md`
- Upstream coordination seed: `upstream-feat011-extension-draft.md`
- App-contract client guide: `docs/app-contract-client-guide.md`

**One-line summary for the next Claude:** code is review-clean and 180/184 done;
the only task you can finish here is **T153** (Linux visual sign-off + signed
`.AppImage`, then Win/macOS); T160b/T166/T167 stay deferred behind upstream
issues #34/#35/#36; clean the tree, run the green gates, then open the PR with an
honest cross-OS validation status.
