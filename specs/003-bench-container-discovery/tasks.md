---

description: "Task list for FEAT-003 — Bench Container Discovery"
---

# Tasks: Bench Container Discovery

**Input**: Design documents from `/specs/003-bench-container-discovery/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md, contracts/socket-api.md

**Tests**: Test tasks are INCLUDED because spec.md SC-006 (unit coverage) and SC-007 (integration coverage) make tests a required deliverable for this feature, and FR-020 forbids exercising real Docker — every test path must be present and green.

**Organization**: Tasks are grouped by user story (US1 = P1, US2 = P2, US3 = P3) so each story is independently implementable, testable, and shippable as an incremental MVP slice.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on still-open tasks)
- **[Story]**: User story this task belongs to (`US1`, `US2`, `US3`); Setup, Foundational, and Polish phases have no story label

## Path Conventions

Single-project Python layout per FEAT-001/FEAT-002. All paths are relative to repo root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the empty package skeletons and confirm the FEAT-003 worktree is ready to extend FEAT-002 source.

- [X] T001 Create `src/agenttower/docker/__init__.py` exporting nothing yet (placeholder package marker for the Docker adapter and parsers).
- [X] T002 Create `src/agenttower/discovery/__init__.py` exporting nothing yet (placeholder package marker for the matching predicate, reconciler, and DiscoveryService).
- [X] T003 [P] Add a `tests/conftest.py` fixture that asserts `AGENTTOWER_TEST_DOCKER_FAKE` is set OR monkeypatches `subprocess.run` and `shutil.which` to refuse `"docker"` argv during the test session (FR-020, SC-007 hard guard).

---

## Phase 2: Foundational (Blocking Prerequisites for All Stories)

**Purpose**: Land the schema migration runner, the v2 tables, the Docker adapter Protocol, the test fake, the parsers, and the new error codes. Every user story below depends on this phase being complete.

⚠️ **CRITICAL**: No user story tasks may begin until this phase is complete.

- [X] T004 Extend `src/agenttower/state/schema.py`: introduce a `_MIGRATIONS` dispatch map keyed by target schema version, a `_apply_migration_v2()` helper that issues the two `CREATE TABLE` and two `CREATE INDEX` statements from data-model.md §2.1 / §2.2, and an `_apply_pending_migrations()` runner that reads the current `schema_version` row, applies pending migrations under one `BEGIN IMMEDIATE` / `COMMIT` transaction, and updates `schema_version` to `CURRENT_SCHEMA_VERSION = 2` at the end. Re-opening on v2 must be a no-op (idempotent).
- [X] T005 Extend `src/agenttower/state/schema.py`: bump `CURRENT_SCHEMA_VERSION` from `1` to `2` and call `_apply_pending_migrations()` from `open_registry()` AFTER the `schema_version` row is read but BEFORE the connection is returned. Refuse to start (raise) when the on-disk version is greater than `CURRENT_SCHEMA_VERSION` (data-model.md §7).
- [X] T006 [P] Create `src/agenttower/state/containers.py`: typed dataclasses (`ContainerRow`, `ContainerScanRow`) and read/write helpers (`upsert_container`, `mark_inactive`, `touch_last_scanned`, `insert_container_scan`, `select_containers`, `select_active_container_ids`, `select_known_container_ids`). All writes accept an open `sqlite3.Connection`; the helpers do NOT begin or commit transactions on their own (the caller owns the transaction boundary per data-model.md §5).
- [X] T007 [P] Create `src/agenttower/docker/adapter.py`: the `DockerAdapter` `Protocol` (methods `list_running()` returning `Sequence[ContainerSummary]`, `inspect(ids)` returning `tuple[Mapping[str, InspectResult], Sequence[PerContainerError]]`), plus the frozen dataclasses `ContainerSummary`, `Mount`, `InspectResult`, `DockerError`, `PerContainerError`, and `ScanResult` from data-model.md §3.
- [X] T008 [P] Create `src/agenttower/docker/parsers.py`: pure helpers `parse_docker_ps_lines(text)` (tab-separated, multi-name comma-split, raises `DockerError(code="docker_malformed")` on shape errors) and `parse_docker_inspect_array(blob, requested_ids)` (validates the JSON is a list of objects, strips leading `/` from `Name`, applies the env-key allowlist `("USER", "HOME", "WORKDIR", "TMUX")` per research R-007, returns `dict[id, InspectResult]` plus a list of `PerContainerError` entries for ids whose payloads were malformed).
- [X] T009 [P] Create `src/agenttower/docker/fakes.py`: `FakeDockerAdapter` that loads its scripted state from a JSON path supplied at construction time (`FakeDockerAdapter.from_path(path)`); supports per-call result tags (`{"action": "ok"|"timeout"|"command_not_found"|"permission_denied"|"non_zero_exit"|"malformed"}`); raises a real `DockerError` for the failure tags so the production code path is exercised end-to-end without `subprocess.run`.
- [X] T010 Extend `src/agenttower/docker/__init__.py`: re-export `DockerAdapter`, `ContainerSummary`, `InspectResult`, `Mount`, `DockerError`, `PerContainerError`, `FakeDockerAdapter`. Do NOT re-export `SubprocessDockerAdapter` yet — it ships in US3.
- [X] T011 Extend `src/agenttower/socket_api/errors.py`: add the six new closed-set codes from research R-014 (`CONFIG_INVALID`, `DOCKER_UNAVAILABLE`, `DOCKER_PERMISSION_DENIED`, `DOCKER_TIMEOUT`, `DOCKER_FAILED`, `DOCKER_MALFORMED`) as module-level string constants. Existing FEAT-002 codes remain bytewise unchanged (FR-022).
- [X] T012 Extend `src/agenttower/socket_api/methods.py`: add `discovery_service: DiscoveryService | None = None` to `DaemonContext` (forward-ref typed; the import lives behind `if TYPE_CHECKING:` to avoid a circular import). Existing dispatch entries remain unchanged.
- [X] T013 [P] Add `tests/unit/test_state_containers.py`: schema v1→v2 migration idempotence on re-open, refuse-future-version case, migration-failure rollback (monkeypatch `_apply_migration_v2` to raise after the first DDL statement, assert the v1 schema remains unchanged and `open_registry()` raises), and JSON column round-trip for `labels_json`, `mounts_json`, `inspect_json` via the helpers in `state/containers.py` (no scan logic yet).
- [X] T014 [P] Add `tests/unit/test_docker_parsers.py`: `docker ps` row parsing (tab + comma split, leading-slash strip), `docker inspect` array parsing including missing `Labels` → `{}`, missing `Mounts` → `[]`, oversized strings, non-list top-level → `docker_malformed`, env-key allowlist filtering.

**Checkpoint**: At the end of Phase 2, `pytest tests/unit/test_state_containers.py tests/unit/test_docker_parsers.py` passes; the codebase still type-checks; FEAT-002's existing tests remain green; the daemon still starts under v1 → v2 migration.

---

## Phase 3: User Story 1 — Scan Running Bench Containers (Priority: P1)

**Story goal**: A developer runs `agenttower scan --containers` against a fake Docker adapter that returns a mix of running bench and non-bench containers, and `agenttower list-containers` shows only the matching ones (id, name, image, status, labels, mounts, active state, last_scanned timestamp). Spec US1 acceptance scenarios 1–3 all pass.

**Independent test**: With `AGENTTOWER_TEST_DOCKER_FAKE` pointing at a fixture containing `py-bench` (matching) and `redis` (non-matching), `agenttower scan --containers` reports `matched=1 ignored=1`, then `agenttower list-containers` shows the persisted `py-bench` row with `active=1`.

⚠️ Do not begin until Phase 2 is complete.

### Implementation for User Story 1

- [X] T015 [US1] Create `src/agenttower/discovery/matching.py`: `MatchingRule` frozen dataclass and `default_rule()` factory that returns `MatchingRule(name_contains=("bench",))`. The `matches(name: str) -> bool` method performs case-insensitive substring matching after `.casefold()` on both sides. Loading from config is deferred to US2; this module only exposes the predicate and the default constant.
- [X] T016 [P] [US1] Create `src/agenttower/discovery/reconcile.py`: pure `reconcile(*, prior_active_ids, prior_known_ids, successful_inspects, failed_inspect_ids, now_iso) -> ReconcileWriteSet` per data-model.md §5. Returns the four-cohort write set (`upserts`, `touch_only`, `inactivate`, plus the two derived counters). No SQL; no I/O.
- [X] T017 [US1] Create `src/agenttower/discovery/service.py`: `DiscoveryService` constructor takes `(connection, adapter, rule)`. Implement the happy-path `scan() -> ScanResult` that (1) generates a UUID4 `scan_id`, (2) calls `adapter.list_running()`, (3) applies the matching rule (counting `ignored`), (4) calls `adapter.inspect(matching_ids)`, (5) calls `reconcile(...)`, (6) opens a single SQLite transaction, applies the write set with the helpers from T006, inserts the `container_scans` row with `status='ok'`, commits, and (7) returns the populated `ScanResult`. The mutex, JSONL emit, lifecycle log, and degraded paths land later in this same FEAT-003 task list under US3; leave clear internal hook points where they will plug in.
- [X] T018 [US1] Create `src/agenttower/discovery/__init__.py` re-exports for `DiscoveryService`, `MatchingRule`, `default_rule`, `reconcile`, `ReconcileWriteSet`. Replace the placeholder package marker from T002.
- [X] T019 [US1] Add `_scan_containers` method handler to `src/agenttower/socket_api/methods.py`: validates `params` is `{}` or absent, calls `ctx.discovery_service.scan()`, serializes the resulting `ScanResult` into the JSON shape from contracts/socket-api.md §3.2, returns `errors.make_ok(result)`. On any uncaught exception, returns `errors.make_error(INTERNAL_ERROR, ...)` so the daemon stays alive (FR-018, FR-022).
- [X] T020 [US1] Add `_list_containers` method handler to `src/agenttower/socket_api/methods.py`: validates `params` is `{}` or `{"active_only": <bool>}`, calls `select_containers(connection, active_only=<bool>)`, decodes `labels_json`/`mounts_json` via `json.loads`, returns the list shape from contracts/socket-api.md §4.2 with `result.filter` set to `"active_only"` or `"all"`. Read-only; does NOT acquire any mutex.
- [X] T021 [US1] Register the two new handlers in the `DISPATCH` dict in `src/agenttower/socket_api/methods.py`. The dict literal MUST keep the FEAT-002 entries first (insertion order) so the dispatch behavior is observably extended, not rewritten (FR-022).
- [X] T022 [US1] Extend `src/agenttower/daemon.py`: at startup, read `AGENTTOWER_TEST_DOCKER_FAKE` from `os.environ`. When set, instantiate `FakeDockerAdapter.from_path(...)`. When unset, leave the slot at `None` for now (US3 will plug in `SubprocessDockerAdapter`). Build a `DiscoveryService(conn, adapter, default_rule())` only when an adapter is available; otherwise the two new methods return `INTERNAL_ERROR` with message `discovery service unavailable`. Attach `discovery_service` to `DaemonContext`.
- [X] T023 [US1] Extend `src/agenttower/cli.py`: add a `scan` subcommand with mutually-exclusive mode flags (only `--containers` exists in FEAT-003) and `--json`. Implement the request → response → render flow per contracts/cli.md C-CLI-201, including the bare `agenttower scan` (no flag) → exit `1` with the documented stderr message. The degraded exit code `5` and the two-line stderr that goes with it lands later in this same FEAT-003 task list under US3; for US1's happy path, the renderer always exits `0` on `result.status == "ok"`.
- [X] T024 [US1] Extend `src/agenttower/cli.py`: add a `list-containers` subcommand with `--active-only` and `--json` per contracts/cli.md C-CLI-202. Default rendering emits the fixed-header tab-separated table from C-CLI-202; `--json` emits the canonical envelope. Exit codes per the contract; `5` is unreachable here (no Docker call).

### Tests for User Story 1

- [X] T025 [P] [US1] Add `tests/unit/test_discovery_matching.py`: case-insensitivity, substring matching, default rule contains `"bench"`, casefold equivalence (e.g., `"BENCH"` matches `"py-bench"`). Config-driven cases (multi-substring, validation) are deferred to US2.
- [X] T026 [P] [US1] Add `tests/unit/test_discovery_reconcile.py`: insert-as-active for new ids, update-and-mark-active for existing ids, mark-inactive for previously-active ids that disappear, and the FR-026 inspect-failure preservation rules (prior-record → touch-only; no-prior-record → no write). Verifies `matched_count` and `inactive_reconciled_count` match data-model.md §5, including the FR-041 invariant that `matched_count + ignored_count` equals the number of parseable `docker ps` rows for a healthy scan.
- [X] T027 [P] [US1] Add `tests/unit/test_socket_api_scan_methods.py`: in-process dispatch for `scan_containers` and `list_containers` against an in-memory SQLite plus a `FakeDockerAdapter`. Asserts the JSON envelope shape from contracts/socket-api.md §3.2 and §4.2 verbatim, including ordering (active rows first, then inactive, then `container_id ASC` tiebreaker per R-011). Add a failure-injection case where the SQLite write raises mid-scan and assert the transaction rolls back, no JSONL append is attempted, the scan mutex is released, the response is `internal_error`, and a follow-up `ping`/`status` succeeds (FR-042).
- [X] T028 [US1] Add `tests/integration/test_cli_scan_containers.py`: spawn the daemon with `AGENTTOWER_TEST_DOCKER_FAKE` pointing at a fixture with `[py-bench, redis]`, run `agenttower scan --containers`, assert exit `0`, six-line `key=value` stdout block (T023 contract), `matched=1`, `ignored=1`. Run `--json` form and assert canonical-line shape. Add an empty healthy fixture returning zero containers and assert a `container_scans` row still persists with `matched_count=0`, `ignored_count=0`, and `inactive_reconciled_count=0` (FR-046).
- [X] T029 [P] [US1] Add `tests/integration/test_cli_list_containers.py`: after a single scan persists a matching container, `agenttower list-containers` returns the documented fixed-header table; `--json` returns the documented envelope; the empty-DB case still exits `0` and emits only the header line.

**Checkpoint**: At the end of Phase 3, the US1 happy path is verifiable internally, but FEAT-003 is NOT release/merge-ready until Phases 5 and 6 complete because the scan mutex, real adapter, degraded states, and final regressions land later in this same task list. `pytest tests/unit/test_discovery_*.py tests/unit/test_socket_api_scan_methods.py tests/integration/test_cli_scan_containers.py tests/integration/test_cli_list_containers.py` all pass. US1 acceptance scenarios 1–3 are demonstrably true. Spec SC-001, SC-002, SC-003 are satisfied with the fake adapter.

---

## Phase 4: User Story 2 — Configure Bench Name Matching (Priority: P2)

**Story goal**: A developer can edit `~/.config/opensoft/agenttower/config.toml` to add a `[containers] name_contains = ["bench", "dev"]` block; the next scan honors it; an empty/non-list/non-string/blank value is rejected with `config_invalid` and does NOT silently widen scope. Spec US2 acceptance scenarios 1–3 all pass.

**Independent test**: With a fixture config containing `name_contains = ["bench", "dev"]` and a fake adapter returning `[py-bench, api-dev, postgres]`, the scan persists `py-bench` and `api-dev` as active and reports `postgres` as ignored. With a fixture config containing `name_contains = []`, the scan exits non-zero with `config_invalid`.

⚠️ Do not begin until Phase 3 is complete (US2 layers config-driven matching on top of US1's hardcoded default).

### Implementation for User Story 2

- [X] T030 [US2] Extend `src/agenttower/config.py`: add `load_containers_block(config_path) -> MatchingRule` that reads the optional `[containers]` table from the existing TOML config (FEAT-001 owns the loader; this adds the FEAT-003 block only). Validation per FR-006 / FR-030: missing block → `default_rule()`; present block must have `name_contains` as a list of non-empty strings (post-`.strip()`); reject empty list, non-list, non-string element, blank-after-strip, more than 32 entries, or any entry longer than 128 characters with `ConfigInvalidError(message=...)` (the message names the offending value verbatim, sanitized to ≤2048 chars per FR-032).
- [X] T031 [US2] Extend `src/agenttower/discovery/service.py`: read the matching rule from a callable supplied at construction time (`rule_provider: Callable[[], MatchingRule]`). The default daemon wires `rule_provider = lambda: load_containers_block(paths.config_file)` so the rule is re-read once per scan (research R-009, FR-030). Tests can pass a `lambda: MatchingRule(...)` for fixed-rule cases.
- [X] T032 [US2] Extend `src/agenttower/socket_api/methods.py` `_scan_containers`: catch `ConfigInvalidError` and return `errors.make_error(CONFIG_INVALID, exc.message)`. The error path MUST short-circuit BEFORE any Docker call (FR-030, R-009).
- [X] T033 [US2] Extend `src/agenttower/daemon.py`: replace the US1 hardcoded `default_rule()` argument with the callable form from T031.

### Tests for User Story 2

- [X] T034 [P] [US2] Add `tests/unit/test_config_containers_block.py`: missing block → `default_rule()`; valid `["bench", "dev"]` → matches both substrings; empty list → `ConfigInvalidError`; non-list (int, string, dict) → `ConfigInvalidError`; non-string element (mixed list) → `ConfigInvalidError`; blank-after-strip element → `ConfigInvalidError`; over-length (33 entries; one entry of 129 chars) → `ConfigInvalidError`. Each error case asserts the message names the offending value.
- [X] T035 [US2] Add `tests/integration/test_cli_scan_custom_rule.py`: write a fixture config with `name_contains = ["bench", "dev"]`, spawn the daemon, point `AGENTTOWER_TEST_DOCKER_FAKE` at `[py-bench, api-dev, postgres]`, run `agenttower scan --containers`, assert `matched=2 ignored=1`, then `list-containers` returns both in active rows. Then change config to `name_contains = ["dev"]`, run a second successful scan, and assert the previously-active `py-bench` row is now `active=0` because it no longer matches the current in-scope rule (FR-049).
- [X] T036 [P] [US2] Add `tests/integration/test_cli_scan_config_invalid.py`: write a fixture config with `name_contains = []`, run `agenttower scan --containers --json`, assert `{"ok":false,"error":{"code":"config_invalid","message":"..."}}`, exit `3`, and that NO Docker call (no `subprocess.run` against `"docker"`) was attempted (FR-030 short-circuit). Repeat for `name_contains = "bench"` (non-list) and `name_contains = ["", "bench"]` (blank-after-strip).

**Checkpoint**: At the end of Phase 4, US2 acceptance scenarios pass. The config-invalid short-circuit is verifiable end-to-end. The daemon still serves US1's default-rule case unchanged.

---

## Phase 5: User Story 3 — Handle Docker Degraded States (Priority: P3)

**Story goal**: A developer running `agenttower scan --containers` against a fake adapter that simulates command-not-found, permission-denied, timeout, non-zero exit, or malformed-inspect errors gets clear CLI output and a degraded scan result. The daemon stays alive; subsequent `agenttower status` succeeds. Concurrent scans serialize via the daemon mutex. Spec US3 acceptance scenarios 1–3 pass.

**Independent test**: For each degraded class (5 of them) the fake adapter triggers, the CLI returns within 3 s (SC-004) with either exit `3` (whole-scan failure) or exit `5` (partial degrade), `agenttower status` immediately afterwards still returns `alive=true`, and the `container_scans` table contains the new row plus a JSONL `container_scan_degraded` event.

⚠️ Do not begin until Phase 4 is complete (US3 plugs the real adapter, mutex, JSONL emit, and degraded exit code `5` into the existing US1+US2 path).

### Implementation for User Story 3

- [X] T037 [US3] Create `src/agenttower/docker/subprocess_adapter.py`: `SubprocessDockerAdapter(env=os.environ.copy())` implementing the `DockerAdapter` Protocol. `list_running()` runs `subprocess.run([resolved_docker, "ps", "--no-trunc", "--format", "{{.ID}}\\t{{.Names}}\\t{{.Image}}\\t{{.Status}}"], capture_output=True, text=True, timeout=5.0, check=False, shell=False, env=self._env)`. `inspect(ids)` runs `subprocess.run([resolved_docker, "inspect", *ids], ..., timeout=5.0)`. Resolves the binary with `shutil.which("docker", path=self._env.get("PATH", os.defpath))` per FR-028. On `FileNotFoundError` / `which` returning `None` → raise `DockerError(code=DOCKER_UNAVAILABLE, ...)`. On `subprocess.TimeoutExpired` → call `proc.kill()` then `proc.wait()` (FR-029) and raise `DockerError(code=DOCKER_TIMEOUT, ...)`. On non-zero exit → inspect stderr for the documented permission-denied substring and emit `DOCKER_PERMISSION_DENIED`; otherwise `DOCKER_FAILED`. On parse failures → `DOCKER_MALFORMED`. All raised messages are bounded to 2048 characters and stripped of NUL/control bytes per FR-032.
- [X] T038 [US3] Re-export `SubprocessDockerAdapter` from `src/agenttower/docker/__init__.py`.
- [X] T039 [US3] Extend `src/agenttower/daemon.py` adapter resolution: when `AGENTTOWER_TEST_DOCKER_FAKE` is unset, instantiate `SubprocessDockerAdapter()`. Production path now wires the real adapter; the fake remains the test-only path.
- [X] T040 [US3] Extend `src/agenttower/discovery/service.py`: introduce a `threading.Lock` instance attribute `_scan_mutex`. `scan()` acquires it with `acquire(blocking=True)` BEFORE generating the scan id, releases it AFTER the SQLite commit (FR-023, R-005, data-model.md §4.2). The lock is recreated on daemon restart (FR-035). `list_containers` MUST NOT touch this lock (FR-034).
- [X] T041 [US3] Extend `src/agenttower/discovery/service.py` `scan()`: wrap the adapter calls in try/except for `DockerError`. On a whole-scan failure (`docker ps` raised), still write a `container_scans` row with `status='degraded'` and the captured `error_code`, `error_message` (≤2048 chars, NUL/control-byte stripped per FR-032), then bubble the error up so the socket handler returns the `ok: false` envelope. On per-container inspect failures, build `error_details` (one entry per failed candidate with `error_code` from the closed subset in research R-014), apply the FR-026 reconciliation (touch-only for prior-record candidates; skip for no-prior-record candidates), insert the `container_scans` row with `status='degraded'`, set the top-level `error_code` to the first per-container error code in Docker ps order per FR-044, and return `ScanResult` to the caller.
- [X] T042 [US3] Extend `src/agenttower/discovery/service.py` `scan()`: AFTER the SQLite commit, when `status='degraded'`, call `events.writer.append_event(events_file, type="container_scan_degraded", payload={"scan_id": ..., "error_code": ..., "error_message": ..., "error_details": [...]})` exactly once. Healthy scans MUST NOT emit (FR-019, FR-046). A JSONL append failure logs to the lifecycle log but does not undo the SQLite write (FR-043).
- [X] T043 [US3] Extend `src/agenttower/discovery/service.py` `scan()`: emit `scan_started` to the lifecycle log BEFORE any Docker call (after acquiring the mutex and generating the scan id) and `scan_completed` AFTER the SQLite commit per research R-015. Each line is TSV: `<iso_ts>\tscan_started\tscan_id=<uuid>` and the longer `scan_completed` form per research R-015 (status, matched, inactive, ignored, optional `error=<code>`). Lifecycle rows MUST contain only scan id, status, counts, and closed error code; they MUST NOT include raw inspect output, raw env values, label values, mount source paths, or full Docker stderr (FR-033).
- [X] T044 [US3] Extend `src/agenttower/socket_api/methods.py` `_scan_containers`: handle the new `DockerError` raised path by returning `errors.make_error(error.code, error.message)` for whole-scan failures. Healthy and partial-degrade `ScanResult` instances continue to return `errors.make_ok(result)` (envelope `ok: true`) per contracts/socket-api.md §3.3.
- [X] T045 [US3] Extend `src/agenttower/cli.py` scan renderer: on envelope `ok: true` with `result.status == "degraded"`, exit `5` and emit the two stderr lines (`error: <message>`, `code: <error_code>`) per contracts/cli.md C-CLI-201. On envelope `ok: false`, continue to exit `3` per FEAT-002's two-line error format. Healthy `result.status == "ok"` still exits `0`.

### Tests for User Story 3

- [X] T046 [P] [US3] Add `tests/unit/test_docker_subprocess_adapter.py`: assert argv is exactly `["docker", "ps", "--no-trunc", "--format", "{{.ID}}\\t{{.Names}}\\t{{.Image}}\\t{{.Status}}"]` and exactly `["docker", "inspect", *ids]`; `shell=False`; `timeout=5.0`. Patch `subprocess.run` to raise `FileNotFoundError` → `DOCKER_UNAVAILABLE`; raise `subprocess.TimeoutExpired` → `DOCKER_TIMEOUT` AND verify the patched `Popen.kill()` + `wait()` was called (FR-029); return CompletedProcess with non-zero exit and permission-denied stderr → `DOCKER_PERMISSION_DENIED`; return invalid JSON → `DOCKER_MALFORMED`.
- [X] T047 [P] [US3] Add `tests/integration/test_cli_scan_degraded.py`: parameterize across the five degraded classes (`command_not_found`, `permission_denied`, `timeout`, `non_zero_exit`, `malformed`). For each, the CLI invocation completes within 3 s (SC-004), exits `3` (whole-scan classes) or `5` (partial-degrade class), the `container_scans` row is present with `status='degraded'`, `events.jsonl` gained exactly one `container_scan_degraded` line for that scan id, and a follow-up `agenttower status` succeeds within 1 s (FR-018, FR-045). Include a degraded fixture with a 4 KiB Docker error string and assert the lifecycle log row remains bounded and contains only the closed error code, not raw stderr or inspect output (FR-033). Include a multi-failure partial-degrade fixture where matching candidates A and B both fail inspect, A fails first in Docker ps order with `docker_timeout` and B fails with `docker_failed`; assert top-level `error_code == "docker_timeout"` and `error_details` has exactly two entries (FR-044).
- [X] T048 [P] [US3] Add `tests/integration/test_cli_scan_reconciliation.py`: scan with `[py-bench]` → active, then scan with `[]` → row transitions to `active=0`, `inactive_reconciled=1` in the new scan, `last_scanned_at` advances; rerun with `[py-bench]` → row re-activates with `first_seen_at` preserved (FR-040, SC-002).
- [X] T049 [P] [US3] Add `tests/integration/test_cli_scan_concurrent.py`: spawn two parallel `agenttower scan --containers --json` invocations with a fake adapter that sleeps 200 ms before returning. Assert two distinct `scan_id` values, two distinct `container_scans` rows, and that `started_at_B >= completed_at_A` (the mutex serialized them) per FR-023 / Quickstart §4. Five-caller fan-out asserts none crashes the daemon (FR-035).
- [X] T050 [P] [US3] Add `tests/integration/test_cli_scan_no_real_docker.py`: a session-scoped fixture monkeypatches `subprocess.run` and `shutil.which` to assert no call uses `"docker"` argv[0]. The fixture is auto-applied to every FEAT-003 integration test via `pytest.fixture(autouse=True, scope="session")` declared in `tests/integration/conftest.py`; this test is the explicit, named guard required by SC-007 while T003 supplies the broad autouse guard. Also add a static source assertion that FEAT-003 code contains no `sudo`, no Docker `start`/`stop`/`exec` subprocess argv, and no `os.setuid` / `os.setgid` calls (FR-031).

**Checkpoint**: At the end of Phase 5, US3 acceptance scenarios 1–3 pass. The five degraded classes are observable end-to-end. Concurrent scans demonstrably serialize. SC-004 holds. The daemon survives every degraded class.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Verify backward compatibility, exercise the no-network-listener invariant for FEAT-003, run the manual quickstart smoke, and confirm the FEAT-002 test suite still passes (SC-005).

- [X] T051 [P] Add `tests/integration/test_feat003_no_network.py`: spawn the daemon under FEAT-003 (the new methods registered) and assert no `AF_INET` / `AF_INET6` socket is opened, mirroring FEAT-002's `tests/integration/test_daemon_no_network.py` pattern. This is the FEAT-003 reaffirmation of FR-021 / SC-007.
- [X] T052 [P] Run the FEAT-001 and FEAT-002 test suites (`pytest tests/unit/test_paths.py tests/unit/test_socket_api_*.py tests/integration/test_cli_ensure_daemon.py tests/integration/test_cli_status.py tests/integration/test_cli_stop_daemon.py tests/integration/test_daemon_lifecycle.py tests/integration/test_daemon_recovery.py tests/integration/test_daemon_signals.py tests/integration/test_daemon_concurrent_start.py tests/integration/test_daemon_no_network.py tests/integration/test_socket_api_protocol.py`) end-to-end and confirm zero regressions (SC-005).
- [X] T053 [P] Manual smoke per `quickstart.md` §1–§6 against a real Docker daemon, capturing the exact command outputs into a transient `/tmp/feat003-smoke.log`. Use this to spot any contract drift between the implementation and the documented commands; if drift exists, file an issue or fix the doc — do NOT silently fix the contract.
- [X] T054 Update the `agenttower status` quickstart line in `quickstart.md` if the daemon-version string changes once FEAT-003 ships (e.g., `0.2.0` → `0.3.0` per pyproject bump). This is a doc-only follow-up; if the version string is unchanged, mark this task complete with a note.
- [X] T055 Confirm `CLAUDE.md` SPECKIT marker still points at `specs/003-bench-container-discovery/plan.md` (already done by `/speckit.plan`); re-check after rebases.

**Checkpoint**: All FEAT-003 unit and integration tests green; FEAT-001 and FEAT-002 suites green; quickstart smoke clean against a real Docker daemon.

---

## Dependencies

- **Phase 1 (Setup, T001–T003)** has no prerequisites and can start immediately.
- **Phase 2 (Foundational, T004–T014)** depends on Phase 1.
- **Phase 3 (US1, T015–T029)** depends on Phase 2.
- **Phase 4 (US2, T030–T036)** depends on Phase 3 (it layers config-driven matching onto US1's hardcoded default and the US1 dispatch handlers).
- **Phase 5 (US3, T037–T050)** depends on Phase 4 (it plugs the real adapter, mutex, degraded paths, JSONL emit, and exit code `5` into the working US1+US2 surface).
- **Phase 6 (Polish, T051–T055)** depends on Phase 5.

Within each phase:
- `[P]` tasks operate on different files and have no inter-dependencies; run in parallel.
- Tasks without `[P]` touch a shared file (`cli.py`, `daemon.py`, `methods.py`, `service.py`) and must run sequentially in the listed order to avoid merge conflicts.

---

## Parallel Execution Examples

### Within Phase 2 (Foundational)

After T004–T005 (schema migration) lands, run T006, T007, T008, T009, T010 in parallel — they touch independent files:

```bash
# (conceptual; actual runner is up to the operator)
parallel ::: \
  "implement T006: src/agenttower/state/containers.py" \
  "implement T007: src/agenttower/docker/adapter.py" \
  "implement T008: src/agenttower/docker/parsers.py" \
  "implement T009: src/agenttower/docker/fakes.py" \
  "implement T010: src/agenttower/docker/__init__.py exports"
