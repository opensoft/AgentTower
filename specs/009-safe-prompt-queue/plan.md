# Implementation Plan: Safe Prompt Queue and Input Delivery

**Branch**: `009-safe-prompt-queue` | **Date**: 2026-05-11 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/009-safe-prompt-queue/spec.md`

## Summary

FEAT-009 turns the FEAT-006-registered master/slave/swarm graph into a
durable, permissioned, tmux-safe input plane. The work splits into six
additive layers, each narrow:

1. **SQLite migration v6 → v7** that adds two new tables — `message_queue`
   (one row per `send-input` invocation, lifecycle states, identity
   snapshots, timestamps) and `daemon_state` (one-row key/value table
   carrying the routing kill switch). No existing FEAT-001..008 table is
   touched. `CURRENT_SCHEMA_VERSION` advances `6 → 7`.

2. **A `routing/` package** under `src/agenttower/routing/` (the
   directory exists today as an empty stub — `__init__.py` only) that
   contains the queue service, DAO, envelope/body validation,
   permission gate, delivery worker, kill switch service, and the
   closed-set error vocabulary. Pure functions where possible (envelope
   rendering, excerpt pipeline, permission decision) so they can be
   unit-tested without spinning up the daemon.

3. **A delivery worker thread** in `src/agenttower/routing/delivery.py`
   that the daemon starts at boot AFTER the FR-040 crash-recovery pass
   (rows with `delivery_attempt_started_at` set and terminal stamps
   unset → `failed` with `attempt_interrupted` before the worker picks
   up any new work). Single worker, serial dispatch in
   `(enqueued_at, message_id)` order across all targets (Clarifications
   Q5 / FR-045); per-target FIFO falls out trivially. Uses the
   FEAT-004 tmux adapter Protocol — see point 4 — for every tmux
   operation; never constructs a shell string with body bytes.

4. **An extended `tmux/` adapter Protocol**. The existing FEAT-004
   `TmuxAdapter` Protocol covers `list-panes` only. FEAT-009 extends it
   with four new methods — `load_buffer(container_id, bench_user,
   socket_path, buffer_name, body_bytes) -> None`, `paste_buffer(...,
   pane_id, buffer_name) -> None`, `send_keys(..., pane_id, key) ->
   None`, `delete_buffer(..., buffer_name) -> None`. The
   `SubprocessTmuxAdapter` gains the four `docker exec -u <bench-user>
   <container-id> tmux ...` invocations (stdin-piped for `load-buffer`,
   no shell substitution); the `FakeTmuxAdapter` records every call so
   tests can assert byte-exact deliveries.

5. **A new CLI surface** — `agenttower send-input`, `agenttower queue`,
   `agenttower queue approve|delay|cancel`, `agenttower routing
   enable|disable|status` — routed through eight new socket methods
   (`queue.send_input`, `queue.list`, `queue.approve`, `queue.delay`,
   `queue.cancel`, `routing.enable`, `routing.disable`,
   `routing.status`) over the existing FEAT-002 / FEAT-005 thin-client
   envelope. The routing toggle endpoints enforce a host-origin check
   at the socket dispatch boundary (Clarifications Q2 / FR-027). The
   `send-input` endpoint enforces a "sender pane resolves to a
   registered active master" check at the socket dispatch boundary
   using the existing FEAT-005 caller-identity headers (Clarifications
   Q3 / FR-006).

6. **JSONL audit append** to the existing FEAT-008 `events.jsonl`
   stream (Clarifications Q4 / FR-046) via the FEAT-001
   `events.writer.append_event` helper, using the seven new
   `queue_message_*` event types. Audit append happens AFTER the
   SQLite state-transition commit (FR-048); JSONL durability failures
   buffer in memory and retry on the next worker cycle, with a
   `degraded_queue_audit_persistence` field surfaced through
   `agenttower status` (mirroring FEAT-008's `degraded_events_
   persistence` pattern).

The ten locked clarifications from `## Clarifications` shape the
implementation rather than constrain the spec:

- **Q1 (storage)** — `envelope_body` is always raw bytes (`BLOB`,
  not `TEXT` — bodies can contain `\n` and `\t` and the SQLite text
  affinity loses fidelity on round-trip in unusual encodings); the
  delivery worker reads the body from SQLite at the start of every
  attempt (FR-012a). Redaction is applied at the excerpt pipeline
  (FR-047b) and never at storage.
- **Q2 / Q3 (kill switch + sender)** — host-origin check is implemented
  at the socket dispatch layer using FEAT-002's peer-credential
  surface (already used by FEAT-005 for in-container identity). A
  host-origin connection is one whose `socket_peer_uid` matches the
  daemon's own uid AND whose caller-context headers do NOT carry a
  bench-container pane identity (the absence is the host signal).
- **Q4 (audit stream)** — single `events.jsonl`, seven new
  `queue_message_*` event types disjoint from FEAT-008's ten classifier
  types and FEAT-007's lifecycle types.
- **Q5 (concurrency)** — one delivery worker thread, serial dispatch.
- **Session 2 Q1 (kill switch race)** — `routing disable` only stops
  pickup; in-flight rows finish (FR-028). The worker re-checks the
  routing flag BEFORE stamping `delivery_attempt_started_at`, never
  AFTER.
- **Session 2 Q2 (`--target` resolution)** — implemented in a new
  pure function `routing.target_resolver.resolve_target(input_str,
  agents_service) -> ResolvedTarget | TargetResolveError`. Shape
  test uses FEAT-006's `AGENT_ID_RE`, not UUIDv4 (see Implementation
  Deviations §1 for the spec-vs-code reconciliation).
- **Session 2 Q3 (multi-line excerpt)** — implemented in
  `routing.excerpt.render_excerpt(body_bytes, redactor) -> str` as the
  four-step pipeline (redact → collapse whitespace runs → truncate to
  240 chars → append `…` if truncated). Unit-tested against every
  excerpt surface (queue listing, audit, `--json`).
- **Session 2 Q4 (`host-operator` sentinel)** — FEAT-006's
  `validate_agent_id_shape` is extended to reserve the literal string
  `host-operator` so the registry refuses any pane registration with
  that id. All FEAT-009 audit/identity writers use the same constant
  `HOST_OPERATOR_SENTINEL = "host-operator"`.
- **Session 2 Q5 (timestamp encoding)** — single helper
  `routing.timestamps.now_iso_ms_utc() -> str` returns
  `YYYY-MM-DDTHH:MM:SS.sssZ`; SQLite columns store the same string;
  `events.jsonl` emits the same string; `--since` parser accepts both
  the millisecond and the seconds form.

