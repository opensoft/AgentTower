# AgentTower MVP Feature Sequence

Status: Draft v0.1
Date: 2026-05-05

This is the first ordered feature queue for AgentTower MVP implementation. Each
item is intended to be run through spec-kit as a separate feature spec. The
ordering is deliberate: prove host control and container discovery first, then
registration, observation, eventing, and finally prompt routing.

## Build Principles

- The Tower deploys first as a host daemon, not an in-container daemon.
- Bench containers use a thin `agenttower` client over the mounted host Unix
  socket.
- MVP only targets running bench containers and tmux panes inside them.
- Every feature should leave the CLI usable and testable.
- Avoid routing input until discovery, registration, logs, and permissions are
  working.
- Keep each feature narrow enough that one master can drive it through spec-kit
  without needing later features to exist.

## FEAT-001: Package, Config, and State Foundation

Goal: create the Python package skeleton and durable local state layout.

Build:

- Python package named `agenttower`.
- Console script stubs for `agenttower` and `agenttowerd`.
- Opensoft config, state, log, socket, and cache path resolution.
- Default config creation at `~/.config/opensoft/agenttower/config.toml`.
- SQLite database creation with a schema version table.
- JSONL event writer utility.
- Basic CLI commands for `--version`, `config paths`, and `config init`.

Acceptance:

- `agenttower --version` works from the repo/dev install.
- `agenttower config init` creates the expected host directories.
- SQLite opens cleanly and stores the current schema version.
- Re-running initialization is idempotent.

Out of scope:

- Daemon process management.
- Docker or tmux discovery.
- Any input routing.

## FEAT-002: Host Daemon Lifecycle and Unix Socket API

Goal: run `agenttowerd` as the host source of truth and expose a local control
API.

Build:

- `agenttowerd` long-running process.
- `agenttower ensure-daemon`.
- Lock file and pid file management.
- Stale pid recovery.
- Unix socket listener at the configured state path.
- Newline-delimited JSON request/response protocol.
- API methods for `ping`, `status`, and `shutdown` for development.
- Socket permission checks limited to the host user.

Acceptance:

- `agenttower ensure-daemon` starts exactly one daemon.
- Re-running `agenttower ensure-daemon` exits successfully without duplication.
- `agenttower status` can call the daemon over the socket.
- Killing the daemon allows the next `ensure-daemon` to recover cleanly.

Out of scope:

- Container socket mounting.
- Discovery workers.
- Background event loops beyond daemon health.

## FEAT-003: Bench Container Discovery

Goal: discover in-scope Docker containers from the host.

Build:

- Docker adapter for `docker ps` and `docker inspect`.
- Configurable bench-name matching with default `name_contains = ["bench"]`.
- Container records in SQLite.
- Active/inactive status tracking.
- `agenttower scan --containers`.
- `agenttower list-containers`.
- Graceful degraded state when Docker is unavailable.

Acceptance:

- Running bench containers appear in `agenttower list-containers`.
- Non-bench containers are ignored by default.
- Container records include id, name, image, status, labels, mounts, and last
  scanned timestamp.
- Docker failures produce actionable CLI output and do not crash the daemon.

Out of scope:

- tmux discovery inside containers.
- Opening new container shells.
- Host-only tmux discovery.

## FEAT-004: Container tmux Pane Discovery

Goal: discover tmux panes inside each running bench container.

Build:

- Host daemon scans tmux with `docker exec -u "$USER"`.
- Default tmux server discovery.
- Multiple tmux socket discovery under `/tmp/tmux-$(id -u)/`.
- Pane records in SQLite.
- Container, tmux server, session, window, pane, pid, tty, command, cwd, and
  title fields.
- `agenttower scan --panes`.
- `agenttower list-panes`.
- Degraded scan status when tmux is unavailable inside a container.

Acceptance:

- Panes inside bench containers appear in `agenttower list-panes`.
- Pane identity includes container id, container user, tmux socket, session,
  window index, pane index, and pane id.
- Restarted or missing containers mark panes inactive instead of deleting
  history.
- tmux failures are visible in scan output.

Out of scope:

- Agent roles or registration.
- Log attachment.
- Sending input.

## FEAT-005: Container-Local Thin Client Connectivity

Goal: make the `agenttower` CLI usable from inside a bench container.

Build:

- Define the MVP socket mount contract.
- Support `AGENTTOWER_SOCKET` override.
- Client connection fallback to the default mounted socket path.
- Container identity detection from cgroup, hostname, environment, or Docker
  metadata available through the daemon.
