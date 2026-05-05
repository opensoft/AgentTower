# Phase 1 Data Model: Host Daemon Lifecycle and Unix Socket API

**Branch**: `002-host-daemon-socket-api` | **Date**: 2026-05-05

FEAT-002 is a process-and-socket feature, not a database feature. It adds
**no SQLite tables** and **no JSONL event records** beyond what FEAT-001
established. The "data model" here is therefore primarily a filesystem
artifact set, an in-memory daemon-state machine, and a wire-format
schema. Each is enumerated below.

The full SQLite registry (`schema_version` table) and the FEAT-001 path
contract are dependencies — see
`specs/001-package-state-foundation/data-model.md`. FEAT-002 reads
`schema_version.version` once at daemon start (R-013) and otherwise does
not touch the database.

---

## 1. Filesystem entities

All four artifacts live under `<STATE_DIR>` resolved by FEAT-001's
`Paths` resolver. The lifecycle log lives under `<LOGS_DIR>`.

| Entity (spec)        | Path                                | Kind         | Created by               | Removed by                              | Mode   |
| -------------------- | ----------------------------------- | ------------ | ------------------------ | --------------------------------------- | ------ |
| Lifecycle Lock       | `<STATE_DIR>/agenttowerd.lock`      | regular file | daemon `run` (open)      | daemon `run` (close on exit)            | `0600` |
| Pid File             | `<STATE_DIR>/agenttowerd.pid`       | regular file | daemon `run` (post-bind) | daemon `run` (clean shutdown) or stale-recovery | `0600` |
| Socket Endpoint      | `<STATE_DIR>/agenttowerd.sock`      | unix socket  | daemon `run` (`bind`)    | daemon `run` (clean shutdown) or stale-recovery | `0600` |
| Lifecycle Log        | `<LOGS_DIR>/agenttowerd.log`        | regular file | daemon `run` (open append) | never (operator-rotated, see R-012)   | `0600` |

### 1.1 Lifecycle Lock

- Acquired with `fcntl.flock(fd, LOCK_EX)` (R-001) before any other
  startup work.
- The exclusive lock is **the authority** for "live daemon for this state
  directory" (FR-006).
- Content is `pid=<int>\n`, written informationally after successful
  bind. The lock semantics do not depend on the bytes.
- The kernel releases the lock automatically when the daemon process
  exits, whether by clean shutdown, signal, or crash.
- Stale lock content (a pid number from a prior crashed daemon) is
  ignored by the next `ensure-daemon`; the lock acquisition succeeds
  *because* the kernel released the lock when the prior process died.

### 1.2 Pid File

- Written *after* the daemon binds the socket and starts its accept
  loop (post-ready), so its presence implies a previously-ready daemon.
- Contents: `<pid>\n` (decimal).
- Treated as informational metadata only, never as a liveness oracle on
  its own (R-002).

### 1.3 Socket Endpoint

- Created by `socket.bind` after `umask(0o077)` is applied (R-003).
- Verified post-bind: `mode & 0o777 == 0o600`, `st_uid == os.geteuid()`.
- Refused if a pre-existing path is anything other than a socket file or
  has wrong owner (R-004).

### 1.4 Lifecycle Log

- Append-only, line-oriented, TSV (R-012).
- Six event tokens: `daemon_starting`, `daemon_ready`,
  `daemon_recovering`, `daemon_shutdown`, `daemon_exited`, `error_fatal`.
- No event/agent/pane/per-request entries (FR-027).

### 1.5 Required pre-existing FEAT-001 artifacts

These exist before FEAT-002 starts and are read but not modified:

| FEAT-001 entity     | Used by FEAT-002 for                                          |
| ------------------- | ------------------------------------------------------------- |
| `CONFIG_FILE`       | (Loaded by daemon at startup; only verifies presence in MVP.) |
| `STATE_DB`          | One read of `schema_version.version` at daemon start (R-013). |
| `LOGS_DIR`          | Parent for the lifecycle log file.                            |
| `STATE_DIR` (parent of `STATE_DB`/`SOCKET`/etc.) | Parent for lock, pid, socket files. |

