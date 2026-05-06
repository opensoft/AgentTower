# Phase 0 Research: Bench Container Discovery

**Branch**: `003-bench-container-discovery` | **Date**: 2026-05-05

This document records the design decisions made during Phase 0 of the
plan. Each decision answers a `NEEDS CLARIFICATION` (none survived
the spec clarifications) or pins a downstream-affecting choice that
the plan summary references.

---

## R-001 — Docker access surface: CLI subprocess, not the Python SDK

**Decision**: Wrap `docker ps --format ...` and
`docker inspect <id>` invocations behind a `DockerAdapter` Protocol
implemented by `SubprocessDockerAdapter` (real) and
`FakeDockerAdapter` (test). No third-party Docker SDK is added to
runtime dependencies. The real adapter resolves `docker` with
`shutil.which("docker")` against the daemon's inherited process
`PATH` at scan time and passes the resolved path as argv[0].
Invocations use `subprocess.run(..., shell=False)` with typed argv
only. FEAT-003 trusts the host user's daemon environment; a malicious
or shadowed Docker binary earlier on PATH is documented as out of
scope rather than partially mitigated.

**Rationale**:
- Constitution caps runtime deps at the Python standard library
  unless a feature explicitly extends the dependency surface; FEAT-003
  has no need to.
- The architecture doc explicitly lists `docker ps` and
  `docker inspect` as the MVP shape (§6).
- Avoids the version-skew risk between `docker` Python SDK releases
  and the host Docker Engine.
- Subprocess is testable with `subprocess.run` mocking, which is
  what FEAT-001/FEAT-002 already do for path and lock primitives.

**Alternatives considered**:
- `docker` Python SDK (`pip install docker`): fewer parsing concerns,
  but adds a third-party dep, requires the Docker daemon Unix socket
  to be reachable, and the SDK has historically lagged engine
  features. Rejected.
- Direct HTTP to `/var/run/docker.sock`: avoids both subprocess and
  third-party dep, but pins to a specific Engine API version and
  adds significant boilerplate (auth, version negotiation, JSON
  schema drift). Rejected for MVP.
- Pinned absolute Docker path in config: useful hardening later, but
  adds configuration and support burden before the MVP has container
  discovery working. Deferred.

---

## R-002 — `docker ps` output format: `--format` table

**Decision**: Run

```sh
docker ps --no-trunc --format '{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}'
```

The adapter parses one container per line, splitting on tab; names
may contain commas if Docker ever lists multiple, in which case the
adapter splits on `,` to emit a `ContainerSummary` per name.

**Rationale**:
- Tab-separated is robust against names containing spaces.
- `--no-trunc` keeps full container ids, which we use as the primary
  key.
- `--format` is stable across Docker engine versions and avoids
  parsing the human header row.
- Architecture doc (§6) pins this exact column set.
- Status text (`running`, `exited`, etc.) is preserved verbatim and
  is informational only; FEAT-003 only persists running containers
  as active (FR-007), the status string is metadata for the operator.

**Alternatives considered**:
- `docker ps --format '{{json .}}'`: per-row JSON, easier to parse
  but Engine version drift adds/removes fields. Rejected; keeps
  brittle field detection in our code.
- Plain `docker ps` (human columns): fragile to width changes.
  Rejected.

---

## R-003 — `docker inspect` shape and the slash-prefix on names

**Decision**: Call

```sh
docker inspect <id1> [<id2> ...]
```

once per scan with the full id list (single subprocess), parse the
JSON array result, and normalize:
- `Id` → `container_id`
- `Name` → `container_name`, stripping a single leading `/`
- `Config.Image` → `image`
- `State.Status` → `status`
- `Config.Labels` → `labels` (dict; empty dict if `null`)
- `Mounts` → list of `{source, target, type, mode, rw}` records
- `Config.User` → `config_user` (nullable)
- `Config.WorkingDir` → `working_dir` (nullable)
- `Config.Env` → filtered subset of identity-shaped env keys (see
  R-007)

**Rationale**:
- One subprocess call for the whole batch keeps the per-call timeout
  budget cleaner: 5 s for the whole batch is conservative on a
  busy Docker daemon, and a hung inspect on one container blocks
  the whole batch (acceptable for MVP — FR-024 is a per-call
  budget).
- Stripping the leading `/` from `Name` matches `docker ps` output
  and lets the matching predicate compare on the same form.
- Edge case from spec ("multiple names or leading slash prefixes")
  is handled by the parser, not the matching layer.

