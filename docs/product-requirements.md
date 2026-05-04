# AgentTower Product Requirements Document

Author/Vendor: Opensoft  
Product: AgentTower  
Primary CLI: `agenttower`  
Daemon: `agenttowerd`  
Target environment: Linux/WSL developer workstations using tmux, Docker, devcontainers, Claude Code, Codex CLI, and long-running terminal workflows  
Status: Draft PRD v0.1  
Date: 2026-05-03

## 1. Executive Summary

AgentTower is an Opensoft local orchestration and monitoring tool for
developers who run multiple AI agent terminals, test jobs, and container shells
in tmux. It provides a local control tower for agent work: discover every tmux
session and pane, show what each pane is doing, let the user assign roles such
as orchestrator or worker, monitor activity and logs, classify important events,
and route concise notifications to one or more selected orchestrator panes.

The system is motivated by a concrete workflow need: a user may run Claude Code,
Codex CLI, test runners, and container shells at the same time. tmux can
preserve durable sessions and mark activity, but it does not notify another
agent or automatically route messages. AgentTower fills that gap by adding
discovery, durable registration, activity classification, event routing, and a
human-facing control surface.

The first version should be a Python CLI and daemon using tmux and Docker
commands directly, SQLite for durable state, JSONL for event logs, and a
terminal UI after the core daemon behavior is stable. The product should be
local-first, transparent, scriptable, and careful about when it sends input into
interactive panes.

## 2. Problem Statement

Developers increasingly run multiple autonomous or semi-autonomous CLI agents in
parallel. Common examples include:

- one main Codex or Claude session acting as an orchestrator
- one or more Claude workers inside tmux windows
- one or more Codex sessions in YOLO mode for focused tasks
- pytest or model benchmark jobs that take a long time
- project shells connected to Docker or devcontainers
- repo worktrees and branch-specific environments

Today, the user has to manually remember where each pane is, poll tmux windows,
inspect logs, and decide whether an agent is waiting for input or still working.
tmux provides sessions, panes, and activity flags, but those signals are
low-level. `tmux monitor-activity` marks activity inside tmux; it does not wake
or notify another agent. `tmux pipe-pane` can write logs, but it does not
interpret them.

The result is operational friction:

- Agents ask questions and sit idle unnoticed.
- Tests finish or fail without a routed notification.
- Multiple tmux sessions become hard to track.
- It is easy to send input to the wrong pane.
- Container context is unclear from the outside.
- Unregistered panes are invisible to helper scripts that rely only on explicit
  registration.

AgentTower should make the local multi-agent terminal environment observable and
routable while keeping the human in control.

## 3. Goals

AgentTower must:

1. Discover all accessible tmux servers, sessions, windows, and panes for the
   current Linux user.
2. Display discovered panes even when they were not launched through
   AgentTower.
3. Let the user label panes and assign roles such as orchestrator, worker, test
   runner, or container shell.
4. Support multiple orchestrators at the same time.
5. Route worker events to one or more selected orchestrator panes.
6. Monitor pane output using durable logs, preferably through `tmux pipe-pane`.
7. Classify meaningful events such as waiting for input, command complete, error
   detected, test failure, or manual review needed.
8. Show available Docker containers and devcontainer-like runtime contexts.
9. Infer whether a pane appears connected to a container when possible.
10. Allow the user to open a new tmux pane or window attached to a selected
    container.
11. Provide a CLI that existing shell helpers such as `yodex`, `yolo`, and
    `cta` can call.
12. Ensure the daemon can be started idempotently whenever a tmux helper starts.
13. Store configuration under the Opensoft namespace.
14. Avoid unsafe or surprising input injection into interactive agent panes.

## 4. Non-Goals for the First Version

The first version should not try to:

- replace tmux
- replace Claude Code or Codex CLI
- host model inference
- manage cloud agents
- implement a full web dashboard before core routing works
- directly edit project repositories
- infer perfect semantic state from arbitrary terminal output
- automatically answer every agent question without a policy layer
- move an existing shell process into a container
- require every pane to be launched through AgentTower

