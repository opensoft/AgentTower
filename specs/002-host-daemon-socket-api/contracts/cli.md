# Contract: User-Facing CLI (FEAT-002)

**Branch**: `002-host-daemon-socket-api` | **Date**: 2026-05-05

This contract is the externally-observable CLI surface that FEAT-002
ships **on top of** FEAT-001. Every behavior listed here is reachable
via `subprocess.run` from a test harness; nothing here depends on Python
in-process imports.

FEAT-002 adds:

- One new `agenttowerd` subcommand: `run`.
- Three new `agenttower` subcommands: `ensure-daemon`, `status`,
  `stop-daemon`.

Existing FEAT-001 behaviors (`agenttower --version`, `agenttower --help`,
`agenttower config paths`, `agenttower config init`,
`agenttowerd --version`) are unchanged.

The newline-delimited JSON socket protocol used by these commands is
documented separately in `socket-api.md`.

---

## C-CLI-101 — `agenttowerd run`

### Invocation

```bash
agenttowerd run
```

### Behavior

Enters daemon mode for the resolved AgentTower state directory. Returns
only on shutdown. The expected caller is `agenttower ensure-daemon`,
which spawns `agenttowerd run` as a detached subprocess. Direct
foreground execution is supported for development debugging.

Startup sequence (R-001 through R-011):

1. Parse argv. With no extra args, enter daemon mode. Any additional
   args print usage to stderr and exit `1`.
2. Verify FEAT-001 initialization is complete: `STATE_DB` exists and
   contains a `schema_version` row. If not, write `error_fatal` to
   stderr/lifecycle log and exit `1`.
3. Open `<STATE_DIR>/agenttowerd.lock` (`O_RDWR | O_CREAT`, mode `0600`)
   and `flock(LOCK_EX | LOCK_NB)`. If acquisition fails, the daemon
   exits `2` with stderr `error: another agenttowerd is already running
   for this state directory`. (This is the "loser of the race" path
   when `ensure-daemon` is called concurrently.)
4. Run `assert_paths_safe()` (R-011). On failure, release lock and exit
   `1` with a path-specific stderr message.
5. Classify any pre-existing pid file and socket file (R-002, R-004).
   Unlink stale socket if present and emit `daemon_recovering`. If the
   socket path exists as a non-socket file/dir, exit `1`.
6. Bind the socket with `umask(0o077)`, post-stat verify mode/owner.
7. Write the pid file (`agenttowerd.pid`, mode `0600`).
8. Emit `daemon_ready` to the lifecycle log.
9. Install SIGTERM/SIGINT handlers, ignore SIGPIPE.
10. Enter the accept loop. Each accepted connection is dispatched to a
    request handler thread (R-005) that reads one line, dispatches one
    of `ping`, `status`, `shutdown`, writes one line, and closes the
    connection (FR-026).

Shutdown sequence (R-007):

1. Either `shutdown_requested.set()` is called by the API handler or by
   the SIGTERM/SIGINT handler.
2. Stop accepting new connections (`server.shutdown()`).
3. Join in-flight handler threads, 2 s timeout per thread.
4. Unlink the socket file, pid file, and lock-file contents (the lock
   itself is released when the fd is closed).
5. Emit `daemon_exited`, exit `0` on the clean path.

### Output (stdout)

None during normal operation. Daemon logs go to the lifecycle log
(R-012), not stdout.

### Output (stderr)

- Empty on the success path until shutdown.
- On any fatal startup error: a single line of the form
  `error: <action verb>: <absolute path or context>: <reason>`,
  matching the FEAT-001 stderr pattern.

### Exit codes

| Code | Meaning                                                                       |
| ---- | ----------------------------------------------------------------------------- |
| `0`  | Clean shutdown after `shutdown` API method or SIGTERM/SIGINT.                 |
| `1`  | Pre-flight failure (FEAT-001 not initialized, unsafe paths, non-socket at socket path, missing required directories). |
| `2`  | Lock contention: another live daemon owns this state directory.               |
| `3`  | Reserved for future runtime-fatal error.                                      |

### Side effects on success

- Creates / updates `agenttowerd.lock`, `agenttowerd.pid`, and the unix
  socket at `<STATE_DIR>/agenttowerd.sock`.
- Appends to `<LOGS_DIR>/agenttowerd.log`.
- Reads one row from `STATE_DB.schema_version`.
- Removes its own pid, lock contents, and socket on clean shutdown.

