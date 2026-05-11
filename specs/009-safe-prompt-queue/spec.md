# Feature Specification: Safe Prompt Queue and Input Delivery

**Feature Branch**: `009-safe-prompt-queue`
**Created**: 2026-05-11
**Status**: Draft
**Input**: User description: "FEAT-009: Safe Prompt Queue and Input Delivery — durable message queue with permission checks, global routing kill switch, and tmux-safe paste-buffer delivery from master agents to eligible target agents inside bench containers."

## Clarifications

### Session 2026-05-11

- Q: How should the envelope body be persisted in `message_queue.envelope_body`, given the byte-exact delivery requirement and the silence of FR-040 about never-started rows? → A: Persist raw body bytes; delivery worker reads from persisted queue state (not transient memory); redaction applies only to operator-visible surfaces (queue listings, audit excerpts, JSONL/history output); restart before the first delivery attempt MUST still preserve deliverability for `queued` rows.
- Q: Who is authorized to toggle the global routing kill switch, given the tension between FR-027 ("host user") and the socket-boundary assumption ("any socket caller has the full CLI surface")? → A: `routing enable` / `routing disable` are host-only in MVP; bench-container callers may read `routing status` but may not change it; rejected in-container toggle attempts return a closed-set error such as `routing_toggle_host_only`; `queue` and `send-input` operations remain governed by their own FEAT-009 rules, separate from kill-switch ownership.
- Q: How should the sender be identified when `send-input` is invoked from the host, where the caller is not inside any registered tmux pane? → A: `send-input` is valid only from a bench-container thin client whose originating tmux pane resolves to a registered, active `master` agent (per FEAT-006); host-side `send-input` is refused with closed-set error `sender_not_in_pane`; no queue row is created on that refusal. FR-006 is reworded so that host CLI exposure covers `queue`, `routing` (status only — see FR-027), and `status`, but not `send-input`.
- Q: Where do `queue_message_*` audit transitions land — the existing FEAT-008 `events.jsonl` stream or a dedicated `queue.jsonl`? → A: Append queue transition audit rows to the existing FEAT-008 `events.jsonl` using distinct `queue_message_*` event types (`queue_message_enqueued`, `queue_message_delivered`, `queue_message_blocked`, `queue_message_failed`, `queue_message_canceled`, `queue_message_approved`, `queue_message_delayed`); `agenttower events` MUST be able to surface both classifier events and queue transition events in one chronology; degraded JSONL behavior is shared with the existing FEAT-008 stream/writer path.
- Q: What concurrency model should the delivery worker use in MVP, given FR-044 (per-target FIFO) and FR-045 (cross-target parallelism allowed)? → A: One delivery worker in MVP; process ready rows serially in `(enqueued_at, message_id)` order; startup recovery (FR-040) runs before the worker begins; per-target FIFO is guaranteed by the single-worker model; true cross-target parallel delivery is deferred to a later feature.
- Q: How does `routing disable` interact with a delivery attempt that is already in-flight (`delivery_attempt_started_at` committed, terminal stamp not yet written)? → A: `routing disable` stops pickup of new ready rows and turns new `send-input` enqueues into `blocked` rows; any row whose `delivery_attempt_started_at` was already committed at toggle time is allowed to finish to `delivered` or `failed` under normal commit ordering; no mid-flight preemption in MVP.
- Q: What identifier forms does `--target` accept across `send-input` and queue filters, given that the FEAT-006 registry exposes both `agent_id` and `label`? → A: `--target` accepts either `agent_id` or label; if the input matches the `agent_id` shape it is resolved as `agent_id`, otherwise it is resolved as label; multiple label matches return closed-set error `target_label_ambiguous`; no match in either form returns `target_not_found`; queue surfaces (listings and `--json`) show both `agent_id` and `label` for the resolved target.
- Q: How should the 240-char excerpt render a multi-line body across queue listings, audit, and `--json`? → A: Apply FEAT-007 redaction first, then collapse all whitespace runs (including `\n` and `\t`) to a single space, then truncate to the 240-char cap, appending `…` only when truncation actually occurred; the resulting excerpt is always single-line in both human output and `--json`.
- Q: What identifier is recorded for host-originated operator actions (host-side `queue cancel`/`approve`/`delay` and `routing enable`/`disable`), given there is no registered bench-container agent for the host? → A: Use the fixed reserved sentinel `host-operator` consistently across queue operator identity fields, `last_toggled_by_agent_id`, and queue-transition audit rows / JSONL operator identity; the FEAT-006 registry MUST reserve `host-operator` so it can never collide with a real agent_id (UUIDv4 namespace makes collision impossible by construction, and the registry MUST refuse registration of an agent with this literal id).
- Q: What is the canonical timestamp encoding for storage and audit/JSON surfaces, and does `--since` accept the same form? → A: UTC only; ISO 8601 with millisecond resolution and `Z` suffix (e.g., `2026-05-11T15:32:04.123Z`); the same string form is used in SQLite timestamp columns, `events.jsonl`, all `--json` outputs, and queue/routing audit surfaces; `--since` accepts the canonical form and also the same UTC form without milliseconds (e.g., `2026-05-11T15:32:04Z`) for operator convenience.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Master queues and delivers a prompt to a slave (Priority: P1)

A registered master agent inside a bench container sends a prompt to a
registered, active slave agent in any reachable bench container. The host
daemon records the prompt as a durable queue row, performs all permission and
availability checks, then delivers the structured envelope into the slave's
tmux pane via paste-buffer plus a submit keystroke. The operator can see the
delivered row in the queue listing and the corresponding audit entry in the
JSONL history.

**Why this priority**: This is the first slice that gives FEAT-009 its
defining capability: actually moving a prompt from one agent to another. It is
the smallest deliverable that proves the durable queue, the permission gate,
the tmux-safe delivery path, and the audit log are wired up end-to-end.
Without it, every later story has nothing to inspect or override.

**Independent Test**: With FEAT-001..FEAT-008 in place, register a master and
a slave inside the same or different bench containers, run
`agenttower send-input --target <slave-agent-id> --message "hello"`, and
verify (a) one queue row exists with terminal state `delivered`, (b) the
slave's tmux pane received exactly the structured envelope as input, (c) the
JSONL audit history contains the queued → delivered transition pair.

**Acceptance Scenarios**:

1. **Given** a registered, active master agent and a registered, active slave
   agent in any reachable bench container, **When** the master runs
   `agenttower send-input --target <slave-agent-id> --message "do thing"`,
   **Then** the daemon creates exactly one queue row in initial state
   `queued`, the delivery worker transitions it to `delivered` within the
   configured delivery timeout, the slave's tmux pane receives the structured
   envelope verbatim plus one trailing submit keystroke, and the CLI exits
   with status `0`.
