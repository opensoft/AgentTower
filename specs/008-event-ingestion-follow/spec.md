# Feature Specification: Event Ingestion, Classification, and Follow CLI

**Feature Branch**: `008-event-ingestion-follow`
**Created**: 2026-05-09
**Status**: Draft
**Input**: User description: "FEAT-008: Event Ingestion, Classification, and Follow CLI — convert attached tmux pane logs into durable, inspectable AgentTower events with conservative rule-based classification and a followable CLI surface."

## Clarifications

### Session 2026-05-10

- Q: When the daemon enters degraded mode for events persistence (e.g., SQLite read-only), what is the locked behavior? → A: Both — buffer the in-flight cycle's classified events in memory and retry the SQLite commit on the next cycle once the degraded state clears, AND surface a visible degraded condition through `agenttower status` while persistence is failing; clear the condition only after the buffered events commit successfully.
- Q: What is the representation of `event_id`? → A: SQLite `INTEGER PRIMARY KEY AUTOINCREMENT`, emitted in JSONL as a JSON number; default ordering uses `event_id` as the final stable tie-breaker; `--cursor` is the encoded last seen `event_id`, opaque at the CLI boundary but integer-backed internally.
- Q: What is the source of `record_at` in MVP? → A: Always `null` in MVP. `observed_at` is always populated; no timestamp extraction heuristics ship in FEAT-008. Future source-time support can populate `record_at` without changing current ordering semantics.
- Q: What is the events retention policy in MVP? → A: No automatic retention, purge, or rotation in FEAT-008. SQLite event rows and the JSONL events history both grow indefinitely; operators may manually delete state if needed. Retention management is deferred to a later feature, not hidden as background behavior.
- Q: How should `agenttower events --target <agent-id>` behave when the agent isn't registered? → A: Error with non-zero exit and a closed-set `agent_not_found` error code/message; this is distinct from "registered agent with zero events" which returns success with an empty result.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Operator inspects classified events for an attached agent (Priority: P1)

A registered agent inside a bench container is producing tmux pane output that
has been attached to AgentTower via the FEAT-007 `attach-log` flow. The host
daemon ingests new bytes from that log, conservatively classifies them, persists
each derived event, and surfaces them through `agenttower events`. From inside
or outside the container, an operator can list the most recent events for any
attached agent and see the classifier type, a redacted excerpt, and the
event timestamp.

**Why this priority**: This is the first slice that gives FEAT-008 user value.
Without it, FEAT-007's attached logs remain raw bytes on disk and the
later FEAT-009/FEAT-010 routing layers have nothing to subscribe to. It is the
smallest deliverable that ingests, classifies, persists, and inspects events.

**Independent Test**: With FEAT-001..FEAT-007 in place, register an agent,
attach its log, write a known classifier-trigger line into the pane, wait one
reader cycle, then run `agenttower events --target <agent-id>` and verify
exactly one event appears with the expected classifier type and a
redacted excerpt.

**Acceptance Scenarios**:

1. **Given** a registered agent with an `active` log attachment and an empty
   log, **When** a single line matching the `error` classifier rule is written
   to the log and one reader cycle elapses, **Then** `agenttower events
   --target <agent-id>` lists exactly one event of type `error` with that
   line's redacted excerpt and a timestamp at or after the write.
2. **Given** the same agent with one prior `error` event recorded, **When** a
   second line matching the `test_passed` classifier rule is appended,
   **Then** `agenttower events --target <agent-id>` returns both events in
   strict reader-observed order, oldest first by default.
3. **Given** a line containing one of the redaction patterns shipped in
   FEAT-007, **When** that line is ingested and classified, **Then** the
   excerpt persisted to SQLite and to the JSONL history is the redacted
   form, never the raw form.
4. **Given** a registered agent with no log attachment, **When** the operator
   runs `agenttower events --target <agent-id>`, **Then** the daemon returns
   an empty result with no error and no synthesized "no attachment" event.
5. **Given** an `<agent-id>` that is not present in the FEAT-002 agent
   registry (typo, deleted, or never registered), **When** the operator
   runs `agenttower events --target <agent-id>`, **Then** the CLI exits
   with a non-zero status and a closed-set `agent_not_found` error
   message; this is distinct from the empty-result success case in
   scenario #4.

---

### User Story 2 — Operator follows the live event stream (Priority: P2)

An operator runs `agenttower events --follow` (optionally narrowed by
`--target <agent-id>`) from a host or container shell. The command first
prints any backlog requested by the operator and then blocks, streaming each
new event as the reader emits it. The follow stream survives transient log
silence and continues until the operator interrupts it.

**Why this priority**: Follow mode is the primary human-facing surface for
"watch what is happening right now" and is required by the architecture
(`agenttower events --follow` in `docs/architecture.md` §20). It is
strictly a streaming view of US1 events, so it cannot ship before US1.

