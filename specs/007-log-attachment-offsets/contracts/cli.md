# CLI Contracts: Pane Log Attachment and Offset Tracking

**Branch**: `007-log-attachment-offsets` | **Date**: 2026-05-08

This document is the authoritative contract for the new
`agenttower` CLI surfaces FEAT-007 introduces. It supplements
`spec.md` FR-031–FR-037, FR-037a, and Clarifications 2026-05-08
Q1, Q2, Q3.

CLI conventions inherited verbatim from FEAT-006:
- Exit codes: `0` success, `1` `host_context_unsupported`, `2`
  `daemon_unavailable`, `3` every other closed-set code, `4` CLI
  internal error.
- Text-mode output: one `key=value` line per field on stdout
  (FR-037).
- `--json` output: one envelope object on stdout, stderr empty
  (FEAT-006 `--json` purity contract).
- Argparse uses `argparse.SUPPRESS` for optional flags so omitted
  flags are absent from the parsed dict and not transmitted on
  the wire.
- Socket resolution chain: `AGENTTOWER_SOCKET` → in-container
  default → host default (FEAT-005).

---

## C-CLI-701 — `agenttower attach-log`

### Synopsis

```text
agenttower attach-log --target <agent-id> [--log <path>] [--json]
```

### Required flags

- `--target <agent-id>`: the FEAT-006 `agt_<12-hex>` agent id to
  attach a log to.

### Optional flags

- `--log <path>`: explicit host-visible log path. Default: the
  canonical FR-005 path
  `~/.local/state/opensoft/agenttower/logs/<container_id>/<agent_id>.log`.
- `--json`: emit the FEAT-006 envelope `{"ok": true, "result":
  {...}}`.

### Behavior

1. Resolve the FEAT-005 socket path; refuse with
   `daemon_unavailable` (exit 2) if the daemon isn't reachable.
2. Send `attach_log` with the agent_id (and `log_path` if
   `--log` was supplied) plus the schema_version hint.
3. On success, print one `key=value` line per field on stdout:
   ```text
   attached agent_id=agt_abc123def456 attachment_id=lat_a1b2c3d4e5f6
   path=/home/user/.local/state/opensoft/agenttower/logs/<container_id>/agt_abc123def456.log
   source=explicit status=active
   ```
4. On failure, exit per the FR-038 closed-set codes and the
   FR-036 exit-code mapping. Failure messages are one line on
   stderr (text mode) or a closed-set `error.code` field
   (`--json` mode).

### Acceptance scenarios → tests

- US1 AS1 → `test_cli_attach_log.py`
- US1 AS2 idempotency → `test_cli_attach_log_idempotent.py`
- US1 AS3 pane reactivation → `test_cli_attach_log_pane_reactivation.py`
- US1 AS4 path supersede → `test_cli_attach_log_supersede_path_change.py`

---

## C-CLI-702 — `agenttower attach-log --status`

### Synopsis

```text
agenttower attach-log --target <agent-id> --status [--json]
```

### Required flags

- `--target <agent-id>`
- `--status` (required for this read-only mode)

### Optional flags

- `--json`

### Behavior

1. Send `attach_log_status` with the agent_id.
2. Universal read-only inspection (FR-032; Clarifications Q3):
   - ALWAYS exits `0` when the agent is resolvable via FR-001.
   - Returns the MOST RECENT row by `last_status_at` regardless
     of status.
   - Returns `attachment=null offset=null` when no row exists.
3. Text-mode output, no row:
   ```text
   agent_id=agt_abc123def456 attachment=null offset=null
   ```
4. Text-mode output, row present:
   ```text
   agent_id=agt_abc123def456 attachment_id=lat_a1b2c3d4e5f6
   path=/host/path/...log status=active source=explicit
   attached_at=2026-05-08T14:23:45.123456+00:00
   last_status_at=2026-05-08T14:23:45.123456+00:00
   byte_offset=4096 line_offset=137 last_event_offset=3200
   file_inode=234:1234567 file_size_seen=8192
   ```
5. NEVER issues `pipe-pane` or `docker exec`; touches only SQLite
   (FR-032).

### Acceptance scenarios → tests

- FR-032 / Clarifications Q3 → `test_cli_attach_log_status.py`

---

## C-CLI-703 — `agenttower attach-log --preview <N>`

### Synopsis

```text
agenttower attach-log --target <agent-id> --preview <N> [--json]
```

### Required flags

- `--target <agent-id>`
- `--preview <N>`: integer, `1 ≤ N ≤ 200`.

### Optional flags

- `--json`

### Behavior

