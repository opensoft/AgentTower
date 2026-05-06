# Contract: CLI additions (FEAT-004)

**Branch**: `004-container-tmux-pane-discovery` | **Date**: 2026-05-06

This contract documents the user-facing CLI surface FEAT-004 adds
on top of FEAT-001 / FEAT-002 / FEAT-003. Every behavior listed
here is reachable via `subprocess.run` from a test harness; nothing
here depends on Python in-process imports.

FEAT-004 adds:

- One new mode flag on the existing FEAT-003 `scan` subcommand:
  `--panes`. The flag composes with `--containers`; the bare
  `agenttower scan` form still exits non-zero, but its error
  message is updated to advertise both target flags.
- One new `agenttower` subcommand: `list-panes` (no positional
  arguments, three optional flags).

Existing FEAT-001 / FEAT-002 / FEAT-003 commands and exit codes are
unchanged (FR-030). The newline-delimited JSON socket protocol used
by these new commands is documented in `socket-api.md`.

---

## C-CLI-401 — `agenttower scan --panes`

### Invocation

```bash
agenttower scan --panes
agenttower scan --panes --json
agenttower scan --containers --panes
agenttower scan --containers --panes --json
```

`agenttower scan` without any target flag prints
`error: scan requires a target flag (e.g. --containers, --panes)`
to stderr and exits `1`. This replaces FEAT-003's identical-shape
error to include the new `--panes` token (FR-030: behavior is
additive — the existing FEAT-003 wording was already "e.g.
--containers", so existing scripts that match exit code `1` keep
working).

`--containers` and `--panes` may be combined in a single
invocation. When both are passed, the CLI calls `scan_containers`
first, then `scan_panes`, and emits two scan-summary blocks
(default mode, separated by a blank line) or two JSON lines
(`--json`). The pane scan reads the active container set from
SQLite at scan start (FR-002), so a combined invocation guarantees
the pane scan sees the freshest container data.

### Behavior

1. Resolve the socket path from FEAT-001 `Paths.socket`. If
   FEAT-001 is not initialized, exit `1` with
   `error: agenttower is not initialized: run \`agenttower config init\``.
2. Connect to the socket with a 1 s connect-timeout. If unreachable,
   exit `2` with the FEAT-002 `daemon-unavailable` message.
3. Send `{"method":"scan_panes"}`. Read one response line with a
   30 s read-timeout (the worst-case pane scan can chain several
   per-call 5 s Docker timeouts; see plan "Performance Goals").
4. If the envelope is `ok: false`, exit `3` with the
   `error.message` on stderr and `code: <error.code>` on a second
   stderr line. Match FEAT-002's two-line error format.
5. If the envelope is `ok: true`, render the result and exit:
   - `0` when `result.status == "ok"`.
   - `5` when `result.status == "degraded"` (same exit code FEAT-003
     uses for partial-degraded scans; documented below).

For the combined `--containers --panes` invocation, the CLI runs
the two requests sequentially over two separate connections (the
socket protocol is one request per connection, FEAT-002 §1). The
final exit code is the **highest-precedence** outcome across the
two: any `3` wins over `5` wins over `0`. Each scan still prints
its own summary block / JSON line in the order it executed.

### Output (stdout, default)

Ten lines, fixed order, `key=value` form:

```text
scan_id=<uuid>
status=<ok|degraded>
containers_scanned=<int>
sockets_scanned=<int>
panes_seen=<int>
panes_newly_active=<int>
panes_reconciled_inactive=<int>
containers_skipped_inactive=<int>
containers_tmux_unavailable=<int>
duration_ms=<int>
```

`duration_ms` is computed client-side from the
`completed_at` minus `started_at` timestamps in the response. The
remaining keys are aliases for the canonical `pane_scans` columns
(`panes_reconciled_inactive` is shortened from
`panes_reconciled_to_inactive` only inside the human view; the
socket and `--json` payloads keep the canonical name from
data-model §2.2).

When `status=degraded`, additional stderr lines are emitted
(stderr only, after the stdout block):

```text
error: <result.error_message>
code: <result.error_code>
```

Followed by zero or more per-scope lines, one per element of
`result.error_details`, capped at 10 entries with a trailing
`... (<N> more)` line if `len(error_details) > 10`:

```text
detail: <container_id> [socket=<tmux_socket_path>] <error_code>: <error_message>
```

Pane truncation notes for entries that have them are summarized
on a single follow-up line:

```text
detail: <container_id> [socket=<tmux_socket_path>] truncated <field>=<original_len>chars on pane <tmux_pane_id> (+<N> more)
```

The `[socket=...]` segment is omitted for per-container failures
(no `id -u`, socket dir missing, socket dir unreadable). All
detail-line strings are sanitized identically to the persisted
`error_message` per data-model §2.2 / R-009 (NUL bytes and C0
control bytes stripped, embedded tabs/newlines replaced by single
spaces).

### Output (stdout, `--json`)

Exactly one line of canonical JSON: the response's `result` object
verbatim, plus the `ok` field:

```json
{"ok":true,"result":{"scan_id":"...","started_at":"...","completed_at":"...","status":"ok","containers_scanned":2,"sockets_scanned":3,"panes_seen":7,"panes_newly_active":7,"panes_reconciled_to_inactive":0,"containers_skipped_inactive":0,"containers_tmux_unavailable":0,"error_code":null,"error_message":null,"error_details":[]}}
```

In the partial-degraded path the envelope stays `ok: true`,
`result.status="degraded"`, and `result.error_details` carries one
element per affected `(container, socket?)` tuple in the canonical
shape `{container_id, tmux_socket_path?, error_code, error_message,
pane_truncations?}` (data-model §6 note 3). Exit code `5`.

In the whole-scan-failure path (envelope `ok: false`), `--json`
emits:

```json
{"ok":false,"error":{"code":"docker_unavailable","message":"docker binary not found on PATH"}}
```

and exits `3` (matches FEAT-002 / FEAT-003's daemon-error exit
code).

For combined `--containers --panes --json`, the CLI emits exactly
two JSON lines in the order the scans executed; each line is
self-contained.

### Output (stderr)

Empty on the success path. On any non-zero exit, FEAT-002 / FEAT-003
patterns apply:

| Path                          | stderr                                                          |
| ----------------------------- | --------------------------------------------------------------- |
| Not initialized (exit 1)      | `error: agenttower is not initialized: run \`agenttower config init\`` |
| Bare `scan` form (exit 1)     | `error: scan requires a target flag (e.g. --containers, --panes)` |
| Daemon unavailable (exit 2)   | `error: daemon is not running or socket is unreachable: try \`agenttower ensure-daemon\`` |
| Daemon error (exit 3)         | Two lines: `error: <message>` then `code: <error.code>`         |
| Degraded scan (exit 5)        | Two lines: `error: <message>` then `code: <error.code>`, plus zero or more `detail: ...` lines |
| Internal CLI error (exit 4)   | `error: internal CLI error: <reason>`                           |

### Exit codes

| Code | Meaning                                                                                      |
| ---- | -------------------------------------------------------------------------------------------- |
| `0`  | Scan completed and `result.status == "ok"`.                                                  |
| `1`  | Pre-flight failure (FEAT-001 not initialized, bare `scan` form).                             |
| `2`  | Socket missing, connect refused, or timed out.                                               |
| `3`  | Daemon returned a structured error (envelope `ok: false`) — typically `docker_unavailable`.  |
| `4`  | Internal CLI error.                                                                          |
| `5`  | Scan completed but `result.status == "degraded"`.                                            |

`5` is intentionally distinct from `3`: a degraded pane scan is a
*successful round-trip* that nevertheless requires operator
attention. Scripts can treat `0` as "everything was clean" and `5`
as "we have data but at least one container or socket had an
issue". This matches FEAT-003's exit-code semantics exactly.

### Side effects

- Triggers exactly one row in the daemon's `pane_scans` table,
  including the whole-scan-failure paths that exit `3`
  (`docker_unavailable` writes a `status='degraded'` row per
  data-model §4.2).
- Triggers zero or more upserts / touch-only / inactivate writes
  on the `panes` table inside one SQLite transaction (FR-024).
- Does not modify the FEAT-003 `containers` or `container_scans`
  tables (FR-030).
- Appends one record to `events.jsonl` only when the scan was
  degraded (FR-025); event type `pane_scan_degraded`. Healthy
  scans append nothing.
