---

description: "Task list for FEAT-002: Host Daemon Lifecycle and Unix Socket API"
---

# Tasks: Host Daemon Lifecycle and Unix Socket API

**Input**: Design documents from `/specs/002-host-daemon-socket-api/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/cli.md, contracts/socket-api.md, quickstart.md, checklists/security.md

**Tests**: This feature includes test tasks because the AgentTower constitution
mandates "broader tests for daemon state, socket protocol, permissions" and the
plan's Project Structure explicitly lists test files. Tests are written
alongside or before the matching implementation task; per-story integration
tests run after that story's implementation tasks complete.

**Organization**: Tasks are grouped by user story to enable independent
implementation and testing of each story. Per-story acceptance is anchored to
spec.md user-story acceptance scenarios and SC-* measurable outcomes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- All paths are repository-relative; the project root is the worktree at `002-host-daemon-socket-api`.

## Path Conventions

Single-project Python layout, inherited from FEAT-001:

- Source: `src/agenttower/`
- Tests: `tests/unit/`, `tests/integration/`

---

## Phase 1: Setup (Spec Hardening from Security Checklist)

**Purpose**: Resolve the high-impact gaps surfaced by
`checklists/security.md` *before* writing code so the implementation
targets a hardened spec. Each sub-bullet ties to a specific CHK item.

- [ ] T001 Address high-impact security-checklist gaps directly in `specs/002-host-daemon-socket-api/spec.md`:
  - Add an explicit FR for the request-line size limit (CHK016): hoist the 64 KiB cap from `research.md` R-006 into the spec's Functional Requirements list.
  - Add an explicit "Out of Scope (FEAT-002)" note for connection-level DoS controls — concurrent-connection cap, slow-client read-timeout, rate limiting (CHK021/22/23) — with a single-host-user-threat-model rationale.
  - Add a constraint to the Assumptions or Constraints section stating that FEAT-002 introduces no third-party runtime dependencies, independent of FEAT-001 (CHK030).
  - Add an Assumptions bullet documenting the implicit threat model: single host user, no remote attacker, malicious local-process-at-same-uid out of scope (CHK040/41).
  - Add an Assumptions bullet acknowledging the security implications of `setsid()`-based detached-session daemonization and noting why it is acceptable for MVP (CHK042).

**Checkpoint**: Spec reflects the security review's blocking gaps. Re-run `/speckit-checklist security` only if substantive new ambiguity is introduced.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the shared primitives every user story depends on:
the wire-error vocabulary, the lifecycle-log emitter, the
`fcntl.flock`-based lock primitive, and the path-safety verifier.

**⚠️ CRITICAL**: No user story implementation can begin until this phase is complete.

- [ ] T002 [P] Create error code constants and JSON-error-response helpers in `src/agenttower/socket_api/errors.py` per `research.md` R-014: closed code set `{bad_json, bad_request, unknown_method, request_too_large, internal_error}` plus `make_error(code, message) -> dict` and `make_ok(result) -> dict` builders.
- [ ] T003 [P] Create public package surface in `src/agenttower/socket_api/__init__.py`: re-export the daemon-runtime entry point (used by `daemon.py`) and the AF_UNIX client (used by `cli.py`); no business logic in this file.
- [ ] T004 Implement core lifecycle primitives in `src/agenttower/socket_api/lifecycle.py` per `research.md` R-001 / R-002 / R-011 / R-012: `acquire_exclusive_lock(lock_path)` using `fcntl.flock(LOCK_EX | LOCK_NB)`; `assert_paths_safe(paths)` mode/owner verifier; `write_pid_file(path, pid)`; `LifecycleLogger` class that opens `<LOGS_DIR>/agenttowerd.log` append-mode 0600 and emits TSV lines for the six event tokens. (Stale-classification + recovery is added later by US3 / T024.)
- [ ] T005 [P] Add unit tests for the error helpers in `tests/unit/test_socket_api_framing.py`: every code in the closed set produces the documented envelope shape; `make_ok(...)` round-trips through `json.dumps`/`json.loads`. (Same file is extended by US1 framing tests; this seeds the file.)
- [ ] T006 [P] Add unit tests for lifecycle primitives in `tests/unit/test_socket_api_lifecycle.py`: lock acquisition succeeds on empty state, fails non-blocking when held, releases on fd close; `assert_paths_safe` accepts 0700/0600 with current uid and refuses 0755 / wrong uid / missing path; lifecycle log writes one TSV line per event with the documented columns and creates the file at mode 0600.

**Checkpoint**: Foundational primitives ready. User-story phases may now proceed in parallel by area.

---

## Phase 3: User Story 1 — Start One Host Daemon (Priority: P1) 🎯 MVP

**Goal**: `agenttower ensure-daemon` is idempotent, lock-serialized, and brings a single live daemon up within 2 s on an initialized host. A `ping` round-trip on the socket confirms readiness.

**Independent Test**: From an initialized AgentTower state directory with no daemon running, run `agenttower ensure-daemon` twice and verify both invocations exit 0 and only one daemon owns the socket. Run 5 invocations concurrently (SC-009) and verify the same property. Run 20 sequentially (SC-002).

### Implementation for User Story 1

- [ ] T007 [US1] Implement the threaded socket server, per-connection request handler, JSON line framing (≤ 64 KiB), and method dispatcher in `src/agenttower/socket_api/server.py` per `research.md` R-003 / R-005 / R-006: `ThreadingUnixStreamServer` subclass with `daemon_threads=True`, `umask(0o077)`-then-`bind` socket creation, post-bind mode/uid verification, request handler that reads one line and writes one line, dispatcher that routes to the methods module. (Shutdown sequencing is added later by US4 / T029.)
- [ ] T008 [US1] Implement the minimal AF_UNIX client in `src/agenttower/socket_api/client.py`: `send_request(socket_path, method, params=None, *, connect_timeout=1.0, read_timeout=1.0) -> dict`; classified exceptions for `DaemonUnavailable` (file-not-found / refused / timeout) and `DaemonError` (response with `ok=false`).
- [ ] T009 [US1] Implement the `ping` method in `src/agenttower/socket_api/methods.py` per `contracts/socket-api.md` §4: dispatcher entry returns `{"ok": true, "result": {}}` and mutates no state. (Stub `status` and `shutdown` to return `unknown_method` until US2 / US4 land them; this keeps the dispatch table closed.)
- [ ] T010 [US1] Extend `src/agenttower/daemon.py` to add the `run` subcommand that wires the daemon main: parse argv, verify FEAT-001 init, acquire lock (T004), `assert_paths_safe`, classify+recover stale artifacts via the recovery hook (initially a no-op, fleshed out in T024/T025), bind socket via T007's server, write pid file (T004), open `LifecycleLogger`, emit `daemon_starting` / `daemon_ready`, install signal hooks (initially a no-op, fleshed out in T029), enter accept loop. `agenttowerd --version` behavior unchanged from FEAT-001. Ensure `python -m agenttower.daemon run` works (R-009).
- [ ] T011 [US1] Extend `src/agenttower/cli.py` with the `ensure-daemon` subcommand per `contracts/cli.md` C-CLI-102: pre-flight FEAT-001 init check; socket-probe with `ping`; non-blocking lock probe; `subprocess.Popen(..., start_new_session=True)` of `agenttowerd run` with stdout/stderr → `<LOGS_DIR>/agenttowerd.log`; ready-poll on 10/50/100/200 ms backoff up to 2 s budget; dual output (`agenttowerd ready: pid=... socket=... state=...` default; canonical-JSON one-liner under `--json`); exit codes 0/1/2/4 per the contract.
- [ ] T012 [P] [US1] Extend `tests/unit/test_socket_api_framing.py` with JSON envelope validation cases per `contracts/socket-api.md` §3: non-UTF-8 → `bad_json`, non-object JSON → `bad_request`, missing/non-string `method` → `bad_request`, `params` not an object → `bad_request`, line > 64 KiB → `request_too_large`, valid `ping` → `{ok:true,result:{}}`.
- [ ] T013 [P] [US1] Add `ping`-method unit tests in `tests/unit/test_socket_api_methods.py`: dispatch returns success envelope; no SQLite or filesystem mutation; idempotent under repeated calls.
- [ ] T014 [P] [US1] Add AF_UNIX client unit tests in `tests/unit/test_socket_api_client.py`: connect-timeout surfaces `DaemonUnavailable`; refused-connection surfaces `DaemonUnavailable`; an `{ok:false}` response surfaces `DaemonError` with code/message preserved.
- [ ] T015 [P] [US1] Add integration tests for `ensure-daemon` in `tests/integration/test_cli_ensure_daemon.py`: idempotence (FR-007 — 20 sequential invocations, exactly one live daemon, SC-002); refuses when FEAT-001 not initialized (FR-003); refuses when state-dir mode is wider than 0700 (SC-008); `--json` output has the documented shape; `started=true` on first run, `started=false` on subsequent runs.
- [ ] T016 [P] [US1] Add concurrent-startup integration test in `tests/integration/test_daemon_concurrent_start.py`: 5 parallel `ensure-daemon` invocations against an empty state dir; assert exactly one live daemon and all 5 exit 0 (FR-028, SC-009).
- [ ] T017 [P] [US1] Add no-network-listener integration test in `tests/integration/test_daemon_no_network.py`: start daemon, scan its open file descriptors via `/proc/<pid>/net/tcp{,6}`, `/proc/<pid>/net/udp{,6}` (or `ss -tuanp` filtered to the pid) and assert zero AF_INET/AF_INET6 sockets are bound or listening (FR-010, SC-007).

**Checkpoint**: US1 (P1) MVP shippable. The daemon comes up idempotently and answers `ping`.

---

## Phase 4: User Story 2 — Query Daemon Health (Priority: P2)

**Goal**: `agenttower status` (and the raw `status` API method) reports daemon liveness, identity, paths, schema version, and version, in both human-readable and JSON modes, within 1 s.

**Independent Test**: With the daemon live, `agenttower status` returns within 1 s with the documented six-line key=value output and exit 0; with no daemon, exits 2 with an actionable `daemon-unavailable` message and never invokes Docker, tmux, or any fallback (FR-020).

### Implementation for User Story 2

- [ ] T018 [US2] Implement the `status` method in `src/agenttower/socket_api/methods.py` per `contracts/socket-api.md` §5 / `research.md` R-013: read pid, start-time-utc, uptime-seconds (clamped at 0 on backwards clock jump), socket path, state path, schema_version (from cache, T019), daemon_version (`importlib.metadata.version("agenttower")`).
- [ ] T019 [US2] Wire one-shot schema_version read into the daemon startup sequence in `src/agenttower/socket_api/lifecycle.py` and pass the cached value through to the dispatcher's daemon-context object (read once at startup, never re-read mid-run, R-013).
- [ ] T020 [US2] Extend `src/agenttower/cli.py` with the `status` subcommand per `contracts/cli.md` C-CLI-103: connect with 1 s timeout, dispatch `status`; map `DaemonUnavailable` → exit 2 with the documented stderr line; map `DaemonError` → exit 3 with `error.message` + `code: <error.code>` on stderr; render six-line `key=value` default output or canonical-JSON one-liner under `--json`.
- [ ] T021 [P] [US2] Extend `tests/unit/test_socket_api_methods.py` with `status` field-set tests: shape exactly matches `contracts/socket-api.md` §5; uptime clamps to 0 when `start_time` is monkeypatched into the future; cached schema_version is reflected without re-reading the SQLite file mid-test.
- [ ] T022 [P] [US2] Add integration tests for `agenttower status` in `tests/integration/test_cli_status.py`: alive case (default + `--json`); daemon-unavailable case (US2 acceptance #2; exit 2; specific stderr substring); SC-003 (round-trip ≤ 1 s on a normally-loaded host).
- [ ] T023 [P] [US2] Add raw-socket protocol integration tests in `tests/integration/test_socket_api_protocol.py` covering every error code (`bad_json` via non-UTF-8, `bad_request` via JSON array, `unknown_method` via `{"method":"frobnicate"}`, `request_too_large` via 65 KiB line, plus successful `ping` and `status`); after each error, send a follow-up `ping` on a new connection to assert daemon stays alive (FR-021, SC-005).

**Checkpoint**: US2 (P2) complete. Script-friendly health check works.

---

## Phase 5: User Story 3 — Recover From Stale Daemon State (Priority: P3)

**Goal**: Stale lifecycle artifacts (pid file pointing at a dead process, dangling socket inode, lock file with no holder) are detected and repaired automatically on the next `ensure-daemon`. Non-AgentTower-shaped artifacts at the socket path (regular file, directory, dangling symlink) are *refused*, not removed.

**Independent Test**: Start the daemon; `kill -9` it; rerun `ensure-daemon`; verify a new healthy daemon comes up within 3 s (SC-004) without manual cleanup. Repeat with the socket replaced by a regular file: verify the rerun exits 1 with the documented refusal (FR-009).

### Implementation for User Story 3

- [ ] T024 [US3] Add stale-artifact classification + recovery to `src/agenttower/socket_api/lifecycle.py` per `research.md` R-002 / R-004: helper `classify_socket_path(path) -> {missing|stale_socket|refuse}` honors lock-as-authority; helper `recover_stale_artifacts(paths)` unlinks stale socket and pid file (only when current process holds `LOCK_EX`) and emits a `daemon_recovering` lifecycle log line per artifact unlinked. Refuses when path is regular file, directory, FIFO, dev node, or dangling symlink.
- [ ] T025 [US3] Wire the recovery hook into the `agenttowerd run` startup sequence in `src/agenttower/daemon.py` between lock acquisition and socket bind (replacing the no-op stub left by T010); ensure ordering matches the data-model state machine (STARTING → RECOVERING → READY).
- [ ] T026 [P] [US3] Extend `tests/unit/test_socket_api_lifecycle.py` with classification cases: stale socket (S_ISSOCK with no listener) → unlinked; regular file at socket path → refuse; directory at socket path → refuse; dangling symlink → refuse; missing path → no-op; `daemon_recovering` line emitted only on successful unlink.
- [ ] T027 [P] [US3] Add stale-recovery integration tests in `tests/integration/test_daemon_recovery.py`: kill -9 → ensure-daemon recovers within 3 s (US3 acceptance #1, SC-004); stale socket without daemon → ensure-daemon recovers (US3 acceptance #2); pre-existing live daemon owns the lock → second startup attempt reports the existing daemon and does not disturb it (US3 acceptance #3, FR-007); refusal cases (regular file, directory, dangling symlink at socket path) — exit 1 with documented stderr.

**Checkpoint**: US3 complete. Recovery is automatic for owned artifacts and refusal is explicit for foreign ones.

---

## Phase 6: User Story 4 — Shut Down Cleanly (Priority: P4)

**Goal**: `agenttower stop-daemon` and SIGTERM/SIGINT both trigger the same finish-in-flight shutdown sequence (clarification Q4): stop accepting new connections, complete in-flight responses, unlink owned artifacts, release the lock, exit 0. A subsequent `ensure-daemon` succeeds without manual cleanup (SC-006).

**Independent Test**: Start daemon, run `stop-daemon`; daemon exits 0 within 3 s and the socket becomes unreachable. Repeat with `kill -TERM` / `kill -INT` and verify equivalent cleanup. With no daemon, `stop-daemon` exits 2 with the documented message (US4 acceptance #3).

### Implementation for User Story 4

- [ ] T028 [US4] Implement the `shutdown` method in `src/agenttower/socket_api/methods.py` per `contracts/socket-api.md` §6: write `{"ok":true,"result":{"shutting_down":true}}` to the response stream, then set the daemon-context `shutdown_requested` event so the server's helper thread can drive the shutdown sequence after the response is flushed.
- [ ] T029 [US4] Implement shutdown sequencing in `src/agenttower/socket_api/server.py` per `research.md` R-007 / R-008: `shutdown_requested = threading.Event()`; helper thread drives `server.shutdown()` after the event is set; `server_close()`; per-handler-thread `join(timeout=2.0)`; unlink owned socket / pid file / lock contents under the held lock; emit `daemon_shutdown` and `daemon_exited` lifecycle log lines; close lock fd to release the kernel lock; SIGTERM/SIGINT handlers set the same event; SIGPIPE → SIG_IGN.
- [ ] T030 [US4] Extend `src/agenttower/cli.py` with the `stop-daemon` subcommand per `contracts/cli.md` C-CLI-104: connect with 1 s timeout (no reachable daemon → exit 2 with `error: no reachable daemon to stop`); send `shutdown`; on `ok:true`, poll the socket up to 3 s for `FileNotFoundError`/`ConnectionRefusedError`; render `agenttowerd stopped: socket=... state=...` default or canonical-JSON one-liner under `--json`; exit codes 0/2/3/4.
- [ ] T031 [P] [US4] Extend `tests/unit/test_socket_api_methods.py` with `shutdown` method tests: response shape exactly matches the contract; `shutdown_requested` event is set; method does not itself unlink artifacts (the server thread does, T029).
- [ ] T032 [P] [US4] Add integration tests for `agenttower stop-daemon` in `tests/integration/test_cli_stop_daemon.py`: clean stop (default + `--json`); no-reachable-daemon case (US4 acceptance #3) returns exit 2 with documented stderr.
- [ ] T033 [P] [US4] Add full-lifecycle integration test in `tests/integration/test_daemon_lifecycle.py`: ensure-daemon → status → stop-daemon → ensure-daemon (fresh start, SC-006) all succeed in sequence; assert no orphan socket, pid, or lock-content files remain after stop.
- [ ] T034 [P] [US4] Add signal-driven cleanup integration tests in `tests/integration/test_daemon_signals.py`: `kill -TERM <pid>` triggers the same shutdown path as the API method (FR-022) — daemon exits 0, artifacts removed, subsequent `ensure-daemon` succeeds; `kill -INT <pid>` likewise; both verify SC-006.

**Checkpoint**: US4 complete. All four user stories ship.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validate end-to-end, confirm the security checklist gaps closed by T001 are still closed, and exercise the documented quickstart against a fresh install.

- [ ] T035 Run `specs/002-host-daemon-socket-api/quickstart.md` end-to-end on a clean host (`agenttower config init` → every command in §1–§6 of quickstart) and confirm each documented stdout/stderr/exit-code line matches verbatim. Patch any drift in `quickstart.md` rather than the implementation if a spec change is the right answer.
- [ ] T036 Walk `specs/002-host-daemon-socket-api/checklists/security.md` item-by-item: mark each `[ ]` as either `[x]` (passes review against current spec + code) or convert to a follow-up task here. Pay particular attention to CHK016 (request size FR), CHK030 (no-third-party-deps as FEAT-002 constraint), CHK040/41 (threat model in Assumptions), CHK042 (`setsid()` rationale) — those should already be addressed by T001.
- [ ] T037 Add a Success-Criteria timing assertion sweep to integration tests where missing: SC-001 (≤ 2 s for `ensure-daemon`), SC-003 (≤ 1 s for `status`), SC-004 (≤ 3 s for stale recovery), SC-006 (post-shutdown ensure-daemon succeeds), SC-009 (5 concurrent ensure-daemon → 1 daemon). Use `time.monotonic()` deltas around the subprocess calls; tolerate +50 % slack on CI.
- [ ] T038 [P] Verify the Speckit pointer in `CLAUDE.md` still references `specs/002-host-daemon-socket-api/plan.md` (set by `/speckit-plan`) and that no stale FEAT-001 references remain in the SPECKIT-marker block.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup / Spec Hardening)**: No code dependencies — runs immediately. Updates `spec.md` only.
- **Phase 2 (Foundational)**: Depends on Phase 1 completion. Blocks every user story.
- **Phase 3 (US1)**: Depends on Phase 2.
- **Phase 4 (US2)**: Depends on Phase 2 and on T009 (`methods.py` module exists). Can run in parallel with the *test* tasks of US3/US4 once T010/T011 stubs are in.
- **Phase 5 (US3)**: Depends on Phase 2 and on T010 (lifecycle hook in `daemon.py`); does **not** depend on US2 functionally — recovery code lives in `lifecycle.py`, which only US1's `daemon.py` startup wires up.
- **Phase 6 (US4)**: Depends on Phase 2, on T007 (`server.py`), and on T009 (`methods.py`). Independent of US2/US3 *functionally*; can be implemented in parallel with US3 by a separate developer.
- **Phase 7 (Polish)**: Depends on US1–US4 being complete.

### User Story Dependencies (functional)

- **US1 (P1)** — independently testable: ping is sufficient to demonstrate the daemon comes up.
- **US2 (P2)** — independently testable: `status` works without `stop-daemon` or stale-recovery being implemented.
- **US3 (P3)** — independently testable: stale-recovery integration tests exercise it in isolation by killing -9 and rerunning.
- **US4 (P4)** — independently testable: shutdown integration tests exercise it from a freshly-`ensured` daemon.

### Within Each User Story

- Implementation tasks editing the same module file are sequential (e.g. T018 → T020 both touch `methods.py`/`cli.py` respectively, but each phase's `methods.py` work happens sequentially within that phase).
- Tests for a story (`[P]`-marked) can run in parallel once the implementation file under test exists.
- Per-story integration tests (in `tests/integration/`) can each run in parallel because each owns its own test file.

### Parallel Opportunities

- T002 / T003 / T005 / T006 in Phase 2.
- T012 / T013 / T014 / T015 / T016 / T017 in Phase 3 (after T011 lands the CLI surface).
- T021 / T022 / T023 in Phase 4.
- T026 / T027 in Phase 5.
- T031 / T032 / T033 / T034 in Phase 6.
- T038 in Phase 7.
- Cross-phase: After Phase 2 completes, two developers can split US3 + US4 work in parallel (different files); a third can take US2.

---

## Parallel Example: User Story 1

```bash
# After T011 lands ensure-daemon, all five US1 test tasks fan out:
Task: "Extend tests/unit/test_socket_api_framing.py with envelope validation cases (T012)"
Task: "Add ping-method unit tests in tests/unit/test_socket_api_methods.py (T013)"
Task: "Add AF_UNIX client unit tests in tests/unit/test_socket_api_client.py (T014)"
Task: "Add ensure-daemon integration tests in tests/integration/test_cli_ensure_daemon.py (T015)"
Task: "Add concurrent-startup test in tests/integration/test_daemon_concurrent_start.py (T016)"
Task: "Add no-network-listener test in tests/integration/test_daemon_no_network.py (T017)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Spec hardening (T001).
2. Phase 2: Foundational primitives (T002–T006).
3. Phase 3: US1 implementation + tests (T007–T017).
4. **STOP and VALIDATE**: Run `tests/integration/test_cli_ensure_daemon.py`,
   `tests/integration/test_daemon_concurrent_start.py`,
   `tests/integration/test_daemon_no_network.py`. Confirm SC-001, SC-002, SC-007, SC-008, SC-009 pass.
