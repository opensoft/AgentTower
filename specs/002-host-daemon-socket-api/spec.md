# Feature Specification: Host Daemon Lifecycle and Unix Socket API

**Feature Branch**: `002-host-daemon-socket-api`
**Created**: 2026-05-05
**Status**: Draft
**Input**: User description: "FEAT-002: Host Daemon Lifecycle and Unix Socket API. Create the next MVP feature spec from docs/mvp-feature-sequence.md. Run this from the root checkout on main only; first verify branch is main and working tree is clean, then create only the specification and requirements checklist. The feature goal is to run agenttowerd as the host source of truth and expose a local control API. A developer can use agenttower ensure-daemon to start exactly one long-running host daemon, re-run it idempotently, call agenttower status over the configured local Unix socket, call ping/status/shutdown over a newline-delimited JSON request/response protocol, and recover cleanly after daemon death, stale pid, stale lock, or stale socket state. The daemon must use the Opensoft config/state/socket paths from FEAT-001; refuse to start until config/state are initialized; enforce host-user-only socket permissions; avoid any TCP/UDP/network listener; and produce scriptable stdout/stderr and exit codes. Include lock file and pid file management, stale pid recovery, local socket lifecycle, safe shutdown, liveness checks, error cases for existing live daemon, stale socket, unwritable state path, invalid permissions, malformed JSON request, unavailable socket, and SIGTERM/ctrl-c cleanup. Out of scope for FEAT-002: container socket mounting, Docker discovery, tmux discovery, background discovery loops, registration, logs, events/classification, prompt routing, input delivery, swarms, multi-master arbitration, TUI, Antigravity, and in-container relay. Stop after specify; do not run clarify, plan, tasks, analyze, implement, or commit."

## Clarifications

### Session 2026-05-05

- Q: Which CLI command triggers daemon shutdown over the local socket API? → A: `agenttower stop-daemon` (mirrors the `agenttower ensure-daemon` verb pattern).
- Q: How does the daemon handle multiple request lines on a single socket connection? → A: One request per connection — the daemon reads one newline-delimited JSON request, writes one response, then closes the connection; any bytes after the first newline are ignored.
- Q: What daemon log file output is in scope for FEAT-002? → A: A minimal lifecycle log file under the FEAT-001 log directory recording start, ready, shutdown, stale-artifact recovery, and fatal errors only; no event/agent/pane logging in FEAT-002.
- Q: How are in-flight requests handled when shutdown is requested or a normal termination signal is received? → A: Finish in-flight, refuse new — the daemon stops accepting new connections immediately, completes responses for already-accepted connections, then closes the listener and exits.
- Q: How do concurrent `ensure-daemon` invocations against an empty state (no pid, lock, or socket) avoid starting two daemons? → A: Lock-first startup — each `ensure-daemon` acquires an exclusive lock on the FEAT-001 lock file before any pid or socket work; concurrent losers block briefly, observe the now-live daemon, and exit successfully via the FR-007 path.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Start One Host Daemon (Priority: P1)

A developer who has initialized AgentTower can run a single CLI command to make
sure the host daemon is running. The command succeeds whether it starts a new
daemon or finds an already-running daemon, and it never creates duplicate
daemons for the same resolved AgentTower state directory.

**Why this priority**: Every later MVP feature depends on a host daemon that is
safe to start repeatedly from shell hooks, terminal helpers, and bench setup
scripts.

**Independent Test**: From an initialized AgentTower state directory with no
daemon running, run `agenttower ensure-daemon` twice and verify both invocations
succeed while only one daemon instance owns the local control socket.

**Acceptance Scenarios**:

1. **Given** AgentTower config and state are initialized and no daemon is running, **When** the developer runs `agenttower ensure-daemon`, **Then** one host daemon starts, binds the configured local socket, records its liveness state, and the command exits successfully.
2. **Given** that daemon is already running, **When** the developer runs `agenttower ensure-daemon` again, **Then** the command exits successfully without starting a second daemon.
3. **Given** AgentTower has not been initialized, **When** the developer runs `agenttower ensure-daemon`, **Then** no daemon starts and the command explains which initialization step is missing.

---

### User Story 2 - Query Daemon Health Over the Local Socket (Priority: P2)

A developer can ask AgentTower whether the host daemon is alive and get
script-friendly status output from the CLI. The CLI communicates with the
daemon through the configured local Unix socket and reports unavailable or
unhealthy daemon states clearly.