- Emits `pane_scan_started` and `pane_scan_completed` lines to
  `agenttowerd.log` (R-014). Both tokens are distinct from
  FEAT-003's `scan_started` / `scan_completed` so the lifecycle
  log can be grepped by scan kind.
- Does not open any AF_INET / AF_INET6 socket (FR-031).
- Does not invoke `docker` or `tmux` from the CLI process; only
  the daemon spawns subprocesses (R-001).

---

## C-CLI-402 — `agenttower list-panes`

### Invocation

```bash
agenttower list-panes
agenttower list-panes --active-only
agenttower list-panes --container <id-or-name>
agenttower list-panes --json
agenttower list-panes --active-only --container <id-or-name> --json
```

The three flags compose freely. `--container` accepts either a
full 64-char hex container id or an exact container name (no
substring match — that is reserved for FEAT-003's matching rule
and would muddy the query). When the supplied id-or-name does not
match any container, the result is an empty pane list and exit
code `0`, mirroring `list-containers`.

### Behavior

1. Resolve the socket path from FEAT-001 `Paths.socket`. If
   FEAT-001 is not initialized, exit `1`.
2. Connect (1 s timeout). If unreachable → exit `2` with
   `daemon-unavailable` message.
3. Send
   `{"method":"list_panes","params":{"active_only":<bool>,"container":<string|null>}}`.
   Read one response line (1 s read-timeout).
4. If envelope is `ok: false`, exit `3` with the FEAT-002 two-line
   error format.
5. Render the result and exit `0`.

`list-panes` does **not** call Docker or tmux; it reads from
SQLite only (FR-016), so no `docker_*`, `tmux_*`, `socket_*`,
`output_malformed`, or scan-related exit code is reachable here.
The command also does **not** acquire the pane-scan mutex (FR-016,
R-004), so `list-panes` returns within ~100 ms even while a slow
`scan_panes` is in flight.

### Output (stdout, default)

A header line followed by zero or more body lines, separated by
ASCII tabs (`\t`). The header is fixed:

```text
ACTIVE	FOCUSED	CONTAINER	SOCKET	SESSION	W	P	PANE_ID	PID	TTY	COMMAND	CWD	LAST_SCANNED
1	1	py-bench	/tmp/tmux-1000/default	work	0	0	%0	1234	/dev/pts/0	bash	/workspace	2026-05-06T18:01:34.692118+00:00
1	0	py-bench	/tmp/tmux-1000/default	work	0	1	%1	1235	/dev/pts/1	vim	/workspace/src	2026-05-06T18:01:34.692118+00:00
0	0	py-bench	/tmp/tmux-1000/work	scratch	0	0	%2	1300	/dev/pts/2	bash	/tmp	2026-05-06T17:55:11.418720+00:00
```

- Container ids are emitted in their full form (FEAT-003 stored
  them with `--no-trunc`); the `CONTAINER` column shows the
  container *name* by default for readability. The full container
  id and the `container_user`, `pane_title`, and `first_seen_at`
  fields are omitted from the default TSV view to keep it
  scannable; all sixteen FR-006 fields appear in `--json`.
- The `ACTIVE` column is `1` for rows whose row-level reconciliation
  flag is `active=1`, `0` otherwise (data-model §2.1 — distinct
  from `pane_active`).
- The `FOCUSED` column is `1` when this pane is the currently
  focused pane in its window (`pane_active=1`), `0` otherwise.
- Rows are ordered by
  `active DESC, container_id ASC, tmux_socket_path ASC,
  tmux_session_name ASC, tmux_window_index ASC,
  tmux_pane_index ASC` (FR-016 / R-008). The default human view
  preserves that order; ties on container_id are broken by socket,
  session, window, and pane index in turn.
- Every text column is sanitized of NUL bytes, C0 control bytes,
  embedded tabs, and embedded newlines (R-009) before emission, so
  one row stays one line of TSV no matter what tmux titles or cwds
  contained.
- When the table is empty, only the header line is emitted and the
  exit code is still `0`. Scripts can detect "no rows" via line
  count (`wc -l == 1`) or by reading `--json`.

### Output (stdout, `--json`)