**Independent Test**: Start `agenttower events --follow --target <agent-id>`
in one terminal; in a second terminal write three classifier-trigger lines
to that agent's log spaced more than the debounce window apart; verify the
follow terminal prints three events in order within one reader cycle each,
without re-printing any backlog already displayed.

**Acceptance Scenarios**:

1. **Given** `agenttower events --follow` is running with no `--target`
   filter, **When** any attached agent emits a new classified event,
   **Then** that event is printed to the follow stream within one reader
   cycle of the underlying log write.
2. **Given** `agenttower events --follow --target <agent-id>` is running,
   **When** another agent emits an event, **Then** that event is NOT
   printed to the follow stream.
3. **Given** the follow stream has been idle for longer than one reader
   cycle, **When** the operator sends SIGINT, **Then** the command exits
   cleanly with a non-error status and writes no further output.

---

### User Story 3 — Daemon restart does not duplicate events (Priority: P2)

The host daemon may stop and restart between reader cycles for any reason
(operator-driven restart, crash recovery, OS reboot). On restart, the reader
must resume from the persisted offset for each attached log and must not
re-emit events for log content already classified before the restart.

**Why this priority**: Without restart safety, every operator-visible
guarantee from US1 and US2 collapses on the next daemon restart. The MVP
positions AgentTower as a durable local control plane; duplicate events
would corrupt downstream FEAT-009/FEAT-010 routing.

**Independent Test**: Attach a log, write five classifier-trigger lines,
allow one reader cycle, stop the daemon, verify five events are persisted,
restart the daemon, wait two reader cycles with no new log writes, and
verify the event count is still exactly five and no new event rows have
been appended to the SQLite events table or the JSONL history.

**Acceptance Scenarios**:

1. **Given** N events have been persisted for an agent, **When** the daemon
   stops and restarts with no new log bytes appended, **Then** the SQLite
   events count and the JSONL appended-line count for that agent are both
   unchanged.
2. **Given** the daemon stopped mid-cycle after persisting K events but
   before advancing offsets, **When** the daemon restarts, **Then** the
   reader resumes at the last persisted offset and re-observes the same
   bytes, but duplicate suppression ensures the K events are not
   re-appended.
3. **Given** the daemon stops and the log file is appended to while the
   daemon is down, **When** the daemon restarts, **Then** the reader
   ingests only the bytes appended after the persisted offset and emits
   events only for them.

---

### User Story 4 — File-change carry-over from FEAT-007 behaves correctly (Priority: P2)

The reader is the production caller that exercises FEAT-007's file-change
detection and reader-recovery helpers. Truncation, recreation, deletion, and
operator-explicit re-attach must all behave exactly as the FEAT-007 spec
prescribed, including timing assertions (≤ 1 reader cycle) and the
no-replay invariant.

**Why this priority**: FEAT-007 shipped the helpers and unit-level coverage
but explicitly left timing + no-replay assertions and the round-trip
integration test (T175, T176, T177) for FEAT-008 to land. The mvp-feature-
sequence carryover block is normative.

**Independent Test**: For each of (truncate-in-place, delete-and-recreate
with new inode, delete-and-leave-missing, missing-then-reappear-then-
re-attach), drive the scenario against a real reader loop and assert the
documented row-status transitions, lifecycle event emissions, offset
resets, and the absence of any event whose excerpt comes from pre-reset
bytes.

**Acceptance Scenarios**:

1. **Given** an active attachment with offsets `(B, L, E)` and the log file
   is truncated in place (same inode, smaller size), **When** at most one
   reader cycle elapses, **Then** the offsets reset to `(0, 0, 0)`, the
   inode is preserved, `file_size_seen` is updated to the post-truncate
   size, exactly one `log_rotation_detected` lifecycle event is emitted,
   and zero durable events are appended whose excerpts come from
   pre-truncate bytes.
2. **Given** an active attachment and the log file is deleted and
   recreated with a new inode, **When** at most one reader cycle elapses,
   **Then** the offsets reset to `(0, 0, 0)`, the inode is updated to the
   new inode, exactly one `log_rotation_detected` lifecycle event is
   emitted, and no durable event is created from any byte present before
   the recreation.
3. **Given** an active attachment whose file is deleted, **When** one
   reader cycle elapses, **Then** the row transitions `active → stale`,
   exactly one `log_file_missing` lifecycle event is emitted, exactly one
   `log_attachment_change` audit row is appended, and the offsets remain
   byte-for-byte unchanged.
4. **Given** a stale attachment whose file is then recreated at the same
   path, **When** one reader cycle elapses, **Then** exactly one
   `log_file_returned` lifecycle event is emitted (suppression-keyed by
   `(agent_id, log_path, file_inode)`), the row remains `stale`, the
   offsets remain unchanged, and no durable event is created.
5. **Given** a stale attachment whose file has reappeared, **When** the
   operator runs `agenttower attach-log --target <agent-id>`, **Then** the
   re-attach succeeds via the FEAT-007 file-consistency check (FR-021),
   offsets reset per FEAT-007 rules, and only bytes written after the
   re-attach produce durable events.