A web UI may be useful later, but the first implementation should be CLI/daemon
first and optionally TUI first.

## 5. Users and Personas

### Primary User: Local Multi-Agent Developer

A developer running several AI agent sessions, tests, and container shells at
once. They need a reliable way to see which panes exist, which are waiting, and
which orchestrator should be notified.

### Secondary User: Agent Orchestrator Operator

A user who wants one Claude or Codex session to act as the main operator. They
need worker panes to notify that orchestrator when they need direction.

### Secondary User: Container-Based Developer

A developer using Docker, devcontainers, or workbench/runtime containers. They
need to see which tmux panes are connected to which containers and open new
panes in selected containers.

## 6. Core Concepts

### Pane

A tmux pane discovered through tmux. It has a pane id such as `%4`, session
name, window index, pane index, current command, current path, tty, process id,
and optional AgentTower metadata.

### Registered Pane

A pane with AgentTower metadata such as label, role, log path, routing targets,
and send-input permission.

### Unregistered Pane

A pane discovered from tmux but not known to AgentTower. It must still appear in
the app so the user can assign metadata.

### Orchestrator

A pane selected to receive routed notifications and possibly drive other panes.
There may be multiple orchestrators.

### Worker

A pane whose output should be monitored and routed to one or more orchestrators.

### Controller / Hub

The overall AgentTower daemon and registry that coordinates discovery,
monitoring, event queueing, and routing.

### Event

A classified activity item derived from pane output, tmux metadata, or container
state. Examples include `waiting_for_input`, `completed`, `error`,
`test_failed`, and `manual_review_needed`.

### Route

A configuration mapping from a source pane to one or more orchestrator panes.

## 7. Functional Requirements

### 7.1 tmux Discovery

AgentTower must query tmux directly to discover panes, including panes that did
not register themselves.

Minimum command shape:

```bash
tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index} pane=#{pane_id} pid=#{pane_pid} tty=#{pane_tty} cmd=#{pane_current_command} cwd=#{pane_current_path} title=#{pane_title}'
```

AgentTower should discover the default tmux server for the current user. It
should also support scanning accessible tmux sockets under:

```text
/tmp/tmux-$(id -u)/
```

If multiple tmux sockets exist, AgentTower should list panes per socket and
store the socket path as part of pane identity.

Acceptance criteria:

- Running `agenttower scan` discovers all panes in the default tmux server.
- Unregistered panes appear in `agenttower list-panes`.
- Pane identity includes tmux socket, session, window, pane index, and pane id.
- Discovery failures are reported without crashing the daemon.

### 7.2 Pane Registry

AgentTower must maintain a durable registry for pane metadata. Raw tmux
discovery provides volatile facts; AgentTower stores human and routing metadata.

Required metadata:

- pane id
- tmux socket
- session name
- window index
- pane index
- current command
- current working directory
- pid
- tty
- label
- role
- project path
- log path
- routing targets
- send-input permission
- last seen timestamp
- active/inactive status

Roles should include at least:

- `orchestrator`
- `worker`
- `test-runner`
- `container-shell`
- `unknown`

Acceptance criteria:

- User can label a pane.
- User can mark one or more panes as orchestrators.
- User can mark panes as workers and route them to orchestrators.
- Registry survives process restart.

### 7.3 Multiple Orchestrators

AgentTower must support multiple orchestrator panes. A worker can route events
to one primary orchestrator or multiple subscribed orchestrators.

Example route model:

```json
{
  "source_pane_id": "%4",
  "source_label": "claude-010",
  "routes_to": ["%0", "%7"],
  "event_types": ["waiting_for_input", "error", "completed"]
}
```

Acceptance criteria:

- More than one pane can have role `orchestrator`.
- A worker can route to multiple orchestrators.
- A worker can be configured to route only selected event types.
- The app can show route mappings clearly.

