# Contract: Socket API additions (FEAT-003)

**Branch**: `003-bench-container-discovery` | **Date**: 2026-05-05

This contract documents the two new methods FEAT-003 adds to the
existing FEAT-002 local control socket API. It extends, but does
not replace, `specs/002-host-daemon-socket-api/contracts/socket-api.md`.
Everything in that document — transport, request/response envelope,
validation order, the `ping`/`status`/`shutdown` semantics, and the
existing closed-error-code set — remains in force unchanged
(FR-022).

The connection model is still **one request per connection**. Both
new methods are still synchronous (the daemon writes the response
before closing the connection).

---

## 1. Request envelope changes

The set of accepted `method` strings expands from
`{"ping", "status", "shutdown"}` to:

```text
{"ping", "status", "shutdown", "scan_containers", "list_containers"}
```

Any other `method` value still returns `unknown_method` per the
existing FEAT-002 validation order step 5.

`params` validation rules are unchanged: must be absent or an
object; unknown keys ignored.

---

## 2. Closed error code set (extended)

FEAT-002's five codes remain. FEAT-003 adds six:

| `code`                       | When emitted                                                                              | Daemon stays alive? |
| ---------------------------- | ----------------------------------------------------------------------------------------- | ------------------- |
| `bad_json`                   | (FEAT-002) bytes are not UTF-8 JSON.                                                      | Yes |
| `bad_request`                | (FEAT-002) envelope or `params` invalid.                                                  | Yes |
| `unknown_method`             | (FEAT-002) `method` not in the dispatch table.                                            | Yes |
| `request_too_large`          | (FEAT-002) line over 64 KiB.                                                              | Yes |
| `internal_error`             | (FEAT-002) unhandled daemon-side exception.                                               | Yes |
| `config_invalid`             | NEW — `[containers] name_contains` is missing-when-required, empty, non-list, or contains non-string / blank elements (FR-006). | Yes |
| `docker_unavailable`         | NEW — `docker` binary not on PATH or not executable.                                      | Yes |
| `docker_permission_denied`   | NEW — Docker reported permission denied connecting to the daemon socket.                  | Yes |
| `docker_timeout`             | NEW — `docker ps` or any `docker inspect` exceeded the 5-second per-call budget (FR-024). | Yes |
| `docker_failed`              | NEW — `docker ps` exited non-zero, OR at least one `docker inspect` returned non-zero against a matching candidate. | Yes |
| `docker_malformed`           | NEW — `docker ps` row could not be parsed, or `docker inspect` JSON shape is invalid.     | Yes |

Note the asymmetry: a `docker_*` code in the **response** envelope
means the *whole scan* could not produce a useful result. A scan
that succeeded but lost some `docker inspect` calls returns
`ok: true` with `result.status = "degraded"` and per-container
detail in `result.error_details` — `result.error_code` carries the
representative code (`docker_failed`, `docker_timeout`, etc.) but
the response envelope's `ok` field is `true`. See §3.2 below.

---

## 3. Method `scan_containers` (C-API-201)

### 3.1 Request

```json
{"method":"scan_containers"}
```

`params` is optional and currently has no defined keys. Unknown
keys are ignored (forward-compatibility).

### 3.2 Success response (healthy scan)

```json
{
  "ok": true,
  "result": {
    "scan_id": "f3c5e1ad-2e6a-4f7e-9a02-7d2b6a1d4a5f",
    "started_at": "2026-05-05T18:01:34.512345+00:00",
    "completed_at": "2026-05-05T18:01:34.692118+00:00",
    "status": "ok",
    "matched_count": 2,
    "inactive_reconciled_count": 0,
    "ignored_count": 7,
    "error_code": null,
    "error_message": null,
    "error_details": []
  }
}
```

### 3.3 Success response (degraded but partial)

The envelope is still `ok: true`; the *scan completed* in the sense
that it produced a result row. `result.status = "degraded"` is the
machine-checkable signal.

```json
{
  "ok": true,
  "result": {
    "scan_id": "...",
    "started_at": "...",
    "completed_at": "...",
    "status": "degraded",
    "matched_count": 1,
    "inactive_reconciled_count": 0,
    "ignored_count": 4,
    "error_code": "docker_failed",
    "error_message": "1 of 2 candidates failed inspect",
    "error_details": [
      {
        "container_id": "abc123...",
        "code": "docker_failed",
        "message": "docker inspect exited 1: Error: No such object: abc123"
      }
    ]
  }
}
```