If any required artifact is missing or has unsafe modes/ownership,
`ensure-daemon` refuses with a path-specific error before spawning the
daemon (FR-003, FR-011, SC-008).

---

## 2. In-memory daemon state machine

The `agenttowerd run` process moves through these states. Each transition
emits exactly one lifecycle log event (R-012).

```text
┌─────────────┐  argv parsed
│  STARTING   │  (state = "starting")
└─────┬───────┘
      │ acquire lock,
      │ verify paths,
      │ classify stale artifacts
      ▼
┌─────────────┐  (no live daemon owned the lock)
│ RECOVERING  │  (state = "recovering"; emitted only if any stale
└─────┬───────┘   socket/pid/lock content was unlinked)
      │ bind socket, write pid file, listen
      ▼
┌─────────────┐
│   READY     │  (state = "ready"; serves requests)
└─────┬───────┘
      │ shutdown method received OR SIGTERM/SIGINT received
      ▼
┌─────────────┐
│ SHUTTING_DOWN │  (state = "shutting_down")
└─────┬───────┘
      │ stop accepting new connections,
      │ join in-flight handlers (≤ 2 s each),
      │ unlink owned artifacts,
      │ release lock
      ▼
┌─────────────┐
│   EXITED    │  process exits 0 (or non-zero on fatal-error path)
└─────────────┘
```

Fatal-error path: from any state, an unrecoverable startup error
(permission failure, lock contention with a live daemon, stale-but-
unsafe artifact, etc.) emits `error_fatal`, releases anything held, and
exits non-zero. No `READY` state is reached.

### 2.1 In-memory fields per running daemon

| Field                     | Type                  | Source                                              |
| ------------------------- | --------------------- | --------------------------------------------------- |
| `pid`                     | `int`                 | `os.getpid()` at startup.                           |
| `start_time_utc`          | `datetime` (UTC, aware) | `datetime.now(UTC)` after lock acquired.        |
| `socket_path`             | `pathlib.Path`        | FEAT-001 `Paths.socket`.                            |
| `state_path`              | `pathlib.Path`        | FEAT-001 `Paths.state_db.parent`.                   |
| `schema_version`          | `int`                 | One-shot read of FEAT-001 `schema_version.version`. |
| `daemon_version`          | `str`                 | `importlib.metadata.version("agenttower")`.         |
| `shutdown_requested`      | `threading.Event`     | Initially clear; set by API or signal handler.      |
| `lock_fd`                 | `int`                 | OS-level fd holding `flock(LOCK_EX)`.               |
| `server`                  | `ThreadingUnixStreamServer` | Created after permission verification.        |
| `lifecycle_log`           | `io.TextIOBase`       | `open(LOG_PATH, "a", buffering=1)`, mode 0600.      |

### 2.2 Uptime semantics

`uptime_seconds` returned by `status` (FR-016, R-013) is computed as
`int((datetime.now(UTC) - start_time_utc).total_seconds())`.
A backwards system-clock jump can yield a negative or shrinking value;
the spec's edge case "system clock changes while uptime is reported"
is handled by clamping to `0` if the delta is negative. This keeps
clients from seeing impossible numbers without inventing a monotonic
clock surface in MVP.

---

## 3. Wire-format schema (newline-delimited JSON)

The complete protocol contract lives in
`contracts/socket-api.md`. This section is the data-model summary.

### 3.1 Request envelope

Every request is **one** UTF-8 JSON object on **one** line, ≤ 64 KiB
including the trailing `\n` (R-006).

```json
{
  "method": "<ping|status|shutdown>",
  "params": { ... }
}
```

| Field    | Type                          | Required | Notes                                                    |
| -------- | ----------------------------- | -------- | -------------------------------------------------------- |
| `method` | string                        | yes      | Closed set: `ping`, `status`, `shutdown`.                |
| `params` | object                        | no       | All FEAT-002 methods accept the empty object or omitted. |

Unknown top-level keys are ignored. Unknown keys inside `params` are
ignored (forward-compatibility for FEAT-003+).

### 3.2 Response envelope

```json
{ "ok": true,  "result": { ... } }
```

or

```json
{ "ok": false, "error": { "code": "<token>", "message": "<string>" } }
```

