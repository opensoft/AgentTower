# AgentTower Architecture

Author/Vendor: Opensoft
Product: AgentTower
Primary CLI: `agenttower`
Daemon: `agenttowerd`
Status: Draft architecture v0.1
Date: 2026-05-04

## 1. Purpose

AgentTower is a local control plane for autonomous and semi-autonomous terminal
agents running inside Opensoft devBench containers. It discovers containerized
tmux panes, records agent metadata, attaches durable logs, classifies terminal
events, and routes structured prompts between master and slave agents.

The MVP is container-first. Host-only tmux panes may be discovered later, but
the first useful system is designed around the way Opensoft works today:
development happens inside named bench containers, with Claude CLI, Codex CLI,
Gemini CLI, OpenCode, shell panes, test runners, and spawned swarms running in
tmux inside those containers.

AgentTower does not understand project-specific workflows such as spec-kit. A
master agent understands the workflow and uses AgentTower as the registry,
router, event stream, and safe input layer.

## 2. MVP Decisions

- MVP scans only running containers whose names identify them as bench
  containers.
- MVP discovers tmux panes inside those containers for the configured bench
  user.
- The host runs the required `agenttowerd` daemon and owns the durable state.
- Container-local `agenttower` commands are thin clients that talk to the host
  daemon over a mounted Unix socket.
- Agents register themselves from inside their tmux panes with
  `agenttower register-self`.
- Pane output is monitored with `tmux pipe-pane` and host-visible log paths
  whenever possible.
- The human assigns panes as `master` or `slave`.
- A pane marked `master` is trusted to send prompts to `slave` panes.
- Multiple masters may address the same slave; AgentTower serializes delivery
  per target pane and performs cooperative arbitration.
- Swarms spawned by a slave are first-class panes and are shown as children of
  that slave.
- AgentTower tracks capabilities such as `claude`, `codex`, `gemini`,
  `opencode`, `shell`, and `test-runner`.
- MVP UI is CLI-only.
- Antigravity is out of scope for MVP. When added, only tmux-backed
  Antigravity agents are in scope.
- Python-thread agent backends and mailbox monitoring are out of scope for MVP.

### 2.1 Terminology

The PRD uses `orchestrator` and `worker`. The MVP architecture uses `master`
and `slave` because the human explicitly chooses panes in those terms:

- `master` maps to an orchestrator pane that can direct other agents.
- `slave` maps to an available worker pane.
- `swarm` maps to a child worker spawned by a slave.

Implementation can expose aliases later, but the architecture treats these as
the MVP role names.

## 3. Non-Goals

MVP does not:

- run model inference
- replace tmux, Docker, Claude CLI, Codex CLI, Gemini CLI, or OpenCode
- implement a web UI or TUI
- inspect Python threads inside agent tools
- monitor Antigravity mailbox files
- guarantee semantic understanding of arbitrary terminal output
- enforce exclusive ownership of slaves by one master
- execute project workflows directly

## 4. Deployment Model

AgentTower uses a host daemon with container-local clients.

```text
bench container(s)                         host
------------------                         ----
tmux panes
  master/slave agents
  agenttower CLI  -----------------------> agenttowerd Unix socket
  pipe-pane logs  -----------------------> host-visible log directory

                                           SQLite registry
                                           JSONL event history
                                           notification queues
                                           docker exec control path
```

The host daemon is the source of truth. It keeps all durable state in the
Opensoft namespace:

```text
~/.config/opensoft/agenttower/config.toml
~/.local/state/opensoft/agenttower/agenttower.sqlite3
~/.local/state/opensoft/agenttower/events.jsonl
~/.local/state/opensoft/agenttower/logs/
~/.local/state/opensoft/agenttower/agenttowerd.sock
~/.cache/opensoft/agenttower/
```

Bench containers mount the daemon socket and, preferably, the state log
directory. No network listener is required for MVP.

## 5. Components

