# Phase 0 Research: Event-Driven Routing and Multi-Master Arbitration

**Branch**: `010-event-routes-arbitration` | **Date**: 2026-05-16 | **Plan**: [plan.md](./plan.md)

This document records the technical decisions taken during the plan
phase. Each section follows the format **Decision → Rationale →
Alternatives considered**. Items resolved by the spec's
`## Clarifications` section are summarized briefly; the spec itself
is the source of truth for those.

---

## R1. Routing worker concurrency model

**Decision**: Single-threaded sequential worker. One cycle in flight
at a time; within a cycle, routes are processed strictly
sequentially in `(created_at, route_id)` order; one route's batch
(up to `batch_size` events) completes before the next route starts.

**Rationale**:
- Directly satisfies SC-010 (byte-for-byte deterministic replay)
  without requiring commit-order barriers, work stealing, or any
  worker-pool sizing knob.
- Eliminates SQLite write contention between concurrent route
  cycles (the cursor-advance-with-enqueue transaction in FR-012 is
  already serializing).
- Matches FEAT-008's classifier-worker pattern (one thread, simple
  loop) so operators reading both event-ingest and routing
  observability surfaces see consistent semantics.
- The per-route batch cap (FR-041 default 100) + 1s cycle interval
  (FR-040) bound worst-case latency at the MVP scale; parallelism
  would add complexity for a workload that is I/O-light.

**Alternatives considered**:
- Per-route concurrency within a cycle (one thread per route):
  rejected — adds worker-pool sizing as a config knob, requires an
  explicit commit-barrier protocol to preserve replay determinism,
  and provides no measurable benefit at the target scale.
