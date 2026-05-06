# Contract: Socket API additions (FEAT-004)

**Branch**: `004-container-tmux-pane-discovery` | **Date**: 2026-05-06

This contract documents the two new methods FEAT-004 adds to the
local control socket API. It extends, but does not replace,
`specs/002-host-daemon-socket-api/contracts/socket-api.md` and
`specs/003-bench-container-discovery/contracts/socket-api.md`.
Everything in those documents — transport, request/response
envelope, validation order, the
`ping`/`status`/`shutdown`/`scan_containers`/`list_containers`
semantics, the existing closed-error-code set, and the FEAT-002
socket-file authorization (`0600`, host user only) — remains in
force unchanged (FR-030, FR-031).

The connection model is still **one request per connection**. Both
new methods are still synchronous (the daemon writes the response
before closing the connection). FEAT-002's 64 KiB request-line cap
remains a request-only cap; FEAT-004 introduces no response-size
error code (R-018).

---

## 1. Request envelope changes

The set of accepted `method` strings expands from FEAT-003's
`{"ping", "status", "shutdown", "scan_containers", "list_containers"}`
to:

```text
{"ping", "status", "shutdown", "scan_containers", "list_containers",
 "scan_panes", "list_panes"}
```

Any other `method` value still returns `unknown_method` per the
existing FEAT-002 validation order step 5.

`params` validation rules are unchanged: must be absent or an
object; unknown keys ignored (forward-compatibility).

The `agenttower status` response continues to include
`schema_version`. After FEAT-004 lands, the daemon reports
`schema_version: 3` (was `2` under FEAT-003); FEAT-002 already
documents `schema_version` as forward-compatible so existing
clients tolerate the bump (data-model §7).

---

## 2. Closed error code set (extended)

FEAT-002's five codes plus FEAT-003's six codes remain. FEAT-004
adds seven additional codes (R-011):

| `code`                       | When emitted                                                                              | Daemon stays alive? |
| ---------------------------- | ----------------------------------------------------------------------------------------- | ------------------- |
| `bad_json`                   | (FEAT-002) bytes are not UTF-8 JSON.                                                      | Yes |
| `bad_request`                | (FEAT-002) envelope or `params` invalid.                                                  | Yes |
| `unknown_method`             | (FEAT-002) `method` not in the dispatch table.                                            | Yes |
| `request_too_large`          | (FEAT-002) line over 64 KiB.                                                              | Yes |
| `internal_error`             | (FEAT-002) unhandled daemon-side exception (incl. SQLite scan-tx rollback per FR-024).    | Yes |
| `config_invalid`             | (FEAT-003) `[containers]` matching config invalid (FEAT-004 does not emit this).          | Yes |
| `docker_unavailable`         | (FEAT-003) `docker` binary not on PATH or not executable. FEAT-004 reuses (FR-022).       | Yes |
| `docker_permission_denied`   | (FEAT-003) Docker reported permission denied connecting to its socket.                    | Yes |
| `docker_timeout`             | (FEAT-003) `docker ps` / `docker inspect` exceeded the 5-second per-call budget.          | Yes |
| `docker_failed`              | (FEAT-003) `docker ps` exited non-zero, or one or more `docker inspect` calls failed.     | Yes |
| `docker_malformed`           | (FEAT-003) `docker ps` row could not be parsed, or `docker inspect` JSON shape invalid.   | Yes |
| `tmux_unavailable`           | NEW — one container has no `tmux` binary on its PATH.                                     | Yes |
| `tmux_no_server`             | NEW — `tmux list-panes` reported "no server running" for the targeted socket.             | Yes |
| `socket_dir_missing`         | NEW — `/tmp/tmux-<uid>/` does not exist inside the container.                             | Yes |
| `socket_unreadable`          | NEW — `/tmp/tmux-<uid>/` exists but cannot be listed (permission denied or similar).      | Yes |
| `docker_exec_failed`         | NEW — non-zero exit from a FEAT-004 `docker exec` payload that is not a known specific code. | Yes |
| `docker_exec_timeout`        | NEW — `subprocess.TimeoutExpired` after 5 s on any FEAT-004 `docker exec` call.           | Yes |
| `output_malformed`           | NEW — `id -u`, socket-listing, or `tmux list-panes` output cannot be parsed.              | Yes |
| `bench_user_unresolved`      | NEW — host-side bench user resolution returned empty for one container (FR-020 fallback chain exhausted). | Yes |