### 5.1 Host Daemon

`agenttowerd` is a long-running Python process on the host. It owns:

- container discovery
- tmux discovery through `docker exec`
- pane registration
- log attachment and offset tracking
- event classification
- JSONL event writing
- SQLite state
- notification queues
- safe input delivery
- cooperative multi-master arbitration

The daemon starts idempotently with `agenttower ensure-daemon` and uses a lock
file and pid file:

```text
~/.local/state/opensoft/agenttower/agenttowerd.lock
~/.local/state/opensoft/agenttower/agenttowerd.pid
```

### 5.2 Container CLI

The `agenttower` command inside a bench container is a thin client. It discovers
the current tmux pane from `$TMUX` and `$TMUX_PANE`, discovers the current
container identity, and sends requests to the host daemon over the mounted Unix
socket.

The CLI is used by humans, wrapper scripts, masters, and agents.

Important commands:

```bash
agenttower ensure-daemon
agenttower register-self --role master --capability claude --label claude-main
agenttower register-self --role slave --capability codex --label codex-01
agenttower list-agents
agenttower list-panes
agenttower list-containers
agenttower events --follow
agenttower send-input --target <agent-id> --message <text>
agenttower route --from <agent-id> --to <agent-id>
agenttower attach-log --target <agent-id>
agenttower set-role --target <agent-id> --role master
agenttower set-capability --target <agent-id> --capability gemini
```

### 5.3 Optional Container Relay

MVP should not require an in-container daemon. If mounted socket access,
host-visible logs, or `docker exec` control is insufficient in a specific
devBench, the architecture allows a later `agenttower-relay`.

The relay would tail local logs or query local tmux and forward events to the
host daemon. It would not own durable state.

## 6. Container Discovery

MVP only scans configured bench containers. A container is in scope when its
name matches the configured bench-name rule. The default rule is a
case-insensitive substring match for `bench`.

Example config:

```toml
[containers]
name_contains = ["bench"]
scan_interval_seconds = 5
```

Discovery uses Docker from the host:

```bash
docker ps --format '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'
docker inspect <container>
```

The daemon stores:

- container id
- container name
- image
- status
- labels
- mounts
- workspace paths
- detected bench user
- last scan timestamp

Stopped containers are useful for history but are not active control targets.

## 7. Container Tmux Discovery

The daemon scans tmux inside each running bench container with `docker exec`.
Bench containers are expected to define the host user as the active user, so MVP
only scans that user.

Command shape:

```bash
docker exec -u "$USER" <container> sh -lc \
  'tmux list-panes -a -F "#{session_name}:#{window_index}.#{pane_index}\t#{pane_id}\t#{pane_pid}\t#{pane_tty}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_title}"'
```

If a container has multiple tmux sockets for the bench user, the daemon scans
the sockets under:

```text
/tmp/tmux-$(id -u)/
```

Pane identity includes:

- container id
- container name
- container user
- tmux socket path
- tmux session name
- window index
- pane index
- tmux pane id
- pane pid

The registry must treat tmux pane ids as live identifiers, not permanent
historical ids. A restarted container or tmux server may reuse pane ids.

## 8. Agent Registration

Registration is preferred over passive discovery. Passive discovery finds panes;
registration tells AgentTower what those panes are allowed to do.

Agents register from inside their tmux pane:

```bash
agenttower register-self \
  --role slave \
  --capability codex \
  --label codex-01 \
  --project /workspace/acme \
  --attach-log
```

`register-self` collects:

- current container identity
- current user
- `$TMUX`
- `$TMUX_PANE`
- current working directory
- current command
- optional role
- optional capability
- optional label
- optional project path

Registration creates or updates an agent record. If `--attach-log` is present,
the daemon attaches `tmux pipe-pane` for that pane.

## 9. Roles

MVP roles:

