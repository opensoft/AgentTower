# Implementation Plan: Event-Driven Routing and Multi-Master Arbitration

**Branch**: `010-event-routes-arbitration` | **Date**: 2026-05-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/010-event-routes-arbitration/spec.md`

## Summary

FEAT-010 turns the FEAT-008 event stream into a deterministic, auditable
routing layer that feeds the FEAT-009 queue. The work splits into seven
narrow, additive layers — none of them touches a FEAT-001..009 table, file,
or socket method except by extension.

1. **SQLite migration v7 → v8**. One new table — `routes` (one row per
   operator-created subscription, with `last_consumed_event_id` cursor +
   audit-stamp columns) — and three new columns on FEAT-009's existing
   `message_queue` (`origin TEXT NOT NULL DEFAULT 'direct'`,
   `route_id TEXT NULL`, `event_id INTEGER NULL`) plus a partial UNIQUE
   index on `(route_id, event_id) WHERE origin = 'route'`.
   `CURRENT_SCHEMA_VERSION` advances `7 → 8`. The migration backfills
   the `origin` default on every existing row (idempotent under
   `_apply_pending_migrations`) and adds the index AFTER the column add
   so that an interrupted migration is safe to resume.

2. **A `routing/routes_*.py` sub-module set** under
   `src/agenttower/routing/` (the package exists today with
   `service.py`, `dao.py`, `delivery.py`, `target_resolver.py`,
   `excerpt.py`, `kill_switch.py`, `audit_writer.py`, `timestamps.py`,
   `permissions.py`, `errors.py`, `envelope.py`, `daemon_adapters.py`).
   FEAT-010 adds **ten** new sibling modules (`routes_dao.py`,
   `routes_service.py`, `source_scope.py`, `template.py`,
   `arbitration.py`, `worker.py`, `heartbeat.py`, `routes_audit.py`,
   `route_errors.py`, `cli_routes.py`) and extends **four** existing
   modules (`service.py` enqueue path, `audit_writer.py` event types,
   `errors.py` vocabulary, `dao.py` queue-row shape) — see
   Implementation Notes §1. Pure functions where possible (template
   rendering, source-scope parser, arbitration decision, heartbeat
   counter aggregation) so they unit-test without spinning up the
   daemon.

3. **A routing worker thread** in `src/agenttower/routing/worker.py`
   that the daemon starts at boot AFTER the FEAT-009 delivery-worker
   crash-recovery pass. **Single-threaded sequential** per
   Clarifications Session 2026-05-16 Q4 / spec §FR-014 (revised): one
   cycle in flight at a time, routes processed strictly sequentially
   in `(created_at, route_id)` order, one route's batch of up to
   `batch_size` events completes before the next route starts. Cycle
   interval default `1.0`s (bounds `[0.1, 60]`), batch cap default
   `100` (bounds `[1, 10000]`). Uses a `threading.Event` wake-up so
   daemon shutdown stops the worker at the next cycle boundary;
   in-flight transactions commit or roll back atomically (FR-043).

4. **A routing heartbeat thread** in
   `src/agenttower/routing/heartbeat.py` — separate thread from the
   worker, sleeps in `interval_seconds` ticks (default 60s, bounds
   `[10, 3600]`), wakes, snapshots the worker's shared counters
   (under a `threading.Lock`), resets them, and writes one
   `routing_worker_heartbeat` JSONL line. First heartbeat fires one
   full interval after the worker thread enters its loop (no startup
   beacon — see Clarifications Session 2026-05-16 Q3 / spec §FR-039a).

5. **A new CLI surface** — `agenttower route
   add|list|show|remove|enable|disable` — routed through six new
   socket methods (`routes.add`, `routes.list`, `routes.show`,
   `routes.remove`, `routes.enable`, `routes.disable`) over the
   existing FEAT-002 / FEAT-005 thin-client envelope. Validation
   (FR-005..008 + the source-scope parser symmetric with target per
   FR-006 revised) happens at the socket dispatch boundary, before
   any SQLite write. Two existing CLI surfaces gain extensions:
   `agenttower queue --origin <direct|route>` (FR-033) and
   `agenttower status --json` gets a top-level `routing` object
   (FR-038).

6. **Internal enqueue extension**. `routing.service.QueueService`
   already exposes the single path to `message_queue` inserts
   (FR-032 of FEAT-009, restated as FR-032 of FEAT-010). FEAT-010
   adds **one** new public method `enqueue_route_message(...)` that
   takes the same envelope/sender/target trio plus
   `(route_id, event_id)`, runs the identical validation /
   permission / kill-switch / FIFO path, and sets `origin='route'`
   on the resulting row. The existing `send_input(...)` method
   (called from the `queue.send_input` socket method) gains a
   `_origin` keyword-only argument defaulting to `'direct'` so the
   existing socket path is byte-identical. This keeps FEAT-010 from
   inventing a second insert path and preserves the "shell
   metacharacters in body never reach a shell" invariant from
   FEAT-009.

7. **JSONL audit append** to the existing FEAT-008 `events.jsonl`
   stream via the FEAT-001 `events.writer.append_event` helper. Six
   new event types (`route_matched`, `route_skipped`,
   `route_created`, `route_updated`, `route_deleted`,
   `routing_worker_heartbeat`) disjoint from FEAT-008's classifier
   types, FEAT-007 lifecycle types, and FEAT-009's seven
   `queue_message_*` types. SQLite commit happens BEFORE the JSONL
   append; JSONL durability failures buffer in memory (bounded
   10_000-entry `deque`, R14) and retry on the next worker cycle.
   The status surface exposes **two independent degraded signals**:
   `routing_worker_degraded` (mirrors FR-051's worker-internal-error
   condition — a transient SQLite lock or `RoutingDegraded` that
   prevented cursor advance), and `degraded_routing_audit_persistence`
   (mirrors the audit buffer's pending-flush state, derived from
   `has_pending()` at status-read time — mirroring FEAT-008's
   `degraded_events_persistence` and FEAT-009's
   `degraded_queue_audit_persistence`). The two signals are
   independent: a healthy worker may still flag audit-persistence
   degraded if `events.jsonl` is briefly unwritable; a degraded
   worker may have a fully-flushed buffer.

The six locked clarifications from `## Clarifications` shape the
implementation rather than constrain the spec:

