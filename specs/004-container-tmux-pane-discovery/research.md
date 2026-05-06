# Phase 0 Research: Container tmux Pane Discovery

**Branch**: `004-container-tmux-pane-discovery` | **Date**: 2026-05-06

This document records the design decisions made during Phase 0 of
the plan. Each decision answers a `NEEDS CLARIFICATION` (none
survived spec writing — the spec is unusually concrete) or pins a
downstream-affecting choice that the plan summary references.
FEAT-004 inherits FEAT-003's decisions on Docker access, subprocess
hardening, and audit boundaries; this document only records what
*differs* from or *extends* FEAT-003.

---

## R-001 — In-container access surface: `docker exec` subprocess, not Docker SDK or tmux libraries

**Decision**: Wrap the closed set of in-container commands behind a
`TmuxAdapter` Protocol with two implementations:
`SubprocessTmuxAdapter` (production) and `FakeTmuxAdapter` (tests).
The real adapter resolves `docker` with `shutil.which("docker")`
against the daemon's inherited process `PATH` at scan time (reusing
FEAT-003's R-001 / R-014 path-resolution policy; FR-022) and passes
the resolved path as `argv[0]`. Every invocation uses
`subprocess.run(..., shell=False, text=True, check=False,
timeout=5.0)` with typed argv only. No third-party Docker SDK or
libtmux binding is added. The closed argv set per scan is:

1. `docker exec -u <bench-user> <container-id> id -u`
2. `docker exec -u <bench-user> <container-id> ls -1 -- /tmp/tmux-<uid>`
3. `docker exec -u <bench-user> <container-id> tmux -S /tmp/tmux-<uid>/<socket-name> list-panes -a -F <format>`

All five user-supplied tokens (`<bench-user>`, `<container-id>`,
`<uid>`, `<socket-name>`, `<format>`) are argv elements only;
nothing is interpolated into a shell string (FR-021,
constitution III).

**Rationale**:
- Constitution caps runtime deps at the Python standard library; no
  business case justifies adding a Docker SDK or libtmux for a
  three-command surface.
- FEAT-003 already proved the subprocess adapter pattern works and
  is testable through an env-var-driven fake (FEAT-003 R-008).
- libtmux talks to the local tmux server, not a server inside a
  container, so it would not work for the in-container case
  anyway.

**Alternatives considered**:
- Reuse FEAT-003's `DockerAdapter` Protocol directly. Rejected:
  the `DockerAdapter` already has tightly-scoped methods
  (`list_running()`, `inspect()`); FEAT-004 needs
  per-container `id -u`, per-container directory listing, and
  per-socket `tmux list-panes`, all of which are different
  operations and would muddy the existing abstraction. A separate
  `TmuxAdapter` Protocol mirrors the FEAT-003 split cleanly.
- A single-shot in-container shell script that does
  `id -u`, `ls /tmp/tmux-$(id -u)/`, and `tmux list-panes` in one
  `docker exec`. Rejected: would need shell quoting (FR-021
  forbids), and per-stage error attribution becomes ambiguous
  (was it `id -u` that failed? `ls`? `tmux`?).

---

## R-002 — `tmux list-panes` format string

**Decision**: Use the format string from `docs/architecture.md` §7
verbatim, plus one trailing field for `pane_active`. The full argv
form is:

```text
tmux -S <socket-path> list-panes -a -F
"#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t#{pane_pid}\t#{pane_tty}\t#{pane_current_command}\t#{pane_current_path}\t#{pane_title}\t#{pane_active}"
```

The parser splits on `\t` and expects exactly 10 fields per row.
Rows with fewer fields are flagged as `output_malformed` and
counted in the degraded result rather than persisted (spec edge
case: "old tmux server, fields missing"). Tabs are the field
delimiter because tmux strips literal tabs from titles by default
and the parser sanitizes tabs out of all persisted fields anyway
(FR-023).

**Rationale**:
- The architecture doc pins
  `#{session_name}:#{window_index}.#{pane_index}\t...` as the
  canonical shape; FEAT-004 expands this into individually-tabbed
  fields so the parser does not need to re-split on `:` and `.`,
  which appear naturally in session names and tmux output.
- `#{pane_active}` is a 0/1 flag indicating whether the pane is
  the currently active pane in its window; persisting it lets
  `agenttower list-panes` report "currently focused" without
  another tmux call.
- 10 fields keeps every row recoverable from a single `\t.split()`
  pass with no quoting layer.

