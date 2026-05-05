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
