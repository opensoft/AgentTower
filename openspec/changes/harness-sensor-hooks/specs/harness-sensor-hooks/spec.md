# harness-sensor-hooks

Capability: Tier-1 inbound event reporting from Claude Code and Codex CLI
lifecycle hooks — how AgentTower declares them, receives them, maps them onto
the existing closed event set, governs them, and manages the harness config
files that carry them.

## Purpose

Lets AgentTower observe an agent's real lifecycle — prompt submitted, turn
stopped, input awaited, turn failed — from the harness's own hook surface
instead of inferring it from scraped pane scrollback, while remaining a
strictly passive sensor that can never block, alter, approve, or steer the
harness it observes.

## ADDED Requirements

### Requirement: Observational-only hook execution

The AgentTower hook command SHALL be strictly observational. It SHALL always
terminate with exit status 0, SHALL NEVER write to standard output, SHALL NEVER
emit a hook decision, and SHALL complete within a bounded wall-clock budget of
at most 1 second. A missing daemon, an unresolvable pane, a socket error, or a
daemon-side rejection SHALL fail open: the hook still exits 0 and the agent
continues to be observed at the Tier-0 tmux floor. Diagnostic output SHALL be
limited to at most one short line on standard error, and only when hook debug
output is explicitly enabled by environment variable.

#### Scenario: Daemon unreachable

- **WHEN** a harness hook fires while the AgentTower daemon socket is absent or
  not accepting connections
- **THEN** the hook command exits 0 within its time budget, writes nothing to
  standard output, and the harness turn proceeds unaffected

#### Scenario: Hook never influences the harness

- **WHEN** any subscribed lifecycle event fires, including a permission or
  notification event
- **THEN** the hook writes no decision to standard output, so the harness's
  normal approval and turn flow continues exactly as if no hook were installed

#### Scenario: Debug diagnostics are opt-in

- **WHEN** the hook debug environment variable is not set and the report fails
- **THEN** the hook produces no output on either stream and still exits 0

### Requirement: Stable, path-relative hook command declaration

AgentTower SHALL declare exactly one hook command string per harness —
`agenttower hook claude` for Claude Code and `agenttower hook codex` for
Codex CLI — and SHALL use that identical string for every subscribed event of
that harness. The lifecycle event SHALL be determined from the `hook_event_name`
field of the hook's stdin payload rather than from the command string. The
command SHALL be resolved from `PATH` and SHALL NOT contain any host-absolute
path.

#### Scenario: One command string across all declared events

- **WHEN** AgentTower installs hook declarations for a harness that subscribes to
  several lifecycle events
- **THEN** every declared handler carries byte-identical command text, so a
  harness that records trust against the hook definition keeps that trust across
  AgentTower upgrades and changes to the subscribed event set

#### Scenario: Event is taken from the payload

- **WHEN** the hook command receives a stdin payload whose `hook_event_name` is
  `Stop`
- **THEN** AgentTower treats the invocation as a Stop event without relying on
  any argument or path in the declared command

#### Scenario: No absolute path is written into harness config

- **WHEN** hook declarations are written to a harness configuration file
- **THEN** the recorded command contains only the `PATH`-resolvable `agenttower`
  token and its subcommand, and no host-specific absolute path

### Requirement: Subscribed harness events map onto the existing closed event set

AgentTower SHALL subscribe to `SessionStart`, `SessionEnd`, `UserPromptSubmit`,
`Stop`, `StopFailure`, and `Notification` (restricted to the
`permission_prompt`, `idle_prompt`, `agent_needs_input`, and `agent_completed`
notification types) for Claude Code, and to `SessionStart`, `SessionEnd`,
`UserPromptSubmit`, `Stop`, and `PermissionRequest` for Codex CLI. Reported
events SHALL map onto the existing closed routable `event_type` set and SHALL
NOT introduce any new `event_type` value: input-awaiting notifications and Codex
permission requests map to `waiting_for_input`; `Stop` and completion
notifications map to `completed`; `UserPromptSubmit` maps to `activity`;
`StopFailure` maps to `error`. `SessionStart` and `SessionEnd` SHALL NOT produce
a routable event. Each hook-originated event SHALL carry a `classifier_rule_id`
in the `hook.` namespace that matches the existing rule-id pattern.