2. **Given** the same setup, **When** the master invokes `send-input` with
   `--json`, **Then** the CLI prints exactly one JSON object containing
   `message_id`, terminal `state`, `enqueued_at`, `delivered_at`, sender and
   target identity (`agent_id`, `label`, `role`), and a redacted `excerpt` of
   the body.
3. **Given** a delivered message, **When** the operator runs
   `agenttower queue`, **Then** the listing includes a row for that
   `message_id` with state `delivered`, the sender and target identity, the
   redacted excerpt, `enqueued_at`, and `delivered_at`.
4. **Given** a delivered message, **When** the operator inspects the JSONL
   audit history, **Then** at least two entries reference the `message_id`:
   one `queue_message_enqueued` recording the initial state and one
   `queue_message_delivered` recording the transition; the audit body uses
   the same redaction rules as the queue listing.
5. **Given** a master sending to a registered swarm child (role `swarm`
   parented to a slave), **When** the master runs `send-input`, **Then**
   delivery proceeds the same as the slave case — the `master → swarm`
   permission is allowed.

---

### User Story 2 — Disallowed senders and targets are refused before delivery (Priority: P1)

The daemon enforces a conservative permission gate. Only `master` may send.
Only `slave` and `swarm` may receive. Any other sender role, any other
target role, or any unknown / inactive participant must result in the
message being recorded as `blocked` with a closed-set reason and never being
delivered to any pane. This applies whether the violation is detected at
submit time or after enqueue.

**Why this priority**: Safety. The architecture's central guarantee is that
AgentTower never injects input into the wrong pane. Without enforcement,
every later capability (routing, arbitration, swarm parentage) becomes a
hazard. The MVP must fail closed.

**Independent Test**: Attempt sends across the matrix of role pairs and
availability states — from an `unknown` sender, a `slave` sender, a `swarm`
sender, a `master` sender to an `unknown` target, a `master` sender to a
`master` target, a `master` sender to a `test-runner` target, a `master`
sender to an inactive slave, and a `master` sender to a slave whose
container is no longer running. In every case verify (a) zero bytes were
delivered to any tmux pane, (b) the queue row terminal state is `blocked`
with the expected closed-set `block_reason`, (c) `send-input` exits non-zero
with the matching closed-set CLI error code.

**Acceptance Scenarios**:

1. **Given** an `unknown` sender (a pane not yet promoted via FEAT-006),
   **When** that pane runs `send-input` to any target, **Then** the queue
   row is created in state `blocked` with `block_reason=sender_role_not_permitted`,
   no tmux delivery is attempted, and the CLI exits non-zero with error code
   `sender_role_not_permitted`.
2. **Given** a `slave` sender or a `swarm` sender, **When** that pane runs
   `send-input` to any target, **Then** the row is `blocked` with
   `block_reason=sender_role_not_permitted` and the CLI exits non-zero with
   the same error code.
3. **Given** a `master` sender, **When** the target's role is `unknown`,
   `master`, `test-runner`, or `shell`, **Then** the row is `blocked` with
   `block_reason=target_role_not_permitted` and the CLI exits non-zero with
   the same error code.
4. **Given** a `master` sender, **When** `--target` references an
   `agent_id` that is not present in the FEAT-006 agent registry, **Then**
   no queue row is created, the CLI exits non-zero with error code
   `target_not_found`, and no audit row is appended.
5. **Given** a `master` sender, **When** the target agent is registered but
   marked `active=false` (pane gone, container stopped, agent deregistered),
   **Then** the row is `blocked` with `block_reason=target_not_active`, no
   tmux delivery is attempted, and the CLI exits non-zero with the same
   error code.
6. **Given** a `master` sender, **When** the target's container is no
   longer in the daemon's active container set, **Then** the row is
   `blocked` with `block_reason=target_container_inactive`.
7. **Given** a `master` sender, **When** the target agent is active in
   the registry but the daemon cannot resolve a matching tmux pane in that
   container at delivery time (FEAT-004 discovery shows the pane gone),
   **Then** the row is `blocked` with `block_reason=target_pane_missing` and
   no delivery is attempted.

---

### User Story 3 — Operator inspects and operates the queue (Priority: P2)

An operator on the host or inside a bench container runs `agenttower queue`
and its subcommands `approve`, `delay`, and `cancel` to inspect pending
work and to deliberately override delivery decisions. The queue surface is
the operator's only mandatory control: it must be machine-readable, filter
by state and target, and produce a deterministic exit code that distinguishes
allowed transitions from rejected ones.

**Why this priority**: The MVP CLI surface in `docs/architecture.md` §20
lists `queue`, `queue approve`, `queue delay`, and `queue cancel` as
required commands. Without them, blocked messages have no remediation path
and queued messages cannot be revoked.

**Independent Test**: Create a master → slave delivery, then `delay` it
before delivery, verify state `blocked` with `operator_delayed`; `approve`
it, verify it transitions back to `queued` and proceeds to `delivered`.
Separately, create a `blocked` row from a permission violation (US2),
`cancel` it, verify state `canceled` and no delivery attempted. Verify
that attempting `cancel` on a `delivered` row exits non-zero with
`terminal_state_cannot_change`.

**Acceptance Scenarios**:

1. **Given** zero or more queue rows in any combination of states, **When**
   the operator runs `agenttower queue`, **Then** the CLI prints a tabular
   listing of all rows ordered oldest `enqueued_at` first, including
   `message_id`, sender identity, target identity, `state`, `enqueued_at`,
   the most recent state-transition timestamp, and a redacted `excerpt`.
2. **Given** the same data, **When** the operator runs
   `agenttower queue --state queued` or `--state blocked`, **Then** the
   listing is restricted to rows in that state; `--target <agent-id>`
   restricts to rows whose `target_agent_id` matches; multiple filters are
   AND-combined.
3. **Given** a row in state `blocked`, **When** the operator runs
   `agenttower queue approve <message-id>`, **Then** the row transitions
   `blocked → queued` if and only if its `block_reason` is operator-
   resolvable (`operator_delayed`, `kill_switch_off` when the switch is
   currently on, `target_not_active` when the target is now active); for
   other block reasons the CLI exits non-zero with closed-set error
   `approval_not_applicable` and the state is unchanged.
4. **Given** a row in state `queued`, **When** the operator runs
   `agenttower queue delay <message-id>`, **Then** the row transitions
   `queued → blocked` with `block_reason=operator_delayed` before the
   delivery worker can pick it up; the row remains blocked until the
   operator approves or cancels it.
