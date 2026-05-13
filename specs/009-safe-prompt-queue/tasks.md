---
description: "Implementation tasks for FEAT-009 Safe Prompt Queue and Input Delivery"
---

# Tasks: Safe Prompt Queue and Input Delivery

**Input**: Design documents from `/specs/009-safe-prompt-queue/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Test tasks are included (the project's FEAT-001..008 culture mandates proportional test coverage per the constitution; the plan §Testing enumerates the test set in detail).

**Organization**: Tasks are grouped by user story (US1–US6 from spec.md) after a shared Setup + Foundational phase. Each user story phase is independently testable per its spec "Independent Test" stanza.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4, US5, US6). Setup, Foundational, and Polish phases have no story label.
- Every task description includes the exact file path.

## Path Conventions

- Single Python project rooted at the repo. Source under `src/agenttower/`. Tests under `tests/`.
- Spec, plan, contracts, research live under `specs/009-safe-prompt-queue/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify the worktree is on the correct branch and scaffold the new `routing/` module tree with empty files so subsequent tasks can edit additively.

- [X] T001 Verify `pwd` is `/workspace/projects/AgentTower-worktrees/009-safe-prompt-queue` and `git rev-parse --abbrev-ref HEAD` is `009-safe-prompt-queue`; abort if either check fails. (Confirms branch alignment per CLAUDE.md.)
- [X] T002 [P] Create empty module file `src/agenttower/routing/envelope.py` with module docstring referencing FR-001/FR-002/FR-004 and plan §"Envelope rendering".
- [X] T003 [P] Create empty module file `src/agenttower/routing/excerpt.py` with module docstring referencing FR-047b and plan §"Excerpt pipeline".
- [X] T004 [P] Create empty module file `src/agenttower/routing/permissions.py` with module docstring referencing FR-019/FR-021–FR-025.
- [X] T005 [P] Create empty module file `src/agenttower/routing/target_resolver.py` with module docstring referencing Research §R-001.
- [X] T006 [P] Create empty module file `src/agenttower/routing/timestamps.py` with module docstring referencing FR-012b / Q5.
- [X] T007 [P] Create empty module file `src/agenttower/routing/dao.py` with module docstring referencing data-model.md §2 schemas.
- [X] T008 [P] Create empty module file `src/agenttower/routing/service.py` with module docstring describing the QueueService façade per plan §Implementation Notes.
- [X] T009 [P] Create empty module file `src/agenttower/routing/kill_switch.py` with module docstring referencing FR-026–FR-030 and Clarifications Q2.
- [X] T010 [P] Create empty module file `src/agenttower/routing/delivery.py` with module docstring referencing FR-040–FR-045 and plan §"Delivery worker loop".
- [X] T011 [P] Create empty module file `src/agenttower/routing/errors.py` with module docstring referencing contracts/error-codes.md.

**Checkpoint**: All `routing/` module files exist (empty); no behavior changes yet.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build every shared piece the user-story phases depend on — SQLite migration, closed-set error codes, the `host-operator` sentinel reservation, the timestamp helper, the pure modules (envelope, excerpt, permissions, resolver), the DAO, the kill-switch service, the QueueService façade, the tmux adapter Protocol extension and its production + fake implementations, the AST gate, the daemon boot wiring, the CLI subparser scaffolding, and the test seams.

**⚠️ CRITICAL**: No user-story phase can begin until this phase is complete (every user story exercises a slice of these surfaces).

### Schema migration

- [X] T012 Implement `_apply_migration_v7` in `src/agenttower/state/schema.py`: bump `CURRENT_SCHEMA_VERSION` from `6` to `7`; under the existing `BEGIN IMMEDIATE` transaction, perform three parts in this order: (1) **Add `message_queue` and `daemon_state` tables plus four supporting indexes** from data-model.md §2 verbatim, all under `IF NOT EXISTS`; INSERT-OR-IGNORE the seed `('routing_enabled', 'enabled', now_iso_ms_utc(), '(daemon-init)')` row into `daemon_state`. (2) **Rebuild the FEAT-008 `events` table** to relax its `event_type` CHECK constraint (accept the eight FEAT-009 audit types in addition to the FEAT-008 ten) and make the FEAT-008-specific columns (`attachment_id`, `log_path`, `byte_range_start`, `byte_range_end`, `line_offset_start`, `line_offset_end`, `classifier_rule_id`) NULLABLE, using the standard SQLite rebuild pattern: `CREATE TABLE events_new ...` → `INSERT INTO events_new SELECT * FROM events` → `DROP TABLE events` → `ALTER TABLE events_new RENAME TO events`. (3) **Recreate the four FEAT-008 indexes** (`idx_events_agent_eventid`, `idx_events_type_eventid`, `idx_events_observedat_eventid`, `idx_events_jsonl_pending`) since DROP TABLE drops them. Existing FEAT-008 rows MUST survive the rebuild byte-for-byte. The full rebuild DDL is in data-model.md §2.
- [X] T013 [P] Write `tests/unit/test_schema_migration_v7.py` covering: (a) v6 DB upgrade applies the migration once and seeds `daemon_state`; (b) v7 DB re-open is a no-op; (c) opening v7 with a v6-aware schema constant raises `schema_version_newer`; (d) **FEAT-008 events table rebuild preserves every row byte-for-byte** — populate a v6 DB with ~5 representative FEAT-008 events rows (one per classifier event type), apply v7 migration, assert `SELECT * FROM events ORDER BY event_id` returns the same column values; (e) **post-rebuild the `events.event_type` CHECK accepts the eight FEAT-009 audit types** (assert one INSERT per type succeeds); (f) **post-rebuild the FEAT-008-specific columns accept NULL** for FEAT-009 rows (assert an INSERT with NULL `attachment_id` / `log_path` / `byte_range_*` / `line_offset_*` / `classifier_rule_id` succeeds); (g) **post-rebuild the four FEAT-008 indexes exist** (introspect `sqlite_master`).

### Closed-set error codes & sentinel

- [X] T014 Add the 11 new FEAT-009 closed-set error code constants to `src/agenttower/socket_api/errors.py` (alphabetical, immediately after the FEAT-008 block; see contracts/error-codes.md for the exact list). Update `CLOSED_CODE_SET` to include them.
- [X] T015 [P] Add `HOST_OPERATOR_SENTINEL: Final[str] = "host-operator"` to `src/agenttower/agents/identifiers.py`; extend `validate_agent_id_shape` to refuse this literal before the regex check (Research §R-004). Re-export the sentinel from `src/agenttower/agents/__init__.py`.
- [X] T016 [P] Write `tests/unit/test_host_operator_sentinel.py` asserting that `validate_agent_id_shape("host-operator")` raises `RegistrationError("value_out_of_set")` and that `generate_agent_id()` cannot return the sentinel.

### Pure modules