#### Scenario: Permission prompt becomes waiting_for_input

- **WHEN** a Claude Code `Notification` event with notification type
  `permission_prompt` is reported for a registered pane
- **THEN** AgentTower records an event of type `waiting_for_input` with a
  `classifier_rule_id` in the `hook.` namespace

#### Scenario: Session boundaries produce no routable event

- **WHEN** a `SessionStart` or `SessionEnd` event is reported
- **THEN** AgentTower updates registration and tier state only, and no routable
  event is appended for routing to consume

#### Scenario: The routable event set is unchanged

- **WHEN** any subscribed harness event is reported
- **THEN** the resulting `event_type` is one of the existing closed set values
  and routing rules written against that set continue to match unchanged

### Requirement: Hook-originated excerpts are fixed templates

The `excerpt` of a hook-originated event SHALL be a fixed daemon-side template
selected by harness, hook event, and subtype. It SHALL NOT contain prompt text,
assistant text, tool input or output, transcript paths, or the working directory.
No hook payload content beyond the enumerated closed-set fields SHALL be written
to the event store or the append-only JSONL history.

#### Scenario: Prompt text never reaches the event store

- **WHEN** a `UserPromptSubmit` event is reported for a pane
- **THEN** the stored event's excerpt is the fixed template for that event and
  contains none of the submitted prompt text

#### Scenario: Transcript path is not persisted

- **WHEN** a hook payload includes a transcript path or working directory
- **THEN** neither value appears in the stored excerpt, and the working directory
  is retained only if it passes existing project-path validation and is stored in
  the existing project path field

### Requirement: Hook report method contract

AgentTower SHALL expose a socket method `events.report` in the dotted namespace,
accepting `container_id`, a six-tuple pane composite key, `harness`
(`claude` or `codex`), `hook_event_name` from the closed set for that harness,
`harness_session_id`, and `observed_at`, with optional `subtype`, working
directory, and `schema_version`. The method SHALL reject malformed input with
`bad_request`, `value_out_of_set`, `field_too_long`, or `schema_version_newer`,
and SHALL reject unknown parameter keys with `bad_request`. Conditions that are
not malformed input — a disabled ingest path, an unknown pane, a rate-limited
agent, or an agent forced to the tmux floor — SHALL NOT be errors.

#### Scenario: Unknown parameter key is rejected

- **WHEN** a report is submitted with a parameter key outside the defined set
- **THEN** the daemon responds with an error whose code is `bad_request` and no
  event or registration side effect occurs

#### Scenario: Out-of-set harness value is rejected

- **WHEN** a report names a `harness` value other than `claude` or `codex`
- **THEN** the daemon responds with an error whose code is `value_out_of_set`

#### Scenario: Non-malformed refusal is not an error

- **WHEN** a well-formed report arrives for a pane composite key that pane
  discovery has not yet observed
- **THEN** the daemon returns a successful response carrying an unaccepted
  verdict rather than an error envelope

### Requirement: Implicit registration on report

An accepted report SHALL ensure a registered agent exists for the reporting
pane. When no agent exists for the pane's composite key, AgentTower SHALL create
one with role `unknown`, capability set to the reporting harness, and an empty
label. When an agent already exists, AgentTower SHALL set its capability to the
reporting harness only if the stored capability is `unknown`, and SHALL NEVER
change its role or label. Hook reporting SHALL NEVER create or promote an agent
to the `master` role.

#### Scenario: First report registers the pane

- **WHEN** a hook reports for a pane that has no registered agent
- **THEN** an agent is created for that pane composite key with role `unknown`
  and capability equal to the reporting harness

#### Scenario: Operator-set capability is preserved

- **WHEN** a hook reports `codex` for an agent whose capability was previously
  set by an operator to something other than `unknown`
- **THEN** the stored capability is left unchanged

#### Scenario: Master is never created by a hook

- **WHEN** a hook reports for any pane
- **THEN** the resulting agent's role is never `master`, and an existing role is
  never modified

### Requirement: Report verdict semantics