5. **Given** a row in state `queued` or `blocked`, **When** the operator
   runs `agenttower queue cancel <message-id>`, **Then** the row
   transitions to terminal state `canceled` and no delivery is attempted;
   any later `approve`/`delay`/`cancel` on the same row exits non-zero
   with `terminal_state_cannot_change`.
6. **Given** a row in state `delivered`, `failed`, or `canceled`, **When**
   the operator runs `approve`, `delay`, or `cancel` on it, **Then** the
   CLI exits non-zero with `terminal_state_cannot_change` and no state
   transition is recorded.
7. **Given** any successful queue subcommand, **When** invoked with
   `--json`, **Then** the CLI emits one JSON object describing the row
   in its new state with the same shape used by `send-input --json`.

---

### User Story 4 — Global routing kill switch (Priority: P2)

The daemon exposes a single global routing flag. When disabled, the daemon
must refuse new delivery attempts and stop the delivery worker from picking
up `queued` rows, but operators must still be able to inspect the queue and
cancel rows. Re-enabling routing resumes delivery from where it stopped.

**Why this priority**: `docs/architecture.md` §23 lists "provide a global
routing kill switch" as a security requirement. Operators need an
unambiguous way to halt all delivery during incidents without taking the
daemon offline.

**Independent Test**: Disable routing, run `send-input` to a normally
deliverable target, verify the row lands in `blocked` with
`block_reason=kill_switch_off` and no tmux delivery occurs; run
`agenttower queue` and confirm the row appears; run
`agenttower routing enable`, verify the existing blocked row stays blocked
until explicitly approved, but new `send-input` calls flow through to
`delivered`.

**Acceptance Scenarios**:

1. **Given** routing is disabled (`agenttower routing disable` previously
   succeeded), **When** any caller runs
   `agenttower routing status`, **Then** the CLI prints `disabled` and the
   timestamp of the last toggle along with the agent identity that toggled
   it; `--json` returns the same fields as a single object.
2. **Given** routing is disabled, **When** a master runs `send-input` to
   an otherwise-permitted target, **Then** the queue row is created in
   state `blocked` with `block_reason=kill_switch_off`, no tmux delivery
   is attempted, and the CLI exits non-zero with the same error code.
3. **Given** routing is disabled, **When** the operator runs
   `agenttower queue`, `agenttower queue --json`, or
   `agenttower queue cancel <message-id>`, **Then** the command succeeds
   and behaves identically to the routing-enabled case; only operations
   that would attempt delivery are refused.
4. **Given** rows already in state `queued` when routing is disabled,
   **When** the kill switch flips off, **Then** the delivery worker stops
   picking up new rows for delivery (existing `queued` rows are not
   automatically moved to `blocked`, but no delivery transitions occur
   while disabled).
5. **Given** routing has just been re-enabled, **When** the delivery
   worker resumes its next cycle, **Then** rows that were in state
   `queued` at the time of the toggle are eligible for delivery again in
   per-target FIFO order; rows that were blocked with
   `kill_switch_off` remain blocked until the operator explicitly
   approves them.

---

### User Story 5 — tmux delivery preserves message content and rejects shell injection (Priority: P3)

The daemon delivers the structured envelope to the target tmux pane via the
paste-buffer flow described in `docs/architecture.md` §16. Two invariants
must hold: (a) the raw body must never be interpolated into a shell command
string, so no character or sequence in the body can cause additional
commands to run on the host or in the container; (b) the body must arrive
in the target pane byte-for-byte after UTF-8 round-trip, including
multi-line bodies and tab characters.

**Why this priority**: Security-critical correctness. The MVP allows
masters to type into live agent terminals; a shell-injection escape would
turn the queue into an arbitrary remote-execution surface. Independent
testability is high because the assertions are local to one delivery.

**Independent Test**: Send a payload that contains characters intentionally
chosen to break naive shell quoting (single quotes, double quotes,
backticks, `$()`, `;`, `&&`, embedded newlines, embedded tab characters,
and a multi-byte UTF-8 sequence). Verify the queue row reaches `delivered`,
the slave's tmux pane history contains the exact pasted text (compared
byte-for-byte against the original body), and no additional shell process
was spawned on the host or in the container as a side effect of the
content.

**Acceptance Scenarios**:

1. **Given** a master sending a body containing the characters
   `'$(touch /tmp/should-not-exist); echo "${X}"; rm -rf /; \`uname\``,
   **When** delivery occurs, **Then** the queue row reaches `delivered`,
   the slave's tmux pane received those exact characters as input, and
   `/tmp/should-not-exist` does not exist on the host or inside any
   container.
2. **Given** a body with three lines separated by `\n`, **When** delivery
   occurs, **Then** the target pane receives all three lines as a single
   paste (no per-line command execution), followed by exactly one submit
   keystroke that submits the pasted block as one input event.
3. **Given** a body containing tab characters and a multi-byte UTF-8
   sequence (e.g., an em-dash), **When** delivery occurs, **Then** those
   characters arrive in the target pane unchanged, with no byte-level
   transformation.
4. **Given** a `send-input` call whose `--message` argument is invalid
   UTF-8, contains a NUL byte, or is empty, **When** the daemon
   processes it, **Then** no queue row is created, no tmux delivery is
   attempted, and the CLI exits non-zero with closed-set error code
   `body_invalid_encoding`, `body_invalid_chars`, or `body_empty`
   respectively.
5. **Given** a body whose serialized envelope size exceeds the configured
   maximum, **When** `send-input` runs, **Then** no queue row is created
   and the CLI exits non-zero with `body_too_large`.

---

### User Story 6 — Daemon restart resolves any interrupted delivery (Priority: P3)

The daemon may stop while a delivery attempt is mid-flight: after the
delivery worker invoked tmux but before it persisted the terminal state.
On restart, the daemon must resolve every such ambiguous row to a terminal
state without silently re-delivering the same envelope to the target pane.

**Why this priority**: Without restart safety, the worst-case failure mode
is silent duplicate delivery — the same prompt arrives twice in an agent's
input. This would corrupt any FEAT-010 routing layer built on top of
FEAT-009. The MVP positions AgentTower as a durable local control plane;
mid-flight ambiguity must always resolve conservatively.

**Independent Test**: Submit a `queued` row, stop the daemon process
exactly between the `delivery_attempt_started_at` stamp and the
`delivered_at` stamp (using a fault-injection hook in tests), restart the
daemon, observe the row resolves to terminal state `failed` with closed-
set `failure_reason=attempt_interrupted`, and confirm no second tmux
paste is issued.

**Acceptance Scenarios**:

1. **Given** a row whose `delivery_attempt_started_at` is set but whose
   `delivered_at` and `failed_at` are both unset (i.e., the daemon
   crashed mid-attempt), **When** the daemon restarts, **Then** the row
   transitions to terminal state `failed` with
   `failure_reason=attempt_interrupted` before the delivery worker picks
   up any new work.
