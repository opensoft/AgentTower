# Implementation Plan: Bench Container Discovery

**Branch**: `003-bench-container-discovery` | **Date**: 2026-05-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-bench-container-discovery/spec.md`

## Summary

Add bench-container discovery to the FEAT-002 host daemon. Two new
socket methods (`scan_containers`, `list_containers`) and two new CLI
verbs (`agenttower scan --containers`, `agenttower list-containers`)
turn `docker ps` + `docker inspect` output into durable, scriptable
records under the existing FEAT-001 SQLite database and JSONL events
file. Docker access is encapsulated behind a `DockerAdapter` protocol
so the entire feature is testable without a real Docker daemon
(FR-020). Two new SQLite tables are added: `containers` (one row per
unique container id ever seen, with active/inactive flag and
last-known inspect metadata) and `container_scans` (one row per scan
invocation). A daemon-scoped `threading.Lock` serializes concurrent
scan requests (FR-023, clarification Q1); every `docker ps` and each
`docker inspect` runs under a 5-second per-call subprocess timeout
(FR-024, clarification Q2); degraded scans persist to
`container_scans` *and* append one record to the existing FEAT-001
events file (FR-019, clarification Q3); and `list-containers` returns
all matching containers by default with active rows ordered first,
plus an `--active-only` filter flag (FR-016, clarification Q5). No
network listener is added; no third-party runtime dependency is
introduced.

## Technical Context

**Language/Version**: Python 3.11+ (inherits from FEAT-001/FEAT-002).
`subprocess.run(..., timeout=...)` with `text=True` and `check=False`
covers all Docker invocations; `json.loads` parses inspect output;
`sqlite3` and `threading` are sufficient for state and serialization.

**Primary Dependencies**: Standard library only — `subprocess`, `json`,
`sqlite3`, `threading`, `uuid`, `datetime`, `pathlib`, `argparse`,
`shutil` (for `which`), `errno`, `os`, `time`, `dataclasses`, `typing`.
No third-party runtime dependency added (constitution technical
constraints; pyproject already pins `requires-python>=3.11` and
declares no runtime deps). The existing optional `[test]` extra
(`pytest>=7`) is the test harness.

**Storage**: Extends the FEAT-001 SQLite database
(`agenttower.sqlite3`) with two new tables — `containers` and
`container_scans` — gated behind a schema migration that bumps the
existing `schema_version` row from `1` to `2`. Appends one JSONL
record to the existing FEAT-001 events file (`events.jsonl`) **only
when** a scan is degraded; healthy scans write nothing to the events
file. No new files, sockets, or directories are introduced.

**Testing**: pytest (≥ 7). Unit tests cover the matching-rule
predicate, the Docker adapter parser/error-normalizer (driven by a
`FakeDockerAdapter` and a `RecordingSubprocessRunner`), the
reconciliation logic (active/inactive transitions, inspect-failure
preservation per FR-026), the `container_scans` row writer, and the
two new socket method handlers in isolation. Integration tests drive
the full CLI surface (`agenttower scan --containers`,
`agenttower list-containers`) over a live daemon spawned exactly as
FEAT-002's `tests/integration/test_daemon_lifecycle.py` does, but with
the daemon's container scan code path bound to the `FakeDockerAdapter`
through a `AGENTTOWER_TEST_DOCKER_FAKE` environment hook (R-008
below). No test invokes `docker` (FR-020, SC-007). Subprocess timeout
behavior is tested by injecting a `FakeDockerAdapter` that sleeps past
the 5-second budget through a monkeypatched `subprocess.run` —
the real `SubprocessDockerAdapter` is exercised against the same fake
runner so the timeout/return-code surfaces are covered without a real
Docker daemon.

**Target Platform**: Linux/WSL developer workstations with Docker CLI
available on `PATH`. Single host user; everything stays under the
host user's `opensoft/agenttower` namespace. The daemon already runs
exclusively on the host (constitution principle I); FEAT-003 changes
nothing about that deployment shape.

**Project Type**: Single-project Python CLI + daemon. Extends
`src/agenttower/`. The previously empty `src/agenttower/docker/` and
`src/agenttower/discovery/` packages are now populated by this
feature. `cli.py`, `daemon.py`, `socket_api/methods.py` are extended;
`state/schema.py` gains a migration helper. No new top-level package.

**Performance Goals**: SC-004 — degraded states must surface in CLI
output within 3 seconds when running against a `FakeDockerAdapter`.
With the per-call 5 s timeout, a real-world worst-case single hung
`docker inspect` takes 5 s; a worst-case full scan with N matching
containers whose inspect calls all hang takes approximately
`5 * (1 + N)` seconds because the daemon first runs `docker ps` and
then one `docker inspect` per matching candidate. The timed-out child
MUST be killed and waited before returning the degraded result. Healthy
scans against ≤20 bench containers should complete in well under 1 s
on a normally-loaded host.

**Constraints**:
- No network listener (constitution I; FR-021).
- No third-party runtime dependency.
- No real Docker invocation inside the test suite (FR-020).
- Existing FEAT-002 socket methods (`ping`, `status`, `shutdown`)
  MUST remain bytewise unchanged in their request/response envelopes
  (FR-022).
- Existing FEAT-001 paths, modes (`0700` dirs, `0600` files), and
  events-file format MUST remain unchanged (FR-022).
- Subprocess command construction MUST never interpolate raw config
  values into a shell string (constitution III); every Docker call
  uses `shell=False` typed argv and is limited to `docker ps
  --no-trunc --format ...` plus `docker inspect <container-id>...`
  (FR-027). The binary is resolved with `shutil.which("docker")`
  against the daemon's inherited `PATH` at scan time; shadowed Docker
  binaries on a trusted host user's `PATH` are out of scope for
  FEAT-003 (FR-028).
- Concurrent scans serialized by a daemon-scoped `threading.Lock`
  (FR-023); more than two callers block behind the same lock with no
  FIFO fairness guarantee, and the lock is recreated on daemon restart
  (FR-035). Readers (`list_containers`) must not acquire the scan
  mutex or call Docker (FR-034).
- `[containers] name_contains` is read per scan, not cached; the
  config list is bounded to 32 stripped strings, each ≤128 characters,
  and invalid config returns `config_invalid` without widening scope
  (FR-030).
- Persisted/error surfaces are allowlisted and bounded: no raw
  `HostConfig`, no raw non-allowlisted env vars, no raw inspect blob,
  and no unbounded stderr in SQLite, JSONL, lifecycle logs, or socket
  responses (FR-032, FR-033). Label values and mount sources remain
  visible to the trusted host user until FEAT-007 redaction lands.
- Each scan allocates one UUID4 `scan_id` and commits the
  `container_scans` row plus all `containers` mutations in one SQLite
  transaction. Whole-scan failures still create a degraded scan row for
  audit even when the socket envelope is `ok:false` (FR-038, FR-042).
- Scan counters are per-scan: `matched_count + ignored_count` equals
  the parseable `docker ps` row count after a successful parse, and
  `inactive_reconciled_count` counts only rows transitioned from
  active to inactive in that scan (FR-041).
- `list_containers` reads only latest committed SQLite state and uses
  deterministic ordering `active DESC, last_scanned_at DESC,
  container_id ASC` (FR-048).

**Scale/Scope**: One host user, one daemon, two new tables, two new
socket methods, two new CLI verbs (one is a new `--containers` flag
on a new `scan` subcommand), one new schema migration (v1 → v2),
one new optional config block (`[containers] name_contains`).
Expected steady state on a developer workstation: < 20 bench
containers, < 5 scans per minute, scan/list response payloads
measured in single-digit kilobytes. FEAT-002's 64 KiB limit is a
request-line cap, not a response cap; FEAT-003 does not introduce a
new response-size error code (FR-036).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle                       | Status | Evidence |
| ------------------------------- | ------ | -------- |
| I. Local-First Host Control     | PASS   | Discovery runs in the existing host daemon over the existing `AF_UNIX` socket. FR-021 forbids any new network listener; SC-007 reaffirms this for FEAT-003's test suite. No durable state moves out of the host's `opensoft/agenttower` namespace. |
| II. Container-First MVP         | PASS   | This feature is the first MVP step that targets bench *containers* directly: `name_contains = ["bench"]` default, only running containers in scope. FR-021 explicitly defers tmux discovery, pane discovery, registration, log attachment, and input delivery to FEAT-004+. |
| III. Safe Terminal Input        | PASS (vacuously) | FR-021 forbids any input delivery in this feature. Docker subprocess argv is constructed from `shutil.which("docker")` plus typed argv lists; raw container names are never interpolated into a shell string. |
| IV. Observable and Scriptable   | PASS   | Both new CLI verbs ship dual output modes (default human-readable, `--json` line-canonical). Healthy and degraded scans persist to SQLite (`container_scans`); degraded scans additionally land in the FEAT-001 JSONL events file (FR-019). All failure paths return a non-zero exit with an actionable stderr line (FR-018, FR-006). |
| V. Conservative Automation      | PASS   | The daemon decides nothing about which containers should exist; it observes `docker ps`, applies a conservative substring rule, and persists. No automatic container start/stop/exec is introduced. |

| Technical Constraint                                                      | Status | Evidence |
| ------------------------------------------------------------------------- | ------ | -------- |
| Primary language Python                                                   | PASS   | Python 3.11+, stdlib only. |
| Console entrypoints `agenttower` & `agenttowerd`                          | PASS   | Extends `agenttower` with `scan` and `list-containers` subcommands. `agenttowerd run` is unchanged. |
| Files under `~/.config` / `~/.local/state` / `~/.cache` `opensoft/agenttower` | PASS | `containers` / `container_scans` tables live in the existing `agenttower.sqlite3`; degraded events append to the existing `events.jsonl`. No new path. |
| Docker default `name_contains = ["bench"]`, host `docker exec -u "$USER"` | PASS   | FR-004. FEAT-003 owns only `docker ps` and `docker inspect`; `docker exec -u "$USER"` is FEAT-004's surface. |
| CLI: human-readable defaults + structured output where it helps           | PASS   | Both new commands ship `--json` (FR-017). |

| Development Workflow                                                          | Status | Evidence |
| ----------------------------------------------------------------------------- | ------ | -------- |
| Build in `docs/mvp-feature-sequence.md` order                                 | PASS   | This is FEAT-003, immediately after FEAT-002. |
| Each feature CLI-testable                                                     | PASS   | The two new CLI verbs are exercised end-to-end against a live daemon with a `FakeDockerAdapter`. |
| Tests proportional to risk; broader for daemon state, sockets, Docker adapters | PASS | Adapter parsing, error normalization, timeout handling, reconciliation, mutex serialization, and full CLI round-trip all get integration coverage. |
| Preserve existing docs and NotebookLM sync mappings                           | PASS   | This feature does not edit existing Markdown under `docs/`. |
| No TUI, web UI, or relay before the core slices work                          | PASS   | None introduced here. |
| Decide explicitly whether `/speckit.checklist <topic>` is needed before tasks | DECISION | A `security` checklist is recommended before `/speckit.tasks` because the Docker subprocess surface is the first time AgentTower shells out to a third-party binary; verifying argv construction (no shell interpolation), PATH resolution, and timeout enforcement is worth a topic-specific gate. The decision and rationale are recorded here so the next agent invocation honors it. |

**Result**: Gates pass. No `Complexity Tracking` entries required.

## Project Structure

### Documentation (this feature)

```text
specs/003-bench-container-discovery/
├── plan.md                        # This file (/speckit.plan output)
├── research.md                    # Phase 0 output: resolved decisions
├── data-model.md                  # Phase 1 output: tables, entity shapes, state transitions
├── quickstart.md                  # Phase 1 output: end-to-end CLI walkthrough
├── contracts/
│   ├── cli.md                     # User-facing CLI contracts (C-CLI-201, C-CLI-202)
│   └── socket-api.md              # New socket methods (C-API-201, C-API-202)
├── checklists/
│   └── requirements.md            # /speckit.specify quality checklist (already present)
└── tasks.md                       # /speckit.tasks output (NOT created by /speckit.plan)
```

### Source Code (repository root)

Only files actually touched by FEAT-003 are listed. FEAT-001/FEAT-002
files remain unchanged unless an explicit "EXTENDS" note appears.

```text
src/agenttower/
├── __init__.py                    # (FEAT-001) unchanged
├── cli.py                         # EXTENDS: add `scan` subparser (with --containers flag) and `list-containers` subparser; both accept --json
├── config.py                      # EXTENDS: load + validate optional `[containers]` block (name_contains list)
├── daemon.py                      # EXTENDS: build a DiscoveryService and a DockerAdapter at startup, attach to DaemonContext, wire the new dispatch entries
├── paths.py                       # (FEAT-001) unchanged
├── events/
│   ├── __init__.py                # (FEAT-001) unchanged
│   └── writer.py                  # (FEAT-001) used by degraded-scan path; no changes
├── socket_api/
│   ├── __init__.py                # unchanged
│   ├── client.py                  # unchanged
│   ├── errors.py                  # EXTENDS: add new error codes (`docker_unavailable`, `docker_permission_denied`, `docker_timeout`, `docker_failed`, `docker_malformed`, `config_invalid`)
│   ├── lifecycle.py               # unchanged
│   ├── methods.py                 # EXTENDS: register `scan_containers` and `list_containers` handlers; extend DaemonContext with discovery service handle
│   └── server.py                  # unchanged (dispatch is data-driven)
├── state/
│   ├── __init__.py                # (FEAT-001) unchanged
│   ├── schema.py                  # EXTENDS: bump CURRENT_SCHEMA_VERSION to 2; add `_apply_migration_v2()` that creates `containers` and `container_scans`
│   └── containers.py              # NEW: typed dataclasses + read/write helpers for the two new tables
├── docker/
│   ├── __init__.py                # NEW: package marker; re-exports DockerAdapter, SubprocessDockerAdapter, FakeDockerAdapter
│   ├── adapter.py                 # NEW: DockerAdapter Protocol; ContainerSummary / InspectResult / DockerError dataclasses
│   ├── subprocess_adapter.py      # NEW: SubprocessDockerAdapter — real implementation; argv construction, 5 s timeouts, return-code → DockerError mapping
│   ├── parsers.py                 # NEW: pure parse helpers for `docker ps --format` table rows and `docker inspect` JSON arrays
│   └── fakes.py                   # NEW: FakeDockerAdapter — scriptable in-memory adapter for tests; loadable via AGENTTOWER_TEST_DOCKER_FAKE
└── discovery/
    ├── __init__.py                # NEW: package marker; re-exports DiscoveryService
    ├── matching.py                # NEW: pure matching predicate (case-insensitive substring, validated config)
    ├── service.py                 # NEW: DiscoveryService — owns the scan mutex, runs scan-then-reconcile, returns ScanResult
    └── reconcile.py               # NEW: pure SQL-free reconciliation function: given prior rows + scan inputs, return write set (insert, update, mark_inactive)

