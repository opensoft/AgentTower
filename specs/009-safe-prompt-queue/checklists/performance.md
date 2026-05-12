# Performance Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the performance / latency / throughput / memory requirements — SC-001 (3 s end-to-end delivery), SC-009 (≤ 100 ms body-too-large rejection), per-delivery budget breakdown, worker memory bound, configurable timeouts. Tests whether the performance contract is specified completely and is verifiable — NOT whether the implementation is fast.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-12
**Walked**: 2026-05-12
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

## Quantified Latency Budgets

- [X] CHK001 Per-stage breakdown declared in plan.md §"Performance Goals" "Per-delivery budget breakdown" (envelope render ≤ 1 ms, SQLite insert ≤ 5 ms, pre-paste re-check ≤ 50 ms, load_buffer ≤ 200 ms, paste_buffer ≤ 100 ms, send_keys ≤ 100 ms, delete_buffer ≤ 50 ms, delivered commit ≤ 50 ms → ≤ 600 ms typical).
- [X] CHK002 Sum (~600 ms) is well under SC-001's 3 s wall-clock; margin documented inline in plan.md §"Performance Goals".
- [X] CHK003 SC-001 conditions are operationally defined in spec.md: "no kernel pressure, healthy Docker, ≤ 4 KiB body".
- [X] CHK004 SC-009 is measured in the daemon — body validation runs server-side in `routing.envelope.validate_body` BEFORE any SQLite write (T022) and is asserted under 100 ms by T081.
- [X] CHK005 `delivery_attempt_timeout_seconds` (5.0) declared in plan.md §"Constraints" with mapping to `tmux_paste_failed` / `tmux_send_keys_failed` / `docker_exec_failed` and reinforced by the new spec §Assumptions "Per-attempt delivery timeout" entry.
- [X] CHK006 `send_input_default_wait_seconds` bounded [0.0, 300.0] in contracts/socket-queue.md and contracts/cli-send-input.md.

## Worker Throughput

- [X] CHK007 `delivery_worker_idle_poll_seconds` (0.1) declared as the empty-queue wakeup bound in plan.md §"Defaults locked".
- [X] CHK008 ≤ 10 deliveries/s peak declared in plan.md §"Scale/Scope" with the single-worker-adequacy rationale.
- [X] CHK009 FIFO at peak is operator-observable: queue depth is visible via `agenttower queue --state queued --target <agent>` per FR-031 / SC-010.
- [ ] CHK010 **Open**: worst-case latency for a row submitted concurrently with a kill-switch toggle is not bounded. Session 2 Q1 specifies the *correctness* contract (in-flight rows finish, new rows block) but no latency bound on how quickly the worker observes the toggle.

## Memory Bounds

- [X] CHK011 Per-row memory bound = 1 in-flight × ≤ 64 KiB envelope = ≤ 64 KiB; declared in plan.md §"Performance Goals" "Worker memory bound".
- [X] CHK012 Buffered-audit cap declared as `degraded_audit_buffer_max_rows = 1024` × per-row size in plan.md §"Defaults locked" + research §R-009.
- [X] CHK013 Total FEAT-009 memory bound at MVP scale (≤ 50 agents × in-flight=1) declared in plan.md §"Performance Goals".

## Degradation Under Load

- [X] CHK014 `events.jsonl` write latency degraded path declared in plan.md §"JSONL audit append + degraded path" and data-model.md §7.2.
- [ ] CHK015 **Open**: behavior under SQLite contention from multiple concurrent `send-input` calls is not specified. `BEGIN IMMEDIATE` provides serialization but per-call latency under high contention is undefined.
- [ ] CHK016 **Open**: disk-pressure behavior is partial — JSONL failure covered via `degraded_queue_audit_persistence`, but SQLite WAL exhaustion is not specified.
- [X] CHK017 `docker exec` consistently exceeding `delivery_attempt_timeout_seconds` → row transitions to `failed` with the appropriate `failure_reason` per FR-018 / FR-043 / plan.md §"Constraints".

## Measurement Surfaces

- [ ] CHK018 **Open**: the specific operator-visible latency metrics surfaced through `agenttower status` (cycle time, in-flight depth, last delivery latency) are not enumerated — T054 adds queue health to status but the field set is unspecified.
- [X] CHK019 Test seams `AGENTTOWER_TEST_ROUTING_CLOCK_FAKE` and `AGENTTOWER_TEST_DELIVERY_TICK` declared as the timing-control surface in research §R-011 and plan.md §Testing; production timing uses real `time.monotonic` when seams are unset.
- [X] CHK020 `time.monotonic` declared as the budget clock in plan.md §"Primary Dependencies" ("`time.time()` is forbidden inside the worker's hot path").

## Configurability

- [X] CHK021 Eight `[routing]` settings declared with default and spec-reference in plan.md §"Defaults locked"; units are implicit from setting names (`_seconds`, `_bytes`, `_chars`, `_rows`).
- [X] CHK022 Override mechanism is `config.toml` only — no env-var or CLI-flag override surface for these defaults; plan.md §"Defaults locked" lists no alternative override paths.
- [ ] CHK023 **Open**: explicit lower/upper bounds on each configurable value are not declared (e.g., minimum `envelope_body_max_bytes` that still fits the header set; maximum `send_input_default_wait_seconds`). Plan §"Defaults locked" gives defaults only.

## Notes

- 17/23 items resolved by spec/plan/research/contracts through the 2026-05-12 remediation; 6 remain open.
- **Outstanding decisions for the user**: CHK010 (kill-switch toggle observation latency), CHK015 (SQLite contention behavior), CHK016 (SQLite WAL disk pressure), CHK018 (`agenttower status` latency field set), CHK023 (configurable-value bounds).