5. The daemon is a functioning host service answering `ping`; FEAT-003 (container discovery) cannot ship without this slice.

### Incremental Delivery

1. Setup + Foundational → Foundation ready (no user-visible value yet).
2. **+ US1** → MVP shippable: container-side scripts can detect the daemon over the socket.
3. **+ US2** → Operators can script health checks (`agenttower status`, `--json` for monitoring).
4. **+ US3** → Daemon survives crash-and-rerun without manual cleanup; safe to wire into shell hooks.
5. **+ US4** → Tests and dev-iteration scripts can deterministically tear the daemon down.
6. **+ Polish** → Quickstart-validated, security-checklist-closed release.

### Parallel Team Strategy

After Phase 2 completes:

- Developer A → US1 (T007–T017) — owns `server.py`, `client.py`, `methods.py:ping`, `cli.py:ensure-daemon`, `daemon.py:run`.
- Developer B → US3 (T024–T027) — owns the recovery additions to `lifecycle.py` and the recovery integration test file. Coordinates with A on the `daemon.py:run` recovery hook (T025).
- Developer C → US4 (T028–T034) — owns the shutdown additions to `server.py` and `methods.py`, plus `cli.py:stop-daemon` and the signal/lifecycle integration tests. Coordinates with A on `server.py` (T007 → T029).
- US2 (T018–T023) is the natural integration-day work for whoever finishes their P1/P3/P4 slice first.

---

## Notes

- `[P]` tasks = different files, no dependencies on incomplete tasks.
- Every task touches an explicit file path under `src/agenttower/` or `tests/`; vague tasks have been removed.
- All tests are pytest-shaped, use `tmp_path` + `monkeypatch` for environment isolation (matches FEAT-001 conventions), and never invoke Docker, tmux, or open a network socket.
- Verify each acceptance scenario in `spec.md` against its corresponding integration test before checking off a story's checkpoint.
- Stop at any checkpoint to validate the story end-to-end before continuing.
- Avoid: cross-story dependencies that break independent testability; same-file conflicts on parallel tasks; bypassing T001 by deferring spec hardening to Phase 7.
