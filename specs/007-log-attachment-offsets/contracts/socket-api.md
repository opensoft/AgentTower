# Socket-API Contracts: Pane Log Attachment and Offset Tracking

**Branch**: `007-log-attachment-offsets` | **Date**: 2026-05-08

This document is the authoritative contract for the four new
daemon socket methods FEAT-007 introduces, plus the FEAT-006
`register_agent` extension when `--attach-log` is in flight. It
supplements `spec.md` FR-031–FR-039 and Clarifications 2026-05-08
Q1, Q2, Q3, Q4, Q5.

The new methods reuse the FEAT-002 newline-delimited JSON
request/response framing and host-user authorization (`0600`,
host user only) verbatim. No new framing, no new authorization
tier, no new envelope shape.

---

## 1. Method dispatch table

The FEAT-006 dispatch table grows from twelve entries to sixteen.
Insertion order is preserved per the FEAT-002 stability rule;
new entries are appended:

```python
DISPATCH: dict[str, Handler] = {
    "ping":              _ping,                 # FEAT-002
    "status":            _status,               # FEAT-002
    "shutdown":          _shutdown,             # FEAT-002
    "scan_containers":   _scan_containers,      # FEAT-003
    "list_containers":   _list_containers,      # FEAT-003
    "scan_panes":        _scan_panes,           # FEAT-004
    "list_panes":        _list_panes,           # FEAT-004
    "register_agent":    _register_agent,       # FEAT-006
    "list_agents":       _list_agents,          # FEAT-006
    "set_role":          _set_role,             # FEAT-006
    "set_label":         _set_label,            # FEAT-006
    "set_capability":    _set_capability,       # FEAT-006
    "attach_log":        _attach_log,           # FEAT-007
    "detach_log":        _detach_log,           # FEAT-007
    "attach_log_status": _attach_log_status,    # FEAT-007
    "attach_log_preview":_attach_log_preview,   # FEAT-007
}
```

Unknown method names continue to return `unknown_method` per
FEAT-002.

---

## 2. Common framing

All envelopes use the FEAT-002 newline-delimited JSON shape:

```text
{"method":"<name>","params":{...}}\n        # request
{"ok":true,"result":{...}}\n                 # success response
{"ok":false,"error":{"code":"<code>","message":"..."}}\n  # error response
```

Request size limit: inherits FEAT-002 `request_too_large`. Field
sanitization: inherits FEAT-006 sanitization (NUL strip,
≤ 4096 chars on free-text, no control bytes after stripping).

**Case-sensitivity contract**: every closed-set token (`status`,
`source`) and every lowercase-hex identifier (`agent_id`,
`attachment_id`, `container_id`) is matched case-sensitively.
Mixed-case inputs MUST be rejected with `value_out_of_set`.

**Schema version contract**: every method's request envelope
accepts an optional `schema_version` integer. The daemon refuses
with `schema_version_newer` (FR-038) when the daemon's
`CURRENT_SCHEMA_VERSION` < client's advertised value. The daemon
ignores client schema_version values < its own (forward-compat
on the daemon side; old clients can still call).

---

## 3. `attach_log`

### 3.1 Request

```json
{
  "method": "attach_log",
  "params": {
    "agent_id": "agt_abc123def456",
    "log_path": "/host/path/A.log",   // OPTIONAL — see FR-005 default
    "schema_version": 5                // OPTIONAL — FR-038 forward-compat hint
  }
}
```

**Required keys**: `agent_id`.

**Optional keys**: `log_path`, `schema_version`.

**Forbidden keys**: any key other than the three listed above is
rejected with `bad_request` (FR-039). In particular, `source` is
rejected at the wire — the daemon sets `source ∈ {explicit,
register_self}` based on call site (`source=explicit` for
standalone `attach_log`; `source=register_self` for
`register_agent` with `--attach-log`).

**Wire shape rules**:
- Absent `log_path` → daemon generates the FR-005 canonical path.
- Empty-string `log_path` → rejected `log_path_invalid`.
- `log_path` not absolute, with `..`, NUL, oversize, or symlink
  escape → rejected `log_path_invalid` or
  `log_path_not_host_visible`.

### 3.2 Success response

