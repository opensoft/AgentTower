# Feature Specification: Event-Driven Routing and Multi-Master Arbitration

**Feature Branch**: `010-event-routes-arbitration`
**Created**: 2026-05-16
**Status**: Draft
**Input**: User description: "FEAT-010: Event-Driven Routing and Multi-Master Arbitration — durable subscriptions that route FEAT-008 events into FEAT-009 queue rows, with deterministic master arbitration and conservative no-auto-deliver semantics."

## Clarifications

### Session 2026-05-16

- Q: For `source_scope_kind=role`, should `source_scope_value` support a capability filter (symmetric with `target_rule=role`), or be role-only? → A: Symmetric — `source_scope_value` parses as `role:<role>[,capability:<cap>]`, reuses the same parser/validator as `target_value` under `target_rule=role`, and matching requires both role AND capability to match when capability is present.
- Q: Should `route_matched` and `route_skipped` audit entries include the resolved target identity directly, or require a join against `message_queue`? → A: Every `route_matched` and `route_skipped` row MUST carry `target_agent_id` and `target_label` as first-class fields; `target_agent_id` MAY be `null` when target resolution never completed (e.g., `reason=no_eligible_master`); skip analysis MUST be possible from one JSONL line without joining any queue row.
- Q: Should the routing worker emit per-cycle lifecycle audit events to `events.jsonl`? → A: No per-cycle entries (would be ~172,800 lines/day of noise at 1 s interval). Instead emit a rate-limited `routing_worker_heartbeat` JSONL audit entry every N seconds (default 60 s, configurable, bounded `[10, 3600]`) regardless of cycle activity, carrying aggregate counts since the last heartbeat (`cycles_since_last_heartbeat`, `events_consumed_since_last_heartbeat`, `skips_since_last_heartbeat`). `agenttower status` remains the primary liveness surface.
- Q: What is the routing worker concurrency model — single-threaded sequential, per-route concurrent within a cycle, or overlapping cycles? → A: Single-threaded sequential. Exactly one routing cycle is in flight at a time per daemon process; within that cycle routes are processed strictly sequentially in FR-042 deterministic order (`created_at` ASC, `route_id` lex tiebreak); cycles do not overlap; no per-route parallelism in MVP.
- Q: Are routes mutable post-creation (i.e., is there an in-place `route update` CLI)? → A: No. Routes are structurally immutable in MVP. Only `enable`/`disable` may change an existing route. Changing selectors (`event_type`, `source_scope`), targeting (`target_rule`/`target_value`), master selection (`master_rule`/`master_value`), or `template` requires `route remove` + `route add` — the fresh route receives a fresh cursor at current event head per FR-002. This is an intentional design choice, not a CLI gap.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Route fires on a matching event and a prompt is delivered (Priority: P1)

An operator creates a route subscribing to a specific FEAT-008 event type (e.g.,
`waiting_for_input`) optionally scoped to a source agent. When the daemon
ingests a new event that matches the route, it deterministically picks a master
agent, renders a prompt envelope from the route's template, enqueues it as a
FEAT-009 message tagged with `origin=route`, and delivers it through the
existing FEAT-009 paste-buffer path. The operator can see the delivered row in
`agenttower queue` filtered by `--origin route` and trace the full chain in the
`events.jsonl` audit history (event → route_matched → queue_message_enqueued →
queue_message_delivered).

**Why this priority**: This is the entire feature reduced to one slice — the
first time an observed event in AgentTower causes a structured prompt to flow
to another agent without operator typing. Every other story in this spec
either varies a parameter on this happy path (P2) or hardens it against
failure (P3). Nothing else in FEAT-010 is meaningful until this works.

**Independent Test**: With FEAT-001..FEAT-009 in place and at least one
registered active master + one registered active slave, create a route via
`agenttower route add --event-type waiting_for_input --target <slave-id>
--template "respond to {source_label}: {event_excerpt}"`. Trigger a
`waiting_for_input` classifier match on the slave's log. Within one daemon
cycle, verify (a) exactly one queue row exists with `origin=route`,
`route_id=<the route>`, `event_id=<the event>`, (b) `agenttower queue
--origin route` lists it, (c) the slave's tmux pane received the rendered
envelope, (d) `events.jsonl` contains the event → `route_matched` →
`queue_message_enqueued` → `queue_message_delivered` sequence in that order.

**Acceptance Scenarios**:

1. **Given** one active master, one active slave, a route subscribing to
   `waiting_for_input` events targeting the slave, **When** the slave's log
   produces a `waiting_for_input` event, **Then** within one daemon routing
   cycle the daemon emits a `route_matched` audit entry naming the route and
   event, enqueues one FEAT-009 row whose `origin=route`, `route_id`, and
   `event_id` reflect the source decision, and delivery proceeds through
   FEAT-009 to terminal state `delivered`.
2. **Given** the same setup, **When** the operator runs `agenttower queue
   --origin route --json`, **Then** the listing includes exactly that row
   and excludes any direct-send rows.
3. **Given** a delivered route-generated message, **When** the operator runs
   `agenttower events --json` (or reads `events.jsonl` directly), **Then**
   the records for that flow include in event-id order: the source FEAT-008
   event, the `route_matched` audit entry referencing the same `event_id`
   and the route_id, the `queue_message_enqueued` audit entry whose
   `origin=route` plus `route_id` plus `event_id` match, and the
   `queue_message_delivered` audit entry whose `message_id` matches.
4. **Given** a route whose `target_rule=source`, **When** an event arrives
   from a slave that is permitted to receive input (role `slave` or
   `swarm`), **Then** the route's enqueue uses that slave as the target and
   the arbitrated master as the sender.
5. **Given** a route whose `target_rule=role` with role `slave` and
   capability `codex`, **When** an event matches and zero, one, or many
   slaves match the role+capability filter at fire time, **Then** the
   selected target is the lexically-lowest active matching `agent_id`
   (zero matches → `route_skipped(no_eligible_target)`).

---

### User Story 2 — Operator manages the route catalog from the CLI (Priority: P1)

An operator inspects, creates, modifies, and removes routes through the
`agenttower route` subcommands. Every route has a stable `route_id`,
human-readable summary, JSON-stable schema, and deterministic exit-code
contract. The catalog must be fully manageable without restarting the daemon
and without ever causing a route to fire on events emitted *before* the route
existed (cursor-at-creation defaults to the current event head).

**Why this priority**: Without CRUD, the routing surface is unusable. This is
the only operator-facing entry point in FEAT-010; the rest is daemon-internal
machinery.

**Independent Test**: Run `agenttower route add ...` → `agenttower route list
--json` → `agenttower route show <route-id> --json` → `agenttower route
disable <route-id>` → `agenttower route enable <route-id>` → `agenttower
route remove <route-id>`. Verify each step's exit code, JSON shape, and
audit-entry emission. Verify a freshly-created route does not fire on any
event whose `event_id` is less than or equal to the largest `event_id`
existing at the moment of creation.

**Acceptance Scenarios**:

1. **Given** the daemon is running with zero routes, **When** the operator
   runs `agenttower route add --event-type waiting_for_input --target
   <slave-id> --template "ping {source_label}"`, **Then** a route row is
   inserted with a generated `route_id`, default `enabled=true`,
   `last_consumed_event_id` set to the current maximum `event_id` in the
   `events` table (or `0` if the table is empty), and a `route_created`
   audit entry is appended.