2. **Given** the same crash-recovery transition, **When** the recovery
   completes, **Then** exactly one audit entry is appended recording the
   transition, and no second tmux paste is invoked for that row.
3. **Given** any combination of `queued`, `blocked`, `delivered`,
   `failed`, and `canceled` rows that did NOT have an interrupted
   in-flight attempt, **When** the daemon restarts, **Then** every such
   row's state is preserved byte-for-byte.

---

### Edge Cases

- **Send to self**. A master invokes `send-input` with `--target` equal
  to its own `agent_id`. Treated as `target_role_not_permitted` (master
  is not in the allowed target set); blocked, never delivered.
- **Concurrent submission to the same target**. Two masters submit
  `send-input` to the same slave at the same instant. Per-target FIFO
  applies: ordering follows `enqueued_at`; ties are broken by
  `message_id` lexical order. No multi-master arbitration prompt is
  emitted in FEAT-009 (deferred to FEAT-010).
- **Concurrent submission to different targets**. Two masters submit to
  two different slaves. Delivery proceeds in parallel; per-target FIFO
  applies independently to each target.
- **Same-master back-to-back submission**. The same master submits two
  prompts to the same slave back-to-back. The second is queued behind
  the first and delivered only after the first reaches `delivered`,
  `failed`, or `canceled`.
- **Target pane gone between enqueue and delivery**. A row was
  validated and queued; before the delivery worker reaches it, the
  target pane disappears (container restarted, tmux session killed).
  The delivery worker re-checks identity and transitions the row to
  `blocked` with `block_reason=target_pane_missing`, never invoking
  tmux.
- **Target role demoted between enqueue and delivery**. A row was queued
  to a slave; an operator changes the target's role to `unknown` before
  delivery. The delivery worker re-checks role and transitions to
  `blocked` with `block_reason=target_role_not_permitted`.
- **Sender becomes inactive between enqueue and delivery**. Sender's
  container or pane goes away. The queued row still proceeds to
  delivery, because the message has already been authorized; the sender's
  current liveness is not re-checked at delivery time. The audit row
  retains the sender identity at the time of enqueue.
- **Sender role demoted between enqueue and delivery**. Same as above —
  delivery proceeds; the authorization decision is locked at enqueue
  time. (This is a deliberate MVP choice: revocation of a master's
  promotion does not retroactively cancel already-queued prompts.)
- **Operator approves a row whose block reason is intrinsic**. A row is
  blocked with `target_role_not_permitted`. The operator runs `approve`.
  The CLI rejects with `approval_not_applicable` (the role rule is not
  operator-resolvable). The operator must `cancel` instead.
- **Operator approves while kill switch is off**. Approving an
  `operator_delayed` row while the kill switch is `disabled` flips the
  row state to `queued`, but the delivery worker will then re-evaluate
  and re-block it with `kill_switch_off`. Closed-set error
  `routing_disabled` is NOT raised by `approve` itself; the operator
  sees the re-block in the next `queue` listing.
- **`send-input` invoked while routing disabled**. Row is created in
  state `blocked` with `block_reason=kill_switch_off`; the CLI exits
  non-zero with `routing_disabled`.
- **`cancel` on a row that the delivery worker is actively processing**.
  Treated as a race: if the delivery worker has already stamped
  `delivery_attempt_started_at` for that row, `cancel` exits non-zero
  with `delivery_in_progress`; the operator must wait for the row to
  reach a terminal state, after which `cancel` is unnecessary.
- **`approve` or `delay` on a row that the delivery worker is actively
  processing**. Same race: exits non-zero with `delivery_in_progress`.
- **Queue row references a sender or target that has been hard-deleted
  from the agent registry**. The row's stored identity fields
  (`sender_agent_id`, `sender_label`, `sender_role`, `target_agent_id`,
  `target_label`, `target_role` as captured at enqueue time) remain
  the source of truth for queue listings and audit; missing live agents
  do not break inspection.
- **Daemon receives `send-input` while shutting down**. Reject with
  closed-set error `daemon_shutting_down`; no row is created.
- **Body larger than the configured maximum**. Reject at submit time
  with `body_too_large`; no row is created. The configured maximum is
  applied to the serialized envelope, not just the body.
- **JSONL audit append fails mid-transition**. Treated the same as any
  durability failure in FEAT-008: buffer the audit entry in memory,
  retry on the next cycle, surface the degraded state through
  `agenttower status`. The SQLite state transition is the authority;
  the JSONL audit append is best-effort retry, never a blocker for
  state advancement.
- **Multi-line body whose first line happens to begin with `[AgentTower]`**.
  The envelope wraps the body, so a body starting with `[AgentTower]`
  cannot be confused with envelope metadata; the envelope's body section
  is delimited from the headers by a blank line and consumed verbatim
  to end-of-message.

## Requirements *(mandatory)*

### Functional Requirements

#### Envelope and message body

- **FR-001**: System MUST define a structured prompt envelope with the
  following required fields rendered as plain-text headers: `Message-Id`
  (UUIDv4), `From` (sender agent id, label, role, capability), `To`
  (target agent id, label, role, capability), `Type` (literal `prompt`),
  `Priority` (literal `normal` in MVP), `Requires-Reply` (literal `yes`
  in MVP). The envelope MUST be human-readable in a plain terminal.
- **FR-002**: System MUST place the body after a single blank line
  following the headers and consume the body verbatim from that point to
  end-of-envelope.
- **FR-003**: System MUST reject any `send-input` whose body is empty,
  is not valid UTF-8, contains a NUL byte (`\x00`), or contains any
  ASCII control character other than `\n` (`\x0a`) and `\t` (`\x09`).
- **FR-004**: System MUST cap the serialized envelope size at a
  configurable maximum, default 64 KiB. Submissions whose serialized
  envelope exceeds the cap MUST be rejected with closed-set CLI error
  `body_too_large`; no queue row is created.
- **FR-005**: System MUST allow multi-line bodies. Line endings inside
  the body MUST be preserved byte-for-byte from `--message` input to
  the delivered tmux paste.

#### `send-input` command