FEAT-004 asymmetry (mirrors FEAT-003 R-014):

- `docker_unavailable` is the **only** code FEAT-004 ever places in
  the top-level socket envelope `error.code`. It maps to a
  whole-scan failure (`shutil.which("docker")` returned nothing or
  the resolved path is not executable at scan time, FR-022).
- `tmux_unavailable`, `tmux_no_server`, `socket_dir_missing`,
  `socket_unreadable`, `docker_exec_failed`, `docker_exec_timeout`,
  and `output_malformed` are **per-(container, socket?) codes
  only**. They appear in `pane_scans.error_code` (the representative
  code), `pane_scans.error_details_json` entries, the socket
  response's `result.error_details` array, the JSONL degraded event,
  and the CLI `--json` payload — but never in the top-level socket
  envelope `error.code`. The envelope for partial-degraded scans is
  `ok: true` with `result.status="degraded"`.

`docker_*` codes from the FEAT-003 set (`docker_permission_denied`,
`docker_timeout`, `docker_failed`, `docker_malformed`) are **not**
emitted by `scan_panes` or `list_panes`. FEAT-004 issues no
`docker ps`, no `docker inspect`, and no `docker info` call (R-001 /
FR-033 close the in-container subprocess set). Failures of the
three FEAT-004 `docker exec` payloads are reported with the new
codes above.