A successful `events.report` response SHALL report whether the report was
accepted, a null reason when accepted and otherwise one of a closed set of
refusal reasons, the resolved agent identifier, the registration outcome
(created, reactivated, updated, or unchanged), the resulting event identifier or
null when no routable event was produced, and the agent's resulting inbound tier.

#### Scenario: Accepted report returns an event identifier

- **WHEN** a mapped, non-suppressed report is accepted
- **THEN** the response reports acceptance, a null reason, the agent identifier,
  the registration outcome, the new event identifier, and inbound tier 1

#### Scenario: Refusal carries a reason

- **WHEN** a report is refused because hook ingest is disabled, the agent is
  rate limited, the agent is forced to the tmux floor, or the pane is not found
- **THEN** the response reports non-acceptance with the corresponding reason and
  a null event identifier

### Requirement: Inbound tier lifecycle

AgentTower SHALL track a per-agent inbound tier of 0 or 1 together with the
reporting harness, the harness session identifier, and the time of the last hook
event. Inbound tier 1 SHALL be set on the first accepted report for a harness
session, and SHALL be reset to 0 on `SessionEnd`, on pane-reconciliation
deactivation, and when the agent's integration mode is set to the tmux-only
floor. There SHALL NOT be a freshness timeout: an idle Tier-1 session SHALL NOT
silently fall back to Tier 0.

#### Scenario: First report raises the tier

- **WHEN** the first report of a harness session is accepted for an agent at
  inbound tier 0
- **THEN** the agent's inbound tier becomes 1 and the reporting harness and
  session identifier are recorded

#### Scenario: SessionEnd clears the binding

- **WHEN** a `SessionEnd` event is reported for a Tier-1 agent
- **THEN** the harness session binding is cleared and the agent's inbound tier
  returns to 0

#### Scenario: Idle session does not downgrade

- **WHEN** a Tier-1 agent produces no hook event for an extended period while its
  session remains open
- **THEN** the agent remains at inbound tier 1

#### Scenario: Pane disappearance resets the tier

- **WHEN** pane reconciliation deactivates an agent whose pane no longer exists
- **THEN** that agent's inbound tier is reset to 0

### Requirement: Per-agent integration mode

Each agent SHALL carry an `integration` mode defaulting to `auto`. In this phase
the accepted values SHALL be `auto` and `tmux-only`; the values reserved by the
connection-tier ladder for later phases SHALL be rejected with
`value_out_of_set`. An agent set to `tmux-only` SHALL refuse hook reports and
remain at inbound tier 0. Operators SHALL be able to set the mode and to read
both the mode and the inbound tier from the agent listing.

#### Scenario: tmux-only forces the floor

- **WHEN** an agent's integration mode is `tmux-only` and a hook report arrives
  for its pane
- **THEN** the report is not accepted, the refusal reason identifies the
  tmux-only mode, and the agent stays at inbound tier 0

#### Scenario: Later-phase modes are rejected

- **WHEN** an operator attempts to set an integration mode reserved for a later
  connection tier
- **THEN** the request is rejected with `value_out_of_set`

#### Scenario: Tier and mode are visible to operators

- **WHEN** an operator lists agents
- **THEN** each agent's inbound tier and integration mode are shown

### Requirement: Scoped classifier suppression

While an agent is at inbound tier 1, the log-reader classifier SHALL suppress
only its `waiting_for_input` and `completed` classifications. All other event
types — including `activity`, `error`, `test_failed`, `test_passed`,
`manual_review_needed`, `long_running`, `pane_exited`, and
`swarm_member_reported` — SHALL continue to be produced from the log path.
Suppressed classifications SHALL be counted for observability and SHALL NOT be
stored as events.

#### Scenario: Duplicate completion is suppressed

- **WHEN** the classifier matches a `completed` pattern in the log of an agent at
  inbound tier 1
- **THEN** no classifier-generated `completed` event is stored, and the
  suppression is counted

#### Scenario: Other event types still flow

- **WHEN** the classifier matches an `error` or `test_failed` pattern for an
  agent at inbound tier 1
- **THEN** the event is stored normally

#### Scenario: Suppression ends with the tier

- **WHEN** an agent falls back to inbound tier 0
- **THEN** classifier-generated `waiting_for_input` and `completed` events resume
  for that agent

### Requirement: Ingest governance controls