```json
{
  "ok": true,
  "result": {
    "agent_id": "agt_abc123def456",
    "attachment_id": "lat_a1b2c3d4e5f6",
    "log_path": "/host/path/A.log",
    "source": "explicit",
    "status": "active",
    "byte_offset": 0,
    "line_offset": 0,
    "attached_at": "2026-05-08T14:23:45.123456+00:00",
    "last_status_at": "2026-05-08T14:23:45.123456+00:00",
    "is_new": true              // false on idempotent re-attach (FR-018)
  }
}
```

### 3.3 Error responses

| Code                              | Cause                                                     |
|-----------------------------------|-----------------------------------------------------------|
| `agent_not_found`                 | `agent_id` not in `agents` table (FR-001)                 |
| `agent_inactive`                  | agent or container `active=0` (FR-002, FR-004)            |
| `pane_unknown_to_daemon`          | bound pane absent after focused rescan (FR-003)           |
| `log_path_invalid`                | shape rules violated (FR-006)                             |
| `log_path_not_host_visible`       | host-visibility proof failed (FR-007)                     |
| `log_path_in_use`                 | different agent owns the path (FR-009)                    |
| `pipe_pane_failed`                | non-zero exit or matching stderr (FR-012)                 |
| `tmux_unavailable`                | tmux not installed in container (FR-013)                  |
| `bad_request`                     | unknown keys or malformed envelope (FR-039)               |
| `value_out_of_set`                | closed-set field violation                                |
| `internal_error`                  | unexpected daemon-side failure                            |
| `schema_version_newer`            | daemon schema lower than advertised (FR-038)              |

---

## 4. `detach_log`

### 4.1 Request

```json
{
  "method": "detach_log",
  "params": {
    "agent_id": "agt_abc123def456",
    "schema_version": 5
  }
}
```

**Required keys**: `agent_id`. **Optional**: `schema_version`.
**Forbidden**: any other key (`bad_request`).

### 4.2 Success response

```json
{
  "ok": true,
  "result": {
    "agent_id": "agt_abc123def456",
    "attachment_id": "lat_a1b2c3d4e5f6",
    "log_path": "/host/path/A.log",
    "status": "detached",
    "byte_offset": 4096,
    "line_offset": 137,
    "last_status_at": "2026-05-08T14:24:00.000000+00:00"
  }
}
```

### 4.3 Error responses

| Code                              | Cause                                                       |
|-----------------------------------|-------------------------------------------------------------|
| `agent_not_found`, `agent_inactive`, `pane_unknown_to_daemon` | same as `attach_log`        |
| `attachment_not_found`            | no row, or row in `{stale, superseded, detached}` (FR-021b) |
| `pipe_pane_failed`                | toggle-off failed (FR-021c)                                 |
| `tmux_unavailable`                | tmux not installed in container (FR-013)                    |
| `bad_request`                     | unknown keys                                                |
| `internal_error`                  | unexpected failure                                          |
| `schema_version_newer`            | (FR-038)                                                    |

---

## 5. `attach_log_status`

### 5.1 Request

```json
{
  "method": "attach_log_status",
  "params": {
    "agent_id": "agt_abc123def456",
    "schema_version": 5
  }
}
```

### 5.2 Success response (row present)

```json
{
  "ok": true,
  "result": {
    "agent_id": "agt_abc123def456",
    "attachment": {
      "attachment_id": "lat_a1b2c3d4e5f6",
      "log_path": "/host/path/A.log",
      "status": "active",
      "source": "explicit",
      "attached_at": "2026-05-08T14:23:45.123456+00:00",
      "last_status_at": "2026-05-08T14:23:45.123456+00:00",
      "superseded_at": null,
      "superseded_by": null
    },
    "offset": {
      "byte_offset": 4096,
      "line_offset": 137,
      "last_event_offset": 3200,
      "last_output_at": "2026-05-08T14:24:00.000000+00:00",
      "file_inode": "234:1234567",
      "file_size_seen": 8192
    }
  }
}
```

### 5.3 Success response (no row)

```json
{
  "ok": true,
  "result": {
    "agent_id": "agt_abc123def456",
    "attachment": null,
    "offset": null
  }
}
```

### 5.4 Error responses

`--status` is universal read (FR-032 / Clarifications Q3); the
only failure modes are infra-level:

| Code                              | Cause                                                     |
|-----------------------------------|-----------------------------------------------------------|
| `agent_not_found`                 | `agent_id` not in `agents` table                          |
| `bad_request`                     | unknown keys                                              |
| `value_out_of_set`                | malformed `agent_id`                                      |
| `internal_error`                  | unexpected SQLite failure                                 |
| `schema_version_newer`            | (FR-038)                                                  |

