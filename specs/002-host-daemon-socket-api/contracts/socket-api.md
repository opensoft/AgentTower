# Contract: Local Control Socket API (FEAT-002)

**Branch**: `002-host-daemon-socket-api` | **Date**: 2026-05-05

This contract defines the wire format and method semantics for the local
Unix socket control API exposed by `agenttowerd`. It is reachable only
through `<STATE_DIR>/agenttowerd.sock` and is not exposed on any network
listener (FR-010, SC-007).

The connection model is **one request per connection** (FR-026,
clarification Q2): the daemon reads one newline-delimited JSON request,
writes one newline-delimited JSON response, then closes the connection.

---

## 1. Transport

| Property                | Value                                                          |
| ----------------------- | -------------------------------------------------------------- |
| Address family          | `AF_UNIX`.                                                     |
| Socket type             | `SOCK_STREAM`.                                                 |
| Path                    | `<STATE_DIR>/agenttowerd.sock` (FEAT-001 `Paths.socket`).      |
| File mode               | `0600`, owned by `os.geteuid()` (FR-011).                      |
| Max request size        | 64 KiB per line, including trailing `\n` (R-006).              |
| Encoding                | UTF-8.                                                         |
| Framing                 | Newline-delimited (`\n`); no length prefix.                    |
| Concurrency             | Threaded server, daemon threads (R-005).                       |

Connection lifecycle (FR-026):

1. Client opens an `AF_UNIX SOCK_STREAM` connection to the socket path.
2. Client writes one UTF-8 line ending in `\n` containing the request
   JSON object.
3. Daemon reads at most 64 KiB up to and including the first `\n`.
4. Daemon writes one UTF-8 line ending in `\n` containing the response
   JSON object.
5. Daemon closes the connection.

Bytes the client writes after step 2 are never read. A client wanting a
second request opens a new connection.

---

## 2. Request envelope (C-API-001)

```json
{ "method": "<token>", "params": { ... } }
```

| Field    | Type    | Required | Notes                                                                     |
| -------- | ------- | -------- | ------------------------------------------------------------------------- |
| `method` | string  | yes      | One of `"ping"`, `"status"`, `"shutdown"` in FEAT-002.                    |
| `params` | object  | no       | All FEAT-002 methods accept an empty/omitted `params`. Unknown keys ignored. |

Forward-compatibility:

- Top-level keys other than `method` and `params` MUST be ignored.
- Unknown keys inside `params` MUST be ignored.
- Future features may add methods; clients MUST surface
  `unknown_method` errors verbatim rather than guessing.

### Validation order (R-014)

1. UTF-8 decode the bytes. On failure → `bad_json`.
2. `json.loads`. On failure → `bad_json`.
3. Top-level value MUST be a JSON object. Otherwise → `bad_request`.
4. `method` MUST be a non-empty string. Otherwise → `bad_request`.
5. `method` MUST be one of `ping`, `status`, `shutdown`. Otherwise →
   `unknown_method`.
6. `params` MUST be absent or an object. Otherwise → `bad_request`.
7. Method-specific dispatch.

---

## 3. Response envelope (C-API-002)

### Success

```json
{ "ok": true, "result": { ... } }
```

### Error

```json
{ "ok": false, "error": { "code": "<token>", "message": "<string>" } }
```

| Field            | Type    | Always present | Notes                          |
| ---------------- | ------- | -------------- | ------------------------------ |
| `ok`             | boolean | yes            | `true` ↔ `result`, `false` ↔ `error`. |
| `result`         | object  | when `ok`      | Method-specific.               |
| `error.code`     | string  | when not `ok`  | From the closed code set.      |
| `error.message`  | string  | when not `ok`  | Human-readable; not parsed.    |

Closed code set in FEAT-002 (R-014):

| `code`              | Meaning                                                       |
| ------------------- | ------------------------------------------------------------- |
| `bad_json`          | Bytes were not valid UTF-8 JSON.                              |
| `bad_request`       | JSON parsed but the envelope or `params` is invalid.          |
| `unknown_method`    | `method` is not one of FEAT-002's three.                      |
| `request_too_large` | Line exceeded `MAX_REQUEST_BYTES = 65536`.                    |
| `internal_error`    | Unexpected daemon-side exception. Daemon stays alive (FR-021). |

---

## 4. Method `ping` (C-API-003)

### Request

```json
{"method":"ping"}
```

### Success response

```json
{"ok":true,"result":{}}
```

### Semantics

- MUST NOT mutate any durable state (FR-015).
- MUST NOT touch the SQLite registry, the events file, the lifecycle
  log (no `daemon_*` event for pings), or any FEAT-001 path beyond what
  is already mapped in memory.
- Latency budget: response within 1 s on a normally-loaded host
  (subset of SC-003).

### Errors

`bad_json`, `bad_request`, `internal_error`.

---