2. **Given** one or more routes exist, **When** the operator runs
   `agenttower route list --json`, **Then** the CLI emits one JSON object
   per route ordered by `created_at` ascending; each object includes
   `route_id`, `event_type`, `source_scope`, `target_rule`, `target_value`,
   `master_rule`, `master_value`, `template`, `enabled`,
   `last_consumed_event_id`, `created_at`, `updated_at`,
   `created_by_agent_id`.
3. **Given** an existing route, **When** the operator runs `agenttower
   route disable <route-id>`, **Then** the route's `enabled` field becomes
   `false`, a `route_updated` audit entry is appended, the
   `last_consumed_event_id` cursor freezes (does not advance while
   disabled), and any new events that would have matched are not consumed.
4. **Given** a previously disabled route, **When** the operator runs
   `agenttower route enable <route-id>`, **Then** `enabled` flips to
   `true`, a `route_updated` audit entry is appended, and on the next
   routing cycle the route resumes processing events with `event_id >
   last_consumed_event_id` (catching up on the backlog accumulated while
   disabled).
5. **Given** any route, **When** the operator runs `agenttower route remove
   <route-id>`, **Then** the row is hard-deleted from the `routes` table, a
   `route_deleted` audit entry is appended, and any historical
   `queue_message_*` rows whose `route_id` references it remain intact
   (the queue history is preserved as an orphan reference).
6. **Given** `agenttower route add` is invoked with `--event-type
   <not-in-FEAT-008-vocabulary>` or `--target-rule role:<unknown-role>`
   or `--template` containing `{<unknown-field>}`, **Then** the CLI exits
   non-zero with closed-set codes `route_event_type_invalid`,
   `route_target_rule_invalid`, or `route_template_invalid` respectively,
   and no row is inserted.
7. **Given** `agenttower route remove <unknown-id>` or `agenttower route
   show <unknown-id>` or `agenttower route enable <unknown-id>`, **Then**
   the CLI exits non-zero with closed-set `route_id_not_found`.

---

### User Story 3 — Multi-master arbitration is deterministic (Priority: P2)

When more than one agent is currently registered as an active master, exactly
one of them wins arbitration for any given (route, event) decision, and the
same input always picks the same winner. When no agent is eligible to be a
master, the route does NOT auto-deliver — it records the skip with a closed-
set reason and advances its cursor (the event is consumed, no queue row is
created).

**Why this priority**: The MVP positions AgentTower as a conservative,
auditable control plane. Multi-master rivalry without arbitration would
either deliver duplicate prompts or pick a winner via timing, both of which
violate the "if unsure, do not auto-deliver" invariant. FEAT-010's value
disappears without this guarantee.

**Independent Test**: Register three masters with `agent_id` values that
sort `agt_aaa…`, `agt_bbb…`, `agt_ccc…`. Create a route whose `master_rule`
is `auto`. Fire 10 matching events. Verify all 10 resulting queue rows have
`sender.agent_id=agt_aaa…`. Deactivate `agt_aaa…`. Fire one more event.
Verify the new row has `sender.agent_id=agt_bbb…`. Deactivate `agt_bbb…`
and `agt_ccc…`. Fire one more event. Verify a `route_skipped` audit entry
with `reason=no_eligible_master` was appended, the route's cursor advanced
past the event, and no queue row was created. Repeat the entire sequence on
a fresh daemon process and verify identical outcomes.

**Acceptance Scenarios**:

1. **Given** N (N ≥ 2) registered active master agents and a route with
   `master_rule=auto`, **When** any matching event fires, **Then** the
   arbitrated winner is the master whose `agent_id` sorts lexically lowest
   among currently-active masters, and the corresponding `queue_message_
   enqueued` row's `sender.agent_id` equals that winner.
2. **Given** a route with `master_rule=explicit` and
   `master_value=<agent-id>`, **When** a matching event fires AND that
   master is currently active, **Then** that master is the winner regardless
   of how many other active masters exist.
3. **Given** a route with `master_rule=explicit` and
   `master_value=<agent-id>`, **When** a matching event fires AND that
   master is currently inactive (or has never been registered), **Then**
   the daemon appends a `route_skipped` audit entry with
   `reason=master_inactive` (active masters exist but the explicit one
   isn't one of them) or `reason=master_not_found` (the explicit
   agent_id has no agent record), the route's cursor advances past the
   event, and no queue row is created.
4. **Given** zero registered active master agents and a route with
   `master_rule=auto`, **When** a matching event fires, **Then** the
   daemon appends a `route_skipped` audit entry with
   `reason=no_eligible_master`, the route's cursor advances past the
   event, and no queue row is created.
5. **Given** the same scenario sequence is replayed on a freshly-restarted
   daemon, **When** the routing worker resumes, **Then** every arbitration
   outcome (winner identity or skip reason) is byte-for-byte identical to
   the pre-restart run.

---

### User Story 4 — Restart and crash safety: no duplicate routing (Priority: P2)

The daemon may stop and restart at any moment, including between reading an
event and creating its queue row. On restart, the routing worker must not
re-process any event that has already been consumed by a given route, and
must not skip any event that has not. Per-route cursors plus transactional
cursor-advance-with-enqueue eliminate both windows.

**Why this priority**: A duplicate-routing bug means the same prompt arrives
twice in an agent's input. Worse, masters could see the same arbitration
event twice and queue conflicting work. This is the single biggest
correctness hazard FEAT-010 introduces; the spec must lock it down.

**Independent Test**: Submit N matching events. Stop the daemon mid-cycle
(after the routing transaction begins, before commit) using a fault-
injection hook. Restart the daemon. Verify (a) the route's
`last_consumed_event_id` reflects only fully-committed prior cycles, (b)
the daemon does not create duplicate queue rows for any
(route_id, event_id) pair, (c) the count of `queue_message_enqueued` audit
entries with `origin=route` equals the count of matching events (modulo
skips), with no `(route_id, event_id)` pair appearing twice.

**Acceptance Scenarios**:

1. **Given** the daemon crashed mid-routing-transaction (no commit), **When**
   it restarts, **Then** the route cursor reflects the last committed
   `event_id`, the next routing cycle re-evaluates the in-flight event,
   and no duplicate queue row is created for `(route_id, event_id)`.
2. **Given** the daemon crashed after committing the cursor advance and the
   queue row insert (same transaction), **When** it restarts, **Then** the
   route does not re-process that event and no duplicate queue row is
   created.
3. **Given** an enabled route exists, **When** the daemon enforces the
   `(route_id, event_id)` uniqueness invariant at queue-insert time and a
   second insert attempt for the same pair is somehow issued (e.g., from
   logic bug), **Then** the insert is rejected at the storage layer and
   the routing worker surfaces a closed-set internal error rather than
   silently producing a duplicate.
4. **Given** a route exists, **When** the daemon advances the cursor in
   the same transaction as the queue insert, **Then** the cursor is never
   ahead of the most recent committed (and corresponding queue row exists
   if applicable) event AND is never behind the most recent committed
   event for that route.

---

### User Story 5 — FEAT-009 surface reuse: kill switch, queue, audit (Priority: P2)

Route-generated work must traverse the same FEAT-009 plumbing as direct
sends: same permission gate, same kill-switch behavior, same per-target
FIFO, same queue inspection commands, same audit JSONL stream. No new
delivery path exists. When the FEAT-009 kill switch is off, route-generated
rows still get created — but they land in `blocked` with
`block_reason=kill_switch_off` just like direct-send rows, and the route's
cursor still advances (the event was consumed by the route regardless of
delivery outcome).

**Why this priority**: Reuse is the spec's central architectural promise to
operators. If FEAT-010 invented a bypass path to tmux, the kill switch
would not stop it, the permission gate would not enforce it, and queue
inspection would lie. Operators trust the FEAT-009 surface; FEAT-010 must
extend it, not work around it.