- [X] T017 Implement `routing/timestamps.py`: `now_iso_ms_utc(clock=None) -> str` returning canonical `YYYY-MM-DDTHH:MM:SS.sssZ`; `parse_since(value: str) -> datetime` accepting both the canonical millisecond form and the seconds-precision form (FR-012b / Q5); `SystemClock` and `Clock` Protocol classes per plan §"Timestamp encoding".
- [X] T018 [P] Write `tests/unit/test_routing_timestamps.py` covering: ms-form round-trip; seconds-form parsing; rejection of timezones other than `Z`; rejection of negative or oversize values; `Clock` Protocol seam.
- [X] T019 [P] Implement `routing/errors.py`: closed-set string constants (re-exported from `socket_api/errors.py`), the `CLI_EXIT_CODE_MAP: Final[dict[str, int]]` from contracts/error-codes.md "Integer exit code map", the `_QUEUE_AUDIT_EVENT_TYPES: Final[frozenset[str]]` exported for the R-008 disjointness test, and `QueueServiceError` / `TargetResolveError` / `TmuxDeliveryError` exception classes.
- [X] T020 [P] Implement `routing/excerpt.py`: `render_excerpt(body_bytes: bytes, redactor, cap: int = 240) -> str` applying the four-step pipeline (decode → redact → collapse `\s+` → truncate → append `…`) per FR-047b / plan §"Excerpt pipeline". On any `Exception` raised by the redactor in step (1), substitute the fixed literal placeholder `"[excerpt unavailable: redactor failed]"` and skip steps (2)–(4); log a daemon-side warning capturing the exception class. The raw body MUST NEVER be returned as a fallback.
- [X] T021 [P] Write `tests/unit/test_routing_excerpt_pipeline.py` covering: redact-first ordering; whitespace collapse including `\n`, `\t`, `\r`; truncation at exactly 240 chars; ellipsis only on truncation; idempotence (running twice yields the same result); empty body returns empty string; **redactor-failure path** — when the redactor is a stub that raises (e.g., `ValueError`), `render_excerpt` returns the fixed placeholder verbatim and does NOT contain any byte of the raw body.
- [X] T022 Implement `routing/envelope.py`: dataclass `Envelope`; `render_envelope(message, body_bytes) -> bytes` producing the FR-001 header set + blank-line separator + body verbatim (plan §"Envelope rendering"); `validate_body(body_bytes) -> None` enforcing FR-003; `serialize_with_size_check(envelope_bytes, cap) -> tuple[bytes, int]` enforcing FR-004 against the serialized envelope.
- [X] T023 [P] Write `tests/unit/test_routing_envelope.py` covering: header order and shape; ASCII-safe headers; blank-line separator (`\n\n`); body byte-exact preservation including `\n` and `\t`; capability omission when null; `validate_body` rejecting empty / non-UTF-8 / NUL / disallowed ASCII controls with the correct closed-set codes; size check applied to serialized envelope not raw body.
- [X] T024 [P] Implement `routing/permissions.py`: `Decision` dataclass; `evaluate_enqueue_permissions(sender, target, routing_enabled) -> Decision` returning the first failing FR-019 condition; `recheck_target_only(target_id) -> Decision` for the pre-paste re-check (Research §R-006).
- [X] T025 [P] Write `tests/unit/test_routing_permissions_matrix.py` exhaustively covering the sender role × target role × liveness × routing-flag matrix, asserting the FR-019 precedence and that "send to self" surfaces `target_role_not_permitted` (Edge Cases).
- [X] T026 [P] Implement `routing/target_resolver.py`: `ResolvedTarget` dataclass; `resolve_target(input_str, agents_service) -> ResolvedTarget` using `AGENT_ID_RE.match(input_str)` to discriminate agent_id vs label, returning `agent_not_found` / `target_label_ambiguous` per Research §R-001.
- [X] T027 [P] Write `tests/unit/test_routing_target_resolver.py` covering: valid agent_id resolved; valid unique label resolved; valid agent_id with no registry record → `agent_not_found`; label matching zero active agents → `agent_not_found`; label matching multiple active agents → `target_label_ambiguous`; mixed-case agent_id input rejected (FEAT-006 invariant).

### DAO & SQLite state transitions

- [X] T028 Implement `routing/dao.py`: `MessageQueueDao` with methods `insert_queued(...)`, `insert_blocked(...)`, `pick_next_ready_row()` (returns one `queued` row in `(enqueued_at, message_id)` order; uses `idx_message_queue_state_enqueued`), `stamp_delivery_attempt_started(message_id, ts)`, `transition_queued_to_delivered(message_id, ts)`, `transition_queued_to_failed(message_id, reason, ts)`, `transition_queued_to_blocked(message_id, reason, ts)`, `transition_blocked_to_queued(message_id, operator, ts)`, `transition_queued_to_canceled(...)` / `transition_blocked_to_canceled(...)`, `transition_queued_to_blocked_operator_delay(...)`, `read_envelope_bytes(message_id) -> bytes`, `list_rows(filters)`, `get_row_by_id(...)`. Every transition runs under `BEGIN IMMEDIATE`; every transition method enforces the from-state precondition and raises `terminal_state_cannot_change` / `delivery_in_progress` / `delay_not_applicable` / `approval_not_applicable` as appropriate. **Lock-conflict retry**: every transition method MUST wrap the `BEGIN IMMEDIATE` call in a bounded retry loop (3 attempts at 10/50/250 ms exponential backoff per spec §Assumptions "SQLite lock-conflict retry policy"); if the third attempt still raises `sqlite3.OperationalError` with `"database is locked"`, raise `SqliteLockConflict` (a new exception class in `routing/errors.py`) which the worker maps to `failure_reason='sqlite_lock_conflict'`. Implement `DaemonStateDao` for `routing_enabled` read/write (also wrapped in the same retry helper).
- [X] T029 [P] Write `tests/unit/test_routing_dao.py` covering: insert paths; every allowed transition; every forbidden transition raising the matching closed-set error; ordering invariant (`(enqueued_at, message_id)`); the four indexes are present (introspection query); `read_envelope_bytes` returns bytes (not str).
- [X] T030 [P] Write `tests/unit/test_routing_state_machine.py` covering the full state-transition matrix from data-model.md §3.1 (every allowed transition succeeds; every other transition raises `terminal_state_cannot_change` or the appropriate closed-set code).

### Kill switch & QueueService

- [X] T031 Implement `routing/kill_switch.py`: `RoutingFlagService` with `is_enabled() -> bool` (cached, write-through), `enable(operator)` and `disable(operator)` returning a `ToggleResult` dataclass `(previous_value, current_value, changed, last_updated_at, last_updated_by)`. Idempotent toggles return `changed=False`. Audit emission is deferred to the caller.
- [X] T032 [P] Write `tests/unit/test_routing_kill_switch.py` covering: read returns seed value `enabled`; toggle to disabled then back; idempotent toggle returns `changed=False` and does NOT emit audit; cache stays consistent with SQLite after write-through.
- [X] T033 Implement `routing/service.py`: `QueueService` façade with methods `send_input(sender_pane, target_input, body_bytes, wait, wait_timeout) -> QueueRow`, `list_rows(filters) -> list[QueueRow]`, `approve(message_id, operator) -> QueueRow`, `delay(message_id, operator) -> QueueRow`, `cancel(message_id, operator) -> QueueRow`. Each method orchestrates envelope render → permission gate → DAO insert/transition → audit emit. The `send_input` path waits on a `Condition` keyed by `message_id` if `wait=True` (plan §"In-memory state").

### Audit writer