**Why this priority**: Container discovery and future thin clients need a small,
reliable control API before they can depend on the daemon.

**Independent Test**: Start the daemon with `ensure-daemon`, run `agenttower
status`, and verify the command reports daemon liveness, socket path, process
identity, and state location without requiring Docker, tmux, or any registered
agents.

**Acceptance Scenarios**:

1. **Given** the daemon is running, **When** the developer runs `agenttower status`, **Then** the CLI receives a successful status response over the local socket and exits successfully.
2. **Given** the socket is missing or unreachable, **When** the developer runs `agenttower status`, **Then** the CLI exits with a non-success status and prints an actionable daemon-unavailable message.
3. **Given** a client sends a `ping` request to the local socket, **When** the daemon handles it, **Then** the response confirms the daemon is alive without mutating durable state.

---

### User Story 3 - Recover From Stale Daemon State (Priority: P3)

A developer can recover from a crash or forced termination without manually
deleting stale lock, pid, or socket files. AgentTower distinguishes live daemon
state from stale daemon state and repairs only the artifacts it owns.

**Why this priority**: Daemon startup must be safe in real development shells,
where containers and terminal sessions can outlive or abruptly kill processes.

**Independent Test**: Start the daemon, terminate it abruptly, leave its pid,
lock, and socket artifacts in place, then run `agenttower ensure-daemon` and
verify a healthy daemon is restored without manual cleanup.

**Acceptance Scenarios**:

1. **Given** a stale pid file points to a process that no longer exists, **When** the developer runs `agenttower ensure-daemon`, **Then** AgentTower removes or replaces its stale lifecycle artifacts and starts one daemon.
2. **Given** a stale socket file exists but no live AgentTower daemon owns it, **When** the developer runs `agenttower ensure-daemon`, **Then** AgentTower replaces the stale socket safely and starts one daemon.
3. **Given** a live AgentTower daemon owns the lock and socket, **When** another startup attempt runs, **Then** the attempt reports the existing daemon and does not disturb it.

---

### User Story 4 - Shut Down Cleanly for Development (Priority: P4)

A developer can stop the daemon through the local control API during tests,
development, or shell cleanup. The daemon also handles normal process
termination by releasing its local socket and liveness artifacts.

**Why this priority**: A development MVP needs deterministic teardown so tests
and repeated spec-kit implementation passes do not leave confusing daemon
state.

**Independent Test**: Start the daemon, request shutdown through the supported
control API or CLI, and verify the process exits and the control socket no
longer accepts requests.

**Acceptance Scenarios**:

1. **Given** the daemon is running, **When** a valid shutdown request is sent over the local socket, **Then** the daemon stops accepting new work, exits cleanly, and removes owned socket and liveness artifacts.
2. **Given** the daemon receives a normal termination signal, **When** shutdown completes, **Then** a subsequent `agenttower ensure-daemon` can start a fresh daemon without manual cleanup.
3. **Given** the daemon is not running, **When** a shutdown request is attempted through the CLI, **Then** the CLI reports that no reachable daemon was stopped.

---

### Edge Cases

- AgentTower config file, state database, or schema-version marker is missing.
- Required config, state, or socket parent paths are owned by another user or
  have broader-than-host-user permissions.
- The configured state directory or socket parent exists but is not writable by
  the host user.
- A pid file points to an unrelated live process.
- A lock file exists without a reachable daemon.
- A socket path exists as a regular file, directory, symlink, or stale socket.
- Another AgentTower daemon is already live for the same resolved state
  directory.
- The daemon receives malformed JSON, an unknown method, or an incomplete
  request.
- A client writes additional bytes after the first request line on the same
  connection.