AgentTower SHALL provide a daemon configuration switch that disables hook ingest
entirely, a switch that disables classifier suppression independently, and a
per-agent rate limit on accepted reports. When ingest is disabled, well-formed
reports SHALL be refused with the disabled reason and SHALL NOT raise the inbound
tier. When an agent exceeds its rate limit, further reports SHALL be refused with
the rate-limited reason rather than an error, and the hook SHALL still exit 0.

#### Scenario: Kill switch disables ingest

- **WHEN** hook ingest is disabled in daemon configuration and a well-formed
  report arrives
- **THEN** the report is refused with the disabled reason, no event is stored,
  and the agent's inbound tier is unchanged

#### Scenario: Rate limit sheds a hook storm

- **WHEN** a single agent submits reports faster than the configured per-agent
  rate limit
- **THEN** excess reports are refused with the rate-limited reason and the hook
  command still exits 0

### Requirement: Hook installation is marked, safe, and idempotent

AgentTower SHALL provide an install operation, per harness, that writes its hook
declarations into the user-scope harness configuration file. Installation SHALL
treat the `agenttower hook ` command prefix as the sole ownership marker, SHALL
NOT add, remove, reorder, or rewrite any other key or handler in the file, SHALL
write a timestamped backup beside the file before modifying it, SHALL write
atomically via a temporary file and rename, and SHALL re-read and verify the
result. Installing twice SHALL leave the file unchanged after the first install.
Installation SHALL refuse with an actionable error when the existing Claude
configuration file is not strict JSON or is not a JSON object. For Codex, installation SHALL create `~/.codex/hooks.json` when it is absent
and merge into it under the same marker rule when it is present. Installation
SHALL NOT modify the Codex TOML configuration file.

#### Scenario: Second install is a no-op

- **WHEN** install is run for a harness whose AgentTower hooks are already
  present and current
- **THEN** the configuration file content is unchanged and the operation reports
  success

#### Scenario: Unrelated configuration is preserved

- **WHEN** install runs against a configuration file containing unrelated keys
  and unrelated hook handlers
- **THEN** those keys and handlers are byte-preserved and only AgentTower-marked
  handlers are added

#### Scenario: Malformed configuration is refused

- **WHEN** the target Claude configuration file is not strict JSON or its
  top-level value is not an object
- **THEN** install refuses with an actionable error naming the file and makes no
  modification

#### Scenario: Existing Codex hooks file is merged, not replaced

- **WHEN** install runs for Codex and `~/.codex/hooks.json` already exists with
  third-party handlers
- **THEN** the AgentTower handlers are merged into that file under the marker
  rule, every existing handler is preserved, and the Codex TOML configuration
  file is untouched

#### Scenario: Backup precedes modification

- **WHEN** install modifies an existing configuration file
- **THEN** a timestamped backup of the prior content exists beside the file
  before the new content is committed

### Requirement: Hook uninstallation removes exactly what was installed

An uninstall operation SHALL remove exactly the handlers whose command carries
the AgentTower ownership marker, SHALL remove any matcher group left empty by
that removal, and SHALL leave every other key, handler, and matcher group
untouched. Uninstall SHALL be safe to run when no AgentTower hooks are present.

#### Scenario: Only marked handlers are removed

- **WHEN** uninstall runs on a configuration file containing both AgentTower
  handlers and third-party handlers under the same event
- **THEN** only the AgentTower handlers are removed and the third-party handlers
  remain

#### Scenario: Empty groups are cleaned up

- **WHEN** removing AgentTower handlers leaves a matcher group with no handlers
- **THEN** that empty matcher group is removed as well

#### Scenario: Uninstall without an install is harmless

- **WHEN** uninstall runs where no AgentTower handlers exist
- **THEN** the file is unchanged and the operation reports success

### Requirement: Codex trust is disclosed, not assumed

After installing Codex hooks, AgentTower SHALL tell the operator that Codex
requires the hook definitions to be reviewed and trusted from inside Codex before
they run, and that changing a hook definition requires re-trusting it. AgentTower
SHALL NOT claim that Codex hooks are active on the basis of file content alone,
and SHALL report Codex trust state as unknown wherever trust state is surfaced.

