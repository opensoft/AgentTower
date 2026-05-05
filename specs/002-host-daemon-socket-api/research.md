# Phase 0 Research: Host Daemon Lifecycle and Unix Socket API

**Branch**: `002-host-daemon-socket-api` | **Date**: 2026-05-05

This document resolves every "NEEDS CLARIFICATION" item from the FEAT-002 plan
Technical Context section, plus the implementation-level decisions that the
spec's clarifications imply but do not pick concrete primitives for.

The spec already resolved the user-visible policy questions (CLI verbs,
connection model, log scope, shutdown semantics, lock-first startup); the
research below picks the stdlib primitives that implement that policy.

---

## R-001 — Cross-process lock primitive for `ensure-daemon` serialization

**Decision**: `fcntl.flock(fd, fcntl.LOCK_EX)` (with `LOCK_NB` for the
non-blocking probe path) on a dedicated lock file at
`<STATE_DIR>/agenttowerd.lock`.

**Rationale**:

- `flock` is in the Python standard library on Linux/macOS, requires no
  third-party dependency, and is advisory at the OS level — exactly the
  behavior the spec wants.
- The kernel automatically releases the lock when the holding process exits
  (clean or abrupt), which is the property FR-008/FR-022 require: the next
  `ensure-daemon` after a crash must succeed without manual cleanup.
- A separate lock file (rather than locking the pid file or the SQLite DB)
  keeps the lock semantics independent of pid file format and lets FEAT-002
  use the lock as the sole liveness signal (R-002 below).

**Alternatives considered**:

- `fcntl.lockf` (POSIX byte-range): same release-on-exit guarantee but
  less commonly used; flock's whole-file semantic matches the use case.
- `os.O_EXCL` create as the lock: gives no waiting/retry semantics, would
  force callers to poll, and leaks the lock file on crash (no
  release-on-exit).
- `filelock` PyPI package: introduces a runtime dependency, which the
  constitution forbids (FEAT-001 establishes stdlib-only as the precedent).

**Lock file properties**:

- Path: `<STATE_DIR>/agenttowerd.lock`.
- Mode: `0600` on creation; refuse if a pre-existing lock file has broader
  mode or wrong owner (FR-011).
- Content: a single line `pid=<int>\n` written *after* the daemon
  successfully binds the socket (purely informational; the lock itself is
  the authority).

---

## R-002 — Pid file format and stale-pid classification

**Decision**: Pid file at `<STATE_DIR>/agenttowerd.pid`, mode `0600`,
contents = decimal pid + `\n`. Stale-classification uses two signals in
order:

1. Acquire `LOCK_EX` (non-blocking, `LOCK_NB`) on `agenttowerd.lock`. If
   acquisition succeeds, no live daemon can be holding the lock — treat
   any pid file, lock content, and socket as stale.
2. If acquisition fails (lock is held), the process holding the lock is
   the live daemon. Read the pid file for the operator's reference but
   trust the lock as ground truth.

**Rationale**:

- The OS-level lock is the single source of truth; the pid file is
  human/operator-readable metadata. Avoiding `os.kill(pid, 0)` as the
  primary check sidesteps the well-known "stale pid file points at a
  recycled unrelated process" failure.
- Reduces FR-009 risk surface: the daemon never deletes "lifecycle
  artifacts" based on a guess; it deletes only when it has acquired the
  exclusive lock.

**Alternatives considered**:

- `os.kill(pid, 0)` as primary check: vulnerable to pid recycling,
  especially on long-lived dev hosts. Used at most as a corroboration
  signal, never as the deciding signal.
- Procfs scraping (`/proc/<pid>/comm`): Linux-specific, fragile, not
  needed once the lock is the authority.

---

## R-003 — Local socket binding and host-user-only permissions

**Decision**: `socket.AF_UNIX` + `socket.SOCK_STREAM` server bound at
`<STATE_DIR>/agenttowerd.sock`. Bind sequence:

1. Verify the socket parent dir is `0700` and owned by `os.geteuid()`;
   refuse otherwise (FR-011).
2. Verify no live daemon owns the socket (R-002 lock check).
3. If a stale socket file (or other path) exists at the bind path, classify
   it (R-004) and unlink only when classified stale; otherwise refuse.
4. Save the current `umask`, set `umask(0o077)`, call `bind`, restore the
   umask. This makes the kernel create the socket inode with mode `0600`.