- Current tmux pane detection from `$TMUX` and `$TMUX_PANE`.
- `agenttower config doctor` focused on socket reachability and tmux identity.

Acceptance:

- Running `agenttower status` inside a bench container reaches the host daemon.
- `agenttower config doctor` reports missing socket, missing tmux, or unknown
  container clearly.
- The same CLI still works from the host.

Out of scope:

- In-container daemon or relay.
- Registering agents.
- Log bind mount validation beyond doctor output.

## FEAT-006: Agent Registration and Role Metadata

Goal: let humans and agents turn discovered panes into registered AgentTower
agents.

Build:

- `agenttower register-self`.
- `agenttower list-agents`.
- `agenttower set-role`.
- `agenttower set-label`.
- `agenttower set-capability`.
- Roles: `master`, `slave`, `swarm`, `test-runner`, `shell`, `unknown`.
- Capabilities: `claude`, `codex`, `gemini`, `opencode`, `shell`,
  `test-runner`, `unknown`.
- Parent agent field for swarm registration.
- Human-controlled promotion to `master`.
- Effective permission derivation from role.

Acceptance:

- An agent inside tmux can register itself with role, label, capability, and
  project path.
- `list-agents` shows registered agents with container and pane identity.
- Unknown panes cannot silently become masters.
- A swarm can register with `--parent <agent-id>`.

Out of scope:

- Automatic swarm inference.
- Log attachment.
- Prompt delivery.

## FEAT-007: Pane Log Attachment and Offset Tracking

Goal: attach durable tmux logs to registered panes and track read offsets.

Build:

- `agenttower attach-log`.
- Optional `register-self --attach-log`.
- Host-visible log path generation:
  `~/.local/state/opensoft/agenttower/logs/<container>/<agent-id>.log`.
- `tmux pipe-pane -o` attachment through `docker exec`.
- Log attachment status in SQLite.
- Log offset table.
- Basic redaction utility for common secret patterns.
- Clear failure when log path is not host-visible.

Acceptance:

- A registered agent can attach a tmux pipe-pane log.
- Re-attaching a log is idempotent.
- Log offsets survive daemon restart.
- Event excerpts use redacted output.

Out of scope:

- Event classification.
- Routing events.
- In-container relay.

## FEAT-008: Event Ingestion, Classification, and Follow CLI

**Status: implemented.** See
`specs/008-event-ingestion-follow/plan.md` for the implementation
record. Acceptance items below are tested by integration tests under
`tests/integration/test_events_us{1..6}*.py` plus
`test_lifecycle_separation.py`. Carry-over obligations from FEAT-007
(T175 truncation, T176 recreation, T177 round-trip) land in
`test_events_us4_carryover.py`.

Goal: convert pane logs into durable, inspectable AgentTower events.

Build:

- Background log readers in the host daemon.
- Offset-based incremental reads.
- Rule-based classifier for initial event types:
  `activity`, `waiting_for_input`, `completed`, `error`, `test_failed`,
  `test_passed`, `manual_review_needed`, `long_running`, `pane_exited`, and
  `swarm_member_reported`.
- Event debounce.
- SQLite event rows.
- Append-only JSONL event history.
- `agenttower events`.
- `agenttower events --follow`.

Acceptance:

- New log output creates durable events.
- Re-reading after daemon restart does not duplicate old events.
- `events --follow` streams new events.
- Classifier rules are visible and conservative.
- File truncation is detected within one reader cycle (≤ 1 s wall-clock at
  MVP scale) and offsets reset to `(0, 0)` without replaying the prior
  file's content (FEAT-007 SC-007 — FEAT-007 shipped the reset signal;
  FEAT-008 ships the timing + no-replay invariant).
- File recreation (changed inode) is detected within one reader cycle and
  offsets reset; same no-replay invariant.
- File-deleted → file-recreated → operator-explicit `attach-log` round-trip:
  reader transitions row to `stale` and emits `log_file_missing`; on
  reappearance emits `log_file_returned` once per
  `(agent_id, log_path, file_inode)` triple; row remains `stale` until the
  operator re-attaches; re-attach resets offsets per FEAT-007 FR-021's
  file-consistency check (FEAT-007 US6 AS3..AS5 — carried over from
  FEAT-007 T177).

Carried over from FEAT-007:

These items are part of FEAT-007's spec but require FEAT-008's reader to
exercise. FEAT-007 shipped the helpers + unit-level coverage; FEAT-008
must consume them and ship the integration / timing assertions.