---

### User Story 5 — Operator gets machine-readable event output (Priority: P3)

Scripts, dashboards, and downstream tooling need a stable, machine-readable
view of events. `agenttower events --json` must produce one JSON object per
event with a stable schema, suitable for piping into `jq` or other tools.
The same flag combines with `--follow` to produce a JSON stream with the
same per-event shape.

**Why this priority**: The MVP CLI in `docs/architecture.md` §20 lists
`agenttower events`. Machine output is required by the broader project
expectation that every CLI is scriptable, but it is not required for the
first interactive demo of US1.

**Independent Test**: Append a known event-trigger line; run `agenttower
events --target <agent-id> --json --limit 1`; pipe through `jq` to assert
the documented field set is present and types match.

**Acceptance Scenarios**:

1. **Given** at least one event exists for an agent, **When** the operator
   runs `agenttower events --target <agent-id> --json --limit 1`, **Then**
   stdout is exactly one JSON object on a single line containing the
   documented event fields and no additional fields beyond the stable
   schema.
2. **Given** `--follow --json` is active, **When** the reader emits a new
   event, **Then** stdout receives one new JSON line in the same schema,
   terminated by a newline.

---

### User Story 6 — Failure surfaces are visible without crashing the daemon (Priority: P3)

When a per-attachment reader cycle fails (unreadable file, sudden
permission change, offset row missing for an active attachment, daemon
degraded mode), the reader loop must continue serving other attachments
and the operator must be able to see the failure. Failures are surfaced
through diagnostic lifecycle events (FEAT-007 surface) and through the
daemon's `status` API, never by silent loss of attached agents.

**Why this priority**: Failure visibility is a correctness requirement,
not a feature. It is P3 because once the happy paths in US1..US4 work, an
operator can already file a bug; the polish here is making the bug
self-evident.

**Independent Test**: Make one attached log file unreadable via
permissions; trigger a reader cycle; assert that other attached agents
still produce events and that the affected attachment's failure is
visible through the daemon `status` output and through FEAT-007 lifecycle
events.

**Acceptance Scenarios**:

1. **Given** two attached agents A and B and B's log file becomes
   unreadable (`EACCES`), **When** one reader cycle elapses, **Then** A
   continues producing events for new log content and the daemon reports
   the per-attachment failure in `agenttower status` (or the same
   diagnostic surface FEAT-007 already uses).
2. **Given** the daemon is in degraded mode (e.g., SQLite write error),
   **When** the reader attempts a cycle, **Then** the reader does not
   silently drop events; it either retries on the next cycle once the
   degraded state clears or surfaces a visible failure that points to
   the underlying degraded condition.
3. **Given** an attachment row exists but its corresponding offset row is
   missing or inconsistent, **When** the reader observes the
   inconsistency, **Then** the reader skips that attachment for the
   cycle, logs the inconsistency, and does not invent or guess offset
   values.

---

### Edge Cases

- **Single line spans multiple reader cycles** (cycle ends mid-line): the
  reader MUST NOT emit an event from a partial line. It advances byte offsets
  only across complete newline-terminated records and re-reads the partial
  tail on the next cycle.
- **Many lines arrive between cycles**: the reader processes them in file
  order and may emit multiple events from one cycle. Per-cycle event count
  is bounded by the configured per-cycle read cap (see FR-019); excess
  bytes remain on disk and are processed on the following cycle.
- **Empty log file** (attachment exists, file is `0` bytes): the reader
  performs one observation per cycle and emits no events.
- **Log file present, no new bytes since last cycle**: the reader records
  the cycle observation and emits no events. Last-output timing tracking
  for `long_running` is updated as needed (FR-013).
- **Same byte sequence appears twice in distinct cycles** (reader read the
  bytes on cycle N, daemon crashed before persisting offsets, reader
  re-reads them on cycle N+1): duplicate suppression via persisted
  per-attachment offsets prevents a second event (US3 AS2).
- **Classifier rule overlap** (one line matches both `error` and
  `test_failed`): the classifier emits exactly one event using the
  documented rule-priority order (FR-008). It does not fan out into
  multiple event types from one line.
- **Debounce collapse for `activity`**: rapid bursts of generic output
  collapse into one `activity` event per debounce window. Other event
  classes (FR-014) remain one-to-one.
- **`pane_exited` inference on a still-attached log file**: emitted when
  FEAT-004's pane discovery marks the source pane inactive AND the
  attached log has not received bytes for the configured grace window
  (FR-018). It is NOT inferred purely from terminal output text.
- **`swarm_member_reported` on a malformed `AGENTTOWER_SWARM_MEMBER`
  line**: the line is ignored at the classifier level and produces a
  generic `activity` event instead. Strict parsing is documented in
  FR-009.