5. After bind, `os.stat` the socket and assert `mode & 0o777 == 0o600` and
   `st_uid == os.geteuid()`. If either check fails, unlink and refuse.
6. `listen(backlog=16)` — small backlog matches the dev-host scale.

**Rationale**: stdlib only; `umask`-then-bind is the standard POSIX idiom
for forcing a tight initial mode on a socket inode. Post-bind stat is the
defense-in-depth check FR-011 expects.

**Alternatives considered**:

- `chmod` after bind: there is a brief window where the socket is reachable
  with looser permissions; the umask trick eliminates that window.
- `socket.SOCK_DGRAM`: ruled out by FR-012's request/response contract
  (newline-delimited framing presumes a stream).

---

## R-004 — Stale socket file classification

**Decision**: Once the current process holds `LOCK_EX` on
`agenttowerd.lock` (R-002 step 1 succeeded), the path at the socket
location is classified as follows:

| Existing path kind                            | Action                                                |
| --------------------------------------------- | ----------------------------------------------------- |
| Socket file (`stat.S_ISSOCK`)                 | Unlink (it cannot be live; we hold the lock).         |
| Regular file, directory, symlink, FIFO, other | **Refuse**: print path-specific error, exit non-zero. |
| Does not exist                                | Proceed to bind.                                      |

**Rationale**: Lock ownership is the authority for "this socket cannot be
live." Per FR-009 the daemon never overwrites a non-AgentTower-shaped
artifact; if the path is a regular file or directory, we refuse to remove
it because we cannot prove we own it.

**Alternatives considered**:

- `connect()` probe before unlink: unnecessary once the lock is held; was
  considered as a defense-in-depth signal but rejected as duplicate work.

---

## R-005 — Server I/O model

**Decision**: `socketserver.ThreadingUnixStreamServer` with
`daemon_threads=True`, `allow_reuse_address=False`, custom request handler
subclassing `StreamRequestHandler`.

**Rationale**:

- Pure stdlib, well-understood, minimal code.
- One thread per connection matches the spec's one-request-per-connection
  contract (FR-026): the thread reads one line, writes one line, returns,
  the connection is closed.
- `daemon_threads=True` guarantees handler threads do not block process
  exit beyond the join window (R-007).
- Throughput is irrelevant at this scale (control API only); the threading
  model's fairness and simplicity dominate.

**Alternatives considered**:

- `asyncio.start_unix_server`: requires async/await throughout the
  handler, more code, no measurable benefit at the expected concurrency.
- Single-threaded `select`/`epoll` loop: rejected for code complexity vs.
  zero scalability gain in this feature.

---

## R-006 — JSON line framing and request size limit

**Decision**: Per accepted connection, the handler:

1. Reads from `self.rfile` using `readline(MAX_REQUEST_BYTES)` where
   `MAX_REQUEST_BYTES = 64 * 1024`.
2. If the returned bytes do not end in `\n`, return error
   `request_too_large` and close.
3. If the returned bytes are empty (peer closed without writing), return
   silently and close.
4. UTF-8 decode and `json.loads` strictly. On `UnicodeDecodeError` /
   `json.JSONDecodeError`, return error `bad_json`.
5. After writing one response line ending in `\n`, return from the
   handler. The server closes the socket. Any additional bytes the client
   may have written after the first newline are never read (FR-026).

**Rationale**: 64 KiB is enormous compared to the largest legitimate
control request (a `status` response is well under 1 KiB); this limit
exists only to bound memory against malformed input, not as a product
limit. The cap is internal and not a user-tunable setting in MVP.

**Alternatives considered**:

- Custom raw-recv loop with manual newline scan: equivalent behavior with
  more code and more edge cases.

---

## R-007 — Shutdown sequencing

**Decision**: A single `threading.Event` named `shutdown_requested`
coordinates all shutdown paths. Both the `shutdown` API method and the
SIGTERM / SIGINT handlers set the event. Sequence:

1. `shutdown_requested.set()`.
2. Call `server.shutdown()` on the `ThreadingUnixStreamServer` from a
   helper thread (cannot be called from the serving thread).
3. The accept loop returns. The listening socket is closed by
   `server.server_close()`, which runs immediately after.
4. The main thread joins outstanding request-handler threads with a
   2-second per-thread timeout. Threads exceeding the timeout are
   abandoned (`daemon_threads=True` makes this safe at exit).