- **Q1 (source-scope symmetry)** — `source_scope.py` exposes one
  parser `parse_source_scope_value(raw: str | None, kind: str) ->
  ParsedSourceScope` that is also called from `target_value` parsing
  (via a shared internal helper `_parse_role_capability(raw: str) ->
  tuple[str, str | None]`), so the role+capability grammar lives in
  exactly one place. Matching in `worker.py` checks role-then-
  capability with capability-absence meaning "any capability."
- **Q2 (audit target identity)** — `routes_audit.py` emits
  `route_matched` and `route_skipped` rows with `target_agent_id`
  and `target_label` as first-class top-level fields; both are
  `null` when target resolution never completed (skip reasons
  `no_eligible_master`, `no_eligible_target`).
  `winner_master_agent_id` is null on the same set of arbitration-
  failure skips and populated for every other case.
- **Q3 (heartbeat instead of per-cycle)** — `heartbeat.py` is a
  separate thread on its own interval so a long routing cycle never
  delays a heartbeat (and a long heartbeat I/O never delays a
  routing cycle). The counter-reset is atomic under the shared lock.
- **Q4 (single-threaded sequential)** — `worker.py` has no
  `concurrent.futures` / `multiprocessing` / `asyncio` imports; the
  cycle is a simple `for route in routes_sorted: for event in
  matching_events_batch: ...` loop. Determinism (SC-010) falls out
  for free.
- **Q5 (immutable routes)** — no `routes.update` socket method, no
  `route update` CLI; the spec rejects any in-place edit. Only
  `enable` and `disable` may change an existing row.
- **Clarifications also strengthen FR-049** —
  `route_source_scope_invalid` is added to the closed-set CLI error
  vocabulary; `route_errors.py` exposes it as a module-level
  constant alongside the other six.

The single highest-stakes property FEAT-010 introduces — that a
restart-mid-cycle cannot produce a duplicate `(route_id, event_id)`
queue row — is enforced by two independent mechanisms:

1. **Cursor-advance-with-enqueue atomicity** (FR-012). The cursor
   `UPDATE` and the queue `INSERT` happen in the same
   `BEGIN IMMEDIATE` SQLite transaction. On crash mid-transaction,
   neither side commits; on restart the next cycle re-evaluates the
   in-flight event and produces exactly one row.
2. **`UNIQUE(route_id, event_id) WHERE origin='route'` partial
   index** (FR-030). Defense-in-depth: if a logic bug ever issues a
   second insert for the same pair, SQLite raises `UNIQUE constraint
   failed` and the routing worker surfaces a closed-set internal
   error `routing_duplicate_insert` rather than silently producing a
   duplicate.

The second highest-stakes property is deterministic replay
(SC-010): every per-(route, event) decision is a pure function of
the route row, the event row, and the active-agent snapshot at
evaluation time. Arbitration ties break lexically; target ties
break lexically; route processing order is
`(created_at ASC, route_id ASC)`; per-route event order is
`event_id ASC`. The only non-deterministic surface is the wall-clock
heartbeat timestamp and the heartbeat counters, both of which are
excluded from the SC-010 byte-for-byte comparison.

The CLI surface is intentionally narrow: one new subcommand group
(`agenttower route`) with six subcommands, one new `--origin`
filter flag on the existing `agenttower queue`, and one new
`routing` JSON sub-object on the existing `agenttower status`.
`--json` re-uses a single stable schema across `route add` /
`route list` / `route show` (modulo the array wrapping for `list`
and the `runtime` sub-object addition for `show`).

## Technical Context

**Language/Version**: Python 3.11+ (inherits from FEAT-001..009;
`pyproject.toml` pins `requires-python>=3.11`). No version bump.