- `master`: trusted orchestration pane that can prompt slaves
- `slave`: agent pane available for delegated work
- `swarm`: child agent spawned under a slave
- `test-runner`: pane running tests, validation, benchmarks, or checks
- `shell`: ordinary interactive shell
- `unknown`: discovered but not registered

The human decides which panes are masters and slaves. AgentTower may suggest a
role from process names, but it must not silently grant master privileges.

## 10. Capabilities

Capabilities describe what an agent can do. They are independent from role.

Initial capabilities:

- `claude`
- `codex`
- `gemini`
- `opencode`
- `shell`
- `test-runner`
- `unknown`

Examples:

- `role=master`, `capability=claude`
- `role=slave`, `capability=codex`
- `role=slave`, `capability=gemini`
- `role=test-runner`, `capability=test-runner`

Masters use the capability registry to select the right agent for a task.
AgentTower does not decide whether Codex, Claude, Gemini, or OpenCode is best
for a project step.

## 11. Swarm Parentage

When a slave starts a swarm, the prompt should require explicit reporting.
AgentTower supports this as a first-class contract.

Master-to-slave swarm prompt pattern:

```text
[AgentTower]
From: master claude-main
To: slave codex-01
Intent: start-swarm

Start a swarm for the assigned task. After creating each worker, immediately
register it with AgentTower or report its tmux pane id, label, capability, and
purpose. Use this format:

AGENTTOWER_SWARM_MEMBER parent=<your-agent-id> pane=<tmux-pane-id>
label=<label> capability=<capability> purpose=<short-purpose>
```

Preferred child registration:

```bash
agenttower register-self \
  --role swarm \
  --parent <parent-agent-id> \
  --capability claude \
  --label claude-swarm-01 \
  --attach-log
```

Fallback inference is allowed when explicit reporting is missing. The daemon can
infer likely swarm children from:

- same container
- same tmux session or adjacent window
- recent creation time
- current command matching a known agent CLI
- active task assignment on the parent slave

Inferred parentage must be marked as inferred and may be corrected by CLI.

## 12. Logging

AgentTower uses tmux logs as the primary observation surface.

Preferred log path:

```text
~/.local/state/opensoft/agenttower/logs/<container>/<agent-id>.log
```

When logs are attached inside a container, the log directory should be
host-visible through a bind mount. The daemon attaches logs using `docker exec`
and `tmux pipe-pane`:

```bash
docker exec -u "$USER" <container> sh -lc \
  'tmux pipe-pane -o -t <pane> "cat >> <log_file>"'
```

The daemon tracks:

- pipe-pane active status
- log path
- last read offset
- last event offset
- last output timestamp

Terminal output can include secrets. Event excerpts should be compact and pass
through redaction before being written to JSONL or routed.

## 13. Event Pipeline

The event pipeline is:

```text
pipe-pane log
    -> offset reader
    -> redactor
    -> classifier
    -> debounce
    -> SQLite event row
    -> JSONL event append
    -> routing queue
```

Initial event types:

- `activity`
- `waiting_for_input`
- `completed`
- `error`
- `test_failed`
- `test_passed`
- `manual_review_needed`
- `long_running`
- `pane_exited`
- `swarm_member_reported`

Classification is rule-based for MVP. It should be conservative and
transparent. The daemon may emit uncertain events, but it must not turn
uncertain classification into automatic command execution.

## 14. Routing Model

AgentTower routes structured messages between agents. The main MVP routing path
is master-to-slave input and slave-to-master event notification.

Rules:

- Masters can send input to slaves by default.
- Masters can send input to swarm children through the parent relationship.
- Unknown panes cannot receive input.
- Slaves do not automatically get permission to prompt masters or other slaves.
- Notifications are queued if the target is busy or if arbitration is pending.
- Every routed message is recorded in JSONL.

## 15. Structured Prompt Envelope

MVP uses a structured plain-text envelope so terminal agents can read it without
special tooling.