Forward-compatibility: a future feature MAY add additional codes to
this set. Clients MUST tolerate unknown codes by treating them as
opaque (matches FEAT-002's existing posture).

---

## 3. Method `scan_panes` (C-API-401)

### 3.1 Request

```json
{"method":"scan_panes"}
```

`params` is optional and currently has no defined keys. Unknown
keys are ignored (forward-compatibility).

### 3.2 Success response (healthy scan)

```json
{
  "ok": true,
  "result": {
    "scan_id": "9b1cf2ea-2a8e-4d97-a30f-3e8b9d1d2c0e",
    "started_at": "2026-05-06T18:01:34.512345+00:00",
    "completed_at": "2026-05-06T18:01:34.992118+00:00",
    "status": "ok",
    "containers_scanned": 2,
    "sockets_scanned": 3,
    "panes_seen": 7,
    "panes_newly_active": 7,
    "panes_reconciled_to_inactive": 0,
    "containers_skipped_inactive": 0,
    "containers_tmux_unavailable": 0,
    "error_code": null,
    "error_message": null,
    "error_details": []
  }
}
```

`status="ok"` means every active container produced at least one
parsed `tmux list-panes` row OR an empty result from a reachable
tmux server, every per-socket scan returned successfully, no row
required truncation, and no row was flagged malformed (FR-027 /
data-model §4.2).

### 3.3 Success response (partial-degraded scan)

The envelope is still `ok: true`; the scan *produced* a result.
`result.status="degraded"` is the machine-checkable signal.

```json
{
  "ok": true,
  "result": {
    "scan_id": "...",
    "started_at": "...",
    "completed_at": "...",
    "status": "degraded",
    "containers_scanned": 2,
    "sockets_scanned": 3,
    "panes_seen": 4,
    "panes_newly_active": 2,
    "panes_reconciled_to_inactive": 1,
    "containers_skipped_inactive": 0,
    "containers_tmux_unavailable": 1,
    "error_code": "tmux_unavailable",
    "error_message": "1 of 2 containers had tmux unavailable",
    "error_details": [
      {
        "container_id": "abc1234...",
        "error_code": "tmux_unavailable",
        "error_message": "tmux: command not found"
      },
      {
        "container_id": "f3c5e1ad...",
        "tmux_socket_path": "/tmp/tmux-1000/work",
        "error_code": "docker_exec_timeout",
        "error_message": "docker exec exceeded 5s budget"
      },
      {
        "container_id": "f3c5e1ad...",
        "tmux_socket_path": "/tmp/tmux-1000/default",
        "error_code": "output_malformed",
        "error_message": "tmux list-panes row had 8 fields, expected 10",
        "pane_truncations": [
          {"tmux_pane_id": "%2", "field": "pane_title", "original_len": 4096}
        ]
      }
    ]
  }
}
```

Per-scope envelope shape (data-model §6 note 3):

```text
{container_id, tmux_socket_path?, error_code, error_message, pane_truncations?}
```

- `tmux_socket_path` is **omitted** for per-container failures
  (`tmux_unavailable`, `socket_dir_missing`, `socket_unreadable`,
  `output_malformed` from a failed `id -u`, `docker_exec_failed` /
  `docker_exec_timeout` on the `id -u` or socket-listing call).
- `pane_truncations` is **omitted** unless at least one pane field
  on a successful socket scan was truncated. Each truncation entry
  carries the pane id, the field name (one of `pane_title`,
  `pane_current_command`, `pane_current_path`, plus the other
  text fields on the row), and the pre-truncation length in
  characters (R-009 / data-model §3.5).
- `error_message` is sanitized (NUL bytes and C0 control bytes
  stripped, embedded tabs/newlines replaced by spaces) and bounded
  to 2048 characters (R-009 / FR-026). Raw `docker exec` stderr,
  raw tmux output, raw environment values, and raw pane field
  values are never placed in `error_message`.

The top-level `result.error_code` is the **first** per-container or
per-socket code in scan order (data-model §2.2). If the only
reason the scan is degraded is field truncation on an otherwise
healthy socket scan, the representative `error_code` is
`output_malformed` and the top-level `error_message` describes the
truncation summary; truncation alone never produces an `ok:false`
envelope.

### 3.4 Error response (whole-scan failure)

When the scan cannot produce a useful result payload for the
caller, the envelope is `ok: false`. The only path that reaches
this shape in FEAT-004 is `docker_unavailable` (R-011, FR-022):

```json
{
  "ok": false,
  "error": {
    "code": "docker_unavailable",
    "message": "docker binary not found on PATH"
  }
}
```

Even in the whole-scan-failure path the daemon still allocates a
scan id, writes a `pane_scans` row with `status="degraded"`
(auditable history), appends one `pane_scan_degraded` JSONL event,
and updates no `panes` rows (data-model §4.2). The scan id is
recoverable from the lifecycle log and SQLite row but is not
returned to the caller in this envelope shape — matching FEAT-003's
asymmetry exactly.

`internal_error` is also reachable here when the SQLite scan
transaction fails to commit (FR-024 / R-015): the transaction
rolls back, no JSONL event is appended, the pane-scan mutex is
released, and the daemon stays alive. A post-commit failure of the
JSONL append or `pane_scan_completed` lifecycle emit also returns
`internal_error` even though the SQLite row is already durable
(R-015 mirrors FEAT-003 R-018 verbatim).

### 3.5 Semantics

- MUST acquire the daemon-scoped **pane-scan mutex**; concurrent
  callers block until it is available (FR-017 / R-004). Concurrent
  pane-scan callers each receive their own complete result and
  produce their own distinct `scan_id` and `pane_scans` row
  (FR-028).
- The pane-scan mutex is **independent** of the FEAT-003
  container-scan mutex. A `scan_panes` and a `scan_containers`
  request MAY proceed concurrently (FR-017 / R-004). Two
  `scan_panes` requests serialize behind the same in-process lock
  with no FIFO guarantee beyond the runtime's lock scheduling.
  The mutex is recreated on daemon restart; in-flight scans do not
  survive process exit.
- MUST persist exactly one row to `pane_scans` and zero or more
  upsert / touch-only / inactivate writes to `panes` in a single
  `BEGIN IMMEDIATE / COMMIT` transaction (FR-024 / R-015). Pane
  rows are **never deleted** during reconciliation (FR-008).
- MUST read the active container set from SQLite at scan start
  (`SELECT container_id, name, config_user FROM containers WHERE
  active = 1`) and MUST NOT re-run the FEAT-003 container scan
  (FR-002). Containers whose `containers.active = 0` at scan start
  trigger the FR-009 inactive-container cascade — their prior
  panes flip to `active=0` in the same transaction without any
  `docker exec` call (data-model §4.1 transition (c)).
- MUST resolve the bench user per container from
  `containers.config_user`, falling back to the daemon process
  `os.environ["USER"]` when that column is NULL (FR-020 / R-005).
- MUST resolve the in-container numeric uid by a bounded
  `docker exec -u <bench-user> <container-id> id -u` call (FR-020
  / R-006). Failure on `id -u` (timeout, non-zero exit, malformed
  output) places the container in `tmux_unavailable_containers`
  for reconciliation purposes; its prior pane rows preserve their
  `active` flag (FR-010 / data-model §4.1 transition (d)) and
  `last_scanned_at` is still updated.
- MUST enumerate sockets via
  `docker exec -u <bench-user> <container-id> ls -1 --
  /tmp/tmux-<uid>` (R-007). The literal `default` socket is the
  implicit default tmux server when present; every other regular
  basename is a candidate socket. Subdirectories, names beginning
  with `/`, and unparseable names are skipped without failing the
  scan (FR-004).
- MUST scan each candidate socket with
  `docker exec -u <bench-user> <container-id>
   tmux -S /tmp/tmux-<uid>/<socket-name> list-panes -a -F <format>`
  (R-002). The format string is the architecture doc §7 form,
  10 tab-separated fields: `session_name, window_index, pane_index,
  pane_id, pane_pid, pane_tty, pane_current_command,
  pane_current_path, pane_title, pane_active`. Rows with the wrong
  field count are flagged `output_malformed` and counted in the
  degraded result rather than persisted.
- MUST reconcile per-`(container, socket)` (FR-011): a failed
  socket inside a container that has at least one other reachable
  socket leaves its prior pane rows unchanged (`touch_only`) — only
  `last_scanned_at` advances. Rows are not flipped to inactive
  unless the same `(container, socket)` produced an `OkSocketScan`
  whose parsed set excludes them (data-model §4.1 transition (a)).
- MUST resolve the Docker binary with `shutil.which("docker")`
  using the daemon process `PATH` at scan time (FR-022) and invoke
  only the three closed-set argv forms enumerated in FR-033 with
  `shell=False`. No shell strings; container ids, names, bench
  user, socket paths, and tmux output are passed as argv elements
  only (FR-021).
- MUST bound every FEAT-004 `docker exec` call by a 5-second per-
  call timeout (FR-018 / R-003). On `subprocess.TimeoutExpired`
  the child MUST be terminated and waited on before the
  reconciler proceeds; the failure is normalized to
  `docker_exec_timeout` and the daemon stays alive.
- MUST sanitize and bound every persisted text field through a
  single helper (R-009 / FR-023): NUL bytes and C0 control bytes
  stripped; embedded tabs and newlines replaced by single spaces;
  truncated to per-field caps (`pane_title` ≤ 2048,
  `pane_current_command` ≤ 2048, `pane_current_path` ≤ 4096, all
  other text fields ≤ 2048). Truncation MUST NOT reject the pane
  row; a `pane_truncations` note is recorded on the per-scope
  detail entry instead.
- Healthy scans (`status="ok"`) MUST NOT write to `events.jsonl`.
  Degraded scans (`status="degraded"`, including the
  `docker_unavailable` whole-scan-failure path) MUST write exactly
  one record there with event type `pane_scan_degraded` (FR-025 /
  FR-028).
- MUST emit `pane_scan_started` to `agenttowerd.log` after
  acquiring the pane mutex and before any `docker exec` call, and
  `pane_scan_completed` after the SQLite commit and the JSONL
  append attempt, immediately before the socket response is
  returned (R-014). Both tokens are distinct from FEAT-003's
  `scan_started` / `scan_completed`. Lifecycle rows MUST contain
  only scan id, status, aggregate counts, and the closed error
  code — never raw tmux output, raw `docker exec` stderr, raw
  environment values, raw pane titles, or raw cwds (FR-026 /
  R-014).
- The `result.error_details` array carries one entry per affected
  `(container, socket?)` tuple. The array is bounded by the actual
  fan-out of the scan (≤ active containers × max sockets per
  container), which the plan caps at ≤ 60 entries on a developer
  workstation (≤ 20 × ≤ 3); no separate response-size error code
  is introduced (R-018).
- Latency budget: SC-006 — a `docker exec` timeout against one
  container produces a `docker_exec_timeout` per-container error
  within the 5-second per-call budget without orphaning the child
  or blocking the rest of the scan. Healthy scans against typical
  bench inventories (≤ 5 active containers, 1 socket each, ≤ 30
  panes total) complete well under 1 s on a normally-loaded host
  (plan "Performance Goals").

### 3.6 Errors

`bad_json`, `bad_request`, `internal_error` (FEAT-002 path);
`docker_unavailable` (whole-scan-failure path inherited from
FEAT-003 / FR-022).

The seven new per-scope codes (`tmux_unavailable`,
`tmux_no_server`, `socket_dir_missing`, `socket_unreadable`,
`docker_exec_failed`, `docker_exec_timeout`, `output_malformed`)
appear only in `result.error_details[]` and the persisted
`pane_scans.error_details_json`, never in the envelope's
`error.code`.

### 3.7 Forward-compatibility

Future features MAY add fields under `result`. Clients MUST
tolerate unknown keys. Future features MAY add new per-scope
error codes; clients MUST tolerate unknown codes by treating them
as opaque.

---

## 4. Method `list_panes` (C-API-402)

### 4.1 Request

```json
{"method":"list_panes","params":{"active_only":false,"container":null}}
```

| `params` field   | Type                | Default  | Notes                                                                                                                  |
| ---------------- | ------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------- |
| `active_only`    | boolean             | `false`  | When `true`, only rows with `panes.active = 1` are returned.                                                           |
| `container`      | string \| null      | `null`   | Optional exact-match filter. Resolves on the daemon as a 64-char hex id match against `panes.container_id`, otherwise as `panes.container_id IN (SELECT container_id FROM containers WHERE name = ?)` (data-model §6 note 4). |

`active_only` and `container` are the only defined param keys;
unknown keys are ignored.

### 4.2 Success response

```json
{
  "ok": true,
  "result": {
    "filter": "all",
    "container_filter": null,
    "panes": [
      {
        "container_id": "f3c5e1ad...",
        "container_name": "py-bench",
        "container_user": "user",
        "tmux_socket_path": "/tmp/tmux-1000/default",
        "tmux_session_name": "work",
        "tmux_window_index": 0,
        "tmux_pane_index": 0,
        "tmux_pane_id": "%0",
        "pane_pid": 1234,
        "pane_tty": "/dev/pts/0",
        "pane_current_command": "bash",
        "pane_current_path": "/workspace",
        "pane_title": "user@py-bench: ~/workspace",
        "pane_active": true,
        "active": true,
        "first_seen_at": "2026-05-06T17:55:01.123456+00:00",
        "last_scanned_at": "2026-05-06T18:01:34.692118+00:00"
      }
    ]
  }
}
```

`result.filter` is `"all"` when `params.active_only` is
unset/false and `"active_only"` when `true`. `result.container_filter`
echoes the request's `params.container` value verbatim (or `null`
when unset) so scripts can confirm the filter was applied.