- The client connects to a socket that closes before a full response.
- The daemon receives SIGTERM or keyboard interruption while handling a request.
- The system clock changes while uptime or start time is reported.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a long-running `agenttowerd` host daemon mode that remains active until a shutdown request or normal termination signal is received.
- **FR-002**: Users MUST be able to run `agenttower ensure-daemon` to ensure the daemon is running for the currently resolved AgentTower config and state paths.
- **FR-003**: `agenttower ensure-daemon` MUST refuse to start the daemon until FEAT-001 initialization artifacts required for daemon operation are present and readable.
- **FR-004**: The daemon and CLI MUST use the config, state database, event history, log directory, socket, and cache paths resolved by the FEAT-001 path contract.
- **FR-005**: System MUST maintain daemon liveness artifacts sufficient to identify the active daemon process, the state directory it serves, and whether startup state is live or stale.
- **FR-006**: System MUST prevent more than one live daemon from serving the same resolved AgentTower state directory.
- **FR-007**: Re-running `agenttower ensure-daemon` while the daemon is live MUST succeed without replacing, killing, or duplicating the live daemon.
- **FR-008**: System MUST detect stale pid, lock, and socket artifacts when no live AgentTower daemon owns them, and MUST recover without requiring manual deletion.
- **FR-009**: System MUST NOT remove or overwrite a lifecycle artifact unless it can classify the artifact as AgentTower-owned and stale.
- **FR-010**: The daemon MUST expose its control API only through the configured local Unix socket path and MUST NOT open TCP, UDP, IPv4, IPv6, raw, or other network listeners.
- **FR-011**: The daemon MUST enforce host-user-only access for the local socket and any newly created lifecycle artifacts, refusing unsafe pre-existing permissions instead of silently accepting them.
- **FR-012**: The daemon MUST use a newline-delimited JSON request and response protocol for local control API messages.
- **FR-013**: The local control API MUST support `ping`, `status`, and `shutdown` methods.
- **FR-014**: Every local control API response MUST include an explicit success or error outcome that a client can parse without inspecting human-oriented text.
- **FR-015**: `ping` MUST confirm the daemon is alive without mutating durable state.
- **FR-016**: `status` MUST report at least daemon liveness, process identity, start time or uptime, socket path, state path, and served schema version when those values are available.
- **FR-017**: `shutdown` MUST stop the daemon cleanly, close the local socket, and remove owned lifecycle artifacts that should not survive a normal shutdown. On shutdown (whether triggered by the `shutdown` API method or a normal termination signal), the daemon MUST stop accepting new local socket connections immediately, complete the response for any request already accepted on an existing connection, then close the listener and exit.
- **FR-018**: The CLI MUST provide `agenttower status` and `agenttower stop-daemon` as clients of the daemon's local socket API; `agenttower stop-daemon` MUST issue the API `shutdown` method, exit successfully when the daemon confirms shutdown, and exit with a non-success status and actionable output when no reachable daemon is found.
- **FR-019**: CLI commands in this feature MUST produce stable exit codes and clear stdout/stderr separation suitable for shell scripts.
- **FR-020**: If the local socket is unavailable, unreachable, or returns an invalid response, CLI clients MUST fail with actionable output and MUST NOT attempt Docker, tmux, registration, routing, or terminal input fallback behavior.
- **FR-021**: The daemon MUST handle malformed JSON, unknown methods, and unsupported request shapes by returning structured errors without crashing.
- **FR-022**: The daemon MUST handle normal termination signals by closing the socket and leaving the next `ensure-daemon` run able to recover without manual cleanup.
- **FR-023**: The daemon MUST NOT perform container discovery, tmux discovery, log attachment, event classification, agent registration, prompt routing, input delivery, swarm tracking, multi-master arbitration, TUI behavior, Antigravity integration, or in-container relay behavior in FEAT-002.
- **FR-024**: The daemon MUST NOT write terminal input or execute commands inside user tmux panes in this feature.
- **FR-025**: The daemon lifecycle MUST be observable through CLI output and API responses even when no containers, tmux panes, or agents exist.
- **FR-026**: The daemon MUST treat each accepted local socket connection as serving exactly one request: it reads one newline-delimited JSON request, writes one newline-delimited JSON response, then closes the connection. Any bytes received after the first newline on the same connection MUST be ignored without affecting the already-sent response or daemon liveness.
- **FR-027**: The daemon MUST write a minimal lifecycle log file under the FEAT-001 log directory that records, at minimum, daemon start, ready-to-serve, normal shutdown, recovery of stale lifecycle artifacts, and fatal startup or runtime errors. The lifecycle log MUST NOT contain event, agent, pane, container, or per-request audit entries in FEAT-002; those are reserved for later features.
- **FR-028**: `agenttower ensure-daemon` MUST serialize startup through an exclusive lock on the FEAT-001 lock file before performing pid file or socket work. Concurrent invocations against an empty state MUST result in exactly one daemon being started; the invocation that loses the lock race MUST wait for the lock holder to either bring a daemon to a ready state or fail, then proceed via the existing live-daemon path (FR-007) or surface the same startup error.
- **FR-029**: The daemon MUST bound the maximum size of a single newline-delimited JSON request line to 64 KiB (65536 bytes including the trailing newline). A connection that writes more than 64 KiB before the first newline MUST receive a `request_too_large` structured error response and have its connection closed without affecting daemon liveness.