### Side effects on failure

- Lock fd is closed (and lock released) before exit.
- No artifacts are left behind that were not already there.

### Out of scope (FEAT-002)

- `agenttowerd run --foreground`, `--config`, `--socket`, etc.: the
  daemon takes no flags in this feature.
- Reload signals (`SIGHUP` is unhandled in FEAT-002).

---

## C-CLI-102 — `agenttower ensure-daemon`

### Invocation

```bash
agenttower ensure-daemon
agenttower ensure-daemon --json
```

### Behavior

Idempotently ensure exactly one daemon is running for the resolved
AgentTower state directory.

Logic (FR-002, FR-007, FR-028):

1. Resolve paths from FEAT-001 `Paths`. If FEAT-001 is not initialized,
   exit `1` with `error: agenttower is not initialized; run
   \`agenttower config init\``.
2. Probe the socket: try to connect; on success, send a `ping`. If the
   `ping` returns `ok: true`, the daemon is already live → success
   path (no spawn, no re-entry). Print the success line and exit `0`.
3. If the probe fails or the socket is absent, attempt to acquire
   `agenttowerd.lock` non-blocking. If the lock is **not** held by
   anyone (we get `LOCK_EX` immediately), we know any artifacts are
   stale. Release the lock and proceed to spawn.
4. If the lock **is** held but ping failed, another `ensure-daemon` is
   in the middle of starting the daemon. Wait up to 2 s on a blocking
   `flock(LOCK_EX)` reattempt while polling the socket. As soon as a
   successful `ping` arrives, exit `0` with the success line.
5. Spawn the daemon (`subprocess.Popen` of `agenttowerd run`, R-009)
   with stdout/stderr redirected to `<LOGS_DIR>/agenttowerd.log`.
6. Poll the socket with `ping` on a 10 / 50 / 100 / 200 ms backoff for
   up to 2 s (SC-001). On success, print the success line and exit `0`.
7. If the spawned process exits or the budget elapses, exit `1` with a
   diagnostic that includes the last ~10 lines of the lifecycle log.

### Output (stdout, default)

Exactly one line of the form:

```text
agenttowerd ready: pid=<int> socket=<absolute-path> state=<absolute-path>
```

### Output (stdout, `--json`)

Exactly one line of canonical JSON:

```json
{"ok":true,"started":<bool>,"pid":<int>,"socket_path":"<...>","state_path":"<...>"}
```

`started` is `true` when this invocation actually spawned the daemon
process, `false` when it found an already-live daemon (FR-007 path).

### Output (stderr)

Empty on the success path. On failure (any non-zero exit), a single
line of the form `error: <reason>: <hint>`. Examples:

```text
error: agenttower is not initialized: run `agenttower config init`
error: daemon failed to become ready within 2.00s: see /home/.../agenttowerd.log
error: unsafe permissions on /home/.../opensoft/agenttower: refusing to start
```

### Exit codes

| Code | Meaning                                                            |
| ---- | ------------------------------------------------------------------ |
| `0`  | Daemon is live (either pre-existing or just started).              |
| `1`  | Pre-flight failure (FEAT-001 not initialized, unsafe paths).       |
| `2`  | Daemon spawned but did not become ready within budget.             |
| `4`  | Internal CLI error.                                                |

### Side effects

- May spawn a long-lived `agenttowerd run` subprocess.
- May create `<LOGS_DIR>/agenttowerd.log` with mode `0600` if absent.
- Does **not** mutate `STATE_DB`, the config file, or any FEAT-001
  artifact.

### Idempotence contract (FR-007)

Running `ensure-daemon` `N` times in succession against an already-live
daemon results in:

- Exactly one live daemon.
- Each invocation exits `0` within 1 s on a normally-loaded host.
- The socket path, pid, state path, and version are byte-identical
  across all `--json` outputs (the live daemon's pid does not change
  between reruns).

---

## C-CLI-103 — `agenttower status`

### Invocation

```bash
agenttower status
agenttower status --json
```

### Behavior

Connect to the configured socket, send a `status` request (`socket-api.md`
§3), and render the result. Does **not** start the daemon.

Logic (FR-018, FR-020):