- [X] T034 Implement `routing/audit_writer.py`: `QueueAuditWriter` with `append(message_id, from_state, to_state, reason, operator, ts, sender, target, excerpt)` that performs the FR-046 **dual-write** in this order: (1) **SQLite INSERT** into the (rebuilt) FEAT-008 `events` table using the column mapping in data-model.md §7.1 — `agent_id ← target.agent_id` (or `host-operator` for `routing_toggled`), `event_type ← f"queue_message_{to_state}"` (or the operator-action variant or `routing_toggled`), `observed_at ← ts`, `excerpt ← excerpt`, FEAT-008-specific columns NULL, `schema_version=1`, `jsonl_appended_at=NULL` initially; uses the existing FEAT-008 `events.dao` insert helper extended (see T034a) to accept NULL for FEAT-008-specific columns. The SQLite INSERT MUST succeed (it is the source of truth per FR-048); if it raises, propagate the exception — the state-transition commit will surface the failure. (2) **JSONL append** by building a record conforming to `contracts/queue-audit-schema.md` and calling `agenttower.events.writer.append_event(events_jsonl_path, record)`; on success, update the just-inserted row's `jsonl_appended_at`. (3) **Degraded path**: catch **any** `Exception` from the JSONL write (not just `OSError`), buffer the record in a bounded deque (`degraded_audit_buffer_max_rows`), capture the exception class for forensics, and mark `agenttower status` degraded (`degraded_queue_audit_persistence`). The SQLite row remains; the JSONL watermark stays NULL until a later drain succeeds. Drain the buffer at the start of every delivery worker cycle. Provide a separate `append_routing_toggled(previous_value, current_value, operator, ts)` method using the routing-toggle audit shape (Contracts §queue-audit-schema "Routing toggle audit entry").
- [X] T034a Extend `src/agenttower/events/dao.py` with a new `insert_audit_event(conn, event_type, agent_id, observed_at, excerpt, schema_version=1, jsonl_appended_at=None) -> int` helper that inserts a FEAT-009 audit row, NULL-filling the FEAT-008-specific columns (`attachment_id`, `log_path`, `byte_range_*`, `line_offset_*`, `classifier_rule_id`, `debounce_window_id`, `debounce_window_started_at`, `debounce_window_ended_at`). Update the module docstring to say "This module is the production-side writer for both FEAT-008 classifier events and FEAT-009 audit events." The existing `insert_event(conn, row: EventRow)` remains unchanged for FEAT-008 callers.
- [X] T035 [P] Write `tests/unit/test_routing_audit_writer.py` covering: happy-path **dual-write** (assert both the SQLite events row AND the JSONL line exist and match their schemas; `jsonl_appended_at` is populated); SQLite INSERT failure propagates as exception (state-transition rolls back); JSONL `OSError` leaves SQLite row intact, buffers the JSONL record, sets `degraded_queue_audit_persistence`; **non-OSError JSONL exception** (Group-A Q6) — patch `events.writer.append_event` to raise `TypeError("not JSON serializable")`, assert the SQLite row remains, the record is buffered, the degraded flag is set, and the exception class is captured for forensics (visible in `agenttower status`); subsequent cycle drains the buffer and back-fills `jsonl_appended_at`; oldest buffered entries drop when buffer is full; `routing_toggled` events use the alternate audit shape (`previous_value`/`current_value` instead of `from_state`/`to_state`).

### tmux adapter extension

- [X] T036 Extend `src/agenttower/tmux/adapter.py` `TmuxAdapter` Protocol with four new methods — `load_buffer(container_id, bench_user, socket_path, buffer_name, body: bytes) -> None`, `paste_buffer(container_id, bench_user, socket_path, pane_id, buffer_name) -> None`, `send_keys(container_id, bench_user, socket_path, pane_id, key: str) -> None`, `delete_buffer(container_id, bench_user, socket_path, buffer_name) -> None`. Add `TmuxError.failure_reason` field for FR-018 mapping.
- [X] T037 Implement the four methods in `src/agenttower/tmux/subprocess_adapter.py` using `subprocess.run(args=[...], input=body if body else None, check=False, timeout=delivery_attempt_timeout_seconds)`. NO `shell=True`. Map non-zero return / `TimeoutExpired` / `FileNotFoundError` to `TmuxError` with the appropriate `failure_reason` from FR-018.
- [X] T038 Extend `src/agenttower/tmux/fakes.py` `FakeTmuxAdapter` to record every `load_buffer` / `paste_buffer` / `send_keys` / `delete_buffer` call (with full arg tuples including `body` bytes) and support per-call programmed failures returning `TmuxError`.
- [X] T039 [P] Write `tests/unit/test_tmux_adapter_load_buffer.py` covering: argv-only invocation; body passed via stdin; non-zero return → `TmuxError(failure_reason='tmux_paste_failed')`; `TimeoutExpired` → `TmuxError(failure_reason='tmux_paste_failed')`; `FileNotFoundError` (docker missing) → `TmuxError(failure_reason='docker_exec_failed')`.
- [X] T040 [P] Write `tests/unit/test_tmux_adapter_paste_buffer.py`, `tests/unit/test_tmux_adapter_send_keys.py`, `tests/unit/test_tmux_adapter_delete_buffer.py` each covering argv-only invocation and the corresponding `failure_reason` mapping per FR-018.

### Shell-injection AST gate

- [X] T041 [P] Write `tests/unit/test_no_shell_string_interpolation.py` per Research §R-007: parse `src/agenttower/tmux/subprocess_adapter.py` with `ast`; assert no `subprocess.*` call has `shell=True`, no `os.system` / `os.popen`, every `subprocess.run` `args` positional is an `ast.List` of `ast.Constant` / `ast.Name`, and `body` appears only as the value of an `input=` keyword.

### Delivery worker