```text
[AgentTower]
Message-Id: <uuid>
From: <source-agent-id> (<source-label>, <source-role>, <source-capability>)
To: <target-agent-id> (<target-label>, <target-role>, <target-capability>)
Type: prompt
Priority: normal
Requires-Reply: yes

<message body>
```

Event notifications use the same envelope:

```text
[AgentTower]
Message-Id: <uuid>
From: agenttowerd
To: <master-agent-id>
Type: event
Event-Type: waiting_for_input
Source-Agent: <slave-agent-id> (<label>)

Summary:
<short summary>

Latest Output:
<redacted excerpt>
```

The envelope is intentionally text-first. It can later gain a JSON attachment or
machine-readable footer, but MVP should remain readable in normal terminals.

## 16. Input Delivery

The daemon delivers input with tmux paste buffers instead of keystroke-by-
keystroke typing:

```bash
docker exec -u "$USER" <container> sh -lc \
  'tmux set-buffer -- <message> && tmux paste-buffer -t <pane> && tmux send-keys -t <pane> Enter'
```

The implementation must avoid shell injection by passing payloads through safe
subprocess arguments or temporary files rather than interpolating raw message
text into shell strings.

Before delivery, the daemon checks:

- target pane is active
- target role can receive input
- source role can send input
- global routing is enabled
- target is not marked blocked
- target queue order permits delivery

Idle detection is conservative in MVP. If the daemon is not confident the pane
is ready, it queues the message.

## 17. Multi-Master Arbitration

Multiple masters may address the same slave. AgentTower serializes messages per
target pane, but it does not enforce exclusive ownership.

If Master A has a pending or recently delivered prompt for a slave and Master B
tries to queue a new prompt for that same slave, the daemon sends Master A's
prompt excerpt to Master B before delivering Master B's prompt. Master B then
decides whether its prompt should still be queued next.

```text
[AgentTower]
Type: arbitration
Target-Slave: codex-01
Existing-Prompt-From: claude-main
Requesting-Master: gemini-main

Another master recently prompted codex-01:

<existing prompt excerpt>

You are trying to queue this prompt next:

<requesting prompt excerpt>

Reply with one:
- queue-next
- delay
- cancel
```

Default behavior:

- messages are FIFO per target pane
- the requesting master is shown the other master's prompt before its prompt is
  delivered
- the requesting master can queue next, delay, or cancel
- if no answer arrives before the configured timeout, the requesting prompt
  remains queued and visible in `agenttower queue`
- the human can override from CLI

This keeps shared slaves possible while avoiding silent prompt collisions.

## 18. State Model

SQLite stores durable state. JSONL stores append-only audit history.

Core tables:

- `containers`
- `tmux_servers`
- `panes`
- `agents`
- `agent_capabilities`
- `routes`
- `events`
- `log_offsets`
- `message_queue`
- `permissions`
- `arbitration_requests`
- `daemon_state`

Important agent fields:

- `agent_id`
- `label`
- `role`
- `capability`
- `container_id`
- `container_name`
- `container_user`
- `tmux_socket`
- `session_name`
- `window_index`
- `pane_index`
- `pane_id`
- `pid`
- `cwd`
- `project_path`
- `parent_agent_id`
- `parentage_source`
- `log_path`
- `send_input_allowed`
- `registered_at`
- `last_seen_at`
- `active`

For MVP, `send_input_allowed` may be derived from role:

- `master` can send to `slave` and `swarm`
- `slave` and `swarm` cannot send input unless explicitly granted later
- `unknown` cannot send or receive input

The derived policy should still be materialized in effective permission checks
so future explicit permissions can be added cleanly.

## 19. Control API

The daemon exposes a local Unix socket API. The protocol can be JSON request /
JSON response over newline-delimited frames.

Example request:

```json
{"method":"list_agents","params":{"role":"slave"}}
```

Example response:

```json
{"ok":true,"result":[{"agent_id":"agt_123","label":"codex-01","capability":"codex"}]}
```

