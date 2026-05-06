# Quickstart: Container tmux Pane Discovery

**Branch**: `004-container-tmux-pane-discovery` | **Date**: 2026-05-06

End-to-end CLI walkthrough of FEAT-004 against a real Docker
daemon and a real bench container running tmux. This document is
the canonical "kick the tires" script for both reviewers and
operators.

All commands run on the host. There is no in-container step in
FEAT-004 (FEAT-005 owns the bench-side CLI).

---

## 0. Prerequisites

- FEAT-001 initialized: `agenttower config init` has been run at
  least once and
  `~/.local/state/opensoft/agenttower/agenttower.sqlite3` exists.
- FEAT-002 daemon reachable: `agenttower status` returns
  `alive=true`. `agenttower status` should also report
  `schema_version=3` after FEAT-004 lands; if it still reports
  `schema_version=2`, restart the daemon (`agenttower stop-daemon
  && agenttower ensure-daemon`) so the v2→v3 migration runs.
- FEAT-003 has discovered at least one bench container:
  `agenttower scan --containers` ran successfully and
  `agenttower list-containers --active-only` shows at least one
  row. FEAT-004 reads the active container set from SQLite at
  scan start (FR-002); it does not re-run the FEAT-003 scan.
- The bench container has `tmux` on its `PATH` and at least one
  live tmux session inside it.
- Docker installed and the host user can run `docker exec`
  without `sudo`.

If `agenttower status` returns `daemon-unavailable`, run
`agenttower ensure-daemon` first.

---

## 1. Default scan against one bench container

Start a bench container and a tmux session inside it:

```bash
$ docker run -d --name py-bench ghcr.io/opensoft/py-bench:latest sleep 3600
$ docker exec -u user py-bench tmux new-session -d -s work
$ docker exec -u user py-bench tmux split-window -t work -h
$ agenttower scan --containers >/dev/null      # populate FEAT-003 state if needed
```

Run the pane scan:

```bash
$ agenttower scan --panes
scan_id=9b1cf2ea-2a8e-4d97-a30f-3e8b9d1d2c0e
status=ok
containers_scanned=1
sockets_scanned=1
panes_seen=2
panes_newly_active=2
panes_reconciled_inactive=0
containers_skipped_inactive=0
containers_tmux_unavailable=0
duration_ms=420
$ echo $?
0
```

`containers_scanned=1` (the `py-bench` container),
`sockets_scanned=1` (its default tmux socket), and `panes_seen=2`
match the two panes inside the `work` session.

`agenttower list-panes` shows the persisted records:

```bash
$ agenttower list-panes
ACTIVE	FOCUSED	CONTAINER	SOCKET	SESSION	W	P	PANE_ID	PID	TTY	COMMAND	CWD	LAST_SCANNED
1	1	py-bench	/tmp/tmux-1000/default	work	0	0	%0	1234	/dev/pts/0	bash	/workspace	2026-05-06T18:01:34.692118+00:00
1	0	py-bench	/tmp/tmux-1000/default	work	0	1	%1	1235	/dev/pts/1	bash	/workspace	2026-05-06T18:01:34.692118+00:00
```

`ACTIVE` is the row-level reconciliation flag; `FOCUSED` is the
tmux `#{pane_active}` value (the currently focused pane in its
window). They are distinct fields — never collapse them.

The same data in machine form (every FR-006 field):

```bash
$ agenttower list-panes --json | jq
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
        "first_seen_at": "2026-05-06T18:01:34.692118+00:00",
        "last_scanned_at": "2026-05-06T18:01:34.692118+00:00"
      },
      {
        "container_id": "f3c5e1ad...",
        "container_name": "py-bench",
        "container_user": "user",
        "tmux_socket_path": "/tmp/tmux-1000/default",
        "tmux_session_name": "work",
        "tmux_window_index": 0,
        "tmux_pane_index": 1,
        "tmux_pane_id": "%1",
        "pane_pid": 1235,
        "pane_tty": "/dev/pts/1",
        "pane_current_command": "bash",
        "pane_current_path": "/workspace",
        "pane_title": "user@py-bench: ~/workspace",
        "pane_active": false,
        "active": true,
        "first_seen_at": "2026-05-06T18:01:34.692118+00:00",
        "last_scanned_at": "2026-05-06T18:01:34.692118+00:00"
      }
    ]
  }
}
```

---

## 2. Combined `--containers --panes` invocation

The most common operator flow after starting a new bench container
is to refresh both the container registry and the pane registry in
one shot. The two scans run sequentially over two socket
connections; the pane scan reads the freshly-committed
`containers` table:

```bash
$ docker run -d --name api-dev ghcr.io/opensoft/api:latest sleep 3600
$ docker exec -u user api-dev tmux new-session -d -s ide
$ agenttower scan --containers --panes
scan_id=...
status=ok
matched=2
inactive_reconciled=0
ignored=0
duration_ms=140

scan_id=9b1cf2ea-...
status=ok
containers_scanned=2
sockets_scanned=2
panes_seen=3
panes_newly_active=1
panes_reconciled_inactive=0
containers_skipped_inactive=0
containers_tmux_unavailable=0
duration_ms=510
```

Two summary blocks separated by a blank line; `--json` would emit
two canonical lines instead. The final exit code is the
highest-precedence outcome across both: `3` > `5` > `0`.

---

## 3. Multiple tmux sockets per container (FR-003 / FR-011)

FEAT-004 scans every socket file under `/tmp/tmux-<uid>/`, not just
`default`. Add a second socket inside the container:

```bash
$ docker exec -u user py-bench tmux -L work new-session -d -s scratch
$ agenttower scan --panes
scan_id=...
status=ok
containers_scanned=1
sockets_scanned=2
panes_seen=3
panes_newly_active=1
panes_reconciled_inactive=0
containers_skipped_inactive=0
containers_tmux_unavailable=0
duration_ms=...
$ agenttower list-panes
ACTIVE	FOCUSED	CONTAINER	SOCKET	SESSION	W	P	PANE_ID	PID	TTY	COMMAND	CWD	LAST_SCANNED
1	1	py-bench	/tmp/tmux-1000/default	work	0	0	%0	1234	/dev/pts/0	bash	/workspace	2026-05-06T18:05:11.812345+00:00
1	0	py-bench	/tmp/tmux-1000/default	work	0	1	%1	1235	/dev/pts/1	bash	/workspace	2026-05-06T18:05:11.812345+00:00
1	1	py-bench	/tmp/tmux-1000/work	scratch	0	0	%0	1310	/dev/pts/2	bash	/tmp	2026-05-06T18:05:11.812345+00:00
```

Note that the `default` and `work` sockets each have their own
`%0` pane id; the composite primary key
`(container_id, socket, session, window, pane_index, pane_id)`
keeps them distinct (FR-007 / data-model §2.1).

Per-socket reconciliation (FR-011): if the `work` socket disappears
between scans (e.g., `tmux -L work kill-server` inside the
container) but `default` keeps running, only the panes belonging to
`work` flip to `active=0`. The `default`-socket panes stay active
and are refreshed normally:

```bash
$ docker exec -u user py-bench tmux -L work kill-server
$ agenttower scan --panes
scan_id=...
status=ok
containers_scanned=1
sockets_scanned=1
panes_seen=2
panes_newly_active=0
panes_reconciled_inactive=1
containers_skipped_inactive=0
containers_tmux_unavailable=0
duration_ms=...
```

The `work` socket is no longer enumerated (its file is gone), so
its prior pane went through transition (a) → `active=0`, and the
`default` socket's two panes stay active.

---

## 4. Filtering `list-panes`

`--active-only` suppresses inactive rows for scripts that only
care about live panes:

```bash
$ agenttower list-panes --active-only
ACTIVE	FOCUSED	CONTAINER	SOCKET	SESSION	W	P	PANE_ID	PID	TTY	COMMAND	CWD	LAST_SCANNED
1	1	py-bench	/tmp/tmux-1000/default	work	0	0	%0	1234	...
1	0	py-bench	/tmp/tmux-1000/default	work	0	1	%1	1235	...
```

`--container <id-or-name>` filters by exact container name or full
64-char hex id. Scripts can pin to a particular bench container
without parsing the table:

```bash
$ agenttower list-panes --container py-bench --json | jq '.result.panes | length'
2
$ agenttower list-panes --container does-not-exist --json | jq '.result'
{
  "filter": "all",
  "container_filter": "does-not-exist",
  "panes": []
}
$ echo $?
0
```

Empty filter result is exit code `0`, mirroring `list-containers`.
There is no substring match; the filter is exact (data-model §6
note 4).

---

## 5. Reconciling away a stopped container (FR-009 cascade)

When a previously-active bench container is stopped or removed,
FEAT-003 marks it inactive on the next container scan. The next
pane scan then cascades that inactivation onto every pane belonging
to that container — without invoking `docker exec` against it
(FR-009 / data-model §4.1 transition (c)):

