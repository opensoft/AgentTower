# Implementation Plan: Host Daemon Lifecycle and Unix Socket API

**Branch**: `002-host-daemon-socket-api` | **Date**: 2026-05-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-host-daemon-socket-api/spec.md`

## Summary

Add the `agenttowerd run` daemon mode and the three user-facing CLI
clients (`agenttower ensure-daemon`, `agenttower status`,
`agenttower stop-daemon`) on top of FEAT-001's package and path
contract. The daemon binds a host-user-only `AF_UNIX` stream socket at
the FEAT-001 `SOCKET` path, exposes a newline-delimited JSON
request/response API with three methods (`ping`, `status`, `shutdown`),
and runs an idempotent startup that uses a single `fcntl.flock` on
`<STATE_DIR>/agenttowerd.lock` as the authoritative liveness signal.
Stale pid, lock, and socket artifacts are recovered automatically when
the kernel-released lock proves no live daemon owns them. The daemon
emits a tab-separated lifecycle log (six event tokens) under FEAT-001's
`LOGS_DIR` and writes nothing to FEAT-001's `EVENTS_FILE`. No network
listener is opened (constitution principle I, FR-010, SC-007). The
implementation is Python 3.11+ standard library only, with
`socketserver.ThreadingUnixStreamServer` for I/O and `subprocess.Popen`
with `start_new_session=True` for daemonization (no double-fork).

## Technical Context

**Language/Version**: Python 3.11+ (inherits FEAT-001's floor; `tomllib`
remains in stdlib, `fcntl` and `signal` available on Linux/macOS).
**Primary Dependencies**: Standard library only — `socket`,
`socketserver`, `fcntl`, `signal`, `subprocess`, `threading`, `json`,
`os`, `errno`, `stat`, `pathlib`, `argparse`, `sqlite3`,
`importlib.metadata`, `datetime`, `time`. No third-party runtime
dependencies, matching FEAT-001's constraint.
**Storage**: Reads only — one row from FEAT-001's
`schema_version` SQLite table at daemon startup (cached in memory for
the daemon's lifetime, R-013). Writes only — one append-only TSV file
at `<LOGS_DIR>/agenttowerd.log` (R-012); two short marker files
(`agenttowerd.lock`, `agenttowerd.pid`) under `<STATE_DIR>`; one
`AF_UNIX` socket inode at `<STATE_DIR>/agenttowerd.sock`. **No SQLite
table is added in FEAT-002.** **No JSONL event record is appended** to
`EVENTS_FILE` (FR-027).
**Testing**: pytest (≥ 7), the same harness FEAT-001 established.
Per-test environment isolation via `tmp_path` + `monkeypatch` of
`$HOME` and the XDG variables. Subprocess-level integration tests
exercise the full `ensure-daemon` → daemon → `status` → `stop-daemon`
loop without Docker or tmux. Socket-protocol contract tests use a raw
`socket.socket(AF_UNIX, SOCK_STREAM)` client. Concurrent-startup tests
use Python's `concurrent.futures.ProcessPoolExecutor` to run multiple
`ensure-daemon` invocations in parallel.
**Target Platform**: Linux/WSL developer workstations with POSIX
filesystem and `AF_UNIX` semantics. Single host user (constitution).
**Project Type**: Single-project Python CLI + daemon — extends
FEAT-001's `src/agenttower/` layout. Adds modules under
`src/agenttower/socket_api/`, extends `daemon.py` and `cli.py`. Empty
package directories owned by FEAT-003+ (`discovery/`, `docker/`,
`logging/`, `routing/`, `tmux/`) remain untouched.
**Performance Goals**: SC-001 (`ensure-daemon` ready within 2 s),
SC-003 (`status` round-trip within 1 s), SC-004 (recovery within 3 s),
SC-006 (post-shutdown `ensure-daemon` succeeds with no manual
cleanup), SC-009 (5 concurrent `ensure-daemon` invocations all exit
`0` and leave exactly one daemon).
**Constraints**: No network listener (FR-010, SC-007); strict
host-user-only modes — `0700` parent dirs, `0600` for the lock, pid,
socket, and log files (FR-011, R-011); no Docker/tmux/registration/
routing/input-delivery code paths (FR-023, FR-024); no third-party
runtime dependencies; one request per accepted connection (FR-026);
finish-in-flight shutdown semantics (FR-017, clarification Q4);
lock-first startup serialization (FR-028, clarification Q5); minimal
lifecycle log only — no event/agent/pane entries in FEAT-002 (FR-027,
clarification Q3).
**Scale/Scope**: One host user, one daemon process per resolved state
directory (FR-006), one socket, one lifecycle log, three API methods,
three new user CLI subcommands, one new daemon CLI subcommand
(`agenttowerd run`). Expected concurrent client load is single-digit
connections from the same host (a developer's shell + a few scripts);
the threading model is sized for that, not for production fan-out.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle                       | Status | Evidence                                                                                                                                                  |
| ------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| I. Local-First Host Control     | PASS   | `AF_UNIX` only; FR-010 forbids any TCP/UDP/IPv4/IPv6/raw listener; SC-007 demands automated verification of "no network listener"; socket mode `0600` host-only (FR-011, R-003). |
| II. Container-First MVP         | PASS   | FR-023 explicitly excludes container discovery, tmux discovery, log attachment, registration, routing, input delivery, swarm tracking, multi-master arbitration, TUI, Antigravity, in-container relay. The daemon ships exactly what container-first MVP needs to plug into next (FEAT-003). |
| III. Safe Terminal Input        | PASS (vacuously) | FR-024 prohibits writing terminal input or executing commands inside tmux panes in this feature. The accept loop dispatches only the three FEAT-002 methods, none of which can interact with a terminal. |
| IV. Observable and Scriptable   | PASS   | All daemon-facing user behavior reaches through the CLI (FR-018). `status --json` is line-canonical JSON for automation; default form is `key=value` lines for shell parsing. Lifecycle is observable via the TSV log file (FR-027). Failures exit non-zero with actionable stderr (FR-019). |
| V. Conservative Automation      | PASS   | The daemon transports control requests; it makes no workflow decisions, runs no model-selection logic, and answers no agent questions. It is a pure transport + lifecycle slice. |

| Technical Constraint                                                  | Status | Evidence                                                                                                                |
| --------------------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------- |
| Primary language is Python                                            | PASS   | Python 3.11+, stdlib only. No third-party runtime deps.                                                                 |
| Console entrypoints `agenttower` & `agenttowerd`                      | PASS   | FEAT-002 extends both: `agenttowerd run` (R-015) and three new `agenttower` subcommands (R-016).                        |
| Files under `~/.config`/`~/.local/state`/`~/.cache` `opensoft/agenttower` | PASS | Lock, pid, socket, lifecycle log all live under FEAT-001's `STATE_DIR` / `LOGS_DIR` (data-model.md §1).                 |
| Docker default `name_contains = ["bench"]`, host `docker exec -u "$USER"` | OUT OF SCOPE | FR-023 excludes Docker entirely from FEAT-002. FEAT-003 inherits FEAT-001's default config block.                    |
| CLI: human-readable defaults + structured output where it helps       | PASS   | All three new CLI commands ship dual output modes (`status` default vs `status --json`, etc.; contracts/cli.md C-CLI-103). |

| Development Workflow                                                          | Status | Evidence                                                                                                              |
| ----------------------------------------------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------- |
| Build in `docs/mvp-feature-sequence.md` order                                 | PASS   | This is FEAT-002, immediately after FEAT-001.                                                                         |
| Each feature CLI-testable                                                     | PASS   | All four user-visible behaviors (`ensure-daemon`, `status`, `stop-daemon`, `agenttowerd run` foreground) exercise the full feature. |
| Tests proportional to risk; broader for daemon state, sockets, permissions   | PASS   | Dedicated tests for the lock primitive, stale-recovery matrix, mode/uid enforcement, signal handling, concurrent-startup race, and full socket-protocol coverage (see Project Structure below). |
| Preserve existing docs and NotebookLM sync mappings                           | PASS   | This feature does not edit existing Markdown under `docs/`.                                                           |
| No TUI, web UI, or relay before the core slices work                          | PASS   | None introduced here. FR-023 explicitly excludes TUI, Antigravity, in-container relay.                                |
| Decide explicitly whether `/speckit.checklist <topic>` is needed before tasks | DECISION | A `security` checklist is recommended (host-user permissions, network-listener prohibition, unsafe-mode handling) before `/speckit.tasks`. The decision and rationale are recorded here so the next agent invocation honors it. |

**Result**: Gates pass. No `Complexity Tracking` entries required.

## Project Structure

### Documentation (this feature)

```text
specs/002-host-daemon-socket-api/
├── plan.md                        # This file (/speckit.plan output)
├── research.md                    # Phase 0 output: 17 resolved decisions
├── data-model.md                  # Phase 1 output: filesystem + state machine + wire format
├── quickstart.md                  # Phase 1 output: end-to-end CLI walkthrough
├── contracts/
│   ├── cli.md                     # User-facing CLI contracts (C-CLI-101..104)
│   └── socket-api.md              # Local Unix socket protocol (C-API-001..005)
├── checklists/
│   └── requirements.md            # /speckit.specify quality checklist
└── tasks.md                       # /speckit.tasks output (NOT created by /speckit.plan)
```

### Source Code (repository root)

Only files actually touched by FEAT-002 are listed. FEAT-001 files
remain unchanged unless an explicit "extends" note appears.

```text
src/agenttower/
├── __init__.py                    # (FEAT-001) unchanged
├── cli.py                         # EXTENDS: add ensure-daemon, status, stop-daemon subparsers
├── daemon.py                      # EXTENDS: add `run` subcommand → daemon main
├── paths.py                       # (FEAT-001) unchanged; consumed by FEAT-002
├── config.py                      # (FEAT-001) unchanged
├── state/
│   ├── __init__.py                # (FEAT-001) unchanged
│   └── schema.py                  # (FEAT-001) unchanged; FEAT-002 reads schema_version
├── events/                        # (FEAT-001) unchanged; FEAT-002 does NOT call append_event
└── socket_api/
    ├── __init__.py                # NEW: package marker, public re-exports
    ├── lifecycle.py               # NEW: lock acquisition, stale-artifact classification + recovery, pid file management, lifecycle log emitter (R-001/R-002/R-004/R-011/R-012)
    ├── server.py                  # NEW: ThreadingUnixStreamServer, request handler, JSON framing, dispatch, shutdown sequencing (R-003/R-005/R-006/R-007/R-008)
    ├── methods.py                 # NEW: ping / status / shutdown method implementations (R-013/R-014)
    ├── client.py                  # NEW: minimal AF_UNIX client used by all three CLI commands (one-line request → one-line response, used by C-CLI-102/103/104)
    └── errors.py                  # NEW: error code constants + helpers for the closed code set (R-014)