NOT raised: `agent_inactive`, `pane_unknown_to_daemon`,
`log_file_missing`, `attachment_not_found`. `--status` reports
state, never fails because of state.

---

## 6. `attach_log_preview`

### 6.1 Request

```json
{
  "method": "attach_log_preview",
  "params": {
    "agent_id": "agt_abc123def456",
    "lines": 50,
    "schema_version": 5
  }
}
```

**Required keys**: `agent_id`, `lines`.
**Optional keys**: `schema_version`.

`lines`: integer, `1 ≤ lines ≤ 200`. Out-of-range surfaces as
`value_out_of_set`.

### 6.2 Success response

```json
{
  "ok": true,
  "result": {
    "agent_id": "agt_abc123def456",
    "attachment_id": "lat_a1b2c3d4e5f6",
    "log_path": "/host/path/A.log",
    "lines": [
      "<redacted line 1>",
      "<redacted line 2>"
    ]
  }
}
```

The `lines` array contains at most `params.lines` entries; fewer
when the host file has fewer lines (or is empty). Each line is
the raw bytes from the file with FR-027 / FR-028 redaction
applied per FR-029 (per-line; multi-line tokens not redacted).

### 6.3 Error responses

| Code                              | Cause                                                              |
|-----------------------------------|--------------------------------------------------------------------|
| `agent_not_found`                 | `agent_id` not in `agents` table                                   |
| `attachment_not_found`            | no row, or most-recent row in `superseded` (FR-033)                |
| `log_file_missing`                | row in allowed status but host file absent (FR-033)                |
| `bad_request`                     | unknown keys                                                       |
| `value_out_of_set`                | `lines` out of range, malformed `agent_id`                         |
| `internal_error`                  | unexpected failure (e.g., file unreadable, encoding error)         |
| `schema_version_newer`            | (FR-038)                                                           |

---

## 7. `register_agent` extension when `--attach-log` is in flight

The FEAT-006 `register_agent` envelope gains exactly ONE new
optional key, `attach_log`, signaling the FEAT-007 attach is in
flight as part of the same call. The CLI sets this key when the
operator passed `--attach-log` to `register-self`.

### 7.1 Extended request

```json
{
  "method": "register_agent",
  "params": {
    "container_id": "<full-id>",
    "pane_composite_key": { ... },
    "role": "slave",
    "capability": "codex",
    "label": "codex-01",
    "project_path": "/workspace/acme",
    "parent_agent_id": "agt_aaa...",
    "attach_log": {                      // NEW — OPTIONAL
      "log_path": "/host/path/A.log"     // OPTIONAL — defaults to FR-005
    },
    "schema_version": 5
  }
}
```

If `attach_log` is absent, the daemon performs the FEAT-006
register-self flow unchanged. If present, the daemon performs
the atomic two-table commit per FR-034 / FR-035.

### 7.2 Success response (extended)

```json
{
  "ok": true,
  "result": {
    "agent_id": "agt_abc123def456",
    "agent": { ...FEAT-006 record... },
    "attach_log": {
      "attachment_id": "lat_a1b2c3d4e5f6",
      "log_path": "/host/path/A.log",
      "source": "register_self",
      "status": "active",
      "byte_offset": 0,
      "line_offset": 0,
      "is_new": true
    }
  }
}
```

### 7.3 Failure

FAIL-THE-CALL (FR-034): on any FEAT-007 failure code, the entire
`register_agent` rolls back atomically. The daemon returns the
FEAT-007 failure code as the top-level error (NOT the FEAT-006
success):

```json
{
  "ok": false,
  "error": {
    "code": "log_path_not_host_visible",
    "message": "no canonical bind mount for /host/path/A.log; ..."
  }
}
```

Zero `agents` row created, zero `log_attachments` row, zero
`log_offsets` row, zero JSONL audit rows.

---

## 8. Validation order (cross-method)

All four FEAT-007 methods AND the extended `register_agent`
follow the same pre-handler gate sequence (mirrors FEAT-006):

1. `_check_schema_version` (FR-038)
2. `_check_unknown_keys` against the method's allowed-keys set
   (FR-039)
3. Required-field presence
4. Closed-set field shape on present optional keys
5. Method-specific resolution and gates (per § Validation order
   in `data-model.md` §7)

Any failure in steps 1-4 surfaces immediately without touching
SQLite, the audit log, or the docker/tmux adapters.