**Primary Dependencies**: Standard library only — `sqlite3`
(`routes` table CRUD, `BEGIN IMMEDIATE` for cursor-advance-with-
enqueue, partial UNIQUE index), `uuid` (`uuid.uuid4()` for
`route_id` — spec FR-001 requires UUIDv4 distinct from FEAT-006's
`agt_<12-hex>` agent_id), `threading` (one worker thread + one
heartbeat thread, both `threading.Event`-driven for graceful
shutdown), `time` (`time.monotonic()` for the worker sleep clock;
`time.time()` is forbidden inside the worker hot path — reuses
FEAT-008's `Clock` Protocol test seam), `datetime` (canonical
ISO-8601-ms-UTC via the existing FEAT-009
`routing.timestamps.now_iso_ms_utc`), `re` (no new regex; reuses
FEAT-006's `AGENT_ID_RE` for source-scope agent_id validation),
`dataclasses`, `typing`, `json`, `argparse` (CLI).

**Reuses verbatim**:
- FEAT-001 `events.writer.append_event` for the six new JSONL event
  types (FR-035, FR-039a)
- FEAT-002 socket server / client / envelope
  (`socket_api/server.py`, `client.py`, `errors.py`) + adds six
  closed-set error codes
- FEAT-005 in-container identity detection for the per-socket-call
  caller-context that populates `created_by_agent_id` on
  `route_created` (FR-001)
- FEAT-006 `agents/service.py` `list_agents`, agent lookup helpers,
  role/capability filtering, `AGENT_ID_RE`,
  `HOST_OPERATOR_SENTINEL`
- FEAT-007 `logs/redaction.py` `redact_one_line` via the existing
  `routing.excerpt.render_excerpt` 4-step pipeline (template
  rendering applies `render_excerpt` to the source event excerpt
  BEFORE substituting `{event_excerpt}`; other `{field}`
  placeholders are raw-pass per FR-008)
- FEAT-008 `events.dao.select_events(conn, *, event_id_gt,
  event_type, limit)` for the per-route batch query (FR-010)
- FEAT-009 `routing.service.QueueService` enqueue path + permission
  gate + kill switch + per-target FIFO + body validation + tmux
  paste-buffer delivery (FR-024, FR-027, FR-032, FR-055)
- FEAT-009 `routing.timestamps.now_iso_ms_utc()` for every new
  timestamp (route `created_at`, `updated_at`, audit `emitted_at`,
  heartbeat `emitted_at`)

**Storage**:
- **SQLite schema v8**: routes table + extended message_queue (3
  new columns + 1 partial UNIQUE index). Migration code lives in a
  new `_apply_migration_v8(conn)` in `state/schema.py`.
- **events.jsonl audit stream**: same file as FEAT-008/009, six
  new event types, JSONL durability mirrors FEAT-008 contract
  (buffer + retry, SQLite is source of truth).
- **No new on-disk file**. Heartbeat counters live in memory only
  (per-process; reset to zero on daemon restart).

**Testing**: pytest (inherits FEAT-008/009 patterns). Test layout:
- `tests/unit/test_routing_routes_dao.py`, `..._service.py`,
  `..._source_scope.py`, `..._template.py`, `..._arbitration.py`,
  `..._worker.py`, `..._heartbeat.py`, `..._audit.py`
- `tests/contract/test_socket_routes.py` (one test per socket
  method, request/response shape from `contracts/socket-routes.md`)
- `tests/contract/test_cli_routes.py` (one test per CLI subcommand,
  exit-code + JSON-shape contract from `contracts/cli-routes.md`)
- `tests/contract/test_route_audit_schema.py` (one test per audit
  event type, JSONL shape from `contracts/routes-audit-schema.md`)
- `tests/integration/test_routing_end_to_end.py` (Story 1 IT +
  Story 2 IT + Story 5 IT, fresh-container, using the existing
  FEAT-009 test fixtures)
- `tests/integration/test_routing_arbitration_determinism.py`
  (Story 3 IT)
- `tests/integration/test_routing_crash_recovery.py` (Story 4 IT,
  with fault-injection hook on the cursor-advance transaction)

**Target Platform**: Linux host daemon (`agenttowerd`) + bench
container CLI (`agenttower`). Both inherit FEAT-001..009
deployment; FEAT-010 adds no platform requirements.

**Project Type**: cli + daemon (single project, additive to
`src/agenttower/routing/`).

**Performance Goals**:
- SC-001: event-to-tmux-paste end-to-end ≤ 5s under typical local
  conditions (default 1s cycle interval + FEAT-009's already-
  measured ~100ms tmux paste budget leaves >3s of headroom for
  arbitration + render at the MVP scale).
- SC-006: `agenttower route list --json` at 1000 routes < 500ms.
  Achieved via single `SELECT * FROM routes ORDER BY created_at,
  route_id` with an index on `(created_at, route_id)`.
- SC-007: `agenttower route add` validation < 100ms (rejected
  inputs return without any SQLite write).
- Per-route batch cap default 100 events bounds worst-case single-
  route catch-up cycle at ~100 × (per-event arbitration + render +
  insert) which is sub-second under MVP scale.

**Constraints**:
- Stdlib only (no new third-party runtime dependency).
- Single-threaded sequential routing worker (no parallelism in MVP).
- Byte-for-byte deterministic replay (SC-010) modulo wall-clock
  timestamps and heartbeat counters.
- No model-based or LLM-based decisions anywhere in FEAT-010
  (FR-053).
- No TUI / web UI / notification surface (FR-054).
- Cannot broaden FEAT-009 permission rules (FR-055).

**Scale/Scope**:
- Routes table: hundreds to low thousands of rows per host (SC-006
  validates 1000).
- Routing cycles: 1/second default → 86,400/day. Quiet cycles emit
  no JSONL.
- Heartbeats: 1/minute default → 1,440/day.
- Audit-event growth: bounded by event-ingest rate × match rate ×
  fan-out (operator-controlled).
- Single host, single daemon process (no multi-daemon coordination).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1
design.*

| Principle | Verdict | Notes |
|---|---|---|
| I. Local-First Host Control | Pass | Routes table lives in the host SQLite registry; the daemon is the only writer; bench-container CLI reads via the existing Unix socket. No network listener. |
| II. Container-First MVP | Pass | Targets bench containers via the existing FEAT-009 tmux paste path (FR-032); FEAT-010 introduces no new container-discovery or pane-discovery surface. Inherits FEAT-009's docker-exec invocation contract. |
| III. Safe Terminal Input | Pass | Routes flow through the existing FEAT-009 enqueue helper (FR-024, FR-032, FR-055); permission gate, kill switch, body validation, and tmux paste-buffer adapter are all unchanged. FEAT-007 redaction is applied to `{event_excerpt}` before template substitution (FR-026). |
| IV. Observable and Scriptable | Pass | `agenttower route` + `agenttower queue --origin` + `agenttower status` (routing section) are CLI-first; every command has `--json`. Six new audit event types + heartbeat make the routing worker fully inspectable via `events --follow` + `status`. |
| V. Conservative Automation | Pass | FR-053 forbids model-based decisions; arbitration and target selection are rule-based and deterministic; no auto-suggestion of routes. The "no auto-deliver when unsure" invariant (skip + cursor-advance when no master) is the central design decision. |

**No constitution violations. Complexity Tracking section is empty.**

## Project Structure

### Documentation (this feature)

```text
specs/010-event-routes-arbitration/
├── plan.md              # This file
├── research.md          # Phase 0 output (key technical decisions)
├── data-model.md        # Phase 1 output (routes table + message_queue extension)
├── quickstart.md        # Phase 1 output (operator + dev quickstart)
├── contracts/           # Phase 1 output
│   ├── cli-routes.md           # `agenttower route ...` CLI contract
│   ├── cli-queue-origin.md     # `agenttower queue --origin` filter contract
│   ├── cli-status-routing.md   # `agenttower status` routing section
│   ├── socket-routes.md        # 6 new socket methods (routes.*)
│   ├── routes-audit-schema.md  # 6 new JSONL event types (incl. heartbeat)
│   └── error-codes.md          # Closed-set CLI + skip-reason vocabulary
├── checklists/          # Pre-plan checklists (8 deep, 1 requirements)
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/agenttower/
├── routing/                              # extended; FEAT-010 adds 10 new modules
│   ├── routes_dao.py                     # NEW — routes table CRUD
│   ├── routes_service.py                 # NEW — CRUD + validation + audit emit
│   ├── source_scope.py                   # NEW — parse_source_scope_value
│   ├── template.py                       # NEW — closed-whitelist {field} substitution
│   ├── arbitration.py                    # NEW — deterministic master selection
│   ├── worker.py                         # NEW — single-threaded routing cycle loop
│   ├── heartbeat.py                      # NEW — periodic heartbeat emitter
│   ├── routes_audit.py                   # NEW — emit 5 lifecycle + 1 heartbeat event types
│   ├── route_errors.py                   # NEW — closed-set FEAT-010 error vocabulary
│   ├── cli_routes.py                     # NEW — `agenttower route` subcommands
│   ├── service.py                        # EXTENDED — add enqueue_route_message + _origin kw arg
│   ├── dao.py                            # EXTENDED — read/write 3 new message_queue columns
│   ├── audit_writer.py                   # EXTENDED — recognize 6 new event types
│   ├── errors.py                         # EXTENDED — re-export FEAT-010 error codes
│   ├── timestamps.py                     # UNCHANGED — reused
│   ├── excerpt.py                        # UNCHANGED — reused for {event_excerpt} redaction
│   ├── target_resolver.py                # EXTENDED — share _parse_role_capability with source_scope
│   ├── permissions.py                    # UNCHANGED — reused via QueueService
│   ├── kill_switch.py                    # UNCHANGED — reused via QueueService
│   ├── delivery.py                       # UNCHANGED
│   ├── envelope.py                       # UNCHANGED
│   └── daemon_adapters.py                # EXTENDED — wire routing worker + heartbeat into boot
├── state/
│   └── schema.py                         # EXTENDED — add _apply_migration_v8, bump CURRENT_SCHEMA_VERSION
├── socket_api/
│   └── server.py                         # EXTENDED — dispatch routes.* methods
├── cli.py                                # EXTENDED — wire route subgroup; --origin on queue; routing section on status
└── events/
    └── dao.py                            # UNCHANGED — reused (select_events)

tests/
├── unit/
│   ├── test_routing_routes_dao.py        # NEW
│   ├── test_routing_routes_service.py    # NEW
│   ├── test_routing_source_scope.py      # NEW
│   ├── test_routing_template.py          # NEW
│   ├── test_routing_arbitration.py       # NEW
│   ├── test_routing_worker.py            # NEW
│   ├── test_routing_heartbeat.py         # NEW
│   ├── test_routing_audit.py             # NEW
│   └── test_routing_route_errors.py      # NEW
├── contract/
│   ├── test_socket_routes.py             # NEW
│   ├── test_cli_routes.py                # NEW
│   ├── test_cli_queue_origin_filter.py   # NEW
│   ├── test_cli_status_routing.py        # NEW
│   └── test_route_audit_schema.py        # NEW
└── integration/
    ├── test_routing_end_to_end.py        # NEW — Story 1, Story 2, Story 5
    ├── test_routing_arbitration_determinism.py  # NEW — Story 3
    └── test_routing_crash_recovery.py    # NEW — Story 4
```

**Structure Decision**: Single project (default layout). FEAT-010
is strictly additive within the existing `src/agenttower/routing/`
package and the existing `tests/{unit,contract,integration}/` tree.
No new top-level directory. Module split rationale:
- One module per concern (DAO / service / parser / renderer /
  arbitrator / worker / heartbeat / audit / errors / CLI) so each
  test file maps to one production module 1:1.
- Pure functions isolated from threaded code (template rendering,
  source-scope parsing, arbitration decision, body validation,
  audit envelope construction) so they unit-test without a
  `sqlite3.Connection` or a worker thread.
- The two threaded modules (`worker.py`, `heartbeat.py`) each own
  a single `threading.Event`-based loop with `Clock`-Protocol-
  driven timing for test seams.

## Implementation Notes

### §1. Module-by-module responsibilities

**`routes_dao.py`** — Pure CRUD against the `routes` table.
Functions: `insert_route(conn, row) -> str` (returns route_id),
`list_routes(conn, *, enabled_only=False) -> list[RouteRow]`,
`select_route(conn, route_id) -> RouteRow | None`,
`update_enabled(conn, route_id, *, enabled) -> bool` (returns True
if state changed — supports FR-009 idempotent no-op),
`delete_route(conn, route_id) -> bool` (returns True on hit),
`advance_cursor(conn, route_id, event_id) -> None`. No business
logic; no audit emission; no JSON shaping. `BEGIN IMMEDIATE` is
opened by callers in `worker.py` / `routes_service.py`, not by DAO
functions.

**`routes_service.py`** — Top-level CRUD orchestration. Functions:
`add_route(conn, *, event_type, source_scope_kind,
source_scope_value, target_rule, target_value, master_rule,
master_value, template, created_by_agent_id) -> RouteRow` — runs
validation in FR-005..008 order, populates
`last_consumed_event_id` via `events.dao.select_max_event_id(conn)
or 0` (FR-002), `INSERT`s under `BEGIN IMMEDIATE`, calls
`routes_audit.emit_route_created(...)`. Similarly:
`remove_route`, `enable_route`, `disable_route`, `list_routes`,
`show_route`.

**`source_scope.py`** — `parse_source_scope_value(raw: str | None,
kind: str) -> ParsedSourceScope` (frozen dataclass with
`role: str | None`, `capability: str | None`,
`agent_id: str | None`). Raises `RouteSourceScopeInvalid` on bad
input. The internal helper `_parse_role_capability(raw: str) ->
tuple[str, str | None]` is **shared** with `target_resolver.py`
per Clarifications Q1 — one grammar, one parser. Match function
`matches(parsed: ParsedSourceScope, event_source_role: str,
event_source_capability: str | None, event_source_agent_id: str)
-> bool`.

**`template.py`** — `validate_template_string(template: str) ->
list[str]` returns the set of `{<field>}` placeholders, raising
`RouteTemplateInvalid` on any unknown field.
`render_template(template: str, event: EventRow, *,
redactor: Callable[[str], str]) -> bytes` substitutes each
placeholder, runs the event excerpt through
`routing.excerpt.render_excerpt(event.body_bytes, redactor)` for
`{event_excerpt}` only, leaves the seven other whitelisted fields
raw, encodes the result to UTF-8 bytes, and runs FEAT-009's
existing body validation (`envelope.validate_body_bytes(...)`).
Returns the bytes ready for `QueueService.enqueue_route_message`.
Raises `RouteTemplateRenderError(reason=...)` with sub-reason in
`{missing_field, body_too_large, body_invalid_chars,
body_invalid_encoding}`.

**`arbitration.py`** — `pick_master(*, master_rule: str,
master_value: str | None, active_masters: list[AgentRow]) ->
ArbitrationResult`. `ArbitrationResult` is either
`MasterWon(agent: AgentRow)` or `MasterSkip(reason: str)` with
reason in the closed set `{no_eligible_master, master_inactive,
master_not_found}`. Pure function; takes a pre-fetched
active-master list snapshot rather than a `conn` so it tests
trivially. Caller (`worker.py`) takes the snapshot once per
`(route, event)` pair at evaluation time per FR-020.

**`worker.py`** — `RoutingWorker(conn_factory, agents_service,
queue_service, audit_emitter, clock, shutdown_event, *,
cycle_interval, batch_size)`. The `run()` method is the
single-threaded sequential loop:
```python
while not shutdown_event.is_set():
    cycle_start = clock.monotonic()
    routes = routes_dao.list_routes(conn, enabled_only=True)
    routes.sort(key=lambda r: (r.created_at, r.route_id))  # FR-042
    for route in routes:
        if shutdown_event.is_set(): break
        _process_route_batch(conn, route, ...)             # FR-041 cap
    clock.sleep_until(cycle_start + cycle_interval)
```
`_process_route_batch` does the per-(route, event) work for up to
`batch_size` events; each event is processed in its own
`BEGIN IMMEDIATE` transaction that:
1. SELECTs the master snapshot
   (`agents_service.list_active(role='master')`)
2. Calls `arbitration.pick_master(...)`
3. On `MasterSkip`: emits `route_skipped` (under best-effort
   retry), `routes_dao.advance_cursor(...)`, COMMIT.
4. On `MasterWon`: resolves target (`target_resolver.resolve_target`
   for explicit; `event.source_agent_id` for source; lex-lowest
   active matching agent for role+capability); on target failure
   emits `route_skipped(target_not_found |
   target_role_not_permitted | no_eligible_target)`, advances
   cursor, COMMITs.
5. On target success: renders template via
   `template.render_template`; on render failure emits
   `route_skipped(template_render_error)` with sub-reason,
   advances cursor, COMMITs.
6. On render success: calls
   `queue_service.enqueue_route_message(envelope=...,
   sender=master, target=resolved_target,
   route_id=route.route_id, event_id=event.event_id)`; this
   INSERTs the queue row and may surface the FEAT-009
   kill-switch-off path (row lands in `blocked` with
   `block_reason=kill_switch_off` per FR-032, Story 5 #1);
   `routes_dao.advance_cursor(...)`; COMMIT; emits
   `route_matched`. The FEAT-009 `target_role_not_permitted` skip
   (Story 5 #4) surfaces via an exception from
   `enqueue_route_message` and is mapped to
   `route_skipped(target_role_not_permitted)` with cursor
   advance.
The worker maintains in-memory aggregate counters
(`cycles_since_last_heartbeat`,
`events_consumed_since_last_heartbeat`,
`skips_since_last_heartbeat`) under a `threading.Lock` that the
heartbeat thread snapshots and resets. Transient errors (SQLite
`OperationalError: database is locked`, internal
`RoutingDegraded`) raise `RoutingTransientError`; the cursor does
NOT advance, the transaction rolls back, the event is re-evaluated
next cycle, the shared `routing_worker_degraded` flag flips for
that cycle and the next.

**`heartbeat.py`** — `HeartbeatEmitter(audit_emitter,
shared_counters, shared_lock, degraded_flag, clock,
shutdown_event, *, interval_seconds)`. The `run()` method: sleep
one interval, snapshot + reset under lock, emit
`routing_worker_heartbeat` audit entry with counters +
`degraded=degraded_flag.is_set()` + `emitted_at` from
`timestamps.now_iso_ms_utc()`, repeat. No startup beacon
(FR-039a).

**`routes_audit.py`** — One emit function per audit type:
`emit_route_matched`, `emit_route_skipped`, `emit_route_created`,
`emit_route_updated` (with `change: {'enabled': true|false}`),
`emit_route_deleted`, `emit_routing_worker_heartbeat`. Each builds
the JSONL envelope (event_type, event_id, route_id, …) and hands
off to `events.writer.append_event` for the actual write. JSONL
durability failure paths buffer in `_pending_audit_buffer:
deque[dict]` (bounded to 10_000 entries; on overflow oldest is
dropped + a one-shot `audit_buffer_overflow` log line is
written), retried by the worker on the next cycle.

**`route_errors.py`** — Closed-set vocabulary as module-level
constants: `ROUTE_ID_NOT_FOUND`, `ROUTE_EVENT_TYPE_INVALID`,
`ROUTE_TARGET_RULE_INVALID`, `ROUTE_MASTER_RULE_INVALID`,
`ROUTE_TEMPLATE_INVALID`, `ROUTE_SOURCE_SCOPE_INVALID`,
`ROUTE_CREATION_FAILED`. Skip-reason constants:
`NO_ELIGIBLE_MASTER`, `MASTER_INACTIVE`, `MASTER_NOT_FOUND`,
`TARGET_NOT_FOUND`, `TARGET_ROLE_NOT_PERMITTED`,
`TARGET_NOT_ACTIVE`, `TARGET_PANE_MISSING`,
`TARGET_CONTAINER_INACTIVE`, `NO_ELIGIBLE_TARGET`,
`TEMPLATE_RENDER_ERROR`, plus the template sub-reasons
`BODY_EMPTY`, `BODY_INVALID_CHARS`, `BODY_INVALID_ENCODING`,
`BODY_TOO_LARGE`.

**`cli_routes.py`** — argparse subparsers for `route
add|list|show|remove|enable|disable`. Each subcommand calls the
matching `socket_api/client` method, formats the response (human +
`--json`), and exits with the documented code. Flag set per
`contracts/cli-routes.md`.

### §2. Extensions to existing modules

**`routing/service.py`** — `QueueService.send_input(...)` gains
`_origin: Literal['direct', 'route'] = 'direct'`, `_route_id: str
| None = None`, `_event_id: int | None = None` as keyword-only
arguments (leading underscore signals "internal, not for socket
callers"). The socket dispatch path for `queue.send_input` does
NOT forward these; they are settable only from the in-process
`enqueue_route_message(...)` public method, which is the FEAT-010
entry point. Both methods share the existing body-validation /
permission / kill-switch / per-target-FIFO code path verbatim.
Insert SQL is updated to include the three new columns; existing
direct-send inserts pass `('direct', None, None)`.

**`routing/dao.py`** — INSERT and SELECT statements updated to
include `origin, route_id, event_id`. The `QueueRow` dataclass
gains three new fields with sensible defaults so existing call
sites continue to work.

**`routing/audit_writer.py`** — `KNOWN_EVENT_TYPES` set gets six
new entries (the FR-035 enumeration). No other change; the writer
is a thin shim over `events.writer.append_event`.

**`routing/errors.py`** — Re-exports the seven CLI error codes
from `route_errors.py` so the socket dispatcher can map exceptions
to codes from one place.

**`state/schema.py`** — Adds `_apply_migration_v8(conn)`:
```sql
-- Step 1: routes table
CREATE TABLE routes (
  route_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  source_scope_kind TEXT NOT NULL,
  source_scope_value TEXT NULL,
  target_rule TEXT NOT NULL,
  target_value TEXT NULL,
  master_rule TEXT NOT NULL,
  master_value TEXT NULL,
  template TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_consumed_event_id INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  created_by_agent_id TEXT NULL
);
CREATE INDEX idx_routes_created_at_route_id
  ON routes(created_at, route_id);
-- Step 2: extend message_queue
ALTER TABLE message_queue
  ADD COLUMN origin TEXT NOT NULL DEFAULT 'direct';
ALTER TABLE message_queue ADD COLUMN route_id TEXT NULL;
ALTER TABLE message_queue ADD COLUMN event_id INTEGER NULL;
CREATE UNIQUE INDEX idx_message_queue_route_event
  ON message_queue(route_id, event_id) WHERE origin = 'route';
-- Step 3: bump schema_version
UPDATE schema_version SET version = 8;
```
`CURRENT_SCHEMA_VERSION = 8`. The migration is idempotent under
the existing `_apply_pending_migrations` framework. Partial INDEX
with `WHERE origin = 'route'` keeps the constraint scoped —
direct-send rows always have NULL `route_id` / `event_id`, so they
wouldn't conflict, but the partial index makes the intent explicit
and avoids any SQLite quirk with NULL semantics in UNIQUE
constraints.

**`socket_api/server.py`** — Six new method handlers under a
`routes.*` namespace. Each takes the existing FEAT-002 envelope,
calls into `routes_service`, maps `RouteError` exceptions to
closed-set codes from `route_errors.py`, returns the documented
JSON shape. No host-vs-container authorization restriction in MVP
(per FEAT-009 assumptions inheritance — see Risk Register §3).

**`cli.py`** — Three changes:
1. Register the `route` subparser group via
   `cli_routes.register(subparsers)`.
2. Add `--origin {direct,route}` to the existing `queue`
   subparser; pass through to the existing `queue.list` socket
   method's `origin_filter` parameter (a new optional filter that
   `routing/service.QueueService.list_queue(...)` will honor).
3. In the existing `status` subparser's human + `--json`
   formatters, inject the `routing` section from the existing
   `status` socket method (extended response — see Risk Register
   §4).

**`routing/daemon_adapters.py`** — `start_daemon(...)` already
spawns the FEAT-009 delivery worker. FEAT-010 adds:
- After delivery-worker start: spawn `RoutingWorker.run()` on a
  daemon thread.
- After routing-worker start: spawn `HeartbeatEmitter.run()` on a
  daemon thread.
- On shutdown signal: set both `Event`s; join both threads with a
  bounded timeout that's a small multiple of the worker's cycle
  interval.

### §3. Cross-cutting design decisions

**Validation order at `route add`** — FR-005 → FR-007 → FR-006 →
new source-scope check → FR-008. Rationale: cheap-string-match
checks first (event_type, master_rule, target_rule), then the two
parsers (source_scope, target_value), then the template field-set
validator. First failure short-circuits; the CLI exit code
reflects the first failure category. (Concurrency-of-multiple-
validation-failures is declared single-error-per-call to match
FEAT-009's pattern.)

**Cursor advance under skip** — The cursor MUST advance on every
terminal decision, even skips, so a route with a permanently-broken
template (caught at `route add` time, but theoretical) cannot
stall the worker. The exception is `RoutingTransientError`, where
the SQLite transaction rolls back and no audit is emitted.

**Cursor freeze under disable** — `worker.run()` only processes
`enabled=true` routes; the cursor row is updated only via the
transaction inside `_process_route_batch`, so a disabled route's
`last_consumed_event_id` is naturally frozen (FR-009, Story 2 #3,
edge cases section).

**Active-master snapshot timing** — Each `(route, event)` pair
takes a fresh `agents_service.list_active(role='master')` call
inside its transaction. Within a cycle, the snapshot may change
between two adjacent events for the same route; this is acceptable
and tested in Story 3 IT. Across restarts, the same input produces
the same snapshot (SC-010) so determinism holds.

**Per-target FIFO order from fan-out** — When N enabled routes
match the same event AND target the same agent, the routing
worker processes them in `(created_at, route_id)` order and
INSERTs N queue rows. Each insert uses `now_iso_ms_utc()` for
`enqueued_at`; since inserts within a cycle happen serially, the
timestamps are monotonically increasing (the existing FEAT-009
millisecond clock guarantees this for adjacent calls).
FEAT-009's delivery worker serializes per-target by `(enqueued_at,
message_id)`, so the delivery order is the same as the
route-processing order.

**`origin='direct'` backward compatibility** — Every existing
`message_queue` row gets `'direct'` via the `DEFAULT` clause at
migration time; every existing FEAT-009 insert path passes
`('direct', None, None)`. The new `--origin` filter on
`agenttower queue` defaults to no filter (returns both origins);
the existing `agenttower queue` invocation continues to show both
direct and route rows.

**Heartbeat emission and degraded state** — The heartbeat's
`degraded` field is the canonical JSONL-side mirror of
`routing_worker_degraded` from the status surface. A heartbeat
emitted DURING a degraded cycle carries `degraded=true`; a
heartbeat emitted after recovery carries `degraded=false`. This
gives JSONL-only operators a way to detect routing health without
polling `status`.

**No `routing_cycle_*` audit events** — Per Clarifications Q3 /
FR-035 / FR-039a, only `routing_worker_heartbeat` provides cycle-
level signal. The worker MUST NOT emit any per-cycle JSONL entry
(enforced by an AST-test in
`tests/unit/test_no_per_cycle_audit_calls.py` that walks
`worker.py` and asserts the only `append_event` calls are for
the five per-(route, event) types).

## Risk Register

1. **Mid-cycle `enabled` flip race**: An operator runs `route
   disable` between two events in the same route's batch. The
   in-flight transaction completes for the currently-evaluated
   event (cursor advances); the next event in the batch is NOT
   processed because the loop re-fetches the route row before each
   event. → **Mitigated** by the `route = routes_dao.select_route(
   conn, route.route_id)` refresh inside `_process_route_batch`
   between events, plus a `if not route.enabled: break`.

2. **Heartbeat counter race**: Worker increments a counter while
   heartbeat thread is reading + resetting. → **Mitigated** by a
   single `threading.Lock` shared by both threads; the lock is
   held only during the snapshot+reset, not during the JSONL
   write.

3. **No host-vs-container authorization on `routes.*` socket
   methods**: A bench-container CLI caller can create or delete
   routes today. Per FEAT-009 inheritance, "host-user only" is
   currently enforced only on `routing enable/disable`. FEAT-010
   does NOT add per-method authorization. → **Documented in spec
   Assumptions section** (host-user only); operator awareness is
   the MVP control. Per-caller RBAC is a follow-up feature.

4. **`status.routing` socket method vs extending existing
   `status` response**: Two options — (a) add the `routing`
   object to the existing `status` method's response (no new
   socket method, but the response grows); (b) add a new
   `status.routing` socket method and have the CLI merge two
   responses. → **Decision**: option (a). Single socket
   round-trip, simpler client. The existing `status` JSON is
   already a nested object; adding one more top-level key is
   additive and backward-compatible.

5. **Migration partial-completion**: An ALTER TABLE succeeds, the
   subsequent CREATE INDEX fails, the daemon crashes. →
   **Mitigated** by `IF NOT EXISTS` guards on every CREATE in
   `_apply_migration_v8` and the existing
   `_apply_pending_migrations` resume-from-current-version
   contract. The migration is idempotent; restarting the daemon
   completes the partial migration.

6. **Audit buffer unbounded growth in extended-degraded state**:
   If `events.jsonl` is unwritable for hours, the in-memory
   buffer could exhaust RAM. → **Mitigated** by a 10_000-entry
   bounded deque with FIFO eviction and a one-shot
   `audit_buffer_overflow` log line. Buffer size is configurable
   but not exposed in MVP.

## Implementation Invariants (concurrency, shutdown, multi-process)

These invariants close concurrency-related quality-gate questions
and are documented here so the implementation can cite them.

1. **Shutdown ordering (FEAT-009 vs FEAT-010 workers)**. On daemon
   shutdown the routing worker and heartbeat thread are signaled
   FIRST (set their `Event`s; join with bounded timeout). The
   FEAT-009 delivery worker stops AFTER (reverse-LIFO of startup
   order per `daemon_adapters.py`). Rationale: routing must stop
   producing new queue rows before delivery drains; this prevents
   a row from being inserted between the delivery-worker's last
   drain pass and shutdown.

2. **Heartbeat-emission shutdown behavior**. When the heartbeat
   thread's `shutdown_event` is set, the in-flight `wait(interval)`
   returns immediately. The thread MUST NOT emit a final heartbeat
   at shutdown; the next daemon start emits the first heartbeat
   one full interval into its lifetime per FR-039a. This avoids a
   degraded-state false-positive in the last-heartbeat-before-
   restart entry.

3. **Concurrent CLI access safety**. Every CLI catalog mutation
   (`routes.add`/`remove`/`enable`/`disable`) opens `BEGIN
   IMMEDIATE` on its SQLite connection. Two concurrent `route
   disable <same-id>` calls serialize at the SQLite write lock;
   the second observes the first's state-change-flag result
   (idempotent no-op per FR-009 — no duplicate audit entry).

4. **SQLite journaling mode**. FEAT-010 inherits the FEAT-001 WAL-
   mode setup (existing `_configure_connection` in
   `state/schema.py`). No FEAT-010-specific journaling change.
   WAL gives FEAT-010 the snapshot consistency it needs for the
   per-(route, event) active-master snapshot (research §R8).

5. **Multi-process daemon detection**. FEAT-010 inherits FEAT-001's
   PID-file lock at daemon startup; a second `agenttowerd`
   invocation on the same state DB exits with the existing
   FEAT-001 "daemon already running" error. The routing worker
   adds no detection layer of its own.

6. **Cycle-overrun behavior**. If a routing cycle's
   `_process_route_batch` execution exceeds `cycle_interval`, the
   next cycle starts IMMEDIATELY after the current cycle's COMMIT
   — `clock.sleep_until(cycle_start + cycle_interval)` is a no-op
   when `cycle_start + cycle_interval` is already in the past.
   Cycles never overlap (FR-014); cycles are never silently
   skipped (each event with `event_id > last_consumed_event_id`
   is eventually evaluated).

## Performance Addendum (advisory; T063b is the testable gate)

These bounds document expected performance and rationale behind
the SLOs in spec.md SC-001/SC-006/SC-007/SC-009. They are
advisory — the testable thresholds live in T063b.

- **5-second end-to-end latency budget (SC-001) decomposition**:
  FEAT-008 ingest (~100 ms) + routing-cycle wake-up (0–1000 ms,
  depends on cycle phase) + arbitration + render (~50 ms) +
  FEAT-009 enqueue + permission gate (~50 ms) + FEAT-009 delivery
  pickup wait (0–1000 ms) + tmux paste (~100 ms) ≈ 2.3 s worst
  case. The 5 s SLO leaves ~2.7 s headroom for SQLite contention
  and tmux jitter.
- **CRUD latency beyond `route add`/`list`**. `route show`,
  `route enable`, `route disable`, `route remove` are single-row
  reads or updates indexed on the PK `route_id`; expected < 100 ms
  at 1000 routes. Not separately measured in T063b — SC-007's
  100 ms validation budget is the tighter bound.
- **Max route count beyond 1000**. Architecture scales to ~10,000
  routes per host before `most_stalled_route` lag computation
  becomes the dominant `status --json` cost. Beyond 10K, operators
  should expect `status --json` latency > 1 s. Out of MVP scope;
  a future feature can add a covering index
  `routes(enabled, last_consumed_event_id)`.
- **Fan-out worst-case (N routes × M events per cycle)**.
  `N_enabled × min(batch_size, M_pending) × (arbitration + render
  + insert)`. At defaults (N=1000, batch_size=100, M unlimited),
  per-cycle work ≈ 100,000 evaluations; at ~1 ms each this is
  100 s, well beyond `cycle_interval=1.0`. Operators with
  thousands of enabled routes SHOULD tune `cycle_interval` upward
  or disable inactive routes.
- **Observability-counter update cost**. `_SharedRoutingState`
  counter increments are O(1) under `threading.Lock`; lock-hold
  time is microseconds. Contributes < 1 % to per-event cycle time.
- **`queue --origin route` filter performance**. New
  `WHERE origin = :origin_filter` uses the existing
  `(enqueued_at, message_id)` ordering scan — no dedicated index.
  At MVP queue sizes (< 100K rows), sub-100 ms. A future
  `idx_message_queue_origin` could be added if profiling indicates.
- **UNIQUE `(route_id, event_id)` index insert performance**. The
  partial UNIQUE index adds one index-write per route-generated
  insert (~10 μs). Direct-send rows incur zero overhead (excluded
  by the partial predicate `WHERE origin='route'`).
- **`most_stalled_route` algorithmic complexity**. Per-route lag
  query is `SELECT COUNT(*) FROM events WHERE event_id > cursor
  AND event_type = ?` — indexed scan, O(log N) + O(M) where M is
  post-cursor matching events. Total cost: O(K × log N +
  total_pending) where K = enabled routes. At K=1000, N=100K,
  total_pending=10K → well under 500 ms.
- **`most_stalled_route` with disabled routes**. Disabled routes
  are EXCLUDED from the computation (`WHERE enabled = 1` in the
  query). A disabled route's accumulating backlog is intentionally
  invisible to this metric — a deliberately-paused route is not
  "stalled."
- **Template-rendering latency**. Per-event render is dominated by
  FEAT-007 redaction over a ≤240-char excerpt (~1 ms). Raw-field
  substitution is O(template length). Total: < 5 ms per render.
- **Audit-retry latency under degraded state**. When the audit
  buffer is non-empty, each cycle's first action drains the
  buffer (one JSONL append per pending entry). Buffer at maxlen
  (10K) → cycle latency dominated by 10K JSONL writes (~10–50 s).
  Intentional: drain takes priority; routing continues in next
  cycle. The `routing_worker_degraded` flag stays set while the
  buffer is non-empty.
- **Degraded-state routing throughput**. Routing continues
  unaffected by audit-buffer state (audit append is outside the
  cursor-advance transaction per FR-039). Throughput is reduced
  ONLY by the per-cycle buffer-drain overhead above.

## Complexity Tracking

> No Constitution Check violations. This section is intentionally
> empty.