- **FR-006**: System MUST expose `agenttower send-input --target
  <agent-id-or-label> --message <text>` from the bench-container
  thin-client CLI surface only. `send-input` MUST be valid only
  when the originating tmux pane (resolved via the thin client's
  pane context) maps to a registered, active `master` agent in
  the FEAT-006 agent registry. Host-side invocations (any caller
  whose tmux pane does not resolve to a registered agent) MUST
  be refused with closed-set error `sender_not_in_pane`; no queue
  row is created and no audit row is appended. The host CLI
  retains full access to `agenttower queue` (including `approve`,
  `delay`, `cancel`), `agenttower routing` (subject to FR-027's
  host-only constraint on `enable`/`disable`), and
  `agenttower status`. The `--target` argument (in both
  `send-input` and the queue filter forms) MUST accept either an
  `agent_id` or a `label`: if the supplied value matches the
  `agent_id` shape (UUIDv4 textual form), it MUST be resolved as
  `agent_id` against the registry; otherwise it MUST be resolved
  as `label`. Multiple active label matches MUST exit non-zero
  with closed-set `target_label_ambiguous` and no queue row is
  created. No match in either form MUST exit non-zero with
  `target_not_found`. Queue surfaces (listings and `--json`) MUST
  show both `agent_id` and `label` for the resolved target so
  scripts and operators can disambiguate after the fact.
- **FR-007**: System MUST also accept `--message-file <path>` as a
  mutually exclusive alternative to `--message` so multi-line and
  shell-special-character bodies can be supplied without shell quoting
  pitfalls. Exactly one of `--message` or `--message-file` MUST be
  required; `--message-file -` reads the body from stdin.
- **FR-008**: System MUST treat `send-input` as the sole entry point
  that creates new queue rows. The daemon MUST NOT create queue rows
  in response to events, schedules, or implicit triggers in MVP.
- **FR-009**: System MUST, on a successful submission, return either
  the row's terminal state (default behavior: wait until terminal state
  or the configured delivery wait timeout, then return the current
  state) or the row's initial state (`--no-wait` flag: return after
  enqueue without waiting for the delivery worker).
- **FR-010**: System MUST distinguish, in `send-input` exit codes,
  between terminal-success (`delivered`, exit `0`), terminal-failure
  (`blocked`, `failed`, `canceled`, exit non-zero with a closed-set
  error code matching the row's reason), wait-timeout (`queued` or
  `blocked` mid-transition, exit non-zero with `delivery_wait_timeout`),
  and submit-time validation rejection (no row created, exit non-zero
  with the matching `body_*` or `target_*` or `sender_*` error code).
- **FR-011**: System MUST support `agenttower send-input --json`
  emitting exactly one JSON object on stdout with stable fields:
  `message_id`, `state`, `block_reason` (nullable), `failure_reason`
  (nullable), `sender` (object with `agent_id`, `label`, `role`,
  `capability`), `target` (same shape), `enqueued_at`,
  `delivery_attempt_started_at` (nullable),
  `delivered_at` (nullable), `failed_at` (nullable), `canceled_at`
  (nullable), `excerpt` (redacted, ≤ 240 characters of the body, with
  ellipsis when truncated).

#### Durable queue table

- **FR-012**: System MUST persist a `message_queue` SQLite table whose
  rows include at minimum: `message_id` (UUIDv4, primary key),
  `state` (one of `queued`, `blocked`, `delivered`, `canceled`,
  `failed`), `block_reason` (closed set, nullable),
  `failure_reason` (closed set, nullable), `sender_agent_id`,
  `sender_label`, `sender_role`, `sender_capability`,
  `target_agent_id`, `target_label`, `target_role`,
  `target_capability`, `target_container_id`, `target_pane_id`
  (resolved at enqueue), `envelope_body` (raw body bytes, always
  persisted verbatim; never redacted at storage time — see FR-012a
  for delivery-source rules and FR-047a for redaction surfaces),
  `envelope_body_sha256` (hex), `envelope_size_bytes`,
  `enqueued_at`, `delivery_attempt_started_at` (nullable),
  `delivered_at` (nullable), `failed_at` (nullable),
  `canceled_at` (nullable), `last_updated_at`, `operator_action`
  (nullable, e.g., `approved`, `delayed`, `canceled`),
  `operator_action_at` (nullable).
- **FR-013**: System MUST treat the five queue states as the only valid
  values for `state`. No other state values may appear in storage,
  CLI output, or audit logs.
- **FR-014**: System MUST treat `delivered`, `canceled`, and `failed`
  as terminal states. Once a row enters a terminal state, no further
  state transitions are allowed; attempts MUST exit non-zero with
  `terminal_state_cannot_change`.
- **FR-015**: System MUST treat `queued` and `blocked` as non-terminal
  states. The allowed transitions are: `queued → delivered`,
  `queued → failed`, `queued → blocked` (only on operator `delay` or
  on a re-check at delivery time that surfaces a new block reason),
  `queued → canceled` (operator), `blocked → queued` (operator
  `approve`), `blocked → canceled` (operator `cancel`).
- **FR-016**: System MUST persist queue rows durably enough that the
  table is recovered byte-for-byte after a daemon restart, modulo the
  recovery transition mandated by FR-040.
- **FR-012a**: System MUST treat the persisted `envelope_body` column
  as the sole source of the bytes delivered to the target tmux pane.
  The delivery worker MUST read the body from SQLite at the start of
  each delivery attempt rather than relying on any in-memory copy
  carried over from enqueue. A `queued` row whose persisted body is
  intact MUST remain deliverable across a clean daemon restart;
  restart MUST NOT cause loss of deliverability for `queued` rows
  whose `delivery_attempt_started_at` was never stamped.
- **FR-012b**: System MUST encode every timestamp — in
  `message_queue` columns, `daemon_state` (routing flag) columns,
  `events.jsonl` audit entries, and all `--json` outputs — as a
  UTC ISO 8601 string with millisecond resolution and a literal
  `Z` suffix (e.g., `2026-05-11T15:32:04.123Z`). Local time,
  epoch-seconds, and offset suffixes other than `Z` MUST NOT
  appear in storage or in any operator-visible surface. The
  `--since` filter on `agenttower queue` MUST accept the
  canonical millisecond form and MUST also accept the UTC form
  without milliseconds (e.g., `2026-05-11T15:32:04Z`) for
  operator convenience; both forms MUST resolve to the same UTC
  instant.

#### Queue states and the closed-set reason vocabulary

- **FR-017**: System MUST emit `block_reason` values only from this
  closed set: `sender_role_not_permitted`, `target_role_not_permitted`,
  `target_not_active`, `target_pane_missing`,
  `target_container_inactive`, `kill_switch_off`, `operator_delayed`.
- **FR-018**: System MUST emit `failure_reason` values only from this
  closed set: `attempt_interrupted`, `tmux_paste_failed`,
  `docker_exec_failed`, `tmux_send_keys_failed`,
  `pane_disappeared_mid_attempt`.
- **FR-019**: System MUST set `state=queued` at row creation only
  when all of the following are true at enqueue time: routing is
  enabled, sender has a permitted role and is currently active,
  target is a registered active agent with a permitted role, target's
  container is active, target's pane is resolvable in current
  FEAT-004 discovery.