### Key Entities *(include if feature involves data)*

- **Daemon Instance**: The live host process serving one resolved AgentTower
  state directory. Key attributes include process identity, start time, socket
  path, state path, and current lifecycle state.
- **Lifecycle Artifact**: A local file-system artifact used to coordinate daemon
  startup and shutdown, such as a pid marker, lock marker, or socket file. It is
  classified as live, stale, unsafe, or missing.
- **Socket Endpoint**: The local Unix socket path clients use to reach the host
  daemon. It is owned by the host user and is never exposed as a network
  listener.
- **Control Request**: A single newline-delimited JSON command sent to the
  daemon. It has a method, optional parameters, and enough client context for
  clear errors.
- **Control Response**: A single newline-delimited JSON result returned by the
  daemon. It has a success or error outcome, optional data, and a structured
  error code for failed requests.
- **Daemon Status**: The daemon's reported health summary, including liveness,
  process identity, uptime or start time, served state path, socket path, and
  schema information.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On an initialized development host, `agenttower ensure-daemon` starts a reachable daemon within 2 seconds.
- **SC-002**: Running `agenttower ensure-daemon` 20 times in a row leaves exactly one live daemon serving the resolved state directory.
- **SC-003**: `agenttower status` receives a successful daemon response within 1 second when the daemon is already running.
- **SC-004**: After an abrupt daemon termination that leaves stale lifecycle artifacts behind, the next `agenttower ensure-daemon` restores a healthy daemon within 3 seconds.
- **SC-005**: A malformed local control request returns a structured error and does not terminate the daemon.
- **SC-006**: A normal shutdown request leaves no reachable daemon socket and allows a subsequent `agenttower ensure-daemon` to start a fresh daemon without manual cleanup.
- **SC-007**: Automated verification can confirm that FEAT-002 opens no network listener and invokes no Docker or tmux command.
- **SC-008**: Unsafe permissions or ownership on required daemon paths cause startup to fail before a socket is bound, with a path-specific error message.
- **SC-009**: Running 5 `agenttower ensure-daemon` invocations concurrently against an empty state directory results in exactly one live daemon and all 5 invocations exiting successfully.

## Assumptions

- AgentTower MVP targets a POSIX-like host environment where local Unix sockets
  and host-user file permissions are available.
- A single host user owns and runs the CLI and daemon. Multi-user shared daemon
  operation is out of scope for MVP.
- FEAT-001 `agenttower config init` remains the explicit initialization step;
  FEAT-002 daemon startup does not silently create or migrate missing durable
  state.
- One daemon serves one resolved AgentTower state directory. Running separate
  daemons for separate test directories is allowed only when their resolved
  paths do not collide.
- The local control API is an MVP control surface for AgentTower CLI clients,
  not a remotely accessible or public network API.
- FEAT-002 lifecycle observability is limited to CLI output and local API
  responses. User-facing event ingestion, event classification, and follow-mode
  event streams are owned by later features.
- FEAT-002 introduces no third-party Python runtime dependencies of its own,
  independent of FEAT-001. Implementation uses the Python standard library only.
  Adding a runtime dependency requires a spec amendment.
- The threat model for FEAT-002 is a single-user developer host: the host user
  is trusted, the local filesystem under the resolved AgentTower namespace is
  trusted, and there is no remote attacker. A malicious local process running
  at the same uid as the AgentTower user is explicitly out of scope; the
  host-user-only socket and file permissions defend against other-uid local
  processes only.
- Connection-level denial-of-service controls are out of scope for FEAT-002:
  there is no concurrent-connection cap, no slow-client read timeout, and no
  request-rate limiting beyond the per-request 64 KiB size limit (FR-029).
  Justification: under the single-host-user threat model, the only client of
  the local socket is the AgentTower CLI itself; rate-limiting requirements
  may be revisited if FEAT-002 is later exposed to untrusted local clients.
- FEAT-002 daemonization detaches the daemon from its controlling terminal via
  `setsid()` (a new session is created when the daemon is spawned by
  `ensure-daemon`). This means the daemon shares no controlling terminal with
  other host processes and cannot be SIGHUP-ed by terminal close. SIGHUP is
  unhandled in FEAT-002; the daemon receives the OS default action. This is
  acceptable for MVP because the daemon offers no config-reload behavior in
  this feature; later features that introduce reload semantics can add a
  SIGHUP handler.