The single highest-stakes property FEAT-009 introduces — that
shell metacharacters in the body cannot escape into a host or
container shell — is enforced by the tmux adapter Protocol contract:
every adapter method takes body bytes as `bytes` (not `str`) and
the production `SubprocessTmuxAdapter` passes them via
`subprocess.run(..., input=body_bytes, ...)` for `load-buffer` and
via `subprocess.run(args=[...], ...)` (argv, not shell) for every
other tmux command. The FR-038 prohibition is enforceable at code-
review time and AST-test-gated by a new `tests/unit/
test_no_shell_string_interpolation.py` that walks the
`SubprocessTmuxAdapter` source and asserts no `subprocess.run(...,
shell=True)`, no `os.system(...)`, no `f"...{body}..."`-style
interpolation involving the body argument.

The second highest-stakes property is restart resilience: every
state transition commits to SQLite BEFORE its companion side effect
(tmux paste, JSONL append). FR-041 (`delivery_attempt_started_at`
committed BEFORE the first tmux call), FR-042 (`delivered_at`
committed BEFORE picking the next row), FR-040 (recovery transitions
all interrupted rows BEFORE the worker resumes) are encoded as
explicit ordering in the delivery worker and tested at call-count
granularity (mirroring FEAT-008's `test_reader_recovery_first.py`
pattern).

The CLI surface is intentionally narrow: three new subcommand groups
(`send-input`, `queue`, `routing`) and one new top-level error
namespace. `--json` re-uses the FR-011 stable schema verbatim
(envelope identity, state, timestamps, redacted excerpt) so a script
piping `send-input --json` to a log file would see the same shape
as `queue --json` modulo the array wrapping.

## Technical Context

**Language/Version**: Python 3.11+ (inherits from FEAT-001 — FEAT-008;
`pyproject.toml` pins `requires-python>=3.11`). Standard library only —
no third-party runtime dependency added.