The socket is mounted into bench containers. File permissions should restrict
access to the host user.

## 20. CLI MVP

Required MVP commands:

```bash
agenttower ensure-daemon
agenttower scan
agenttower list-containers
agenttower list-panes
agenttower list-agents
agenttower register-self
agenttower set-role
agenttower set-label
agenttower set-capability
agenttower attach-log
agenttower events
agenttower events --follow
agenttower send-input
agenttower queue
agenttower queue approve <message-id>
agenttower queue delay <message-id>
agenttower queue cancel <message-id>
agenttower route
```

Useful later commands:

```bash
agenttower open-container
agenttower claim-swarm
agenttower infer-swarms
agenttower config doctor
```

## 21. Example Workflow

1. The user starts a bench container.
2. The user starts tmux sessions for Claude CLI, Codex CLI, Gemini CLI, and
   OpenCode inside that container.
3. Each pane runs `agenttower register-self` with role and capability.
4. The user marks one or more panes as `master`.
5. The user marks available workers as `slave`.
6. A master runs `agenttower list-agents` to see available slaves.
7. The master prompts a slave to execute part of a workflow.
8. The slave starts a swarm and reports child tmux pane ids or has children run
   `agenttower register-self --role swarm --parent <slave>`.
9. AgentTower attaches logs and classifies events from the slave and swarm.
10. The master receives structured event notifications and continues the
    workflow.
11. If another master wants to prompt the same slave, AgentTower queues the
    message and asks the requesting master whether it still wants that prompt
    next after seeing the other master's prompt.

For a spec-kit workflow, the master remains responsible for the process. For
example, a Codex master may step through spec-kit and use AgentTower to prompt a
Claude slave with slash-command work such as `/clarify`, then route the answers
back into the continuing workflow. AgentTower transports prompts and events; it
does not implement spec-kit logic.

## 22. Failure Modes

Container unavailable:

- mark container inactive
- mark child panes inactive
- keep historical agent records
- do not deliver queued input

tmux unavailable inside container:

- mark container scan degraded
- report actionable error in `agenttower scan`
- keep registered agents stale until rediscovered

socket unavailable inside container:

- container CLI reports that it cannot reach host `agenttowerd`
- user can run `agenttower config doctor`

log path not host-visible:

- attach-log fails with a clear message
- optional relay may solve this in a later version

ambiguous swarm parentage:

- mark parentage as inferred
- show confidence and evidence
- allow correction through CLI

multi-master conflict:

- queue, ask the active master for approval, and expose the queue to the human

## 23. Security

AgentTower can type into live terminals. Security and safety are part of the
architecture.

Requirements:

- no network listener for MVP
- Unix socket permissions limited to the host user
- no input to unknown panes
- no silent promotion to master
- audit every routed prompt and event
- redact common secrets from event excerpts
- avoid shell interpolation for message payloads
- provide a global routing kill switch
- provide queue inspection and cancellation

## 24. V2 Scope

Likely V2 work:

- containerized source-of-truth `agenttowerd` using a shared persistent
  state/log/socket mount; see `docs/v2-container-daemon-prd.md`
- Antigravity tmux backend support
- optional in-container `agenttower-relay`
- host-only tmux discovery as a peer to container discovery
- TUI
- richer idle detection
- explicit per-agent permission grants
- file event adapters
- Python-thread and mailbox bridge support if needed
- local LLM-assisted classification as an optional classifier plugin

## 25. Open Questions

These should be resolved during implementation:

- What exact bind mount path will devBench containers use for the daemon socket
  and logs?
- What timeout should multi-master arbitration use?
- Should arbitration default to hold forever, notify the human, or eventually
  deliver FIFO?
- Which agent output patterns should define `waiting_for_input` for Claude,
  Codex, Gemini, and OpenCode?
- Should `master` permission be limited to panes explicitly marked by the human
  in the same project, same container, or all bench containers?
