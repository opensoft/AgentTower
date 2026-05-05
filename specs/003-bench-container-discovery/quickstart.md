# Quickstart: Bench Container Discovery

**Branch**: `003-bench-container-discovery` | **Date**: 2026-05-05

End-to-end CLI walkthrough of FEAT-003 against a real Docker
daemon. This document is the canonical "kick the tires" script for
both reviewers and operators.

All commands run on the host. There is no in-container step in
FEAT-003.

---

## 0. Prerequisites

- FEAT-001 initialized: `agenttower config init` has been run at
  least once and `~/.local/state/opensoft/agenttower/agenttower.sqlite3`
  exists.
- FEAT-002 daemon reachable: `agenttower status` returns `alive=true`.
- Docker installed and the host user can run `docker ps` without
  `sudo`.

If `agenttower status` returns `daemon-unavailable`, run
`agenttower ensure-daemon` first.

---

## 1. Default scan (no config changes)

The default matching rule is "container name contains `bench`,
case-insensitive". With at least one running bench container on
the host:

```bash
$ docker run -d --name py-bench ghcr.io/opensoft/py-bench:latest sleep 3600
$ docker run -d --name redis redis:7
$ agenttower scan --containers
scan_id=f3c5e1ad-2e6a-4f7e-9a02-7d2b6a1d4a5f
status=ok
matched=1
inactive_reconciled=0
ignored=1
duration_ms=180
$ echo $?
0
```

`matched=1` (the `py-bench` container) and `ignored=1` (the
`redis` container fell outside the rule). `inactive_reconciled=0`
because no prior bench container record exists.

`agenttower list-containers` shows the persisted record:

```bash
$ agenttower list-containers
ACTIVE	ID	NAME	IMAGE	STATUS	LAST_SCANNED
1	f3c5e1ad...	py-bench	ghcr.io/opensoft/py-bench:latest	running	2026-05-05T18:01:34.692118+00:00
```

The same data in machine form:

```bash
$ agenttower list-containers --json | jq
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
        "labels": {},
        "mounts": [],
        "active": true,
        "first_seen_at": "2026-05-05T18:01:34.692118+00:00",
        "last_scanned_at": "2026-05-05T18:01:34.692118+00:00",
        "config_user": null,
        "working_dir": "/workspace"
      }
    ]
  }
}
```

---

## 2. Adding a custom matching rule

Edit `~/.config/opensoft/agenttower/config.toml` to add a
`[containers]` block:

```toml
[containers]
name_contains = ["bench", "dev"]
```

No restart is required; the daemon reads the matching rule once per scan.

Now both `py-bench` and any container whose name contains `dev`
will match:

```bash
$ docker run -d --name api-dev ghcr.io/opensoft/api:latest sleep 3600
$ agenttower scan --containers
scan_id=...
status=ok
matched=2
inactive_reconciled=0
ignored=1
duration_ms=...
```

Reverting to default behavior is as simple as removing the
`[containers]` block (FR-005: the block is optional; absence means
"use the default `["bench"]`").

---

## 3. Reconciling away a stopped container

When a previously-active bench container disappears from
`docker ps`, the next scan flips its `active` flag to `0`. The
historical row is preserved (FR-013).

```bash
$ docker rm -f py-bench
$ agenttower scan --containers
scan_id=...
status=ok
matched=0
inactive_reconciled=1
ignored=0
duration_ms=...
$ agenttower list-containers
ACTIVE	ID	NAME	IMAGE	STATUS	LAST_SCANNED
0	f3c5e1ad...	py-bench	ghcr.io/opensoft/py-bench:latest	running	2026-05-05T18:02:15.418720+00:00
```

The `--active-only` flag suppresses inactive rows for scripts
that only care about live containers:

```bash
$ agenttower list-containers --active-only
ACTIVE	ID	NAME	IMAGE	STATUS	LAST_SCANNED
$ # no rows
```

---

## 4. Concurrent scans serialize automatically

FR-023: a second scan request blocks on the daemon's scan mutex
until the first completes. Verify with two parallel CLI calls:

```bash
$ ( agenttower scan --containers --json & agenttower scan --containers --json & wait )
{"ok":true,"result":{"scan_id":"...A","started_at":"...","completed_at":"...","status":"ok",...}}
{"ok":true,"result":{"scan_id":"...B","started_at":"...","completed_at":"...","status":"ok",...}}
```

The two `started_at` timestamps are non-overlapping; scan B's
`started_at` is greater than or equal to scan A's `completed_at`.

---

## 5. Degraded states

### 5.1 Docker is missing

If `docker` is not on PATH, the scan fails fast:

```bash
$ env PATH=/usr/bin:/bin agenttower scan --containers
$ echo $?
3
$ agenttower scan --containers --json
{"ok":false,"error":{"code":"docker_unavailable","message":"docker binary not found on PATH"}}
```

The daemon stays alive — `agenttower status` continues to work.

### 5.2 Permission denied on the Docker socket

When the host user can't connect to `/var/run/docker.sock`:

```bash
$ agenttower scan --containers --json
{"ok":false,"error":{"code":"docker_permission_denied","message":"Got permission denied while trying to connect to the Docker daemon"}}
$ echo $?
3
```

### 5.3 One container fails inspect, the rest succeed

This is the *partial* degraded path. The envelope is `ok: true`
but `result.status = "degraded"`:

```bash
$ agenttower scan --containers --json | jq
{
  "ok": true,
  "result": {
    "scan_id": "...",
    "status": "degraded",
    "matched_count": 1,
    "inactive_reconciled_count": 0,
    "ignored_count": 4,
    "error_code": "docker_failed",
    "error_message": "1 of 2 candidates failed inspect",
    "error_details": [
      {
        "container_id": "abc123...",
        "error_code": "docker_failed",
        "error_message": "docker inspect exited 1: Error: No such object: abc123"
      }
    ]
  }
}
$ echo $?
5
```

Exit code `5` (degraded) is distinct from `3` (whole-scan
failure). Scripts that treat any non-zero as a hard error will
still see a problem; scripts that want to differentiate can match
on `5`.

The container that succeeded is still persisted; the container
that failed inspect either keeps its prior state (if a prior row
existed) or is omitted entirely (if it never had a prior row) per
FR-026.

### 5.4 Inspecting the audit trail

Degraded scans append exactly one record to `events.jsonl`:

```bash
$ tail -1 ~/.local/state/opensoft/agenttower/events.jsonl | jq
{
  "type": "container_scan_degraded",
  "ts": "2026-05-05T18:05:42.123456+00:00",
  "payload": {
    "scan_id": "...",
    "error_code": "docker_failed",
    "error_message": "1 of 2 candidates failed inspect",
    "error_details": [...]
  }
}
```

Healthy scans produce nothing in `events.jsonl`.

The full scan history is in SQLite:

```bash
$ sqlite3 ~/.local/state/opensoft/agenttower/agenttower.sqlite3 \
    'SELECT scan_id, started_at, status, matched_count FROM container_scans ORDER BY started_at DESC LIMIT 5'
...
```

---

## 6. Validation: misconfigured `name_contains`

If `[containers] name_contains` is set to an empty list, a
non-list, or a list containing a non-string / blank element, the
daemon refuses to scan and surfaces an actionable error rather
than silently widening scope to all containers (FR-006):

```toml
[containers]
name_contains = []
```

```bash
$ agenttower scan --containers --json
{"ok":false,"error":{"code":"config_invalid","message":"[containers] name_contains must be a non-empty list of non-empty strings; got []"}}
$ echo $?
3
```

Fix the config and rerun the scan. No daemon restart is required
because the config is read once per scan.

---

## 7. Cleanup

To exercise FEAT-003 from scratch on a development machine:

```bash
$ agenttower stop-daemon
$ rm -f ~/.local/state/opensoft/agenttower/agenttower.sqlite3* \
        ~/.local/state/opensoft/agenttower/events.jsonl
$ agenttower config init
$ agenttower ensure-daemon
$ agenttower scan --containers
```

This wipes durable state but keeps the config file. The next
`scan --containers` produces a fresh `first_seen_at` for every
matching container.