**Independent Test**: Disable routing (`agenttower routing disable`).
Create a route. Trigger a matching event. Verify (a) the resulting queue
row exists with `state=blocked`, `block_reason=kill_switch_off`,
`origin=route`, (b) no tmux delivery was attempted, (c) the route's
cursor advanced past the event, (d) `agenttower queue --origin route`
shows the row. Enable routing. Approve the row. Verify it transitions
through to `delivered`.

**Acceptance Scenarios**:

1. **Given** routing is disabled and a route exists, **When** a matching
   event fires, **Then** the route creates a FEAT-009 queue row in state
   `blocked` with `block_reason=kill_switch_off`, `origin=route`,
   `route_id` and `event_id` populated, and no tmux delivery is
   attempted.
2. **Given** the kill-switch-blocked row from scenario 1, **When** the
   operator runs `agenttower queue --json`, **Then** the row appears with
   the new `origin`, `route_id`, and `event_id` fields populated and the
   pre-existing FEAT-009 fields populated as if it were a direct send.
3. **Given** the same row, **When** the operator runs
   `agenttower queue cancel <message-id>` or
   `agenttower queue approve <message-id>` (after re-enabling routing),
   **Then** the transition is permitted exactly as it would be for a
   direct-send row, and the resulting audit entry's `event_type` (e.g.,
   `queue_message_canceled`) is identical in shape — only `origin`,
   `route_id`, `event_id` differ from the direct-send case.
4. **Given** a route fires and the arbitrated winner-master attempts to
   send to a target whose role is not `slave` or `swarm` (e.g.,
   `target_rule=explicit` against a `master`), **Then** the queue row
   lands in `blocked` with `block_reason=target_role_not_permitted` —
   FEAT-009's existing rule, not a new FEAT-010 rule.
5. **Given** two routes that select the same event AND both target the
   same slave, **When** both fire on the same event, **Then** two queue
   rows are created (one per route), each tagged with its own `route_id`,
   and FEAT-009's per-target FIFO serializes their delivery in
   `enqueued_at` order.

---

### User Story 6 — Conservative template rendering with redaction (Priority: P3)

Route templates are static strings with explicit `{field}` placeholders.
The allowed field set is a closed whitelist of FEAT-008 event fields
(`event_id`, `event_type`, `source_agent_id`, `source_label`,
`source_role`, `source_capability`, `event_excerpt`, `observed_at`). The
event excerpt is run through FEAT-007 redaction before interpolation. The
rendered envelope must satisfy FEAT-009's body validation (UTF-8, size
cap, no NUL, etc.); rendering failure causes a `route_skipped` with
reason `template_render_error` and cursor advance.

**Why this priority**: Templates are how event data crosses the boundary
into another agent's input stream. Even with FEAT-007 redaction, the
template surface is the smallest practical interpretation primitive in
the spec and must be conservative by construction. No interpolated shell
expressions, no nested rendering, no function calls — just substitute the
whitelist.

**Independent Test**: Create routes whose templates use each whitelisted
field. Trigger events whose excerpts contain redactable patterns (e.g.,
"GITHUB_TOKEN=abcdef…"). Verify the rendered envelope substitutes the
fields correctly AND the excerpt portion is the redacted form. Separately
create routes with templates referencing unknown fields and verify they
fail at `route add` time, not at fire time.

**Acceptance Scenarios**:

1. **Given** a route with template `"event {event_type} from
   {source_label}: {event_excerpt}"`, **When** an event fires whose
   excerpt contains a redactable pattern, **Then** the rendered envelope
   body contains the literal `event_type`, the literal `source_label`,
   and the *redacted* excerpt (not the raw excerpt).
2. **Given** a route whose template references `{unknown_field}`, **When**
   the operator runs `agenttower route add`, **Then** the CLI exits
   non-zero with closed-set `route_template_invalid` before any row is
   inserted; the route is rejected at submit time, not at fire time.
3. **Given** a route whose template rendering would produce an envelope
   exceeding FEAT-009's `body_too_large` cap, **When** an event fires
   that would render to oversized, **Then** the daemon appends a
   `route_skipped` audit entry with `reason=template_render_error` (sub-
   reason `body_too_large`), advances the cursor, and creates no queue
   row.
4. **Given** a route whose template renders to a body containing a NUL
   byte or invalid UTF-8 (e.g., an event excerpt with raw control bytes
   that survived redaction), **When** the event fires, **Then** the
   daemon appends `route_skipped(reason=template_render_error)` with
   sub-reason `body_invalid_chars` or `body_invalid_encoding`, advances
   the cursor, and creates no queue row.

---

### User Story 7 — Routing surface is visible in `agenttower status` (Priority: P3)

`agenttower status` (and its `--json` form) exposes the routing
subsystem's health so operators can detect stalled routes, missing
masters, or unexpected skip-rate spikes. Read-only; cannot change state.

**Why this priority**: Without status visibility, the routing worker is
opaque. Operators need a way to verify "is routing working at all" and
"which routes are alive" without scraping JSONL. Lower priority than the
core safety stories because it's diagnostic, not corrective.

**Independent Test**: Run `agenttower status --json` on a freshly-started
daemon (zero routes), after creating routes (positive route count), and
after disabling routes. Verify the routing section appears with the
expected counts and timestamps in each case.

**Acceptance Scenarios**:

1. **Given** the daemon is running, **When** the operator runs
   `agenttower status --json`, **Then** the output includes a top-level
   `routing` object containing `routes_total`, `routes_enabled`,
   `routes_disabled`, `last_routing_cycle_at` (timestamp of most recent
   routing worker pass), `events_consumed_total` (sum of consumed
   events across all routes since daemon start), `skips_by_reason`
   (object keyed by closed-set skip reason; values are counts since
   daemon start).
2. **Given** at least one route has `last_consumed_event_id` lagging
   significantly behind the maximum `event_id` in `events`, **When**
   `agenttower status --json` is invoked, **Then** the `routing`
   object includes a `most_stalled_route` field with the lagging
   route's `route_id` and lag (count of unconsumed matching events
   above its cursor); when no route is lagging, the field is null.

---

### Edge Cases

- **Route created after events already exist**. Default behavior:
  `last_consumed_event_id` is set to the current maximum `event_id` in
  the `events` table at creation time. A new route never fires on
  historical events. If the operator wants to replay, they must use a
  later `route reset-cursor` command (out of scope for FEAT-010 MVP;
  defer to a follow-up).
- **Route disabled while a routing cycle is in flight**. The cycle
  completes for events it has already loaded; subsequent cycles do not
  pick up new events for the disabled route. Cursor freezes at the
  last successfully-processed `event_id`.
- **Route enabled after long downtime accumulated a backlog**. Resumes
  from the frozen cursor; processes the entire backlog in one or more
  routing cycles. The daemon SHOULD bound the per-cycle batch size to
  avoid blocking other workers, but the spec leaves the exact cap to
  the planning phase.
- **Routing cycle runs while the kill switch is off**. The cycle still
  evaluates routes and creates queue rows; rows just land in `blocked`
  with `block_reason=kill_switch_off` (FEAT-009 path). The route's
  cursor advances regardless.
- **Routing cycle runs while no master is registered AT ALL**. The
  `route_skipped(reason=no_eligible_master)` audit entry is emitted
  for every matching event; the route's cursor advances; no queue
  rows are created. When a master is later registered, future events
  flow normally — but the events that fired during the master-less
  window are NOT replayed.