```

T013 and T014 (foundational unit tests) can run in parallel with each other and with T011 (`socket_api/errors.py` extension) and T012 (`socket_api/methods.py` `DaemonContext` extension).

### Within Phase 3 (User Story 1)

T015 (matching) and T016 (reconcile) are independent pure modules — implement in parallel. T017 (DiscoveryService.scan happy path) depends on both. T018 (`discovery/__init__.py` exports) depends on T015–T017.

T025, T026, T027 (US1 unit tests) can all run in parallel after T015–T017 are merged. T029 ([P] integration test) can run in parallel with the US1 unit tests once T020 is complete.

### Within Phase 5 (User Story 3)

T046 (subprocess adapter unit tests) can run in parallel with T047, T048, T049, T050 (integration tests) once T037–T045 are all merged — they exercise different surfaces and live in different files.

---

## Implementation Strategy

All phases T001–T055 are in scope for this FEAT-003 PR. The phase checkpoints are still useful because each user story is independently testable, but no task is deferred to a later feature and `/speckit.taskstoissues` is not needed for this task list.

### Incremental Checkpoints

- **Checkpoint 1**: Phases 1 + 2 + 3 → US1 happy path.
- **Checkpoint 2**: + Phase 4 → US2 config-driven matching + invalid-config rejection.
- **Checkpoint 3**: + Phase 5 → US3 real Docker adapter, degraded states, mutex, exit `5`.
- **Checkpoint 4**: + Phase 6 → backward-compat verification + smoke test → ready to merge to `main`.

Each checkpoint is independently testable: every checkpoint runs only the test files added or extended within that phase, without requiring later phases.

---

## Format Validation

Every task above conforms to the required checklist format:
- Starts with `- [ ]` (unchecked markdown checkbox).
- Carries a sequential ID `T001` through `T055`.
- User-story tasks (T015–T050) carry `[USn]` labels; Setup/Foundational/Polish tasks do not.
- `[P]` markers appear only where the task touches a file no other in-phase task touches.
- Every task description names at least one exact file path or named test scenario for unambiguous execution.
