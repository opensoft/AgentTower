# AgentTower V2 Container Daemon Product Requirements Document

Author/Vendor: Opensoft  
Product: AgentTower  
Primary CLI: `agenttower`  
Daemon: `agenttowerd`  
Target environment: Linux/WSL developer workstations using Docker, devBench
containers, tmux, Claude Code, Codex CLI, Gemini CLI, OpenCode, and long-running
terminal workflows  
Status: Draft V2 PRD v0.1  
Date: 2026-05-06

## 1. Executive Summary

AgentTower MVP keeps `agenttowerd` on the host. V2 should explore moving the
source-of-truth daemon into a dedicated AgentTower daemon container while bench
containers continue to run thin `agenttower` clients and tmux panes.

The V2 container-daemon model should preserve the MVP control-plane behavior:
discover bench containers, discover tmux panes, record agent metadata, attach
logs, classify events, and route safe prompts. The main V2 change is deployment:
`agenttowerd` runs in a managed container and uses a shared state/log/socket
mount that is also mounted into every participating bench container.

The preferred V2 storage model is a shared persistent Docker volume or WSL host
bind mount. The daemon container root filesystem must not be the source of truth
for logs, state, sockets, or event history.

## 2. Problem Statement

MVP host-daemon deployment is the correct first step because it gives the daemon
direct access to Docker and host-owned state with minimal moving parts. After MVP
proves the workflow, Opensoft may want a more container-native deployment where:

- AgentTower can be started as a standard container service.
- Bench containers talk to a daemon container over a shared Unix socket.
- Pane logs are written to a shared Linux-mounted volume.
- The daemon can use Linux file notifications such as inotify for low-latency log
  wakeups.
- AgentTower state can be isolated from the user's host Python environment.
- devBench templates can standardize the AgentTower mount contract.

The risk is that a naive container-daemon design can lose data or make running
bench containers unmanaged. Docker cannot add a missing bind mount to an already
running container, and storage that exists only inside the daemon container is
fragile across daemon restarts, upgrades, and recreation.

## 3. Goals

V2 must:

1. Run `agenttowerd` as a dedicated daemon container.
2. Preserve a single source-of-truth daemon for a developer workspace.
3. Discover running bench containers from the daemon container.
4. Detect whether each bench container has the required AgentTower shared mount.
5. Let bench containers reach the daemon through a mounted Unix socket.
6. Let bench containers write tmux `pipe-pane` logs into the shared mount.
7. Let the daemon watch shared logs with optional inotify and mandatory
   offset-based reconciliation.
8. Preserve durable state across daemon container restart, upgrade, and
   recreation.
9. Support both Docker named volume and WSL host bind-mount deployments.
10. Report unmanaged bench containers clearly when they are missing the required
    socket/log mount.
11. Keep MVP host-daemon deployment supported until V2 is explicitly adopted.

## 4. Non-Goals

V2 should not:

- require one daemon per bench container by default
- store source-of-truth state only in the daemon container root filesystem
- require a network listener for bench-to-daemon communication
- require bench containers to write directly to the registry database
- silently mutate or restart existing bench containers to add mounts
- replace tmux, Docker, Claude Code, Codex CLI, Gemini CLI, or OpenCode
- solve remote/cloud agent orchestration
- make inotify the only correctness mechanism for log ingestion

## 5. Recommended Deployment Model

V2 should run one AgentTower daemon container per developer workspace.

```text
Docker host / WSL

  agenttowerd container
    /agenttower/state/agenttower.sqlite3
    /agenttower/state/events.jsonl
    /agenttower/state/agenttowerd.sock
    /agenttower/state/logs/
    Docker discovery/control access

  bench container A
    /agenttower/state/agenttowerd.sock
    /agenttower/state/logs/
    tmux panes
    thin agenttower client

  bench container B
    /agenttower/state/agenttowerd.sock
    /agenttower/state/logs/
    tmux panes
    thin agenttower client
```

The shared mount may be either:

- a Docker named volume, for a clean container-native deployment
- a WSL host bind mount, for easier human inspection, backup, and debugging

The daemon owns SQLite writes. Bench containers write tmux pane logs and call the
daemon socket. Bench containers must not write directly to SQLite or JSONL event
history except through daemon-owned APIs.

## 6. Storage Decision

### 6.1 Preferred: Shared Persistent Volume

The primary V2 design should use a shared persistent volume mounted into the
daemon container and every participating bench container.

Benefits:

- survives daemon container restart and recreation
- gives bench containers a stable log path
- lets the daemon watch logs from one directory tree
- avoids coupling AgentTower to one host path when a named Docker volume is used
- still allows host inspection when a WSL bind mount is selected

Required paths:

```text
/agenttower/state/agenttower.sqlite3
/agenttower/state/events.jsonl
/agenttower/state/agenttowerd.sock
/agenttower/state/logs/<container>/<agent-id>.log
/agenttower/state/config.toml
```

### 6.2 Allowed: WSL Host Bind Mount

A WSL host bind mount is acceptable and may be the best default for early V2
testing because it keeps state easy to inspect.

Example host path:

```text
~/.local/state/opensoft/agenttower-v2/
```

### 6.3 Rejected: Daemon Container Root Filesystem

AgentTower should not use a path that exists only inside the daemon container as
the source of truth for logs, sockets, SQLite, or event history.

Reasons:

- bench containers cannot reliably mount another container's root filesystem
- daemon container recreation can lose logs and sockets
- existing `tmux pipe-pane` attachments can break after daemon replacement
- crash diagnosis becomes harder when logs disappear with the daemon container
- upgrades become stateful and risky

Ephemeral container-local storage may be used only for temporary caches that can
be safely regenerated.

## 7. Bench Container Contract

Each managed bench container must mount the AgentTower shared state path at the
same container path expected by the thin client.

Required environment:

```text
AGENTTOWER_SOCKET=/agenttower/state/agenttowerd.sock
AGENTTOWER_STATE_DIR=/agenttower/state
AGENTTOWER_LOG_DIR=/agenttower/state/logs
```

Required behavior:

- `agenttower status` inside the bench container reaches the daemon container.
- `agenttower register-self` can identify the current container and tmux pane.
- `agenttower attach-log` writes the pane log into the shared log directory.
- Missing or unreadable mounts are reported by `agenttower config doctor`.

V2 should provide Docker Compose, devcontainer, or devBench snippets that add
the mount and environment variables before a bench container starts.

## 8. Discovery and Startup

The V2 startup flow should be:

1. Start the `agenttowerd` container.
2. The daemon opens the shared Unix socket.
3. The daemon scans running containers using configured bench matching rules.
4. The daemon marks each running bench container as managed or unmanaged.
5. Managed containers have the required shared state/log/socket mount.
6. Unmanaged containers are reported with an actionable fix.
7. The daemon scans tmux panes in managed containers.
8. The daemon attaches or verifies pane logs for registered agents.
9. The daemon begins log ingestion and event classification.

Important constraint: V2 should not silently restart a running bench container to
add missing mounts. Docker does not support adding arbitrary bind mounts to an
already running container, so AgentTower must report the problem and provide
restart instructions or template updates.

## 9. Log Watching

V2 may use inotify from inside the daemon container when the shared mount
supports it. Inotify is a latency optimization, not the correctness model.

Correctness still depends on:

- durable log files
- SQLite log offsets
- file size, inode, and mtime checks
- periodic polling reconciliation
- safe handling of missing, truncated, or rotated logs

Expected watcher behavior:

```text
on inotify modify/create/move event:
  enqueue the affected log path for reading

periodically:
  stat every attached log path
  read appended bytes from saved offset
  update offset
  classify events
```

This design survives missed file notifications and daemon restarts.

## 10. Docker Access

The daemon container needs enough Docker access to inspect bench containers and
run tmux/log commands where required.

Possible access models:

1. Mount the Docker socket into the daemon container.
2. Use a constrained Docker API proxy.
3. Use a small host-side helper for privileged Docker operations.

Mounting the Docker socket is the simplest implementation, but it grants broad
host Docker control. V2 must document this risk and should prefer a constrained
proxy or helper if the security bar requires it.

## 11. Functional Requirements

- **V2-FR-001**: System MUST provide a supported deployment mode where
  `agenttowerd` runs in a dedicated daemon container.
- **V2-FR-002**: The daemon container MUST use a persistent shared state mount
  for SQLite, JSONL events, logs, config, and the Unix socket.
- **V2-FR-003**: Source-of-truth state MUST survive daemon container restart and
  recreation.
- **V2-FR-004**: System MUST NOT use the daemon container root filesystem as the
  source of truth for durable state.
- **V2-FR-005**: Bench containers MUST reach the daemon through a mounted Unix
  socket, not a TCP/UDP network listener.
- **V2-FR-006**: The daemon MUST detect running bench containers that are
  missing the shared mount and mark them unmanaged.