tests/
├── unit/
│   ├── test_socket_api_lifecycle.py     # NEW: lock acquisition, stale-pid logic, mode/uid checks, lifecycle log line shape
│   ├── test_socket_api_methods.py       # NEW: ping/status/shutdown method-level dispatch (in-process, no real socket)
│   ├── test_socket_api_framing.py       # NEW: JSON envelope validation, error code mapping, 64 KiB cap
│   └── test_socket_api_client.py        # NEW: client connect/timeout/error-code surfaces
└── integration/
    ├── test_cli_ensure_daemon.py        # NEW: idempotence (FR-007), pre-flight refusal (FR-003), unsafe-permission refusal (SC-008)
    ├── test_cli_status.py               # NEW: alive case, daemon-unavailable case (US2 #2), --json
    ├── test_cli_stop_daemon.py          # NEW: clean stop, no-reachable-daemon (US4 #3), --json
    ├── test_daemon_lifecycle.py         # NEW: full start → status → stop loop end-to-end via subprocess
    ├── test_daemon_recovery.py          # NEW: stale pid / stale socket / non-socket file at socket path (US3, FR-008/FR-009, SC-004)
    ├── test_daemon_signals.py           # NEW: SIGTERM and SIGINT cleanup (FR-022, SC-006)
    ├── test_daemon_concurrent_start.py  # NEW: 5 parallel ensure-daemon invocations (SC-009, FR-028)
    ├── test_daemon_no_network.py        # NEW: lsof / ss-style verification that no AF_INET/AF_INET6 socket is opened (SC-007)
    └── test_socket_api_protocol.py      # NEW: raw-socket protocol tests for all three methods + every error code (FR-021, SC-005)
```

**Structure Decision**: Single-project layout, kept consistent with
FEAT-001's `src/agenttower/` scaffolding. The previously-empty
`socket_api/` package is now populated by this feature and is the only
new subpackage introduced. The other empty subpackages (`discovery/`,
`docker/`, `logging/`, `routing/`, `tmux/`) remain placeholders for
FEAT-003+ and are intentionally untouched here. `cli.py` and `daemon.py`
are extended, not rewritten — FEAT-001's existing argparse subparsers
and entrypoints stay in place.

## Complexity Tracking

> No constitutional violations to justify. This section is intentionally empty.