- **Two routes select the same event AND have overlapping target rules**.
  Each route creates its own queue row independently. FEAT-009's
  per-target FIFO serializes delivery. The operator is responsible for
  not creating duplicate-effect routes; the daemon does not detect or
  warn about overlap in MVP.
- **Route's explicit `master_agent_id` references an agent that does
  not exist in the registry**. Treated as a config error caught at
  fire time, not at route creation: `route_skipped(reason=master_not_
  found)`. (Validation at route creation time is best-effort but not
  guaranteed, since the agent might be unregistered later.)
- **Route's `target_rule=explicit` references an agent that no longer
  exists**. Treated as a fire-time error: the FEAT-009 enqueue path
  surfaces `target_not_found` and the queue row is rejected before
  insert. The route appends `route_skipped(reason=target_not_found)`
  and advances its cursor.
- **Route's `target_rule=source` fires on an event whose source agent
  has been deregistered between event emission and route fire time**.
  Same as the explicit case above:
  `route_skipped(reason=target_not_found)`, cursor advances.
- **Same `(route_id, event_id)` somehow inserted twice** (transactional
  invariant violated). The storage layer enforces a UNIQUE constraint
  on `(route_id, event_id)` in `message_queue`; the second insert
  raises a closed-set error and the routing worker logs it as a hard
  internal error. This is a defense-in-depth check; under correct
  cursor-advance-with-enqueue, it cannot fire.
- **FEAT-008 event table has been wiped between routing cycles** (or
  events purged below `last_consumed_event_id`). The next cycle's
  query for `event_id > last_consumed_event_id` returns rows starting
  at the new smallest available `event_id`. Routing continues from
  there; the cursor moves forward as usual. No spec-level retention
  policy in MVP per FEAT-008's inheritance.
- **An operator creates two routes with identical selectors but
  different templates**. Each fires on every matching event and each
  produces its own queue row. Operators are free to create overlapping
  routes.
- **Master is deregistered between arbitration and queue insert (race
  window of milliseconds)**. The arbitration result is locked in at
  the moment of evaluation; the queue row is inserted with that
  master's identity as `sender`. FEAT-009's sender-liveness-not-
  re-checked-at-delivery rule (from FEAT-009 Assumptions) means the
  delivery still proceeds. The audit shows the arbitrated master as
  sender, which may not match the current master roster.
- **Daemon is shutting down**. The routing worker stops at the next
  cycle boundary; no new events are processed. In-flight transactions
  complete normally or roll back atomically.
- **The `events.jsonl` audit append fails for a route lifecycle
  entry**. Inherits FEAT-008's degraded-mode behavior: buffer the
  audit entry in memory, retry on the next cycle, surface degraded
  state through `agenttower status`. SQLite cursor advance is the
  authority; the JSONL append is best-effort retry.
- **Operator removes a route while one of its (route_id, event_id)
  queue rows is mid-delivery**. The queue row's `route_id` field
  becomes an orphan reference (the `routes` row is gone, but the
  `route_id` value in the queue row remains). Queue inspection and
  audit history continue to work; the route detail view returns
  `route_id_not_found` for that id.

## Requirements *(mandatory)*

### Functional Requirements

#### Route entity and lifecycle

- **FR-001**: System MUST persist a `routes` SQLite table with at
  minimum the following columns: `route_id` (UUIDv4, primary key),
  `event_type` (closed set matching the FEAT-008 emitted event
  vocabulary), `source_scope_kind` (closed set: `any`, `agent_id`,
  `role`), `source_scope_value` (nullable; for `kind=any` MUST be
  NULL; for `kind=agent_id` MUST be a single `agt_*` agent_id; for
  `kind=role` MUST parse as `role:<role>[,capability:<cap>]` using
  the same grammar as `target_value` under `target_rule=role`),
  `target_rule` (closed set: `explicit`, `source`, `role`),
  `target_value` (nullable; type depends on `target_rule`),
  `master_rule` (closed set: `auto`, `explicit`), `master_value`
  (nullable; agent_id when `master_rule=explicit`), `template`
  (TEXT; rendered string template), `enabled` (boolean, default
  `true`), `last_consumed_event_id` (INTEGER, references FEAT-008
  `events.event_id`), `created_at`, `updated_at`,
  `created_by_agent_id` (nullable; `agt_*` or `host-operator`
  sentinel).
- **FR-002**: System MUST set `last_consumed_event_id` at route
  creation time to `MAX(events.event_id)` from the FEAT-008 events
  table, or `0` when the events table is empty. A new route MUST
  NOT fire on any event whose `event_id` is less than or equal to
  the cursor value at creation.
- **FR-003**: System MUST treat `routes` as the source of truth
  for the routing subsystem; deleting a route via `route remove`
  hard-deletes the row. Queue rows whose `route_id` references a
  deleted route remain intact (their `route_id` becomes an orphan
  reference; queue inspection does not fail).
- **FR-004**: System MUST expose CLI commands `agenttower route
  add`, `agenttower route list`, `agenttower route show <route-id>`,
  `agenttower route remove <route-id>`, `agenttower route enable
  <route-id>`, `agenttower route disable <route-id>`, each
  accepting `--json` and returning a closed-set non-zero exit on
  error.
- **FR-005**: System MUST reject `route add` invocations whose
  `--event-type` value is not in the FEAT-008 classifier vocabulary
  with closed-set `route_event_type_invalid`. Allowed event types
  are: `activity`, `waiting_for_input`, `completed`, `error`,
  `test_failed`, `test_passed`, `manual_review_needed`,
  `long_running`, `pane_exited`, `swarm_member_reported`.
- **FR-006**: System MUST reject `route add` invocations whose
  `--target-rule` value is not in `{explicit, source, role}` with
  closed-set `route_target_rule_invalid`. When `target_rule=role`,
  the `target_value` MUST parse as `role:<role>[,capability:<cap>]`
  and the role MUST be in `{slave, swarm}` (the FEAT-009 receive-
  permitted set). The system MUST reuse the same parser/validator
  for `source_scope_value` when `source_scope_kind=role`; source-
  side role values are NOT restricted to `{slave, swarm}` (a route
  may legitimately subscribe to events from `master`-role agents).
  Source-scope validation failures (unknown `source_scope_kind`,
  malformed `source_scope_value`, unknown role token) surface as
  closed-set `route_source_scope_invalid`.
- **FR-007**: System MUST reject `route add` invocations whose
  `--master-rule` value is not in `{auto, explicit}` with closed-
  set `route_master_rule_invalid`.
- **FR-008**: System MUST reject `route add` invocations whose
  `--template` references any field outside the closed whitelist
  with closed-set `route_template_invalid`. Whitelist:
  `{event_id}`, `{event_type}`, `{source_agent_id}`,
  `{source_label}`, `{source_role}`, `{source_capability}`,
  `{event_excerpt}`, `{observed_at}`.
- **FR-009**: System MUST allow `enable`/`disable` to be invoked
  on a route that is already in the requested state; the second
  invocation MUST succeed idempotently without appending a
  duplicate `route_updated` audit entry (the operation is a no-op
  at the storage layer).
- **FR-009a**: System MUST treat routes as structurally
  immutable post-creation. The CLI MUST NOT expose any `route
  update` (or equivalent in-place edit) command. The only fields
  on an existing route an operator may change are `enabled`
  (via `route enable` / `route disable`) and the implicit
  `last_consumed_event_id` cursor (advanced by the routing
  worker per FR-012). Selectors (`event_type`, `source_scope`),
  targeting (`target_rule`, `target_value`), master selection
  (`master_rule`, `master_value`), and `template` MUST be
  changed only via `route remove` followed by `route add`; the
  replacement route receives a new `route_id` and a fresh
  cursor at current event head per FR-002.