`result.panes` is ordered deterministically by
`active DESC, container_id ASC, tmux_socket_path ASC,
tmux_session_name ASC, tmux_window_index ASC,
tmux_pane_index ASC` (FR-016 / R-008).

Empty state is a valid response: `result.panes = []`. A
`container_filter` value that matches no row produces an empty
list with envelope `ok: true` (no `bad_request`).

Field semantics worth pinning down for clients (data-model §6):

1. `pane_active` (boolean — the focused-pane flag from
   `#{pane_active}`) and `active` (boolean — the row-level
   reconciliation flag) are **distinct** fields. They are NEVER
   collapsed at the protocol boundary.
2. Every text field is post-sanitization, post-truncation: NUL
   bytes and C0 control bytes are absent; embedded tabs and
   newlines have been replaced by single spaces; lengths are
   bounded to the per-field caps in R-009 (`pane_title` ≤ 2048,
   `pane_current_command` ≤ 2048, `pane_current_path` ≤ 4096, all
   other text fields ≤ 2048).
3. `first_seen_at` and `last_scanned_at` are ISO-8601 UTC with
   microsecond precision (matches FEAT-002 / FEAT-003).
4. `tmux_window_index`, `tmux_pane_index`, `pane_pid` are
   integers; every other field that looks like a string is a
   string.

