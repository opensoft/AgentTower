# Reliability & Durability Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the state machine, crash recovery, delivery-worker invariants, per-target FIFO, concurrency model, and shutdown lifecycle. Tests whether the durability requirements themselves are complete, deterministic, and operator-verifiable — NOT whether the implementation crashes.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Walked**: 2026-05-12
**Feature**: [spec.md](../spec.md)

## State Machine Invariants

- [X] CHK001 Five states only; CHECK constraint forbids any other value (FR-013 + data-model.md §2 CHECK).
- [X] CHK002 Closed transition list enumerated (FR-015 + data-model.md §3.1).
- [X] CHK003 Terminal states distinguished from non-terminal with enforceable invariant (FR-014 + data-model.md §3.2).
- [X] CHK004 Terminal-state mutation MUST exit non-zero with `terminal_state_cannot_change` (FR-014).
- [X] CHK005 `queued → blocked` re-check vs operator `delay` distinguished via `block_reason` (FR-025 + data-model.md §3.1).
- [X] CHK006 Operator vs worker triggers distinguished in data-model.md §3.1 "Trigger" column.

## Crash Recovery Requirements

- [X] CHK007 Recovery trigger precise: `delivery_attempt_started_at IS NOT NULL AND delivered_at IS NULL AND failed_at IS NULL AND canceled_at IS NULL` (FR-040 + data-model.md §2 partial index).
- [X] CHK008 Recovery completes BEFORE worker thread spawn (FR-040 + research §R-012 + T048 boot ordering).
- [X] CHK009 Recovery emits one audit entry per affected row, same format as non-recovery (US6 #2 + FR-046 + T084).
- [X] CHK010 Non-interrupted rows preserved byte-for-byte (FR-016 + US6 #3).
- [X] CHK011 `queued` rows with never-stamped `delivery_attempt_started_at` remain deliverable across clean restart (FR-012a + Clarifications Q1 of 2026-05-11).
- [X] CHK012 No second tmux paste (FR-040 + SC-004 + T044 call-count assertion).

## Delivery Worker Invariants

- [X] CHK013 `delivery_attempt_started_at` commits BEFORE any tmux call as a hard MUST (FR-041).
- [X] CHK014 Terminal stamp commits BEFORE next row pickup (FR-042).
- [X] CHK015 `failure_reason` closed set has no catch-all "other" value (FR-018 enumerates exactly 5; FR-043 maps tmux/docker errors).
- [X] CHK016 Delivery worker reads `envelope_body` from SQLite at the start of each attempt (FR-012a + Clarifications Q1).
- [X] CHK017 `docker exec` failure before any tmux command runs is handled by the FR-041 stamp-before-tmux invariant: the row already has `delivery_attempt_started_at` set when the adapter raises `TmuxError(failure_reason='docker_exec_failed')`, and is then transitioned to `failed` with that reason.

## Per-Target FIFO

- [X] CHK018 Per-target FIFO measurable invariant: at most one row with `delivery_attempt_started_at` set and terminal stamps unset, per `target_agent_id`, at any moment (FR-044).
- [X] CHK019 FIFO requirement is independent of concurrency model (FR-044 + FR-045); the single-worker MVP satisfies it trivially, future worker-pool would need a per-target lock map.
- [X] CHK020 FIFO success criterion stated as `delivered`-order matches `enqueued_at`-order modulo non-delivered states (SC-010).
- [X] CHK021 Tie-breaking on identical `enqueued_at`: `message_id` lexical order (FR-031 + Edge Cases "Concurrent submission to the same target").

## Concurrency Model

- [X] CHK022 MVP = single worker; cross-target parallelism explicitly deferred (FR-045 + Clarifications Q5).
- [X] CHK023 Ready-row selection: `(enqueued_at, message_id)` ascending (FR-045 + Clarifications Q5).
- [X] CHK024 Worker wakeup cadence: `delivery_worker_idle_poll_seconds = 0.1` (plan §"Defaults locked"); overridable via `AGENTTOWER_TEST_DELIVERY_TICK` seam in tests (research §R-011).

## Shutdown & Lifecycle

- [X] CHK025 `send-input` during shutdown → `daemon_shutting_down` (Edge Cases + FR-049).
- [X] CHK026 Resolved by Group-A Q4: abort. Spec §Assumptions "Graceful shutdown is abort, not drain"; T042 worker loop exits at the next `_stop.is_set()` check without draining; next-boot FR-040 recovery resolves in-flight rows.
- [ ] CHK027 **Open**: behavior when SQLite is locked or unwritable at startup (e.g., another `agenttowerd` already running, or filesystem read-only) is not specified — does the daemon refuse to serve, serve read-only, or retry?
- [X] CHK028 Operator-visible degraded signals declared (FR-048 + `degraded_queue_audit_persistence` field + T054).
- [X] CHK029 `daemon_state` lives in the same SQLite DB; FR-016 byte-for-byte restart survival applies uniformly (data-model.md §2).
- [X] CHK030 "Successful tmux paste plus submit keystroke" = subprocess return codes for `load_buffer`, `paste_buffer`, `send_keys`, `delete_buffer` are all 0; no pane-content read required (plan §"Delivery worker loop" `try/except TmuxError` structure).

## Plan-Grounded Additions (2026-05-12 pass)

- [X] CHK031 Recovery is synchronous before `DeliveryWorker.start()`; T048 boot wiring + T043 call-order assertion (research §R-012).
- [X] CHK032 `idx_message_queue_in_flight` partial index `WHERE` clause matches the FR-040 recovery `UPDATE` predicate exactly (data-model.md §2).
- [X] CHK033 Recovery is a single `UPDATE` statement (plan §"Recovery + worker startup ordering"), not a per-row loop — atomic under `BEGIN IMMEDIATE`.
- [X] CHK034 "Drain buffered audits BEFORE pick next ready row" declared in plan §"JSONL audit append + degraded path"; T034 implements; T043 / T044 can extend to assert order.
- [X] CHK035 `delivery_attempt_timeout_seconds < send_input_default_wait_seconds` invariant declared in spec §Assumptions "Per-attempt delivery timeout" (added 2026-05-12); operators raising either MUST preserve the invariant.
- [X] CHK036 `Clock` Protocol seam (`AGENTTOWER_TEST_ROUTING_CLOCK_FAKE`) and `_stop.wait` granularity declared (plan §Testing + research §R-011).
- [X] CHK037 `routing_flag.is_enabled()` cache is write-through (plan §"In-memory state": "every toggle writes daemon_state first, then updates the cache"); T031 implements.
- [X] CHK038 Resolved by Group-A Q5: bounded retry (3 attempts at 10/50/250 ms); persistent failure → `failure_reason='sqlite_lock_conflict'` (added to FR-018 closed set). Spec §Assumptions "SQLite lock-conflict retry policy"; T028 DAO retry helper.
- [X] CHK039 `_wait_observers` cleanup: created on demand, removed on terminal transition (plan §"In-memory state").
- [X] CHK040 Resolved by Group-A Q6: `QueueAuditWriter.append` catches any `Exception` (not only `OSError`); buffers the record with the exception class captured for forensics; sets `degraded_queue_audit_persistence`. The SQLite INSERT (already committed) is never rolled back. T034 + T035 implement and test.

## Notes

- 39/40 items resolved (3 new Group-A walk resolutions appended); 1 remains open.
- **Outstanding decision for the user**: CHK027 (SQLite-locked-at-startup behavior — daemon refuses, retries, or serves read-only).