**Alternatives considered**:
- One subprocess per container (`docker inspect <id>` × N): simpler
  per-container error attribution, but multiplies syscall and
  startup cost; with N containers each at the 5 s timeout, the
  worst case is N × 5 s. Rejected for the default path; the
  adapter falls back to per-container inspection only when the
  batch call returns invalid JSON or a non-zero exit so partial
  success is still possible.
- Skip inspect entirely; rely on `docker ps` columns: insufficient
  because labels and mounts are the FEAT-004 hand-off surface
  (FR-011). Rejected.

---

## R-004 — Per-call subprocess timeout: 5 seconds

**Decision**: Pass `timeout=5.0` to every `subprocess.run` invocation
in `SubprocessDockerAdapter` and translate the resulting
`subprocess.TimeoutExpired` into a `DockerError(code="docker_timeout")`.
The adapter relies on Python's `subprocess.run` timeout behavior,
which kills and waits for the child process before raising, and tests
assert the timeout path is normalized rather than leaked.

**Rationale**: Pinned by spec clarification Q2 (FR-024). Matches the
architecture doc's `scan_interval_seconds = 5` informally and keeps
a single hung Docker call from wedging the daemon indefinitely. The
scan mutex can still be held for `5 * (1 + N)` seconds in the worst
case where `docker ps` plus N per-container inspect calls time out.

**Alternatives considered**: 3 s (too aggressive on cold WSL) or
10 s (delays degraded recovery). Both rejected during clarification.

---

## R-005 — Concurrent scan handling: in-process `threading.Lock`

**Decision**: `DiscoveryService` owns a single `threading.Lock`. Every
call to `scan()` acquires the lock with `acquire(blocking=True)`,
runs the scan, writes the SQLite reconciliation in one
`BEGIN/COMMIT` transaction, and releases. The new `scan_containers`
socket method handler is the only caller in production. If more than
two scan callers wait, they serialize behind the same lock with no
MVP FIFO fairness guarantee beyond the interpreter/OS lock behavior.
The lock is in-process only and is recreated after daemon restart; an
in-flight scan is abandoned if the daemon process exits.

**Rationale**:
- Pinned by clarification Q1 (FR-023). Serialized scans avoid
  conflicting reconciliation writes and keep the SQLite write path
  single-writer-friendly.
- An in-process lock is the right primitive: the daemon is the
  single SQLite writer (constitution principle I) so no inter-process
  coordination is needed.
- `list_containers` is a read-only path that takes a separate short
  read transaction; it MUST NOT contend on the scan mutex (per
  plan-level constraint), so readers stay fast even during a slow
  scan.

**Alternatives considered**:
- `multiprocessing.Lock` / file lock: unnecessary; one daemon owns
  the database. Rejected.
- Async/await with an `asyncio.Lock`: would force restructuring
  FEAT-002's threading server. Rejected.
- Reject second scan with `scan_in_progress` (clarification option C):
  rejected during clarification.

---

## R-006 — Container Scan Result persistence

**Decision**: Each scan writes one row to a new
`container_scans` table. Degraded scans additionally append one
record to the existing FEAT-001 `events.jsonl` file via
`events.writer.append_event(...)`. Healthy scans do **not** write
to `events.jsonl`.

**Rationale**:
- Pinned by clarification Q3 (FR-019, FR-025). SQLite gives
  scriptable history; JSONL is the existing audit channel for
  noteworthy events; healthy scans are too frequent to flood it.

**Schema (v2 migration)**:
- `containers (container_id TEXT PRIMARY KEY, name TEXT, image TEXT, status TEXT, labels_json TEXT, mounts_json TEXT, inspect_json TEXT, config_user TEXT, working_dir TEXT, active INTEGER NOT NULL CHECK(active IN (0,1)), first_seen_at TEXT NOT NULL, last_scanned_at TEXT NOT NULL)`
- `container_scans (scan_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('ok','degraded')), matched_count INTEGER NOT NULL, inactive_reconciled_count INTEGER NOT NULL, ignored_count INTEGER NOT NULL, error_code TEXT, error_message TEXT, error_details_json TEXT)`

`scan_id` is a UUID4 string (clarification assumption); timestamps
are ISO-8601 UTC with microsecond precision (matches FEAT-002's
`status.start_time_utc`).

**Alternatives considered**:
- Per-container scan history table (`container_scan_observations`):
  attractive for richer history, but YAGNI for FEAT-003. Rejected.
- JSONL-only or SQLite-only: rejected during clarification.