#### Event-to-route matching

- **FR-010**: System MUST scan each enabled route on every routing
  cycle and select events whose `event_id > last_consumed_event_id`
  AND whose `event_type` equals the route's `event_type` AND whose
  source matches the route's `source_scope` under these rules:
  `source_scope_kind=any` matches any source; `source_scope_kind=
  agent_id` matches when `event.source_agent_id ==
  source_scope_value`; `source_scope_kind=role` matches when
  `event.source_role == role` AND (if `capability` is present in
  `source_scope_value`) `event.source_capability == capability`.
  Both role AND capability MUST match when capability is present;
  capability absence MUST match any capability.
- **FR-011**: System MUST process events in `event_id` ascending
  order within each route's cycle, ensuring causality with the
  FEAT-008 ordering convention.
- **FR-012**: System MUST advance the route's
  `last_consumed_event_id` to the just-processed event's
  `event_id` whenever the route's evaluation of that event reaches
  a terminal decision (enqueued OR skipped with closed-set
  reason). The cursor advances in the same SQLite transaction as
  the queue insert (when enqueuing) or as a standalone update
  (when skipping).
- **FR-013**: System MUST NOT advance the cursor on an event whose
  evaluation aborted due to a transient internal error (e.g.,
  SQLite lock conflict mid-transaction). Such events are re-
  evaluated on the next cycle. The closed-set internal-error
  vocabulary is documented under FR-051.
- **FR-014**: System MUST run the routing worker as a single-
  threaded sequential loop: exactly one routing cycle is in
  flight at a time per daemon process, cycles do not overlap
  (cycle N+1 begins only after cycle N has fully completed or
  rolled back), and within a cycle routes are processed
  strictly sequentially in the FR-042 deterministic order — one
  route's batch (up to `batch_size` events per FR-041)
  completes before the next route starts. MVP does NOT support
  per-route parallelism or per-event parallelism.
- **FR-015**: System MUST support fan-out: when N enabled routes
  match the same event, each route creates its own queue row
  independently and each route advances its own cursor.

#### Multi-master arbitration

- **FR-016**: System MUST, when a route's `master_rule=explicit`,
  select the master named by `master_value` as the winner if that
  agent currently has role `master` AND `active=true`. Otherwise
  the route MUST skip with closed-set reason `master_inactive`
  (the agent exists but is not currently an active master) or
  `master_not_found` (no agent record matches the `master_value`).
- **FR-017**: System MUST, when a route's `master_rule=auto`,
  select as the winner the agent with the lexically-lowest
  `agent_id` among all currently registered active agents whose
  role is `master`.
- **FR-018**: System MUST, when no active master agent exists (or
  the explicit master is unavailable per FR-016), skip the route
  with closed-set reason `no_eligible_master` (auto rule) or
  `master_inactive`/`master_not_found` (explicit rule), advance
  the cursor, and create no queue row.
- **FR-019**: System MUST evaluate arbitration BEFORE template
  rendering. A skip due to arbitration MUST NOT consume CPU on
  template rendering.
- **FR-020**: System MUST capture the winner identity at
  arbitration time and use that identity as the `sender` on the
  resulting FEAT-009 queue row. The winner identity is the agent
  identity (`agent_id`, `label`, `role`, `capability`) as it
  existed at the moment of evaluation.

#### Target selection

- **FR-021**: System MUST, when `target_rule=explicit`, attempt
  to resolve `target_value` as an `agent_id` first, then as a
  `label` (case-sensitive exact match), then as a tag if FEAT-
  006 supports tags (it does not in MVP; this is a no-op).
  Resolution failure surfaces as `route_skipped(target_not_
  found)`.
- **FR-022**: System MUST, when `target_rule=source`, use the
  source agent of the FEAT-008 event as the target. The source
  agent MUST currently exist, be active, AND have a permitted
  receive role; failures surface as `route_skipped(target_not_
  found)` or `route_skipped(target_role_not_permitted)`.
- **FR-023**: System MUST, when `target_rule=role`, select the
  lexically-lowest active agent matching the role+capability
  filter from `target_value`. Zero matches surface as
  `route_skipped(no_eligible_target)`.
- **FR-024**: System MUST, in all target-resolution paths, pass
  the resolved target identity into the FEAT-009 enqueue helper
  and let FEAT-009's existing permission gate (FR-021..FR-025 of
  FEAT-009) be the authoritative check. FEAT-010 MUST NOT
  duplicate or weaken FEAT-009 permission logic.

#### Template rendering

- **FR-025**: System MUST render the route's template by
  substituting each `{<field>}` placeholder with the
  corresponding event field from the whitelist in FR-008. No
  other substitution syntax is supported (no nested
  interpolation, no expressions, no function calls).
- **FR-026**: System MUST run the event's excerpt through the
  FEAT-007 redaction utility BEFORE substituting `{event_
  excerpt}`. The raw (unredacted) excerpt MUST NEVER appear in a
  rendered route body.
- **FR-027**: System MUST treat the rendered body as the FEAT-009
  envelope body input; FEAT-009's body validation (FR-003 / FR-
  004 of FEAT-009: UTF-8, no NUL, allowed control chars only,
  size cap) applies unchanged. Validation failure surfaces as
  `route_skipped(template_render_error)` with a sub-reason naming
  the specific FEAT-009 validation code.
- **FR-028**: System MUST treat any missing whitelisted field at
  render time as a render error (`route_skipped(template_render_
  error/missing_field)`). The daemon MUST NOT substitute a
  placeholder or empty string for missing data.

#### FEAT-009 reuse and queue-row tagging

- **FR-029**: System MUST extend the FEAT-009 `message_queue`
  table with three new nullable columns: `origin` (closed set:
  `direct` | `route`; default `direct` for backward
  compatibility), `route_id` (nullable; populated only when
  `origin=route`), `event_id` (nullable; populated only when
  `origin=route`; references FEAT-008 `events.event_id`).
- **FR-030**: System MUST enforce a UNIQUE constraint on
  `(route_id, event_id)` in `message_queue` where both are non-
  null. This is the defense-in-depth guard against duplicate
  routing.
- **FR-031**: System MUST advance the SQLite schema version to
  `8` and ship a migration that adds the FR-029 columns plus the
  FR-030 UNIQUE index plus the `routes` table from FR-001.
- **FR-032**: System MUST route every route-generated enqueue
  through the same internal entry point that FEAT-009's
  `queue.send_input` socket method uses for validation,
  permission gating, kill-switch handling, and per-target FIFO.
  FEAT-010 MUST NOT bypass any FEAT-009 check or write to
  `message_queue` directly outside that internal helper.
- **FR-033**: System MUST surface route-generated queue rows in
  `agenttower queue` listings (both human and `--json`) with the
  new `origin`, `route_id`, `event_id` fields populated. A new
  CLI filter `--origin <direct|route>` MUST restrict the listing
  to one origin.
- **FR-034**: System MUST allow FEAT-009 operator actions
  (`queue approve`, `queue delay`, `queue cancel`) on route-
  generated rows under the same rules as direct-send rows. No
  additional permission applies.

#### Audit and observability