#### Scenario: Install output states the trust step

- **WHEN** Codex hook installation completes
- **THEN** the output states that the operator must review and trust the
  AgentTower hooks inside Codex, and that a changed definition must be re-trusted

#### Scenario: Trust state is reported as unknown

- **WHEN** hook status is reported for Codex
- **THEN** the trust state is reported as unknown rather than as trusted

### Requirement: Hook status reporting

A status operation SHALL report, per harness, whether AgentTower hooks are
installed, which lifecycle events are declared, the declared command string, and
the configuration file location expressed relative to the user's home directory.
When the daemon is reachable it SHALL additionally report accepted, rejected, and
rate-limited report counts, the number of agents at inbound tier 1, and the time
of the most recent accepted report. Status SHALL succeed and report the local
file facts even when the daemon is unreachable. A machine-readable output form
SHALL be available.

#### Scenario: Status works without a daemon

- **WHEN** status is run while the daemon is unreachable
- **THEN** the installed state, declared events, command string, and config file
  location are reported and the daemon-derived counters are reported as
  unavailable

#### Scenario: Status warns about an unresolvable command

- **WHEN** the `agenttower` command does not resolve on `PATH` in the current
  environment
- **THEN** status and install both warn that the declared hook command will not
  resolve when the harness runs it

### Requirement: App contract additive minor for hook state

The host-only app contract SHALL be raised by one additive minor version. It
SHALL append a `hooks_ingest` readiness subsystem to the ordered subsystem list,
reporting `ok` when ingest is enabled and healthy, `degraded` when ingest is
disabled by configuration, and `unavailable` on
persistent write failure, each with a reason and a hint. Agent reads SHALL
include the agent's inbound tier and integration mode, and the dashboard read
SHALL include accepted, rejected, and Tier-1-agent counts. These fields SHALL be
always-emitted additive read-side fields and SHALL NOT be gated behind a
capability flag.

#### Scenario: New subsystem appears in readiness

- **WHEN** an app client reads readiness from the daemon
- **THEN** a `hooks_ingest` subsystem is present at the end of the ordered
  subsystem list with a status, a reason, and a hint

#### Scenario: Disabled ingest reports degraded

- **WHEN** hook ingest is disabled by configuration
- **THEN** the `hooks_ingest` subsystem reports `degraded` with a reason that
  identifies the configuration switch

#### Scenario: Agent reads carry tier state

- **WHEN** an app client reads an agent
- **THEN** the agent's inbound tier and integration mode are present without any
  capability flag having to be negotiated

### Requirement: Transport and privilege invariants are unchanged

Hook reporting SHALL reach the daemon only over the existing mounted Unix socket
using the existing newline-delimited JSON request/response wire, and SHALL NOT
introduce any network listener. The peer-credential check that refuses peers
whose user id differs from the daemon's SHALL remain unchanged, and the
host-only restriction on `app.*` methods SHALL remain unchanged while
`events.report` accepts bench-container callers like other non-`app.*` methods.

#### Scenario: No listener is opened

- **WHEN** hook ingest is enabled and hooks are reporting
- **THEN** the daemon opens no network listener and all reports arrive on the
  existing Unix socket

#### Scenario: Foreign uid is still refused

- **WHEN** a peer whose user id differs from the daemon's calls `events.report`
- **THEN** the connection is refused exactly as for any other method

#### Scenario: Container callers are accepted

- **WHEN** a thin client inside a bench container calls `events.report`
- **THEN** the call is dispatched normally and is not refused as host-only

### Requirement: Hook reports are audited

Every accepted hook report that produces a routable event SHALL append that event
to the append-only JSONL history in the same shape as a classifier-produced
event, distinguished by its `hook.` namespaced rule identifier. Registration side
effects caused by a report SHALL be audited exactly as operator-initiated
registration is audited today.

#### Scenario: Hook event is written to the audit history

- **WHEN** a hook report is accepted and mapped to a routable event
- **THEN** a corresponding record is appended to the JSONL history with a `hook.`
  namespaced rule identifier

#### Scenario: Implicit registration is audited

- **WHEN** a hook report implicitly creates or reactivates an agent
- **THEN** a registration audit record is written using the existing registration
  audit shape