5. Unlink the socket file, the pid file, and the informational lock-file
   contents, in that order, while still holding `LOCK_EX`.
6. Release the lock by closing the lock file descriptor.
7. Exit `0`.

**Rationale**: Maps directly to the spec's "finish in-flight, refuse new"
clarification. The 2-second per-thread timeout is the safety net for
pathological handlers and is far longer than any legitimate FEAT-002
request takes.

**Alternatives considered**:

- Hard cutoff (close listener and any open connections immediately):
  rejected by clarification Q4.
- Exposing the join timeout as a config knob: out of scope for FEAT-002;
  a 2-second hard-coded value is sufficient given the request shapes
  this feature defines.

---

## R-008 — Signal handling

**Decision**: `signal.signal(SIGTERM, _shutdown_initiator)` and
`signal.signal(SIGINT, _shutdown_initiator)` registered in the daemon
main thread before the accept loop starts. The handler is a tiny function
that calls `shutdown_requested.set()` and dispatches the
`server.shutdown()` call onto a helper thread.

`SIGHUP` is **not** handled in FEAT-002 (no config reload feature yet);
the daemon receives the OS default action. `SIGPIPE` is set to `SIG_IGN`
to prevent client disconnects mid-write from killing the daemon.

**Rationale**: Aligns SIGTERM/Ctrl-C with the API `shutdown` method (FR-022,
clarification Q4). Ignoring SIGPIPE matches the standard server pattern.

---

## R-009 — Daemonization model

**Decision**: `agenttower ensure-daemon` spawns the daemon by calling
`subprocess.Popen([sys.executable, "-m", "agenttower.daemon", "run"], ...)`
with:

- `stdin=subprocess.DEVNULL`,
- `stdout` and `stderr` redirected to the lifecycle log file
  (`<LOGS_DIR>/agenttowerd.log`, opened append, `0600`),
- `start_new_session=True` (calls `setsid()` so the daemon is its own
  process group leader and survives shell exit),
- `close_fds=True`.

The parent (`ensure-daemon`) does **not** double-fork. After spawning, it
polls the socket path with short backoff (10 ms, 50 ms, 100 ms, 200 ms,
…) until either:

- a connect succeeds and a `ping` returns `ok: true` → success, or
- the spawned PID exits → failure (parse the last few lines of the
  lifecycle log into the stderr error message), or
- the 2-second budget (SC-001) elapses → failure with timeout error.

**Rationale**: Classical POSIX double-fork is unnecessary because
`setsid()` already detaches the daemon from the controlling terminal and
the parent does not need to remain a process-group ancestor. This is
materially simpler than double-fork and is the pattern most modern
service supervisors expect for a foreground-supervisable daemon.

The "ping after spawn" handshake is preferable to a pidfile-poll
handshake because it confirms the *socket is serving* (the user's
contract), not just that the daemon process exists.

**Alternatives considered**:

- POSIX double-fork: more boilerplate; the only benefit (immunity to
  controlling-terminal capture) is already provided by `start_new_session`.
- Anonymous pipe ready-signal from child: requires custom code in both
  parent and child for a benefit (faster ready detection) we don't need
  given the tiny startup time.
- systemd unit / launchd plist: out of scope for MVP; constitution does
  not assume an init system.

---

## R-010 — Liveness/ready handshake

**Decision**: Same as R-009: parent polls socket and sends a `ping` until
success or budget exceeded. The daemon's "ready" point is defined as:
lock acquired, socket bound and listening, pid file written, lifecycle
log line `daemon: ready socket=<path> pid=<n>` flushed.

**Rationale**: A successful `ping` round-trip is the strongest possible
proof of readiness — it exercises the exact code path real clients will
use.

---

## R-011 — Permission and ownership enforcement

**Decision**: A single `assert_paths_safe()` helper invoked at daemon
startup (after lock acquisition, before bind) verifies, for each of:

- `STATE_DIR` — must exist, be a directory, mode `& 0o777 == 0o700`,
  `st_uid == os.geteuid()`.
- `LOGS_DIR` — same checks, mode `0700`.
- `<STATE_DIR>/agenttowerd.lock` (post-creation) — file, mode `0600`,
  owned by current uid.
- `<STATE_DIR>/agenttowerd.pid` (post-creation) — file, mode `0600`,
  owned by current uid.