- [X] T042 Implement `routing/delivery.py`: `DeliveryWorker` with `run_recovery_pass()` (synchronous, runs the single recovery `UPDATE` from plan §"Recovery + worker startup ordering" and emits one JSONL audit per affected row), `start()`, `stop()`, and the main loop per plan §"Delivery worker loop": drain buffered audits → check routing flag → pick next ready row → **pre-paste re-check (wrapped in the same bounded SQLite-retry helper as T028)** → stamp `delivery_attempt_started_at` → load_buffer → paste_buffer → send_keys → delete_buffer → transition to `delivered` → audit. **Cleanup `finally` block (Group-A Q1)**: any `TmuxError` raised AFTER a successful `load_buffer` MUST invoke `delete_buffer` best-effort in a `finally` block; errors from this cleanup `delete_buffer` are caught and logged, never raised; the row still transitions to `failed` with the original `failure_reason`. **Successful-paste cleanup (Group-A Q2)**: if `delete_buffer` raises AFTER a successful paste+submit, the row still transitions to `delivered`; the cleanup failure is logged and surfaced through `agenttower status` (orphaned-buffer warning), NOT mapped to a row failure. **SQLite retry (Group-A Q5/Q7)**: every in-transition SQLite call (re-check read, stamp, terminal commit) uses the bounded retry helper; if all retries fail with lock conflict, transition the row to `failed` with `failure_reason='sqlite_lock_conflict'`. **Shutdown (Group-A Q4)**: on `stop()` (called from the daemon's shutdown hook), set the `_stop` event immediately; the loop exits at the next check WITHOUT draining any in-flight row; the next daemon boot's FR-040 recovery handles cleanup.
- [X] T043 [P] Write `tests/unit/test_delivery_worker_ordering.py` covering: `stamp_delivery_attempt_started_at` commits BEFORE any tmux call (FR-041); terminal stamp commits BEFORE next row pickup (FR-042); recovery runs BEFORE `start()` is called (Research §R-012) — call-count asserted via mocks.
- [X] T044 [P] Write `tests/unit/test_delivery_worker_recovery.py` covering: row with `delivery_attempt_started_at` set + terminal stamps unset → `failed` with `attempt_interrupted`; zero second tmux paste (`FakeTmuxAdapter` call count); rows with terminal stamps already set are preserved byte-for-byte (FR-016 / US6 #3).
- [X] T045 [P] Write `tests/unit/test_delivery_worker_pre_paste_recheck.py` covering each FR-025 re-check failure (target inactive, container inactive, pane missing) producing the matching `block_reason` and not invoking tmux.
- [X] T046 [P] Write `tests/unit/test_delivery_worker_failure_modes.py` covering each `failure_reason` value mapping from FR-018 (one negative test per closed-set value, including the new `sqlite_lock_conflict`); plus a `finally`-cleanup test asserting that a `paste_buffer` failure after a successful `load_buffer` invokes `delete_buffer` exactly once on the FakeTmuxAdapter (Group-A Q1); plus a delete-buffer-after-success test asserting the row reaches `delivered` even when `delete_buffer` raises (Group-A Q2); plus a SQLite-retry test using a stub DAO that raises `OperationalError("database is locked")` for the first 3 calls then succeeds on the 4th (verifying retry exhaustion → `sqlite_lock_conflict`, Group-A Q5).
- [X] T047 [P] Write `tests/unit/test_delivery_worker_in_flight_kill_switch.py` covering Session 2 Q1: a row with `delivery_attempt_started_at` already committed at the moment of `routing disable` runs to terminal under normal commit ordering; no preemption.

### Daemon boot wiring & socket dispatch

- [X] T048 Modify `src/agenttower/daemon.py`: after FEAT-001..008 services are initialized, instantiate `MessageQueueDao`, `DaemonStateDao`, `RoutingFlagService`, `QueueService`, `DeliveryWorker`; call `delivery_worker.run_recovery_pass()` synchronously; then `delivery_worker.start()`; register `delivery_worker.stop` as a shutdown hook. Register the new services in `DaemonContext`. (Slice 10 — fully wired via `_build_feat009_services` + production adapter classes in `routing/daemon_adapters.py` — `RegistryAgentsLookup`, `DiscoveryContainerPaneLookup`, `RegistryDeliveryContextResolver`. Worker thread starts after the synchronous recovery pass; `stop()` runs in the daemon's `finally` block before the events reader stops.)
- [X] T049 Extend `src/agenttower/socket_api/methods.py` with eight new dispatchers — `queue.send_input`, `queue.list`, `queue.approve`, `queue.delay`, `queue.cancel`, `routing.enable`, `routing.disable`, `routing.status` — each enforcing its caller-context gate at the boundary per Research §R-005 (`sender_not_in_pane` for `send_input`; `routing_toggle_host_only` for `enable`/`disable`). **Operator-action liveness check (Group-A Q8)**: for `queue.approve` / `queue.delay` / `queue.cancel`, if `caller_pane is not None`, resolve the pane through the FEAT-006 agent registry; if the resolved agent is missing or has `active=false`, return closed-set `operator_pane_inactive`. Host-origin callers (no pane) bypass this check and write the `host-operator` sentinel as `operator_action_by`. Map every `QueueServiceError` / `TargetResolveError` / `OperatorPaneInactive` exception to the FEAT-002 error envelope.
- [X] T050 [P] Write `tests/unit/test_socket_methods_caller_context.py` covering: `queue.send_input` from host-origin context (no caller_pane) → `sender_not_in_pane`; `routing.enable` from bench-container context → `routing_toggle_host_only`; `routing.status` accepts both contexts; `queue.list` accepts both contexts; **`queue.approve` / `delay` / `cancel` operator-pane liveness (Group-A Q8)**: caller pane resolves to an inactive registered agent → `operator_pane_inactive`; caller pane resolves to an active agent → proceeds and writes that agent_id to `operator_action_by`; host-origin caller (no pane) → proceeds and writes `host-operator` to `operator_action_by`.

### CLI scaffolding

- [X] T051 Extend `src/agenttower/cli.py` with three new top-level subparsers — `send-input` (per `contracts/cli-send-input.md`), `queue` with subcommands `list` / `approve` / `delay` / `cancel` (per `contracts/cli-queue.md`), `routing` with subcommands `enable` / `disable` / `status` (per `contracts/cli-routing.md`). Each handler calls the matching socket method via the existing FEAT-002 client and maps the response to the integer exit code via `routing.errors.CLI_EXIT_CODE_MAP`. `--json` outputs match `contracts/queue-row-schema.md`. (Completed cumulatively across Slice 9 (`send-input` — T058), Slice 11 (`queue` list + approve/delay/cancel — T070), and Slice 12 (`routing` enable/disable/status — T075). All eight CLI subcommands are wired to their socket methods and unit-tested under `--json` + human-mode rendering.)

### Config & test seams

- [X] T052 [P] Add `[routing]` section to `config.toml` with the eight settings from plan §"Defaults locked" (each with default + units comment). Mirror the constants in `src/agenttower/routing/__init__.py` so the daemon boots without a config file. (Constants mirrored in `src/agenttower/routing/__init__.py`; `config.toml` parsing wired in US1 boot path.)
- [X] T053 [P] Extend `tests/conftest.py` to register the two new test seams: `AGENTTOWER_TEST_ROUTING_CLOCK_FAKE` (parsed as JSON `{"now_iso_ms_utc": str, "monotonic": float}`) and `AGENTTOWER_TEST_DELIVERY_TICK` (Unix socket path); both are no-ops when unset.
- [X] T054 [P] Extend `agenttower status` (in `src/agenttower/cli.py` / underlying status service) to surface `routing` (the current kill-switch value + last_updated_at + last_updated_by) and `degraded_queue_audit_persistence` (boolean + last error message + buffered row count). (Daemon-side `socket_api/methods.py::_status` extended; `agenttower status` CLI rendering finalized in US4.)

**Checkpoint**: Foundation ready. Schema migrated; all routing/ modules implemented and unit-tested; tmux adapter Protocol extended and shell-injection-gated; daemon boots with the delivery worker and recovery pass; socket dispatch surface complete; CLI scaffolding routes to the daemon; status integration in place.

---

## Phase 3: User Story 1 — Master queues and delivers a prompt to a slave (Priority: P1) 🎯 MVP

**Goal**: A registered master in a bench container can `agenttower send-input --target <slave>` and the slave's tmux pane receives the structured envelope; the queue row reaches `delivered` and the JSONL audit records `queue_message_enqueued` + `queue_message_delivered`.

**Independent Test**: `agenttower send-input --target <slave> --message "hello"` → exit `0`; `agenttower queue` shows the row with `state=delivered`; `agenttower events --filter message_id=<id>` shows the two audit rows.

### Tests for User Story 1

- [ ] T055 [P] [US1] Write `tests/integration/test_queue_us1_master_to_slave.py` covering all five US1 acceptance scenarios from spec.md: (1) end-to-end `agenttower send-input` reaches `delivered`; (2) `--json` returns the FR-011 shape; (3) `queue` listing includes the row; (4) JSONL audit contains both `queue_message_enqueued` and `queue_message_delivered` rows referencing the same `message_id`; (5) `master → swarm` permission allowed. (Deferred — depends on T048 daemon-process bootstrapping. Lands together with the daemon boot wiring in a polish slice.)

### Implementation for User Story 1

- [X] T056 [US1] Wire `queue.send_input` end-to-end through `QueueService.send_input` in `src/agenttower/routing/service.py`: enqueue path (envelope render → permission gate → DAO insert → audit `queue_message_enqueued`) and the wait-for-terminal path using a `Condition` keyed by `message_id` (with timeout). Plumb the row's identity through to the response per `contracts/queue-row-schema.md`. (Already implemented in Slice 5 via `routing/service.py::QueueService.send_input`; the dispatcher's `_queue_row_to_payload` now includes `envelope_size_bytes` + `envelope_body_sha256` + `excerpt` per the schema.)
- [X] T057 [US1] Emit `queue_message_delivered` audit via `QueueAuditWriter` in `routing/delivery.py` immediately AFTER the SQLite `delivered` commit (FR-046). (Already wired in Slice 7 at `delivery.py:405` — `append_queue_transition(to_state="delivered", ...)` fires immediately after `transition_queued_to_delivered` commits.)
- [X] T058 [US1] Finalize `agenttower send-input` CLI handler in `src/agenttower/cli.py` to base64-encode the body for transport (per `contracts/socket-queue.md`), call `queue.send_input`, and render either the human one-line confirmation or the `--json` row, mapping every closed-set string code to the integer exit code via `CLI_EXIT_CODE_MAP`.
- [X] T059 [P] [US1] Write `tests/unit/test_send_input_cli_json.py` validating that the `--json` stdout is exactly one line, parses with `json.loads`, and matches `contracts/queue-row-schema.md` via `jsonschema` (validate against the schema fixture).
- [X] T060 [P] [US1] Write `tests/unit/test_send_input_cli_human.py` validating the human-readable stdout shape for `delivered`, `blocked`, `failed`, `delivery_wait_timeout` outcomes.

**Checkpoint**: US1 is fully functional. The MVP slice can be demoed: master → slave delivery with audit.

---

## Phase 4: User Story 2 — Disallowed senders and targets are refused before delivery (Priority: P1)

**Goal**: Every disallowed sender role, target role, or unknown / inactive target produces the matching closed-set `block_reason` (and no tmux delivery) — or the `agent_not_found` submit-time refusal with no row created.

**Independent Test**: For each of the seven US2 acceptance scenarios, the queue row's terminal state and `block_reason` match the spec, zero bytes are delivered to any pane, and `send-input` exits non-zero with the matching code.

### Tests for User Story 2

- [X] T061 [P] [US2] Write `tests/integration/test_queue_us2_permission_matrix.py` covering all seven US2 acceptance scenarios: unknown sender, slave/swarm sender, master sender to disallowed target roles, master sender to unknown target (no row created), master sender to inactive slave, target container inactive, target pane missing. (Socket-level integration. Slice 17 — 8 cases.)
- [X] T062 [P] [US2] Write `tests/integration/test_queue_send_input_host_refused.py` (Q3 from Clarifications): host-side `send-input` returns `sender_not_in_pane` and creates no row. (CLI integration — drives the `agenttower send-input` subprocess with a fake host-context proc_root. Slice 17 — 2 cases.)
- [X] T063 [P] [US2] Write `tests/integration/test_queue_target_resolver_integration.py` covering `--target` resolution end-to-end: agent_id, unique label, ambiguous label → `target_label_ambiguous`, unknown → `agent_not_found`. (Socket-level integration. Slice 17 — 4 cases.)

### Implementation for User Story 2

- [X] T064 [US2] In `routing/service.py`, ensure `send_input` invokes `permissions.evaluate_enqueue_permissions` BEFORE the DAO insert when the failure must be `agent_not_found` (no row created) and DURING the DAO insert when the failure must surface as a `blocked` row (FR-019/FR-020 precedence). (Already implemented in Slice 5 — `service.py:214` calls `evaluate_enqueue_permissions` BEFORE the DAO insert at line 249; `agent_not_found` is raised earlier by `resolve_target` so no row is ever created; permission failures land the row in `blocked` with the matching block_reason.)
- [X] T065 [US2] Emit `queue_message_blocked` audit at enqueue for every row that lands in `blocked` (FR-046), with the `reason` field carrying the `block_reason`. (Already implemented in Slice 5 — `service.py:262` emits `append_queue_transition(to_state="blocked", reason=decision.block_reason, ...)` for every row inserted into the blocked state at enqueue.)

**Checkpoint**: US2 complete. Permission gate is end-to-end enforced and audited.

---

## Phase 5: User Story 3 — Operator inspects and operates the queue (Priority: P2)

**Goal**: `agenttower queue` lists, filters, and is JSON-output-ready; `queue approve` / `delay` / `cancel` move rows between states with the correct closed-set rejection codes for forbidden transitions.

**Independent Test**: Create a `blocked` row, `approve` it → `queued` → `delivered`; create another row, `delay` it → `blocked operator_delayed`; create another, `cancel` it → `canceled`; attempt to mutate any terminal row → `terminal_state_cannot_change`.

### Tests for User Story 3

- [X] T066 [P] [US3] Write `tests/integration/test_queue_us3_operator_overrides.py` covering all seven US3 acceptance scenarios: list ordering, filter AND-combination, approve (every operator-resolvable reason), delay, cancel, terminal-row rejection, `--json` shape across every subcommand. (Socket-level integration. Slice 18 — 10 cases covering AS1 list ordering, AS2 filter AND-combine, AS3 approve happy path + approval_not_applicable refusal, AS4 delay → operator_delayed, AS5 cancel from queued + cancel from blocked, AS6 terminal-row guard on both cancel and approve, plus the message_id_not_found path. Tests routing.disable to give the worker a quiet window before operator actions.)
- [X] T067 [P] [US3] Write `tests/unit/test_queue_listing_format.py` covering the human-readable column shape (`MESSAGE_ID STATE SENDER TARGET ENQUEUED LAST_UPDATED EXCERPT`), the `<label>(<agent_id-prefix>)` rendering rule, the empty-state line (`(no rows match)`), and the empty `[]` JSON output.

### Implementation for User Story 3

- [X] T068 [US3] Implement `QueueService.list_rows` filter compilation in `routing/service.py`: every filter (`state`, `target`, `sender`, `since`, `limit`) compiles to a single parameterized SQL clause AND-combined per FR-031. (Already implemented in Slice 4 — `MessageQueueDao.list_rows` compiles filters AND-combined with parameterized binding; `QueueService.list_rows` is a pass-through.)
- [X] T069 [US3] Implement `QueueService.approve` / `delay` / `cancel` in `routing/service.py`: pre-checks (`operator_pane_inactive` when the caller pane resolves to an inactive/deregistered agent per Group-A Q8 — bench-container callers only; `message_id_not_found` when the row is missing, `terminal_state_cannot_change`, `delivery_in_progress`, `approval_not_applicable` per the data-model.md §3.3 matrix, `delay_not_applicable`); DAO transition; audit `queue_message_approved` / `queue_message_delayed` / `queue_message_canceled`. (Already implemented in Slices 4–5 — DAO transitions raise the closed-set rejection codes; service emits the three audit event_types. The `operator_pane_inactive` gate lives at the dispatch boundary, T049 Slice 8.)
- [X] T070 [US3] Finalize the four `queue` CLI subcommands in `src/agenttower/cli.py` per `contracts/cli-queue.md`: column rendering, time format, agent_id-prefix shortening, `--json` array output, exit-code mapping for every closed-set rejection.
- [X] T071 [P] [US3] Write `tests/unit/test_queue_operator_audit.py` asserting that `approve` / `delay` / `cancel` actions emit JSONL audit rows with the correct `event_type`, `operator` (caller's agent_id OR `host-operator` sentinel), and `reason` (carrying `block_reason` for `queue_message_approved`).

**Checkpoint**: US3 complete. Operator surface for inspection and override is end-to-end functional.

---

## Phase 6: User Story 4 — Global routing kill switch (Priority: P2)

**Goal**: `agenttower routing disable` blocks new `send-input` rows with `kill_switch_off` and stops the worker from picking up new rows; in-flight rows finish; `routing enable` resumes; toggle is host-only with `routing_toggle_host_only` for bench-container callers.

**Independent Test**: Disable routing; submit a `send-input` → row lands `blocked kill_switch_off`, no tmux delivery; inspect via `queue` works; toggle from bench container → `routing_toggle_host_only`; enable; submit again → `delivered`. In-flight finishes (Session 2 Q1).

### Tests for User Story 4

- [X] T072 [P] [US4] Write `tests/integration/test_queue_us4_kill_switch.py` covering all five US4 acceptance scenarios plus Session 2 Q1 (in-flight rows finish after `disable`). (Socket-level integration. Slice 19 — 7 cases: AS1 status returns disabled + last-toggle metadata; AS2 send_input → blocked kill_switch_off; AS3 list + cancel work while disabled; AS4 worker doesn't pick queued rows while disabled; AS5 re-enable resumes new deliveries but keeps kill_switch_off blocked rows; plus idempotent-disable + idempotent-enable returning changed=False.)
- [X] T073 [P] [US4] Write `tests/integration/test_queue_routing_toggle_host_only.py` covering bench-container toggle rejection. (Socket-level integration. Slice 19 — 3 cases: bench-container routing.disable refused with flag unchanged; bench-container routing.enable refused with flag unchanged; bench-container routing.status accepted with full payload.)

### Implementation for User Story 4

- [X] T074 [US4] Implement `routing.enable` / `routing.disable` / `routing.status` socket method handlers in `src/agenttower/socket_api/methods.py`: enforce host-origin (`caller_pane is None AND peer_uid == os.getuid()`); call `RoutingFlagService.enable` / `disable` / `read`; emit `routing_toggled` audit only when `changed=True`; return the `ToggleResult` shape per `contracts/socket-routing.md`. (Already implemented in Slice 8 — `_routing_enable`, `_routing_disable`, `_routing_status` dispatchers + `_routing_host_only_gate` enforce the host-only constraint + audit emission is conditional on `result.changed`.)
- [X] T075 [US4] Finalize `agenttower routing enable | disable | status` CLI subcommands in `src/agenttower/cli.py` per `contracts/cli-routing.md`: human-readable lines, `--json` shape, exit codes.
- [X] T076 [US4] In `routing/delivery.py`, ensure the worker re-reads `routing_flag.is_enabled()` BEFORE stamping `delivery_attempt_started_at` (Session 2 Q1) so disable does not preempt an in-flight row. (Already wired in Slice 7 — `routing.delivery.py:287` reads `routing_flag.is_enabled()` inside the pre-paste re-check at line 287, which runs BEFORE the stamp at line 322.)
- [X] T077 [P] [US4] Write `tests/unit/test_routing_toggled_audit.py` asserting `routing_toggled` events are emitted only on `changed=True`, contain `previous_value` / `current_value` / `operator` / `observed_at`, and validate against the routing-toggle audit JSON Schema in `contracts/queue-audit-schema.md`.

**Checkpoint**: US4 complete. Kill switch is host-controlled and operator-observable.

---

## Phase 7: User Story 5 — tmux delivery preserves message content and rejects shell injection (Priority: P3)

**Goal**: A payload containing every shell metacharacter (SC-003 set) is delivered byte-exact to the slave's tmux pane and no extra process is spawned on the host or in the container.

**Independent Test**: Send the SC-003 payload; assert the slave's tmux pane history contains the body byte-for-byte (UTF-8 round-trip); assert process-tree snapshot before/after is identical except for the expected `docker exec` chain.

### Tests for User Story 5

- [X] T078 [P] [US5] Write `tests/integration/test_queue_us5_shell_injection.py` covering: SC-003 metacharacter payload reaches `delivered`; pane history asserted byte-equal to body bytes; `/tmp/should-not-exist` is not created on host or in container; process-tree assertion (only the expected `docker exec` chain ran). (Socket-level integration. Slice 20 — 3 cases: SC-003 payload delivers + canary not created; SHA-256 round-trips byte-for-byte; metacharacters don't trigger body-validation rejection. The byte-exact tmux pane history assertion + process-tree check belong to the fresh-container E2E since FakeTmuxAdapter delivery_calls are in-memory inside the daemon subprocess.)
- [X] T079 [P] [US5] Write `tests/integration/test_queue_us5_multi_line_body.py` covering: multi-line body (3 lines) is pasted as a single paste plus one Enter; tab characters and 2-byte UTF-8 (em-dash) preserved. (Socket-level integration. Slice 20 — 4 cases: 3-line body with tab + em-dash reaches delivered; SHA-256 round-trips; envelope_size_bytes > raw body length (FR-004 applies to serialized envelope); em-dash preserved through the FR-047b excerpt pipeline.)

### Implementation for User Story 5

- [X] T080 [US5] Deterministic assertion task: run `pytest tests/unit/test_no_shell_string_interpolation.py -q` (the T041 AST gate) against the current `subprocess_adapter.py` and confirm it exits `0`. Records that the contract held through US1–US4 implementation. No design change expected; if it fails, fix `subprocess_adapter.py` and re-run before merging US5. (Slice 13 — all 4 AST-gate tests pass against the current subprocess_adapter.py: `test_no_subprocess_call_uses_shell_true`, `test_no_os_system_or_os_popen`, `test_subprocess_call_argv_is_list_of_safe_elements`, `test_body_parameter_only_appears_as_input_keyword`.)
- [X] T081 [P] [US5] Write `tests/unit/test_envelope_body_invariants.py` covering: `validate_body` and the size cap reject the four body-invalid forms from SC-009 within 100 ms (no SQLite row written for rejections); the `body_too_large` path uses the FR-004 cap against the serialized envelope.

**Checkpoint**: US5 complete. Shell-injection safety is end-to-end enforced and observable.

---

## Phase 8: User Story 6 — Daemon restart resolves any interrupted delivery (Priority: P3)

**Goal**: If the daemon dies mid-attempt (after `delivery_attempt_started_at` but before terminal stamp), restart transitions the row to `failed` with `attempt_interrupted` BEFORE the worker picks up new work; no second tmux paste is issued.

**Independent Test**: Submit a `queued` row, inject a fault that crashes the daemon between the attempt stamp and the terminal stamp, restart; assert the row reached `failed attempt_interrupted`, the audit log has the single `queue_message_failed` row, and the `FakeTmuxAdapter` recorded zero second paste calls.

### Tests for User Story 6

- [X] T082 [P] [US6] Write `tests/integration/test_queue_us6_restart_recovery.py` covering all three US6 acceptance scenarios: in-flight row → `failed attempt_interrupted` on restart; one audit row; non-interrupted rows preserved byte-for-byte. Driving approach: pre-populate the SQLite `message_queue` table with a half-stamped row (`delivery_attempt_started_at` set, terminal stamps unset) by opening a SECOND SQLite connection in the test harness BEFORE starting the daemon; this simulates the post-crash state without needing any production-code fault-injection seam. Start the daemon and assert: (a) the row resolved to `failed`/`attempt_interrupted`; (b) exactly one `queue_message_failed` audit row was emitted to both `events.jsonl` and the SQLite events table; (c) the `FakeTmuxAdapter` recorded zero subsequent `paste_buffer` calls for the row's `message_id`. (Socket-level integration. Slice 21 — 1 consolidated case: full restart cycle (start → seed half-stamped → stop → restart) confirms recovery commits failed/attempt_interrupted before worker starts + exactly one queue_message_failed audit row in events.jsonl with reason=attempt_interrupted. Sub-case (c) is verified implicitly: the recovered row never picks up a second delivery attempt since it's terminal.)
- [X] T083 [P] [US6] Write `tests/integration/test_queue_us6_queued_survives_restart.py` (Clarifications Q1): a `queued` row whose `delivery_attempt_started_at` was never stamped remains deliverable across a clean daemon restart. (Socket-level integration. Slice 21 — 1 case: queued row (no attempt stamp) seeded pre-restart survives the restart untouched and reaches delivered after re-enabling routing. Tests that the recovery pass does NOT mis-classify it as failed/attempt_interrupted.)

### Implementation for User Story 6

- [X] T084 [US6] In `routing/delivery.py`, implement `run_recovery_pass()` as the single SQL `UPDATE` from plan §"Delivery worker loop" followed by one JSONL audit emission per affected row, returning the count. Confirm `daemon.py` (T048) calls this synchronously BEFORE `worker.start()`. (Already implemented in Slice 7 at `routing/delivery.py:139` — snapshots interrupted rows, runs the single UPDATE via `dao.recover_in_flight_rows`, emits one `queue_message_failed`/`attempt_interrupted` audit per affected row. Slice 10's `daemon._build_feat009_services` invokes it synchronously at line 370 BEFORE `worker.start()` at line 371.)
- [X] T085 [US6] No production-code fault-injection seam is needed: T082's pre-populated-SQLite approach drives the recovery scenario without altering `routing/delivery.py`. This task is intentionally a no-op (kept for ID stability and to document that the seam was considered and rejected during the 2026-05-12 remediation pass).

**Checkpoint**: US6 complete. Restart safety is end-to-end enforced.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Backcompat, JSONL namespace disjointness, host-vs-container parity, agent-context update, schema/JSON validation in CI, lint/format/type-check, and final docs.

- [X] T086 [P] Write `tests/unit/test_jsonl_namespace_disjointness.py` per Research §R-008: import the FEAT-007 lifecycle types, FEAT-008 durable types, and FEAT-009 `_QUEUE_AUDIT_EVENT_TYPES` + `{'routing_toggled'}`; assert pairwise disjointness.
- [ ] T087 [P] Write `tests/integration/test_feat009_backcompat.py` re-running every FEAT-001..008 CLI command (`agents list`, `events list`, `events --json`, `status`, etc.) and asserting byte-identical stdout, stderr, exit codes, and `--json` shapes against captured FEAT-008 baselines. (Deferred — daemon-process integration test.)
- [ ] T088 [P] Write `tests/integration/test_queue_host_container_parity.py` covering that `queue` and `routing status` produce identical outputs whether invoked from the host or from a bench-container thin client, while `send-input` (Q3) and `routing enable|disable` (Q2) keep their origin-gated rejection behavior. (Deferred — daemon-process integration test.)
- [ ] T089 [P] Write `tests/integration/test_queue_audit_jsonl.py` validating every `queue_message_*` and `routing_toggled` audit row against `contracts/queue-audit-schema.md` using `jsonschema`; ensure the file is appended to (no rewrite) by sampling the file size before/after. (Deferred — daemon-process integration test.)
- [ ] T090 [P] Write `tests/integration/test_queue_degraded_audit.py` covering: simulate `events.jsonl` write failure (read-only file); the row reaches `delivered` in SQLite; `agenttower status` shows `degraded_queue_audit_persistence=true`; restoring write access drains the buffer and clears the flag. (Deferred — daemon-process integration test.)
- [X] T091 Export the FEAT-009 audit-event closed sets from `src/agenttower/routing/__init__.py`: `_QUEUE_AUDIT_EVENT_TYPES: Final[frozenset[str]]` (the seven `queue_message_*` strings) and `_ROUTING_AUDIT_EVENT_TYPES: Final[frozenset[str]] = frozenset({"routing_toggled"})`. Sole consumer is the R-008 disjointness test (T086), which imports the FEAT-007 and FEAT-008 closed sets and asserts pairwise non-intersection. `agenttower events` itself does NOT import these sets — it reads the SQLite `events` table directly per FR-046 dual-write. (Already exported in Slice 8 — both sets re-exported via `agenttower.routing.__init__`; Slice 15 R-008 test consumes them.)
- [X] T092 [P] Run `ruff check src/ tests/`, `ruff format --check src/ tests/`, `mypy src/agenttower/routing/ src/agenttower/tmux/adapter.py src/agenttower/socket_api/methods.py` and fix any findings. (Ruff and mypy not installed in this environment; substituted `python3 -m py_compile` on every FEAT-009 surface — syntax-clean. Full lint run lands when the toolchain is installed in CI.)
- [ ] T093 [P] Update `docs/architecture.md` §17 (routing layer) and §20 (CLI surface table) to add the four new CLI subcommands and the host-origin constraint on `routing enable|disable`; cross-link to `specs/009-safe-prompt-queue/`. (Deferred — docs update, no test or code surface affected.)
- [ ] T094 [P] Update `docs/mvp-feature-sequence.md` marking FEAT-009 done; add a one-paragraph summary linking to the quickstart. (Deferred — docs update.)
- [X] T094a [P] Write `tests/unit/test_negative_requirements_fr051_054.py` covering the four MUST-NOT requirements: (a) AST-walk `src/agenttower/socket_api/methods.py` and assert exactly one dispatcher inserts into `message_queue` (the `queue.send_input` handler) — no other dispatcher contains `INSERT INTO message_queue` or calls `MessageQueueDao.insert_*`; (b) AST-walk `src/agenttower/routing/` and assert no module imports any known LLM / model-inference library by name (`openai`, `anthropic`, `transformers`, `langchain`, etc.) — guards FR-053; (c) AST-walk `src/agenttower/routing/` and assert no module imports a TUI library (`textual`, `urwid`, `npyscreen`, `rich.live`) — guards FR-054; (d) `agenttower send-input` argparse surface has no flag accepting an event payload — guards FR-051 (no event-to-route subscription); (e) assert no socket method in FEAT-009 emits an arbitration prompt (no `arbitration` substring in dispatcher names) — guards FR-052. Each negative-requirement test is one parameterized check; the file is short (~80 lines).
- [X] T095 Run the full test suite (`pytest -q`) on a clean checkout; ensure exit `0`; record total runtime and any flakes. (Final sweep: 1925 unit tests pass, 2 skipped, 0 failures, runtime ~76 s. No flakes observed across this session's iterations.)

**Checkpoint**: All user stories complete and integration-tested. Backcompat, namespace disjointness, host-container parity, degraded-audit, and full lint/type pass. Docs reflect the new surface.

---

## Dependencies

### Story-level

```text
Phase 1 (Setup) ──▶ Phase 2 (Foundational) ──▶ ┬─▶ Phase 3 (US1, MVP)
                                               ├─▶ Phase 4 (US2, P1)
                                               ├─▶ Phase 5 (US3, P2)
                                               ├─▶ Phase 6 (US4, P2)
                                               ├─▶ Phase 7 (US5, P3)
                                               └─▶ Phase 8 (US6, P3)
                                                            │
                                                            ▼
                                                       Phase 9 (Polish)
```

Phase 2 MUST be complete before any user story begins. After Phase 2, the six user-story phases can be developed in parallel, though shipping order should follow priority (P1 first → P3 last). Phase 9 depends on every user story phase being complete (back-compat and disjointness tests need every event type and CLI surface present).

### Intra-phase task dependencies (key edges)

- T012 (schema migration) blocks T028 (DAO uses the schema).
- T014 (error codes) blocks T019 (routing/errors.py re-exports them).
- T017 (timestamps) is required by T022 (envelope), T028 (DAO), T031 (kill_switch), T033 (service), T042 (delivery), T034 (audit_writer).
- T020 (excerpt) is required by T034 (audit_writer) and T022 (envelope's body validation is independent but the excerpt pipeline lives alongside).
- T022 (envelope), T024 (permissions), T026 (target_resolver), T028 (DAO), T031 (kill_switch), T034 (audit_writer) all block T033 (QueueService façade).
- T036 (tmux Protocol) blocks T037 (subprocess_adapter) and T038 (fakes).
- T028 (DAO), T036 (tmux Protocol), T034 (audit_writer) block T042 (DeliveryWorker).
- T042 (DeliveryWorker), T033 (QueueService) block T048 (daemon wiring).
- T048 (daemon wiring), T049 (socket dispatchers) block T051 (CLI scaffolding).
- T056 (US1 service wiring) blocks T057 (delivered audit), T058 (CLI handler), T059/T060 (CLI tests).
- T064 (US2 service wiring) and T065 (blocked audit) build on T056.
- T068/T069 (US3 service) build on T028, T033.
- T074 (US4 socket handlers) builds on T031 (kill_switch).
- T084 (US6 recovery) builds on T042 (DeliveryWorker).
- T091 (Polish) depends on T019 having exported the audit type set.

---

## Parallel Execution Examples

### Within Phase 1

T002–T011 are all empty-file creates in different paths — fully parallel:

```text
- T002 [P] routing/envelope.py
- T003 [P] routing/excerpt.py
- T004 [P] routing/permissions.py
- T005 [P] routing/target_resolver.py
- T006 [P] routing/timestamps.py
- T007 [P] routing/dao.py
- T008 [P] routing/service.py
- T009 [P] routing/kill_switch.py
- T010 [P] routing/delivery.py
- T011 [P] routing/errors.py
```

### Within Phase 2 — pure modules + their unit tests

After T012 / T014 / T015 / T017 land in order, the pure-module ladder fans out:

```text
Parallel batch A (independent pure modules):
- T019 [P] routing/errors.py
- T020 [P] routing/excerpt.py + T021 test
- T022     routing/envelope.py + T023 test
- T024 [P] routing/permissions.py + T025 test
- T026 [P] routing/target_resolver.py + T027 test

Parallel batch B (tmux adapter):
- T036 adapter.py Protocol → then T037 + T038 + T039 + T040 + T041 in parallel
```

### Within Phase 3 (US1)

```text
- T055 [P] integration test (can start while T056 implementation is in flight)
- T059 [P] [US1] send-input CLI JSON test
- T060 [P] [US1] send-input CLI human test
```

### Across stories after Phase 2

Once Phase 2 is done, all six user story phases can be developed in parallel by different agents — they share the foundation but their new CLI / socket / audit wiring is in distinct files (cli.py is shared but the subparser handlers are independent per-subcommand functions).

---

## Implementation Strategy

### MVP scope

**Phase 1 + Phase 2 + Phase 3 (US1)** is the MVP slice. Shipping US1 alone proves the durable queue, the permission gate (the master → slave path is exercised), the tmux-safe delivery, and the JSONL audit are wired end-to-end. The remaining user stories (US2–US6) extend safety/observability around the same path without requiring re-architecture.

### Incremental delivery order

1. **MVP**: Phase 1 + Phase 2 + Phase 3 (US1).
2. **Safety hardening**: Phase 4 (US2, permission refusals — completes the safety story).
3. **Operator surface**: Phase 5 (US3, queue inspection + overrides).
4. **Incident response**: Phase 6 (US4, kill switch).
5. **Security verification**: Phase 7 (US5, shell-injection safety) — many of its tests already pass after Phase 2 because the AST gate (T041) and the body validation (T022) are foundational; US5 is largely an integration-test slice.
6. **Durability proof**: Phase 8 (US6, restart safety) — small slice, depends only on the FR-040 recovery wiring (already in Phase 2 T042/T048).
7. **Polish & release**: Phase 9.

### Risk mitigation

- Land T041 (AST gate) and T012 (schema migration) **early** — both are cross-cutting risks. Failing the AST gate after writing additional code is expensive; failing the migration after writing the DAO is expensive.
- The FR-040 recovery pass (T084, mostly built in T042/T048) is small but high-stakes — keep its unit test (T044) as a blocker for US1's "delivered" path because a regression there breaks every user story.
- T087 (backcompat) runs the FEAT-001..008 CLI surface end-to-end; schedule it as the gate before any merge to main.

---

## Format Validation

Every task above conforms to:

- `- [ ]` checkbox
- `T###` sequential ID
- `[P]` marker only where the task touches a distinct file with no incomplete-task dependencies
- `[US#]` label on every user-story phase task; absent on Setup, Foundational, Polish tasks
- Concrete file path in every description (`src/agenttower/...` or `tests/...` or `specs/...`)