1. Send `attach_log_preview` with `agent_id` and `lines=N`.
2. Allowed when most-recent row's status ∈ `{active, stale,
   detached}` AND host file at row's `log_path` exists.
3. Refused with `attachment_not_found` (exit 3) when:
   - most-recent row has status `superseded`, OR
   - agent has no `log_attachments` row.
4. Refused with `log_file_missing` (exit 3) when the resolved
   row's host file does not exist.
5. Refused with `value_out_of_set` (exit 3) when N is out of
   range.
6. On success, output is the last N lines of the host file,
   redacted via FR-027 / FR-028, joined with newlines.
7. NEVER issues `pipe-pane` or `docker exec`; reads the host
   file directly (FR-033).

### `--json` envelope (success)

```json
{
  "ok": true,
  "result": {
    "agent_id": "agt_abc123def456",
    "attachment_id": "lat_a1b2c3d4e5f6",
    "log_path": "/host/path/...log",
    "lines": [
      "<redacted line 1>",
      "<redacted line 2>"
    ]
  }
}
```

### Acceptance scenarios → tests

- US3 → `test_cli_attach_log_redaction_preview.py`
- FR-033 / Clarifications Q3 → `test_cli_attach_log_preview.py`
- FR-033 file-missing → `test_preview_file_missing.py` (unit)

---

## C-CLI-704 — `agenttower detach-log`

### Synopsis

```text
agenttower detach-log --target <agent-id> [--json]
```

### Required flags

- `--target <agent-id>`

### Optional flags

- `--json`

### Behavior

1. Send `detach_log` with the agent_id.
2. Valid only when the agent has a `log_attachments` row in
   `status=active` (FR-021b).
3. Same liveness gates as attach (FR-021e): agent active,
   pane active, container active.
4. On success, daemon issues `tmux pipe-pane -t <pane>` (no
   command), transitions row `active → detached`, retains the
   `log_offsets` row byte-for-byte, and appends one
   `log_attachment_change` audit row.
5. Text-mode output:
   ```text
   detached agent_id=agt_abc123def456 attachment_id=lat_a1b2c3d4e5f6
   path=/host/path/...log status=detached
   ```
6. Refused with `attachment_not_found` (exit 3) when:
   - agent has no `log_attachments` row, OR
   - agent's most-recent row has status ∈ `{stale, superseded,
     detached}`.

### Acceptance scenarios → tests

- US7 AS1 / SC-011 → `test_cli_detach_log.py`
- US7 AS3 / FR-021b → `test_cli_detach_log_invalid_state.py`
- US7 AS4 / FR-021a → `test_cli_no_implicit_detach.py`

---

## C-CLI-705 — `agenttower register-self --attach-log`

### Synopsis

```text
agenttower register-self [<existing FEAT-006 flags>] --attach-log [--log <path>]
```

### Behavior (extends FEAT-006 C-CLI-601)

1. The CLI sends `register_agent` (FEAT-006) with an additional
   wire field that signals attach-log is in flight (Research
   R-002).
2. On the daemon side, the FEAT-006 `register_agent` handler
   detects the flag and runs the FEAT-007 attach inside the SAME
   `BEGIN IMMEDIATE` transaction (FR-035): agent row write +
   `log_attachments` row + `log_offsets` row + both JSONL audit
   rows committed atomically.
3. JSONL audit ordering: `agent_role_change` FIRST,
   `log_attachment_change` SECOND (FR-035, deterministic for
   downstream consumers).
4. FAIL-THE-CALL (FR-034): if the FEAT-007 attach fails for any
   FR-038 closed-set code, the entire `register_agent` rolls
   back atomically — zero `agents` row, zero `log_attachments`
   row, zero `log_offsets` row, zero JSONL audit rows.
5. The CLI surfaces the FEAT-007 failure code as the top-level
   error (the FEAT-006 success message is NOT printed first).
6. On success, text-mode output is the FEAT-006 register-self
   line followed by the FEAT-007 attached line, in that order:
   ```text
   registered agent_id=agt_abc123def456 ...
   attached agent_id=agt_abc123def456 attachment_id=lat_... ...
   ```

### Acceptance scenarios → tests

- US4 AS1 / SC-008 → `test_cli_register_self_attach_log_success.py`
- US4 AS2 / SC-008 → `test_cli_register_self_attach_log_failure.py`

---

## Closed-set error codes (CLI-side, inherited from FR-038)

| Code                              | Exit | Raised by                                  |
|-----------------------------------|------|--------------------------------------------|
| `host_context_unsupported`        | 1    | client-side (FEAT-005)                     |
| `daemon_unavailable`              | 2    | client-side (FEAT-002)                     |
| `not_in_tmux`                     | 3    | client-side (FEAT-005)                     |
| `container_unresolved`            | 3    | client-side (FEAT-005)                     |
| `tmux_pane_malformed`             | 3    | client-side (FEAT-005)                     |
| `agent_not_found`                 | 3    | daemon (FR-001)                            |
| `agent_inactive`                  | 3    | daemon (FR-002, FR-004)                    |
| `pane_unknown_to_daemon`          | 3    | daemon (FR-003)                            |
| `log_path_invalid`                | 3    | daemon (FR-006)                            |
| `log_path_not_host_visible`       | 3    | daemon (FR-007)                            |
| `log_path_in_use`                 | 3    | daemon (FR-009)                            |
| `pipe_pane_failed`                | 3    | daemon (FR-012)                            |
| `tmux_unavailable`                | 3    | daemon (FR-013)                            |
| `attachment_not_found`            | 3    | daemon (FR-021b, FR-033)                   |
| `log_file_missing`                | 3    | daemon (FR-033, only on `--preview`)       |
| `bad_request`                     | 3    | daemon (FR-039)                            |
| `value_out_of_set`                | 3    | daemon (closed-set field violations)       |
| `internal_error`                  | 3    | daemon (unexpected failures; daemon stays alive) |
| `schema_version_newer`            | 3    | daemon (FR-038 forward-compat)             |

CLI internal errors (argparse failures, JSON parse failures of
daemon response, etc.) exit with code `4`.
