# Tier-1 Plan-Side Fix Instructions

**Date**: 2026-05-23
**Source findings**: Round-2 checklist walk (`/speckit-checklist` re-verification pass) — see [alignment.md](./checklists/alignment.md), [quickstart-quality.md](./checklists/quickstart-quality.md).
**Scope**: Three Tier-1 findings (F-A1, F-A2, F-A11).
**Posture**: **All three are plan-side artifact edits, NOT spec changes.** No OpenSpec proposal is required. Edit the named files directly in the `012-flutter-control-panel` branch, then `git add` + `git commit` normally.

> If you discover during these edits that a fix actually *requires* changing `spec.md` (e.g. you decide to flip the F-A1 convention the other way), STOP and create an OpenSpec change proposal first via `/opsx:propose` (target: spec-quality-pass-feat-012 v2 or similar). Do NOT edit spec.md ad-hoc.

---

## F-A1. Normalize state-value vocabulary (hyphens vs underscores)

### What's wrong

`spec.md` writes pane states with hyphens (`discovered-and-unmanaged`, `discovered-and-registered`, etc.) but `data-model.md` and `quickstart.md` write them with underscores (`discovered_and_unmanaged`, etc.). A grep across artifacts won't find a state name in all locations. An implementer or auditor cannot trace the same state across spec ↔ data-model ↔ quickstart.

**Empirical evidence**:

```text
spec.md:       3 hyphenated, 0 underscored
data-model.md: 0 hyphenated, 3 underscored
quickstart.md: 0 hyphenated, 4 underscored
```

### Direction of fix

**Keep spec.md unchanged (hyphenated convention authoritative).** Update data-model.md and quickstart.md to use hyphenated values in prose, AND keep underscore variants only inside Dart code blocks (where snake_case is the Dart convention for enum variants).

Rationale: spec.md is the source of truth and was written first; the two plan-side artifacts drifted from it. The Dart convention for enum variants is snake_case, so the underscore form is fine inside Dart code blocks — but prose references should match the spec.

### Files to edit

#### 1. `specs/012-flutter-control-panel/data-model.md`

Find the Pane state enum and the prose that references pane states. The state names appear in §1.4 (Pane entity) and possibly elsewhere.

Change (in **prose only**, not in the Dart `enum PaneState { … }` declaration):

```text
discovered_and_unmanaged    →   discovered-and-unmanaged
discovered_and_registered   →   discovered-and-registered
inactive_or_stale           →   inactive/stale          (spec uses "inactive/stale")
discovery_degraded          →   discovery-degraded
```

Inside any Dart code block (e.g. `enum PaneState { ... }` or the `state: PaneState` field), KEEP the underscore form — it's the Dart convention.

The "Allowed transitions" sentence in §1.4 currently reads (paraphrased):

> Allowed transitions: `discovered_and_unmanaged ↔ discovered_and_registered` (adoption / de-adoption); any state may transition to `inactive_or_stale` on pane disappearance ...

Replace with:

> Allowed transitions: `discovered-and-unmanaged ↔ discovered-and-registered` (adoption / de-adoption); any state may transition to `inactive/stale` on pane disappearance and may return to its prior state on rediscovery; any state may transition to `discovery-degraded` on probe failure and back on recovery. There are no terminal pane states.

(The Dart enum variant identifiers stay as `discoveredAndUnmanaged` / `discoveredAndRegistered` / `inactiveOrStale` / `discoveryDegraded` per Dart camelCase convention; those are different from both the spec hyphens and the JSON-shaped underscores.)

#### 2. `specs/012-flutter-control-panel/quickstart.md`

Quickstart references pane states in prose 4× (Step 1 acceptance check, Step 2 acceptance check, and the failure-modes table). Replace every underscore-form pane state with the hyphenated spec form. Specifically grep for `discovered_and_unmanaged` and `discovered_and_registered` and replace.

The state names referenced in quickstart should match spec.md FR-014 exactly: `discovered-and-unmanaged`, `discovered-and-registered`, `inactive/stale`, `discovery-degraded`.

### Verification

After both edits:

```bash
cd /workspace/projects/AgentTower-worktrees/012-flutter-control-panel

# Should now find hyphen form in all 3 files (matching spec)
grep -c "discovered-and-unmanaged" specs/012-flutter-control-panel/{spec,data-model,quickstart}.md
# Expect: spec.md ≥1, data-model.md ≥1, quickstart.md ≥1

# Should find underscore form ONLY in code blocks of data-model.md (none in quickstart.md prose)
grep -c "discovered_and_unmanaged" specs/012-flutter-control-panel/{spec,data-model,quickstart}.md
# Expect: spec.md 0, data-model.md may have some (in code blocks), quickstart.md 0
```

