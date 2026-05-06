# Implementation Plan: Container tmux Pane Discovery

**Branch**: `004-container-tmux-pane-discovery` | **Date**: 2026-05-06 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-container-tmux-pane-discovery/spec.md`

## Summary

Add tmux pane discovery on top of the FEAT-003 container registry.
The host daemon shells out via `docker exec -u <bench-user>` into
every container that FEAT-003 has marked active, enumerates tmux
sockets under `/tmp/tmux-<uid>/`, scans each socket with
`tmux -S <socket> list-panes -a -F <format>`, and persists pane
identity (container, socket, session, window, pane index, tmux pane
id, pid, tty, command, cwd, title, active flag, first/last seen)
into a new SQLite `panes` table. A new `pane_scans` table records
one row per scan (counts + closed-set degraded errors). Two new
socket methods (`scan_panes`, `list_panes`) and two new CLI verbs
(`agenttower scan --panes`, `agenttower list-panes`) drive the
feature. A new `TmuxAdapter` Protocol (`SubprocessTmuxAdapter`
production, `FakeTmuxAdapter` tests) keeps the entire feature
testable without a real Docker daemon, real container, or real
tmux server (FR-034). A second daemon-scoped `threading.Lock`
serializes pane scans independently of the FEAT-003 container-scan
mutex (FR-017); per-call subprocesses are bounded at 5 seconds
(FR-018); reconciliation is per `(container, socket)` (FR-011);
`tmux_unavailable` containers preserve their prior pane `active`
flags (FR-010); an inactive container cascade marks its panes
inactive without invoking `docker exec` (FR-009). The schema is
migrated v2 → v3 in one transaction (FR-029); FEAT-001 / FEAT-002
/ FEAT-003 surfaces remain unchanged (FR-030, FR-031). No network
listener, no in-container daemon, no third-party runtime
dependency.

## Technical Context

**Language/Version**: Python 3.11+ (inherits from FEAT-001 /
FEAT-002 / FEAT-003). `subprocess.run(..., timeout=...)` with
`text=True`, `check=False`, and typed argv (no shell) covers every
new in-container call; `sqlite3` and `threading` are sufficient for
state and serialization; `uuid.uuid4` allocates `scan_id`.

**Primary Dependencies**: Standard library only — `subprocess`,
`sqlite3`, `threading`, `uuid`, `datetime`, `pathlib`, `argparse`,
`shutil` (for `which`), `os`, `time`, `dataclasses`, `typing`,
`json`. No third-party runtime dependency added (constitution
technical constraints; pyproject already pins
`requires-python>=3.11` and declares no runtime deps). The existing
optional `[test]` extra (`pytest>=7`) is the test harness.

**Storage**: Extends the FEAT-003 SQLite database
(`agenttower.sqlite3`) with two new tables — `panes` and
`pane_scans` — gated behind a schema migration that bumps
`schema_version` from `2` to `3`. Appends one JSONL record to the
existing FEAT-001 events file (`events.jsonl`) **only when** a pane
scan is degraded (FR-025); healthy scans write nothing to the
events file. No new files, sockets, or directories are introduced.

**Testing**: pytest (≥ 7). Unit tests cover socket-listing parsing,
`tmux list-panes` row parsing, per-pane sanitization/truncation,
per-`(container, socket)` reconciliation, the new socket method
handlers, the `TmuxAdapter` Protocol seam, and the migration v2→v3.
Integration tests drive the full CLI surface
(`agenttower scan --panes`, `agenttower list-panes`) over a live
daemon spawned exactly the way FEAT-003 already does, but with a
new `AGENTTOWER_TEST_TMUX_FAKE` env var pointing at a JSON fixture
that drives the `FakeTmuxAdapter`. The harness reuses
`AGENTTOWER_TEST_DOCKER_FAKE` for FEAT-003's container surface so
both adapters can be faked simultaneously. No test invokes
`docker` or `tmux` (FR-034, SC-009).

**Target Platform**: Linux/WSL developer workstations with Docker
CLI available on `PATH`. Single host user; everything stays under
the host user's `opensoft/agenttower` namespace. The daemon
already runs exclusively on the host (constitution principle I);
FEAT-004 changes nothing about that deployment shape and does not
introduce in-container processes beyond the enumerated `docker
exec` payloads (FR-032, FR-033).

**Project Type**: Single-project Python CLI + daemon. Extends
`src/agenttower/`. The previously empty `src/agenttower/tmux/`
package is now populated by this feature. `cli.py`, `daemon.py`,
`socket_api/methods.py`, `socket_api/errors.py`, and
`state/schema.py` are extended; a new `state/panes.py` module is
added next to `state/containers.py`. No new top-level package.

**Performance Goals**: SC-006 — a `docker exec` timeout against one
container produces a `docker_exec_timeout` per-container error
within the 5-second per-call budget without orphaning the child or
blocking the rest of the scan. Worst-case mutex hold for a single
fully-hung container with K candidate sockets is approximately
`5 * (1 + 1 + K)` seconds (one `id -u`, one socket-listing, K
list-panes). With C active containers the worst case is roughly
`C * 5 * (2 + K_max)`; in practice C ≤ 20 and K_max ≤ 3 on a
developer workstation, so a fully-degraded scan is bounded by tens
of seconds. Healthy scans against typical bench inventories
(C ≤ 5, K = 1, P ≤ 30) should complete well under 1 s on a
normally-loaded host. `list_panes` is read-only and MUST return
within 100 ms for ≤ 1000 rows.

**Constraints**:
- No network listener (constitution I; FR-031). MVP keeps the
  FEAT-002 socket-file authorization (`0600`, host user only) and
  adds no new transport, role, or auth tier (FR-031).
- No third-party runtime dependency.
- No real Docker or tmux invocation inside the test suite (FR-034,
  SC-007, SC-009).
- Existing FEAT-001 / FEAT-002 / FEAT-003 socket methods, CLI verbs,
  and persisted SQLite schema MUST remain unchanged
  (FR-030); FEAT-004 only *reads* `containers` rows.
- Subprocess command construction MUST never interpolate raw values
  into a shell string (constitution III; FR-021). Every
  `docker exec` call uses `shell=False` typed argv. The set of
  in-container commands is closed (FR-033): one `id -u` per scanned
  container; one socket-listing call per container; one
  `tmux -S <socket> list-panes -a -F <format>` per discovered
  socket. Container ids, names, bench user, socket paths, and
  pane-derived strings are passed as argv elements only.
- Docker binary resolution reuses FEAT-003's strategy
  (`shutil.which("docker")` against the daemon's inherited `PATH`
  at scan time; FR-022). A missing or non-executable resolved
  binary produces an `ok:false` envelope with `docker_unavailable`
  and persists a `pane_scans` row in the same shape FEAT-003 uses
  for whole-scan failures.
- Per-call subprocess timeouts are bounded by 5 seconds (FR-018).
  A timeout is normalized to a closed-set
  `docker_exec_timeout` per-container or per-socket error; the
  child process MUST be terminated and waited on before the
  reconciler proceeds.
- Pane field values stored anywhere (SQLite, JSONL, socket
  responses, CLI JSON, lifecycle log) MUST be NUL- and
  control-byte-sanitized and bounded to per-field maximums
  (`pane_title` ≤ 2048, `pane_current_command` ≤ 2048,
  `pane_current_path` ≤ 4096, all other text fields ≤ 2048).
  Oversized values are truncated; truncation is recorded as a
  per-pane note in the scan result (FR-023).
- Pane reconciliation is keyed on the composite
  `(container_id, tmux_socket_path, tmux_session_name,
  tmux_window_index, tmux_pane_index, tmux_pane_id)` (FR-007).
  Pane rows MUST NOT be deleted on reconciliation (FR-008). When
  every socket inside a container fails to scan and tmux is
  absent, prior pane rows for that container preserve their prior
  `active` flag and only `last_scanned_at` is updated (FR-010);
  partial socket failures preserve sibling sockets' rows
  unchanged (FR-011).
- Inactive-container cascade: containers whose `containers.active`
  reads `0` at scan start MUST have their previously active panes
  marked inactive in the same FEAT-004 transaction without
  invoking `docker exec` (FR-009).
- Pane scans are serialized by a *new* in-process
  `threading.Lock`, independent of the FEAT-003 scan mutex
  (FR-017). The two scan mutexes do not block each other.
- Pane-scan transactions: one `BEGIN IMMEDIATE` per scan that
  inserts the `pane_scans` row plus all `panes`
  upsert/touch/inactivate writes; rollback on failure releases
  the mutex, returns `internal_error`, suppresses the JSONL
  append (FR-024).
- `list_panes` is read-only, MUST NOT call Docker or tmux, MUST
  NOT acquire the pane-scan mutex, and MUST return rows in the
  deterministic order
  `active DESC, container_id ASC, tmux_socket_path ASC,
  tmux_session_name ASC, tmux_window_index ASC,
  tmux_pane_index ASC` (FR-016).
- The bench user used for `docker exec -u <bench-user>` is derived
  per scan from the FEAT-003 `containers.config_user` column when
  populated, falling back to `os.environ["USER"]` of the daemon
  process (FR-020). The numeric uid that builds
  `/tmp/tmux-<uid>/` is resolved by a bounded in-container
  `id -u` call at scan time, NOT assumed to be `1000` (FR-020).
- Persisted/error surfaces are allowlisted and bounded in the same
  spirit as FEAT-003: no raw `tmux list-panes` output, no raw
  `docker exec` stderr beyond the bounded message, no raw
  environment, no unbounded text in lifecycle logs or JSONL
  (FR-026). Per-socket failure reasons in the SQLite scan row,
  the JSONL degraded event, the socket response, and the CLI
  `--json` payload share one canonical shape:
  `{container_id, tmux_socket_path?, error_code, error_message,
  pane_truncations?}`.

**Scale/Scope**: One host user, one daemon, two new tables, two
new socket methods, two new CLI verbs, one new schema migration
(v2 → v3), one new pane-scan mutex, and one new test-only
environment hook (`AGENTTOWER_TEST_TMUX_FAKE`). Expected steady
state on a developer workstation: ≤ 20 active bench containers,
≤ 3 tmux sockets each, ≤ 30 panes total per container,
≤ 5 pane scans per minute. Scan/list response payloads are
single-digit kilobytes per active pane after bounded
sanitization. FEAT-002's 64 KiB request-line cap remains a
request-only cap; FEAT-004 introduces no new response-size error
code.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle                     | Status | Evidence |
| ----------------------------- | ------ | -------- |
| I. Local-First Host Control   | PASS   | All new work runs in the existing host daemon over the existing `AF_UNIX` socket. FR-031 forbids any new network listener; FEAT-004's tests assert the same harness invariant the FEAT-002/FEAT-003 tests do (no AF_INET/AF_INET6). No durable state moves out of the host's `opensoft/agenttower` namespace. |
| II. Container-First MVP       | PASS   | This feature is the first MVP step that targets bench *tmux panes* directly inside running bench containers via `docker exec -u <bench-user>`. Host-only tmux discovery, in-container daemon, log capture, and input delivery are explicitly out of scope (FR-031). |
| III. Safe Terminal Input      | PASS (vacuously) | FR-031 forbids any input delivery in this feature. Every in-container command uses `shell=False` typed argv (FR-021); container ids, container names, bench user, socket paths, and pane field values are never interpolated into a shell string. |
| IV. Observable and Scriptable | PASS   | Both new CLI verbs ship dual output modes (default human-readable; `--json` line-canonical). Healthy and degraded scans persist to SQLite (`pane_scans`); degraded scans additionally land in the FEAT-001 JSONL events file (FR-025). All failure paths return a non-zero exit with an actionable stderr line that mirrors FEAT-002/FEAT-003 patterns. |
| V. Conservative Automation    | PASS   | The daemon discovers panes; it does not register agents, attach logs, classify events, or deliver input (FR-031). Reconciliation never deletes pane history (FR-008); the unknown-container-state path preserves the prior `active` flag rather than guessing (FR-010). |

| Technical Constraint                                                          | Status | Evidence |
| ----------------------------------------------------------------------------- | ------ | -------- |
| Primary language Python                                                       | PASS   | Python 3.11+, stdlib only. |
| Console entrypoints `agenttower` & `agenttowerd`                              | PASS   | Extends `agenttower` with `scan --panes` and `list-panes` subcommands. `agenttowerd run` is unchanged. |
| Files under `~/.config` / `~/.local/state` / `~/.cache` `opensoft/agenttower` | PASS   | `panes` and `pane_scans` tables live in the existing `agenttower.sqlite3`; degraded events append to the existing `events.jsonl`. No new path. |
| Docker default `name_contains = ["bench"]`, host `docker exec -u "$USER"`     | PASS   | The bench-user fallback is `os.environ["USER"]` per FR-020. The default container-matching rule is owned by FEAT-003 and is not modified here. |
| CLI: human-readable defaults + structured output where it helps               | PASS   | Both new commands ship `--json` (FR-014, FR-015). |

| Development Workflow                                                          | Status | Evidence |
| ----------------------------------------------------------------------------- | ------ | -------- |
| Build in `docs/mvp-feature-sequence.md` order                                 | PASS   | This is FEAT-004, immediately after FEAT-003. |
| Each feature CLI-testable                                                     | PASS   | Both new CLI verbs are exercised end-to-end against a live daemon with a `FakeTmuxAdapter` and a `FakeDockerAdapter`. |
| Tests proportional to risk; broader for daemon state, sockets, Docker/tmux adapters, permissions, and input delivery | PASS | Adapter parsing, error normalization, timeout handling, per-`(container, socket)` reconciliation, mutex serialization (independent of the FEAT-003 scan mutex), and full CLI round-trip all get integration coverage. |
| Preserve existing docs and NotebookLM sync mappings                           | PASS   | This feature does not edit existing Markdown under `docs/`. |
| No TUI, web UI, or relay before the core slices work                          | PASS   | None introduced here. FEAT-004 is the third core slice (after FEAT-002 daemon and FEAT-003 container discovery). |
| Decide explicitly whether `/speckit.checklist <topic>` is needed before tasks | DECISION | A `security` checklist is recommended before `/speckit.tasks` because FEAT-004 is the *first* feature that runs subprocesses **inside** trusted-but-untrusted bench containers, and pane-derived strings (titles, cwds) are the first user-controllable data persisted from a container surface. Verifying argv construction, bench-user / uid resolution, sanitization bounds, and timeout enforcement is worth a topic-specific gate. The decision and rationale are recorded here so the next agent invocation honors it. |

**Result**: Gates pass. No `Complexity Tracking` entries required.

## Project Structure

### Documentation (this feature)

```text
specs/004-container-tmux-pane-discovery/
├── plan.md                        # This file (/speckit.plan output)
├── research.md                    # Phase 0 output: resolved decisions
├── data-model.md                  # Phase 1 output: tables, entity shapes, state transitions
├── quickstart.md                  # Phase 1 output: end-to-end CLI walkthrough
├── contracts/
│   ├── cli.md                     # User-facing CLI contracts (C-CLI-401, C-CLI-402)
│   └── socket-api.md              # New socket methods (C-API-401, C-API-402)
├── checklists/                    # /speckit.checklist outputs (currently empty)
└── tasks.md                       # /speckit.tasks output (NOT created by /speckit.plan)
```

### Source Code (repository root)

Only files actually touched by FEAT-004 are listed. FEAT-001 /
FEAT-002 / FEAT-003 files remain unchanged unless an explicit
"EXTENDS" note appears.

```text
src/agenttower/
├── cli.py                                # EXTENDS: add `scan --panes` flag handler and `list-panes` subparser; both accept --json
├── daemon.py                             # EXTENDS: build a PaneDiscoveryService and a TmuxAdapter at startup; attach to DaemonContext; close the new connection on shutdown
├── socket_api/
│   ├── errors.py                         # EXTENDS: add new error codes (`tmux_unavailable`, `tmux_no_server`, `socket_dir_missing`, `socket_unreadable`, `docker_exec_failed`, `docker_exec_timeout`, `output_malformed`)
│   ├── methods.py                        # EXTENDS: register `scan_panes` and `list_panes` handlers; extend DaemonContext with a pane-discovery service handle
│   └── server.py                         # unchanged (dispatch is data-driven)
├── state/
│   ├── schema.py                         # EXTENDS: bump CURRENT_SCHEMA_VERSION to 3; add `_apply_migration_v3()` that creates `panes` and `pane_scans`
│   └── panes.py                          # NEW: typed dataclasses + read/write helpers for the two new tables
├── tmux/
│   ├── __init__.py                       # NEW: package marker; re-exports TmuxAdapter, SubprocessTmuxAdapter, FakeTmuxAdapter
│   ├── adapter.py                        # NEW: TmuxAdapter Protocol; PaneRow / SocketListing / TmuxError dataclasses
│   ├── subprocess_adapter.py             # NEW: SubprocessTmuxAdapter — real implementation; argv construction for `id -u`, socket-dir listing, `tmux list-panes`; 5 s timeouts; return-code → TmuxError mapping
│   ├── parsers.py                        # NEW: pure parse helpers for `id -u` output, socket-dir listing output, and `tmux list-panes -F` rows
│   └── fakes.py                          # NEW: FakeTmuxAdapter — scriptable in-memory adapter for tests; loadable via AGENTTOWER_TEST_TMUX_FAKE
└── discovery/
    ├── pane_service.py                   # NEW: PaneDiscoveryService — owns the pane-scan mutex, runs scan-then-reconcile, returns PaneScanResult
    └── pane_reconcile.py                 # NEW: pure SQL-free reconciliation: per-(container, socket) write set; preserves prior rows for tmux_unavailable / failed sockets