- **FR-020**: System MUST set `state=blocked` at row creation
  whenever any condition in FR-019 fails. The first failing condition,
  evaluated in the order listed in FR-019, determines the
  `block_reason`.

#### Permission rules

- **FR-021**: System MUST permit sender role `master` only. Any other
  sender role (`slave`, `swarm`, `test-runner`, `shell`, `unknown`)
  MUST be refused with `block_reason=sender_role_not_permitted`.
- **FR-022**: System MUST permit target roles `slave` and `swarm`
  only. Any other target role (`master`, `test-runner`, `shell`,
  `unknown`) MUST be refused with
  `block_reason=target_role_not_permitted`.
- **FR-023**: System MUST refuse delivery when the sender is marked
  inactive at enqueue time, with
  `block_reason=sender_role_not_permitted` (an inactive sender is
  treated identically to an unprivileged sender).
- **FR-024**: System MUST refuse delivery when the target is marked
  inactive at enqueue time or at the delivery worker's pre-paste
  re-check, with `block_reason=target_not_active`.
- **FR-025**: System MUST re-evaluate permission and availability
  checks at the start of every delivery attempt. If any check fails
  at re-check time, the row MUST be transitioned `queued → blocked`
  with the appropriate `block_reason`, and no tmux paste MUST be
  invoked. Sender liveness and sender role are NOT re-checked at
  delivery time (authorization is locked at enqueue per the
  Assumptions section).

#### Global routing kill switch

- **FR-026**: System MUST persist a single boolean routing flag in
  `daemon_state` with default value `enabled=true` on a freshly
  initialized state directory.
- **FR-027**: System MUST expose CLI commands
  `agenttower routing enable`, `agenttower routing disable`, and
  `agenttower routing status` that each accept `--json`. In MVP,
  `routing enable` and `routing disable` MUST be accepted only from
  callers connecting from the host (outside any bench container);
  bench-container thin-client callers MUST be refused for these two
  subcommands and the CLI MUST exit non-zero with closed-set error
  `routing_toggle_host_only`, leaving the persisted flag and audit
  log unchanged. `routing status` (including `--json`) MUST remain
  callable from any authorized socket caller, host or bench
  container. No further RBAC applies in MVP; `queue` and
  `send-input` operations remain governed by their own FEAT-009
  rules, independent of kill-switch ownership.
- **FR-028**: System MUST, while the flag is `disabled`, create new
  rows from `send-input` in state `blocked` with
  `block_reason=kill_switch_off` and refuse to pick up any
  additional `queued` row in the delivery worker. A row whose
  `delivery_attempt_started_at` was already committed at the
  moment of toggle MUST be allowed to run to a terminal state
  (`delivered` or `failed`) under the normal FR-041 / FR-042
  commit ordering; the kill switch MUST NOT preempt or abort an
  in-flight attempt in MVP.
- **FR-029**: System MUST, while the flag is `disabled`, continue to
  serve `agenttower queue`, `agenttower queue cancel`, and
  `agenttower queue delay` without restriction.
- **FR-030**: System MUST, while the flag is `disabled`, refuse
  `agenttower queue approve` for rows whose `block_reason` is
  `kill_switch_off` (it cannot resolve the underlying block until the
  switch is enabled). Approving a row blocked for other reasons is
  still allowed; the operator may see the row re-block on the next
  delivery worker cycle if the switch is still off.

#### Operator commands

- **FR-031**: System MUST expose `agenttower queue` as the canonical
  list command with filters `--state <state>`, `--target <agent-id>`,
  `--sender <agent-id>`, `--since <iso8601>`, `--limit <n>`, and
  `--json`. Ordering is `enqueued_at` ascending; the final
  tie-breaker is `message_id` lexical order.
- **FR-032**: System MUST expose `agenttower queue approve
  <message-id>`, `agenttower queue delay <message-id>`, and
  `agenttower queue cancel <message-id>`. Each MUST accept `--json`,
  succeed with exit `0` only when the transition was applied, and
  return a closed-set non-zero exit otherwise.
- **FR-033**: System MUST treat `approve` as valid only when the
  row's current state is `blocked` AND the `block_reason` is
  operator-resolvable. Operator-resolvable reasons are:
  `operator_delayed`, `kill_switch_off` (only when the switch is
  currently `enabled`), `target_not_active`,
  `target_pane_missing`, `target_container_inactive`. Other reasons
  MUST exit non-zero with `approval_not_applicable`.
- **FR-034**: System MUST treat `delay` as valid only when the row's
  current state is `queued`. Other states MUST exit non-zero with
  closed-set `delay_not_applicable` (for `blocked`) or
  `terminal_state_cannot_change` (for terminal states).
- **FR-035**: System MUST treat `cancel` as valid when the row's
  current state is `queued` or `blocked`. Terminal states MUST exit
  non-zero with `terminal_state_cannot_change`.
- **FR-036**: System MUST refuse `approve`, `delay`, and `cancel`
  for any row whose `delivery_attempt_started_at` is currently set
  and whose terminal-state stamps are not yet set, exiting non-zero
  with closed-set `delivery_in_progress`.

#### tmux delivery mechanics

- **FR-037**: System MUST deliver every envelope via the
  paste-buffer flow: load the envelope into a tmux buffer via
  `tmux load-buffer -` (or an equivalent stdin-based command), paste
  into the target pane via `tmux paste-buffer -t <pane>`, then send a
  single submit keystroke via `tmux send-keys -t <pane> Enter`.
- **FR-038**: System MUST NOT interpolate any byte of the body or
  envelope into a shell command string. Every tmux invocation MUST
  receive the body via stdin or via tmux's own no-shell argument
  passing. The implementation MUST NOT use `sh -lc "tmux set-buffer
  -- <message>"` or any equivalent shell-string construction with the
  body as a literal substitution.
- **FR-039**: System MUST clear (or otherwise scope) the tmux paste
  buffer after each delivery so that an unrelated subsequent
  `paste-buffer` invocation cannot inadvertently re-paste the message
  body. The implementation MAY use a uniquely named buffer per
  message or `tmux delete-buffer` after `paste-buffer`.

#### Delivery worker, durability, and restart safety

- **FR-040**: System MUST, on daemon startup, find every row whose
  `delivery_attempt_started_at` is set AND whose `delivered_at`,
  `failed_at`, and `canceled_at` are all unset, and transition each
  such row to terminal state `failed` with
  `failure_reason=attempt_interrupted` before the delivery worker
  picks up any new work.
- **FR-041**: System MUST, in the delivery worker, stamp
  `delivery_attempt_started_at` (committed to SQLite) BEFORE invoking
  any tmux command for that row.
