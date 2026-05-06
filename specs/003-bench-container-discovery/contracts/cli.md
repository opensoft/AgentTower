# Contract: CLI additions (FEAT-003)

**Branch**: `003-bench-container-discovery` | **Date**: 2026-05-05

This contract documents the user-facing CLI surface that FEAT-003
adds on top of FEAT-001/FEAT-002. Every behavior listed here is
reachable via `subprocess.run` from a test harness; nothing here
depends on Python in-process imports.

FEAT-003 adds:

- One new `agenttower` subcommand: `scan` with mode flag
  `--containers` (the bare `agenttower scan` form is reserved for
  FEAT-004 and currently exits non-zero).
- One new `agenttower` subcommand: `list-containers` (no positional
  arguments).

Existing FEAT-001/FEAT-002 behaviors are unchanged (FR-022).

The newline-delimited JSON socket protocol used by these commands
is documented in `socket-api.md`.

---

## C-CLI-201 — `agenttower scan --containers`

### Invocation

```bash
agenttower scan --containers
agenttower scan --containers --json
```

`agenttower scan` without `--containers` prints
`error: scan requires a target flag (e.g. --containers)` to stderr
and exits `1`. This reserves the bare form for FEAT-004 (`--panes`).

### Behavior

1. Resolve the socket path from FEAT-001 `Paths.socket`. If
   FEAT-001 is not initialized, exit `1` with
   `error: agenttower is not initialized: run \`agenttower config init\``.
2. Connect to the socket with a 1 s connect-timeout. If unreachable,
   exit `2` with the FEAT-002 `daemon-unavailable` message.
3. Send `{"method":"scan_containers"}`. Read one response line
   with a 10 s read-timeout (must accommodate worst-case
   per-call Docker timeouts).
4. If the envelope is `ok: false`, exit `3` with the
   `error.message` on stderr and `code: <error.code>` on a second
   stderr line. Match FEAT-002's two-line error format.
5. If the envelope is `ok: true`, render the result and exit:
   - `0` when `result.status == "ok"`.
   - `5` when `result.status == "degraded"` (new exit code for
     this feature; documented below).

### Output (stdout, default)

Six lines, fixed order, `key=value` form:

```text
scan_id=<uuid>
status=<ok|degraded>
matched=<int>
inactive_reconciled=<int>
ignored=<int>
duration_ms=<int>
```

`duration_ms` is computed client-side from the
`completed_at` minus `started_at` timestamps in the response.
The default stdout aliases `matched_count` to `matched` and
`inactive_reconciled_count` to `inactive_reconciled` intentionally
to keep human output compact; `--json` preserves canonical field
names.

When `status=degraded`, two additional stderr lines are emitted
(stderr only, after the stdout block):

```text
error: <result.error_message>
code: <result.error_code>
```

### Output (stdout, `--json`)

Exactly one line of canonical JSON: the response's `result` object
verbatim, plus the `ok` field:

```json
{"ok":true,"result":{"scan_id":"...","started_at":"...","completed_at":"...","status":"ok","matched_count":2,"inactive_reconciled_count":0,"ignored_count":7,"error_code":null,"error_message":null,"error_details":[]}}
```

In the whole-scan-failure path (envelope `ok: false`), `--json`
emits:

```json
{"ok":false,"error":{"code":"docker_unavailable","message":"docker binary not found on PATH"}}
```