tests/
├── unit/
│   ├── test_tmux_parsers.py                       # NEW: tmux list-panes row parsing; missing-field rows flagged as malformed
│   ├── test_tmux_subprocess_adapter.py            # NEW: argv construction (no shell), timeout normalization, exec failure → TmuxError
│   ├── test_pane_reconcile.py                     # NEW: per-(container, socket) reconciliation; tmux_unavailable preservation; partial-socket preservation; inactive-container cascade
│   ├── test_pane_field_sanitize.py                # NEW: NUL/control-byte stripping; per-field truncation thresholds; per-pane truncation note
│   ├── test_state_panes.py                        # NEW: panes + pane_scans table writes; composite-key upsert; schema v2→v3 migration idempotence
│   └── test_socket_api_pane_methods.py            # NEW: in-process dispatch of scan_panes / list_panes; mutex independence from FEAT-003 mutex
└── integration/
    ├── test_cli_scan_panes.py                     # NEW: scan_panes with fake adapters (Docker + tmux); persisted records visible via list-panes; default + --json
    ├── test_cli_list_panes.py                     # NEW: default ordering (active first, deterministic tiebreak), --active-only filter, --container filter, --json schema
    ├── test_cli_scan_panes_multi_socket.py        # NEW: two sockets in one container; per-socket reconciliation; one-socket-fails preserves the other (FR-011)
    ├── test_cli_scan_panes_tmux_unavailable.py    # NEW: tmux missing/no-server → degraded; prior panes preserved (FR-010)
    ├── test_cli_scan_panes_inactive_cascade.py    # NEW: container marked inactive → panes cascade-inactive without docker exec (FR-009)
    ├── test_cli_scan_panes_timeout.py             # NEW: docker_exec_timeout normalization; remaining containers continue; daemon stays alive (SC-006)
    ├── test_cli_scan_panes_concurrent.py          # NEW: two parallel scan_panes serialize via the new mutex; container scan + pane scan can overlap (FR-017)
    ├── test_cli_scan_panes_no_real_docker.py      # NEW: harness-level guard that asserts `docker` and `tmux` are never spawned during the test session (SC-009)
    └── test_feat004_no_network.py                 # NEW: assert no AF_INET/AF_INET6 socket is opened by the daemon under FEAT-004 load (FR-031)
```

**Structure Decision**: Keep the FEAT-001 / FEAT-002 / FEAT-003
single-project layout. The previously-empty `tmux/` package is
populated for the first time, mirroring the
`docker/` package's Protocol + Subprocess + Fake + parsers split
introduced by FEAT-003. Pane state helpers go under
`state/panes.py` so the schema module remains the single owner of
the migration sequence and the dataclasses live next to the SQL
that reads them. `discovery/pane_service.py` and
`discovery/pane_reconcile.py` are new siblings of FEAT-003's
`discovery/service.py` and `discovery/reconcile.py`; the FEAT-003
container service is *not* modified beyond an additive
read-only call (`select_active_containers_with_user`) added to
`state/containers.py`. Both new socket methods delegate to the
pane service.

## Complexity Tracking

> No constitutional violations to justify. This section is intentionally empty.