---

## R-007 — Inspect environment-key allowlist

**Decision**: Persist only environment variable *names* (not values)
that match a small allowlist of identity-shaped keys: `USER`,
`HOME`, `WORKDIR`, `TMUX`. Names are stored as a JSON list under
the `inspect_json.env_keys` field.

**Rationale**: FR-011 calls for "environment keys needed for
identity"; persisting full env values would store credentials and
violate the spec's "no redaction in FEAT-003" assumption (which
defers redaction to FEAT-007). Storing only allowlisted names gives
FEAT-004 the hooks it needs to detect tmux scope without leaking
secrets in FEAT-003.

**Alternatives considered**:
- Store the full env list: rejected; secrets surface.
- Store nothing about env: rejected; FEAT-004 needs identity hints.

---

## R-008 — Test seam for the Docker adapter

**Decision**: The daemon resolves which adapter to instantiate by
checking `os.environ.get("AGENTTOWER_TEST_DOCKER_FAKE")` at startup.
If set, it loads a `FakeDockerAdapter` from a JSON fixture path
named by the env var. Otherwise it instantiates
`SubprocessDockerAdapter`.

**Rationale**: Integration tests already spawn the daemon as a
subprocess (FEAT-002 pattern). Passing the fake adapter through
`os.environ` avoids any import-time monkeypatching across process
boundaries and keeps production code free of test-only branches
beyond the env-var check.

**Alternatives considered**:
- CLI flag (`agenttowerd run --docker-fake <path>`): leaks a test
  surface into the production CLI. Rejected.
- `unittest.mock.patch` of `subprocess.run`: doesn't work across
  the spawned daemon process. Rejected.
- A separate `agenttowerd-test` binary: too heavy for a single
  feature. Rejected.

The env-var name is namespaced (`AGENTTOWER_TEST_*`) so it is
self-documenting and unlikely to collide. Production deployments
must not set it; an integration test asserts the env var is unset
when running the real binary.

---

## R-009 — Default config block (`[containers]`)

**Decision**: The default config file written by FEAT-001's
`agenttower config init` does **not** need to ship a `[containers]`
block in FEAT-003 — the loader treats absence as "use the default
list `["bench"]`" (FR-004). The config loader validates on every
scan: list-of-strings, non-empty, each element non-empty after
`strip()`, at most 32 entries, and each stripped entry no longer than
128 characters. Invalid values produce a `config_invalid` socket error
with an actionable message (FR-006).

**Rationale**: Backward-compat with FEAT-001 config files (FR-022).
Adding a default block would change the byte-for-byte output of
`agenttower config init`, which is part of FEAT-001's contract.
Re-reading per scan lets developers adjust bench naming without
restarting the daemon.

**Alternatives considered**:
- Ship the default block: rejected (changes FEAT-001 behavior).
- Strict mode where missing block is an error: rejected; the spec's
  US2 acceptance scenario 1 explicitly tests default-no-config
  behavior.

---

## R-010 — Inspect-failure record handling

**Decision**: When `docker inspect` fails for a matching candidate
that has a prior `containers` row, the reconcile path emits an
`UPDATE last_scanned_at = ? WHERE container_id = ?` write —
nothing else. When the failing candidate has no prior row, no
write is emitted at all and the failure is captured in the
`container_scans.error_details_json` payload.

**Rationale**: Pinned by clarification Q4 (FR-026). Holding the
prior `active` flag and inspect metadata is the most conservative
truth. The no-prior-record case avoids creating a phantom row that
would then need a special "we don't really know what this is" state
in the schema.

**Edge case**: If `docker ps` returns a matching container that
has *never* been seen and `docker inspect` succeeds for everything
else, the new container is inserted as active in the same
transaction. The reconcile module computes the full write set and
the SQLite writer applies it in one transaction.

---

## R-011 — `list-containers` ordering and filtering

**Decision**: `list_containers` returns rows ordered by
`active DESC, last_scanned_at DESC, container_id ASC`. The
`--active-only` flag adds `WHERE active = 1` to the query.

**Rationale**: Clarification Q5 pins active-first, then inactive.
Within each group, `last_scanned_at DESC` puts freshly observed
records on top; `container_id ASC` is the stable tiebreaker for
deterministic test output.

**JSON shape** (consumed by `agenttower list-containers --json`):

