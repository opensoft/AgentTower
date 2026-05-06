# Tasks: Container tmux Pane Discovery (FEAT-004)

**Input**: Design documents from `/specs/004-container-tmux-pane-discovery/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md, contracts/socket-api.md, quickstart.md, checklists/security.md

**Tests**: REQUIRED. The spec pins unit coverage for socket enumeration, `tmux list-panes` row parsing, per-pane sanitization/truncation, per-(container, socket) reconciliation, and socket method response shapes (SC-008), and integration coverage for every `scan --panes` / `list-panes` path including degraded states and the no-real-Docker/tmux invariant (SC-009 / FR-034 / R-017). Test tasks are written before the implementation they cover and MUST FAIL before that implementation runs.

**Organization**: Tasks are grouped by user story (P1 → P3) so each can be implemented and validated independently against the acceptance scenarios in spec.md.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Different files, no dependencies on incomplete tasks → can run in parallel.
- **[Story]**: Maps to spec.md user stories (`[US1]`, `[US2]`, `[US3]`).
- File paths are relative to the repository root (FEAT-004 worktree).

## Path Conventions

Single-project Python layout. Source under `src/agenttower/`, tests under `tests/unit/` and `tests/integration/`. Paths shown match plan.md §Project Structure exactly.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the worktree is correct and pin the FEAT-004 scope. No new tooling, no new dependencies (stdlib only per plan §Primary Dependencies).

- [X] T001 Verify worktree state: `pwd` is `004-container-tmux-pane-discovery`, branch is `004-container-tmux-pane-discovery`, FEAT-003 artifacts exist (`src/agenttower/docker/`, `src/agenttower/discovery/service.py`, `src/agenttower/state/containers.py`, `tests/integration/test_cli_scan_containers.py`); abort tasks if any are missing.
- [X] T002 [P] Confirm `pyproject.toml` `requires-python>=3.11` and the `[test]` extra still pins `pytest>=7`; do not add new runtime dependencies.

**Checkpoint**: Worktree validated; FEAT-004 may extend the existing layout.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the cross-cutting modules every user story needs. ⚠️ No user-story tasks may start until this phase is complete.

### 2.1 Error code surface

- [X] T003 Extend `src/agenttower/socket_api/errors.py` to add the eight FEAT-004 closed-set codes (`tmux_unavailable`, `tmux_no_server`, `socket_dir_missing`, `socket_unreadable`, `docker_exec_failed`, `docker_exec_timeout`, `output_malformed`, `bench_user_unresolved`); preserve every existing FEAT-002 / FEAT-003 code (FR-019, FR-030, R-011).

### 2.2 Schema migration v2 → v3

- [X] T004 Extend `src/agenttower/state/schema.py` to bump `CURRENT_SCHEMA_VERSION` from `2` to `3` and add `_apply_migration_v3()` that creates the `panes` and `pane_scans` tables plus the `panes_active_order`, `panes_container_socket`, and `pane_scans_started` indexes per data-model §2.1 / §2.2; migration runs in one transaction with `IF NOT EXISTS` guards; refuse startup on schema versions newer than 3 (FR-029, R-016).

### 2.3 Pane state helpers

- [X] T005 [P] Create `src/agenttower/state/panes.py` with the typed dataclasses (`PaneRow`, `PaneUpsert`, `PaneCompositeKey`, `PriorPaneRow`, `ContainerMeta`, `PaneScanRow`, `PerScopeError`, `PaneTruncationNote`) and the read/write helpers `select_all_panes`, `select_panes_for_listing(active_only, container_filter)`, `apply_pane_reconcile_writeset(...)`, `insert_pane_scan(...)` — all SQLite-only, no Docker / tmux imports (data-model §2 and §3, FR-024).
- [X] T006 Extend `src/agenttower/state/containers.py` to add a read-only `select_active_containers_with_user()` that returns `(container_id, name, config_user)` tuples and an `select_container_ids_active_zero_with_panes()` that returns the FR-009 cascade set (SQL only, no behavior change to FEAT-003 writes; FR-002, FR-009, FR-030).

### 2.4 Sanitization & truncation

- [X] T007 [P] Create `src/agenttower/tmux/parsers.py` with `sanitize_text(value, max_length) -> (str, bool)` (NUL + C0 stripping per R-009, tab/newline → space, UTF-8-aware truncation), plus the closed parser entry points `parse_id_u(stdout)`, `parse_socket_listing(stdout)` (skips subdirs, names with `/`, blank lines per R-007), and `parse_list_panes(stdout) -> tuple[list[ParsedPane], list[MalformedRow]]` (10 tab-separated fields per R-002; rows with the wrong field count produce `MalformedRow` not exception).

### 2.5 TmuxAdapter Protocol + dataclasses

- [X] T008 [P] Create `src/agenttower/tmux/adapter.py` with the `TmuxAdapter` Protocol (`resolve_uid`, `list_socket_dir`, `list_panes`), the result dataclasses (`ParsedPane`, `SocketListing`, `OkSocketScan`, `FailedSocketScan`, `SocketScanOutcome` union, `TmuxError(Exception)`), and a `__init__.py` that re-exports them (data-model §3, R-001).

### 2.6 SubprocessTmuxAdapter (production)

- [X] T009 [P] Create `src/agenttower/tmux/subprocess_adapter.py` implementing `SubprocessTmuxAdapter` with: `shutil.which("docker")` resolution at scan time (FR-022), typed argv with `shell=False, text=True, check=False, timeout=5.0` for the three closed-set payloads (`id -u`, `ls -1 -- /tmp/tmux-<uid>`, `tmux -S <socket> list-panes -a -F <format>` per R-001 / R-002 / R-007), translation of `subprocess.TimeoutExpired` into `TmuxError(code="docker_exec_timeout", ...)` with terminate-and-wait semantics (FR-018, R-003), and mapping of non-zero exits / unparseable stdout / permission-denied stderr into the closed-set codes from T003.

### 2.7 FakeTmuxAdapter (test-only)

- [X] T010 [P] Create `src/agenttower/tmux/fakes.py` implementing `FakeTmuxAdapter.from_fixture_path(path)` per R-012; fixture supports `containers[id].uid`, `id_u_failure`, `socket_dir_missing`, `sockets[name]` either as a parsed-pane list or `{"failure": {...}}`; failures raise `TmuxError` with the closed-set codes; the adapter never spawns a subprocess.

### 2.8 Reconciliation (pure function)

- [X] T011 [P] Create `src/agenttower/discovery/pane_reconcile.py` exposing `reconcile(*, prior_panes, socket_results, tmux_unavailable_containers, inactive_cascade_containers, container_metadata, now_iso) -> PaneReconcileWriteSet` per data-model §5; runs every `ParsedPane` field through `sanitize_text` and emits `PaneTruncationNote` entries (R-009); produces disjoint `upserts` / `touch_only` / `inactivate` sets and the seven aggregate counters; pure SQL-free.

### 2.9 PaneDiscoveryService (orchestration)

- [X] T012 Create `src/agenttower/discovery/pane_service.py` with `PaneDiscoveryService(tmux_adapter, db, events_writer, lifecycle_log, clock)` exposing `scan() -> PaneScanResult`; owns its own `threading.Lock` independent of the FEAT-003 mutex (FR-017, R-004); enforces the FR-025 write order (acquire mutex → emit `pane_scan_started` → load active container set + cascade set → resolve bench user/uid → enumerate sockets → per-socket scan → reconcile → single `BEGIN IMMEDIATE` insert/upserts/touch/inactivate commit → conditional JSONL `pane_scan_degraded` append → emit `pane_scan_completed` → return); rolls back on SQLite failure, suppresses JSONL on rollback, releases mutex, returns `internal_error` (FR-024, R-015); never calls Docker for containers in the inactive cascade set (FR-009).

### 2.10 Daemon wiring + test seam

- [X] T013 Extend `src/agenttower/daemon.py` to instantiate the chosen `TmuxAdapter` at startup (`AGENTTOWER_TEST_TMUX_FAKE` env var → `FakeTmuxAdapter` per R-012, otherwise `SubprocessTmuxAdapter`), build a `PaneDiscoveryService`, and attach it to `DaemonContext` alongside the FEAT-003 container service; close on shutdown without disturbing the existing FEAT-003 wiring.

### 2.11 Socket method registration

- [X] T014 Extend `src/agenttower/socket_api/methods.py` to register `scan_panes` and `list_panes` handlers; both delegate to `DaemonContext.pane_service` / the new `state.panes` reads; `list_panes` MUST NOT acquire either scan mutex and MUST NOT call Docker or tmux (FR-016); `scan_panes` envelope shapes match contracts/socket-api.md §3.2 / §3.3 / §3.4 verbatim.

**Checkpoint**: Foundation ready — schema migrates v2→v3, adapters and reconciler compile and import, daemon wires the new service, and the two socket methods are dispatch-table-visible. Unit-test tasks below validate each helper before the user-story phases consume them.

---

## Phase 3: User Story 1 — Discover tmux Panes Inside Active Bench Containers (Priority: P1) 🎯 MVP

**Goal**: Running `agenttower scan --panes` followed by `agenttower list-panes` surfaces every tmux pane from every active bench container with all FR-006 fields populated and per-scan reconciliation working (spec §User Story 1, SC-001, SC-002).

**Independent Test**: With a `FakeTmuxAdapter` reporting one active container that hosts a default tmux server with two sessions and three panes, `agenttower scan --panes` persists exactly three active pane records and `agenttower list-panes` exposes every required FR-006 field. Removing one parsed pane from a subsequent scan flips its `active` flag to `0` without deleting the row.

### Tests for User Story 1 (write FIRST; MUST FAIL before US1 implementation)

- [X] T015 [P] [US1] Create `tests/unit/test_tmux_parsers.py` covering `parse_id_u` (digits / non-numeric / empty / extra lines), `parse_socket_listing` (skips subdirs, names with `/`, blank lines, preserves `default`), and `parse_list_panes` (10-field happy path, fewer/extra fields → `MalformedRow`, embedded tabs in title sanitized) (R-002, R-007, R-009, FR-005).
- [X] T016 [P] [US1] Create `tests/unit/test_pane_field_sanitize.py` covering `sanitize_text`: NUL drop, C0 strip, tab/newline → space, UTF-8-aware truncation at 2048 / 4096, returns `(value, truncated)`; assert truncation is recorded as a `PaneTruncationNote`, never rejects rows (FR-023, R-009).
- [X] T017 [P] [US1] Create `tests/unit/test_state_panes.py` covering: v2→v3 migration applied to a v2 fixture creates `panes` + `pane_scans` with the exact column set from data-model §2; idempotent re-open against v3; refusal on v4; composite-key upsert preserves `first_seen_at`; `select_panes_for_listing` returns deterministic FR-016 order; `apply_pane_reconcile_writeset` performs upsert/touch/inactivate atomically and rolls back on injected failure (FR-024, FR-029, FR-016).
- [X] T018 [P] [US1] Create `tests/unit/test_pane_reconcile.py` covering the reconcile pure function: transition (a) inactive flip, transition (b) refresh, sanitize integration, `panes_seen` / `panes_newly_active` counters; this story exercises only single-container, single-socket scenarios (multi-socket is US2, degraded is US3) (FR-007, FR-008).
- [X] T019 [P] [US1] Create `tests/unit/test_socket_api_pane_methods.py` covering in-process dispatch of `scan_panes` and `list_panes`: bad envelope → `bad_request`; unknown params → ignored; `list_panes` with no panes → `panes:[]`; `list_panes` MUST NOT acquire the pane-scan mutex (assert via a held lock + timing); `scan_panes` healthy envelope matches contracts/socket-api.md §3.2 (FR-013, FR-016).
- [X] T020 [P] [US1] Create `tests/integration/test_cli_scan_panes.py`: with `AGENTTOWER_TEST_DOCKER_FAKE` + `AGENTTOWER_TEST_TMUX_FAKE` set, spawn the daemon, run `agenttower scan --panes` and `agenttower scan --panes --json`, assert the 10-line `key=value` output (uses short `panes_reconciled_inactive=`) AND the canonical JSON envelope (uses long `panes_reconciled_to_inactive`), assert the SQLite `pane_scans.panes_reconciled_inactive` column matches the JSON `result.panes_reconciled_to_inactive` value byte-for-byte (alias map per data-model §6 note 5), and verify exactly one `pane_scans` row + the expected `panes` rows (SC-001, contracts/cli.md §C-CLI-401).
- [X] T021 [P] [US1] Create `tests/integration/test_cli_list_panes.py`: assert the default TSV header + ordering per FR-016, `--json` shape with every FR-006 field, `--active-only` filter, `--container <name>` exact match, empty filter result exit `0`, distinct `pane_active` vs `active` fields (SC-005, contracts/cli.md §C-CLI-402, data-model §6 note 1).

### Implementation for User Story 1

- [X] T022 [US1] Extend `src/agenttower/cli.py` to add the `--panes` flag handler on the existing `scan` subparser and the new `list-panes` subparser; both accept `--json`; `list-panes` accepts `--active-only` and `--container <id-or-name>`; bare `agenttower scan` updates its error message to advertise `--panes` (FR-014, FR-015, FR-030).
- [X] T023 [US1] Implement the default `agenttower scan --panes` rendering (11 fixed `key=value` lines plus optional `error:` / `code:` / `detail:` / truncation summary lines) and the `--json` rendering (canonical envelope echoed verbatim plus `ok`); honor exit codes `0` / `3` / `5` (contracts/cli.md §C-CLI-401).
- [X] T024 [US1] Implement the default `agenttower list-panes` TSV rendering (13 columns, FR-016 order, post-sanitization fields) and the `--json` rendering (full FR-006 field set per pane, `result.filter` / `result.container_filter` / `result.panes`); empty filter result exit `0` (contracts/cli.md §C-CLI-402).
- [X] T025 [US1] Implement the `scan_panes` daemon path: read active containers via `select_active_containers_with_user`, derive bench user per container (FR-020 / R-005), drive `PaneDiscoveryService.scan()`, marshal `PaneScanResult` into the contracts/socket-api.md §3.2 / §3.3 envelope; the JSON serializer MUST rename the dataclass field `panes_reconciled_inactive` to the wire field `panes_reconciled_to_inactive` per data-model §6 note 5 (this is the only renamed field; the SQLite column, the dataclass field, and the CLI default `key=value` line keep the short name); healthy scan → `events.jsonl` UNCHANGED (FR-025).
- [X] T026 [US1] Implement the `list_panes` daemon path: read-only SQLite SELECT with `params.active_only` + `params.container` (64-char hex → id match, otherwise `containers.name` exact match per data-model §6 note 4); deterministic order per FR-016; never touches scan mutex / Docker / tmux (FR-016).
- [X] T027 [US1] Run T020 + T021 against the live daemon and verify SC-001, SC-002, and SC-005 are met before moving to US2.

**Checkpoint**: User Story 1 fully functional. A single bench container with one tmux socket scans cleanly, panes persist with full FR-006 field set, reconcile-to-inactive works, and CLI exit codes match the contract.

---

## Phase 4: User Story 2 — Discover Multiple tmux Sockets Per Container (Priority: P2)

**Goal**: Bench containers running multiple tmux servers (default + `tmux -L work` etc.) surface panes from every socket through `agenttower list-panes`, each row carrying its originating socket path; per-(container, socket) reconciliation isolates a single failing socket from its healthy siblings (spec §User Story 2, FR-003 / FR-004 / FR-011).

**Independent Test**: With a fixture reporting two socket files under `/tmp/tmux-<uid>/` (`default` and `work`, fixture uid bound at test setup) and distinct pane sets per socket, `agenttower scan --panes` persists the union of their panes; killing one socket between scans flips only its panes to inactive, leaving sibling-socket panes unchanged.

### Tests for User Story 2 (write FIRST; MUST FAIL before US2 implementation)

- [X] T028 [P] [US2] Extend `tests/unit/test_pane_reconcile.py` (or add `tests/unit/test_pane_reconcile_multi_socket.py`) with: two `(c, s)` tuples on the same container both `OkSocketScan`, one `OkSocketScan` + one `FailedSocketScan` on the same container (FR-011 sibling preservation → `touch_only`), pane id `%0` reused across two distinct sockets in the composite key (FR-007).
- [X] T029 [P] [US2] Create `tests/integration/test_cli_scan_panes_multi_socket.py`: fixture has `default` + `work` sockets with disjoint pane sets; assert `sockets_scanned=2`, `panes_seen` equals the union, both `tmux_socket_path` values appear in `list-panes --json`; second scan with `work` removed inactivates only its panes; second scan where `work` returns `FailedSocketScan(tmux_no_server)` keeps prior `work` panes unchanged with `last_scanned_at` advanced (FR-011).

### Implementation for User Story 2

- [X] T030 [US2] Verify `SubprocessTmuxAdapter.list_socket_dir` (T009) yields one entry per regular file under `/tmp/tmux-<uid>/` and that `parse_socket_listing` (T007) drops subdirs, dotted names, and entries with `/`; add a fast-path so `default` is always treated as a candidate when present (R-007, FR-004).
- [X] T031 [US2] Confirm `PaneDiscoveryService.scan()` (T012) calls `tmux list-panes` once per discovered socket and feeds the results as a `dict[(container_id, socket_path), SocketScanOutcome]` into `reconcile`; one failing socket MUST NOT abort the per-container loop (FR-005, FR-011).
- [X] T032 [US2] Run T028 + T029 against the live daemon and verify the FR-011 sibling-preservation rule is observable in both `list-panes --json` and `pane_scans.error_details_json`.

**Checkpoint**: User Stories 1 AND 2 work independently. Multi-socket containers persist union pane sets; per-(container, socket) reconciliation preserves sibling sockets across partial failures.

---

## Phase 5: User Story 3 — Handle tmux and `docker exec` Degraded States (Priority: P3)

**Goal**: Pane discovery degrades gracefully when tmux is missing, when `docker exec` fails or times out, when a container goes inactive between FEAT-003 and FEAT-004 scans, and when the daemon itself is unreachable. The daemon never crashes because of one bad container or socket (spec §User Story 3, FR-009 / FR-010 / FR-018 / FR-019 / SC-006).

**Independent Test**: With a fixture injecting `tmux: not found`, `no server running`, `docker exec` non-zero exit, `docker exec` timeout, malformed `tmux list-panes` rows, and a container marked inactive between scans, the scan completes with `degraded` status, persists a `pane_scans` row, surfaces the failures in CLI output, preserves prior pane history per FR-010 / FR-011, and the daemon stays alive.

### Tests for User Story 3 (write FIRST; MUST FAIL before US3 implementation)

- [X] T033 [P] [US3] Extend `tests/unit/test_pane_reconcile.py` with the FR-009 inactive-container cascade (transition (c)), FR-010 tmux-unavailable preservation (transition (d)), and FR-011 sibling preservation (transition (e)); assert `containers_skipped_inactive` and `containers_tmux_unavailable` counters and that no `docker exec` is invoked for cascade containers.
- [X] T034 [P] [US3] Extend `tests/unit/test_tmux_subprocess_adapter.py` with: `subprocess.TimeoutExpired` → `TmuxError(docker_exec_timeout)` with terminate+wait semantics; non-zero exit → `docker_exec_failed`; permission-denied stderr → `socket_unreadable` only on the socket-listing call; closed argv shape assertions (no `shell=True`, no shell metacharacters interpolated); kill-itself-fails escalation → secondary 1 s grace period → `TmuxError(internal_error)`, daemon stays alive, lifecycle log records closed-set unrecovered-child message (no raw stderr); FR-020 fallback chain (`config_user` → `$USER` → `getpwuid`) and `bench_user_unresolved` when all three are empty; `:uid` form on `config_user` splits on first `:` and uses left-hand component (FR-018, FR-019, FR-020, FR-021, FR-033, R-003, R-005).
- [X] T035 [P] [US3] Create `tests/integration/test_cli_scan_panes_tmux_unavailable.py`: `tmux: command not found` and `no server running` paths each produce `degraded` status, `containers_tmux_unavailable >= 1`, exit `5`, prior pane rows preserved with `active` UNCHANGED and `last_scanned_at` advanced (FR-010, SC-004).
- [X] T036 [P] [US3] Create `tests/integration/test_cli_scan_panes_inactive_cascade.py`: container marked inactive in `containers` between scans → all of its prior active panes flip to `active=0` with `last_scanned_at` updated, `containers_skipped_inactive=1`, no `docker exec` issued for that container (assert via FakeTmuxAdapter call log), exit `0` (FR-009, SC-003).
- [X] T037 [P] [US3] Create `tests/integration/test_cli_scan_panes_timeout.py`: fake injects `subprocess.TimeoutExpired` on one container's `id -u`; `error_code=docker_exec_timeout` in `error_details`, remaining containers continue, daemon stays alive (`agenttower status` succeeds), no orphaned children (assert via fake's terminate/wait counter), per-call budget ≤ 5 s (FR-018, SC-006).
- [X] T038 [P] [US3] Create `tests/integration/test_cli_scan_panes_concurrent.py`: two parallel `scan_panes` calls serialize behind the pane-scan mutex (non-overlapping `started_at`/`completed_at`); a parallel `scan_containers` + `scan_panes` MAY overlap because their mutexes are independent (FR-017, R-004).
- [X] T039 [P] [US3] Add a daemon-unreachable case to `tests/integration/test_cli_scan_panes.py` (or create `test_cli_scan_panes_no_daemon.py`): with the daemon stopped, both `scan --panes` and `list-panes` exit `2` with the FEAT-002 `daemon-unavailable` message (SC-004 daemon-unreachable variant).

### Implementation for User Story 3

- [X] T040 [US3] Extend `PaneDiscoveryService` (T012) so the FR-009 cascade is applied without invoking `docker exec` for inactive containers and the FR-010 / FR-011 preservation paths route through `touch_only` rather than `inactivate` (data-model §4.1 transitions (c)/(d)/(e)).
- [X] T041 [US3] Wire the lifecycle log emitter to write `pane_scan_started` (after mutex acquired, before any `docker exec`) and `pane_scan_completed` (after SQLite commit + JSONL append attempt, before socket response) per R-014; lifecycle rows carry only scan id, status, aggregate counts, and the closed error code — no raw stderr / output / env / pane fields (FR-026).
- [X] T042 [US3] Implement the `docker_unavailable` whole-scan-failure path: when `shutil.which("docker")` returns nothing or the path is not executable, the daemon still allocates a `scan_id`, writes a `pane_scans` row with `status="degraded"`, appends one `pane_scan_degraded` JSONL event, and returns the `ok:false` envelope per contracts/socket-api.md §3.4 (FR-022, R-011).
- [X] T043 [US3] Implement post-commit failure handling: SQLite commit succeeds but JSONL append or `pane_scan_completed` emit fails → return `internal_error`, daemon stays alive, the `pane_scans` row is NOT rolled back, the pane-scan mutex is released (FR-025 post-commit clause, R-015 mirrors FEAT-003 R-018). Also implement the symmetric pre-commit lifecycle log failure: `pane_scan_started` emit fails after mutex acquisition → release mutex, no `docker exec` issued, no `pane_scans` row, return `internal_error` (FR-025 pre-commit clause).
- [X] T044 [US3] Run T033–T039 and verify SC-003, SC-004, SC-006, and the FR-019 closed-error-code surface are observable end-to-end.

**Checkpoint**: All three user stories are independently functional. Healthy, partial-degraded, and whole-scan-failure paths each persist the right `pane_scans` row, `events.jsonl` entry (or none), and lifecycle log lines.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Cross-cutting hardening, the no-real-Docker/tmux invariant, the no-network-listener invariant, and the security-checklist sign-off.

- [X] T045 [P] Create `tests/integration/test_cli_scan_panes_no_real_docker.py` per R-017: assert both `AGENTTOWER_TEST_DOCKER_FAKE` and `AGENTTOWER_TEST_TMUX_FAKE` are set in `os.environ` at collection time; monkeypatch `shutil.which` and `subprocess.run` and assert neither is called with `"docker"` or `"tmux"` as `argv[0]` for the duration of the session (SC-009, FR-034).
- [X] T046 [P] Create `tests/integration/test_feat004_no_network.py` asserting no AF_INET / AF_INET6 socket is opened by the daemon during any FEAT-004 dispatch path (FR-031).
- [X] T047 [P] Add a `tests/unit/test_state_panes_migration_idempotence.py` (or extend T017) that opens a fresh DB, applies v1→v3 in one daemon start, restarts, and asserts `_apply_migration_v3` runs zero additional statements (R-016).
- [X] T048 Walk `specs/004-container-tmux-pane-discovery/quickstart.md` end-to-end against the live daemon with the fake adapters and confirm every command in §1–§9 produces the documented output and exit codes; capture any drift back into the spec rather than the code.
- [X] T049 Walk `specs/004-container-tmux-pane-discovery/checklists/security.md` against the final spec / plan / research / data-model / contracts artifacts; encode any remaining gaps as spec amendments before merge — do not paper over them in code.
- [X] T050 [P] Confirm the FEAT-001 / FEAT-002 / FEAT-003 test suites still pass on this branch (SC-007); add no new dependencies (plan §Primary Dependencies).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No upstream dependencies.
- **Foundational (Phase 2)**: Depends on Setup. ⚠️ Blocks every user-story phase.
- **User Story 1 (Phase 3)**: Depends on Foundational. MVP.
- **User Story 2 (Phase 4)**: Depends on Foundational; integrates with US1 via the shared adapter / reconciler but is independently testable (multi-socket fixtures).
- **User Story 3 (Phase 5)**: Depends on Foundational; covers degraded paths that overlay every prior phase but is independently testable (degraded fixtures).
- **Polish (Phase 6)**: Depends on every user-story phase the team intends to ship.

### Within Each User Story

- Tests are written BEFORE the implementation tasks they cover and MUST fail prior to that implementation running.
- Models / dataclasses (Phase 2) precede services; services (Phase 2) precede CLI / socket method handlers; CLI / handlers precede the integration tests that drive them end-to-end.

### Parallel Opportunities

- Phase 1: T001 → T002 [P].
- Phase 2: T003 → T004; T005 [P] / T007 [P] / T008 [P] / T009 [P] / T010 [P] / T011 [P] all parallel after T003+T004 land; T006 sequenced before T012 (state read used by service); T012 sequenced after T005–T011; T013 sequenced after T012; T014 sequenced after T013.
- Phase 3 tests T015–T021 are all [P] (different files); implementation T022–T026 sequenced (T022 → T023 → T024 → T025 → T026); T027 closes the phase.
- Phase 4 tests T028 [P], T029 [P]; implementation T030 → T031 → T032.
- Phase 5 tests T033–T039 are all [P]; implementation T040 → T041 → T042 → T043 → T044.
- Phase 6 tasks T045–T047 [P] and T050 [P] run in parallel; T048 and T049 are sequential walkthroughs.

---

## Parallel Example: User Story 1 tests

```bash
# Spawn all US1 test files together (different paths, no inter-task deps):
Task: "Create tests/unit/test_tmux_parsers.py"             # T015
Task: "Create tests/unit/test_pane_field_sanitize.py"      # T016
Task: "Create tests/unit/test_state_panes.py"              # T017
Task: "Create tests/unit/test_pane_reconcile.py"           # T018
Task: "Create tests/unit/test_socket_api_pane_methods.py"  # T019
Task: "Create tests/integration/test_cli_scan_panes.py"    # T020
Task: "Create tests/integration/test_cli_list_panes.py"    # T021
```

```bash
# After T012 + T013 land, US1 implementation tasks run sequentially because
# they all extend src/agenttower/cli.py / daemon.py / socket_api/methods.py:
Task: "Extend cli.py with --panes flag and list-panes subparser"  # T022
Task: "Implement scan --panes default + --json rendering"         # T023
Task: "Implement list-panes default TSV + --json rendering"       # T024
Task: "Implement scan_panes daemon handler"                       # T025
Task: "Implement list_panes daemon handler"                       # T026
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1: Setup (T001 + T002 [P]).
2. Phase 2: Foundational (T003 → T004; then T005 [P] / T007 [P] / T008 [P] / T009 [P] / T010 [P] / T011 [P]; then T006 → T012 → T013 → T014).
3. Phase 3: User Story 1 (US1 tests [P], then T022 → T026 sequentially, then T027).
4. **STOP and VALIDATE**: SC-001 / SC-002 / SC-005 against the FakeTmuxAdapter; quickstart.md §1 walks cleanly; security checklist §1–§4 review.
5. Demo / merge if MVP scope is sufficient.