### 3.4 Error response (whole-scan failure)

When the scan could not produce a result row at all (Docker
binary missing, permission denied with no successful `docker ps`,
or the matching config is invalid), the envelope is `ok: false`:

```json
{
  "ok": false,
  "error": {
    "code": "docker_unavailable",
    "message": "docker binary not found on PATH"
  }
}
```

In the whole-scan-failure path the daemon still writes a
`container_scans` row with `status = "degraded"` (auditable
history), still appends a JSONL event, and still updates no
`containers` rows. The new scan_id is recoverable from the
lifecycle log but is not returned to the caller in this envelope
shape (the caller already knows the scan failed).

### 3.5 Semantics

- MUST acquire the daemon-scoped scan mutex; concurrent callers
  block until it is available (FR-023).
- Mutex hold time is bounded by the per-Docker-subprocess timeout
  (FR-024) plus SQLite write time. Worst-case mutex hold for a
  fully-hung Docker is `~5 seconds * (1 + N matching candidates)`
  with the per-container fallback path.
- MUST persist exactly one row to `container_scans` and zero or
  more upserts/touch-only/inactivate writes to `containers` in a
  single SQLite transaction.
- Healthy scans MUST NOT write to `events.jsonl`; degraded scans
  MUST write exactly one record there (event type
  `container_scan_degraded`).
- Latency budget: SC-004 (3 s when running against the
  `FakeDockerAdapter`).

### 3.6 Errors

`bad_json`, `bad_request`, `internal_error` (FEAT-002 path);
`config_invalid`, `docker_unavailable`, `docker_permission_denied`,
`docker_timeout`, `docker_failed`, `docker_malformed` (this
feature, whole-scan-failure path).

### 3.7 Forward-compatibility

Future features may add fields under `result`. Clients MUST tolerate
unknown keys.

---

## 4. Method `list_containers` (C-API-202)

### 4.1 Request

```json
{"method":"list_containers","params":{"active_only":false}}
```

| `params` field   | Type    | Default  | Notes                                            |
| ---------------- | ------- | -------- | ------------------------------------------------ |
| `active_only`    | boolean | `false`  | When `true`, only rows with `active = 1` are returned. |

`active_only` is the only defined param key; unknown keys are
ignored.

### 4.2 Success response

```json
{
  "ok": true,
  "result": {
    "filter": "all",
    "containers": [
      {
        "id": "f3c5e1ad...",
        "name": "py-bench",
        "image": "ghcr.io/opensoft/py-bench:latest",
        "status": "running",
        "labels": {"opensoft.bench": "true"},
        "mounts": [
          {"source": "/home/user/proj", "target": "/workspace", "type": "bind", "mode": "rw", "rw": true}
        ],
        "active": true,
        "first_seen_at": "2026-05-05T17:55:01.123456+00:00",
        "last_scanned_at": "2026-05-05T18:01:34.692118+00:00",
        "config_user": "user",
        "working_dir": "/workspace"
      }
    ]
  }
}
```

`result.filter` is `"all"` when `params.active_only` is unset/false
and `"active_only"` when `true`. The field is informational and
self-documents the response.

`result.containers` is ordered by:
`active DESC, last_scanned_at DESC, container_id ASC` (R-011).

Empty state is a valid response: `result.containers = []`.

### 4.3 Semantics

- MUST be a read-only SQLite SELECT under a short transaction.
- MUST NOT block on the scan mutex (R-005).
- MUST decode `labels_json` and `mounts_json` to JSON
  objects/arrays before emitting the response.
- Latency budget: < 100 ms for ≤ 100 rows on a normally-loaded host.

### 4.4 Errors

`bad_json`, `bad_request`, `internal_error`. None of the
`docker_*` or `config_invalid` codes can be emitted by this method
because it does not touch Docker or the matching config.

---

## 5. Out-of-scope (FEAT-003)

The following methods, params, fields, and behaviors remain
**not** part of FEAT-003 and continue to return `unknown_method`:

- `register_agent`, `list_agents`, `set_role`, `set_capability`
  (FEAT-006).
- `scan_panes`, `list_panes` (FEAT-004).
- `events`, `events_follow` (FEAT-008).
- `send_input`, `route` (FEAT-009).

A future feature SHOULD NOT redefine the `result` shape of either
new method; it MAY add fields. Clients MUST tolerate unknown
result-level keys.