```json
{
  "ok": true,
  "result": {
    "containers": [
      {
        "id": "<full container id>",
        "name": "<container name>",
        "image": "<image ref>",
        "status": "<docker status>",
        "labels": {"com.example": "yes"},
        "mounts": [{"source": "...", "target": "...", "type": "bind", "mode": "rw", "rw": true}],
        "active": true,
        "first_seen_at": "<iso>",
        "last_scanned_at": "<iso>",
        "config_user": "user",
        "working_dir": "/workspace"
      }
    ]
  }
}
```

`--active-only` adds `"filter": "active_only"` to the result for
self-documentation.

---

## R-012 — Schema migration v1 → v2

**Decision**: `state/schema.py` bumps `CURRENT_SCHEMA_VERSION` to
`2`. `open_registry` reads the existing version row, runs each
pending `_apply_migration_vN` step under a single transaction, and
updates the row to `CURRENT_SCHEMA_VERSION` at the end. v2 creates
the two new tables only; it does not touch any FEAT-001 table.

**Rationale**: FEAT-002's plan explicitly notes that FEAT-006 will
need migration support. FEAT-003 is the first feature that adds
durable schema beyond `schema_version`, so introducing the
migration runner here is the right scope. The runner is small
(single-file, dispatch-by-version) and is exercised both by the
v1→v2 case and by an idempotent re-open path.

**Alternatives considered**:
- Drop and recreate on version mismatch: rejected; destroys data.
- Defer migration runner to FEAT-006: rejected; FEAT-003 needs it
  immediately and FEAT-006 will benefit from a working pattern.

---

## R-013 — CLI surface (new subcommands)

**Decision**:
- `agenttower scan [--containers] [--json]`: a top-level `scan`
  subcommand. In FEAT-003 the only mode flag is `--containers`; if
  no mode flag is passed, the command exits non-zero with
  `error: scan requires a target flag (e.g. --containers)`. This
  reserves the bare `agenttower scan` invocation for FEAT-004's
  `--panes` mode without a breaking rename later.
- `agenttower list-containers [--active-only] [--json]`: standalone
  subcommand. No positional arguments.

**Rationale**:
- Architecture doc (§20) lists `agenttower scan` as a singular
  command. Reserving the bare form for FEAT-004 (`--panes`) is the
  smallest forward-compatible surface.
- `list-containers` is already named in the architecture doc; we
  ship it standalone (not under `scan`) because it is a query, not
  an action.

**Alternatives considered**:
- Bare `agenttower scan` performing a containers-only scan in
  FEAT-003: rejected; rename in FEAT-004 would break scripts.
- A single `agenttower containers <verb>` umbrella: rejected;
  doesn't match the architecture doc's flat verb list.

---

## R-014 — Closed error code set for the new socket methods

**Decision**: The new methods return one of:

| code                        | Meaning                                                    |
| --------------------------- | ---------------------------------------------------------- |
| `bad_json`                  | (existing) bytes weren't UTF-8 JSON                        |
| `bad_request`               | (existing) envelope or params invalid                      |
| `unknown_method`            | (existing) method not in the dispatch table                |
| `request_too_large`         | (existing) line over 64 KiB                                |
| `internal_error`            | (existing) unhandled daemon exception                      |
| `config_invalid`            | NEW — `[containers] name_contains` is malformed (FR-006)   |
| `docker_unavailable`        | NEW — `docker` not on PATH or not executable               |
| `docker_permission_denied`  | NEW — Docker reported permission denied (`Got permission denied while trying to connect to the Docker daemon`) |
| `docker_timeout`            | NEW — `subprocess.TimeoutExpired` after 5 s                |
| `docker_failed`             | NEW — non-zero exit from `docker ps`/`docker inspect`      |
| `docker_malformed`          | NEW — output is not parseable / inspect JSON shape invalid |

`docker_*` codes only ever appear in `container_scans.error_code`
when the **whole** scan was degraded (i.e., we could not produce a
useful set of results). When `docker ps` succeeds and only some
`docker inspect` calls fail, the scan is still degraded but the
top-level error code is `docker_failed` with per-container detail
in `error_details_json`. The matching scan_containers socket
response carries the same code. For partial inspect failures, the
representative top-level code is the first per-container failure code
in Docker ps order; each matching candidate contributes at most one
per-container detail entry.

**Rationale**: FEAT-002 uses a closed error-code set for the same
reasons (forward-compatible client parsing, machine-friendly).
Extending the set rather than redefining keeps FEAT-002 clients
unbroken (FR-022).

---

## R-015 — Lifecycle log additions