- **File rotation between read and offset persist**: `reader_cycle_offset_
  recovery` handles the file-change classification before bytes are read,
  so a same-cycle truncate/recreate produces the reset path and zero
  events from pre-rotation bytes (US4 AS1, AS2).
- **Reader sees `MISSING` followed by `REAPPEARED` in adjacent cycles
  before any operator action**: behaves per US4 AS3 then US4 AS4. No
  durable event is emitted by either transition.
- **Excerpt longer than the configured per-event excerpt cap**: the
  excerpt is truncated to the cap with a documented truncation marker;
  redaction runs before truncation so secret patterns split across the
  truncation boundary remain redacted.
- **JSONL events file write transient failure**: the durable SQLite write
  is the source of truth; the JSONL append is best-effort within one
  cycle. Failed JSONL appends are visible as a daemon degraded condition
  and retried on subsequent cycles using a watermark, never silently
  dropped.
- **Operator runs `events --follow` against a daemon that is not
  running**: the CLI reports the FEAT-002 "daemon unreachable" surface,
  not a silent hang.
- **Operator runs `events` while a reader cycle is mid-write**: the
  query reads the SQLite snapshot at the time of the call and never
  partially-rendered events. SQLite consistency is the contract.

## Requirements *(mandatory)*

### Functional Requirements

#### Reader Loop and Offset Advancement

- **FR-001**: The host daemon MUST run a background reader that visits every
  attachment in `active` status at least once per reader cycle. The reader
  cycle wall-clock cap is `1` second at MVP scale; the implementation MAY
  use a tighter cycle.
- **FR-002**: For each visited attachment, the reader MUST call
  `agenttower.logs.reader_recovery.reader_cycle_offset_recovery(...)` exactly
  once per cycle BEFORE reading any bytes for that attachment in that
  cycle. The reader MUST act on the returned `ReaderCycleResult.change`
  before attempting to read bytes (e.g., when the result indicates
  `TRUNCATED`, `RECREATED`, or `MISSING`, the byte-read step is skipped or
  restarts from the freshly-reset offset).
- **FR-003**: The reader MUST NOT mutate `log_attachments` or `log_offsets`
  rows directly. Status transitions, inode/size observation updates, and
  offset resets MUST flow through FEAT-007 helpers
  (`reader_cycle_offset_recovery`, `lo_state.reset`,
  `lo_state.update_file_observation`, and the `LogService` re-attach path).
  Only offset advancement during normal reads is performed by the reader,
  and only via the documented `log_offsets` advance path described in
  FR-004.
- **FR-004**: The reader is the SOLE production caller that may advance
  `log_offsets.byte_offset`, `log_offsets.line_offset`, and
  `log_offsets.last_event_offset`. The test seam
  `agenttower.state.log_offsets.advance_offset_for_test` MUST NOT be
  imported by any production module. The existing AST gate
  (`tests/unit/test_logs_offset_advance_invariant.py`) MUST continue to
  pass.
- **FR-005**: The reader MUST advance offsets only across complete records
  (newline-terminated lines as the MVP record boundary). Partial trailing
  bytes are re-read on the next cycle.
- **FR-006**: The reader MUST persist the durable event row AND the
  advanced offset row in a single atomic commit per emitted event (or per
  cycle batch within a single transaction), so a crash between events
  cannot leave the SQLite event count out of sync with the persisted
  offset. The JSONL append (FR-029) is performed AFTER the SQLite commit.

#### Classifier

- **FR-007**: The classifier MUST be rule-based only. The MVP rule
  catalogue is closed; additions are per-feature changes. No LLM call,
  network call, or model inference is permitted on the classifier path.
- **FR-008**: The classifier MUST classify each complete record into
  exactly one of these event types:
  `activity`, `waiting_for_input`, `completed`, `error`, `test_failed`,
  `test_passed`, `manual_review_needed`, `long_running`, `pane_exited`,
  `swarm_member_reported`. When a record matches multiple rules, the
  documented rule-priority order resolves the tie deterministically. A
  test fixture MUST exist for every rule and for the priority order.
- **FR-009**: The classifier rule that emits `swarm_member_reported` MUST
  parse exactly the line shape documented in `docs/architecture.md` §11:
  `AGENTTOWER_SWARM_MEMBER parent=<agent-id> pane=<tmux-pane-id>
  label=<label> capability=<capability> purpose=<short-purpose>`.
  Malformed variants (missing required keys, invalid agent-id shape,
  whitespace-corrupted values) MUST classify as `activity` and MUST NOT
  produce a `swarm_member_reported` event.
- **FR-010**: Every classifier rule (regex / matcher) MUST be expressed
  in code such that it can be asserted in unit tests without inspecting
  daemon internals. Hidden heuristics that cannot be asserted in tests
  are forbidden. The classifier MUST be a pure function: same input
  bytes plus same prior reader-state inputs yields same output type.
- **FR-011**: The classifier MUST be conservative. When a record is
  ambiguous, it MUST classify as `activity` rather than guess one of the
  domain-specific types.
