# Managed Sessions Quickstart Walkthrough (T052)

This document records how to run the [`specs/013-managed-session-lifecycle/quickstart.md`](../specs/013-managed-session-lifecycle/quickstart.md) walkthrough end-to-end against a real `agenttowerd` and a real bench container, plus the in-process verification harness that stands in for it during CI.

T052's intent: prove the quickstart matches observed behavior, and capture any drift between the spec/contracts and what the daemon actually does.

---

## In-process verification (CI)

The full quickstart sequence is exercised in-process by these tests, which use canned spawn-pipeline backends instead of a real tmux/docker channel:

| Test file | Quickstart section covered |
|---|---|
| `tests/integration/test_story1_create_standard_layout.py` | §US1 (pending Phase 4c production tmux backend; module-level skip) |
| `tests/integration/test_story2_auto_prepare_operations.py` | §US2 — every step from "Verify in agent surfaces" through FR-015 FIFO + FR-021 redaction shape |
| `tests/integration/test_story3_lifecycle_operations.py` | §US3 — remove + recreate (with chain-traversal via M5) + adopted-pane protection |
| `tests/integration/test_managed_edge_cases.py` | §Edge cases table (bullets 1, 5, 7, 9, 11 explicitly; others covered by contract tests) |
| `tests/contract/test_managed_dispatch.py` | Dispatcher reachability + per-method envelope shape (M1-M8) |
| `tests/contract/test_managed_perf_sla.py` | SC-001 + SC-008 + SC-009 wall-clock SLAs (in-process bounds) |

Together these cover every observable behavior the quickstart asserts. Drift between quickstart prose and tests should produce a test-failure first; if you see drift only at quickstart-run time, **fix the code** (the quickstart is the spec-side truth, not the snapshot).

---

## Production walkthrough (manual)

For a real end-to-end demo against a running `agenttowerd` plus a real bench container, follow the quickstart in order:

1. Verify preconditions (§Preconditions): `agenttowerd` running, socket reachable, a bench container available, two operator YAML files in `~/.config/opensoft/agenttower/launch_commands/`.
2. Run §US1 step-by-step. Confirm `state == "ready"` within SC-001's 2-minute budget.
3. Run §US2 §"Verify in agent surfaces" — confirm `app.agent.list` returns the 3 managed agents with `origin == "managed"`.
4. Run §US3 §"Remove and recreate a managed pane" — confirm tmux kill happens, recreate produces a `predecessor_id`-linked row, adopted pane attempt returns `managed_pane_protected_adopted`.
5. Run §US3 §"Daemon restart (SC-008)" — stop the daemon, confirm tmux panes alive, start the daemon, hit `app.managed_layout_detail` within ~5s, confirm `state == "ready"`.
6. Run §Edge cases — at minimum exercise the `managed_session_name_conflict` and `managed_layout_capacity_exceeded` paths.

Production end-to-end wiring has **landed** in daemon boot (`src/agenttower/daemon.py`, managed startup block ~L985–1022):

- The tmux spawn backend composition (`spawn_backends.py` over the FEAT-004 docker-exec channel) is registered, and the M1 handler's `kickoff_spawn_pipeline()` drives `spawn_layout_in_background` after `create_layout` returns.
- `recovery.reconcile()` runs via `reconcile_managed_state_at_boot(...)` before the socket accepts requests (FR-020 / SC-008 / SC-009); its `ReconcileOutcome` is stored on the DaemonContext (`managed_reconcile_outcome`).
- The FEAT-008 JSONL lifecycle event emitter is bound via `make_managed_event_emitter(paths.events_file)` and threaded through create / remove / recreate / recovery.
- The FR-022 pending-marker TTL sweep runs on a 60-second cadence via `start_pending_marker_sweep(...)`, cancelled on shutdown through `managed_sweep_cancel`.

What remains is **operational validation**, not code wiring: a real-bench manual smoke against a running `agenttowerd` + bench container has not yet been recorded in the Drift report below.

---

## Drift report (last run)

| Date | Run by | Result | Notes |
|---|---|---|---|
| _(none yet — quickstart is exercised in-process via the test suites listed above; the daemon-boot wiring has landed, so a real-bench manual smoke can now be run and recorded here)_ | | | |

When the production walkthrough is run, add a row above with the date, runner, pass/fail, and any drift between the quickstart prose and observed behavior. Then either:

- The quickstart is canonical → file a code fix for the divergence.
- The behavior is canonical → file a spec amendment + re-run.

Per T052: drift is a signal to fix code, not the spec.