**Alternatives considered**:
- JSON output (`tmux list-panes -F '{...}'`): rejected; tmux's
  format does not produce strictly-valid JSON when pane fields
  contain `"` or `\`.
- `tmux display-message -p` per pane: rejected; one subprocess
  per pane explodes the worst-case timeout budget (5 s × N
  panes).

---

## R-003 — Per-call subprocess timeout: 5 seconds

**Decision**: Pass `timeout=5.0` to every `subprocess.run`
invocation in `SubprocessTmuxAdapter` and translate the resulting
`subprocess.TimeoutExpired` into a `TmuxError(code="docker_exec_timeout",
container_id=..., socket_path=...)`. The adapter relies on
Python's `subprocess.run` timeout behavior, which kills and waits
for the child process before raising; tests assert the timeout
path is normalized rather than leaked. **Termination escalation**:
if the implicit kill-and-wait that `subprocess.run` performs
itself raises `OSError` or hangs (the kernel cannot reap the
child), the adapter MUST attempt one explicit
`process.terminate(); process.wait(timeout=1.0)` cycle. If that
secondary 1 s grace period also expires (or itself raises), the
adapter MUST log the unrecovered child to the lifecycle log
(closed-set message only — no raw stderr), MUST stop attempting
to recover that child, and MUST raise
`TmuxError(code="internal_error", ...)` so the per-scope error
escalates to `internal_error` at the reconciler boundary while
the daemon stays alive and the rest of the scan continues. This
escalation path is exercised by the FakeTmuxAdapter via a
dedicated injection knob (`unrecoverable_child=True`).

**Rationale**:
- Pinned by spec FR-018 — same per-call budget as FEAT-003 (R-004),
  which keeps the operator mental model consistent: "any single
  Docker subprocess can hang up to 5 s before it is killed."
- 5 s is enough to absorb cold WSL Docker startup latency without
  letting a wedged pane scan stall the daemon for minutes.
- `docker_exec_timeout` is one of the closed-set codes named in
  FR-019.

**Alternatives considered**:
- 3 s (too aggressive for cold WSL), 10 s (delays degraded
  recovery). Both rejected by parity with FEAT-003's pinned
  budget.

---

## R-004 — Pane-scan mutex: separate `threading.Lock`, independent of FEAT-003

**Decision**: `PaneDiscoveryService` owns its own
`threading.Lock`. Every call to `scan()` acquires the lock with
`acquire(blocking=True)`, runs the scan, writes the SQLite
reconciliation in one `BEGIN IMMEDIATE / COMMIT`, and releases. The
new `scan_panes` socket method handler is the only caller in
production. The mutex is independent of the FEAT-003
container-scan mutex; the two scans MAY proceed concurrently
(FR-017). Concurrent pane-scan callers serialize behind the same
in-process lock with no FIFO fairness guarantee beyond the
runtime's lock scheduling. The lock is in-process only and is
recreated after daemon restart; an in-flight scan is abandoned if
the daemon exits.

**Rationale**:
- Pinned by spec FR-017. Two scans against the same SQLite writer
  cannot share the FEAT-003 mutex, but they CAN run in parallel
  because they touch disjoint tables (containers vs panes), and
  both writers funnel into one SQLite file via the daemon-owned
  connection. SQLite's WAL handles concurrent writers from one
  process safely, but only when each writer's transaction is
  bounded; the two mutexes give the daemon that boundedness.
- An in-process lock is the right primitive: the daemon is the
  single SQLite writer (constitution principle I) so no
  inter-process coordination is needed.
- `list_panes` is a read-only path that takes a separate short
  read transaction; it MUST NOT contend on either scan mutex
  (FR-016), so readers stay fast even during a slow scan.

**Alternatives considered**:
- Reuse the FEAT-003 mutex for all scans. Rejected: forces
  serialized container and pane scans even though they're
  independent in scope. FR-017 explicitly allows them to overlap.
- Reject second pane-scan with `scan_in_progress`. Rejected:
  FEAT-003 chose blocking serialization in clarification Q1, and
  matching that choice here keeps the operator model simple ("a
  second scan blocks until the first completes; both then return
  their own complete result").
- Async `asyncio.Lock`. Rejected: would force restructuring the
  FEAT-002 threading server.

---

## R-005 — Bench user resolution

**Decision**: For each active container, derive the bench user used
in `docker exec -u <bench-user>` from FEAT-003's persisted
`containers.config_user` column. When that column is `NULL`
(FEAT-003 reports it as `None` if `Config.User` was empty), fall
back to `os.environ.get("USER")` of the daemon process; when that
also returns empty (rare on developer workstations but possible
under some service managers / sandboxes), fall back to
`pwd.getpwuid(os.getuid()).pw_name`. If all three return empty —
in practice only when the daemon is somehow running with a uid
that has no `/etc/passwd` entry, e.g., inside a stripped container
context that does not apply to AgentTower's host deployment — the
container scan is skipped with a per-container
`bench_user_unresolved` error and is treated as
`tmux_unavailable` for FR-010 preservation. If
`containers.config_user` carries a `:uid` form (e.g., `app:1001`),
the resolver splits on the first `:` and uses the left-hand
component; the right-hand `uid` is ignored at the host-side
resolution step because the container-side `id -u` is the
authoritative source for `/tmp/tmux-<uid>/`. The bench user is
loaded once at scan start (a SQLite read), not per `docker exec`
invocation.

**Rationale**:
- FR-020 pins the resolution order. Hardcoding `1000` was
  explicitly rejected by the spec assumption "Treating `1000` as a
  hardcoded uid is rejected because production bench users vary
  across machines."
- A daemon-process `USER` fallback is what the architecture doc
  §7 already documents (`docker exec -u "$USER"`).
- Per-container override via `[panes]` config block is out of
  scope for FEAT-004 (spec assumption); a future feature can add
  one without breaking this resolution order.

**Alternatives considered**:
- Always use `os.environ["USER"]` and ignore inspect data.
  Rejected: containers may run with a different `Config.User`
  (e.g., `root` images, `app` images) and the host user may not
  exist inside the container.
- Make the fallback fail rather than read `os.environ`. Rejected:
  developer machines often run bench containers with no explicit
  `USER` set; failing here would prevent any scan from working.

---

## R-006 — Numeric uid resolution: in-container `id -u`, not assumed

**Decision**: Resolve the numeric uid that builds
`/tmp/tmux-<uid>/` by calling
`docker exec -u <bench-user> <container-id> id -u` and parsing the
single integer line. Cache the result in-memory for the duration
of the scan only (one entry per container). A non-numeric or
empty stdout, a non-zero exit, or a 5 s timeout produces a
per-container `output_malformed` / `docker_exec_failed` /
`docker_exec_timeout` error and skips the rest of that container's
scan (no socket-listing call, no list-panes call) without crashing
the daemon.

**Rationale**:
- Pinned by FR-020. The uid varies across machines (`1000`,
  `1001`, `0`, ...). Hardcoding any value is rejected by the
  spec.
- One `id -u` call per container is bounded by the same 5 s
  timeout as the rest of the per-call budget; the worst-case
  total overhead across all active bench containers is
  `C × 5 s`.
- Caching only within one scan keeps the data fresh on the next
  scan (no stale uid surviving a container rebuild).

**Alternatives considered**:
- Read the uid from the container's `/etc/passwd` via `cat`.
  Rejected: would require parsing nss output and shell-quoting
  the bench user; `id -u` is a one-shot integer.
- Parse it from FEAT-003's `inspect_json` (e.g.,
  `Config.User=user:1001`). Rejected: `Config.User` is often a
  name only, not `user:uid`, and inspect would have to be
  pre-resolved on every scan.

---

## R-007 — Socket discovery under `/tmp/tmux-<uid>/`

**Decision**: After resolving the uid, run
`docker exec -u <bench-user> <container-id> ls -1 -- /tmp/tmux-<uid>`
inside the container. Each line of stdout is a candidate socket
name. The literal name `default` is treated as the implicit
default socket when present. Every other regular file is treated
as an additional candidate socket. Subdirectories, names beginning
with `/` (defensive: `ls -1` against a directory should never emit
those, but if it does the parser drops them), and lines that do
not parse as plain socket basenames are skipped without failing
the scan (FR-004). If the directory is missing (`ls` exits with
code 2 or stderr matches `no such file`), the per-container error
is `socket_dir_missing` and the spec's FR-010 "tmux unavailable"
preservation rule applies. If `ls` fails with permission denied,
the per-container error is `socket_unreadable` and the same
preservation rule applies.

**Rationale**:
- `ls -1` produces one basename per line, no metadata, no shell
  globbing. Combined with `-- /tmp/tmux-<uid>` (the `--` ends
  options) the argv is shell-injection-safe even if the uid
  somehow surfaced unusual characters (it can't — `id -u` returns
  digits or fails).
- Distinguishing `socket_dir_missing` from `socket_unreadable` on
  exit-code/stderr signals lets the operator triage the
  difference without parsing raw stderr; both still fall under
  the spec's "tmux unavailable" preservation rule (FR-010).
- The literal `default` socket name is the tmux convention for
  the implicit default server; treating it as such matches what
  the architecture doc §7 documents.

**Alternatives considered**:
- `find /tmp/tmux-<uid> -maxdepth 1 -type s -printf ...`.
  Rejected: requires GNU find, not in every minimal bench image.
- `python -c 'import os; ...'`. Rejected: forces a Python
  interpreter inside the container.
- `docker exec ... ls -F`. Rejected: `-F` decorates names with a
  trailing `=` for sockets, making the parser's job harder.

---

## R-008 — Pane reconciliation: per-(container, socket), composite key

**Decision**: Pure function in
`discovery/pane_reconcile.py`. Given:
- `prior_panes`: every existing `panes` row indexed by
  composite key `(container_id, tmux_socket_path,
  tmux_session_name, tmux_window_index, tmux_pane_index,
  tmux_pane_id)`.
- `socket_results`: a dict `{(container_id, socket_path) →
  SocketScanOutcome}` where `SocketScanOutcome` is one of:
  - `Ok(panes=[ParsedPane, ...])` — successful per-socket scan.
  - `Failed(error_code, error_message)` — failed per-socket scan
    on a container whose tmux is otherwise reachable.
- `tmux_unavailable_containers`: set of `container_id` values
  whose tmux scope is unknown (no socket dir, all sockets
  failed, no `id -u` result, etc.). FR-010 preserves prior
  `active` flags for these.
- `inactive_containers`: set of `container_id` values whose
  `containers.active = 0` at scan start. FR-009 inactivates all
  prior panes for these without invoking `docker exec`.
- `now_iso`: scan completion timestamp.

Returns a `PaneReconcileWriteSet` with:
- `upserts`: full row writes for every parsed `ParsedPane` in
  every successful socket scan.
- `touch_only`: composite keys whose only change is
  `last_scanned_at` (FR-010 preservation set + FR-011 sibling-
  socket preservation set).
- `inactivate`: composite keys to flip `active = 0` (panes from
  `Ok(panes=[...])` results that were previously active and are
  no longer in that socket's parsed list, plus FR-009's cascade
  set).
- Per-pane truncation notes (one entry per truncated field;
  not persisted to `panes`, only to the scan result).
- Aggregate counters: `panes_seen`, `panes_newly_active`,
  `panes_reconciled_to_inactive`,
  `containers_skipped_inactive`,
  `containers_tmux_unavailable`.

**Rationale**:
- Pinned by FR-007 (composite key) and FR-008 / FR-010 / FR-011
  (per-socket reconciliation). A pure function isolates the
  trickiest logic from SQLite, making it unit-testable.
- The data flow mirrors FEAT-003's `reconcile()` so reviewers
  recognize the shape; the differences (per-socket scope,
  tmux_unavailable preservation, cascade) are precisely the
  clarifications spec FR-009 / FR-010 / FR-011 demand.

**Alternatives considered**:
- Reconcile per-container only. Rejected: contradicts FR-011
  ("Reconciliation is per-(container, socket) tuple, not
  per-container").
- Use `(tmux_pane_id,)` as the primary identity. Rejected:
  pane ids reuse across server restarts (spec edge case "A
  pane id (`%N`) is reused after a tmux server restart, but
  the new pane is in a different session/window"). FR-007
  pins the composite key.

---

## R-009 — Field sanitization & truncation

**Decision**: Every text field destined for SQLite, JSONL, socket
responses, CLI JSON, or the lifecycle log is run through a
`sanitize_text(value, max_length)` helper that:
1. Drops NUL bytes (`\x00`) entirely.
2. Drops every byte in the C0 control range (`\x01`–`\x08`,
   `\x0b`–`\x1f`, `\x7f`) **except** `\t` and `\n` for fields
   where those are meaningful (none currently — pane fields
   strip both).
3. Replaces every embedded `\t` and `\n` in pane fields with a
   single space (so the human-readable TSV `list-panes` output
   stays one row per pane).
4. Truncates the result to `max_length` characters
   (UTF-8-aware, not bytes).
5. Returns `(value, truncated: bool)` so the scan result can
   record per-pane truncation notes.

Per-field maximums (FR-023):
- `pane_title`: 2048
- `pane_current_command`: 2048
- `pane_current_path`: 4096
- All other text fields (`tmux_socket_path`, `tmux_session_name`,
  `pane_tty`, etc.): 2048

Truncation does NOT reject the pane row (FR-023). Truncation
notes accumulate per pane and surface in the scan result's
`pane_truncations` list.

**Rationale**:
- Pinned by FR-023. NUL bytes break both SQLite TEXT (silent
  truncation in some bindings) and JSON (illegal in keys/values),
  so stripping them is mandatory before either layer.
- Stripping C0 control bytes prevents terminal-control-byte
  injection through pane titles into the operator's terminal
  when they `cat` `events.jsonl` or run `agenttower list-panes`.
- Replacing `\t` and `\n` with single spaces (rather than
  dropping them) preserves token boundaries in the human view.
- The 4096 cwd cap is double the title cap because deep monorepo
  paths legitimately exceed 2048 (spec assumption).

**Alternatives considered**:
- Reject the pane row outright on any oversize field. Rejected:
  FR-023 explicitly says "Oversized values MUST be truncated
  rather than rejecting the pane row."
- No sanitization, rely on JSON encoder. Rejected: JSON encoder
  does not strip C0 control bytes, and SQLite TEXT does not
  enforce UTF-8 constraints.

---

## R-010 — `pane_scans` row + degraded JSONL audit

**Decision**: Each pane scan writes one row to a new
`pane_scans` table. Degraded scans additionally append one
record to the existing FEAT-001 `events.jsonl` file with event
type `pane_scan_degraded`, mirroring FEAT-003's
`container_scan_degraded` shape. Healthy scans do **not** write
to `events.jsonl` (FR-025).

Schema (v3 migration):
```sql
CREATE TABLE pane_scans (
    scan_id                    TEXT PRIMARY KEY,
    started_at                 TEXT NOT NULL,
    completed_at               TEXT NOT NULL,
    status                     TEXT NOT NULL CHECK(status IN ('ok','degraded')),
    containers_scanned         INTEGER NOT NULL,
    sockets_scanned            INTEGER NOT NULL,
    panes_seen                 INTEGER NOT NULL,
    panes_newly_active         INTEGER NOT NULL,
    panes_reconciled_inactive  INTEGER NOT NULL,
    containers_skipped_inactive INTEGER NOT NULL,
    containers_tmux_unavailable INTEGER NOT NULL,
    error_code                 TEXT,
    error_message              TEXT,
    error_details_json         TEXT
);
```

`scan_id` is a UUID4 string; timestamps are ISO-8601 UTC with
microsecond precision (matches FEAT-002 / FEAT-003).

**Rationale**:
- Pinned by FR-012. SQLite gives scriptable history; JSONL is the
  existing audit channel for noteworthy events; healthy scans are
  too frequent to flood it.
- The counter set is the union of every counter the spec calls
  out in FR-012 / SC-001. `error_code` is the representative
  closed-set code (the first per-container or per-socket failure
  in scan order); `error_details_json` carries one entry per
  affected `(container, socket?)` tuple.
- A degraded pane scan appends *exactly one* JSONL record per
  scan_id (FR-028); convergent re-scans against unchanged state
  do not duplicate JSONL records but DO produce distinct
  `pane_scans` rows (FR-028).

**Alternatives considered**:
- Per-pane scan history table (`pane_scan_observations`).
  Rejected: YAGNI; FEAT-008 will own the events pipeline.
- Reuse FEAT-003's `container_scans` table with an extra column
  for "scan kind". Rejected: muddies the schema and forces
  FEAT-003 readers to filter; a separate table is cleaner.

---

## R-011 — Closed error code set for the new socket methods

**Decision**: Extend FEAT-003's closed code set with seven new
codes. The new methods can return one of:

| code                        | Meaning                                                                                   |
| --------------------------- | ----------------------------------------------------------------------------------------- |
| `bad_json`                  | (existing) bytes weren't UTF-8 JSON                                                       |
| `bad_request`               | (existing) envelope or params invalid                                                     |
| `unknown_method`            | (existing) method not in the dispatch table                                               |
| `request_too_large`         | (existing) line over 64 KiB                                                               |
| `internal_error`            | (existing) unhandled daemon exception (incl. SQLite scan-tx rollback)                     |
| `docker_unavailable`        | (FEAT-003) `docker` binary missing or non-executable on the daemon's PATH at scan time    |
| `tmux_unavailable`          | NEW — one container has no `tmux` binary on its PATH                                      |
| `tmux_no_server`            | NEW — `tmux list-panes` exited with the "no server running" condition for every socket    |
| `socket_dir_missing`        | NEW — `/tmp/tmux-<uid>/` does not exist inside the container                              |
| `socket_unreadable`         | NEW — `/tmp/tmux-<uid>/` exists but cannot be listed (permission denied or similar)       |
| `docker_exec_failed`        | NEW — non-zero exit from a `docker exec` payload that is not a known specific code        |
| `docker_exec_timeout`       | NEW — `subprocess.TimeoutExpired` after 5 s on any `docker exec` call                     |
| `output_malformed`          | NEW — `id -u`, socket-listing, or `tmux list-panes` output cannot be parsed               |
| `bench_user_unresolved`     | NEW — host-side bench user resolution (config_user → $USER → getpwuid) yielded empty (FR-020) |

`tmux_*`, `socket_*`, `output_malformed`, `docker_exec_failed`,
and `docker_exec_timeout` only ever appear in `pane_scans.error_code`
or in per-`(container, socket?)` entries of
`error_details_json` / socket `result.error_details`. The
top-level socket envelope's `error.code` is `docker_unavailable`
only (when `shutil.which("docker")` returns nothing); every other
failure produces an `ok:true` envelope with
`result.status = "degraded"` and per-entry detail. This matches
FEAT-003's whole-scan vs partial-degraded asymmetry exactly
(FEAT-003 R-014).

**Rationale**:
- FEAT-002 / FEAT-003 use a closed error-code set for the same
  reason (forward-compatible client parsing, machine-friendly).
  Extending the set rather than redefining keeps FEAT-002 /
  FEAT-003 clients unbroken (FR-030).
- Distinguishing `tmux_unavailable` (no binary) from
  `tmux_no_server` (binary present, no live server) matters for
  the FR-010 preservation rule: both are "tmux unavailable" for
  reconciliation, but the operator-facing diagnosis differs.
- `output_malformed` covers tmux servers that honor the format
  string only partially (spec edge case: "old tmux server, fields
  missing").

---

## R-012 — Test seam for the tmux adapter

**Decision**: The daemon resolves which tmux adapter to
instantiate by checking
`os.environ.get("AGENTTOWER_TEST_TMUX_FAKE")` at startup. If set,
it loads a `FakeTmuxAdapter` from a JSON fixture path named by
the env var. Otherwise it instantiates `SubprocessTmuxAdapter`.
This mirrors FEAT-003's `AGENTTOWER_TEST_DOCKER_FAKE` exactly
(FEAT-003 R-008). Both env vars can be set simultaneously so the
daemon's container scan AND pane scan are both fake-driven during
integration tests.

The fake fixture format is per-container and per-socket:

```json
{
  "containers": {
    "<container-id>": {
      "uid": "1000",
      "id_u_failure": null,
      "socket_dir_missing": false,
      "sockets": {
        "default": [
          {"session_name": "...", "window_index": 0, "pane_index": 0,
           "pane_id": "%0", "pane_pid": 1234, "pane_tty": "/dev/pts/0",
           "pane_current_command": "bash", "pane_current_path": "/workspace",
           "pane_title": "...", "pane_active": true}
        ],
        "work": {"failure": {"code": "tmux_no_server", "message": "..."}}
      }
    }
  }
}
```

The fixture explicitly supports per-container failures
(`id_u_failure`, `socket_dir_missing`) and per-socket failures
(`failure: {code, message}`) so every spec edge case has a
corresponding fixture path.

**Rationale**:
- Integration tests already spawn the daemon as a subprocess
  (FEAT-002 / FEAT-003 pattern). Passing the fake adapter through
  `os.environ` avoids any import-time monkeypatching across
  process boundaries.
- The fixture shape mirrors the failure set directly so a test
  author can express "this container has no socket dir but
  another has two sockets, one of which fails" without writing
  Python adapter glue per test.

**Alternatives considered**:
- CLI flag (`agenttowerd run --tmux-fake <path>`). Rejected:
  leaks a test surface into the production CLI.
- Patch `subprocess.run`. Rejected: doesn't work across the
  spawned daemon process.
- One env var that drives both Docker and tmux fakes. Rejected:
  the two fakes have unrelated fixture shapes; one var per
  adapter keeps the seam orthogonal.

---

## R-013 — CLI surface (new subcommands)

**Decision**:
- `agenttower scan --panes [--json]`: a new mode flag on the
  existing FEAT-003 `scan` subcommand. `--containers` and
  `--panes` may be combined in one invocation (`agenttower scan
  --containers --panes`); when both are passed, the CLI calls
  `scan_containers` first, then `scan_panes`, and emits two
  scan-summary blocks (default mode) or two JSON lines
  (`--json`). When neither flag is passed, the existing FEAT-003
  error message ("scan requires a target flag (e.g.
  --containers)") is updated to include `--panes` in the
  example.
- `agenttower list-panes [--active-only] [--container <id-or-name>] [--json]`:
  standalone subcommand. `--active-only` filters to
  `active = 1`. `--container` filters by container id (full
  match) or container name (exact match). When the filter
  matches no container, the result is an empty pane list with
  exit code `0` (matches `list-containers` semantics).

**Rationale**:
- Architecture doc §20 lists `agenttower scan` as singular.
  Combining `--containers` and `--panes` in one invocation lets
  developers refresh the whole registry with one command, which
  is the most common case after starting a new bench container.
- `list-panes` is named in the architecture doc §20; we ship it
  standalone (not under `scan`) because it is a query, not an
  action.
- `--container <id-or-name>` matches the architecture doc's
  expectation that operators reference containers by name as
  often as by id, and FEAT-003 already persists both.

**Alternatives considered**:
- Bare `agenttower scan` triggers both. Rejected: would change
  FEAT-003's behavior (FR-030).
- A separate `agenttower panes` umbrella. Rejected: doesn't
  match the architecture doc's flat verb list.
- `--container <id>` only (no name). Rejected: ergonomically
  worse for the most common case (developers know `py-bench`,
  not the full hash).

---

## R-014 — Lifecycle log additions

**Decision**: The daemon's existing TSV lifecycle log
(`<LOGS_DIR>/agenttowerd.log`) gains two new event tokens:
- `pane_scan_started` — emitted after `PaneDiscoveryService.scan`
  acquires the pane mutex, before any `docker exec` call.
  Columns: `<ts>\tpane_scan_started\tscan_id=<uuid>`.
- `pane_scan_completed` — emitted after the SQLite pane-scan
  transaction commits and after any degraded JSONL append is
  attempted; columns:
  `<ts>\tpane_scan_completed\tscan_id=<uuid>\tstatus=<ok|degraded>\tcontainers=<int>\tsockets=<int>\tpanes_seen=<int>\tnewly_active=<int>\tinactivated=<int>\tskipped_inactive=<int>\ttmux_unavailable=<int>`.

Degraded scans append one extra column: `error=<code>`.

The existing six FEAT-002 tokens
(`daemon_starting`, `daemon_ready`, etc.) and FEAT-003's two
tokens (`scan_started`, `scan_completed`) are not modified; they
remain authoritative for FEAT-003 container scans.

**Rationale**:
- Keeps the FEAT-002 lifecycle log as the single source of truth
  for daemon-visible activity.
- Distinct token names (`pane_scan_*`) prevent operators from
  conflating pane-scan rows with FEAT-003 container-scan rows
  when grepping the log.

Security boundary: lifecycle rows MUST NOT include raw tmux
output, raw `docker exec` stderr beyond the bounded message, raw
environment values, raw pane titles or cwds, or container names
beyond the single closed-set error code. They carry only scan id,
aggregate counts, status, and the closed error code.

Write order requirement: `pane_scan_started` is emitted after the
mutex is acquired and before any subprocess call. The SQLite scan
transaction commits before the degraded JSONL event is appended.
`pane_scan_completed` is emitted after the SQLite commit and JSONL
append attempt, immediately before the socket response is
returned.

---

## R-015 — Scan transaction and side-effect failure handling

**Decision**: The SQLite transaction that writes `pane_scans` and
all `panes` mutations is the authoritative commit boundary. If it
fails, the transaction rolls back, no JSONL degraded event is
appended, the pane-scan mutex is released, and the caller
receives `internal_error`. If the SQLite transaction commits but
the degraded JSONL append or `pane_scan_completed` lifecycle
emit fails, the committed row is not rolled back; the caller
receives `internal_error` (post-commit side-effect failure), and
the daemon stays alive. This mirrors FEAT-003 R-018 verbatim.

**Rationale**:
- SQLite is the durable source of truth for scan history.
  Rolling back after an external append/log failure is impossible
  once the SQLite commit has succeeded, so the failure is
  surfaced clearly without pretending the scan did not happen.
- Mirroring FEAT-003 here keeps the operator mental model
  consistent: a `pane_scans` row exists for every scan_id the
  daemon ever started, even if the audit append failed.

---

## R-016 — Schema migration v2 → v3

**Decision**: `state/schema.py` bumps `CURRENT_SCHEMA_VERSION`
to `3`. `_apply_pending_migrations` already runs each pending
`_apply_migration_vN` step under a single transaction (FEAT-003
R-012); FEAT-004 adds `_apply_migration_v3` that creates the
two new tables (`panes`, `pane_scans`) and their indexes. The
v3 migration touches no existing FEAT-003 table. An otherwise-empty
v2 database receives both new tables and bumps `schema_version`
to `3`. A daemon running this build against a v3 SQLite database
opens cleanly with no migration applied. A daemon running this
build against a v4 (future) SQLite database refuses to start
(FR-029) — schema downgrade is not supported.

**Rationale**:
- FEAT-003 R-012 proved the migration-runner pattern. Reusing it
  here keeps the schema-evolution surface small and consistent.
- The v2 → v3 step is purely additive (no column changes on
  existing tables, FR-030).
- Idempotent re-open is guaranteed by the existing `IF NOT
  EXISTS` guards on every `CREATE TABLE` / `CREATE INDEX` in
  the migration body.

**Alternatives considered**:
- Drop and recreate on version mismatch. Rejected: destroys data.
- Defer migration runner enhancements to a future feature.
  Rejected: nothing new is needed; the runner already supports
  v_n → v_{n+1} dispatch.

---

## R-017 — Test budget and SC-009 verification

**Decision**: All FEAT-004 integration tests run with both
`AGENTTOWER_TEST_DOCKER_FAKE` and `AGENTTOWER_TEST_TMUX_FAKE` set
so neither `docker` nor `tmux` is ever invoked (FR-034, SC-009).
The harness includes
`tests/integration/test_cli_scan_panes_no_real_docker.py` which:
1. Asserts both env vars are set in `os.environ` at collection
   time.
2. Monkeypatches `shutil.which` and `subprocess.run` for the
   duration of the session and asserts neither is called with
   `"docker"` or `"tmux"` as `argv[0]`.

The 5 s timeout path is exercised with a `FakeTmuxAdapter` that
simulates `subprocess.TimeoutExpired` directly, not by sleeping;
this keeps the test suite well under a second per scenario while
still verifying the timeout normalization code path.

**Rationale**:
- Hard guards on the no-real-Docker/tmux constraint protect
  against accidental regressions.
- Fake-adapter-driven timeout simulation is the same pattern
  FEAT-003 used (R-016) and keeps test latency predictable.

---

## R-018 — Sensitive-field and response-size boundary

**Decision**: Persist only the pane fields enumerated in FR-006:
`container_id`, `container_name`, `container_user`,
`tmux_socket_path`, `tmux_session_name`, `tmux_window_index`,
`tmux_pane_index`, `tmux_pane_id`, `pane_pid`, `pane_tty`,
`pane_current_command`, `pane_current_path`, `pane_title`,
`pane_active`, `first_seen_at`, `last_scanned_at`. Raw
`tmux list-panes` output, raw `docker exec` stderr beyond the
bounded message, raw environment values, and raw inspect data
are not persisted in any FEAT-004 table or audit channel.
Per-`(container, socket)` failure messages are bounded to 2048
characters after sanitization before they enter SQLite, JSONL,
logs, or socket responses (FR-026, R-009).

FEAT-002's 64 KiB request-line cap remains a request-only cap;
FEAT-004 keeps responses small by bounding pane field lengths
(R-009) and does not add a response-size error code. With the
expected scale (≤ 20 active containers × ≤ 30 panes each ×
≤ 4096 chars per cwd), a worst-case `list_panes` response is
on the order of a few hundred kilobytes, well within reasonable
limits for a single Unix-socket read on a developer workstation.

**Rationale**:
- FEAT-004 is a local host-user tool, so pane titles and cwds
  remain visible until FEAT-007 redaction. The per-field bounds
  prevent accidental persistence of multi-megabyte pane titles
  or cwds.
- Mirroring FEAT-003 R-017 here keeps the operator threat model
  unchanged: trusted host user, untrusted in-container data,
  bounded but unredacted persistence.

**Alternatives considered**:
- Redact pane titles and cwds now. Desirable, but FEAT-007 owns
  reusable redaction policy. Deferred.
- Add socket pagination/response-size errors. Unnecessary at
  the MVP scale. Deferred.