1. Resolve the socket path from FEAT-001 `Paths.socket`.
2. Connect with a 1 s connect-timeout (SC-003 budget). On
   `FileNotFoundError` (path missing), `ConnectionRefusedError`, or
   timeout, exit `2` with a daemon-unavailable message. Do **not**
   attempt Docker, tmux, registration, or any fallback (FR-020).
3. Send the request, read one response line (1 s read-timeout). On
   timeout or invalid JSON, exit `2`.
4. If the response is `ok: false`, exit `3` with the `error.message`
   on stderr and the `error.code` on a second stderr line.
5. Render the result and exit `0`.

### Output (stdout, default)

Six lines, fixed order, `key=value` form:

```text
alive=true
pid=<int>
start_time=<ISO-8601>
uptime_seconds=<int>
socket_path=<absolute path>
state_path=<absolute path>
```

(`schema_version` and `daemon_version` are returned in the JSON form
but not in the human-readable summary, to keep the default output a
quick at-a-glance view; both are present in `--json` output for
scripting.)

### Output (stdout, `--json`)

Exactly one line of the response's `result` object verbatim, plus the
`ok` field:

```json
{"ok":true,"result":{"alive":true,"pid":12345,"start_time_utc":"2026-05-05T12:34:56.789012+00:00","uptime_seconds":42,"socket_path":"/home/.../agenttowerd.sock","state_path":"/home/.../","schema_version":1,"daemon_version":"0.2.0"}}
```

### Output (stderr)

Empty on success.

On daemon-unavailable (exit `2`), one line:

```text
error: daemon is not running or socket is unreachable: try `agenttower ensure-daemon`
```

On daemon-error (exit `3`), two lines:

```text
error: <error.message>
code: <error.code>
```

### Exit codes

| Code | Meaning                                          |
| ---- | ------------------------------------------------ |
| `0`  | `status` returned `ok: true`.                    |
| `2`  | Socket missing, connect refused, or timed out.   |
| `3`  | Daemon returned a structured error.              |
| `4`  | Internal CLI error.                              |

---

## C-CLI-104 — `agenttower stop-daemon`

### Invocation

```bash
agenttower stop-daemon
agenttower stop-daemon --json
```

### Behavior

Send the `shutdown` API method to the daemon over the socket and report
the outcome. Does not block waiting for the daemon process to exit
beyond verifying that the socket subsequently becomes unreachable
(FR-018, FR-022).

Logic:

1. Resolve socket path from FEAT-001 `Paths.socket`.
2. Connect (1 s timeout). If unreachable → exit `2` with
   `error: no reachable daemon to stop` (US4 acceptance scenario 3).
3. Send `{"method":"shutdown"}`, read one response line.
4. If `ok: true`, poll the socket for up to 3 s (SC-006 budget) until a
   `connect` raises `FileNotFoundError` or `ConnectionRefusedError`.
   Then print the success line and exit `0`.
5. If `ok: false`, exit `3` with the structured error.
6. If the post-shutdown poll exceeds 3 s, exit `3` with
   `error: daemon acknowledged shutdown but socket is still reachable`.

### Output (stdout, default)

One line:

```text
agenttowerd stopped: socket=<absolute-path> state=<absolute-path>
```

### Output (stdout, `--json`)

```json
{"ok":true,"stopped":true,"socket_path":"<...>","state_path":"<...>"}
```

### Output (stderr)

Empty on success. On failure, see exit codes below.

### Exit codes

| Code | Meaning                                                   |
| ---- | --------------------------------------------------------- |
| `0`  | Daemon acknowledged shutdown and the socket is unreachable. |
| `2`  | No reachable daemon to stop (US4 acceptance #3).          |
| `3`  | Daemon returned an error or did not release the socket.   |
| `4`  | Internal CLI error.                                       |

---

## Cross-cutting CLI guarantees (FEAT-002)

- All FEAT-002 invocations produce **no records** in `EVENTS_FILE`.
- All FEAT-002 invocations open **no network listener** (FR-010, SC-007).
- No FEAT-002 invocation calls Docker or tmux (FR-023, SC-007). The
  socket-protocol client uses only the local `AF_UNIX` socket.
- All failures exit non-zero with stderr that names the offending path
  or cause (FR-019).
- All paths printed or operated on resolve to absolute paths under the
  user's `opensoft/agenttower` namespace (FEAT-001 contract).
- The daemon writes only to the lifecycle log file (and the socket).
  It does not write events to `EVENTS_FILE` (FR-027).