### Optional broader sweep

Other enum vocabularies might have the same issue. Spot-check by grepping for hyphenated vs underscored forms of:

- Pane states (above) — confirmed
- Drift sources: `static_check`, `agent_review`, `operator_report`, `test_result` — spec uses underscores; data-model uses underscores; probably consistent.
- Validation entrypoint types: `unit_test`, `integration_test`, `contract_test`, `smoke`, `e2e`, `demo_flow`, `doctor` — spec uses underscores; data-model uses underscores; probably consistent.
- Queue states: `queued`, `blocked`, `delivered`, `canceled`, `failed` — single words, no inconsistency possible.

If the spot-check finds more discrepancies, fix them with the same direction: prose follows spec, code blocks use Dart camelCase.

---

## F-A2. Add 7 missing Success Criteria to plan.md Performance Goals

### What's wrong

`plan.md` Performance Goals section cites only some of the spec's measurable SCs. **7 SCs are missing**: SC-002, SC-003, SC-004, SC-008, SC-008a, SC-011, SC-012.

(SC-001/005/006/007/010/013 are already cited. SC-009 is cited in the Constraints section for security posture, not as a performance budget.)

### Empirical evidence

```text
$ for sc in SC-001 SC-002 SC-003 SC-004 SC-005 SC-006 SC-007 SC-008 SC-008a SC-009 SC-010 SC-011 SC-012 SC-013; do
    echo "$sc: $(grep -c "$sc" specs/012-flutter-control-panel/plan.md)"
  done
SC-001: 2     ✓ cited
SC-002: 0     ✗ missing
SC-003: 0     ✗ missing
SC-004: 0     ✗ missing
SC-005: 1     ✓ cited
SC-006: 1     ✓ cited
SC-007: 1     ✓ cited
SC-008: 0     ✗ missing
SC-008a: 0    ✗ missing
SC-009: 3     ✓ cited (in Constraints, not Performance Goals)
SC-010: 1     ✓ cited
SC-011: 0     ✗ missing
SC-012: 0     ✗ missing
SC-013: 1     ✓ cited
```

### File to edit

`specs/012-flutter-control-panel/plan.md`

### Location

Inside the `**Performance Goals**` block under `## Technical Context`. Add 7 new bullet lines.

### What to add

Append the following 7 bullets at the end of the existing Performance Goals list (preserving the existing 10 bullets that are already there):

```text
- Operator can identify active driving master + current feature/change phase from card-level info alone (no drill-down): ≤ 5 s per project (SC-002).
- Generating a single-feature handoff with auto-filled context completes in ≤ 30 s from "open handoff flow" to "submitted"; Project Context section names repository, PRD, architecture, roadmap, and selected feature spec paths with no operator typing of paths (SC-003).
- For a feature range with at least one deferred and one merged intermediate item, the resolved work-item list shown in preview MUST exactly match the list embedded in the submitted prompt and explicitly call out excluded items (SC-004).
- Across ≥5 distinct daemon-side event classes producing attention-queue items, operator can correctly classify and navigate to the resolution surface for each class within 10 s using only the queue's icon + color treatment (SC-008).
- While the operator hovers over the attention queue, no item under the pointer changes position for ≥ 2 s (the FR-053 interaction-stability window), measured by automated UI interaction tests across 100 simulated live-update bursts (SC-008a).
- Onboarding's step completion rate (steps presented → steps completed) is ≥ 90% across the eight FR-010 milestones, measured across an internal Opensoft operator cohort (SC-011).
- ≥ 90% of new operators report on a post-onboarding survey that they could identify which agent is driving which feature for their primary project from card-level information alone (SC-012).
```

### Verification

```bash
# All 14 SCs should now appear at least once in plan.md
for sc in SC-001 SC-002 SC-003 SC-004 SC-005 SC-006 SC-007 SC-008 SC-008a SC-009 SC-010 SC-011 SC-012 SC-013; do
  c=$(grep -c "$sc" specs/012-flutter-control-panel/plan.md)
  printf "%-8s %d\n" "$sc" "$c"
done
# Expect: every SC ≥ 1
```

---

## F-A11. Add Windows-equivalent verification commands to quickstart.md