| Field      | Type     | When required             | Notes                          |
| ---------- | -------- | ------------------------- | ------------------------------ |
| `ok`       | boolean  | always                    | `true` ↔ result, `false` ↔ error. |
| `result`   | object   | when `ok == true`         | Method-specific shape.         |
| `error`    | object   | when `ok == false`        | `{code, message}`.             |

### 3.3 Method-specific result shapes

| Method     | `result` shape on success                             | Error codes that can apply              |
| ---------- | ----------------------------------------------------- | --------------------------------------- |
| `ping`     | `{}` (empty object)                                   | `bad_json`, `bad_request`, `internal_error`. |
| `status`   | See R-013 / `contracts/socket-api.md` §3.             | `bad_json`, `bad_request`, `internal_error`. |
| `shutdown` | `{ "shutting_down": true }`                           | `bad_json`, `bad_request`, `internal_error`. |

The full closed code vocabulary is `{bad_json, bad_request,
unknown_method, request_too_large, internal_error}` (R-014).

### 3.4 Connection lifecycle

Per FR-026 / clarification Q2:

1. Client connects.
2. Daemon's handler reads exactly one line ending in `\n`.
3. Daemon writes exactly one line ending in `\n`.
4. Daemon closes the connection.
5. Any further bytes the client may have written after step 2 are never
   read.

A client that needs a second request opens a new connection. A client
that closes before reading the response sees no further effect on the
daemon (the response write may raise `BrokenPipeError`; the daemon
suppresses it and continues — SIGPIPE is ignored, R-008).

---

## 4. Lifecycle log record shape (informational)

Each lifecycle log line:

```text
<ts>\tlevel=<info|warn|error|fatal>\tevent=<token>\t<key=value pairs separated by tabs>
```

Where `<ts>` is ISO-8601 UTC microsecond, e.g.
`2026-05-05T12:34:56.789012+00:00`. Examples:

```text
2026-05-05T12:34:56.789012+00:00	level=info	event=daemon_starting	pid=12345	state_dir=/home/user/.local/state/opensoft/agenttower
2026-05-05T12:34:56.812445+00:00	level=info	event=daemon_recovering	unlinked=/home/user/.local/state/opensoft/agenttower/agenttowerd.sock	reason=stale_socket
2026-05-05T12:34:56.834102+00:00	level=info	event=daemon_ready	socket=/home/user/.local/state/opensoft/agenttower/agenttowerd.sock	pid=12345
2026-05-05T12:35:42.501007+00:00	level=info	event=daemon_shutdown	trigger=api
2026-05-05T12:35:42.612331+00:00	level=info	event=daemon_exited	exit_code=0
```

Tab-separated and grep-friendly; no third-party logging dependency
required.

---

## 5. Relationships and lifecycle summary

```text
ensure-daemon (parent)
   ├── verify FEAT-001 init artifacts
   ├── verify host-user-only modes on STATE_DIR / LOGS_DIR
   ├── spawn agenttowerd run  (Popen, start_new_session=True)
   │      │
   │      ▼
   │   STARTING → acquire flock → verify paths
   │      │              │
   │      │              └── if held: parent's poll will detect live daemon
   │      │                  via ping; ensure-daemon exits 0 (FR-007 path).
   │      │
   │      ├── classify and unlink stale lifecycle artifacts (RECOVERING)
   │      ├── bind socket (umask 0o077), verify mode 0600/uid
   │      ├── write pid file
   │      └── enter accept loop  → READY
   │
   └── poll socket + send ping until success or budget elapses
       (success → exit 0; budget exceeded or child exited → exit 1)
```

Shutdown:

```text
shutdown method   ─┐
SIGTERM           ─┼─→ shutdown_requested.set()
SIGINT            ─┘
                       │
                       ▼
                   server.shutdown()  (stop accepting new connections)
                       │
                       ▼
                   join in-flight handlers (≤ 2s each)
                       │
                       ▼
                   unlink socket, pid file, lock contents
                       │
                       ▼
                   close lock fd → kernel releases lock
                       │
                       ▼
                   exit 0  (next ensure-daemon can start cleanly)
```