- **FR-042**: System MUST, after a successful tmux paste plus submit
  keystroke, transition the row to `delivered`, stamp `delivered_at`,
  and commit before issuing any subsequent delivery for the same
  target.
- **FR-043**: System MUST, on any tmux/docker error during a delivery
  attempt, transition the row to `failed` with the appropriate
  `failure_reason` from FR-018 and commit before picking up the next
  row.
- **FR-044**: System MUST enforce per-target FIFO ordering at the
  delivery worker: for a given `target_agent_id`, at most one row may
  have `delivery_attempt_started_at` set with no terminal stamp at
  any moment; the next row may only begin once the current row
  reaches a terminal state.
- **FR-045**: System MUST run a single delivery worker in MVP that
  processes ready rows serially in ascending `(enqueued_at,
  message_id)` order across all targets, with at most one tmux
  delivery in flight at any moment. The FR-040 startup-recovery
  pass MUST complete before this worker begins picking up rows.
  Per-target FIFO (FR-044) is satisfied trivially by the single-
  worker model; cross-target FIFO is an incidental consequence of
  serial dispatch in MVP. Genuine cross-target parallel delivery
  (a worker pool or per-target workers) is deferred to a later
  feature and MUST NOT be introduced in FEAT-009.

#### Audit / JSONL

- **FR-046**: System MUST append one JSONL audit entry per state
  transition to the existing FEAT-008 `events.jsonl` stream
  (shared with classifier events; not a dedicated queue file).
  Each entry MUST use an `event_type` drawn from the
  `queue_message_*` namespace: `queue_message_enqueued`,
  `queue_message_delivered`, `queue_message_blocked`,
  `queue_message_failed`, `queue_message_canceled`,
  `queue_message_approved`, `queue_message_delayed`. The entry
  MUST include `message_id`, `from_state`, `to_state`, `reason`
  (the `block_reason` or `failure_reason` when relevant), the
  operator identity (when the transition was operator-driven),
  and the transition timestamp. For host-originated operator
  actions (host-side `queue approve`/`delay`/`cancel` and
  `routing enable`/`disable`), the operator identity MUST be the
  fixed reserved sentinel string `host-operator`; the FEAT-006
  agent registry MUST refuse registration of an agent with this
  literal id so the sentinel cannot collide with a real agent.
  `agenttower events` MUST surface both classifier events and
  `queue_message_*` transition events in one interleaved
  chronological view.
- **FR-047**: System MUST include a redacted `excerpt` (≤ 240
  characters, derived from the body via the FEAT-007 redaction
  utility) in every audit entry that records a state transition
  for which the body is meaningful (`enqueued`, `delivered`,
  `blocked` at enqueue with the body already validated). The raw
  body MUST NOT appear in audit output.
- **FR-047a**: System MUST apply body redaction only at
  operator-visible surfaces: `agenttower queue` listings (the
  `excerpt` column), audit entries / JSONL history output
  (`excerpt` field), and `send-input --json` (the `excerpt`
  field). The persisted `envelope_body` column, the tmux paste
  buffer, and the bytes delivered to the target pane MUST NOT be
  redacted; they MUST remain byte-exact to the body supplied at
  submit time.
- **FR-047b**: System MUST render the excerpt with the following
  fixed pipeline applied to every operator-visible surface
  (`agenttower queue` human and `--json`, audit `excerpt` in
  `events.jsonl`, `send-input --json`): (1) apply the FEAT-007
  redaction utility to the raw body; (2) collapse every run of
  whitespace characters (including `\n`, `\t`, `\r`, and ASCII
  space) to a single ASCII space; (3) truncate the result to at
  most 240 characters; (4) append the ellipsis character `…`
  (U+2026) if and only if step (3) actually discarded characters.
  The excerpt MUST therefore be single-line in both human-readable
  and `--json` output.
- **FR-048**: System MUST treat audit-append failures the same way
  FEAT-008 treats JSONL durability failures, reusing the same
  FEAT-008 stream/writer path: buffer in memory, retry on the next
  cycle, surface a degraded state through `agenttower status`.
  SQLite state transitions are the source of truth and MUST NOT
  block on `events.jsonl` write failures.

#### Failure handling

- **FR-049**: System MUST treat a closed-set CLI error vocabulary as
  contractual. The full set (one error code per row, listed without
  state-machine duplication) is:
  `sender_role_not_permitted`, `target_role_not_permitted`,
  `target_not_active`, `target_not_found`, `target_pane_missing`,
  `target_label_ambiguous`, `sender_not_in_pane`,
  `target_container_inactive`, `kill_switch_off`, `routing_disabled`,
  `body_empty`, `body_invalid_encoding`, `body_invalid_chars`,
  `body_too_large`, `delivery_wait_timeout`,
  `delivery_in_progress`, `approval_not_applicable`,
  `delay_not_applicable`, `terminal_state_cannot_change`,
  `routing_toggle_host_only`, `daemon_shutting_down`,
  `daemon_unavailable`.
- **FR-050**: System MUST exit non-zero with a stable exit-code
  mapping for each closed-set error code. The exact integer
  assignment MAY vary across implementation revisions, but the
  mapping MUST be exposed through `--json` output as a string code,
  and the mapping MUST be documented and tested.

#### Interaction boundaries

- **FR-051**: System MUST NOT create or transition any queue row in
  response to a FEAT-008 event in MVP. Event-to-route subscriptions
  are explicitly out of scope.
- **FR-052**: System MUST NOT emit an arbitration prompt or any
  inter-master notification in MVP. Multi-master arbitration is
  deferred to FEAT-010; FEAT-009 provides only the per-target FIFO
  primitive on which arbitration will later build.
- **FR-053**: System MUST NOT infer or interpret semantic content of
  the body. Body classification, summarization, intent extraction,
  and any LLM-driven processing are out of scope.
- **FR-054**: System MUST NOT include a TUI, web UI, or desktop
  notification surface in FEAT-009; CLI plus JSONL plus
  `agenttower status` are the only user-facing surfaces.

### Key Entities *(include if feature involves data)*

- **Message (queue row)**: A durable record of one prompt-delivery
  attempt. Holds the envelope body, sender and target identity
  captured at enqueue, current state, closed-set reason fields, all
  transition timestamps, and operator action metadata. One message
  per `--target` per `send-input` invocation.
- **Envelope**: The plain-text rendering of a Message that is pasted
  into the target pane. Built from the Message's identity and body
  fields per FR-001 and FR-002. Never used as a storage primary
  key; the Message row is the durable artifact.
- **Routing flag**: A single boolean in the daemon's
  `daemon_state` table representing the global routing kill switch
  (`enabled` / `disabled`). Includes `last_toggled_at` and
  `last_toggled_by_agent_id` for audit. For host-originated
  toggles, `last_toggled_by_agent_id` is the reserved sentinel
  `host-operator` (see FR-046).