- **FR-035**: System MUST append one of six FEAT-010-introduced
  audit event types to the FEAT-008 `events.jsonl` stream:
  `route_matched` (route matched an event AND arbitration
  produced a winner AND enqueue path was taken), `route_skipped`
  (route matched an event BUT no queue row was created, with a
  closed-set `reason`), `route_created`, `route_updated`,
  `route_deleted` (operator-driven catalog changes), and
  `routing_worker_heartbeat` (periodic liveness signal — see
  FR-039a). The system MUST NOT emit per-cycle
  `routing_cycle_started`/`routing_cycle_completed` entries;
  cycle-level observability lives in `agenttower status`
  (`last_routing_cycle_at`, `events_consumed_total`,
  `skips_by_reason`) and in the aggregated heartbeat.
- **FR-036**: System MUST include in every `route_matched` and
  `route_skipped` audit entry: `event_id` (the FEAT-008 event
  being evaluated), `route_id`, `winner_master_agent_id`
  (nullable; null on skip when arbitration did not produce a
  winner), `target_agent_id` (nullable; null on skips where
  target resolution never completed, e.g.,
  `reason=no_eligible_master`, `reason=no_eligible_target`),
  `target_label` (nullable; populated whenever `target_agent_id`
  is populated, copied from the agent registry at evaluation
  time), `reason` (nullable; populated on skip from the closed
  set in FR-037), and a redacted excerpt of the source event
  (≤ 240 chars, same convention as FEAT-009). Each audit row
  MUST be self-contained: skip analysis MUST be possible from
  one JSONL line without joining `message_queue` or any other
  audit row.
- **FR-037**: System MUST emit `route_skipped` `reason` values
  only from this closed set: `no_eligible_master`,
  `master_inactive`, `master_not_found`, `target_not_found`,
  `target_role_not_permitted`, `target_not_active`,
  `target_pane_missing`, `target_container_inactive`,
  `no_eligible_target`, `template_render_error`,
  `body_empty`, `body_invalid_chars`, `body_invalid_encoding`,
  `body_too_large`.
- **FR-038**: System MUST extend `agenttower status` (human and
  `--json`) with a `routing` section: `routes_total`,
  `routes_enabled`, `routes_disabled`, `last_routing_cycle_at`,
  `events_consumed_total`, `skips_by_reason` (object keyed by
  closed-set reason), `most_stalled_route` (object with
  `route_id` and `lag`, or null when no route is lagging).
- **FR-039**: System MUST treat audit-append failures for the
  FEAT-010 audit event types the same way FEAT-008 treats JSONL
  durability failures: buffer in memory, retry on the next
  cycle, surface a degraded state through `agenttower status`.
  SQLite state transitions remain the source of truth.
- **FR-039a**: System MUST emit a `routing_worker_heartbeat`
  audit entry to `events.jsonl` at a configurable interval
  (default 60 seconds, bounded `[10, 3600]`), regardless of
  whether any route matched any event during that interval.
  Each heartbeat MUST carry: `emitted_at` (ISO-8601 timestamp),
  `interval_seconds` (the configured interval at the moment of
  emission), `cycles_since_last_heartbeat` (count of routing
  cycles that ran in the window), `events_consumed_since_last_
  heartbeat` (sum across all routes), `skips_since_last_
  heartbeat` (sum across all routes), and `degraded` (boolean
  mirroring the `routing_worker_degraded` status field from
  FR-051). The heartbeat counters reset at each emission. The
  first heartbeat after daemon start MUST emit one full
  interval after the worker loop begins (no startup heartbeat).

#### Daemon worker behavior

- **FR-040**: System MUST run a routing worker loop within the
  daemon at a configurable interval, default 1 second, bounded
  to `[0.1, 60]` seconds.
- **FR-041**: System MUST process at most a configurable batch
  size of matching events per route per cycle (default 100,
  bounded `[1, 10_000]`), to prevent one stalled route from
  blocking the entire worker.
- **FR-042**: System MUST process routes in deterministic order
  per cycle: routes sorted by `created_at` ascending, with
  `route_id` lexical order as final tie-breaker. This makes
  per-cycle replay deterministic in tests.
- **FR-043**: System MUST stop the routing worker cleanly on
  daemon shutdown: in-flight transactions commit or roll back
  atomically, the worker exits at the next cycle boundary, and
  no in-progress event is left half-processed.
- **FR-044**: System MUST recover correctly across restarts: a
  cold-start daemon re-reads route rows and resumes from each
  route's `last_consumed_event_id` cursor. No additional
  recovery transition (FEAT-009 FR-040 analogue) is required
  because FEAT-010's only in-flight state is the transactional
  cursor-advance-plus-enqueue, which is atomic.

#### CLI contract

- **FR-045**: System MUST emit `agenttower route add --json`
  output as exactly one JSON object on stdout with stable fields:
  `route_id`, `event_type`, `source_scope`, `target_rule`,
  `target_value`, `master_rule`, `master_value`, `template`,
  `enabled`, `last_consumed_event_id`, `created_at`,
  `created_by_agent_id`.
- **FR-046**: System MUST emit `agenttower route list --json`
  output as a JSON array of route objects, each with the FR-045
  shape, ordered by `created_at` ascending.
- **FR-047**: System MUST emit `agenttower route show <route-id>
  --json` output as exactly one route object plus an additional
  `runtime` sub-object with `last_routing_cycle_at` (most recent
  cycle where this route was scanned), `events_consumed`
  (lifetime), `last_skip_reason` (most recent skip's reason or
  null), `last_skip_at`.
- **FR-048**: System MUST emit `agenttower route remove`,
  `route enable`, `route disable` `--json` output as exactly one
  JSON object containing `route_id` and the resulting
  `operation` (`removed`, `enabled`, `disabled`) plus a
  timestamp.

#### Failure handling and error vocabulary