## 5. Method `status` (C-API-004)

### Request

```json
{"method":"status"}
```

### Success response

```json
{
  "ok": true,
  "result": {
    "alive": true,
    "pid": 12345,
    "start_time_utc": "2026-05-05T12:34:56.789012+00:00",
    "uptime_seconds": 42,
    "socket_path": "/home/user/.local/state/opensoft/agenttower/agenttowerd.sock",
    "state_path": "/home/user/.local/state/opensoft/agenttower/",
    "schema_version": 1,
    "daemon_version": "0.2.0"
  }
}
```

### Field semantics (FR-016, R-013)

| Field            | Type     | Source                                                              |
| ---------------- | -------- | ------------------------------------------------------------------- |
| `alive`          | boolean  | Always `true` for any successful response (the daemon is answering). |
| `pid`            | integer  | `os.getpid()` of the daemon at startup.                             |
| `start_time_utc` | string   | ISO-8601 with offset, microsecond precision, UTC.                   |
| `uptime_seconds` | integer  | `int((now - start).total_seconds())`, clamped to 0 on backwards clock jump. |
| `socket_path`    | string   | Absolute path of the bound socket.                                  |
| `state_path`     | string   | Absolute path of `STATE_DIR` (parent of socket and registry).       |
| `schema_version` | integer  | Cached from `schema_version.version` at daemon startup.             |
| `daemon_version` | string   | `importlib.metadata.version("agenttower")`.                         |

Forward-compatibility: future features MAY add fields under `result`.
Clients MUST tolerate unknown keys.

### Semantics

- MUST NOT mutate durable state.
- The cached `schema_version` is **not** re-read mid-run; restarting the
  daemon picks up schema changes (relevant for FEAT-006 migrations).
- Latency budget: SC-003 (1 s).

### Errors

`bad_json`, `bad_request`, `internal_error`.

---

## 6. Method `shutdown` (C-API-005)

### Request

```json
{"method":"shutdown"}
```

### Success response

```json
{"ok":true,"result":{"shutting_down":true}}
```

The daemon writes the response **before** closing the listener so that
the requesting client sees a clean ack. After the response is flushed,
the daemon enters the shutdown sequence (R-007):

1. Stop accepting new connections.
2. Join in-flight handler threads (≤ 2 s each).
3. Unlink the socket file, pid file, and lock-file contents.
4. Close the lock fd (kernel releases the lock).
5. Process exits `0`.

### Semantics (FR-017, clarification Q4)

- MUST stop accepting **new** connections immediately after the response
  is flushed.
- MUST complete the response of any request that was already accepted
  on an existing connection before exiting.
- MUST remove owned lifecycle artifacts (socket file, pid file, lock
  contents).
- A subsequent `agenttower ensure-daemon` MUST succeed without manual
  cleanup (SC-006).

### Errors

`bad_json`, `bad_request`, `internal_error`.

---

## 7. Edge case handling (FR-021, SC-005)

| Scenario                                                          | Daemon response                                  | Daemon stays alive? |
| ----------------------------------------------------------------- | ------------------------------------------------ | ------------------- |
| Empty input (peer closed without sending bytes)                   | No response written, connection closed.          | Yes.                |
| Bytes that are not valid UTF-8                                    | `error.code = "bad_json"`.                       | Yes.                |
| Line larger than 64 KiB without `\n`                              | `error.code = "request_too_large"`.              | Yes.                |
| Valid UTF-8 but not parseable JSON                                | `error.code = "bad_json"`.                       | Yes.                |
| JSON parses to a non-object (array, scalar)                       | `error.code = "bad_request"`.                    | Yes.                |
| `method` missing or not a string                                  | `error.code = "bad_request"`.                    | Yes.                |
| `method` is a string not in `{ping,status,shutdown}`              | `error.code = "unknown_method"`.                 | Yes.                |
| `params` present but not an object                                | `error.code = "bad_request"`.                    | Yes.                |
| Extra bytes after the first newline on the same connection        | First request's response is sent, connection is closed, extras never read. | Yes. |
| Client closes mid-write                                           | `BrokenPipeError` is suppressed; SIGPIPE ignored. | Yes.                |
| Unexpected daemon-side exception in handler                       | `error.code = "internal_error"`.                 | Yes (FR-021).       |

---

## 8. Out of scope (FEAT-002)

The following methods, params, fields, and behaviors are **not** part of
FEAT-002 and MUST return `unknown_method` if requested:

- `register_agent`, `list_agents`, `set_role`, `set_capability` (FEAT-005+).
- `list_panes`, `list_containers` (FEAT-003+).
- `events`, `events_follow` (FEAT-007+).
- `send_input`, `route` (FEAT-009+).

This contract intentionally exposes only the three methods spelled out
in FR-013. Adding more methods is a later-feature concern; FEAT-002
provides the framing and dispatch table they will plug into.