### 4.3 Semantics

- MUST be a read-only SQLite SELECT under a short read transaction.
- MUST NOT acquire the pane-scan mutex (FR-016 / R-004) and MUST
  NOT acquire the FEAT-003 container-scan mutex; readers stay
  fast even during a slow scan.
- MUST NOT call Docker, tmux, or any subprocess.
- MUST reflect latest committed SQLite state only; in-flight scan
  writes are not visible.
- MUST order rows deterministically by the FR-016 key.
- MUST resolve `params.container` on the daemon side per
  data-model §6 note 4: a 64-char hex argument is matched directly
  on `panes.container_id`; any other value is matched on
  `containers.name` and the resulting id set is intersected with
  `panes.container_id`. No substring or partial match.
- MUST exclude pane rows whose `container_id` is not present in
  `containers` (defensive: the FEAT-003 schema is read-only here,
  but `panes` rows are not foreign-keyed so a manual delete on
  `containers` could leave dangling panes; the contract surfaces
  only rows with a matching container).
- Exposes pane titles, current commands, and cwds to the trusted
  host user only via the inherited FEAT-002 socket-file
  authorization; secret redaction is deferred to FEAT-007 (R-018).
- Latency budget: < 100 ms for ≤ 1000 rows on a normally-loaded
  host (plan "Performance Goals").