**Primary Dependencies**: Standard library only — `sqlite3`
(`message_queue` and `daemon_state` CRUD; `BEGIN IMMEDIATE` for
state-transition criticals; `BLOB` affinity for `envelope_body`;
per-statement parameterization with no string interpolation),
`uuid` (`uuid.uuid4()` for `message_id`, the spec FR-001
identifier — distinct from FEAT-006's `agt_<12-hex>` agent_id —
see Implementation Deviation §1), `subprocess` (extended tmux
adapter; argv-only invocations; stdin-piped `load-buffer`),
`threading` (one daemon-side delivery worker thread, plus
`threading.Event`-based wakeup for graceful shutdown; per-target
serialization is degenerate under the single-worker model so no
new mutex registry is needed),
`time` (`time.monotonic()` for the delivery-wait timeout clock;
`time.time()` is forbidden inside the worker hot path — a `Clock`
Protocol test seam mirrors FEAT-008's pattern),
`datetime` (`datetime.now(tz=datetime.UTC)` for the canonical
ISO-8601 millisecond UTC timestamp helper — see Implementation
Notes §"Timestamp encoding"),
`hashlib` (`hashlib.sha256` for `envelope_body_sha256`),
`dataclasses`, `typing`, `json`, `argparse` (CLI).

Reuses FEAT-001 `events.writer.append_event` verbatim for the JSONL
append (FR-046, FR-048); reuses FEAT-002 socket server
(`socket_api/server.py`), client (`socket_api/client.py`), envelope
(`socket_api/errors.py`) verbatim and adds 11 new closed-set error
codes (full list in `data-model.md` §8); reuses FEAT-005 in-container
identity detection on both sides of the socket (the daemon to enforce
host-origin and sender-pane checks; the CLI to surface caller context
headers); reuses FEAT-006 `agents/service.py` `list_agents` / lookup
helpers for sender-pane resolution and `--target` resolution, plus
the `AGENT_ID_RE` shape regex from `agents/identifiers.py`; reuses
FEAT-006 `agents/identifiers.py` — extended to reserve
`host-operator` (a single literal added to the existing reservation
predicate; not a wire-format break); reuses FEAT-007
`logs/redaction.py` `redact_one_line` verbatim for the FR-047b
excerpt pipeline; reuses FEAT-008 `events/writer.py` JSONL
write path verbatim and follows its degraded-buffer pattern
(`degraded_events_persistence` becomes the model for
`degraded_queue_audit_persistence`).

**Storage**: One SQLite migration `v6 → v7` (FEAT-009) with three
parts: (1) add two new tables (`message_queue`, `daemon_state`)
and four supporting indexes; (2) **rebuild the FEAT-008 `events`
table** in-place to widen its `event_type` CHECK constraint
(accept the eight FEAT-009 audit types in addition to the
FEAT-008 ten) and make the FEAT-008-specific NOT NULL columns
(`attachment_id`, `log_path`, `byte_range_*`, `line_offset_*`,
`classifier_rule_id`) NULLABLE so queue audit rows can be
inserted without those fields; (3) recreate the four FEAT-008
indexes that the rebuild drops. The rebuild uses the standard
SQLite `CREATE TABLE …_new` + `INSERT … SELECT *` + `DROP` +
`RENAME` pattern, runs inside the same `BEGIN IMMEDIATE`
transaction as the additive tables, and preserves every FEAT-008
row byte-for-byte (validated by `test_schema_migration_v7.py`
T013). `CURRENT_SCHEMA_VERSION` advances from `6` to `7`.
Migration is idempotent on re-open via `IF NOT EXISTS` for the
additive tables; the rebuild part guards on the current schema
version being exactly `6` so it does not re-run on v7. Refuses
to serve the daemon on rollback (mirrors FEAT-007 / FEAT-008's
pattern). The two new tables and the rebuilt `events` table
(full DDL in `data-model.md`):

```sql
CREATE TABLE message_queue (
    message_id                 TEXT PRIMARY KEY,                    -- UUIDv4 string form
    state                      TEXT NOT NULL CHECK (state IN (
        'queued', 'blocked', 'delivered', 'canceled', 'failed'
    )),
    block_reason               TEXT,                                 -- closed set (FR-017)
    failure_reason             TEXT,                                 -- closed set (FR-018)
    sender_agent_id            TEXT NOT NULL,
    sender_label               TEXT NOT NULL,
    sender_role                TEXT NOT NULL,
    sender_capability          TEXT,
    target_agent_id            TEXT NOT NULL,
    target_label               TEXT NOT NULL,
    target_role                TEXT NOT NULL,
    target_capability          TEXT,
    target_container_id        TEXT NOT NULL,
    target_pane_id             TEXT NOT NULL,
    envelope_body              BLOB NOT NULL,                        -- raw bytes (FR-012a, Q1)
    envelope_body_sha256       TEXT NOT NULL,                        -- hex
    envelope_size_bytes        INTEGER NOT NULL,                     -- serialized envelope, not body
    enqueued_at                TEXT NOT NULL,                        -- ISO 8601 ms UTC (FR-012b)
    delivery_attempt_started_at TEXT,
    delivered_at               TEXT,
    failed_at                  TEXT,
    canceled_at                TEXT,
    last_updated_at            TEXT NOT NULL,
    operator_action            TEXT CHECK (operator_action IS NULL OR operator_action IN (
        'approved', 'delayed', 'canceled'
    )),
    operator_action_at         TEXT,
    operator_action_by         TEXT                                  -- agent_id or 'host-operator' sentinel
);

CREATE INDEX idx_message_queue_state_enqueued
    ON message_queue (state, enqueued_at, message_id);
CREATE INDEX idx_message_queue_target_enqueued
    ON message_queue (target_agent_id, enqueued_at, message_id);
CREATE INDEX idx_message_queue_sender_enqueued
    ON message_queue (sender_agent_id, enqueued_at, message_id);
CREATE INDEX idx_message_queue_in_flight
    ON message_queue (target_agent_id)
    WHERE delivery_attempt_started_at IS NOT NULL
      AND delivered_at IS NULL
      AND failed_at IS NULL
      AND canceled_at IS NULL;

CREATE TABLE daemon_state (
    key                       TEXT PRIMARY KEY CHECK (key IN ('routing_enabled')),
    value                     TEXT NOT NULL,
    last_updated_at           TEXT NOT NULL,
    last_updated_by           TEXT NOT NULL                          -- agent_id or 'host-operator'
);
```

The JSONL append target is the existing FEAT-001 / FEAT-008
`events.jsonl` file at `~/.local/state/opensoft/agenttower/
events.jsonl`. No new audit log path. The closed `queue_message_*`
event-type set (`queue_message_enqueued`, `queue_message_delivered`,
`queue_message_blocked`, `queue_message_failed`,
`queue_message_canceled`, `queue_message_approved`,
`queue_message_delayed`) is disjoint from FEAT-008's ten durable
types and FEAT-007's six lifecycle types by spec construction; a new
consolidated test (`test_jsonl_namespace_disjointness.py`) asserts
zero overlap across the closed sets.

**Testing**: pytest (≥ 7), reusing the FEAT-002..008 daemon harness in
`tests/integration/_daemon_helpers.py` verbatim — every FEAT-009
integration test spins up a real host daemon under an isolated `$HOME`
and drives the `agenttower` console script as a subprocess. The
existing test seams (`AGENTTOWER_TEST_DOCKER_FAKE`,
`AGENTTOWER_TEST_TMUX_FAKE`, `AGENTTOWER_TEST_PROC_ROOT`,
`AGENTTOWER_TEST_LOG_FS_FAKE`, `AGENTTOWER_TEST_EVENTS_CLOCK_FAKE`,
`AGENTTOWER_TEST_READER_TICK`) are reused unchanged. Two new test
seams are introduced:

- `AGENTTOWER_TEST_ROUTING_CLOCK_FAKE` — JSON-encoded
  `{"now_iso_ms_utc": <ISO-string>, "monotonic": <float>}` consumed
  by `routing.timestamps.now_iso_ms_utc()` and the worker's
  `time.monotonic()` budget so the delivery-wait timeout, the
  `enqueued_at` ordering, and the FR-040 recovery are deterministic
  in tests.
- `AGENTTOWER_TEST_DELIVERY_TICK` — a Unix domain socket path the
  delivery worker, when set, blocks on instead of polling between
  cycles; tests write one byte to the socket to advance the worker
  by exactly one row (or one no-op tick when no rows are ready).
  Mirrors FEAT-008's `AGENTTOWER_TEST_READER_TICK`.

Integration tests cover every US1 / US2 / US3 / US4 / US5 / US6
acceptance scenario plus the spec's 14+ edge cases. Unit tests cover:

- Envelope rendering: header set & ordering, blank-line separator,
  multi-line body preserved verbatim, FR-001 / FR-002 invariants,
  size cap applied to serialized envelope not raw body.
- Body validation: empty / non-UTF-8 / NUL / ASCII-control rejection
  with correct closed-set codes; size cap rejection with no SQLite
  write (FR-003, FR-004, SC-009).
- Excerpt pipeline: redact-first, collapse whitespace runs (incl.
  `\n`, `\t`, `\r`), truncate to 240 chars, append `…` only on
  overflow (FR-047b, Q3); unit-tested against every excerpt surface.
- Permission gate: full sender×target×role×liveness×routing matrix
  produces the correct closed-set `block_reason` with the FR-019
  precedence order; "send to self" is `target_role_not_permitted`.
- `--target` resolver: agent_id shape match → registry lookup; not
  agent_id shape → label lookup; multiple label matches →
  `target_label_ambiguous`; no match → `agent_not_found`.
- State machine: every allowed transition, every forbidden
  transition is rejected with `terminal_state_cannot_change` or
  the matching closed-set code (FR-014, FR-015, FR-033 – FR-036).
- Delivery worker: ordering invariants (FR-041 before tmux, FR-042
  before next pickup), per-target FIFO (degenerate under single
  worker but assertable), pre-paste re-check at delivery time
  (FR-025), failure-mode mapping to `failure_reason` closed set
  (FR-018, FR-043).
- Crash recovery: every (`delivery_attempt_started_at` set, terminal
  unset) row resolves to `failed` with `attempt_interrupted` before
  the worker resumes (FR-040, SC-004); no second tmux paste issued
  (call-count assertion); rows whose `delivery_attempt_started_at`
  was never stamped remain `queued` and deliverable (FR-012a, Q1).
- Kill switch: host-origin check accepts host, refuses bench
  container with `routing_toggle_host_only` (FR-027, Q2); `status`
  accepts both; row creation while disabled is `blocked` with
  `kill_switch_off`; in-flight rows finish (FR-028, Session 2 Q1).
- tmux delivery safety: every shell metacharacter from SC-003 is
  delivered byte-exact; no process-tree change between before-paste
  and after-paste snapshots; AST gate asserts no `shell=True`, no
  `os.system`, no `f"...{body}..."` in `SubprocessTmuxAdapter`.
- Schema migration v6 → v7: v6-only DB upgrade, v7-already-current
  re-open, forward-version refusal.
- Queue DAO: every filter combination, `(enqueued_at, message_id)`
  ordering stability, `--since` parse accepts both ms and seconds
  forms (Q5).
- CLI: `send-input` exit-code matrix, `queue` listing format,
  `queue approve/delay/cancel` exit codes, `routing` exit codes,
  `--json` schema validation against `contracts/queue-row-schema.md`
  JSON Schema, daemon-unreachable surface, host-vs-container parity.
- Audit: every state transition emits exactly one JSONL row, raw
  body excluded, host-operator sentinel used for host-originated
  transitions, degraded-JSONL buffered retry path (mirrors FEAT-008
  FR-029).

A backwards-compatibility test (`test_feat009_backcompat.py`) gates
the SC parallel to FEAT-008's by re-running every FEAT-001..008 CLI
command and asserting byte-identical stdout, stderr, exit codes, and
`--json` shapes.

**Target Platform**: Linux/WSL developer workstations. The daemon
continues to run exclusively on the host (constitution principle I);
FEAT-009 introduces zero new in-container processes. The delivery
worker is a single host-side thread that invokes `docker exec -u
<bench-user> <container-id> tmux ...` for every tmux call (reusing
the FEAT-004 invocation pattern, extended with four new tmux
subcommands). The CLI runs from inside a bench container as a
short-lived thin client (FEAT-005) for `send-input`, or from the host
or a bench container for `queue` / `routing status`, or from the host
only for `routing enable` / `routing disable`. No new network
listener.

**Project Type**: Single-project Python CLI + daemon. Extends
`src/agenttower/`. Three existing modules (`cli.py`,
`state/schema.py`, `socket_api/methods.py`) gain additive surfaces;
one existing module (`socket_api/errors.py`) gains 11 new closed-
set error codes; one existing module (`tmux/adapter.py`) gains four
new Protocol methods plus their `SubprocessTmuxAdapter` /
`FakeTmuxAdapter` implementations; one existing module
(`agents/identifiers.py`) gains one new reserved-id constant
(`HOST_OPERATOR_SENTINEL`); one existing module (`daemon.py`) gains
the delivery-worker thread lifecycle (recovery → start at boot →
graceful stop). The existing-but-empty `routing/` package gains nine
new modules. Zero existing modules have their semantics changed for
existing call sites.

**Performance Goals**:

- SC-001 — `send-input` to slave's tmux pane within ≤ 3 s under
  typical local conditions. The delivery worker wakeup latency is
  ≤ 100 ms (the `AGENTTOWER_TEST_DELIVERY_TICK` granularity in
  tests, `time.sleep(0.1)` between empty cycles in production);
  the `docker exec` + tmux paste round-trip is ≤ 1 s on a healthy
  local Docker; the SQLite commit budget is ≤ 50 ms per
  transition. SC-001 has comfortable margin.
- SC-009 — body-too-large rejection within ≤ 100 ms. The size
  check is in the submit-time `routing.envelope.serialize`
  function, runs BEFORE any SQLite write or `docker exec`, and
  fails in O(len(body)) bytes — sub-millisecond at the 64 KiB cap.
- Per-delivery budget breakdown: envelope render ≤ 1 ms, SQLite
  insert ≤ 5 ms, pre-paste re-check ≤ 50 ms (one
  `containers/list` + one `agents/get` call, both already cached
  in the daemon), `tmux load-buffer` ≤ 200 ms, `tmux paste-buffer`
  ≤ 100 ms, `tmux send-keys` ≤ 100 ms, `tmux delete-buffer` ≤ 50 ms,
  SQLite `delivered` commit ≤ 50 ms. Total ≤ 600 ms typical, well
  under the 3 s SC-001 budget.
- Worker memory bound: one row in flight at a time × ≤ 64 KiB
  envelope ≤ 64 KiB. The buffered audit deque is bounded by the
  `degraded_queue_audit_persistence` retention policy (mirrors
  FEAT-008's `_pending` cap at one cycle's worth of byte cap).

**Constraints**:

- Single delivery worker thread; cross-target parallelism deferred
  (Clarifications Q5).
- Envelope size cap: 65 536 bytes (64 KiB) serialized, configurable
  in `config.toml` `[routing]` section. Cap applies to the
  serialized envelope including headers (FR-004).
- Default `send-input` wait timeout: 10 s, configurable. `--no-wait`
  flag bypasses (FR-009).
- Default delivery attempt timeout: 5 s wall-clock from the
  `delivery_attempt_started_at` stamp to the final tmux command's
  return — if a tmux invocation hangs longer than this, the worker
  kills the subprocess and transitions the row to `failed` with
  `tmux_paste_failed` / `tmux_send_keys_failed` / `docker_exec_failed`
  depending on which step was outstanding (FR-018, FR-043).
- File modes: SQLite WAL files inherit FEAT-001's `0o600` /
  `0o700`; `events.jsonl` is owned by FEAT-001; FEAT-009 introduces
  zero new file modes. The new `daemon_state` table is in the same
  SQLite DB; no new file is created.
- No third-party dependencies beyond stdlib (project rule).

**Scale/Scope**: ≤ 50 attached agents, ≤ a few `send-input` per
minute per master under typical interactive use, peak ≤ ~10
deliveries/s sustained (queued behind the single worker). The
`message_queue` table grows unbounded (no retention in MVP —
Assumptions). At 10 rows/s × 86 400 s/day = 864 K rows/day under
sustained peak, ≤ 50 KB/row → ~40 GB/day. Operators own retention;
manual pruning via `agenttower queue` filters + SQLite delete is
allowed. Realistic interactive use yields orders of magnitude less.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | Justification |
|---|---|---|
| I. Local-First Host Control | **PASS** | The daemon, the `message_queue` table, the `daemon_state` table, the `events.jsonl` audit append, and the delivery worker all run host-side. The routing kill switch is host-only (Clarifications Q2 / FR-027). Bench containers run thin-client CLI over the Unix socket — no new network listener, no new in-container long-running process. All durable state remains under `~/.local/state/opensoft/agenttower/`. |
| II. Container-First MVP | **PASS** | FEAT-009 targets running bench containers and tmux panes inside them. Pane resolution reuses FEAT-004's `docker exec -u <bench-user>` pattern verbatim and extends it with the four new tmux subcommands (`load-buffer`, `paste-buffer`, `send-keys`, `delete-buffer`). No host-only tmux delivery. No relay or Python-thread-side input fabrication. |
| III. Safe Terminal Input | **PASS** | This is the principle FEAT-009 fulfills. Sender role is gated to registered active masters (FR-021); target role is gated to slave/swarm (FR-022); the kill switch is a single global override (FR-026 – FR-030); every delivery is queued and auditable (FR-046); shell-string interpolation of the body is prohibited at the tmux adapter Protocol contract and AST-gate-tested (FR-038). Unknown panes never receive input by spec construction — the delivery worker re-checks pane identity at attempt time and transitions the row to `blocked` with `target_pane_missing` rather than `docker exec` into a wrong pane (FR-025). |
| IV. Observable and Scriptable | **PASS** | Three new CLI subcommand groups, all supporting `--json`. SQLite holds the `message_queue` state of truth; `events.jsonl` carries the JSONL audit (FEAT-008 inheritance). The degraded-JSONL state surfaces through `agenttower status` (`degraded_queue_audit_persistence`). Every error is a closed-set code with a stable string form (FR-049). |
| V. Conservative Automation | **PASS** | The daemon never originates a `send-input` — every queue row is created by a `master` invoking the CLI (FR-008, FR-051). The daemon does not classify, summarize, or interpret the body (FR-053). No LLM call, no automatic arbitration (FR-052 — multi-master arbitration is deferred to FEAT-010). The kill switch is operator-controlled. The default approval policy is "no approval required" (Assumptions) — pause-by-default is deferred to a later feature. |

No constitution violations to justify; the Complexity Tracking section
is empty.

### Post-Phase-1 re-check (2026-05-11)

After generating `research.md`, `data-model.md`, `contracts/` (seven
files), and `quickstart.md`, the Constitution Check still passes on
all five principles. Specifically:

- **I (Local-First)** — Phase 1 confirms zero new network listener,
  zero new in-container long-running process. The two new SQLite
  tables (`message_queue`, `daemon_state`) live in the existing host
  state DB. JSONL audit reuses the existing FEAT-008 `events.jsonl`.
- **II (Container-First)** — Phase 1 confirms the extended tmux
  adapter Protocol uses the same `docker exec -u <bench-user> <id>
  tmux -S <socket-path> ...` pattern FEAT-004 established. No host-
  only delivery path.
- **III (Safe Terminal Input)** — Phase 1 hardens the safety
  guarantees: the tmux Protocol contract is bytes-typed; the AST
  gate (R-007) is concrete; the kill switch is enforced at the
  socket dispatch boundary with a closed-set rejection code; sender
  origin is gated by FEAT-005's pane-identity surface; per-message
  buffer scoping is mandatory.
- **IV (Observable and Scriptable)** — Phase 1 produces stable JSON
  Schemas for both the row contract (`queue-row-schema.md`) and the
  audit shape (`queue-audit-schema.md`), validates them against
  `jsonschema` in the quickstart, and locks the closed-set CLI
  exit-code map in `error-codes.md`. Failure modes have actionable
  closed-set codes; no silent degradation.
- **V (Conservative Automation)** — Phase 1 confirms the daemon
  never originates a queue row, never classifies body content,
  never makes routing decisions beyond the closed-set permission
  rules. Operator override is explicit, audited, and reversible.

Complexity Tracking remains empty.

## Project Structure

### Documentation (this feature)

```text
specs/009-safe-prompt-queue/
├── spec.md              # Clarified spec (2 clarification sessions)
├── plan.md              # This file
├── research.md          # Phase 0: tmux paste-buffer scoping, host-origin detection,
│                        #   shell-injection AST gate, body BLOB vs TEXT, deferred decisions
├── data-model.md        # Phase 1: message_queue + daemon_state schemas, state machine,
│                        #   closed sets, JSONL audit schema, identity capture
├── contracts/           # Phase 1: socket methods, CLI surface, JSON schemas, error vocab
│   ├── socket-queue.md
│   ├── socket-routing.md
│   ├── cli-send-input.md
│   ├── cli-queue.md
│   ├── cli-routing.md
│   ├── queue-row-schema.md
│   ├── queue-audit-schema.md
│   └── error-codes.md
├── quickstart.md        # Phase 1: end-to-end send-input + queue + kill switch demo
├── checklists/          # Already populated by /speckit.checklist
│   ├── requirements.md
│   ├── security.md
│   ├── api.md
│   ├── reliability.md
│   ├── data.md
│   ├── observability.md
│   └── ux.md
└── tasks.md             # NOT created by this command
```

### Source Code (repository root)

```text
src/agenttower/
├── routing/                          # PACKAGE EXISTS AS STUB — populate with the 11 modules below
│   ├── __init__.py                   # MODIFIED — re-exports public types + HOST_OPERATOR_SENTINEL
│   ├── envelope.py                   # NEW — render_envelope, validate_body, serialize
│   ├── excerpt.py                    # NEW — render_excerpt (redact → collapse → truncate → …)
│   ├── permissions.py                # NEW — evaluate_permissions(sender, target, routing) -> Decision
│   ├── target_resolver.py            # NEW — resolve_target(input_str, agents_service) -> ResolvedTarget
│   ├── dao.py                        # NEW — message_queue CRUD + state transitions; daemon_state CRUD
│   ├── service.py                    # NEW — QueueService façade consumed by socket methods
│   ├── kill_switch.py                # NEW — RoutingFlagService (read/toggle, host-origin enforcement)
│   ├── delivery.py                   # NEW — DeliveryWorker thread, FR-040 recovery, dispatch loop
│   ├── timestamps.py                 # NEW — now_iso_ms_utc, parse_since (millis & seconds forms)
│   ├── audit_writer.py               # NEW — QueueAuditWriter: FR-046 dual-write (SQLite events table + events.jsonl), degraded buffer, mapping per data-model §7.1
│   └── errors.py                     # NEW — closed-set error codes (re-exported from socket_api/errors.py)
├── tmux/
│   ├── adapter.py                    # MODIFIED — extend TmuxAdapter Protocol with 4 new methods
│   ├── subprocess_adapter.py         # MODIFIED — implement load_buffer/paste_buffer/send_keys/delete_buffer
│   ├── fakes.py                      # MODIFIED — FakeTmuxAdapter records every call
│   └── parsers.py                    # UNCHANGED
├── state/
│   ├── schema.py                     # MODIFIED — CURRENT_SCHEMA_VERSION 6 → 7,
│   │                                 #   add _apply_migration_v7 with message_queue + daemon_state DDL
│   ├── agents.py                     # UNCHANGED
│   ├── log_attachments.py            # UNCHANGED
│   ├── log_offsets.py                # UNCHANGED
│   ├── panes.py                      # UNCHANGED (target_pane_id captured at enqueue from current pane state)
│   ├── containers.py                 # UNCHANGED
│   └── bench_user.py                 # UNCHANGED
├── agents/
│   ├── identifiers.py                # MODIFIED — add HOST_OPERATOR_SENTINEL constant,
│   │                                 #   extend validate_agent_id_shape to refuse it on registration
│   └── (all other modules UNCHANGED)
├── socket_api/
│   ├── methods.py                    # MODIFIED — add 8 new method dispatchers + host-origin / sender-pane
│   │                                 #   gates at the dispatch boundary
│   ├── errors.py                     # MODIFIED — add 11 new closed-set error codes
│   └── server.py                     # UNCHANGED (request/response only)
├── cli.py                            # MODIFIED — add send-input / queue / routing subparsers + flags
├── daemon.py                         # MODIFIED — register QueueService + RoutingFlagService +
│                                     #   DeliveryWorker in DaemonContext; run FR-040 recovery at boot
│                                     #   BEFORE worker.start(); stop worker on graceful shutdown
└── events/                           # UNCHANGED (writer.append_event consumed verbatim for JSONL audit)

tests/
├── unit/
│   ├── test_routing_envelope.py                     # NEW — render + serialize + size cap
│   ├── test_routing_body_validation.py              # NEW — empty / non-UTF-8 / NUL / controls
│   ├── test_routing_excerpt_pipeline.py             # NEW — redact → collapse → truncate → …
│   ├── test_routing_permissions_matrix.py           # NEW — full role × liveness × routing matrix
│   ├── test_routing_target_resolver.py              # NEW — agent_id / label / ambiguous / not_found
│   ├── test_routing_state_machine.py                # NEW — every allowed + every forbidden transition
│   ├── test_routing_dao.py                          # NEW — CRUD + filter combinations + ordering
│   ├── test_routing_timestamps.py                   # NEW — ms UTC + parse_since round-trip
│   ├── test_routing_kill_switch.py                  # NEW — host-origin enforcement + status read
│   ├── test_delivery_worker_ordering.py             # NEW — FR-041 before tmux, FR-042 before next pickup
│   ├── test_delivery_worker_recovery.py             # NEW — FR-040 recovery, no second paste
│   ├── test_delivery_worker_in_flight_kill_switch.py # NEW — Session 2 Q1: in-flight rows finish
│   ├── test_delivery_worker_pre_paste_recheck.py    # NEW — FR-025
│   ├── test_delivery_worker_failure_modes.py        # NEW — tmux/docker error → failure_reason mapping
│   ├── test_tmux_adapter_load_buffer.py             # NEW — argv-only invocation, stdin body bytes
│   ├── test_tmux_adapter_paste_buffer.py            # NEW — argv-only, buffer scoped per message
│   ├── test_tmux_adapter_send_keys.py               # NEW — argv-only, single Enter
│   ├── test_tmux_adapter_delete_buffer.py           # NEW — buffer cleared after delivery
│   ├── test_no_shell_string_interpolation.py        # NEW — AST gate (FR-038)
│   ├── test_schema_migration_v7.py                  # NEW — v6 upgrade, v7 re-open, forward refusal
│   ├── test_host_operator_sentinel.py               # NEW — registry refuses host-operator agent_id
│   ├── test_jsonl_namespace_disjointness.py         # NEW — FEAT-007 / 008 / 009 event_type sets disjoint
│   └── (existing FEAT-001..008 unit tests UNCHANGED)
├── integration/
│   ├── test_queue_us1_master_to_slave.py            # NEW — US1 acceptance scenarios 1-5
│   ├── test_queue_us2_permission_matrix.py          # NEW — US2 acceptance scenarios + SC-002
│   ├── test_queue_us3_operator_overrides.py         # NEW — US3 + SC-008
│   ├── test_queue_us4_kill_switch.py                # NEW — US4 + SC-005 + Session 2 Q1
│   ├── test_queue_us5_shell_injection.py            # NEW — US5 + SC-003
│   ├── test_queue_us6_restart_recovery.py           # NEW — US6 + SC-004
│   ├── test_queue_host_container_parity.py          # NEW — host-vs-container CLI parity for queue/routing
│   ├── test_queue_send_input_host_refused.py        # NEW — Q3: host-side send-input rejected
│   ├── test_queue_routing_toggle_host_only.py       # NEW — Q2: bench-container toggle rejected
│   ├── test_queue_target_resolver_integration.py    # NEW — agent_id + label + ambiguous + not_found end-to-end
│   ├── test_queue_audit_jsonl.py                    # NEW — queue_message_* event types in events.jsonl
│   ├── test_queue_degraded_audit.py                 # NEW — degraded_queue_audit_persistence buffered retry
│   └── test_feat009_backcompat.py                   # NEW — every FEAT-001..008 CLI byte-identical
└── conftest.py                       # MODIFIED — register AGENTTOWER_TEST_ROUTING_CLOCK_FAKE,
                                      #   AGENTTOWER_TEST_DELIVERY_TICK
```

**Structure Decision**: Single-project Python CLI + daemon, mirroring
the package-per-domain split established by FEAT-003 (`discovery/`),
FEAT-004 (`tmux/`), FEAT-005 (`config_doctor/`), FEAT-006 (`agents/`),
FEAT-007 (`logs/`), and FEAT-008 (`events/`). The empty `routing/`
stub package is populated by FEAT-009 with nine new modules. No new
top-level package is introduced. The tmux adapter Protocol gains four
new methods (additive); the agents identifier module gains one
reserved-id constant (additive); every other module touched is
strictly additive.

## Implementation Notes

### Defaults locked (FR-004, FR-009 obligations)

The MVP defaults named in the spec are codified in `config.toml`
under a new `[routing]` section. The values below are also encoded as
constants in `src/agenttower/routing/__init__.py` so the daemon can
boot without a config file.

| Setting | Default | Spec ref |
|---|---|---|
| `envelope_body_max_bytes` | `65536` (64 KiB) | FR-004, SC-009 |
| `excerpt_max_chars` | `240` | FR-011, FR-047b, Q3 |
| `excerpt_truncation_marker` | `"…"` (U+2026) | FR-047b |
| `send_input_default_wait_seconds` | `10.0` | FR-009, Assumptions |
| `delivery_attempt_timeout_seconds` | `5.0` | FR-018, FR-043 |
| `delivery_worker_idle_poll_seconds` | `0.1` | (internal) |
| `degraded_audit_buffer_max_rows` | `1024` | FR-048 (mirrors FEAT-008 FR-040) |
| `submit_keystroke` | `"Enter"` | FR-037, Assumptions |

`agenttower config paths` is extended to surface a `[routing]`
subsection (mirroring the FEAT-008 `[events]` extension).

### Timestamp encoding (Session 2 Q5 / FR-012b)

A single helper `routing.timestamps.now_iso_ms_utc() -> str` returns
the canonical form `YYYY-MM-DDTHH:MM:SS.sssZ` (e.g.,
`2026-05-11T15:32:04.123Z`). Implementation:

```python
def now_iso_ms_utc(clock: Clock = _SystemClock()) -> str:
    dt = clock.utcnow()  # tz-aware datetime.now(tz=datetime.UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
```

SQLite columns, `events.jsonl` rows, and `--json` outputs all store
the string verbatim. The `--since` parser
(`routing.timestamps.parse_since`) accepts both:

- `2026-05-11T15:32:04.123Z` (canonical, millisecond-precise)
- `2026-05-11T15:32:04Z` (seconds-precise, operator convenience)

and returns a tz-aware UTC `datetime`. Anything else →
closed-set `body_invalid_chars`-style error
`since_invalid_format` (NEW, added to the FR-049 vocabulary).

### `--target` resolver (Session 2 Q2)

The resolver lives in `routing.target_resolver.resolve_target`:

```python
def resolve_target(
    input_str: str,
    agents_service: AgentsService,
) -> ResolvedTarget:
    if AGENT_ID_RE.match(input_str):
        record = agents_service.get_agent_by_id(input_str)
        if record is None:
            raise TargetResolveError("agent_not_found")
        return ResolvedTarget.from_record(record)
    matches = agents_service.find_agents_by_label(
        input_str, only_active=True,
    )
    if len(matches) == 0:
        raise TargetResolveError("agent_not_found")
    if len(matches) > 1:
        raise TargetResolveError("target_label_ambiguous")
    return ResolvedTarget.from_record(matches[0])
```

Shape detection uses FEAT-006's `AGENT_ID_RE` (`^agt_[0-9a-f]{12}$`).
The spec's mention of "UUIDv4 textual form" in the
Q2 / Q3 / FR-006 wording is a reference to "the registered agent_id
shape" — see Implementation Deviation §1 for the spec-vs-code
reconciliation.

### Host-origin and sender-pane enforcement (Q2 / Q3)

The socket_api layer enriches every request envelope with a
`CallerContext` derived at the connection accept stage from
`SO_PEERCRED` (the existing FEAT-005 mechanism). The context carries:

- `peer_uid` — always populated.
- `caller_pane` — populated when the caller is a bench-container
  thin client (FEAT-005's pane-identity surface); `None` otherwise.

Two boundary checks are added at the `methods.py` dispatch layer:

- `send-input` → reject with `sender_not_in_pane` if
  `caller_pane is None`. If pane is set, look up the registered
  active agent by `(container_id, pane_composite_key)`; if not
  master → `sender_role_not_permitted`.
- `routing.enable` / `routing.disable` → reject with
  `routing_toggle_host_only` if `caller_pane is not None`. The
  daemon process's uid is the same as the host user's uid (FEAT-001
  invariant), so `peer_uid == os.getuid()` is necessary but not
  sufficient; the pane-absence check is the discriminator.

`routing.status` accepts both contexts (pane present or absent).

For the **operator-action endpoints** (`queue.approve` / `queue.delay`
/ `queue.cancel`), the dispatch layer adds a third boundary check
(Group-A walk Q8): if `caller_pane is not None`, resolve the pane
through `agents_service` and require `active=true`. If the resolved
agent is missing or inactive, refuse the call with the new closed-set
`operator_pane_inactive` (CLI exit code 21). Host-origin callers
(pane absent) bypass this check and write the `host-operator`
sentinel into `operator_action_by`. This prevents operator-action
audit rows from carrying stale or deregistered agent identities.

### Envelope rendering (FR-001, FR-002)

```text
Message-Id: <uuidv4>
From: <sender-agent_id> "<sender-label>" <sender-role> [capability=<…>]
To: <target-agent_id> "<target-label>" <target-role> [capability=<…>]
Type: prompt
Priority: normal
Requires-Reply: yes

<body bytes verbatim, including \n and \t>
```

Implementation: `routing.envelope.render_envelope(message, body_bytes)
-> bytes`. The header section is ASCII (UTF-8 by construction since
labels are FEAT-006-validated as ASCII-safe per their FR-005). The
blank line separator is exactly `\n\n`. The body is appended verbatim.
Size cap (FR-004) is enforced against `len(rendered_bytes)` AFTER
construction; rejection produces `body_too_large` and no SQLite row.

### Delivery worker loop (single thread, serial)

```python
def run_loop(self):
    self._run_recovery_pass()   # FR-040, runs once at startup
    while not self._stop.is_set():
        # Group-A Q4: stop() sets _stop; we exit immediately without draining in-flight rows.
        self._drain_buffered_audits()           # FR-048 degraded-JSONL drain on every cycle
        if not self._routing_flag.is_enabled():
            self._stop.wait(self._idle_poll_seconds)
            continue
        row = self._dao.pick_next_ready_row()   # (state='queued') ORDER BY enqueued_at, message_id
        if row is None:
            self._stop.wait(self._idle_poll_seconds)
            continue
        self._deliver_one(row)

def _deliver_one(self, row):
    # FR-025 pre-paste re-check. Group-A Q7: SQLite reads inside the recheck use
    # the same bounded retry helper; persistent lock → SqliteLockConflict.
    try:
        recheck = self._permissions.recheck_target_only(row)
    except SqliteLockConflict:
        self._dao.transition_queued_to_failed(row.message_id, "sqlite_lock_conflict")
        self._audit.append(..., to_state="failed", reason="sqlite_lock_conflict")
        return
    if recheck.blocked:
        self._dao.transition_queued_to_blocked(row.message_id, recheck.block_reason)
        self._audit.append(..., from_state="queued", to_state="blocked", reason=recheck.block_reason)
        return

    # FR-041 stamp BEFORE any tmux call (also wrapped in the bounded-retry helper inside the DAO).
    try:
        self._dao.stamp_delivery_attempt_started(row.message_id, self._clock.now_iso_ms_utc())
    except SqliteLockConflict:
        # Row is still 'queued'; the next cycle will retry. No audit emit here
        # because no state change happened.
        return

    buffer_name = f"agenttower-{row.message_id}"
    body = self._dao.read_envelope_bytes(row.message_id)
    load_succeeded = False
    try:
        self._tmux.load_buffer(row.target_container_id, ..., buffer_name, body)
        load_succeeded = True
        self._tmux.paste_buffer(..., row.target_pane_id, buffer_name)
        self._tmux.send_keys(..., row.target_pane_id, "Enter")
    except TmuxError as exc:
        # Group-A Q1: best-effort buffer cleanup if load_buffer already succeeded.
        if load_succeeded:
            try:
                self._tmux.delete_buffer(..., buffer_name)
            except TmuxError:
                self._log.warning("delete_buffer cleanup failed for %s", row.message_id)
        # Row transitions to failed with the original failure_reason.
        try:
            self._dao.transition_queued_to_failed(row.message_id, exc.failure_reason)
            self._audit.append(..., to_state="failed", reason=exc.failure_reason)
        except SqliteLockConflict:
            # Recovery on next boot will catch this row via FR-040.
            self._log.error("could not commit failure for %s; deferred to recovery", row.message_id)
        return

    # Paste+submit succeeded. Group-A Q2: cleanup failure here does NOT downgrade
    # the row's terminal state; the body has already been delivered.
    try:
        self._tmux.delete_buffer(..., buffer_name)
    except TmuxError:
        self._log.warning("orphaned tmux buffer %s after successful delivery", buffer_name)
        self._status.mark_orphaned_buffer(buffer_name)

    # FR-042 commit BEFORE picking the next row.
    try:
        self._dao.transition_queued_to_delivered(row.message_id, self._clock.now_iso_ms_utc())
        self._audit.append(..., to_state="delivered")
    except SqliteLockConflict:
        # Recovery on next boot will see delivery_attempt_started_at set + delivered_at unset
        # and transition this row to failed/attempt_interrupted. Operator visibility via audit
        # is degraded for this row only.
        self._log.error("could not commit delivered for %s; deferred to recovery", row.message_id)
```

The recovery pass (FR-040) is a single SQLite statement:

```sql
UPDATE message_queue
SET state = 'failed',
    failure_reason = 'attempt_interrupted',
    failed_at = ?,
    last_updated_at = ?
WHERE delivery_attempt_started_at IS NOT NULL
  AND delivered_at IS NULL
  AND failed_at IS NULL
  AND canceled_at IS NULL;
```

followed by one JSONL audit emission per affected row. The recovery
pass completes BEFORE `DeliveryWorker.start()` is called — enforced
by daemon boot ordering and tested at call-count granularity.

### Excerpt pipeline (FR-047b / Q3)

```python
def render_excerpt(body_bytes: bytes, redactor, cap: int = 240) -> str:
    raw_str = body_bytes.decode("utf-8")  # validated earlier; raises only if FR-003 was bypassed
    redacted = redactor.redact_one_line(raw_str)
    collapsed = re.sub(r"\s+", " ", redacted)   # collapse \n, \t, \r, space runs
    if len(collapsed) <= cap:
        return collapsed
    return collapsed[:cap] + "…"           # … on truncation
```

Tested against every excerpt surface: queue listing column, audit
`excerpt` field, `send-input --json` `excerpt` field. The pipeline
is pure — same input always produces the same output, no clock
dependence, no I/O.

### tmux adapter Protocol extension (FR-037, FR-038, FR-039)

```python
class TmuxAdapter(Protocol):
    # Existing FEAT-004 methods unchanged ...

    def load_buffer(
        self,
        container_id: str,
        bench_user: str,
        socket_path: str,
        buffer_name: str,
        body: bytes,
    ) -> None: ...
    """Invoke `docker exec -u <bench_user> <container_id> tmux -S
    <socket_path> load-buffer -b <buffer_name> -` with body piped via
    stdin (subprocess input=body). MUST NOT shell-escape body."""

    def paste_buffer(
        self,
        container_id: str,
        bench_user: str,
        socket_path: str,
        pane_id: str,
        buffer_name: str,
    ) -> None: ...

    def send_keys(
        self,
        container_id: str,
        bench_user: str,
        socket_path: str,
        pane_id: str,
        key: str,    # closed set in production: "Enter" only
    ) -> None: ...

    def delete_buffer(
        self,
        container_id: str,
        bench_user: str,
        socket_path: str,
        buffer_name: str,
    ) -> None: ...
```

`SubprocessTmuxAdapter` implements each with `subprocess.run(args=[...],
input=body if body else None, check=False, stdout=PIPE, stderr=PIPE,
timeout=routing.config.delivery_attempt_timeout_seconds)` and maps
non-zero return codes / `TimeoutExpired` / `FileNotFoundError` to
the closed-set `failure_reason` values via the existing `TmuxError`
type (extended with the new `failure_reason` field for FR-018
mapping).

The shell-injection AST gate
(`tests/unit/test_no_shell_string_interpolation.py`) walks
`subprocess_adapter.py` with the `ast` module and asserts:

- No `subprocess.run(..., shell=True)` call exists.
- No `os.system(...)` call exists.
- Every `subprocess.run` call's `args` is a list literal whose
  elements are either string literals or `ast.Name` references to
  parameters — never an f-string, `.format(...)`, or `%` formatting
  of the `body` parameter.

### JSONL audit append + degraded path (FR-046, FR-048)

Append flow per state transition:

```python
def append_queue_audit(self, message_id, from_state, to_state, reason, operator, ts):
    record = {
        "schema_version": 1,
        "event_type": f"queue_message_{to_state}",  # or the operator-driven variant
        "message_id": message_id,
        "from_state": from_state,
        "to_state": to_state,
        "reason": reason,                           # nullable
        "operator": operator,                       # agent_id or HOST_OPERATOR_SENTINEL or None
        "observed_at": ts,
        "excerpt": ...,                             # redacted, ≤ 240 chars (see excerpt pipeline)
    }
    try:
        events.writer.append_event(self._jsonl_path, record)
    except OSError as exc:
        self._buffer_for_retry(record, exc)
        self._status.mark_degraded("queue_audit", str(exc))
```

The buffered retry path mirrors FEAT-008's `_pending` deque pattern.
On every worker cycle, the worker drains the buffer first
(`drain_buffered_audits()`) before picking the next ready row.

### Recovery + worker startup ordering

`daemon.py` boot sequence (additive):

```python
# ... existing FEAT-001..008 init ...

routing_dao = MessageQueueDao(state_db)
routing_flag = RoutingFlagService(state_db)
queue_service = QueueService(routing_dao, routing_flag, agents_service, ...)
delivery_worker = DeliveryWorker(
    routing_dao, routing_flag, tmux_adapter, audit_writer, clock,
)

# FR-040: recovery MUST run before the worker thread starts.
delivery_worker.run_recovery_pass()

# Now safe to start the worker thread.
delivery_worker.start()
ctx.register_shutdown_hook(delivery_worker.stop)
```

`run_recovery_pass()` is a synchronous method that does the
recovery `UPDATE` + per-row JSONL audit emits before returning.
`start()` spawns the worker thread; the thread's first action is
its main loop (the recovery pass is NOT inside the loop — it ran
already). A unit test asserts the call order at function-mock
granularity (FR-040 SC-004 requirement).

## Implementation Deviations

None for FEAT-009 in the strict "spec says X, plan does Y" sense.
Three points are worth flagging because they look like deviations on
first read but are explicit reconciliations of spec wording against
existing FEAT-001..008 code:

### 1. `--target` shape detection uses `AGENT_ID_RE`, not literal UUIDv4

The spec's Clarifications session 2 Q2 wording — "if the supplied
value matches the `agent_id` shape (UUIDv4 textual form), it MUST be
resolved as `agent_id`" — references "UUIDv4 textual form" as the
shape descriptor. However, the actual FEAT-006 agent_id shape is
`agt_<12-hex>` (`AGENT_ID_RE` from `src/agenttower/agents/
identifiers.py`), NOT UUIDv4. The plan reconciles this by:

- Using `AGENT_ID_RE` in the `--target` resolver (the spec's intent
  is shape detection against the registered identifier, not literal
  UUIDv4 detection).
- Keeping the spec's `message_id` field as a true UUIDv4 (FR-001),
  since `message_id` is a FEAT-009 internal queue identifier with no
  prior FEAT-001..008 convention to honor and the spec explicitly
  chose UUIDv4 for it.

This is documented in `research.md` §"Target shape detection" with
the spec quote, the code reference, and the reconciliation rationale.
No spec amendment is required because the spec's intent ("shape
match against the registered agent_id form") is preserved; only the
literal "UUIDv4" descriptor is reinterpreted as "the registered
agent_id shape."

### 2. `envelope_body` is `BLOB`, not `TEXT`

The spec wording in FR-012 calls `envelope_body` "raw body bytes,
always persisted verbatim." The natural SQLite affinity for raw byte
preservation is `BLOB`, not `TEXT`. SQLite's `TEXT` affinity applies
implicit encoding conversions when the connection's `text_factory`
is unset; a body containing valid UTF-8 plus a literal `\x00` byte
would round-trip incorrectly through `TEXT`. The plan locks
`envelope_body BLOB NOT NULL` to guarantee the FR-012a byte-exact
round-trip. The spec does not specify SQL affinity, so this is a
pure planning decision, not a deviation.

### 3. `daemon_state` is a new table, not a column on an existing table

FR-026 says "System MUST persist a single boolean routing flag in
`daemon_state`." The natural reading is that `daemon_state` is a
key/value table (one row per key). The plan creates a new
`daemon_state` table with a CHECK constraint pinning `key` to the
closed set `{'routing_enabled'}` for MVP. Future single-row daemon
flags (e.g., a maintenance-mode flag) extend the CHECK constraint
without schema migration. A spec-side alternative — using a column
on an existing table — was considered and rejected: no existing
table has the right cardinality (containers, agents, panes, log_*
are all many-rows-per-thing), and a flag like "routing enabled" has
no natural foreign-key parent.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No constitution violations. This section intentionally empty.