- **FR-049**: System MUST treat a closed-set CLI error
  vocabulary as contractual. The full FEAT-010-introduced set
  (additions to FEAT-009's vocabulary) is:
  `route_id_not_found`, `route_event_type_invalid`,
  `route_target_rule_invalid`, `route_master_rule_invalid`,
  `route_template_invalid`, `route_source_scope_invalid`,
  `route_creation_failed`. Plus the closed set of
  `route_skipped(reason=…)` values from FR-037 which appear in
  audit `reason` fields (not CLI exit codes).
- **FR-050**: System MUST expose a stable string-code mapping
  for every CLI exit, with the integer-to-string mapping
  documented and tested. Tooling MUST branch on the JSON code,
  not on integer exit values.
- **FR-051**: System MUST surface routing-worker internal
  errors that prevent cursor advance as a `routing_worker_
  degraded` condition in `agenttower status`, identical in
  shape to FEAT-008's classifier-degraded condition; this is
  NOT a CLI exit code but a status field.

#### Interaction boundaries

- **FR-052**: System MUST NOT introduce any non-event trigger
  for route firing. Timers, polling of arbitrary state, file
  watchers, and external webhooks are explicitly out of scope.
  Routes fire only in response to FEAT-008 events.
- **FR-053**: System MUST NOT use any model-based or LLM-based
  arbitration, target selection, template inference, or route
  suggestion in MVP. All decisions are rule-based and
  deterministic from the inputs.
- **FR-054**: System MUST NOT include a TUI, web UI, or desktop
  notification surface in FEAT-010. CLI (`route`, `queue`,
  `status`, `events`) plus the unified `events.jsonl` stream
  are the only operator-facing surfaces.
- **FR-055**: System MUST NOT modify FEAT-009 permission rules
  (FEAT-009 FR-021..FR-025). FEAT-010 may only restrict (e.g.,
  refuse to route to certain combinations) but never broaden
  what FEAT-009 permits.

### Key Entities *(include if feature involves data)*

- **Route**: A durable subscription record specifying which
  FEAT-008 events should generate FEAT-009 queue rows, with
  which arbitrated master as sender, against which target, and
  rendered through which template. Has its own
  `last_consumed_event_id` cursor for replay safety.
- **Routing cycle**: A single pass of the daemon's routing
  worker through all enabled routes. Bounded by the per-route
  batch size from FR-041 and the cycle interval from FR-040.
- **Arbitration decision**: A point-in-time selection of one
  master agent (or no master, with a closed-set reason) for one
  (route, event) pair. Determined by the route's `master_rule`
  and the current active-master set; deterministic given the
  same inputs.
- **Template**: A static string with `{<field>}` placeholders
  drawn from a closed whitelist of FEAT-008 event fields.
  Rendered once per (route, event) pair after arbitration
  succeeds.
- **Queue row, route-tagged**: A FEAT-009 `message_queue` row
  whose new `origin=route` plus `route_id` plus `event_id`
  columns identify the route and source event that produced it.
  All other queue semantics (state machine, audit, FIFO,
  delivery) are unchanged from FEAT-009.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can register a master + slave, create
  a route via `agenttower route add`, trigger a matching event,
  and observe the resulting envelope arrive in the slave's tmux
  pane within 5 seconds of the FEAT-008 event being persisted
  under typical local conditions.
- **SC-002**: When two or more active masters exist and a route
  fires `N=100` times with `master_rule=auto`, 100% of the
  resulting queue rows have `sender.agent_id` equal to the
  lexically-lowest active master `agent_id` at each fire
  moment, AND 0% of fires produce a queue row whose sender is
  a different master.
- **SC-003**: When zero active masters exist and a route fires
  `N=10` times, 100% of fires produce one `route_skipped`
  audit entry with `reason=no_eligible_master`, the route's
  cursor advances exactly `N` times, and 0 queue rows are
  created.
- **SC-004**: After a fault-injection crash that aborts a
  routing transaction mid-flight `N=10` times, on each
  restart the daemon does not produce duplicate `(route_id,
  event_id)` queue rows; the count of `queue_message_enqueued`
  audit entries with each unique `(route_id, event_id)`
  remains exactly 1.
- **SC-005**: When the FEAT-009 kill switch is disabled,
  100% of route-generated rows land in `blocked` with
  `block_reason=kill_switch_off`, 0% reach the target pane,
  AND the route's cursor still advances exactly once per
  matching event.
- **SC-006**: An `agenttower route list --json` invocation on
  a daemon with 1000 routes returns in under 500 ms and emits
  valid JSON parseable by `jq` with zero errors.
- **SC-007**: A route whose template references unknown
  fields, invalid event types, or out-of-vocabulary target
  rules is rejected at `route add` time in under 100 ms with
  a closed-set CLI error code, and zero rows are inserted
  into `routes`.
- **SC-008**: A `route_skipped` audit entry includes enough
  information (event_id, route_id, reason, redacted excerpt)
  to reconstruct why the skip occurred without consulting any
  other audit entry; verifiable by parsing one JSONL line in
  isolation.
- **SC-009**: An operator can `disable` a route, accumulate
  matching events for at least 1 hour with zero queue rows
  created, then `enable` the route and observe the backlog
  drain (all matching events from the disable window get
  routed) within `ceil(backlog_size / batch_size)` cycles.
- **SC-010**: Routing-cycle determinism: starting from a
  fixed initial database snapshot and replaying the same
  events twice in two separate daemon processes (cold start
  → process → shutdown for each), the resulting `message_
  queue` and `events.jsonl` row contents for FEAT-010-
  relevant entries are byte-for-byte identical between runs,
  modulo wall-clock timestamps.

## Assumptions

- **Fan-out semantics in MVP**. When multiple enabled routes
  select the same event, each fires independently. Per-target
  FIFO from FEAT-009 serializes any same-target deliveries.
  Operators are responsible for avoiding overlapping selectors
  if they want exclusive routing — the daemon does not detect
  or warn about overlap. (Considered: first-match by priority
  order; rejected for MVP because it adds a `priority` column
  and a tie-break rule whose semantics are harder to test.)
- **Auto-arbitration tie-break is lexically-lowest active
  master `agent_id`**. Chosen because (a) it is fully
  deterministic across restarts, (b) it requires no state
  history (no "last winner" memory), (c) it is testable
  without timing dependencies, (d) it makes test fixtures
  predictable. The trade-off is that one master may receive a
  disproportionate share of work; the next feature (or an
  operator-tuned `master_rule=explicit` per route) can address
  load distribution. Considered alternatives: round-robin,
  least-recently-routed, registered_at order, random with
  fixed seed.
- **Routes are NOT priority-ordered in MVP**. Fan-out + per-
  target FIFO replaces priority. Adding `priority` is a
  forward-compatible additive change for a later feature.
- **`last_consumed_event_id` is per-route**. Each route owns
  its own cursor; no shared global routing cursor. This makes
  enable/disable/replay reasoning local to one route.
- **Cursor at route creation = current event head**. New
  routes never replay history. To replay, an operator must use
  a future `route reset-cursor` command (out of scope for
  FEAT-010 MVP).
- **Routes are structurally immutable in MVP**. There is no
  `route update` CLI. Operators change selectors, targeting,
  master selection, or template via `route remove` + `route
  add`. Rationale: an in-place edit creates ambiguity around
  cursor preservation (does an `event_type` change reset the
  cursor? do pending matches under the old selector stay
  pending?) that's cleanly avoided by the immutability +
  fresh-cursor-on-add model. The `remove` + `add` flow is
  explicit, auditable (`route_deleted` + `route_created`), and
  forward-compatible: if a real pain-point emerges, `route
  update` can be added later as additive CLI surface without
  breaking existing routes.
- **Cursor freezes when route is disabled**. Re-enabling
  resumes from the frozen cursor and processes the accumulated
  backlog. (Considered: cursor advances even while disabled,
  resetting on re-enable. Rejected because it surprises
  operators who expect "disable + re-enable" to mean "pause
  + resume.")
- **Per-route batch cap default = 100 events/cycle**. Chosen
  to bound worst-case latency of a single stalled route's
  catch-up. Bounded `[1, 10000]` so operators can tune for
  larger replays. Per-cycle elapsed-time bound is not in MVP
  scope.
- **Master eligibility = `role=master` AND `active=true`**.
  No additional capability or container-locality constraint
  in MVP. Operators who want capability-aware arbitration use
  `master_rule=explicit` per route.
- **Target selection runs only three rules in MVP**: `explicit`
  (specific agent), `source` (the source agent of the event),
  `role` (lexically-lowest active matching agent by role and
  optional capability). Considered: queue-depth-aware
  selection ("send to the least busy slave"); rejected
  because it depends on FEAT-009 queue state at decision time
  and complicates determinism.
- **Template syntax is simple `{field}` substitution from a
  closed whitelist**. No nested interpolation, no expressions,
  no function calls. Considered: Jinja2, Python f-string,
  Go-template; all rejected for MVP because each requires a
  templating engine dependency and broader sandbox concerns.
- **Source event excerpt is redacted before interpolation**.
  Uses the existing FEAT-007 redaction utility unchanged.
- **Route-generated rows use the arbitrated master as `sender`
  in the FEAT-009 queue row**. The audit history shows a real
  master identity, not a synthetic `agenttowerd` or `route:
  …` sender. This keeps the queue audit surface uniform
  between direct and route-generated work; the new `origin`,
  `route_id`, `event_id` columns are the discriminator.
- **The FEAT-009 internal enqueue helper is the only path to
  `message_queue` insert**. FEAT-010 does not write to
  `message_queue` directly. This guarantees identical
  validation, permission, kill-switch, and FIFO behavior
  between direct sends and route-generated sends.
- **Audit-and-cursor-advance is atomic per (route, event)**.
  The cursor advance and the queue insert (when enqueueing)
  are committed in one SQLite transaction. The audit JSONL
  append is best-effort retry (FEAT-008 inheritance). On
  crash mid-transaction, the cursor reflects only fully-
  committed work.
- **Per-target FIFO is reused from FEAT-009; FEAT-010 adds no
  new ordering primitives**. Two routes targeting the same
  slave will serialize via FEAT-009's per-target FIFO; the
  ordering follows `enqueued_at`.
- **No multi-master arbitration *prompts* in MVP**. The
  architecture's §17 "send the other master's prompt to the
  requesting master and ask queue-next/delay/cancel" behavior
  is OUT OF SCOPE for FEAT-010. FEAT-010 ships the
  deterministic-winner primitive; the operator-facing
  arbitration dialog is a follow-up feature. (Scope note: the
  `docs/mvp-feature-sequence.md` FEAT-010 section bundles
  both arbitration logic and arbitration prompts; this spec
  scopes only the deterministic-winner logic. The operator-
  facing arbitration prompt is deferred.)
- **No swarm-member parsing in MVP**. The `docs/mvp-feature-
  sequence.md` FEAT-010 section also lists swarm member
  report parsing (`AGENTTOWER_SWARM_MEMBER parent=… pane=…
  …`) and swarm parent/child display in `list-agents`. This
  spec scopes only the event-routing-and-arbitration half of
  the original FEAT-010 envelope. Swarm-member parsing
  becomes its own follow-up feature; FEAT-008's existing
  `swarm_member_reported` event type already provides the
  ingest surface, so the deferral is additive, not
  blocking.
- **JSON output shape stability**. All `--json` output across `route
  add`/`list`/`show`/`remove`/`enable`/`disable`, `queue`, and
  `status` is field-ordering-insensitive — consumers MUST NOT rely
  on key order. Additive JSON fields are permitted within a SemVer
  minor bump; field removals or renames require a major bump. The
  `runtime` sub-object in `route show --json` shares this contract.
  The `status` JSON `routing` object versions alongside the SQLite
  schema version (current: v8).
- **Template field sensitivity classification**. Of the eight
  template-whitelist fields (FR-008), exactly one — `{event_excerpt}`
  — is user-controlled (originates in bench-container output) and
  MUST be redacted via FEAT-007 before substitution. The other
  seven (`{event_id}`, `{event_type}`, `{source_agent_id}`,
  `{source_label}`, `{source_role}`, `{source_capability}`,
  `{observed_at}`) are operator-controlled (set at agent
  registration via FEAT-006) or daemon-generated (assigned by
  FEAT-008 on event ingest) and pass through raw. The same
  designation applies to audit-entry identifier fields
  (`winner_master_agent_id`, `target_agent_id`, `target_label` per
  FR-036): operator-controlled identifiers, raw-pass.
- **Bench-container access to route catalog**. Bench-container
  callers may invoke `routes.list`, `routes.show` (read), and also
  `routes.add`/`remove`/`enable`/`disable` (write) — FEAT-010 MVP
  does not restrict route CRUD by caller origin. The host-only
  restriction continues to apply only to `routing enable/disable`
  (FEAT-009 inheritance). Per-caller RBAC is a follow-up feature.
- **Threat model summary**. FEAT-010's trust chain: bench-container
  agents emit log lines → FEAT-008's classifier turns them into
  untrusted events → operator-defined routes (trusted) subscribe →
  the arbitrated master (trusted) becomes the sender of the
  resulting queue row → FEAT-009's existing permission gate decides
  whether the target accepts input → FEAT-009's tmux paste-buffer
  adapter delivers. The only path from untrusted slave output to a
  downstream agent's input stream is via `{event_excerpt}`
  substitution, which is FEAT-007-redacted at render time (FR-026).
- **FEAT-008 event-source authenticity inherited**. FEAT-010 relies
  on FEAT-008's `source_agent_id` integrity — events cannot be
  forged by slaves because FEAT-008 derives `source_agent_id` from
  the pane-to-agent mapping registered at FEAT-006 agent setup, not
  from the log content itself.
- **DoS bounds**. Route-add and other socket calls inherit FEAT-002's
  socket-level rate handling; FEAT-010 adds no per-method rate
  limit (operators are trusted). The audit JSONL stream is bounded
  by the 10,000-entry retry buffer (research §R14) with FIFO
  eviction protecting RAM. Template body is capped at 4 KiB at
  route creation time (data-model.md §1) to prevent storage
  exhaustion via oversized templates.
- **FEAT-008 schema dependency pin**. FEAT-010 requires the FEAT-008
  `events` table to provide `event_id` (INTEGER), `event_type`
  (TEXT, closed set), `source_agent_id` (TEXT), `source_role`
  (TEXT), `source_capability` (TEXT NULL), and `event_excerpt`
  (TEXT). This corresponds to FEAT-008 schema at or above v6 (the
  pre-FEAT-009 baseline). The FEAT-010 v7→v8 migration assumes a
  v7+ starting point.
- **Routing-worker config knob storage**. The three routing-worker
  knobs (`cycle_interval`, `batch_size`, `heartbeat_interval`) are
  sourced from `agenttowerd` startup CLI arguments and held in
  memory only — NOT persisted in SQLite in MVP. Operators set them
  per-daemon-process. Persistent configuration is a follow-up
  feature.
- **Redactor failure surfaces as a skip reason**. If the FEAT-007
  redactor raises an exception while rendering `{event_excerpt}`,
  the worker MUST emit `route_skipped(reason=template_render_error,
  sub_reason=redactor_failure)` and advance the cursor — NOT
  substitute a placeholder or proceed with raw text.
- **Failed `route add` does not emit audit**. CLI validation
  rejections (`route_event_type_invalid`, `route_template_invalid`,
  etc.) exit the CLI with the closed-set error code and write the
  error to stderr; they do NOT emit `route_created` (or any other)
  JSONL audit entry. The operator's audit trail begins at the
  first successfully-created route.
- **"Typical local conditions" definition for SC-001**. The 5-second
  end-to-end latency SLO applies under the following baseline:
  x86_64 Linux host (development workstation or bench-test container
  host), SSD-backed storage for the SQLite registry, fewer than 100
  FEAT-008 events ingested per second, fewer than 1000 enabled
  routes, FEAT-009 delivery worker not saturated by direct-send
  backlog, and no concurrent host-wide CPU pressure. Out-of-spec
  conditions (HDD storage, sustained > 100 events/s, > 1000 routes)
  may exceed the SLO; the spec does not commit to a degraded-mode
  latency budget in MVP.
- **No retention policy in MVP** (FEAT-008 inheritance). The
  `routes` table, `last_consumed_event_id` cursors, and audit
  JSONL grow indefinitely. Operators may manually prune.
- **Authorization at the socket boundary is host-user only**
  (FEAT-009 inheritance). Any caller with socket access can
  create or remove routes. Per-caller RBAC is out of scope.
- **No idle-detection heuristics for routing**. The router
  fires whenever events match, regardless of target
  busyness. FEAT-009's per-target FIFO is the only flow
  control.
- **JSONL audit destination**: Reuses the existing FEAT-008
  `events.jsonl` stream with `route_*` audit event types.
  Operators reading events with `agenttower events --follow`
  see route lifecycle entries inline with classifier events
  and queue audit entries.