```bash
$ docker rm -f py-bench
$ agenttower scan --containers >/dev/null         # container row → active=0
$ agenttower scan --panes
scan_id=...
status=ok
containers_scanned=1
sockets_scanned=1
panes_seen=1
panes_newly_active=0
panes_reconciled_inactive=2
containers_skipped_inactive=1
containers_tmux_unavailable=0
duration_ms=...
$ agenttower list-panes --active-only --container py-bench --json | jq '.result.panes | length'
0
```

The `containers_skipped_inactive=1` counter confirms FEAT-004 saw
the inactive container and applied the cascade without spawning a
`docker exec`. The `agenttower list-panes` (no `--active-only`)
view still shows the historical rows with `ACTIVE=0` — pane history
is preserved, never deleted (FR-008).

---

## 6. Concurrent scans serialize independently

FR-017: a second `scan_panes` request blocks on the **pane-scan
mutex** until the first completes. The pane-scan mutex is
*independent* of the FEAT-003 container-scan mutex, so
`scan_containers` and `scan_panes` MAY proceed in parallel.

Two parallel pane-scan calls (serialize):

```bash
$ ( agenttower scan --panes --json & agenttower scan --panes --json & wait )
{"ok":true,"result":{"scan_id":"...A","started_at":"...","completed_at":"...","status":"ok",...}}
{"ok":true,"result":{"scan_id":"...B","started_at":"...","completed_at":"...","status":"ok",...}}
```

The two `started_at` timestamps are non-overlapping; scan B's
`started_at` is greater than or equal to scan A's `completed_at`.

A container scan and a pane scan in parallel (overlap allowed):

```bash
$ ( agenttower scan --containers --json & agenttower scan --panes --json & wait )
{"ok":true,"result":{"scan_id":"...C","status":"ok",...}}
{"ok":true,"result":{"scan_id":"...P","status":"ok",...}}
```

The two scans target disjoint mutexes (and disjoint SQLite tables);
their `started_at`/`completed_at` windows can overlap. The single
SQLite writer process serializes the two `BEGIN IMMEDIATE` commits
internally, but the pane scan does not block waiting for the
container mutex.

---

## 7. Degraded states

### 7.1 Container has no `tmux` binary

A minimal bench image without tmux preserves prior pane history
and surfaces a `tmux_unavailable` per-container error (FR-010):

```bash
$ docker run -d --name min-bench alpine:3.19 sleep 3600
$ agenttower scan --containers >/dev/null
$ agenttower scan --panes --json | jq
{
  "ok": true,
  "result": {
    "scan_id": "...",
    "status": "degraded",
    "containers_scanned": 2,
    "sockets_scanned": 1,
    "panes_seen": 2,
    "panes_newly_active": 0,
    "panes_reconciled_to_inactive": 0,
    "containers_skipped_inactive": 0,
    "containers_tmux_unavailable": 1,
    "error_code": "tmux_unavailable",
    "error_message": "id -u exited 127: bash: tmux: command not found",
    "error_details": [
      {
        "container_id": "abc1234...",
        "error_code": "tmux_unavailable",
        "error_message": "id -u exited 127: bash: tmux: command not found"
      }
    ]
  }
}
$ echo $?
5
```

Exit code `5` (degraded) is distinct from `3` (whole-scan failure).
The `min-bench` container has no prior pane rows so nothing is
preserved; for a container that *did* have prior pane history,
those rows would keep their previous `active` flag and only
`last_scanned_at` would advance (FR-010 transition (d)).

### 7.2 `docker exec` timeout

A wedged `docker exec` payload normalizes to `docker_exec_timeout`
within the 5-second per-call budget (FR-018 / SC-006). The
underlying child is terminated and waited on before the
reconciler proceeds; the daemon stays alive and remaining
containers continue to be processed:

```bash
$ agenttower scan --panes --json | jq
{
  "ok": true,
  "result": {
    "scan_id": "...",
    "status": "degraded",
    "containers_scanned": 2,
    "sockets_scanned": 1,
    "panes_seen": 2,
    "containers_tmux_unavailable": 1,
    "error_code": "docker_exec_timeout",
    "error_message": "docker exec exceeded 5.0s budget",
    "error_details": [
      {
        "container_id": "stuck-bench-id...",
        "error_code": "docker_exec_timeout",
        "error_message": "docker exec exceeded 5.0s budget"
      }
    ]
  }
}
$ agenttower status
alive=true
...
```

### 7.3 Pane field truncation

A pane title or cwd longer than its per-field cap (R-009: 2048 /
2048 / 4096) is truncated rather than rejecting the row. The pane
is still persisted, and a `pane_truncations` note appears on the
per-scope error detail:

```bash
$ docker exec -u user py-bench tmux rename-window -t work:0 \
    "$(python3 -c 'print("a"*5000)')"
$ agenttower scan --panes --json | jq '.result.error_details'
[
  {
    "container_id": "f3c5e1ad...",
    "tmux_socket_path": "/tmp/tmux-1000/default",
    "error_code": "output_malformed",
    "error_message": "1 pane field(s) truncated",
    "pane_truncations": [
      {"tmux_pane_id": "%0", "field": "pane_title", "original_len": 5000}
    ]
  }
]
$ echo $?
5
```

The pane row still appears in `list-panes --json` with
`pane_title` truncated to 2048 characters — never raw, never
rejected.

### 7.4 Docker is missing

If `docker` is not on the daemon's PATH, the scan fails fast with
the FEAT-003 `docker_unavailable` envelope (FR-022). The daemon
still writes a `pane_scans` row with `status="degraded"` for audit:

```bash
$ env PATH=/usr/bin:/bin agenttowerd run &  # restart with stripped PATH
$ agenttower scan --panes --json
{"ok":false,"error":{"code":"docker_unavailable","message":"docker binary not found on PATH"}}
$ echo $?
3
$ agenttower status
alive=true
...
```

Exit code `3` (whole-scan failure) is distinct from `5` (partial
degraded). The daemon stays alive and `agenttower status`
continues to work.

### 7.5 Inspecting the audit trail

Degraded pane scans append exactly one record to `events.jsonl`
(FR-025), parallel to FEAT-003's `container_scan_degraded`:

```bash
$ tail -1 ~/.local/state/opensoft/agenttower/events.jsonl | jq
{
  "type": "pane_scan_degraded",
  "ts": "2026-05-06T18:14:02.123456+00:00",
  "payload": {
    "scan_id": "...",
    "error_code": "tmux_unavailable",
    "error_message": "1 of 2 containers had tmux unavailable",
    "error_details": [...]
  }
}
```

Healthy pane scans produce nothing in `events.jsonl` (FR-025).

The full scan history is in SQLite:

```bash
$ sqlite3 ~/.local/state/opensoft/agenttower/agenttower.sqlite3 \
    'SELECT scan_id, started_at, status, panes_seen, containers_tmux_unavailable
     FROM pane_scans ORDER BY started_at DESC LIMIT 5'
```

The lifecycle log carries one `pane_scan_started` and one
`pane_scan_completed` row per scan, distinct from FEAT-003's
`scan_started` / `scan_completed` tokens (R-014):

```bash
$ grep pane_scan_ ~/.local/state/opensoft/agenttower/agenttowerd.log | tail -2
2026-05-06T18:14:01.999999+00:00	pane_scan_started	scan_id=...
2026-05-06T18:14:02.198765+00:00	pane_scan_completed	scan_id=...	status=degraded	containers=2	sockets=1	panes_seen=2	newly_active=0	inactivated=0	skipped_inactive=0	tmux_unavailable=1	error=tmux_unavailable
```

Lifecycle rows never carry raw tmux output, raw `docker exec`
stderr beyond the bounded message, raw environment values, or raw
pane titles / cwds (FR-026 / R-014).

---

## 8. Daemon unavailable

When the daemon is not running, both new commands exit `2` with
the FEAT-002 `daemon-unavailable` message:

```bash
$ agenttower stop-daemon
$ agenttower scan --panes
error: daemon is not running or socket is unreachable: try `agenttower ensure-daemon`
$ echo $?
2
$ agenttower list-panes
error: daemon is not running or socket is unreachable: try `agenttower ensure-daemon`
$ echo $?
2
```

`agenttower ensure-daemon` brings the daemon back up; the in-memory
pane-scan mutex is recreated on restart, and any scan that was
in-flight at shutdown is abandoned (no partial pane row was
committed, FR-024 / R-015).

---

## 9. Cleanup

To exercise FEAT-004 from scratch on a development machine
(includes wiping the FEAT-003 state):

```bash
$ agenttower stop-daemon
$ rm -f ~/.local/state/opensoft/agenttower/agenttower.sqlite3* \
        ~/.local/state/opensoft/agenttower/events.jsonl
$ agenttower config init
$ agenttower ensure-daemon
$ agenttower scan --containers --panes
```

This wipes durable state for both FEAT-003 and FEAT-004 but keeps
the config file. The next combined scan re-creates `containers`
and `panes` rows with fresh `first_seen_at` timestamps and
allocates fresh `scan_id` UUIDs for both scan tables.

To wipe only the FEAT-004 tables (preserving FEAT-003 container
history) is **not** a supported operation — the schema version is
the cache key for migration replay, and the v3 migration is
idempotent on re-open. If you need a clean pane state, remove the
whole SQLite file as above and re-run a combined scan.