- Per-route serial with overlapping cycles (cycle N+1 starts before
  cycle N's last route finishes): rejected — cycles become a soft
  scheduling boundary rather than a synchronization point, which
  makes test fixtures harder to reason about.

**Locked by**: Clarifications Session 2026-05-16 Q4 → spec §FR-014
(revised).

---

## R2. Cursor-advance + enqueue transaction shape

**Decision**: One `BEGIN IMMEDIATE` SQLite transaction per
`(route, event)` evaluation. Cursor `UPDATE` and queue `INSERT`
(when enqueuing) commit together. On skip, the cursor UPDATE is
the only mutation in the transaction. On transient internal error
(SQLite lock, `RoutingDegraded`), the transaction rolls back and
the cursor stays at the previous value; the event is re-evaluated
next cycle.

**Rationale**:
- Eliminates the duplicate-routing window (Story 4 #1 + #2): if the
  daemon crashes mid-transaction, neither side commits, and the
  next cycle re-evaluates from the unchanged cursor.
- `BEGIN IMMEDIATE` (as opposed to `BEGIN DEFERRED`) acquires the
  write lock at the start of the transaction, so contention with
  other writers (delivery worker, CLI catalog ops) fails fast
  rather than mid-transaction.
- Matches FEAT-009's per-row-state-transition `BEGIN IMMEDIATE`
  pattern.

**Alternatives considered**:
- Two-step "advance cursor, then enqueue" without transaction:
  rejected — opens the Story 4 #1 duplicate window.
- "Enqueue first, then advance cursor" without transaction:
  rejected — opens the "advanced cursor without queue row" window
  (worse: the event is silently skipped on restart).
- `SAVEPOINT`-nested transactions to share with FEAT-009's
  internals: rejected — adds complexity for no benefit since
  FEAT-010's transaction is the outermost one for its work.

**Defense-in-depth**: A partial UNIQUE index on
`message_queue(route_id, event_id) WHERE origin='route'` (FR-030)
catches any logic bug that issues a second insert; SQLite raises
`UNIQUE constraint failed` and the worker surfaces a closed-set
`routing_duplicate_insert` internal error.

---

## R3. Source-scope grammar (role+capability filter)

**Decision**: `source_scope_value` for `kind=role` parses as
`role:<role>[,capability:<cap>]` — the same grammar as
`target_value` under `target_rule=role`. One parser shared between
`source_scope.py` and `target_resolver.py` via an internal helper
`_parse_role_capability(raw: str) -> tuple[str, str | None]`.
Matching requires both role AND capability to match when capability
is present; capability-absence matches any capability.

**Rationale**:
- Symmetry with target reduces operator learning surface and
  validation code duplication.
- One parser, one validator, one set of error messages.
- Operators who want capability-filtered source scope (e.g., "react
  only to events from `codex`-capable slaves") can express it
  without splitting into N routes.

**Alternatives considered**:
- Role-only source scope (asymmetric with target): rejected for
  user-surprise (different grammars for symmetric concepts) and
  for forcing operators into per-source-agent routes when a
  capability filter would do.
- Role-only now, capability filter later: rejected because adding
  capability later would require a column-format migration; doing
  it now is column-format-compatible.

**Locked by**: Clarifications Session 2026-05-16 Q1 → spec §FR-001,
§FR-006, §FR-010, §FR-049.

---

## R4. Audit target identity on `route_matched` / `route_skipped`

**Decision**: Every `route_matched` and `route_skipped` audit row
carries `target_agent_id` and `target_label` as first-class
top-level fields. `target_agent_id` is `null` only when target
resolution never completed (skip reasons `no_eligible_master` and
`no_eligible_target`); `target_label` is `null` whenever
`target_agent_id` is null.

**Rationale**:
- Satisfies SC-008 (one JSONL line is enough to reconstruct why a
  skip happened) for target-related skip reasons
  (`target_not_found`, `target_role_not_permitted`, etc.) — those
  reasons produce no `queue_message_*` row, so the target identity
  has nowhere else to live.
- Removes the need for audit consumers to join with `message_queue`
  for the matched case.
- Uniform grammar across the two per-(route, event) audit types
  (only difference is the `reason` field on `route_skipped` and
  the `winner_master_agent_id` field's nullability).

**Alternatives considered**:
- Target fields on `route_matched` only: rejected — target-related
  skips would still need a separate join, defeating SC-008 for
  exactly the cases operators most need to debug.
- Audit a synthetic `attempted_target_value` (raw rule value)
  instead of resolved identity: rejected — operators want the
  resolved agent_id, not the rule string that produced it.

**Locked by**: Clarifications Session 2026-05-16 Q2 → spec §FR-036.

---

## R5. Cycle observability: heartbeat vs per-cycle audit

**Decision**: No per-cycle `routing_cycle_started` /
`routing_cycle_completed` audit entries. Instead, a separate
heartbeat thread emits one `routing_worker_heartbeat` JSONL entry
every `interval_seconds` (default 60s, bounds `[10, 3600]`)
regardless of cycle activity, carrying aggregate counts since the
last heartbeat (`cycles_since_last_heartbeat`,
`events_consumed_since_last_heartbeat`,
`skips_since_last_heartbeat`) plus a `degraded` boolean mirroring
the `routing_worker_degraded` status field.

**Rationale**:
- A per-cycle audit at the default 1s interval would emit ~172,800
  lines/day even when zero events match — drowning out real audit
  signal in `agenttower events --follow`.
- `agenttower status` already exposes `last_routing_cycle_at` and
  per-reason skip counts; the heartbeat is a supplementary JSONL-
  only liveness signal for operators who don't poll status.
- A separate thread (rather than the worker emitting the
  heartbeat) means a long routing cycle never delays a heartbeat
  and a slow JSONL write never delays a routing cycle.

**Alternatives considered**:
- Per-cycle audit always: rejected — noise volume.
- Per-cycle audit on non-quiet cycles only: rejected — "is the
  worker alive?" still requires polling status during quiet
  periods, missing the value of a JSONL liveness signal.
- No JSONL cycle signal at all (status only): rejected — leaves
  JSONL-only monitoring without a liveness signal.

**Locked by**: Clarifications Session 2026-05-16 Q3 → spec §FR-035,
§FR-039a.

---

## R6. Route immutability

**Decision**: Routes are structurally immutable post-creation. No
`route update` CLI; no `routes.update` socket method. Only
`enable`/`disable` may change an existing row. Selectors,
targeting, master selection, and template can only be changed via
`route remove` + `route add` — the replacement gets a new
`route_id` and a fresh cursor at current event head per FR-002.

**Rationale**:
- An in-place edit creates ambiguity: does changing `event_type`
  reset the cursor? Do pending matches under the old selector stay
  pending? Should fan-out apply retroactively? Eliminating mutation
  eliminates all three questions.
- `remove` + `add` is auditable (`route_deleted` + `route_created`
  in JSONL); the operator can copy `route show --json` output,
  edit it, and re-add.
- The cursor-reset-on-recreation is deliberate and visible, not a
  hidden side effect of editing.

**Alternatives considered**:
- `route update` that preserves cursor: rejected — operators would
  be surprised when a `event_type` change retroactively pulls in
  events that the new selector now matches.
- `route update` that resets cursor on selector change only:
  rejected — splits update semantics by field, hard to document.

**Locked by**: Clarifications Session 2026-05-16 Q5 → spec
§FR-009a.

---

## R7. Single insert path for `message_queue`

**Decision**: `routing.service.QueueService.send_input(...)` gains
three keyword-only arguments — `_origin`, `_route_id`, `_event_id`
— that the socket dispatch path does NOT forward (the leading
underscore signals "in-process only"). A new public method
`enqueue_route_message(...)` is the FEAT-010 entry point; it calls
the same internal helper as `send_input` with `_origin='route'`.

**Rationale**:
- Preserves the FEAT-009 invariant that there is exactly ONE code
  path between the socket boundary and the SQLite insert.
- All FEAT-009 checks (body validation, permission gate, kill
  switch, per-target FIFO) apply to FEAT-010 inserts automatically.
- The keyword-only arguments cannot leak to the socket path
  because the socket dispatcher passes only positional + named
  arguments by explicit allowlist — adding `_route_id` to the
  allowlist would require an explicit change visible in code
  review.

**Alternatives considered**:
- Two parallel insert helpers (one for direct, one for route):
  rejected — duplicates the body-validation / permission /
  kill-switch / FIFO code path and creates two surfaces for the
  next bug to hide in.
- Make `route_id`/`event_id` public arguments on `send_input`:
  rejected — operators using `agenttower send-input` should never
  see route metadata in the help text.

---

## R8. Active-master snapshot timing

**Decision**: Each `(route, event)` evaluation reads a fresh
active-master snapshot via `agents_service.list_active(role=
'master')` inside its transaction. The snapshot is captured at the
moment of arbitration evaluation and used as the input to
`arbitration.pick_master(...)`; the winner identity is locked in
at that moment per FR-020.

**Rationale**:
- Within a cycle, the active-master set may legitimately change
  (an operator deregisters a master between events). A fresh
  snapshot per event gives the operator's most-recent state effect
  on the next event without surprising semantics.
- Across daemon restarts, the same input event sequence produces
  the same snapshots (the agents table is deterministic given the
  same registration history), so SC-010 holds.
- Snapshot inside the transaction means a concurrent agent
  deregistration (CLI calls `agents.deactivate`) is either fully
  visible or fully invisible to the snapshot — never partially
  visible.

**Alternatives considered**:
- One snapshot per cycle (cached across all routes/events): rejected
  — surprising "I deregistered the master 10 seconds ago, why is
  it still receiving routes?" behavior at the cycle boundary.
- Cached for the whole `_process_route_batch` of one route:
  rejected — same surprise within a long batch.

**Locked by**: spec §FR-020 + Edge Cases section "Master is
deregistered between arbitration and queue insert".

---

## R9. Template grammar restrictions

**Decision**: Templates are plain UTF-8 strings with `{<field>}`
placeholders drawn from a closed whitelist of 8 fields (`event_id`,
`event_type`, `source_agent_id`, `source_label`, `source_role`,
`source_capability`, `event_excerpt`, `observed_at`). No nested
interpolation, no expressions, no function calls, no escape
sequences beyond the `{` literal becoming `{{` (and `}` becoming
`}}`) — matching Python's `str.format` literal-brace convention.
Template-parse-time validation catches unknown fields; render-time
validation catches missing fields (theoretically impossible if
parse-time validation passes, but defended).

**Rationale**:
- Smallest possible interpretation primitive that satisfies the
  use cases (event echoing + structured prompts).
- No templating-engine dependency (Jinja2, Mako, etc.) keeps the
  stdlib-only constraint.
- Closed whitelist makes the security review trivial: every field
  that crosses into another agent's input stream is enumerated;
  `{event_excerpt}` (the only field that could contain attacker-
  controlled content) is routed through FEAT-007 redaction; the
  other seven are operator-controlled or daemon-generated.

**Alternatives considered**:
- Jinja2: rejected — adds dependency, sandboxing surface, learning
  curve.
- Python f-string compile: rejected — `eval`-adjacent, opens
  arbitrary expression injection.
- Go-template-style `{{ .field }}`: rejected — closer to expression
  language than substitution, adds parsing complexity.

---

## R10. SQLite schema migration v7 → v8

**Decision**: Single new table (`routes`), three new columns on
`message_queue` (one `NOT NULL DEFAULT 'direct'`, two `NULL`), one
new index on `routes`, one partial UNIQUE index on `message_queue`.
Migration is idempotent under the existing
`_apply_pending_migrations` framework (each `CREATE TABLE` /
`CREATE INDEX` uses `IF NOT EXISTS`; each `ALTER TABLE ADD
COLUMN` is preceded by a `PRAGMA table_info` check that returns
the existing columns and short-circuits if the column already
exists).

**Rationale**:
- Backward-compatible: existing `message_queue` rows get
  `origin='direct'` via the `DEFAULT` clause; no FEAT-009 code
  path changes are required.
- Partial UNIQUE index (`WHERE origin = 'route'`) keeps the
  uniqueness constraint scoped to route-generated rows and avoids
  any SQLite quirk with NULL semantics in regular UNIQUE indexes.
- Idempotent under partial-completion: an interrupted migration
  (column added, index not yet created) is safe to resume.

**Alternatives considered**:
- Separate `route_message_queue` table linked by FK: rejected —
  duplicates the FEAT-009 state machine, breaks the
  "FEAT-009 plumbing is the only plumbing" promise, and forces
  every queue inspection query to UNION two tables.
- Add `origin` as a separate enum column without a default:
  rejected — requires a backfill UPDATE that's not atomic with the
  ALTER on large `message_queue` tables.

---

## R11. Failure-mode mapping (FEAT-009 inheritance)

**Decision**: FEAT-010's enqueue helper calls FEAT-009's
`QueueService` internals verbatim. When FEAT-009 raises any of its
existing exceptions, FEAT-010 maps them to the matching
`route_skipped` reason from the closed FR-037 set:

| FEAT-009 exception | FEAT-010 skip reason |
|---|---|
| `TargetNotFound` | `target_not_found` |
| `TargetRoleNotPermitted` | `target_role_not_permitted` |
| `TargetNotActive` | `target_not_active` |
| `TargetPaneMissing` | `target_pane_missing` |
| `TargetContainerInactive` | `target_container_inactive` |
| `BodyEmpty` | `template_render_error` (sub-reason `body_empty`) |
| `BodyInvalidChars` | `template_render_error` (sub-reason `body_invalid_chars`) |
| `BodyInvalidEncoding` | `template_render_error` (sub-reason `body_invalid_encoding`) |
| `BodyTooLarge` | `template_render_error` (sub-reason `body_too_large`) |
| `KillSwitchOff` | (NO skip — row inserted with `block_reason='kill_switch_off'`, cursor advances per FR-032 + Story 5 #1) |

**Rationale**:
- Reuses FEAT-009's already-tested failure-mode logic; no
  duplicated validation in FEAT-010.
- The `KillSwitchOff` exemption is deliberate: a kill-switched
  send is not a route skip — the row IS inserted (just in
  `blocked` state) and the route's cursor MUST advance (Story 5
  #1).

**Alternatives considered**:
- Re-implement validation in FEAT-010 to surface FEAT-010-flavored
  errors: rejected — violates FR-055 (cannot broaden or duplicate
  FEAT-009 logic).
- Treat kill-switch as a skip: rejected — would mean the route's
  cursor freezes during kill-switch-off, which violates the
  Story 5 design.

---

## R12. Heartbeat thread vs in-worker heartbeat

**Decision**: Heartbeat is a separate `threading.Thread` daemon
that sleeps in `interval_seconds` ticks via a `threading.Event`
wait. It snapshots + resets shared counters under a
`threading.Lock` (held briefly), then writes one JSONL line
outside the lock.

**Rationale**:
- A long routing cycle (e.g., draining a 100-event backlog) does
  not delay the heartbeat.
- A slow JSONL write (degraded filesystem) does not delay the
  routing cycle.
- The lock is held only during the counter snapshot+reset, which
  is microseconds; no JSONL I/O happens under the lock.
- `threading.Event.wait(interval)` returns immediately when the
  shutdown Event is set, so graceful shutdown is bounded by the
  worker's join timeout.

**Alternatives considered**:
- Heartbeat in the worker (last action of each cycle, if interval
  elapsed): rejected — a stalled cycle delays the heartbeat by
  the cycle duration, masking the very stall it's supposed to
  signal.
- `threading.Timer` for the heartbeat: rejected — `Timer` creates
  one thread per fire, leaks if not cancelled cleanly on shutdown.
- `asyncio` scheduler: rejected — pulls the whole daemon onto an
  event loop for a single periodic task; out of scope.

---

## R13. CLI exit-code surface

**Decision**: Reuses FEAT-009's integer-to-string mapping scheme
(`socket_api/errors.py` exposes a single registry). FEAT-010 adds
seven new closed-set string codes (FR-049 revised):
`route_id_not_found`, `route_event_type_invalid`,
`route_target_rule_invalid`, `route_master_rule_invalid`,
`route_template_invalid`, `route_source_scope_invalid`,
`route_creation_failed`. Integer values are allocated by the
existing registry; tooling MUST branch on the string code, not
the integer (FR-050).

**Rationale**:
- Single error-code registry across all features; new codes added
  by extension, never by collision.
- String codes are stable and machine-parseable; integer values
  are an implementation detail.

**Alternatives considered**:
- New FEAT-010-specific error namespace: rejected — fragments the
  error vocabulary across modules, makes the CLI contract harder
  for operators to learn.

---

## R14. Audit-buffer overflow handling

**Decision**: When JSONL append fails (filesystem error, disk
full), the failed entry is appended to a `collections.deque`
buffer (`maxlen=10_000`). The worker drains the buffer on each
cycle by retrying every pending append. On buffer overflow (deque
hits maxlen and a new entry pushes out the oldest), the daemon
writes ONE `audit_buffer_overflow` log line (to stderr / the
daemon log, NOT to events.jsonl) and increments a status counter
`routing.audit_buffer_dropped`.

**Rationale**:
- Bounded memory: 10,000 entries × ~1KB = ~10MB worst case.
- Lossy under sustained failure (intentional): SQLite state is the
  source of truth (FR-039); operators can reconstruct from queue
  state + status counters.
- One overflow log line per overflow event (not per dropped entry)
  prevents log-flood amplification.

**Alternatives considered**:
- Unbounded buffer: rejected — RAM exhaustion under prolonged
  filesystem failure.
- Block the worker until JSONL recovers: rejected — couples
  routing throughput to JSONL write availability; violates the
  "SQLite is the source of truth" invariant.

---

## R17. Determinism boundaries with FEAT-008, redaction, substitution order, and test-fixture format

**Decision**: The byte-for-byte replay contract (SC-010) holds under
this specific input bundle:
1. Initial SQLite snapshot at known schema version (v8).
2. Same event sequence ingested by FEAT-008 in the same order
   with the same `event_id` assignments.
3. Same agent registry state (FEAT-006) at each per-(route, event)
   evaluation moment.
4. Same routing-worker config knobs (`cycle_interval`,
   `batch_size`, `heartbeat_interval` — though heartbeat output is
   excluded from determinism per R1).
5. Same FEAT-007 redactor (REDACTOR_VERSION constant from
   `logs/redaction.py`; bumping it is a determinism-breaking
   change documented separately).

**Determinism boundaries with FEAT-008**: FEAT-010's per-route
event-scan query (`event_id > last_consumed_event_id AND
event_type = ?`) is deterministic given the FEAT-008 events table
state. Events committed BY FEAT-008 mid-cycle become visible to
the NEXT FEAT-010 cycle, not the current one (WAL snapshot
semantics — research §R2 / plan §Implementation Invariants §4).

**FEAT-007 redaction is deterministic**: `logs/redaction.py` is
a regex-based pipeline with no random/time-based input. Given the
same input string, `redact_one_line` returns the same output. The
`REDACTOR_FAILED_PLACEHOLDER` path is also deterministic (raised
only on regex-engine failure, which is itself deterministic per
input).

**Template substitution order**: `template.render_template` does
substitution in a single left-to-right pass over the template
string. Field placeholders are replaced as encountered; no
recursive substitution (a substituted value containing `{field}`
is NOT re-substituted). Equivalent to `str.format_map` semantics
with the closed whitelist.

**Test-fixture format for SC-010 replay tests**: A fixture is a
tuple of (initial-state-archive, event-log) where:
- initial-state-archive: a tarball of the daemon's state directory
  at a known schema version (registry SQLite + companion files).
- event-log: a JSON-Lines file of FEAT-008 event rows in
  `event_id` order, each containing the full row needed for
  re-insertion.
The replay harness (used by Story 4 IT + the SC-010 verification
in T034) extracts the state archive, ingests the events via the
FEAT-008 internal helper (bypassing the classifier), runs the
routing worker for a bounded number of cycles, and exports the
`message_queue` + audit JSONL for byte-comparison with a reference
output.

**Rationale**:
- Pinning the input bundle explicitly makes "what does
  deterministic mean" testable without hand-waving.
- Tying FEAT-007 determinism to a `REDACTOR_VERSION` constant
  gives operators a single artifact to track when the redaction
  contract changes.
- The single-pass left-to-right substitution rules out
  surprising-recursion behavior at the template grammar level
  even though the closed whitelist already makes recursion
  impossible.
- The fixture-format spec keeps replay tests reproducible across
  developer environments.

**Alternatives considered**:
- Per-field substitution as separate `.replace()` calls (multi-
  pass): rejected — order matters when one field's value happens
  to look like another field's placeholder.
- Pickled-Python state archives: rejected — opaque to
  cross-version replay; tar+SQLite is portable.

---

## R16. Crash-recovery fault-injection contract (test seam)

**Decision**: The routing worker reads one environment variable
`_AGENTTOWER_FAULT_INJECT_ROUTING_TXN_ABORT` (default: unset).
Accepted values:
- `before_commit` — raise `SystemExit(137)` inside
  `_process_route_batch` AFTER the `BEGIN IMMEDIATE` opens AND after
  the queue `INSERT` runs BUT BEFORE the SQLite `COMMIT`. Used by
  Story 4 IT to validate cursor + queue inserts roll back atomically.
- `after_commit` — raise `SystemExit(137)` AFTER the `COMMIT` returns
  BUT BEFORE the audit JSONL append. Used to validate the JSONL
  durability buffer + retry path under crash.
- (unset) — no-op (production behavior).

The hook lives entirely in `worker.py` (no separate fault-injection
module); production builds compile it out at zero cost because the
env-var read happens once at worker construction time and the hook
is a single `if self._fault_inject_point == 'before_commit'` branch
inside the per-(route, event) loop.

**Rationale**:
- Single env-var, two-string vocabulary keeps the test seam minimal
  and self-documenting.
- `SystemExit(137)` (rather than `os._exit()` or `kill -9`) lets
  pytest's daemon-fixture catch the exit and verify on-disk state
  cleanly; the 137 code matches SIGKILL convention so a real crash
  signal would land in the same audit shape.
- Living in the worker (not a separate module) avoids a circular
  test-vs-prod import problem and keeps the production codepath
  branch-free at runtime when the env var is unset (one cached
  string compare per event is negligible).

**Alternatives considered**:
- A `FaultInjector` Protocol injected via DI: rejected — adds
  surface area to `RoutingWorker.__init__` for a debug-only feature.
- A separate `_fault_inject.py` module imported only under
  `pytest`: rejected — couples the production worker import to
  test-mode detection.
- Multiple env vars (`..._BEFORE_COMMIT=1`, `..._AFTER_COMMIT=1`):
  rejected — invites operator confusion if both are set.

**Tests that use this hook**: `tests/integration/test_routing_crash_recovery.py` (Story 4 IT). The hook contract is also documented in tasks.md T039.

---

## R15. Validation order at `route add`

**Decision**: At `route add`, validations run in this order, with
first-failure short-circuit:
1. `--event-type` in FEAT-008 closed vocabulary (FR-005)
2. `--master-rule` in `{auto, explicit}` (FR-007)
3. `--target-rule` in `{explicit, source, role}` (FR-006)
4. `--source-scope` parses correctly (Clarifications Q1)
5. `--target` parses correctly per `--target-rule`
6. `--template` references only whitelisted fields (FR-008)

**Rationale**:
- Cheap-string-match checks first (event_type, master_rule,
  target_rule); they fail fast on operator typos.
- Parsers (source_scope, target_value) next; they require a small
  state machine but no DB access.
- Template field-set validator last; it requires walking the
  template string and is the most expensive check.
- Single error per call matches FEAT-009's pattern; operators see
  one error at a time and fix in order.

**Alternatives considered**:
- Accumulate all validation errors and return a list: rejected —
  more complex CLI output, no operator demand for it, breaks the
  single-string-code contract.
