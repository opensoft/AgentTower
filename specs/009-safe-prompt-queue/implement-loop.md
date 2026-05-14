# FEAT-009 Implementation Loop Driver

**Purpose**: Self-contained prompt for `/loop` to continue FEAT-009 implementation one cohesive slice at a time. Each iteration picks up where the previous one left off, lands a clean commit, and stops. Do NOT chain slices in a single iteration — one slice per loop tick.

**How to invoke**:

```text
/loop $(cat specs/009-safe-prompt-queue/implement-loop.md)
```

(Or paste the contents inline if the shell substitution isn't available in your harness.)

---

## Standing context (every iteration)

- **Repo**: `/workspace/projects/AgentTower-worktrees/009-safe-prompt-queue`
- **Branch**: `009-safe-prompt-queue` (verify with `git rev-parse --abbrev-ref HEAD` before any work).
- **Python**: 3.12 available as `python3`; tests run via `PYTHONPATH=src pytest tests/unit -q`.
- **Authority artifacts** (read these in this order):
  1. `specs/009-safe-prompt-queue/spec.md` — FRs + Clarifications + Assumptions (closed sets, exit codes, contracts).
  2. `specs/009-safe-prompt-queue/plan.md` — Project Structure, Implementation Notes, Defaults, Delivery worker loop pseudocode.
  3. `specs/009-safe-prompt-queue/data-model.md` — SQLite schema, state machine, column mapping for FR-046 dual-write.
  4. `specs/009-safe-prompt-queue/contracts/` — socket / CLI / JSON Schema / error codes.
  5. `specs/009-safe-prompt-queue/research.md` — R-001..R-012 decisions (e.g., R-002 BLOB affinity, R-004 sentinel, R-005 host-origin, R-007 AST gate, R-012 boot ordering).
  6. `specs/009-safe-prompt-queue/tasks.md` — **the authoritative task list with `[X]` / `[ ]` status**.
- **Locked decisions** (don't re-litigate):
  - Single delivery worker (Q5); abort-on-shutdown (Group-A Q4).
  - SQLite dual-write to `events` table + JSONL (FR-046 + Group-A Q1).
  - Bounded retry on `BEGIN IMMEDIATE` lock conflict; persistent → `failure_reason='sqlite_lock_conflict'` (Group-A Q5/Q7).
  - Redactor failure → fixed placeholder `"[excerpt unavailable: redactor failed]"` (Group-A Q3).
  - `agent_not_found` for `--target` lookup; `message_id_not_found` for `queue approve/delay/cancel` row-id lookup (Clarifications session 2 Q5).
  - Operator-pane liveness check (Group-A Q8) → `operator_pane_inactive`.
  - Host-only routing toggle via `(caller_pane is None AND peer_uid == os.getuid())` (Clarifications session 2 Q2 + R-005).
  - `host-operator` sentinel for host-originated audits; `(daemon-init)` sentinel for the migration-time seed row.

## Per-iteration workflow

1. **Sanity gates** (abort on failure):
   - `pwd` is the worktree path above; `git rev-parse --abbrev-ref HEAD` is `009-safe-prompt-queue`.
   - Working tree is clean (`git status --short` is empty). If not clean, STOP and ask the user — do not commit dirty unrelated state.
   - `PYTHONPATH=src pytest tests/unit -q` is green on the current HEAD. If it isn't, STOP and report — the prior iteration left a regression that must be fixed first.

2. **Identify the next slice**:
   - Open `specs/009-safe-prompt-queue/tasks.md`.
   - Find the first task whose checkbox is `[ ]` (in document order).
   - Identify the smallest cohesive slice that ends at a natural commit boundary (see the Slice Plan below for the canonical grouping).
   - The slice is **one chunk** — 5 to 15 tasks. Do not exceed.
   - If the next slice would conflict with the Slice Plan (e.g., depends on an unfinished slice), STOP and report.

3. **Implement the slice**:
   - For each task in the slice:
     - Read the task description; cross-reference plan/data-model/contracts/research as needed.
     - Implement the code or test exactly per the task description, the locked decisions above, and the FR / contract / data-model spec.
     - Prefer Edit over Write for existing files; use Write only for new files.
     - Match the existing FEAT-001..008 style (FEAT-008's modules are the freshest reference — see `src/agenttower/events/` for module shape, docstring style, type annotations).
     - Follow the constitution: no third-party runtime dependency added; stdlib only; bytes-typed body throughout; no shell-string interpolation.
   - **Tests-along-with-impl rule**: each implementation task's companion test task ([P]-marked sibling in tasks.md) lands in the same slice when feasible. Unit tests run after each module — keep the test green throughout the slice.

4. **Verification gates** (every slice MUST pass before commit):
   - `PYTHONPATH=src pytest tests/unit -q` — full unit suite green. Time budget ≤ 2 minutes.
   - `python3 -c "import agenttower"` doesn't crash on import (caught by tests, but verify if anything imports new modules).
   - **Regression budget**: zero unit-test failures introduced by the slice. If a FEAT-001..008 test breaks because of a spec-aligned change (e.g., a schema version bump), update it in the same slice with a one-line note explaining the alignment.
   - If you can't get green within the slice's scope, STOP and report — do not push a broken slice.

5. **Mark + commit**:
   - In `specs/009-safe-prompt-queue/tasks.md`, change each completed task's `- [ ] T<NNN>` to `- [X] T<NNN>` (preserve every other character including the `[P]` / `[USx]` markers).
   - `git add -A` (include source code, tests, and the tasks.md mark-off).
   - `git commit` with a structured message in this shape (FEAT-008 / prior slice commits are the style reference):

     ```text
     FEAT-009 Slice <N>: <one-line summary>

     <2–4 paragraphs describing what landed, which tasks (T<NNN>...) were
     completed, which FRs are now satisfied, and any locked-decision
     references (Group-A Q<n>, Clarifications Q<n>, research §R-NNN).>

     Tests: <pytest result summary, e.g., "1532 unit tests pass; 0
     regressions; +33 new tests this slice">.

     Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
     ```

6. **STOP** — do not start the next slice in the same iteration. Print a one-paragraph status block to the user covering:
   - Tasks completed this slice (IDs).
   - Total `[X]` / total `[ ]` count.
   - Next slice's first task ID.
   - Any blockers, surprises, or new decisions surfaced.

## When to break out of the loop

STOP the loop (do not continue scheduling iterations) when ANY of these is true:

- All tasks in `tasks.md` are marked `[X]`.
- A blocking decision surfaces that wasn't anticipated by the spec / plan / Group-A walk — e.g., a contract gap that requires user judgment.
- The unit test suite fails on `main` (or HEAD) in a way the slice can't resolve.
- An external dependency or environment assumption breaks (e.g., `pytest` not found, `python3` < 3.11).
- The user has interrupted with explicit "stop" / "halt" / "no more".

In all stop cases, leave the working tree clean (commit or stash WIP) so a human can pick up.

## Slice Plan (canonical chunking)

This is the recommended grouping. Each row is one `/loop` iteration. The first column is the slice number; the second is the task range; the third is the slice's coherence rationale.

| Slice | Tasks | Coherence |
|------:|---|---|
| 1 | T001–T013 | Phase 1 Setup + schema migration v7 + migration test. **DONE in commit 2a4b34f.** |
| 2 | T014–T021 | Closed-set error codes + `HOST_OPERATOR_SENTINEL` reservation + timestamps module + errors module + excerpt pipeline + their tests. All pure modules — no DAO or worker yet. |
| 3 | T022–T027 | Envelope rendering + body validation + permissions matrix + `--target` resolver + their unit tests. Still pure / no I/O. |
| 4 | T028–T032 | `MessageQueueDao` + `DaemonStateDao` (with bounded SQLite-lock retry helper) + state-machine + kill-switch service + their tests. First SQLite-touching slice. |
| 5 | T033–T035 + T034a | `QueueAuditWriter` (FR-046 dual-write to `events` table + JSONL with degraded-buffer + non-OSError catch) + `events/dao.py` extension `insert_audit_event` + audit writer test. Touches FEAT-008. |
| 6 | T036–T041 | tmux adapter Protocol extension (4 new methods) + `SubprocessTmuxAdapter` impl + `FakeTmuxAdapter` extension + 4 method-level tests + AST gate test (`test_no_shell_string_interpolation.py`). |
| 7 | T042–T047 | `DeliveryWorker` (recovery pass + main loop + cleanup `finally` + abort-shutdown + SQLite retry integration) + 5 worker tests (ordering, recovery, kill-switch race, pre-paste re-check, failure modes). |
| 8 | T048–T054 | `QueueService` façade + daemon boot wiring (recovery synchronous before `worker.start()`) + socket method dispatchers (8 new) + caller-context tests + CLI scaffolding + config.toml `[routing]` section + conftest test seams + `agenttower status` integration. |
| 9 (US1) | T055–T060 | US1 MVP: master→slave end-to-end integration test + send-input service wiring + queue_message_delivered audit + CLI handler + CLI JSON / human tests. |
| 10 (US2) | T061–T065 | US2 permission gate refusals + host-side refusal + target resolver integration + audit `queue_message_blocked` emission. |
| 11 (US3) | T066–T071 | US3 operator overrides: queue list/approve/delay/cancel implementation + listing format test + operator audit. |
| 12 (US4) | T072–T077 | US4 kill switch: routing socket handlers + CLI subcommands + worker re-read of routing flag before stamp + routing_toggled audit. |
| 13 (US5) | T078–T081 | US5 shell-injection safety + multi-line body integration + AST-gate-still-passes verification + body invariant tests. |
| 14 (US6) | T082–T085 | US6 restart recovery: integration test driven by pre-populated SQLite half-stamped row (no production-code fault-injection seam needed). |
| 15 (Polish) | T086–T095 (incl. T094a) | Polish: disjointness test, backcompat, host/container parity, audit JSONL schema validation, degraded-audit integration, docs, lint/type, final test-suite green check. |

**Slice boundaries are advisory.** A loop iteration may shrink a slice if scope grows unexpectedly (e.g., DAO touches more existing FEAT-006 surface than anticipated) — but never grow a slice beyond the upper boundary listed, and never split a `[P]`-marked test from its impl-task partner across slices unless the test is genuinely independent.

## Anti-patterns (forbidden in any iteration)

- ❌ Skipping the regression test sweep "just for a small slice."
- ❌ Marking a task `[X]` whose implementation is partial or whose test isn't green.
- ❌ Committing without the `Co-Authored-By` trailer.
- ❌ Re-litigating locked decisions (Group-A items, Clarifications answers, research R-NNN). If a decision needs revisiting, STOP and surface it to the user.
- ❌ Adding a third-party runtime dependency (FEAT-009 stdlib-only per plan §"Primary Dependencies").
- ❌ Inventing a new closed-set error code without adding it to spec FR-049 + contracts/error-codes.md + data-model §8 in the same slice.
- ❌ Shell-string-interpolating the body anywhere — the AST gate (T041, lands in Slice 6) is the durable enforcement, but every slice must respect it.

## State carry-over between iterations

Each iteration is independent. The state is fully captured in:

- **git HEAD** — the prior slice's commit.
- **`tasks.md`** — `[X]` vs `[ ]` checkboxes.
- **Code on disk** — the actual implementation.

If a future iteration needs to know "what did Slice N do?", it reads the git log message and the `[X]`-flipped tasks. No out-of-band state.

---

## Quick-reference: where things live

| Surface | Path |
|---|---|
| Spec | `specs/009-safe-prompt-queue/spec.md` |
| Plan | `specs/009-safe-prompt-queue/plan.md` |
| Data model | `specs/009-safe-prompt-queue/data-model.md` |
| Research | `specs/009-safe-prompt-queue/research.md` |
| Tasks | `specs/009-safe-prompt-queue/tasks.md` |
| Quickstart | `specs/009-safe-prompt-queue/quickstart.md` |
| Contracts | `specs/009-safe-prompt-queue/contracts/` (socket, CLI, JSON schemas, error codes) |
| Source | `src/agenttower/routing/` (new) + `src/agenttower/tmux/` + `src/agenttower/state/schema.py` + `src/agenttower/cli.py` + `src/agenttower/socket_api/methods.py` + `src/agenttower/daemon.py` |
| Tests | `tests/unit/` + `tests/integration/` (existing helpers in `tests/integration/_daemon_helpers.py`) |
| FEAT-008 reference style | `src/agenttower/events/` modules + their `tests/unit/test_events_*.py` neighbors |

---

**Now execute one iteration per the workflow above. Report at the end and stop.**