- **Reader-cycle entry point obligation.** FEAT-008's reader MUST call
  `agenttower.logs.reader_recovery.reader_cycle_offset_recovery(...)`
  once per attached row per cycle. The helper owns the
  `unchanged | truncated | recreated | missing | reappeared` dispatch,
  the `BEGIN IMMEDIATE` flip from `active → stale`, the
  `log_attachment_change` audit row append, and the FR-061-suppressed
  emission of `log_rotation_detected` / `log_file_missing` /
  `log_file_returned`. FEAT-008 reader code MUST NOT touch
  `log_attachments` or `log_offsets` directly.
- **File-change classifier.** Use
  `agenttower.state.log_offsets.detect_file_change(host_path,
  stored_inode, stored_size_seen) -> FileChangeKind` as the canonical
  classifier (Pure function, no side effects).
- **Sole production-side offset advancer.** FEAT-008's reader is the only
  production caller that may write to `log_offsets.byte_offset` /
  `line_offset` / `last_event_offset`. The test seam
  `state.log_offsets.advance_offset_for_test` MUST NOT be imported by
  any production module — enforced by AST gate
  `tests/unit/test_logs_offset_advance_invariant.py` (T080).
- **Detection-timing tests carried from FEAT-007.** T175 (truncation
  ≤ 1 s) and T176 (recreation ≤ 1 s) integration tests — FEAT-007 left
  them un-ticked because the reader cycle does not exist yet. Land them
  in FEAT-008 as integration tests against the real reader loop.
- **AS3..AS5 round-trip carried from FEAT-007.** T177 — same reason.
- **Lifecycle event surface assertion (FEAT-007 T173, optional).** Single
  consolidated test that every event from `data-model.md §3`
  (`log_rotation_detected`, `log_file_missing`, `log_file_returned`,
  `log_attachment_orphan_detected`, `mounts_json_oversized`,
  `socket_peer_uid_mismatch`) routes through the daemon's lifecycle
  logger and never appears in `events.jsonl`. Each event class is
  individually proven by its own dedicated test today; FEAT-008 may
  consolidate these assertions when adding its own event surface.

Out of scope:

- LLM-assisted classification.
- Prompt routing from events.
- Desktop notifications.

## FEAT-009: Safe Prompt Queue and Input Delivery

Goal: safely deliver structured prompts from masters to eligible targets.

Build:

- Structured AgentTower prompt envelope.
- `agenttower send-input --target <agent-id> --message <text>`.
- Message queue table.
- Queue states: queued, delivered, blocked, canceled, failed.
- `agenttower queue`.
- `agenttower queue approve <message-id>`.
- `agenttower queue delay <message-id>`.
- `agenttower queue cancel <message-id>`.
- Permission checks:
  `master` can send to `slave` and `swarm`; `unknown` cannot receive input.
- Global routing kill switch.
- Safe tmux paste-buffer delivery without shell interpolation of raw messages.

Acceptance:

- A master can queue and deliver a prompt to a slave.
- Unknown panes reject input.
- Delivery is auditable in JSONL.
- Canceled messages are not delivered.
- Raw prompt text cannot escape into shell command construction.

Out of scope:

- Event-to-route subscriptions.
- Multi-master arbitration.
- Idle detection beyond conservative queueing.

## FEAT-010: Routes, Swarm Tracking, and Multi-Master Arbitration

Goal: support the MVP autonomous workflow where masters route work to slaves,
slaves report swarms, and multiple masters can share a slave without silent
collisions.

Build:

- `agenttower route --from <agent-id> --to <agent-id>`.
- Event notification envelopes from daemon to masters.
- Route subscriptions for selected event types.
- Per-target FIFO delivery.
- Arbitration request records.
- Arbitration prompt shown to a requesting master when another master has a
  pending or recently delivered prompt for the same slave.
- Arbitration decisions: queue-next, delay, cancel.
- Swarm member report parsing for:
  `AGENTTOWER_SWARM_MEMBER parent=<agent-id> pane=<tmux-pane-id> ...`.
- Swarm parent/child display in `list-agents`.

Acceptance:

- A slave event can notify one or more routed masters.
- Two masters can target the same slave; the second master sees the first
  prompt excerpt before its prompt is delivered.
- Human can inspect and override queued arbitration state.
- Swarm children are shown clearly under their parent slave.

Out of scope:

- Automatic semantic task assignment.
- Automatic answers to agent questions.
- TUI.
- Antigravity support.

## Later Features

These are intentionally after the first 10:

- Open a new tmux pane or window attached to a selected container.
- Inferred swarm parentage.
- Shell helper integration for yodex, yolo, cta, and related tools.
- TUI.
- Host-only tmux discovery.
- Optional in-container relay.
- Antigravity tmux backend.