- **Audit entry**: One JSONL record per Message state transition.
  Append-only, never re-written. Carries the redacted excerpt, not
  the raw body.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can register a master and a slave, run
  `agenttower send-input --target <slave> --message <text>`, and
  observe the slave's tmux pane receive the message envelope within
  3 seconds of the CLI command being invoked under typical local
  conditions (no kernel pressure, healthy Docker, ≤ 4 KiB body).
- **SC-002**: 100% of attempted sends from senders whose role is not
  `master`, OR to targets whose role is not `slave` or `swarm`, OR
  to inactive / non-existent targets, MUST be recorded as either
  refused at submit (`target_not_found`) or blocked with the
  matching closed-set reason; 0% reach `delivered`.
- **SC-003**: A payload containing every shell metacharacter from
  the set `'` `"` `` ` `` `$` `(` `)` `;` `|` `&` `<` `>` `\` `\n`
  `\t` plus a 2-byte UTF-8 character can be delivered to a slave
  with no additional process spawned on the host or in the
  container, verifiable via process-tree snapshots before and after
  delivery.
- **SC-004**: After a daemon restart that interrupted N in-flight
  delivery attempts, 100% of those rows resolve to terminal state
  `failed` with `failure_reason=attempt_interrupted` before the
  next delivery worker cycle, and 0% receive a second tmux paste.
- **SC-005**: When the global kill switch is disabled, 100% of
  newly submitted sends land in `blocked` with
  `block_reason=kill_switch_off` and 0% reach the target pane, while
  `agenttower queue` listing still returns success.
- **SC-006**: Every queue row's full transition history is
  reconstructible from JSONL audit entries alone, without consulting
  SQLite, for at least the last 1,000 transitions per agent pair
  under MVP's no-rotation policy (FEAT-008 inheritance).
- **SC-007**: A `send-input --json` invocation, on success or
  failure, prints exactly one JSON object on stdout that conforms
  to the FR-011 shape and parses with `jq` with zero errors.
- **SC-008**: An operator can delay an in-flight queued message
  before the delivery worker picks it up, observe its state as
  `blocked` with `operator_delayed`, then `approve` it and observe
  the same `message_id` reach `delivered` — all within a single
  `agenttower queue` listing's worth of polling latency.
- **SC-009**: A body whose decoded length exceeds the configured
  cap is rejected at submit time with `body_too_large` in under
  100 ms, with zero bytes of the body persisted in the queue table
  (no `message_queue` row is created for rejected submissions).
- **SC-010**: Per-target FIFO is observably correct: for any
  sequence of N submissions to the same target by any combination
  of authorized senders, the order in which rows reach
  `delivered` matches the order of `enqueued_at`, modulo rows that
  reach `blocked`, `failed`, or `canceled`.

## Assumptions

- **CLI default wait behavior**: `send-input` blocks until the row
  reaches a terminal state or until the configured delivery wait
  timeout (default 10 s) elapses. A `--no-wait` flag is provided
  for fire-and-forget invocations that return immediately after
  enqueue. The default is wait-style because the MVP operator
  experience favors seeing `delivered` vs. `blocked` directly in
  the CLI exit.
- **Approval policy**: No approval is required by default for
  `master → slave` or `master → swarm`. `approve` is the
  operator's tool to unblock rows that previously landed in
  `blocked`. A per-target or per-role "require approval" policy is
  deferred to a later feature; FEAT-009 ships only the operator
  override.
- **`delay` semantics**: `delay` is a manual hold — a `queued`
  row transitions to `blocked` with
  `block_reason=operator_delayed` and remains blocked until the
  operator approves or cancels it. There is no automatic
  re-queueing timer in MVP. This is the simplest of the three
  reasonable interpretations (timestamped retry / manual hold /
  simple state flip).
- **Excerpt size in queue listings and audit**: 240 characters
  after redaction, with ellipsis when truncated, matching the
  FEAT-008 convention.
- **Body size cap**: 64 KiB on the serialized envelope (not the
  raw body), configurable in `config.toml`. Chosen because typical
  prompt envelopes are < 4 KiB and 64 KiB is well below tmux
  paste-buffer limits while leaving headroom for multi-line
  pasted code.
- **Per-target FIFO is in scope; multi-master arbitration is
  not**: The architecture's §17 arbitration prompt is FEAT-010's
  responsibility. FEAT-009 only delivers FIFO ordering so FEAT-010
  has a primitive to build on.
- **Sender liveness at delivery time is NOT re-checked**: Once
  enqueued, a message proceeds even if the sender's role is later
  demoted or the sender's container goes away. This avoids a
  whole class of consistency races and treats authorization as a
  decision locked at enqueue time. Operators who need to revoke a
  pending prompt use `queue cancel`.
- **Target liveness, role, container, and pane ARE re-checked at
  delivery time**: This is the conservative dual to the sender
  policy. A target that disappears between enqueue and delivery
  must not receive surprise input from a stale row.
- **Submit keystroke is `Enter`**: The MVP sends one
  `tmux send-keys -t <pane> Enter` after `paste-buffer`. Agents
  that require a different submit pattern (the Codex/Claude
  driver note in `.codex/speckit-claude-driver.json` is captured
  as future work, not MVP scope) are out of scope for FEAT-009.
- **Routing flag scope**: One global boolean per daemon instance.
  Per-target, per-role, or per-sender kill switches are out of
  scope; that finer-grained control belongs in FEAT-010 or later.
- **JSONL audit destination**: Reuses the existing FEAT-008
  `events.jsonl` stream with `queue_message_*` audit event types
  (see FR-046 for the enumerated set), rather than opening a
  second JSONL file. Operators reading events with
  `agenttower events` see queue transitions interleaved
  chronologically with classifier events. Confirmed in the
  Clarifications session above; no planning-stage revisit.
- **No retention policy in MVP**: As with FEAT-008's events,
  queue rows and audit entries accumulate without automatic
  rotation. Manual operator pruning is allowed.
- **Authorization at the socket boundary is host-user only**:
  Any caller with access to the daemon socket has the full CLI
  surface available for `send-input`, `queue` (including
  `queue cancel`, `queue approve`, `queue delay`), and
  `routing status`. The only MVP exception is `routing enable`
  / `routing disable`, which are host-only (see FR-027); bench-
  container callers attempting either get closed-set
  `routing_toggle_host_only`. There is no per-caller RBAC in MVP
  beyond that origin check.
- **`send-input` argument parsing**: Exactly one of `--message`
  or `--message-file` must be supplied. `--message-file -` reads
  from stdin. This lets shells with awkward quoting bypass the
  shell quoting surface entirely.