- **V2-FR-007**: The daemon MUST NOT silently restart or mutate running bench
  containers to add missing mounts.
- **V2-FR-008**: The daemon MUST support Docker named volume and WSL host
  bind-mount deployments.
- **V2-FR-009**: Bench containers MUST write pane logs into the shared log
  directory through `tmux pipe-pane`.
- **V2-FR-010**: Log ingestion MUST use durable offsets and periodic
  reconciliation even when inotify is enabled.
- **V2-FR-011**: The daemon MAY use inotify to reduce event latency when the
  shared mount supports it.
- **V2-FR-012**: The daemon MUST degrade to polling when file notifications are
  unavailable or unreliable.
- **V2-FR-013**: Bench containers MUST NOT write directly to SQLite registry
  state.
- **V2-FR-014**: `agenttower config doctor` MUST report socket reachability,
  shared mount visibility, tmux identity, and daemon-container reachability.
- **V2-FR-015**: V2 MUST preserve the MVP safety policy for prompt delivery and
  must not inject input into unknown or unauthorized panes.

## 12. Success Criteria

- A user can start the daemon container and run `agenttower status` from the
  host and from a managed bench container.
- Running bench containers are classified as managed or unmanaged.
- A managed bench container can register a tmux pane as an agent.
- A registered pane can attach a `tmux pipe-pane` log under the shared log
  directory.
- The daemon container detects appended log output within two seconds with
  polling alone, and faster when inotify is available.
- Restarting or recreating the daemon container does not delete SQLite state,
  JSONL events, socket mount configuration, or pane logs.
- An unmanaged bench container receives a clear diagnostic and a documented
  restart/template fix.
- No bench container writes directly to the registry database.

## 13. Test Strategy

### 13.1 Unit Tests

- shared path resolution
- mount contract validation
- managed/unmanaged container classification
- inotify event normalization
- polling reconciliation
- log truncation and rotation handling
- Docker inspect parsing
- socket path and permission checks

### 13.2 Integration Tests With Fake Docker

Use fake Docker command/API responses to test:

- daemon container startup
- bench container discovery
- missing mount diagnostics
- named-volume versus bind-mount path detection
- unavailable Docker access
- malformed Docker metadata

### 13.3 Real Docker Smoke Tests

Run a daemon container and at least one bench container using the shared mount.

Required smoke flow:

```bash
agenttower container up
agenttower status
docker exec <bench> agenttower status
docker exec <bench> tmux new-session -d -s agenttower-smoke
docker exec <bench> agenttower register-self --role slave --capability shell
docker exec <bench> agenttower attach-log
agenttower events --follow
```

The smoke test passes when the daemon container sees the bench container, the
bench container reaches the socket, the tmux pane log is written to the shared
mount, and appended output produces AgentTower events.

### 13.4 Restart Tests

- restart daemon container
- recreate daemon container with the same shared volume
- verify registry state remains
- verify old pane logs remain readable
- verify log offsets resume without duplicating prior events

## 14. V2 Milestones

### Milestone 1: Container Deployment Skeleton

- Build daemon container image.
- Start daemon container with shared volume.
- Expose Unix socket in shared volume.
- Preserve MVP host-daemon mode.

### Milestone 2: Shared Mount Contract

- Define named-volume and WSL bind-mount templates.
- Add `config doctor` checks.
- Mark containers managed/unmanaged.

### Milestone 3: Containerized Log Watching

- Watch shared logs from daemon container.
- Add optional inotify wakeups.
- Keep offset polling reconciliation.

### Milestone 4: Docker Access Hardening

- Document Docker socket risk.
- Evaluate constrained Docker proxy or host helper.
- Add least-privilege deployment option if feasible.

### Milestone 5: Migration and Compatibility

- Provide migration from MVP host state to V2 shared state.
- Keep CLI behavior stable across host-daemon and container-daemon modes.
- Document rollback to MVP host daemon.

## 15. Open Questions

1. Should the first V2 implementation default to a Docker named volume or WSL
   host bind mount?
2. Is mounting the Docker socket acceptable for the initial V2 prototype, or
   should a constrained Docker API proxy be required from the start?
3. Should V2 provide an `agenttower container up` command, a Compose file, or
   both?
4. Should unmanaged bench containers be merely reported, or should AgentTower
   offer to generate a replacement/restart command?
5. How should V2 migrate existing MVP state paths without duplicating agent IDs
   or losing log offsets?
6. Should inotify be implemented through a small Linux-only dependency, ctypes,
   or delayed until a later optimization pass?