tests/
├── unit/
│   ├── test_discovery_matching.py          # NEW: substring rule; case-insensitivity; rejection of empty/non-list/non-string config
│   ├── test_docker_parsers.py              # NEW: docker ps row parsing, slash-stripping for inspect names, JSON shape resilience
│   ├── test_docker_subprocess_adapter.py   # NEW: argv construction, command-not-found, permission-denied stderr → DockerError, 5 s timeout normalization (uses a fake subprocess.run)
│   ├── test_discovery_reconcile.py         # NEW: active→inactive on absence, inspect-failure prior-record preservation, inspect-failure no-prior-record skip
│   ├── test_state_containers.py            # NEW: table writes, scan_id correlation, JSON column round-trip, schema v1→v2 migration idempotence
│   ├── test_socket_api_scan_methods.py     # NEW: in-process dispatch of scan_containers / list_containers (no real socket); mutex behavior under threaded callers
│   └── test_config_containers_block.py     # NEW: name_contains list parsing, malformed value errors
└── integration/
    ├── test_cli_scan_containers.py         # NEW: scan with fake adapter; persisted records visible via list-containers; default + --json
    ├── test_cli_list_containers.py         # NEW: default ordering (active first), --active-only filter, --json schema, empty-state case
    ├── test_cli_scan_degraded.py           # NEW: command-not-found, permission-denied, timeout, non-zero exit, malformed inspect — all surface as degraded scans within SC-004's 3 s budget
    ├── test_cli_scan_reconciliation.py     # NEW: previously-active container disappears → marked inactive in same invocation (SC-002)
    ├── test_cli_scan_concurrent.py         # NEW: two parallel scan_containers requests serialize via the daemon mutex (FR-023); both return ok results
    └── test_cli_scan_no_real_docker.py     # NEW: harness-level guard that asserts `docker` is never spawned during the test session (SC-007 verification for FEAT-003)
```

**Structure Decision**: Keep FEAT-001's single-project layout. Two
previously-empty subpackages — `docker/` and `discovery/` — are
populated for the first time. State helpers go under
`state/containers.py` so the schema module remains the single owner
of the migration sequence and the data dataclasses live next to the
SQL that reads them. The Docker adapter is a Protocol (not an ABC)
to keep the test fake lightweight and to make the seam with
`subprocess.run` mockable. `discovery/service.py` is the only place
that knows how to combine an adapter call with the SQLite reconcile
write; both new socket methods delegate to it.

## Complexity Tracking

> No constitutional violations to justify. This section is intentionally empty.