### 7.4 Logging and Monitoring

AgentTower must prefer log-based monitoring over raw tmux activity flags. tmux
TUI applications repaint often, so activity alone is too noisy.

AgentTower should use:

```bash
tmux pipe-pane -o -t <pane> 'cat >> <log_file>'
```

`monitor-activity` may be enabled as a secondary visual signal:

```bash
tmux set-window-option -t <pane> monitor-activity on
```

Acceptance criteria:

- AgentTower can attach a log to a pane.
- AgentTower can detect whether pipe-pane is active.
- AgentTower stores log paths in its registry.
- AgentTower can continue watching after restart by using stored log offsets.
- AgentTower does not treat every TUI repaint as a meaningful event.

### 7.5 Event Classification

AgentTower must classify terminal output into meaningful events.

Initial event types:

- `activity`: generic output changed
- `waiting_for_input`: agent or process appears to be asking for input
- `completed`: a job or command appears complete
- `error`: a command or process emitted an error
- `test_failed`: test output indicates failure
- `test_passed`: test output indicates success
- `manual_review_needed`: agent or workflow asks for human/manual decision
- `long_running`: no terminal completion yet after a configured time
- `pane_exited`: pane process ended

Classification should be conservative. It is better to notify with uncertainty
than to send unsafe commands automatically.

Acceptance criteria:

- AgentTower emits JSONL events with pane id, timestamp, type, summary, and raw
  excerpt.
- Duplicate output is debounced.
- Events include enough context for an orchestrator to decide what to do.
- Classifier rules are configurable or extensible.

### 7.6 Notification Routing

AgentTower must route compact notifications to orchestrator panes. It should not
blindly type verbose logs or commands.

Recommended notification format:

```text
[AgentTower] Activity from claude-010 pane %4.

State: waiting_for_input
Latest output:
Claude is asking whether to proceed despite incomplete checklist items.

Recommended action: ask it to triage incomplete checklist items read-only before implementation.
```

Routing should use safe input methods such as `tmux paste-buffer` followed by
`Enter`, rather than brittle keystroke-by-keystroke typing for long text.

Acceptance criteria:

- User can enable or disable routing per pane.
- User can mark whether AgentTower is allowed to send input to a target
  orchestrator pane.
- AgentTower can route a notification to one orchestrator.
- AgentTower can route a notification to multiple orchestrators.
- AgentTower can run in notify-only mode where events are logged but not sent.

### 7.7 Safe Input Policy

AgentTower must avoid corrupting interactive sessions. Before sending to an
orchestrator, it should consider whether the target pane appears idle, in a
slash-command menu, or already processing.

Minimum safety rules:

- Never send input to a pane unless user has granted send-input permission.
- Prefer notify-only default for untrusted panes.
- Do not send a notification while a target pane appears to be mid-command
  unless configured.
- Use a queue when the orchestrator is not ready.
- Provide a dry-run or preview mode.

Acceptance criteria:

- Send-input permission defaults to false for discovered panes.
- Registered orchestrators can opt into receiving routed text.
- Queued notifications are visible in CLI/TUI.
- The user can flush or discard queued notifications.

### 7.8 Docker and Devcontainer Discovery

AgentTower must show available containers and infer pane-to-container
relationships where possible.

Minimum Docker commands:

```bash
docker ps -a --format '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'
docker inspect <container>
```

AgentTower should display:

- container id
- name
- image
- status
- compose project/service labels
- devcontainer labels where available
- mounted workspace paths
- ports if useful

Acceptance criteria:

- `agenttower list-containers` shows running and stopped containers.
- Container metadata includes name, image, status, and useful labels.
- Docker failures are handled gracefully when Docker is unavailable.

### 7.9 Connecting tmux Panes to Containers

AgentTower should let the user open new tmux panes or windows connected to
selected containers.

It cannot move an existing shell process into a container. It can:

1. Create a new tmux window or pane running:

```bash
docker exec -it <container> <shell>
```

2. Send `docker exec -it <container> <shell>` into an idle existing pane when
   explicitly requested.

The safer default is to create a new pane/window.

Acceptance criteria:

- User can select a container and open a new tmux pane attached to it.
- User can choose shell command, defaulting to `zsh` or `bash` based on
  availability.
- AgentTower labels the new pane as `container-shell`.
- AgentTower records which container the pane is associated with.

### 7.10 CLI Entrypoints

AgentTower should provide:

- `agenttower`: user-facing CLI
- `agenttowerd`: daemon process

Initial CLI commands:

```bash
agenttower ensure-daemon
agenttower scan
agenttower list-panes
agenttower list-containers
agenttower register-pane --pane <pane> --label <label> --role <role> --log <path>
agenttower attach-log --pane <pane> --log <path>
agenttower route --from <pane> --to <pane>
agenttower set-role --pane <pane> --role <role>
agenttower set-label --pane <pane> --label <label>
agenttower events
agenttower notify --from <pane> --type <type> --message <text>
agenttower open-container --container <name-or-id> --new-window
agenttower tui
```

Acceptance criteria:

- Shell helpers can call `agenttower ensure-daemon` idempotently.
- Shell helpers can register the pane they start.
- Human can inspect panes and containers from CLI.

### 7.11 Daemon Startup

Every tmux-based helper should check whether AgentTower is running and start it
if needed.

Expected helper flow:

```bash
agenttower ensure-daemon
start tmux session/pane
agenttower register-pane --pane "$pane_id" --label yodex-main --role orchestrator --log "$log_file"
agenttower attach-log --pane "$pane_id" --log "$log_file"
```

The daemon must use a lock file so repeated startup attempts do not create
duplicate daemons.

Recommended files:

```text
~/.local/state/opensoft/agenttower/agenttowerd.lock
~/.local/state/opensoft/agenttower/agenttowerd.pid
```

Acceptance criteria:

- `agenttower ensure-daemon` is safe to run repeatedly.
- If daemon is running, command exits successfully without starting another
  daemon.
- If daemon is stale, lock/pid state can be recovered.

### 7.12 tmux Hooks

AgentTower may install optional tmux hooks as a backup discovery mechanism.

Example:

```tmux
set-hook -g after-new-session 'run-shell "agenttower ensure-daemon >/dev/null 2>&1"'
set-hook -g after-new-window 'run-shell "agenttower scan >/dev/null 2>&1"'
```

Acceptance criteria:

- Hooks are optional and user-visible.
- AgentTower can install and remove hooks.
- Hooks do not break tmux startup if AgentTower is unavailable.

### 7.13 TUI

After the daemon and CLI are stable, AgentTower should provide a TUI.

The TUI should show:

- tmux servers/sockets
- sessions/windows/panes
- pane labels and roles
- current command and cwd
- log status
- latest classified event
- routes
- available containers
- pane-container associations
- queued notifications

Core user actions:

- mark pane as orchestrator
- mark pane as worker
- route worker to orchestrator
- attach/detach log
- open pane in container
- preview latest pane output
- send test notification
- enable/disable routing
- allow/deny send-input permission

Acceptance criteria:

- User can discover unregistered panes visually.
- User can assign roles without typing pane ids manually.
- User can see which panes route to which orchestrators.
- TUI does not need to be first milestone if CLI covers the workflows.

## 8. Data Storage Requirements

AgentTower should use Opensoft namespaced paths:

```text
~/.config/opensoft/agenttower/config.toml
~/.local/state/opensoft/agenttower/agenttower.sqlite3
~/.local/state/opensoft/agenttower/events.jsonl
~/.local/state/opensoft/agenttower/logs/
~/.cache/opensoft/agenttower/
```

SQLite should store durable state:

- panes
- pane metadata
- containers
- routes
- event offsets
- notification queue
- user permissions
- daemon state

JSONL should store inspectable event history:

- timestamp
- event id
- pane identity
- event type
- summary
- raw excerpt path or inline excerpt
- routed targets
- delivery status

Logs should remain append-only where possible.

## 9. Security and Safety Requirements

AgentTower can send text into live terminal panes, so it must be conservative.

Requirements:

- Do not send input to unregistered panes by default.
- Do not send input to panes without explicit permission.
- Do not print or store secrets unnecessarily.
- Redact common secret patterns from event excerpts where possible.
- Store files under user-owned directories with normal user permissions.
- Avoid destructive commands.
- Make routing actions auditable through JSONL events.
- Provide a global kill switch for routing.
- Provide per-pane send-input permissions.

## 10. Technical Recommendation

Use Python for the first implementation.

Rationale:

- Direct access to subprocess calls for tmux and Docker.
- Built-in SQLite support.
- Straightforward JSONL event writing.
- Good fit for local Linux/WSL tooling.
- Easy packaging as CLI and daemon.
- TUI can later use Textual, curses, or another Python terminal UI framework.

Recommended first implementation style:

- Python package named `agenttower`.
- Console scripts: `agenttower`, `agenttowerd`.
- Daemon uses polling every 1-2 seconds initially.
- No network service required for v0.
- Keep classifier rules simple and transparent.

## 11. Milestones

### Milestone 1: Discovery and Registry

- Initialize config/state directories.
- Implement SQLite schema.
- Discover tmux panes.
- Discover Docker containers.
- List panes and containers from CLI.
- Register pane metadata.

### Milestone 2: Logs and Events

- Attach `tmux pipe-pane` logs.
- Track file offsets.
- Emit JSONL events.
- Add basic event classifier.
- Implement debounce.

### Milestone 3: Routing

- Mark orchestrators.
- Configure worker-to-orchestrator routes.
- Queue notifications.
- Deliver notifications to permitted orchestrator panes.
- Add notify-only mode and dry-run mode.

### Milestone 4: Container Actions

- Infer container associations from process tree where possible.
- Open new tmux window/pane attached to a selected container.
- Label container panes.

### Milestone 5: TUI

- Build TUI view over panes, containers, events, and routes.
- Add keyboard actions for labeling, role assignment, routing, and container
  attach.

### Milestone 6: Shell Helper Integration

- Update `yodex`, `yolo`, `cta`, and similar helpers to call
  `agenttower ensure-daemon`.
- Register started panes.
- Attach logs automatically.
- Set default roles based on helper type.

## 12. Open Questions

1. Should AgentTower live as a standalone repo under Opensoft immediately, or
   start as a scripts package and then be extracted?
2. Should the first UI be a TUI, a web app, or CLI-only until routing is stable?
3. Should notifications be routed only to orchestrator panes or also to desktop
   notifications?
4. Should event classification use only rules at first, or optionally call a
   local LLM later?
5. How should AgentTower handle tmux panes inside containers where the host
   cannot see the tmux socket?
6. What default event types should route automatically versus require manual
   review in the TUI?
7. Should per-project routing profiles exist, or should routes be global per
   user?

## 13. Success Metrics

AgentTower is successful when:

- A user can run multiple Claude/Codex/test/container panes and see them in one
  place.
- Unregistered tmux panes are discoverable.
- Workers can notify selected orchestrators when they are waiting or fail.
- The user can safely route notifications without accidentally typing into the
  wrong pane.
- Shell helpers can start AgentTower automatically without duplicate daemons.
- Docker/container context is visible enough to choose where to open new shells.
- The system improves local multi-agent workflow without requiring changes to
  Claude, Codex, tmux, or Docker.

## 14. Initial Product Positioning

AgentTower is the local control tower for autonomous terminal agents. It does
not replace agents or terminals; it makes them observable, routable, and safer
to coordinate. It is designed for developers who work across tmux, containers,
worktrees, and AI coding agents, and who need a durable local hub for parallel
agent work.