- **FR-012**: Classifier output MUST carry the redacted excerpt, NEVER the
  raw excerpt. Redaction uses the FEAT-007 redaction utility.
- **FR-013**: The classifier MUST track per-attachment "last output at"
  for `long_running` inference. `long_running` is emitted exactly once
  per running task when the configured grace window passes without new
  output following a record that is itself classified as ongoing work
  (e.g., `activity` after `waiting_for_input` is not eligible). The
  detailed eligibility table is part of the classifier rule catalogue
  and MUST be testable line-by-line.

#### Debounce

- **FR-014**: Debounce semantics MUST be:
  - **Scope**: per-attachment.
  - **Window**: a configurable wall-clock window with a documented MVP
    default (≤ 5 seconds at MVP scale).
  - **Collapse-eligible classes**: `activity` ONLY. Multiple `activity`
    classifications within one window collapse into one `activity` event
    whose excerpt is the latest record's redacted excerpt and whose
    debounce metadata records the collapsed count and the window
    bounds.
  - **One-to-one classes**: `waiting_for_input`, `completed`, `error`,
    `test_failed`, `test_passed`, `manual_review_needed`,
    `long_running`, `pane_exited`, `swarm_member_reported`. Each
    qualifying record produces exactly one event.
- **FR-015**: Debounce state MUST NOT span daemon restarts. After a
  restart, the first qualifying record produces an event; collapsing
  resumes from that record onward.

#### `pane_exited` Inference

- **FR-016**: `pane_exited` MUST be inferred from FEAT-004 pane state
  (pane no longer present in tmux discovery for the attached pane
  identity) AND a configurable grace window (see FR-017) without new
  log output. It MUST NOT be inferred from log text alone.
- **FR-017**: The grace window before `pane_exited` is emitted MUST have
  a documented MVP default (≤ 30 seconds at MVP scale) and MUST be
  testable through dependency injection of the clock.
- **FR-018**: Exactly one `pane_exited` event MUST be emitted per
  attached pane lifecycle. If the same pane id reappears later (FEAT-004
  notes pane ids may be reused), it counts as a new lifecycle once the
  attachment is re-bound.

#### Per-cycle Bounds

- **FR-019**: The reader MUST cap the bytes read per attachment per
  cycle. The cap MUST have a documented MVP default sufficient to drain
  typical interactive output without starving other attachments. Bytes
  beyond the cap remain on disk and are processed on the next cycle. The
  cap MUST be observable in test (e.g., via configuration injection).

#### Restart Resume and Duplicate Suppression

- **FR-020**: On daemon start, the reader MUST treat the persisted
  per-attachment offsets as authoritative and resume from them.
- **FR-021**: An event is "new" iff its source byte range begins at or
  after the persisted `byte_offset` for its attachment at the moment of
  the cycle that emits it. The reader MUST NOT emit an event for any
  byte range strictly less than the persisted `byte_offset`.
- **FR-022**: Restart resume MUST NOT depend on JSONL state. The JSONL
  history is append-only and inspectable but not load-bearing for
  duplicate suppression. SQLite + persisted offsets are the source of
  truth.
- **FR-023**: After restart, the reader MUST handle the case where the
  log file's inode or size disagrees with the persisted observation by
  delegating to `reader_cycle_offset_recovery` (FR-002), which will
  classify TRUNCATED / RECREATED / MISSING / REAPPEARED and apply
  FEAT-007's rules without re-emitting historical events.

#### Persistence and JSONL Surface

- **FR-024**: Each emitted event MUST be persisted as one row in a
  durable SQLite events table whose schema includes the fields listed
  in the **Event** entity below. Inserts MUST be transactional with the
  offset advance per FR-006.