and exits `3` (matches FEAT-002's daemon-error exit code).

### Output (stderr)

Empty on the success path. On any non-zero exit, FEAT-002's
patterns apply:

| Path                          | stderr                                                          |
| ----------------------------- | --------------------------------------------------------------- |
| Not initialized (exit 1)      | `error: agenttower is not initialized: run \`agenttower config init\`` |
| Bare `scan` form (exit 1)     | `error: scan requires a target flag (e.g. --containers)`        |
| Daemon unavailable (exit 2)   | `error: daemon is not running or socket is unreachable: try \`agenttower ensure-daemon\`` |
| Daemon error (exit 3)         | Two lines: `error: <message>` then `code: <error.code>`         |
| Degraded scan (exit 5)        | Two lines: `error: <message>` then `code: <error.code>`         |
| Internal CLI error (exit 4)   | `error: internal CLI error: <reason>`                           |

### Exit codes

| Code | Meaning                                                                        |
| ---- | ------------------------------------------------------------------------------ |
| `0`  | Scan completed and `result.status == "ok"`.                                    |
| `1`  | Pre-flight failure (FEAT-001 not initialized, bare `scan` form, unsafe paths). |
| `2`  | Socket missing, connect refused, or timed out.                                 |
| `3`  | Daemon returned a structured error (envelope `ok: false`).                     |
| `4`  | Internal CLI error.                                                            |
| `5`  | Scan completed but `result.status == "degraded"`.                              |

`5` is intentionally distinct from `3`: a degraded scan is a
*successful round-trip* that nevertheless requires operator
attention. Scripts can treat `0` as "everything was clean" and `5`
as "we have data but Docker had at least one issue".

### Side effects

- Triggers exactly one row in the daemon's `container_scans`
  table, including whole-scan failures that exit `3`.
- Triggers zero or more upserts/touch-only/inactivate writes to the
  `containers` table.
- Appends one record to `events.jsonl` only when the scan was
  degraded.
- Emits `scan_started` and `scan_completed` lines to
  `agenttowerd.log`.

---

## C-CLI-202 — `agenttower list-containers`

### Invocation

```bash
agenttower list-containers
agenttower list-containers --active-only
agenttower list-containers --json
agenttower list-containers --active-only --json
```

### Behavior

1. Resolve the socket path from FEAT-001 `Paths.socket`. If
   FEAT-001 is not initialized, exit `1`.
2. Connect (1 s timeout). If unreachable → exit `2` with
   `daemon-unavailable` message.
3. Send `{"method":"list_containers","params":{"active_only":<bool>}}`.
   Read one response line (1 s read-timeout).
4. If envelope is `ok: false`, exit `3` with the FEAT-002 two-line
   error format.
5. Render the result and exit `0`.

`list-containers` does **not** call Docker; it reads from SQLite
only (R-005), so no `docker_*` exit code is reachable here.

### Output (stdout, default)

A header line followed by zero or more body lines, separated by
ASCII tabs (`\t`). The header is fixed:

```text
ACTIVE	ID	NAME	IMAGE	STATUS	LAST_SCANNED
1	f3c5e1ad...	py-bench	ghcr.io/opensoft/py-bench:latest	running	2026-05-05T18:01:34.692118+00:00
0	abc1234...	old-bench	ghcr.io/opensoft/old-bench:latest	exited	2026-05-04T11:22:33.444444+00:00
```

- Container ids are emitted in their full form (the daemon stored
  them with `--no-trunc`).
- The `ACTIVE` column is `1` for active rows, `0` for inactive
  rows; rows are ordered active-first per FR-016 / R-011.
- When the table is empty, only the header line is emitted and
  exit code is still `0`. Scripts can detect "no rows" via line
  count (`-eq 1`) or by reading `--json`.

### Output (stdout, `--json`)

Exactly one line of canonical JSON, mirroring the socket response
verbatim plus the `ok` field:

```json
{"ok":true,"result":{"filter":"all","containers":[{...}, {...}]}}
```

`--active-only` produces `"filter": "active_only"` and only rows
with `"active": true`.

### Output (stderr)

Empty on success. On failure, FEAT-002's patterns apply.

### Exit codes

| Code | Meaning                                          |
| ---- | ------------------------------------------------ |
| `0`  | Response received and rendered.                  |
| `1`  | Pre-flight failure.                              |
| `2`  | Socket missing, connect refused, or timed out.   |
| `3`  | Daemon returned a structured error.              |
| `4`  | Internal CLI error.                              |

(No code `5` here; `list-containers` cannot trigger a degraded
scan — it is a query.)

### Side effects

None on success.

---

## Cross-cutting CLI guarantees (FEAT-003)

- All FEAT-003 CLI invocations open **no network listener** (FR-021,
  inherited from FEAT-002). A test asserts no AF_INET/AF_INET6
  socket is opened by either CLI command.
- All FEAT-003 CLI invocations exercise Docker only **through the
  daemon**, which uses the resolved adapter
  (`SubprocessDockerAdapter` or `FakeDockerAdapter` per R-008).
  The CLI processes themselves never spawn `docker` directly.
- The daemon resolves Docker from its inherited process `PATH` at scan
  time and treats a shadowed Docker binary as outside the FEAT-003
  threat model for the trusted host user. Missing or non-executable
  Docker maps to `docker_unavailable`.
- Human-readable output sanitizes tabs, newlines, NUL bytes, and
  terminal control bytes from Docker-derived strings. `--json` output
  uses JSON escaping and the same bounded error-message values as the
  socket API.
- All paths printed or operated on resolve to absolute paths under
  the user's `opensoft/agenttower` namespace.
- Healthy scans produce **no records** in `events.jsonl`. Degraded
  scans produce exactly one (event type
  `container_scan_degraded`).
- Both new commands ship dual output modes (default `key=value` /
  TSV-table; `--json` line-canonical) so both human users and
  shell scripts get a stable contract.

---

## Out-of-scope (FEAT-003)

- `agenttower scan --panes` (FEAT-004).
- `agenttower scan` with no flags as a "scan everything" shortcut
  (deferred until at least FEAT-004 lands and the union of
  scanners is well-defined).
- `agenttower list-containers --include-stopped` or any non-bench
  matching surface (FEAT-007+ if ever).
- Per-container detail subcommands (`agenttower describe-container`
  etc.); use `--json` output and `jq` for now.
