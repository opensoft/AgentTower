---
description: "Task list for FEAT-010 Event-Driven Routing and Multi-Master Arbitration"
---

# Tasks: Event-Driven Routing and Multi-Master Arbitration

**Branch**: `010-event-routes-arbitration`
**Input**: Design documents from `specs/010-event-routes-arbitration/`
**Prerequisites**: spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md
**Tests**: Tests are INCLUDED — the spec carries 7 Independent Test scenarios (one per user story) plus 10 measurable Success Criteria. Constitution Principle IV ("Observable and Scriptable") + Development Workflow ("broader tests for daemon state, socket protocol, permissions, input delivery") justify a test-included workflow.
**Organization**: Tasks are grouped by user story; within each story tests come before implementation; parallel-safe tasks are marked `[P]`.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1..US7)
- Every task includes an exact file path

## Path Conventions

Single project layout (per plan.md §Project Structure):
- Source: `src/agenttower/`
- Tests: `tests/{unit,contract,integration}/`
- Specs: `specs/010-event-routes-arbitration/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the daemon-development baseline is intact. FEAT-001..009 already shipped, so setup is minimal — no new third-party dependency, no new top-level directory.

- [X] T001 Verify `pyproject.toml` at repo root pins `requires-python>=3.11` and lists no FEAT-010-specific new runtime dependency (stdlib-only constraint per plan.md Technical Context).
- [X] T002 [P] Confirm `tests/conftest.py` exposes the FEAT-009 shared fixtures (`bench_test_container`, `daemon_under_test`, `tmp_state_db`) that FEAT-010 integration tests will reuse; document any extension needed in `tests/conftest.py` comments.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema migration + error vocabulary + DAOs + audit-emit primitives that EVERY user story depends on. No user-story work begins until this phase passes.

**CRITICAL**: T003 (schema v8) blocks every other FEAT-010 SQLite touch. T005 (route_errors.py) blocks every module that raises a closed-set error.

- [X] T003 Add `_apply_migration_v8(conn)` to `src/agenttower/state/schema.py` per data-model.md §3 (CREATE TABLE routes + idempotent ALTER message_queue + partial UNIQUE index + UPDATE schema_version); bump `CURRENT_SCHEMA_VERSION = 8`.
- [X] T004 [P] Add `tests/unit/test_schema_migration_v8.py` covering: cold-create-at-v8 succeeds, upgrade-from-v7 succeeds, idempotent re-apply succeeds (interrupted-migration scenario), `PRAGMA table_info(message_queue)` shows three new columns with correct types/defaults, partial UNIQUE index exists with `WHERE origin='route'` predicate.
- [X] T005 Create `src/agenttower/routing/route_errors.py` with the closed-set vocabulary per `contracts/error-codes.md` §1–§4: 7 CLI error code constants (`ROUTE_ID_NOT_FOUND`, `ROUTE_EVENT_TYPE_INVALID`, `ROUTE_TARGET_RULE_INVALID`, `ROUTE_MASTER_RULE_INVALID`, `ROUTE_TEMPLATE_INVALID`, `ROUTE_SOURCE_SCOPE_INVALID`, `ROUTE_CREATION_FAILED`), 10 skip-reason constants, 5 sub-reason constants, 4 internal-error constants; define `RouteError` exception hierarchy (RouteIdNotFound, RouteEventTypeInvalid, etc.) for type-safe raising.
- [X] T006 [P] Add `tests/unit/test_routing_route_errors.py` asserting every constant has a stable string value, no collision with FEAT-001..009 codes, and the integer registry mapping (via `socket_api/errors.py`) round-trips.
- [X] T007 Create `src/agenttower/routing/routes_dao.py` with `RouteRow` frozen dataclass + pure CRUD functions (`insert_route`, `list_routes`, `select_route`, `update_enabled`, `delete_route`, `advance_cursor`) per plan.md §1; callers open `BEGIN IMMEDIATE` — DAO functions never start a transaction.
- [X] T008 [P] Add `tests/unit/test_routing_routes_dao.py` covering: insert returns route_id, list ordered by `(created_at ASC, route_id ASC)`, select returns None on miss, update_enabled returns False on no-op (FR-009 idempotent), delete returns False on miss, advance_cursor is monotonic, all queries parameterized.
- [X] T009 Extend `src/agenttower/routing/dao.py`: add `origin`, `route_id`, `event_id` to the `QueueRow` dataclass with sensible defaults; update INSERT and SELECT statements to include the three new columns; existing direct-send insert sites pass `('direct', None, None)`.
- [X] T010 [P] Extend `tests/unit/test_routing_dao.py` with new-column round-trip tests; verify backward-compat for rows inserted under schema v7.
- [X] T011 Extend `src/agenttower/routing/audit_writer.py`: add the six new event types (`route_matched`, `route_skipped`, `route_created`, `route_updated`, `route_deleted`, `routing_worker_heartbeat`) to the `KNOWN_EVENT_TYPES` set; no behavior change.
- [X] T012 Create `src/agenttower/routing/routes_audit.py` with one emit function per audit type (`emit_route_matched`, `emit_route_skipped`, `emit_route_created`, `emit_route_updated`, `emit_route_deleted`, `emit_routing_worker_heartbeat`); build the JSONL envelope per `contracts/routes-audit-schema.md` and hand off to `events.writer.append_event`; on append failure, push to bounded `collections.deque(maxlen=10_000)` retry buffer per research.md §R14. Expose `has_pending() -> bool` (returns `len(_pending_audit_buffer) > 0`) — read by `status` socket handler in T055 to compute the `degraded_routing_audit_persistence` flag per data-model.md §4-§5.

**Checkpoint**: Schema v8 in place; routes table CRUDable; audit emit primitives ready; error vocabulary frozen. User-story work can now begin.

---

## Phase 3: User Story 1 — Route fires on matching event, prompt delivered (Priority: P1)

**Goal**: Operator-created route subscribing to `waiting_for_input` events fires within one daemon cycle, deterministically picks a master, renders a template, enqueues a route-tagged FEAT-009 row, and delivers through the existing tmux paste path. Full chain visible in `events.jsonl`.

**Independent Test** (from spec §Story 1): With FEAT-001..009 plus T003-T012 in place, register one active master + one active slave, manually `INSERT` one route row, trigger a `waiting_for_input` event on the slave's log; within one daemon cycle verify (a) exactly one queue row with `origin=route`, `route_id`, `event_id`, (b) `agenttower queue --origin route` lists it (requires US5 — for US1 isolation, query SQLite directly), (c) slave's tmux pane received the rendered envelope, (d) `events.jsonl` contains event → `route_matched` → `queue_message_enqueued` → `queue_message_delivered` in order.

### Tests for User Story 1

> Write these tests FIRST and confirm they FAIL before implementing T018-T024.

- [ ] T013 [P] [US1] Create `tests/unit/test_routing_source_scope.py` covering `parse_source_scope_value`: `kind=any` → NULL value, `kind=agent_id` → `agt_*` validated, `kind=role` → grammar parsing of `role:<r>[,capability:<c>]`, invalid kinds raise `RouteSourceScopeInvalid`. Also test `matches(parsed, event_source_role, event_source_capability, event_source_agent_id)` with role-only match, role+capability match, capability-mismatch rejection.
- [ ] T014 [P] [US1] Create `tests/unit/test_routing_template.py` covering `validate_template_string` (allowed/disallowed fields, double-brace literal escape) and `render_template` (every whitelisted field substituted, `{event_excerpt}` routed through `routing.excerpt.render_excerpt` with FEAT-007 redaction, output is UTF-8 bytes, body validation tie-in raises `RouteTemplateRenderError` with sub-reasons).
- [ ] T015 [P] [US1] Create `tests/unit/test_routing_arbitration.py` covering `pick_master`: `master_rule=auto` with N≥2 masters picks lex-lowest (FR-017), `master_rule=auto` with 0 masters returns `MasterSkip(no_eligible_master)`, `master_rule=explicit` returns `MasterWon` when active, `MasterSkip(master_inactive)` when registered-but-inactive, `MasterSkip(master_not_found)` when no registry record.
- [ ] T016 [P] [US1] Create `tests/unit/test_routing_worker.py` covering: cycle iterates routes in `(created_at, route_id)` order (FR-042); per-event `BEGIN IMMEDIATE` transaction encloses cursor-advance + queue-insert atomically (FR-012); transient SQLite-lock error rolls back without cursor advance (FR-013); shutdown_event mid-cycle exits at next event boundary; in-flight `route disable` between batch events stops processing for that route (Risk Register §1).
- [ ] T017 [P] [US1] Create `tests/contract/test_route_audit_schema.py` covering JSONL schema for `route_matched` and `route_skipped` per `contracts/routes-audit-schema.md`: required fields, nullability rules for `winner_master_agent_id` / `target_agent_id` / `target_label` per skip reason, sub_reason populated only for `template_render_error`, redacted excerpt cap of 240 chars.
- [ ] T018 [P] [US1] Create `tests/integration/test_routing_end_to_end.py::test_story1_happy_path` reproducing the spec's Story 1 Independent Test against the bench-container fixture.

### Implementation for User Story 1

- [ ] T019 [US1] Create `src/agenttower/routing/source_scope.py`: `ParsedSourceScope` frozen dataclass + `parse_source_scope_value(raw, kind) -> ParsedSourceScope` + `matches(parsed, event_source_role, event_source_capability, event_source_agent_id) -> bool` per plan.md §1; raise `RouteSourceScopeInvalid` on bad input.
- [ ] T020 [US1] Extract `_parse_role_capability(raw: str) -> tuple[str, str | None]` to a shared helper used by BOTH `source_scope.py` and `src/agenttower/routing/target_resolver.py`; refactor `target_resolver.py` `target_rule=role` path to call the shared helper (Clarifications Q1 + research.md §R3).
- [ ] T021 [US1] Create `src/agenttower/routing/template.py`: `validate_template_string(template) -> list[str]` + `render_template(template, event, *, redactor) -> bytes` per plan.md §1; substitute placeholders, route `{event_excerpt}` through `routing.excerpt.render_excerpt`, encode UTF-8, run FEAT-009 `envelope.validate_body_bytes`, map body-validation exceptions to `RouteTemplateRenderError(reason='template_render_error', sub_reason=...)` per contracts/error-codes.md §3.
- [ ] T022 [US1] Create `src/agenttower/routing/arbitration.py`: `ArbitrationResult` (MasterWon | MasterSkip) + `pick_master(*, master_rule, master_value, active_masters) -> ArbitrationResult` per plan.md §1; pure function — no SQLite, no I/O — caller passes the snapshot.
- [ ] T023 [US1] Extend `src/agenttower/routing/service.py` `QueueService`: add `_origin: Literal['direct','route']='direct'`, `_route_id: str | None = None`, `_event_id: int | None = None` as keyword-only args on `send_input`; add new public method `enqueue_route_message(*, envelope, sender, target, route_id, event_id) -> ...` that calls the same internal helper with `_origin='route'`; ensure the socket dispatcher for `queue.send_input` does NOT forward the underscore-prefixed args (research.md §R7).
- [ ] T024 [US1] Create `src/agenttower/routing/worker.py`: `RoutingWorker(conn_factory, agents_service, queue_service, audit_emitter, clock, shutdown_event, *, cycle_interval, batch_size)` per plan.md §1; implement `run()` single-threaded sequential loop sorting routes by `(created_at, route_id)`; implement `_process_route_batch(route)` opening `BEGIN IMMEDIATE` per event, calling `arbitration.pick_master` → target resolution → `template.render_template` → `queue_service.enqueue_route_message`, advancing cursor in same transaction; map FEAT-009 exceptions to skip reasons per `contracts/error-codes.md` §5; treat `KillSwitchOff` as enqueue-with-blocked NOT a skip (Story 5 #1, FR-032); maintain in-memory `_SharedRoutingState` counters under `threading.Lock` per data-model.md §4; set `_SharedRoutingState.routing_worker_degraded=True` on transient internal error (SQLite lock, `RoutingDegraded`) and clear it on the next successful cycle (FR-051); read fault-injection env var `_AGENTTOWER_FAULT_INJECT_ROUTING_TXN_ABORT` per research.md §R16 (production builds: env var unset → no-op).
- [ ] T025 [US1] Extend `src/agenttower/routing/daemon_adapters.py` `start_daemon`: after the FEAT-009 delivery-worker spawn, spawn `RoutingWorker.run()` on a daemon thread; on shutdown signal set the worker's `Event` and join with a timeout that is a small multiple of `cycle_interval`.

**Checkpoint**: US1 fully functional in isolation — routes inserted via direct SQL fire deterministically and deliver via FEAT-009. (Note: the spec's Story 1 IT references `agenttower queue --origin route` which is implemented in US5; for US1-isolation verification, query SQLite directly for the route-tagged row. Full IT replay including the `--origin route` filter requires US5 to ship — see Phase 7 checkpoint.)

---

## Phase 4: User Story 2 — Operator manages route catalog from CLI (Priority: P1)

**Goal**: `agenttower route add|list|show|remove|enable|disable` deliver durable, JSON-stable CRUD over the routes table with audit-stamped catalog events; new routes default to `last_consumed_event_id = MAX(events.event_id)` so historical events never replay.

**Independent Test** (spec §Story 2): `route add` → `route list --json` → `route show <id> --json` → `route disable` → `route enable` → `route remove`. Verify exit codes, JSON shapes per `contracts/cli-routes.md`, audit emission, and FR-002 cursor-at-creation behavior.

### Tests for User Story 2

- [ ] T026 [P] [US2] Create `tests/unit/test_routing_routes_service.py` covering `add_route` validation order (FR-005 → FR-007 → FR-006 → source-scope → FR-008 per research.md §R15), `last_consumed_event_id` initialization to `MAX(events.event_id) OR 0`, `route_id` UUIDv4 generation, audit emit per CRUD op, FR-009 idempotency on enable/disable.
- [ ] T027 [P] [US2] Create `tests/contract/test_socket_routes.py` covering all 6 `routes.*` socket methods per `contracts/socket-routes.md`: request/response envelope shape, error envelope shape, every closed-set error code emitted under matching input.
- [ ] T028 [P] [US2] Create `tests/contract/test_cli_routes.py` covering all 6 `agenttower route` subcommands per `contracts/cli-routes.md`: exit codes, `--json` shape, human-format one-line summary, validation rejection paths.

### Implementation for User Story 2

- [ ] T029 [US2] Create `src/agenttower/routing/routes_service.py`: `add_route`, `remove_route`, `enable_route`, `disable_route`, `list_routes`, `show_route` orchestrating `routes_dao` + `routes_audit`; `add_route` runs validation in research.md §R15 order; `enable_route`/`disable_route` are idempotent — return state-changed flag, audit emit only on actual flip (FR-009); `show_route` includes `runtime` sub-object (events_consumed, last_skip_reason, last_skip_at, last_routing_cycle_at) per `contracts/cli-routes.md` §3.
- [ ] T030 [US2] Extend `src/agenttower/socket_api/server.py`: register 6 new method handlers under `routes.*` namespace per `contracts/socket-routes.md` (`routes.add`, `routes.list`, `routes.show`, `routes.remove`, `routes.enable`, `routes.disable`); map `RouteError` exceptions to closed-set CLI codes from `route_errors.py`; capture `created_by_agent_id` from FEAT-005 caller-context headers (host CLI → `host-operator`; bench-container → `agt_*`).
- [ ] T031 [US2] Create `src/agenttower/routing/cli_routes.py`: argparse subparsers for `route add|list|show|remove|enable|disable` per `contracts/cli-routes.md` flag tables; each subcommand calls the matching `socket_api/client` method, formats response (human + `--json` to stdout), prints errors as `error: <code>: <message>` to stderr, exits with the documented code.
- [ ] T032 [US2] Extend `src/agenttower/cli.py`: register `cli_routes.register(subparsers)` for the `route` subgroup; add `agenttower route` help text noting that route updates require `remove` + `add` (FR-009a per Clarifications Q5).

**Checkpoint**: US1 + US2 together form the **MVP** — operator can create routes via CLI, the worker fires them, FEAT-009 delivers them, and the chain is auditable.

---

## Phase 5: User Story 3 — Multi-master arbitration is deterministic (Priority: P2)

**Goal**: With N≥2 active masters, every fire deterministically picks the lex-lowest `agent_id`; when no master is eligible, skip with closed-set reason and advance the cursor. Identical input → identical winner across daemon restarts (SC-002, SC-010).

**Independent Test** (spec §Story 3): Register 3 masters `agt_aaa…`, `agt_bbb…`, `agt_ccc…`; fire 10 matching events → all 10 queue rows have `sender.agent_id=agt_aaa…`. Deactivate `agt_aaa…`; one more fire → row uses `agt_bbb…`. Deactivate `agt_bbb…` and `agt_ccc…`; one more fire → `route_skipped(no_eligible_master)`, cursor advanced, no queue row. Replay on fresh daemon → byte-identical outcomes.

### Tests for User Story 3

- [ ] T033 [P] [US3] Extend `tests/unit/test_routing_arbitration.py` with lex-lowest tie-break tests at N=2, N=3, N=5 active masters; verify 100% selection over N=100 simulated fires (SC-002 measurability).
- [ ] T034 [P] [US3] Create `tests/integration/test_routing_arbitration_determinism.py` reproducing the spec's Story 3 Independent Test against the bench-container fixture; include the freshly-restarted daemon replay variant (SC-010 for arbitration).

### Implementation for User Story 3

- [ ] T035 [US3] Confirm `arbitration.py` (T022) implements the lex-lowest tie-break as `sorted(active_masters, key=lambda a: a.agent_id)[0]` (NOT `min(...)`, NOT a streaming-min, NOT a stable-sort dependency) — this is the implementation pattern that satisfies SC-002's 100% determinism contract over N=100 fires; add an explicit code comment citing FR-017 + SC-002.
- [ ] T036 [US3] Confirm `routes_audit.emit_route_skipped` (T012) populates `winner_master_agent_id=null`, `target_agent_id=null`, `target_label=null`, `reason='no_eligible_master'` for the FR-018 arbitration-failure path (Clarifications Q2). Add an explicit unit-test case `test_emit_route_skipped_no_eligible_master_null_fields` in `tests/unit/test_routing_audit.py` asserting all three null fields appear in the JSONL envelope.

**Checkpoint**: Arbitration determinism gated by automated tests; SC-002 and SC-003 measurable from CLI output.

---

## Phase 6: User Story 4 — Restart and crash safety, no duplicate routing (Priority: P2)

**Goal**: Cursor-advance-with-enqueue atomicity (FR-012) + UNIQUE `(route_id, event_id)` partial index (FR-030) eliminate duplicate-routing windows. After N fault-injected mid-transaction crashes, the count of `queue_message_enqueued` audit entries per `(route_id, event_id)` pair is exactly 1 (SC-004).

**Independent Test** (spec §Story 4): Submit N matching events; stop daemon mid-cycle using fault-injection hook; restart; verify (a) cursor reflects only fully-committed prior cycles, (b) no duplicate queue rows per `(route_id, event_id)`, (c) audit-entry count per pair is exactly 1.

### Tests for User Story 4

- [ ] T037 [P] [US4] Create `tests/integration/test_routing_crash_recovery.py` reproducing the spec's Story 4 Independent Test: fault-inject after BEGIN before COMMIT; fault-inject after COMMIT but before next-cycle wake; fault-inject during the second of N events in a batch; verify UNIQUE constraint as defense-in-depth fires only under deliberately-induced double-insert.
- [ ] T038 [P] [US4] Extend `tests/unit/test_routing_worker.py` with explicit transaction-rollback path tests: SQLite `OperationalError(database is locked)` → cursor stays at previous value, route remains in next-cycle queue, degraded flag flips for that cycle and clears on next-successful cycle.

### Implementation for User Story 4

- [ ] T039 [US4] Implement the fault-injection hook in `worker.py` per the contract documented in `research.md §R16` (env var `_AGENTTOWER_FAULT_INJECT_ROUTING_TXN_ABORT` with values `before_commit` | `after_commit`; raises `SystemExit(137)` at the specified point; no-op when env var unset). The contract is already pinned in research.md; this task is the implementation only.
- [ ] T040 [US4] Verify the `idx_message_queue_route_event` partial UNIQUE index actually fires on attempted double-insert by writing a test in `tests/unit/test_routing_dao.py` that deliberately calls the insert helper twice with identical `(route_id, event_id)` and asserts `sqlite3.IntegrityError`; map the exception to `RoutingDuplicateInsert` per `contracts/error-codes.md` §4.
- [ ] T040a [P] [US4] Add `tests/integration/test_routing_event_purge_between_cycles.py` reproducing the spec Edge Case "FEAT-008 event table has been wiped between routing cycles": insert events 1..N, set `last_consumed_event_id=5`, delete events with `event_id < 100`, run one routing cycle, assert no exception is raised AND the next `event_id > 5` available is processed normally AND the cursor advances forward from that point (spec §Edge Cases).

**Checkpoint**: SC-004 measurable; duplicate-routing safety gated by automated tests; events-purged-below-cursor edge case validated.

---

## Phase 7: User Story 5 — FEAT-009 surface reuse (kill switch, queue, audit) (Priority: P2)

**Goal**: Route-generated rows traverse FEAT-009 plumbing unchanged. Kill-switch-off route fires produce blocked rows (NOT skips), cursor still advances. `agenttower queue --origin route` exposes route-tagged rows. SC-005: 100% of kill-switched route rows land in `blocked` AND cursor advances.

**Independent Test** (spec §Story 5): `agenttower routing disable`; create route; trigger matching event; verify (a) queue row exists with `state=blocked`, `block_reason=kill_switch_off`, `origin=route`, (b) no tmux delivery, (c) cursor advanced, (d) `agenttower queue --origin route` shows row. Re-enable, approve, verify transition to `delivered`.

### Tests for User Story 5

- [ ] T041 [P] [US5] Create `tests/contract/test_cli_queue_origin_filter.py` covering `--origin direct|route|<absent>|<invalid>` per `contracts/cli-queue-origin.md`: filter behavior, JSON shape extension (origin/route_id/event_id present on every row), `queue_origin_invalid` exit code.
- [ ] T042 [P] [US5] Extend `tests/integration/test_routing_end_to_end.py` with `test_story5_kill_switch_off_route_blocks` reproducing the spec's Story 5 Independent Test; assert SC-005 100% threshold (every fire under kill-switch-off → blocked + cursor-advance).

### Implementation for User Story 5

- [ ] T043 [US5] Extend `src/agenttower/routing/service.py` `QueueService.list_queue`: add `origin_filter: Literal['direct','route'] | None = None` kw arg; modify SELECT to `WHERE (:origin_filter IS NULL OR origin = :origin_filter) ORDER BY enqueued_at, message_id`.
- [ ] T044 [US5] Extend `src/agenttower/cli.py` queue subparser: add `--origin {direct,route}` flag; pass through to `queue.list` socket method's new `origin_filter` parameter; reject other values with `queue_origin_invalid` exit code per `contracts/cli-queue-origin.md`.
- [ ] T045 [US5] Extend the human-format `agenttower queue` table in `cli.py` to include `ORIGIN`, `ROUTE_ID`, `EVENT_ID` columns (truncated/dashed for direct rows) per `contracts/cli-queue-origin.md` "Human-format output" section.
- [ ] T045a [P] [US5] Add `tests/integration/test_routing_end_to_end.py::test_route_row_approve_delay_cancel` covering FR-034: create a route, trigger an event under kill-switch-off (row lands `blocked`), then exercise `agenttower queue approve <id>` / `queue delay <id>` / `queue cancel <id>` on the route-generated row; assert each transition succeeds identically to a direct-send row (same audit shape, same exit code, same JSON), with only `origin`/`route_id`/`event_id` differing in the audit envelope.

**Checkpoint**: US5 closes the FEAT-009-reuse loop; route-tagged rows behave identically to direct rows under all FEAT-009 operations (listing AND operator-action paths covered).

---

## Phase 8: User Story 6 — Conservative template rendering with redaction (Priority: P3)

**Goal**: Closed-whitelist `{field}` substitution, FEAT-007 redaction applied to `{event_excerpt}` only, FEAT-009 body validation surfaces as `template_render_error` with `sub_reason`. No template grammar beyond the whitelist (no nested interpolation, no expressions, no function calls).

**Independent Test** (spec §Story 6): Create routes whose templates use each whitelisted field; trigger events whose excerpts contain redactable patterns (e.g., `GITHUB_TOKEN=abcdef…`); verify rendered envelope substitutes fields correctly AND excerpt portion is redacted. Also create routes with templates referencing unknown fields — verify they fail at `route add`, not at fire time.

### Tests for User Story 6

- [ ] T046 [P] [US6] Extend `tests/unit/test_routing_template.py` with: every whitelisted field substitutes correctly; redactable pattern in event excerpt produces redacted body (not raw); template referencing unknown field rejected at `validate_template_string` time; body_empty/body_invalid_chars/body_invalid_encoding/body_too_large sub-reason mapping per `contracts/error-codes.md` §3.
- [ ] T047 [P] [US6] Extend `tests/integration/test_routing_end_to_end.py` with `test_story6_template_render_failure` covering oversized-render → `route_skipped(template_render_error, sub_reason=body_too_large)` + cursor-advance + no queue row.

### Implementation for User Story 6

- [ ] T048 [US6] Refine `src/agenttower/routing/template.py` `render_template` to ensure redaction is applied to `{event_excerpt}` BEFORE substitution (FR-026) by calling `routing.excerpt.render_excerpt(event.event_excerpt, redactor=logs.redaction.redact_one_line)`; verify other 7 whitelisted fields are raw-pass per FR-008 (operator-controlled or daemon-generated).
- [ ] T049 [US6] Wire FEAT-009 body-validation exceptions to `RouteTemplateRenderError` sub-reasons in `template.py`: catch `BodyEmpty`, `BodyInvalidChars`, `BodyInvalidEncoding`, `BodyTooLarge` from `envelope.validate_body_bytes` and re-raise with matching sub_reason string per `contracts/error-codes.md` §3.

**Checkpoint**: US6 hardens the data-crossing-trust-boundary surface; security.md §Template-Injection Safety items become testable.

---

## Phase 9: User Story 7 — Routing surface visible in `agenttower status` (Priority: P3)

**Goal**: `agenttower status --json` carries a top-level `routing` object exposing `routes_total`, `routes_enabled`, `routes_disabled`, `last_routing_cycle_at`, `events_consumed_total`, `skips_by_reason`, `most_stalled_route`, `routing_worker_degraded`. Heartbeat thread emits `routing_worker_heartbeat` JSONL every interval (default 60s, bounds `[10, 3600]`).

**Independent Test** (spec §Story 7): Run `agenttower status --json` on freshly-started daemon (zero routes), after creating routes, and after disabling routes; verify routing section appears with expected counts in each case.

### Tests for User Story 7

- [ ] T050 [P] [US7] Create `tests/contract/test_cli_status_routing.py` covering `agenttower status --json` `routing` section per `contracts/cli-status-routing.md`: field set, types, FEAT-009-kill-switch-merge under same `routing` object, `most_stalled_route` null vs object, sparse `skips_by_reason` map.
- [ ] T051 [P] [US7] Create `tests/unit/test_routing_heartbeat.py` covering: heartbeat fires at `interval_seconds` cadence (not before first interval elapses — no startup beacon per FR-039a); counter snapshot+reset is atomic under shared lock; `degraded` field in the emitted JSONL entry mirrors `_SharedRoutingState.routing_worker_degraded`; shutdown_event short-circuits the sleep.

### Implementation for User Story 7

- [ ] T052 [US7] Create `src/agenttower/routing/heartbeat.py`: `HeartbeatEmitter(audit_emitter, shared_state, clock, shutdown_event, *, interval_seconds)` class per plan.md §1; `run()` loops sleep-snapshot-reset-emit until shutdown; first emission one full interval after thread start; emit via `routes_audit.emit_routing_worker_heartbeat` with `degraded` field copied from `shared_state.routing_worker_degraded` under `shared_state.lock`.
- [ ] T053 [US7] Define `_SharedRoutingState` dataclass per data-model.md §4 in `src/agenttower/routing/worker.py` (or a new `_shared_state.py` if it grows) with fields per data-model.md §4: `cycles_since_last_heartbeat`, `events_consumed_since_last_heartbeat`, `skips_since_last_heartbeat`, `events_consumed_total`, `skips_by_reason`, `last_routing_cycle_at`, `routing_worker_degraded`, `audit_buffer_dropped`, `lock`. Ensure `worker.py` mutates and `heartbeat.py` reads-and-resets under the same `threading.Lock`.
- [ ] T054 [US7] Extend `src/agenttower/routing/daemon_adapters.py`: after the routing worker spawn, spawn `HeartbeatEmitter.run()` on a daemon thread; pass the shared state object (which carries its own `lock` plus `routing_worker_degraded` flag) from the routing worker; on shutdown signal set both Events and join both threads with bounded timeout.
- [ ] T055 [US7] Extend the existing `status` socket method handler in `src/agenttower/socket_api/server.py`: add the `routing` sub-object per `contracts/cli-status-routing.md` carrying TWO INDEPENDENT degraded signals — (a) `routing_worker_degraded` read from `_SharedRoutingState.routing_worker_degraded` under `lock`; (b) `degraded_routing_audit_persistence` derived at read time from `routes_audit.has_pending()` (T012 exposed helper); plus `routes_total`/`routes_enabled`/`routes_disabled` from a `SELECT COUNT(*) ... GROUP BY enabled` over `routes`; plus `most_stalled_route` from T056; plus `events_consumed_total`, `skips_by_reason`, `last_routing_cycle_at` from `_SharedRoutingState`. Merge with FEAT-009's existing `routing.enabled` field under the same `routing` JSON object per "Backward compatibility" section.
- [ ] T056 [US7] Implement `most_stalled_route` lag computation in `src/agenttower/routing/routes_service.py` `compute_most_stalled(conn) -> StalledRoute | None`: query each enabled route, count `events WHERE event_id > cursor AND event_type = route.event_type` (use indexed scan), return the row with largest lag; tie-break by `(created_at, route_id)`; return None if all lags are 0.
- [ ] T057 [US7] Extend `src/agenttower/cli.py` `status` subparser: format the `routing` section in human + `--json` output per `contracts/cli-status-routing.md` "Human-format output" example.

**Checkpoint**: US7 closes the observability loop; `agenttower status --json` is the operator's single-pane-of-glass surface for routing health.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, AST invariants, final regression check. No new feature surface.

- [ ] T058 [P] Create `tests/unit/test_no_per_cycle_audit_calls.py` — AST test that walks `src/agenttower/routing/worker.py` and asserts the only `append_event` (or `emit_*`) calls in the worker's hot path are for the five per-(route, event) and per-route-lifecycle types; no `routing_cycle_started` / `routing_cycle_completed` may appear (Clarifications Q3 / FR-035 / `contracts/routes-audit-schema.md` §AST-test invariant).
- [ ] T059 [P] Add module docstrings to every new file in `src/agenttower/routing/` (`route_errors.py`, `routes_dao.py`, `routes_service.py`, `source_scope.py`, `template.py`, `arbitration.py`, `worker.py`, `heartbeat.py`, `routes_audit.py`, `cli_routes.py`) — one paragraph per module summarizing responsibility and citing the relevant FR numbers.
- [ ] T060 [P] Update `docs/architecture.md` with a "FEAT-010: Event-Driven Routing" section linking to the spec, plan, and quickstart; note the routing worker / heartbeat threads as new daemon-internal components.
- [ ] T061 [P] Update `docs/mvp-feature-sequence.md` to mark the event-routing + arbitration half of FEAT-010 as shipped; restate that swarm-member parsing and the operator-facing arbitration prompt remain deferred (spec Assumptions section).
- [ ] T062 Manually run the `quickstart.md` §1–§5 operator path end-to-end against a fresh `agenttowerd` build (smoke test); record any deviation in a comment at the top of `quickstart.md`.
- [ ] T063 Run the full `pytest` suite (`pytest tests/`); confirm zero FEAT-001..009 regressions; confirm all new FEAT-010 tests pass; capture test-count delta in the PR description.
- [ ] T063a [P] Create `tests/unit/test_scope_boundary_invariants.py` — AST + import scans enforcing FR-052 / FR-053 / FR-054 negative requirements across the ENTIRE `src/agenttower/routing/` package (not just `worker.py` and `heartbeat.py`). Assertions: NO `asyncio`, NO `concurrent.futures`, NO `threading.Timer` anywhere in `src/agenttower/routing/*.py` (FR-052: no non-event triggers beyond the explicit interval-based worker + heartbeat); NO `openai`, `anthropic`, `langchain`, `httpx` to LLM endpoints (FR-053: no model-based decisions); NO `tkinter`, `fastapi`, `flask`, `starlette`, `uvicorn`, `pywebview`, `pync`, `notify2`, `dbus` (FR-054: no TUI / web UI / notification surface). One assertion per FR with a descriptive failure message citing the spec FR number.
- [ ] T063b [P] Create `tests/performance/test_routing_slos.py` — measurable assertions for the four perf SCs: SC-001 (event-to-paste end-to-end ≤ 5s under the "typical local conditions" definition in spec Assumptions), SC-006 (`agenttower route list --json` at 1000-route fixture < 500ms), SC-007 (`agenttower route add` validation rejection < 100ms cold-start and warm), SC-009 (disabled route accumulates a fixed backlog of 1000 matching events; after re-enable, the backlog drains in `ceil(1000 / batch_size) = 10` cycles at the default `batch_size=100` — wall-clock duration of the disabled period is not part of the criterion). Each test fails with the actual measured value vs threshold for easy triage.

---

## Dependencies & Story Completion Order

```text
Phase 1 (Setup)
  ↓
Phase 2 (Foundational) ── T003..T012 ── BLOCKS all stories
  ↓
  ├── Phase 3 (US1, P1) ── worker pipeline ──┐
  │                                          │
  ├── Phase 4 (US2, P1) ── CRUD + CLI ───────┤
  │     (US2 is technically independent of US1 worker,
  │      but the MVP needs both shipped together)
  │                                          │
  └── (US1 + US2 = MVP ship boundary) ───────┘
                  ↓
  ├── Phase 5 (US3, P2) — depends on Phase 3 (arbitration is part of US1 baseline)
  ├── Phase 6 (US4, P2) — depends on Phase 3 (worker txn semantics)
  ├── Phase 7 (US5, P2) — depends on Phase 3 (worker fires) + Phase 4 (CLI access)
  ├── Phase 8 (US6, P3) — depends on Phase 3 (template called by worker)
  └── Phase 9 (US7, P3) — depends on Phase 3 (shared state populated by worker)
                  ↓
            Phase 10 (Polish)
```

### Per-story parallel-execution opportunities

| Story | Parallel tests | Parallel impls |
|---|---|---|
| US1 | T013, T014, T015, T016, T017, T018 — six test files in parallel | T019 (source_scope) + T021 (template) + T022 (arbitration) — three pure-function modules in parallel |
| US2 | T026, T027, T028 — three test files in parallel | T030 + T031 — server + CLI in parallel (after T029 service exists) |
| US3 | T033, T034 — two test files in parallel | T035, T036 — refinement tasks (mostly verification) |
| US4 | T037, T038, T040a — three test files in parallel | T039 (fault hook) + T040 (UNIQUE verify) — independent |
| US5 | T041, T042, T045a — three test files in parallel | T043 + T044 — service + CLI extensions independent (after T043 lands) |
| US6 | T046, T047 — two test files in parallel | T048 + T049 — same file, sequential |
| US7 | T050, T051 — two test files in parallel | T052 (heartbeat) + T056 (lag query) in parallel; T054, T055, T057 sequential downstream |
| Polish | T058, T059, T060, T061, T063a, T063b — six-way parallel | T062 + T063 sequential at the end |

### Foundational-phase parallelization

T004 (migration test), T006 (errors test), T008 (DAO test), T010 (dao extension test), T012 alone (routes_audit) can run in parallel **after** their respective implementation tasks land (T003 → T004; T005 → T006; T007 → T008; T009 → T010).

The full foundational impl-ordering is: T003 (schema) → T005 (errors) → T007 (routes_dao) → T009 (dao extension) → T011 (audit_writer extension) → T012 (routes_audit). Test tasks T004/T006/T008/T010 fan out in parallel after each impl lands.

---

## Implementation Strategy

**MVP scope** (US1 + US2, Phases 1-4): operator can create a route via CLI, the worker fires it deterministically, FEAT-009 delivers it, and the full chain is auditable. Ship-ready after Phase 4 if you scope MVP tightly.

**Incremental delivery** beyond MVP:
- **Wave 2** (US3 + US4, Phases 5-6): hardening — arbitration determinism + crash safety. No new operator-visible surface, but raises confidence to "deploy to a real bench."
- **Wave 3** (US5, Phase 7): closes the queue-inspection loop so operators can see route-tagged rows via the existing `agenttower queue` CLI without SQL.
- **Wave 4** (US6, Phase 8): conservative template rendering hardening. Already largely covered by US1 baseline; this wave adds the redaction-integration test surface.
- **Wave 5** (US7, Phase 9): observability — `agenttower status` routing section + JSONL heartbeat. Diagnostic, not corrective; lowest priority.
- **Polish** (Phase 10): cross-cutting docs + AST invariant + regression sweep.

Each wave is independently testable and shippable.

---

## Format validation

All 67 tasks above follow the required format: `- [ ]` checkbox + `T0##` ID + optional `[P]` + `[USx]` for story phases + description with explicit file path. Setup/Foundational/Polish phases have no story label per the format spec.

**Task numbering note**: After the 2026-05-16 `/speckit.analyze` remediation pass, 4 tasks were inserted using compound suffix IDs (`T040a` in Phase 6, `T045a` in Phase 7, `T063a` + `T063b` in Phase 10) to avoid renumbering 30+ downstream cross-references. The suffixed IDs preserve execution order within each phase. Total task count: 63 originals + 4 inserted = 67.