### Incremental Delivery

1. Setup + Foundational → adapters + service + dispatch wired.
2. + US1 → first MVP slice ships single-container, single-socket discovery (the most common bench setup).
3. + US2 → multi-socket workflows ship; sibling-preservation makes pane history robust to one failing tmux server.
4. + US3 → degraded paths ship; tmux-unavailable, timeout, inactive cascade, and daemon-unreachable are all covered with no daemon crash.
5. + Polish → no-real-Docker/tmux harness assertion, no AF_INET assertion, migration idempotence, quickstart + checklist sign-off.

### Parallel Team Strategy

After Phase 2 closes, three developers can ship independently against the foundation:

- Developer A: Phase 3 (US1 / MVP).
- Developer B: Phase 4 (US2) — depends on US1's CLI tasks landing for the integration test harness shape; the unit reconcile task (T028) can start sooner.
- Developer C: Phase 5 (US3) — same shape; T033–T034 unit tests start as soon as the foundation lands.

All three converge in Phase 6 for the cross-cutting hardening + walkthroughs.

---

## Notes

- [P] = different files, no upstream dependencies on incomplete tasks; never use [P] on tasks that extend the same file (e.g., multiple `cli.py` extensions).
- Every user-story task carries the `[USn]` label so traceability back to spec.md acceptance scenarios stays explicit.
- Tests are written first within each story phase and MUST fail before the implementation tasks they cover begin (template invariant).
- Commit after each task or each logical group; keep `pyproject.toml` and dependency footprint stable (plan §Primary Dependencies — stdlib only).
- Stop at every checkpoint (end of Phase 2, end of US1, end of US2, end of US3) to validate independently before proceeding.
- Avoid: cross-story dependencies that break independence; same-file [P] tasks; unbounded raw stderr/tmux output anywhere outside the bounded `error_message` field; any code path that spawns `docker` or `tmux` from the CLI process.