- **FR-025**: Each emitted event MUST also be appended as exactly one
  JSON object on its own line to the project's JSONL events history file
  (FEAT-001's events writer). The JSON shape MUST be the documented
  stable schema (FR-027).
- **FR-026**: The JSONL events history MUST contain ONLY FEAT-008
  durable events. FEAT-007 lifecycle events
  (`log_rotation_detected`, `log_file_missing`, `log_file_returned`,
  `log_attachment_orphan_detected`, `mounts_json_oversized`,
  `socket_peer_uid_mismatch`, audit-failure lifecycle signals) MUST
  continue to flow through the FEAT-007 lifecycle logger surface and
  MUST NOT appear in the FEAT-008 events stream. A single integration
  test (consolidating FEAT-007 T173) MUST assert this separation.
- **FR-027**: The JSONL stable schema for one event MUST include at
  minimum: `event_id`, `event_type`, `agent_id`, `attachment_id`,
  `log_path`, `byte_range_start`, `byte_range_end`, `line_offset_start`,
  `line_offset_end`, `observed_at` (reader timestamp; always
  populated), `record_at` (best-effort source time; in FEAT-008
  MVP this field is always emitted as `null` — no timestamp
  extraction heuristics ship in MVP, and any future source-time
  support is a non-breaking schema-version bump that does not
  change ordering semantics), `excerpt` (redacted),
  `classifier_rule_id`, `debounce` (object containing `window_id`,
  `collapsed_count`, `window_started_at`, `window_ended_at`), and
  `schema_version`. Additional optional fields MAY be added in later
  features behind a non-breaking schema-version bump.
- **FR-028**: Event ordering on read MUST be deterministic. The CLI's
  default order is oldest-first by `(observed_at ASC, byte_range_start
  ASC, event_id ASC)`. `event_id` is the final stable tie-breaker and
  is the SQLite `INTEGER PRIMARY KEY AUTOINCREMENT` value (monotonic
  per daemon process). `--reverse` flips the order; no other ordering
  is supported in MVP.
- **FR-029**: If the JSONL append fails after the SQLite commit
  succeeds, the failure MUST be recorded as a daemon degraded
  condition and retried on subsequent cycles using a watermark
  (e.g., last successfully-appended `event_id`). Events MUST NOT be
  silently dropped from JSONL, and the SQLite row remains the source
  of truth.

#### CLI Surface

- **FR-030**: `agenttower events` MUST list events. Default behavior:
  - oldest-first, capped at a documented MVP page size (≤ 50);
  - filterable by `--target <agent-id>`;
  - filterable by `--type <event_type>` (repeatable);
  - filterable by `--since <iso-8601>` and `--until <iso-8601>`;
  - paginated via `--limit N` and `--cursor <opaque>`. The cursor is
    opaque at the CLI boundary but is internally an encoding of the
    last seen `event_id` (the integer primary key) plus the active
    sort direction; clients MUST treat it as opaque and only round-
    trip the value emitted by a prior page;
  - returns deterministic order per FR-028.
- **FR-031**: `agenttower events` default human output MUST render one
  event per row, including timestamp, agent label and id, event type,
  and a one-line excerpt (further truncated for terminal display from
  the persisted excerpt cap). The default human output is for human
  scanning and is not contractually stable across MVP minor versions.
- **FR-032**: `agenttower events --json` MUST emit one JSON object per
  event, one event per line, in the schema of FR-027. The JSON output
  IS the stable contract for scripting consumers. Combined with
  `--follow`, the JSON line stream extends with new events as they are
  emitted.
- **FR-033**: `agenttower events --follow` MUST stream new events as
  they are emitted by the reader. By default it prints no backlog; it
  prints only events emitted at or after the moment the follow stream
  is established. `--since <iso-8601>` MAY be combined with `--follow`
  to print a bounded backlog before streaming.
- **FR-034**: The follow stream MUST detect the daemon being unavailable
  (FEAT-002 surface) and exit with a non-zero status and a clear
  message. Operator-initiated SIGINT MUST exit cleanly with a zero
  status.
- **FR-035**: `agenttower events` MUST honor the FEAT-005 thin-client
  contract: it works identically from the host and from inside a bench
  container by routing through the mounted Unix socket.
- **FR-035a**: When `agenttower events --target <agent-id>` is invoked
  with an `agent-id` that is not present in the FEAT-002 agent
  registry, the CLI MUST exit with a non-zero status and emit a
  closed-set `agent_not_found` error (machine-readable code + human
  message). This is distinct from the empty-result success case where
  the agent IS registered but has no events or no log attachment. The
  same rule applies to `agenttower events --follow --target
  <agent-id>` at follow-stream initialization.

#### Failure Surface

- **FR-036**: A reader cycle for one attachment that fails MUST NOT
  prevent other attachments' cycles from running.
- **FR-037**: Per-attachment reader failures MUST be visible to
  operators through the daemon `status` surface (or an equivalent
  inspect path) AND through the FEAT-007 lifecycle logger when the
  failure maps to one of the FEAT-007 lifecycle event types.
- **FR-038**: An unreadable log file (`EACCES`, `ENOENT` outside the
  FEAT-007 missing/recreated path, or any other I/O error) MUST be
  surfaced as a per-attachment diagnostic and MUST NOT cause loss of
  the attachment row.
- **FR-039**: A missing offset row for an active attachment MUST be
  treated as an inconsistency: the reader skips that attachment for
  the cycle and surfaces the inconsistency. The reader MUST NOT
  invent offset values to keep going.
- **FR-040**: When the daemon enters degraded mode for events
  persistence (e.g., SQLite is read-only), the reader MUST NOT
  silently drop events. The reader MUST:
  1. Buffer the in-flight cycle's classified events in memory and
     retry the SQLite commit on the next cycle once the degraded
     state clears.
  2. Surface a visible degraded condition through `agenttower status`
     (alongside the FEAT-007 lifecycle logger when applicable) while
     events persistence is failing.
  3. Clear the degraded condition only after the buffered events
     commit successfully.

  The buffer MUST be bounded by the per-cycle byte cap (FR-019) and
  the per-cycle event count it implies; if a degraded window exceeds
  what one cycle can carry forward, the reader stops advancing
  offsets so that unread bytes remain on disk for the next cycle and
  no events are lost. This behavior parallels FR-029's JSONL-failure
  pattern and MUST be testable.

#### Integration Contracts with FEAT-007 (locked from carry-over)

- **FR-041**: Reader-cycle entry point obligation. The reader MUST
  call `agenttower.logs.reader_recovery.reader_cycle_offset_recovery(...)`
  per FR-002. This helper owns the
  `unchanged | truncated | recreated | missing | reappeared` dispatch,
  the `BEGIN IMMEDIATE` flip from `active → stale`, the
  `log_attachment_change` audit row append, and the lifecycle-event
  suppression mechanism owned by FEAT-007 (FEAT-007 spec FR-061) for
  the emission of `log_rotation_detected` / `log_file_missing` /
  `log_file_returned`. Note: `FR-061` here refers to the FEAT-007
  spec, not to a FEAT-008 requirement; FEAT-008's FR list ends at
  FR-045.
- **FR-042**: File-change classifier obligation. Code that needs to
  classify a file-change observation MUST consume
  `agenttower.state.log_offsets.detect_file_change(host_path,
  stored_inode, stored_size_seen) -> FileChangeKind` (a pure function
  with no side effects) or the equivalent stat-driven branch already
  embedded in `reader_cycle_offset_recovery`. The reader MUST NOT
  re-implement file-change classification.
- **FR-043**: FEAT-007 carry-over integration tests. FEAT-008 MUST
  ship integration tests against the real reader loop that land:
  - T175: truncation detected within one reader cycle (≤ 1 s wall-clock
    at MVP scale);
  - T176: recreation (changed inode) detected within one reader cycle;
  - T177: file-deleted → file-recreated → operator-explicit re-attach
    round-trip behaves per US4 AS3..AS5.
  Each test MUST also assert the no-replay invariant: no durable
  event whose excerpt comes from pre-reset bytes.
- **FR-044**: Optional consolidated lifecycle-surface assertion. FEAT-008
  MAY add a single integration test (consolidating FEAT-007 T173) that
  asserts every lifecycle event class enumerated in FR-026 routes
  through the FEAT-007 lifecycle logger and never appears in the
  FEAT-008 events stream. The dedicated per-class FEAT-007 tests
  remain authoritative.

#### Configuration and Defaults

- **FR-045**: All MVP defaults named in this spec
  (reader cycle cap, debounce window, `pane_exited` grace window,
  per-event excerpt cap, per-cycle byte cap, default page size) MUST
  be configurable through the FEAT-001 configuration surface and MUST
  be visible in `agenttower config paths` or an equivalent diagnostic
  output. Defaults MUST be documented in the FEAT-008 plan.

### Key Entities

- **Event (durable)**: One classified observation derived from a complete
  log record. Identity: `event_id` (SQLite `INTEGER PRIMARY KEY
  AUTOINCREMENT`, monotonic per daemon, emitted in JSONL as a JSON
  number; opaque at the CLI boundary). Linkage: `agent_id`,
  `attachment_id`, `log_path`. Position:
  `byte_range_start`, `byte_range_end`, `line_offset_start`,
  `line_offset_end`. Timing: `observed_at` (reader wall-clock at
  classification, always populated), `record_at` (best-effort source
  time; always `null` in FEAT-008 MVP).
  Classification: `event_type` (one of the 10 enum values),
  `classifier_rule_id` (which rule fired). Content: `excerpt`
  (redacted, capped). Grouping: `debounce` (window_id,
  collapsed_count, window_started_at, window_ended_at). Schema:
  `schema_version`. Ordering guarantee: monotonic `event_id` per
  daemon process; cross-process ordering uses
  `(observed_at, byte_range_start)`.
- **Event Stream (JSONL)**: Append-only newline-delimited JSON file at
  the FEAT-001 events history path. One line per event. Stable schema
  per FR-027. Inspectable but not load-bearing for restart resume.
- **Reader-Cycle State (in-memory)**: Per-attachment cycle-local state:
  the `ReaderCycleResult` returned by FEAT-007's helper, the bytes
  read for the current cycle, the post-classify event batch, the
  per-attachment "last output at" used by `long_running`, and the
  pre-cycle `(byte_offset, line_offset, last_event_offset)`. Discarded
  at end of cycle; not persisted.
- **Debounce Window**: Per-attachment, per-event-class window with
  `window_id` (opaque), `window_started_at`, `window_ended_at`,
  `collapsed_count`. Materialized into the durable Event row at
  emission time; no separate persistent table required for MVP.
- **Classifier Rule**: Identified by `classifier_rule_id`. Carries
  the matcher (regex or equivalent), the produced `event_type`, and
  the priority for tie-breaking. Catalogued in code; documented in
  the FEAT-008 plan; testable line by line.
- **Reader Failure (diagnostic)**: Per-attachment failure record
  surfaced through `agenttower status` and (where mapped) through
  FEAT-007 lifecycle events. Not a durable Event; never appears in
  the FEAT-008 events stream.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can list classified events for any attached
  agent within `5` seconds of a triggering log line being written, end-to
  end (write → reader cycle → SQLite commit → CLI render).
- **SC-002**: `agenttower events --follow` prints a new event within
  one reader cycle (≤ `1` second at MVP scale) of the underlying log
  write, measured from the last byte of the triggering record being
  flushed to disk.
- **SC-003**: Across `10` consecutive daemon restarts with no
  intervening log writes, the SQLite event count and JSONL appended-
  line count for every attached agent remain unchanged (zero
  duplicates, zero drops).
- **SC-004**: Truncation in place is detected and offsets reset to
  `(0, 0, 0)` within one reader cycle, and zero durable events are
  emitted whose excerpts originate from pre-truncate bytes (FEAT-007
  T175 promoted to FEAT-008 integration coverage).
- **SC-005**: File recreation (changed inode) is detected and offsets
  reset within one reader cycle, with the same no-replay invariant
  as SC-004 (FEAT-007 T176).
- **SC-006**: For the deleted → recreated → operator-explicit
  re-attach round-trip, the documented sequence of row-status,
  lifecycle, and offset-reset effects holds in `100` % of test
  iterations across `100` runs of the integration test (FEAT-007
  T177).
- **SC-007**: The classifier produces the documented `event_type` for
  every fixture line in the rule catalogue with `100` % accuracy and
  produces `activity` for every documented ambiguous line.
- **SC-008**: Zero production modules import
  `agenttower.state.log_offsets.advance_offset_for_test`. The AST
  gate `tests/unit/test_logs_offset_advance_invariant.py` continues
  to pass.
- **SC-009**: Zero FEAT-007 lifecycle event classes (FR-026) appear
  in the JSONL events history across the FEAT-008 integration suite.
- **SC-010**: A reader cycle that fails for one attachment leaves
  every other attachment producing events on its next cycle in
  `100` % of test iterations.
- **SC-011**: `agenttower events --json` schema is stable: every
  event in the integration suite parses against the documented
  schema (FR-027) with zero schema validation failures.
- **SC-012**: `agenttower events` produces identical output (modulo
  pagination cursor) when invoked from the host and from inside a
  bench container against the same daemon.

## Assumptions

- **FEAT-001..FEAT-007 are complete and merged.** FEAT-008 consumes
  them. In particular, FEAT-007's `attach-log` flow, its log offset
  schema, its lifecycle logger, its redaction utility, and its
  reader-recovery helper are present and behaving per their spec.
- **MVP scope is bench containers only.** Host-only tmux panes are
  out of scope, in line with the architecture's MVP decision (`docs/
  architecture.md` §2). The reader does not attempt to ingest from
  host-only tmux panes even if such an attachment somehow exists.
- **One host daemon per host user.** No cross-host coordination is
  attempted; events live entirely under
  `~/.local/state/opensoft/agenttower/`.
- **Log records are newline-terminated.** MVP treats `\n` as the
  record boundary. Binary or non-newline-terminated payloads are
  out of scope.
- **Wall-clock time is the daemon process clock.** No external time
  service is consulted. Tests inject the clock for FR-013, FR-014,
  FR-016, and FR-017.
- **Per-MVP scale**: ≤ `50` attached agents, ≤ a few KB/s per agent
  of typical interactive output. The cycle cap, byte cap, and
  debounce defaults assume this scale; they are configurable
  (FR-045).
- **No LLM classification, no prompt routing, no notifications, no
  automatic input delivery.** These are out of scope for FEAT-008
  and remain reserved for FEAT-009 / FEAT-010 / later features.
- **No event-driven automation.** FEAT-008 makes events durable and
  inspectable. Subscribing to events for routing and arbitration is
  FEAT-010.
- **No automatic retention, purge, or rotation in MVP.** SQLite event
  rows and the JSONL events history both grow indefinitely under
  FEAT-008. Disk usage scales with activity; at MVP scale (≤ 50
  agents, ≤ a few KB/s per agent) this is acceptable for normal use.
  Operators MAY manually delete state if needed. Automatic retention
  management (TTL, count-bound rolling purge, JSONL rotation) is
  deferred to a later feature; FEAT-008 MUST NOT silently prune
  events as a background behavior.
- **No UI/TUI beyond the CLI.** TUI and desktop notifications are
  later work.
- **`pane_exited` depends on FEAT-004 pane discovery.** If FEAT-004
  has not run a pane scan recently enough to mark a pane inactive,
  `pane_exited` is not emitted on the basis of log silence alone
  (FR-016).
- **Lifecycle events stay diagnostic.** FEAT-007 lifecycle events
  remain on the FEAT-007 surface and never become entries in the
  FEAT-008 events stream (FR-026, SC-009).