Exactly one line of canonical JSON, mirroring the socket response
verbatim plus the `ok` field. Every pane object carries the full
FR-006 / data-model §2.1 field set:

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

`result.filter` is `"all"` when `params.active_only` is unset/false
and `"active_only"` when `true`. `result.container_filter` echoes
the `--container <id-or-name>` argument verbatim (or `null` when
absent) so scripts can confirm the filter was applied.

`result.panes` is always an array; empty result is `panes: []` and
exit code `0`.

### Output (stderr)

Empty on success. On failure, FEAT-002 / FEAT-003 patterns apply
unchanged.

### Exit codes

| Code | Meaning                                          |
| ---- | ------------------------------------------------ |
| `0`  | Response received and rendered.                  |
| `1`  | Pre-flight failure (FEAT-001 not initialized).   |
| `2`  | Socket missing, connect refused, or timed out.   |
| `3`  | Daemon returned a structured error.              |
| `4`  | Internal CLI error.                              |

(No code `5` here; `list-panes` is a query and cannot trigger a
degraded scan.)

### Side effects

None on success. The SQLite read runs under a short read-only
transaction; no JSONL append, no lifecycle log line, no Docker or
tmux call (FR-016).

---

## Cross-cutting CLI guarantees (FEAT-004)

- All FEAT-004 CLI invocations open **no network listener**
  (FR-031, inherited from FEAT-002 / FEAT-003). A test asserts no
  AF_INET / AF_INET6 socket is opened by either CLI command or by
  the daemon during their dispatch.
- All FEAT-004 CLI invocations exercise Docker and tmux only
  **through the daemon**, which uses the resolved adapters
  (`SubprocessDockerAdapter` from FEAT-003 plus the new
  `SubprocessTmuxAdapter` from R-001). The CLI processes
  themselves never spawn `docker` or `tmux` directly (R-017).
- The daemon resolves Docker from its inherited process `PATH` at
  scan time (FR-022); a missing or non-executable resolved binary
  maps to `docker_unavailable` and exits `3`.
- The bench user used inside `docker exec -u <bench-user>` is
  derived per scan from `containers.config_user` and falls back to
  the daemon process `$USER` (FR-020 / R-005). The numeric uid
  used to build `/tmp/tmux-<uid>/` is resolved by an in-container
  `id -u` call per scan (FR-020 / R-006).
- Human-readable output sanitizes NUL bytes, C0 control bytes, and
  embedded tabs/newlines from every tmux-derived string before
  printing (R-009). `--json` output uses standard JSON escaping
  with the same bounded values that the socket API persisted to
  SQLite.
- All paths printed or operated on resolve to absolute paths under
  the user's `opensoft/agenttower` namespace.
- Healthy pane scans produce **no records** in `events.jsonl`.
  Degraded pane scans produce exactly one (event type
  `pane_scan_degraded`, parallel to FEAT-003's
  `container_scan_degraded`).
- Both new commands ship dual output modes (default `key=value` /
  TSV-table; `--json` line-canonical) so both human users and
  shell scripts get a stable contract (constitution IV).
- `agenttower list-panes` runs concurrently with any in-flight
  `scan_panes` or `scan_containers` without blocking (FR-016 /
  FR-017): the read-only path takes its own short SQLite read
  transaction and acquires neither scan mutex.

---

## Out-of-scope (FEAT-004)

- Pane registration as an *agent* (`register_agent`,
  `set_role`, `set_capability`) — FEAT-006.
- Pane log capture and offset tracking (`attach`, log streaming) —
  FEAT-008.
- Input delivery to a pane (`send_input`, `route`) — FEAT-009.
- `agenttower scan` with no flags as a "scan everything" shortcut
  (deferred until at least one feature beyond FEAT-004 lands and
  the union of scanners is well-defined).
- `agenttower list-panes --container <substring>` substring match,
  `--session <name>` filter, or any other secondary filter beyond
  `--active-only` and exact `--container <id-or-name>`. Use
  `--json` output and `jq` for richer queries.
- Per-pane detail subcommands (`agenttower describe-pane`, etc.).
- Container-side execution of `agenttower scan --panes` or
  `agenttower list-panes` — FEAT-005 owns the in-container client.
- Secret redaction of pane titles, current commands, or current
  working directories — FEAT-007.