- `<STATE_DIR>/agenttowerd.sock` (post-bind) — socket, mode `0600`,
  owned by current uid.
- `<LOGS_DIR>/agenttowerd.log` (post-creation) — file, mode `0600`,
  owned by current uid.

If any check fails, the daemon: releases the lock, exits non-zero, and
writes a path-specific error to the lifecycle log and stderr (FR-011,
SC-008). If a pre-existing artifact has broader mode, the daemon refuses
rather than chmodding (matches FEAT-001's policy).

**Rationale**: Centralizing the check makes the audit trivial and matches
the constitution's "Local-First Host Control" principle: refuse rather
than silently weaken security.

---

## R-012 — Lifecycle log file

**Decision**: Single append-only file at
`<LOGS_DIR>/agenttowerd.log`, mode `0600`. One line per event in the
form:

```text
<ISO-8601 UTC>\tlevel=<info|warn|error|fatal>\tevent=<short-token>\t<key=value pairs>
```

Events emitted in FEAT-002:

| `event=`            | When                                                   |
| ------------------- | ------------------------------------------------------ |
| `daemon_starting`   | After argv parse, before lock acquisition.             |
| `daemon_ready`      | After bind/listen and pid file write.                  |
| `daemon_recovering` | When stale lifecycle artifacts are unlinked.           |
| `daemon_shutdown`   | After `shutdown_requested.set()`, before listener close. |
| `daemon_exited`     | Last line before `sys.exit`; includes exit code.       |
| `error_fatal`       | Any unrecoverable startup or runtime error.            |

No event/agent/pane/per-request entries appear here in FEAT-002 (FR-027).
Rotation is delegated to the operator; FEAT-002 does not size-cap the
file.

**Rationale**: Tab-separated lines are trivially `awk`-able and grep-able
without forcing a structured-log dependency. Six event tokens cover the
lifecycle without leaking into FEAT-005's audit-log territory.

**Alternatives considered**:

- JSON-Lines: cleaner for programmatic consumers but heavier for human
  tailing during MVP development, where the file is mostly read by a
  human looking at "did the daemon come up cleanly?".

---

## R-013 — `status` response field set

**Decision**: The `status` API method returns the following fixed-shape
result:

```json
{
  "ok": true,
  "result": {
    "alive": true,
    "pid": 12345,
    "start_time_utc": "2026-05-05T12:34:56.789012+00:00",
    "uptime_seconds": 42,
    "socket_path": "/home/.../agenttowerd.sock",
    "state_path": "/home/.../",
    "schema_version": 1,
    "daemon_version": "0.2.0"
  }
}
```

`schema_version` is read once at daemon startup from the FEAT-001
`schema_version` SQLite table and cached for the daemon's lifetime;
FEAT-002 does not poll the DB for schema changes mid-run.
`daemon_version` is `importlib.metadata.version("agenttower")`.

**Rationale**: Maps the FR-016 "at least" list to a concrete schema that
later features (`agenttower config doctor` in FEAT-004, container
discovery in FEAT-003) can rely on without re-clarifying.

---

## R-014 — Error response shape and code vocabulary

**Decision**: Every non-success response has shape:

```json
{
  "ok": false,
  "error": {
    "code": "<machine-readable token>",
    "message": "<human-readable summary>"
  }
}
```

Error codes (closed set in FEAT-002):

| `code`              | Meaning                                                                |
| ------------------- | ---------------------------------------------------------------------- |
| `bad_json`          | Request was not valid JSON or not UTF-8.                               |
| `bad_request`       | Request was JSON but missing/invalid `method` field, or extra params.  |
| `unknown_method`    | `method` was not `ping`, `status`, or `shutdown`.                      |
| `request_too_large` | Request line exceeded `MAX_REQUEST_BYTES`.                             |
| `internal_error`    | Unexpected server-side exception; daemon stays alive (FR-021, SC-005). |

**Rationale**: A small closed vocabulary lets clients (CLI, future relay)
match on `code` without parsing `message`. New codes added by later
features are additive.

---

## R-015 — Daemon CLI surface

**Decision**: `agenttowerd` gains a `run` subcommand. The full FEAT-002
daemon CLI is:

```bash
agenttowerd --version    # FEAT-001 contract, unchanged
agenttowerd run          # NEW: enter daemon mode, never returns until shutdown
```

Any other invocation in FEAT-002 returns the argparse usage to stderr and
exits non-zero. No `agenttowerd config`, `agenttowerd status`, etc., in
this feature — those go through the user CLI (`agenttower`).

**Rationale**: Keeps the daemon binary minimal; user-visible operations
flow through `agenttower` and use the socket. `agenttowerd run` exists
solely so `ensure-daemon` has something explicit to spawn.

---

## R-016 — User CLI surface (FEAT-002 additions)

**Decision**: `agenttower` gains three subcommands:

```bash
agenttower ensure-daemon    # idempotent start
agenttower status           # query daemon over socket
agenttower stop-daemon      # send shutdown over socket
```

All three accept `--json` to switch from human-readable text output to a
single line of JSON on stdout (matching the constitution's
"human-readable defaults and structured output where it materially helps
automation"). Without `--json`, output is a small, fixed set of
human-friendly lines with stable keys for `grep`-based scripts.

**Rationale**: Two-mode output is what FEAT-001 already uses (e.g.
`config paths` is `KEY=value` for trivial scripting); FEAT-002 picks the
same dual-mode pattern.

---

## R-017 — Exit code map for the user CLI

**Decision**: FEAT-002 introduces these exit codes:

| Code | Meaning                                                                  | Used by                              |
| ---- | ------------------------------------------------------------------------ | ------------------------------------ |
| `0`  | Success.                                                                 | All three commands.                  |
| `1`  | Pre-flight failure (FEAT-001 not initialized, unsafe paths, etc.).       | `ensure-daemon`.                     |
| `2`  | Daemon unavailable (no socket, connect refused, response timeout).       | `status`, `stop-daemon`.             |
| `3`  | Daemon returned a structured error.                                      | `status`, `stop-daemon`.             |
| `4`  | Internal CLI error (unexpected exception).                               | All three.                           |

`stop-daemon` against an absent daemon returns exit `2` with an
"actionable daemon-unavailable message" (US4 acceptance scenario 3 +
clarification Q1).

**Rationale**: Distinguishes "the daemon told me no" (exit 3) from "I
could not reach the daemon" (exit 2), which is the distinction
container-side scripts in FEAT-003 will need.

---

## Summary table of resolved unknowns

| Topic                                       | Resolved by | Concrete choice                                                  |
| ------------------------------------------- | ----------- | ---------------------------------------------------------------- |
| Cross-process lock                          | R-001       | `fcntl.flock(LOCK_EX)` on `agenttowerd.lock`.                    |
| Stale-pid detection                         | R-002       | Lock is authority; pid file is informational.                    |
| Socket bind + permissions                   | R-003       | `umask(0o077)` then `bind`, post-stat verify `0600`/uid.         |
| Stale socket classification                 | R-004       | Unlink only if `S_ISSOCK` and we hold the lock.                  |
| I/O model                                   | R-005       | `ThreadingUnixStreamServer`, daemon threads.                     |
| JSON framing + size limit                   | R-006       | `readline(64 KiB)`, strict UTF-8 + `json.loads`.                 |
| Shutdown sequencing                         | R-007       | `shutdown_requested` event, drain join 2 s/thread.               |
| Signal handling                             | R-008       | SIGTERM/SIGINT → shutdown path; SIGPIPE ignored.                 |
| Daemonization                               | R-009       | `Popen` with `start_new_session=True`; no double-fork.           |
| Ready handshake                             | R-010       | Parent polls socket and `ping`s until budget or PID exits.       |
| Permission enforcement                      | R-011       | `assert_paths_safe()` post-lock, pre-bind.                       |
| Lifecycle log                               | R-012       | TSV at `<LOGS_DIR>/agenttowerd.log`, six event tokens.           |
| `status` field set                          | R-013       | Fixed shape with pid, uptime, paths, schema_version, version.    |
| Error response shape                        | R-014       | `{ok:false, error:{code,message}}`, five-token closed code set.  |
| Daemon CLI surface                          | R-015       | `agenttowerd run` (new) + existing `--version`.                  |
| User CLI surface                            | R-016       | `ensure-daemon`, `status`, `stop-daemon`, all with `--json`.     |
| Exit code map                               | R-017       | 0 success / 1 pre-flight / 2 unavailable / 3 daemon-error / 4 internal. |

No remaining `NEEDS CLARIFICATION` items.