### What's wrong

`quickstart.md` Step 6 (Daemon-outage handling) uses `pkill -f agenttowerd` to stop the daemon — Unix-only. Windows operators have no equivalent command in the same flow. The "Prerequisites — Verification commands" section also assumes a Unix shell environment (`docker exec -u "$USER"` works on Windows under WSL but not in native PowerShell).

### File to edit

`specs/012-flutter-control-panel/quickstart.md`

### Locations + changes

#### Change 1 — Step 6 outage trigger

Find the block:

```text
1. In a separate terminal, stop `agenttowerd`:
   ```bash
   pkill -f agenttowerd      # Linux/macOS
   ```
```

Replace with:

```text
1. In a separate terminal, stop `agenttowerd`:
   ```bash
   pkill -f agenttowerd      # Linux/macOS
   ```
   On Windows (PowerShell):
   ```powershell
   Stop-Process -Name agenttowerd -Force
   ```
   Or use Task Manager → find `agenttowerd.exe` → End Task.
```

#### Change 2 — Step 6 daemon restart

Find the block:

```text
3. Restart the daemon:
   ```bash
   agenttowerd &
   ```
```

Replace with:

```text
3. Restart the daemon:
   ```bash
   agenttowerd &            # Linux/macOS
   ```
   On Windows (PowerShell):
   ```powershell
   Start-Process agenttowerd
   ```
```

#### Change 3 — Prerequisites verification commands

Find the block:

```text
# Confirm at least one bench container
docker ps --filter "name=bench" --format "table {{.Names}}\t{{.Status}}"

# Confirm at least one tmux pane in the bench container
docker exec -u "$USER" <bench-container> tmux list-panes
```

Add a Windows note above this block (or as an inline annotation):

```text
> **Windows note**: the `docker exec -u "$USER" …` command works under WSL2 (where `$USER` resolves) but in native PowerShell, replace `$USER` with the explicit Windows username matching the bench-container's expected UID, or run the docker commands from inside WSL2.
```

### Verification

```bash
# Quickstart should now mention PowerShell or Windows commands at least twice
grep -c -i "powershell\|windows" specs/012-flutter-control-panel/quickstart.md
# Expect: ≥ 3 (one for each of the three locations above; the existing FEAT-011 Windows AF_UNIX mention may also match)
```

---

## After all three fixes

### Verify nothing else changed

```bash
git status --short
# Expect: only 3 files modified —
#   M specs/012-flutter-control-panel/plan.md
#   M specs/012-flutter-control-panel/data-model.md
#   M specs/012-flutter-control-panel/quickstart.md
```

### Re-run the verification greps from above

```bash
# F-A1 verification
grep -c "discovered-and-unmanaged" specs/012-flutter-control-panel/{spec,data-model,quickstart}.md

# F-A2 verification (every SC ≥ 1)
for sc in SC-001 SC-002 SC-003 SC-004 SC-005 SC-006 SC-007 SC-008 SC-008a SC-009 SC-010 SC-011 SC-012 SC-013; do
  printf "%-8s %d\n" "$sc" "$(grep -c "$sc" specs/012-flutter-control-panel/plan.md)"
done

# F-A11 verification
grep -c -i "powershell\|windows" specs/012-flutter-control-panel/quickstart.md
```

### Commit

```bash
git add specs/012-flutter-control-panel/{plan,data-model,quickstart}.md
git commit -m "fix(feat-012): plan-side Tier-1 alignment (F-A1/F-A2/F-A11)

- F-A1: normalize pane-state vocabulary to hyphenated form in data-model.md
  and quickstart.md prose (matches spec.md FR-014 convention; Dart enum
  variants kept as snake_case in code blocks per Dart convention)
- F-A2: add 7 missing Success Criteria (SC-002, SC-003, SC-004, SC-008,
  SC-008a, SC-011, SC-012) to plan.md Performance Goals
- F-A11: add Windows (PowerShell) equivalents to quickstart.md Step 6
  outage commands and prerequisite verification commands"
```

### After the commit

- These fixes do NOT require an OpenSpec change because no spec text was modified.
- They DO unblock /speckit-tasks: the plan-side artifacts are now alignment-clean enough that tasks.md generation will not carry the divergences forward.
- The Tier-2 (F-A3 through F-A11 minus F-A1/F-A2) and Tier-3 findings from the Round-2 walk remain open; they're non-blocking and can be addressed during /speckit-tasks or as plan polish.