**Decision**: The daemon's existing TSV lifecycle log
(`<LOGS_DIR>/agenttowerd.log`) gains two new event tokens:
- `scan_started` — emitted when `DiscoveryService.scan` acquires the
  mutex; columns: `<ts>\tscan_started\tscan_id=<uuid>`.
- `scan_completed` — emitted after the SQLite scan transaction commits
  and after any degraded JSONL append is attempted;
  columns:
  `<ts>\tscan_completed\tscan_id=<uuid>\tstatus=<ok|degraded>\tmatched=<int>\tinactive=<int>\tignored=<int>`.

Degraded scans append one extra column: `error=<code>`.

**Rationale**: Keeps the FEAT-002 lifecycle log as the single
source of truth for daemon-visible activity. The existing six
event tokens (`daemon_starting`, `daemon_ready`, etc.) are not
modified.

Security boundary: lifecycle rows MUST NOT include raw inspect output,
raw environment values, label values, mount source paths, or full
Docker stderr. They carry only scan id, aggregate counts, status, and
closed error code.

Write order requirement: `scan_started` is emitted after the scan
mutex is acquired and before config/Docker execution. The SQLite scan
transaction commits before the degraded JSONL event is appended.
`scan_completed` is emitted after the SQLite commit and JSONL append
attempt, immediately before the socket response is returned.

---

## R-016 — Test budget and SC-004 verification

**Decision**: All FEAT-003 integration tests run with
`AGENTTOWER_TEST_DOCKER_FAKE` set so no real `docker` binary is
ever invoked (FR-020, SC-007). The harness includes
`tests/integration/test_cli_scan_no_real_docker.py` which:
1. Asserts `AGENTTOWER_TEST_DOCKER_FAKE` is set in `os.environ` at
   collection time.
2. Monkeypatches `shutil.which` and `subprocess.run` for the
   duration of the session and asserts neither is called with
   `"docker"` as argv[0].

SC-004 (the 3 s degraded budget) is enforced with a per-test
`pytest.fail` if a degraded scan invocation exceeds 3 s
wall-clock. The fake adapter returns immediately for
non-timeout-tagged scenarios; for the timeout scenario it sleeps
just past 5 s in a worker thread that the
`SubprocessDockerAdapter`'s patched `subprocess.run` proxies, so
the 3 s assertion is independent of the 5 s timeout (the timeout
case is tested separately and explicitly).

**Rationale**: Hard guards on the no-real-Docker constraint protect
against accidental regressions; an explicit budget keeps the
non-functional requirement testable.

---

## R-017 — Sensitive-field and response-size boundary

**Decision**: Persist only normalized inspect fields needed by
FEAT-004: id, name, image, status, labels, mounts, config user,
working directory, allowlisted environment keys (`USER`, `HOME`,
`WORKDIR`, `TMUX`), and full status. Raw `HostConfig`, raw
non-allowlisted environment variables, and raw inspect JSON are
excluded. Docker stderr and per-container failure messages are
bounded to 2048 characters after NUL/control-byte sanitization before
they enter SQLite, JSONL, logs, or socket responses. FEAT-002's
64 KiB limit remains request-only; FEAT-003 keeps responses small by
excluding raw inspect/env data and does not add a response-size error
code.

**Rationale**: FEAT-003 is a local host-user tool, so mount sources
and label values remain visible until FEAT-007 redaction. The
allowlist prevents accidental persistence of high-risk Docker fields
while keeping enough metadata for FEAT-004 pane discovery.

**Alternatives considered**:
- Full inspect blob persistence: simpler debugging, but too broad for
  a local security boundary. Rejected.
- Redact labels and mount sources now: desirable, but FEAT-007 owns
  reusable redaction policy. Deferred.
- Add socket pagination/response-size errors now: unnecessary for the
  MVP bench-container scale and would change FEAT-002 response
  contracts. Deferred.

---

## R-018 — Scan transaction and side-effect failure handling

**Decision**: The SQLite transaction that writes `container_scans` and
all `containers` mutations is the authoritative commit boundary. If it
fails, the transaction rolls back, no JSONL degraded event is appended,
the scan mutex is released, and the caller receives `internal_error`.
If the SQLite transaction commits but the degraded JSONL append or
`scan_completed` lifecycle emit fails, the committed row is not rolled
back; the caller receives `internal_error`, and the daemon stays alive.

**Rationale**: SQLite is the durable source of truth for scan history.
Rolling back after an external append/log failure is impossible once
the SQLite commit has succeeded, so the failure is surfaced clearly
without pretending the scan did not happen.