Response-size note: FEAT-002's 64 KiB cap applies to request
lines, not response lines. FEAT-004 keeps responses bounded by
the per-field length caps (R-009) and by the steady-state scale
(≤ 20 active containers × ≤ 30 panes × ≤ 4096 chars per cwd —
worst case a few hundred kilobytes per `list_panes` response,
within reasonable Unix-socket read limits on a developer
workstation).

### 4.4 Errors

`bad_json`, `bad_request`, `internal_error`. None of the
`docker_*`, `tmux_*`, `socket_*`, `output_malformed`,
`docker_exec_*`, or `config_invalid` codes can be emitted by this
method because it does not touch Docker, tmux, the matching
config, or the pane-scan mutex.

A `params.active_only` value that is not a boolean, or a
`params.container` value that is not `null` or a string, produces
`bad_request`.

---

## 5. Out-of-scope (FEAT-004)

The following methods, params, fields, and behaviors remain **not**
part of FEAT-004 and continue to return `unknown_method`:

- `register_agent`, `list_agents`, `set_role`, `set_capability`
  (FEAT-006).
- `attach`, `detach`, `tail_logs`, log-streaming methods (FEAT-008).
- `events`, `events_follow` (FEAT-008).
- `send_input`, `route` (FEAT-009).
- A `params.session` filter or any per-window / per-pane filter on
  `list_panes` beyond `active_only` and exact `container`.
- A `params.scan_kind` mode on `scan_panes` (incremental scans,
  watcher-driven scans) — request-driven scans only in MVP
  (assumption in spec.md §Assumptions).
- A pagination or response-size error code on `list_panes` —
  unnecessary at MVP scale (R-018).

A future feature SHOULD NOT redefine the `result` shape of either
new method; it MAY add fields. Clients MUST tolerate unknown
result-level keys and unknown error codes.
