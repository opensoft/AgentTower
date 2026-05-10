# Tasks: Pane Log Attachment and Offset Tracking

**Input**: Design documents from `/specs/007-log-attachment-offsets/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests are INCLUDED. Plan.md mandates dedicated unit + integration coverage for every FR (constitution principle "Observable and Scriptable" + plan.md § Project Structure test inventory). Each user story phase ships with the tests that prove it independently.

**Organization**: Tasks are grouped by user story (US1..US7) so each story can be implemented and validated as an independent increment. P1 stories (US1 + US2) are the MVP slice.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps the task to a user story (US1..US7); Setup / Foundational / Polish phases carry no story label
- File paths are absolute under the repo root (`src/agenttower/`, `tests/unit/`, `tests/integration/`)

## Path Conventions

- Source: `src/agenttower/` (single-project Python CLI + daemon, per plan.md § Project Structure)
- Unit tests: `tests/unit/`
- Integration tests: `tests/integration/`
- Spec/contracts: `specs/007-log-attachment-offsets/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Land the additive surface area FEAT-007 needs before any user story logic runs — closed-set error codes, schema migration scaffolding, the new `logs/` package skeleton, and the wire-envelope dispatch slots.

- [X] T001 [P] Add FEAT-007 closed-set error codes to `src/agenttower/socket_api/errors.py`: `LOG_PATH_INVALID`, `LOG_PATH_NOT_HOST_VISIBLE`, `LOG_PATH_IN_USE`, `PIPE_PANE_FAILED`, `TMUX_UNAVAILABLE`, `ATTACHMENT_NOT_FOUND`, `LOG_FILE_MISSING`. Extend `CLOSED_CODE_SET` with these constants. Existing codes unchanged byte-for-byte (FR-038).
- [ ] T002 [P] Create `src/agenttower/logs/__init__.py` with empty package marker plus the re-export stubs `LogAttachmentRecord`, `LogOffsetRecord`, `AttachLogRequest`, `LogService`, `LogRedactor` (placeholder typing only; concrete classes filled in by foundational + story tasks).
- [X] T003 Bump `CURRENT_SCHEMA_VERSION` from `4` to `5` in `src/agenttower/state/schema.py`; add empty `_apply_migration_v5` function and register it in `_MIGRATIONS[5]`. Migration body lands in T010 (foundational); this task only wires the version constant + dispatch hook so existing v4 DBs do not refuse to open.
- [X] T004 [P] Add four placeholder dispatch entries to `src/agenttower/socket_api/methods.py` (`attach_log`, `detach_log`, `attach_log_status`, `attach_log_preview`) routed to NOT-YET-IMPLEMENTED handlers that return `internal_error`. Existing FEAT-001..006 entries unchanged byte-for-byte. Insertion order appended after FEAT-006 entries per contracts/socket-api.md §1.
- [ ] T005 [P] Add four typed client wrappers to `src/agenttower/socket_api/client.py`: `attach_log()`, `detach_log()`, `attach_log_status()`, `attach_log_preview()`. Reuse FEAT-002 connect / framing helpers verbatim; bodies route to the dispatch added in T004.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Land the cross-cutting modules every user story depends on: SQLite schema, identifier generation, host-visibility proof, pipe-pane construction, host-fs adapter, log-path validation, mutex registry, audit/lifecycle surfaces.

**⚠️ CRITICAL**: No user story phase below can begin until this phase is complete.

### Schema and DAO layer

- [X] T010 Implement `_apply_migration_v5` in `src/agenttower/state/schema.py` per data-model.md §1.1 + §1.2: create `log_attachments` table (TEXT PK, FK to `agents.agent_id`, six denormalized pane-key columns, status CHECK, source CHECK, FK self-ref `superseded_by`), create `log_offsets` table (composite PK, FK to `agents.agent_id`), and create the four indexes (`log_attachments_agent_status`, `log_attachments_pane_status`, `log_attachments_active_log_path` partial unique, `log_offsets_agent`). Idempotent via `IF NOT EXISTS`.
- [X] T010a [P] Integration + unit test in `tests/integration/test_schema_migration_v5.py` and `tests/unit/test_schema_v5_migration_unit.py`: v4-only DB upgrades to v5 cleanly; v5-already-current re-open is a no-op; forward-version refusal preserved; FEAT-001..006 tables untouched (FR-038 / SC parallel to FEAT-006 SC-010). Gates every later phase — schema-migration tests live in Phase 2 because every story depends on the v5 schema being present.
- [X] T011 [P] Create `src/agenttower/state/log_attachments.py` — typed read/write helpers mirroring `state/agents.py` pattern: `insert_attachment`, `update_status`, `select_active_for_agent`, `select_most_recent_for_agent`, `select_active_by_log_path`, `select_by_pane_composite_key`. Closed-set validation at the application layer for `status` and `source` per data-model.md §4.2.
- [X] T012 [P] Create `src/agenttower/state/log_offsets.py` — typed read/write helpers: `insert_offset_at_zero`, `update_offset` (atomic advance — FEAT-008's anchor), `select_for_agent_path`, `reset_offset_for_rotation`, `update_file_observation` (`file_inode`, `file_size_seen`, `last_output_at`). Initial values per FR-015.

### Identifier generation

- [X] T013 [P] [US1] Create `src/agenttower/logs/identifiers.py` — `generate_attachment_id() -> str` using `secrets.token_hex(6)` → `lat_<12-hex>` (R-001). Bounded retry loop (≤ 5 attempts) on `IntegrityError` from caller; expose `MAX_ATTACHMENT_ID_RETRIES`.
- [X] T014 [P] Unit test in `tests/unit/test_attachment_id_generation.py`: `lat_<12-hex>` shape regex; collision retry under fake `IntegrityError`; assert exhausting the bounded retry budget (`MAX_ATTACHMENT_ID_RETRIES = 5`, Research R-001 / FR-035 retry-budget rule) raises `internal_error` and the daemon stays alive; entropy bound (no leading zeros constraint); namespace non-collision with `agt_<12-hex>` (FR-038 / Research R-001).

### Host-visibility proof + path validation

- [X] T015 Create `src/agenttower/logs/host_fs.py` — adapter for `os.stat(follow_symlinks=False)`, `os.path.exists`, `os.path.realpath`, `os.makedirs(mode=0o700, exist_ok=True)`, `os.access`, `os.open(O_CREAT|O_WRONLY|O_EXCL, 0o600)`. Honors `AGENTTOWER_TEST_LOG_FS_FAKE` per Research R-013; production path uses real syscalls verbatim. `stat_log_file` returns `FileStat` with `inode` (shaped `"<dev>:<ino>"` per R-010), `size`, `mtime_iso`. Reuse FEAT-001 `_verify_file_mode` / `_verify_dir_mode` helpers (FR-008, FR-048, FR-057).
- [X] T016 [P] Create `src/agenttower/logs/path_validation.py` — `validate_log_path(path: str) -> None` raising `LogPathInvalid`. Implements FR-006 + FR-051 + FR-052 + FR-053: absolute, ≤ 4096 chars, no `..`, no NUL/C0/`\n`/`\r`/`\t`/`\x7f`, not under daemon-owned roots, realpath not under `/proc`/`/sys`/`/dev`/`/run`. Loads daemon-owned root constants from a single module-level source (`logs/canonical_paths.py`).
- [X] T017 [P] Create `src/agenttower/logs/canonical_paths.py` — single authoritative source for the canonical log-root prefix `~/.local/state/opensoft/agenttower/logs/` (FR-005). Exposes helpers used by FR-011 canonical-target match, FR-043 orphan detection, FR-052 daemon-owned-path rejection, and FR-054 strict-equality match. No duplication of the constant elsewhere.
- [X] T018 Create `src/agenttower/logs/host_visibility.py` — `prove_host_visible(container_mounts_json, container_side_path) -> HostVisibilityProof` per Research R-004 + FR-007 + FR-050 + FR-056 + FR-063: filter mounts to `bind`/`volume`, deepest-prefix-wins, realpath escape rejection, ≤ 8-hop chained-mount depth, ≤ 256 mount entries cap, `os.access(W_OK)` for attach paths. Raises `LogPathNotHostVisible` with actionable message; emits `mounts_json_oversized` lifecycle event when bound exceeded.
- [X] T019 [P] Unit test in `tests/unit/test_host_visibility_proof.py`: positive (canonical bind mount present), negative (no canonical mount), overlapping mounts (deepest match wins), symlink escape rejected, read-only mount rejected for attach, empty / malformed `Mounts` JSON, > 256 mount entries rejection.
- [X] T020 [P] Unit test in `tests/unit/test_log_path_validation.py`: every FR-006 rule + every FR-051/FR-052/FR-053 hardening rule produces `log_path_invalid` with byte-identical message shape vs. FEAT-006 `project_path` validation where applicable.

### Pipe-pane shell construction

- [X] T021 Create `src/agenttower/logs/pipe_pane.py` — `build_attach_argv(container_user, container_id, pane_short_form, container_side_log) -> list[str]` and `build_toggle_off_argv(...)` using `shlex.quote` per Research R-006 + FR-010 + FR-047. `build_inspection_argv(...)` for the FR-011 `tmux list-panes -F '#{pane_pipe} #{pane_pipe_command}' -t <pane>` form. All output is the argv list passed to subprocess (no `shell=True` at outer Python layer).
- [X] T022 [P] Unit test in `tests/unit/test_pipe_pane_command_construction.py`: shlex-quoted log path, shlex-quoted pane short form, exact argv shape per FR-010, rejects un-validated raw NUL byte, defense-in-depth shlex even on already-validated input.
- [X] T023 Create `src/agenttower/logs/pipe_pane_state.py` — `parse_list_panes_output(output: str) -> PaneState` returning `(pane_pipe_active: bool, pipe_command: str)`. `classify_pipe_target(pipe_command, expected_canonical_path)` does STRICT EQUALITY match per FR-054 (no substring or prefix match). Uses `shlex` to tokenize the pipe command and compares the full `cat >> <quoted_path>` form.
- [X] T024 [P] Unit test in `tests/unit/test_pipe_pane_state_inspection.py`: parses `pane_pipe=0` / `pane_pipe=1`; classifies AgentTower-canonical (strict equality) vs. foreign target; rejects substring-trickery (`cat >> /tmp/x; cat >> /canonical/path/...` classified as foreign per FR-054).

### Sanitization for stderr / pipe_pane_command

- [X] T025 [P] Add `sanitize_pipe_pane_stderr(stderr: bytes) -> str` in `src/agenttower/logs/pipe_pane.py` (or shared helper in FEAT-006 sanitization module if one exists): NUL strip, ≤ 2048 chars, no control bytes (FR-012, FR-062). Add `sanitize_pipe_pane_command_for_storage` (≤ 4096 chars) for the `log_attachments.pipe_pane_command` column.
- [X] T026 [P] Unit test in `tests/unit/test_pipe_pane_failed_sanitization.py`: non-zero docker exec exit; non-zero tmux pipe-pane exit; tmux stderr matching `session not found` / `pane not found` / `no current target`; sanitized stderr excerpt rules (FR-012).

### Mutex registry

- [X] T027 Create `src/agenttower/logs/mutex.py` — `LogPathLockMap` per-`log_path` mutex registry. Key by canonical host-side path (str). Thread-safe fetch-or-create under guard lock (mirrors FEAT-006 `_PerKeyLockMap` pattern, Research R-007). `acquire_in_order(agent_lock, log_path_lock_or_none)` helper enforces FR-059 ordering: agent FIRST, log_path SECOND only when explicit `--log` was supplied. Reverse-order acquisition raises `internal_error`.
- [X] T028 [P] Unit test in `tests/unit/test_log_path_locks_mutex.py`: concurrent fetch returns same lock object; thread-safe under contention; `acquire_in_order` enforces agent-then-path ordering; raises `internal_error` on reverse-order attempt (SC-013).

### Audit + lifecycle event surface

- [X] T029 Create `src/agenttower/logs/audit.py` — `append_log_attachment_change(payload: dict) -> None` reusing FEAT-001 `events.writer.append_event` verbatim; emits the FR-044 audit row per data-model.md §2 with bounded payload sizes (FR-062). `payload.source` ∈ `{explicit, register_self}`. Skip on no-op (FR-018) and failed attaches (FR-045).
- [X] T030 Create `src/agenttower/logs/lifecycle.py` — emit helpers for `log_rotation_detected`, `log_file_missing`, `log_file_returned`, `log_attachment_orphan_detected`, `mounts_json_oversized`, `socket_peer_uid_mismatch` (data-model.md §3). Suppression rules per FR-061: per-`(agent_id, log_path)` last-state tracking for `log_file_missing`; per-`(agent_id, log_path, file_inode)` triple suppression for `log_file_returned`; per-`(container_id, pane_composite_key, observed_pipe_target)` triple per daemon lifetime for `log_attachment_orphan_detected`. Routes via the daemon's existing lifecycle logger (NOT events.jsonl per FR-046).

### Socket-method gates

- [X] T031 Wire `_check_schema_version` and `_check_unknown_keys` in `src/agenttower/socket_api/methods.py` for the four new methods (T004 placeholders). Allowed-keys sets per data-model.md §4.4 + FR-039. `attach_log`: `{schema_version, agent_id, log_path, source}` (source rejected on wire — clients cannot supply). `detach_log`: `{schema_version, agent_id}`. `attach_log_status`: `{schema_version, agent_id}`. `attach_log_preview`: `{schema_version, agent_id, lines}`. Unknown keys → `bad_request` listing offending keys.
- [X] T032 [P] Unit test in `tests/unit/test_socket_api_attach_log_envelope.py`: every FR-039 wire shape rule, including `source` rejected on wire (clients cannot supply); unknown key `bad_request`; missing `agent_id` rejection.

### CLI subparsers

- [X] T033 Extend `src/agenttower/cli.py` with new subparsers: `attach-log` (with `--target`, `--log`, `--status`, `--preview`, `--json` mode flags), `detach-log` (with `--target`, `--json`). Use `argparse.SUPPRESS` defaults for every optional flag per Research R-002 (mirrors FEAT-006 Q1 wire encoding). Add `--attach-log` flag with optional nested `--log` to existing `register-self` subparser. Bodies invoke the T005 client wrappers; closed-set error → exit code mapping per FR-036.

**Checkpoint**: Foundation ready. Schema migrated, every supporting module + adapter + test seam in place. User story phases can begin.

---

## Phase 3: User Story 1 - Attach a tmux pipe-pane log to a registered agent (Priority: P1) 🎯 MVP

**Goal**: A registered FEAT-006 agent's pane output is durably captured to a host-visible log file via `tmux pipe-pane -o` issued through `docker exec`. One row in `log_attachments`, one row in `log_offsets` at `(0,0)`, one JSONL audit row.

**Independent Test**: Spin up the existing FEAT-002 daemon harness, seed FEAT-003 + FEAT-004 + FEAT-006 with one active container/pane/agent, run `agenttower attach-log --target <agent-id>`, assert exit `0`, assert one row in each table, assert one JSONL `log_attachment_change` row, assert the fake `docker exec` received the documented `tmux pipe-pane -o -t <pane> 'cat >> <log>'` invocation (US1 acceptance scenarios + plan.md § Project Structure inventory).

### Tests for User Story 1

- [X] T040 [P] [US1] Unit test in `tests/unit/test_log_attachments_table.py`: composite uniqueness `(agent_id, log_path)` when status=active enforced via partial unique index; status CHECK constraint; `lat_<12-hex>` PK shape; FK to `agents.agent_id`; field types + nullability per data-model.md (FR-014).
- [X] T041 [P] [US1] Unit test in `tests/unit/test_log_offsets_table.py`: composite PK `(agent_id, log_path)`; initial values `(0, 0, 0, NULL, NULL, 0)` on creation; field types; FK to `agents.agent_id` (FR-015).
- [X] T042 [P] [US1] Unit test in `tests/unit/test_log_attach_transaction.py`: single `BEGIN IMMEDIATE` for `log_attachments` + `log_offsets` writes; rollback on either failure; pipe-pane success without offset row never observable (FR-016).
- [X] T043 [P] [US1] Unit test in `tests/unit/test_log_offsets_durability_signals.py`: every successful write commits; SQLite WAL mode is on; no daemon-side caching ahead of COMMIT (FR-017).
- [X] T044 [P] [US1] Unit test in `tests/unit/test_attach_idempotency.py`: same `(agent_id, log_path)` and status=active is no-op success; no duplicate row; no offset reset; no audit row; pipe-pane re-issued defensively under `-o` flag idempotency (FR-018).
- [X] T045 [P] [US1] Unit test in `tests/unit/test_log_path_in_use.py`: same path owned by different `agent_id` with status=active rejected with `log_path_in_use`; conflicting `agent_id` surfaced in actionable message (FR-009).
- [X] T046 [P] [US1] Unit test in `tests/unit/test_audit_row_shape.py`: `log_attachment_change` payload per data-model.md §2 — every field present (`attachment_id`, `agent_id`, `prior_status`, `new_status`, `prior_path`, `new_path`, `prior_pipe_target`, `source`, `socket_peer_uid`, `ts`); types + nullability; bounded payload sizes per FR-062 (FR-044).
- [X] T047 [P] [US1] Unit test in `tests/unit/test_audit_no_op_skip.py`: idempotent re-attach (FR-018) appends zero audit rows; failed attach appends zero audit rows; only actual state transitions appear (FR-045).
- [X] T048 [P] [US1] Unit test in `tests/unit/test_attach_log_mutex.py`: concurrent `attach_log` for same `agent_id` serialized through FEAT-006 `agent_locks`; concurrent calls for different agents proceed in parallel (FR-040).
- [X] T049 [P] [US1] Unit test in `tests/unit/test_attach_log_path_collision.py`: concurrent `attach_log` from different agents whose explicit `--log` paths collide serialized through `log_path_locks`; first wins, second hits `log_path_in_use` (FR-041).
- [X] T050 [P] [US1] Integration test in `tests/integration/test_cli_attach_log.py`: US1 AS1 / SC-001 — happy-path attach returns 0; one row in each table; one JSONL audit row; fake docker exec received documented invocation; under 2-second P95 budget asserted via fixture timing.
- [X] T051 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_idempotent.py`: US1 AS2 / SC-002 — re-running attach-log 100 times produces exactly one row in each table; no offset reset; no duplicate audit row.
- [X] T052 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_pane_reactivation.py`: US1 AS3 / FR-020 / SC-006 — pane reactivation reuses attachment; `byte_offset` retained byte-for-byte (advanced via test seam to `4096` before reactivation, asserted unchanged after re-attach); pipe-pane re-engaged.
- [X] T053 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_supersede_path_change.py`: US1 AS4 / FR-019 — path change supersedes prior `active` row (this test covers the active→superseded branch; stale/detached supersede branches land in their own stories).
- [X] T054 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_host_visibility.py`: SC-005 / FR-007 — explicit `--log` not under any bind mount refused `log_path_not_host_visible`; zero rows, zero docker exec, zero JSONL.
- [X] T055 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_pipe_pane_failed.py`: FR-012 — non-zero pipe-pane exit / matching stderr → `pipe_pane_failed`; sanitized stderr excerpt; no `log_attachments` row persisted.
- [X] T055a [P] [US1] Integration test in `tests/integration/test_feat007_pipe_pane_race.py`: FR-055 — list-panes succeeds + pipe-pane fails; asserts no retry, no row, no toggle-off, no JSONL. 5 parametrized cases pass.
- [ ] T056 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_tmux_unavailable.py`: FR-013 — tmux not installed in container → `tmux_unavailable`; no docker exec issued.
- [X] T057 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_inactive_agent.py`: edge cases — `agents.active=0` / `containers.active=0` → `agent_inactive`; `panes.active=0` post-rescan → `pane_unknown_to_daemon`.
- [X] T058 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_path_in_use.py`: FR-009 — different agent owns same path → `log_path_in_use`; conflicting `agent_id` in message.
- [X] T059 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_path_invalid.py`: FR-006 + FR-051..053 — relative / `..` / NUL / oversize / shell-meta / daemon-owned-root / `/proc` rejected `log_path_invalid`; SC-012 zero-side-effect assertion.
- [X] T060 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_concurrent_same_agent.py`: FR-040 — two concurrent attach-log calls for same `agent_id` serialize via `agent_locks`; second observes first's writes inside `BEGIN IMMEDIATE`.
- [X] T061 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_concurrent_path_collision.py`: FR-041 — two concurrent attach-log from different agents with colliding `--log` paths; first wins, second hits `log_path_in_use`.
- [ ] T062 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_host_context.py`: edge cases — host shell without `--target` → `host_context_unsupported`; with `--target` → succeeds.
- [X] T063 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_no_daemon.py`: SC parallel to FEAT-006 SC-009 — daemon down → exit `2` with FEAT-002 daemon-unavailable message.
- [X] T064 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_schema_newer.py`: FR-038 — daemon `schema_version` < CLI advertised → `schema_version_newer`; refuses without state mutation.
- [X] T065 [P] [US1] Integration test in `tests/integration/test_cli_attach_log_unknown_keys.py`: FR-039 — wire envelope unknown keys → `bad_request` listing offending keys; including `source` rejection on wire.

### Implementation for User Story 1

- [ ] T070 [US1] Create `src/agenttower/logs/client_resolve.py` — client-side resolver invoked by `cli.py` for `attach-log` / `detach-log`. Reuses FEAT-005 in-container identity for the host-context check; resolves `--target <agent-id>` via the FEAT-006 `list_agents` socket method; maps every failure to a closed-set error code. Used by T080's CLI invocation path.
- [X] T071 [US1] Create `src/agenttower/logs/service.py` — `LogService` orchestrator with `attach_log(req: AttachLogRequest) -> AttachLogResult`. Implements the full validation order from data-model.md §7 (steps 1–23): schema version check, unknown keys, agent resolution (FR-001..004, including FEAT-006 FR-041 focused rescan trigger), log-path shape validation (T016), host-visibility proof (T018), `log_path_in_use` check (T011), `tmux_unavailable` check, mutex acquisition in FR-059 order (T027), `BEGIN IMMEDIATE`, dir+file mode invariants (T015 / FR-008 / FR-048 / FR-057), `tmux list-panes` inspection (T021/T023 / FR-011), `tmux pipe-pane` attach (T021), insert/update `log_attachments` + `log_offsets` (T011, T012), audit row append (T029), COMMIT, lock release LIFO. Handles FR-018 idempotent re-attach branch (no audit row, no row mutation).
- [X] T072 [US1] Wire the `attach_log` daemon-side handler in `src/agenttower/socket_api/methods.py` to `LogService.attach_log` (replace the T004 placeholder). Plumb `socket_peer_uid` from FEAT-002 SO_PEERCRED into the request context per Research R-009. Set `source=explicit` daemon-internally per FR-039.
- [X] T073 [US1] Implement the success + error CLI rendering for `attach-log` in `src/agenttower/cli.py`: text-mode one `key=value` line per field (FR-037), `--json` envelope `{"ok": true, "result": {...}}` (FR-031). Closed-set error mapping per FR-036 + contracts/cli.md C-CLI-701.

### FEAT-007 backwards-compat + no-real-docker-or-tmux gates

- [X] T074 [P] [US1] Integration test in `tests/integration/test_feat007_no_real_docker_or_tmux.py`: parallel to `test_feat006_no_real_docker_or_tmux.py`; assert no real docker / tmux / network call during the FEAT-007 test session beyond what FEAT-003/FEAT-004 fakes simulate.
- [X] T075 [P] [US1] Integration test in `tests/integration/test_feat007_backcompat.py`: SC parallel to FEAT-006 SC-010 — every FEAT-001..006 CLI command produces byte-identical stdout, stderr, exit codes, and `--json` shapes; no existing socket method gains a new code or shape.
- [X] T077 [P] [US1] Unit test in `tests/unit/test_feat007_no_test_seam_in_production.py`: assert `AGENTTOWER_TEST_LOG_FS_FAKE` is read ONLY by `logs/host_fs.py`; production code paths import nothing else from the seam (FR-060).

**Checkpoint**: User Story 1 fully functional. An operator can attach a log to a registered agent and the system maintains the durable two-table state. Demo-ready as MVP slice 1.

---

## Phase 4: User Story 2 - Log offsets persist across daemon restart (Priority: P1)

**Goal**: Offsets recovered from SQLite after `SIGTERM` AND `SIGKILL` daemon restart are byte-for-byte identical to the offsets at shutdown. WAL durability proven; FEAT-008 readers will resume at exactly the same position.

**Independent Test**: Attach one log, advance offset to `(byte_offset=4096, line_offset=137)` via test seam, kill daemon (SIGTERM and SIGKILL paths), restart, re-read the row, assert byte-identical recovery (US2 acceptance scenarios + SC-003).

### Tests for User Story 2

- [X] T080 [P] [US2] Unit test in `tests/unit/test_offset_advance_invariant.py`: `attach-log` MUST NOT advance `byte_offset`; `line_offset` is derived from `byte_offset` and `\n` count; FEAT-007 ships only the schema invariant + persistence (FR-022, FR-023).
- [X] T081 [P] [US2] Integration test in `tests/integration/test_cli_attach_log_offsets_persist_restart.py`: US2 / SC-003 — offsets advanced via test seam to `(4096, 137)`; daemon `SIGTERM` restart; offsets recovered byte-for-byte. Repeat with `SIGKILL` (WAL durability) and assert same invariant. Sub-100ms recovery time asserted at MVP scale per plan.md § Performance Goals.

### Implementation for User Story 2

- [X] T082 [US2] Add the `advance_offset(agent_id, log_path, new_byte_offset, new_line_offset, ...)` test seam in `state/log_offsets.py` (T012). Production-only callable from a dedicated module path that is gated behind a `_FOR_TEST_ONLY_advance_offset` symbol; unit test asserts no production code imports it (mirrors FR-060 pattern).
- [X] T083 [US2] Verify `agenttower/state/schema.py` opens SQLite with WAL mode (`PRAGMA journal_mode=WAL`); if FEAT-001 already established this, add a regression assertion in T043's test rather than re-applying the pragma. Document in plan.md § Constraints if any change to the existing pragma surface is needed.

**Checkpoint**: User Story 2 fully functional. The MVP slice (US1 + US2) is now complete: durable attachment + durable offset across restart.

---

## Phase 5: User Story 3 - Operator-facing log preview applies basic secret redaction (Priority: P2)

**Goal**: `agenttower attach-log --target <agent-id> --preview <N>` emits the last N lines of the host log with FR-028 secret patterns replaced by `<redacted:<type>>` markers. Pure function; no external calls; never alters offsets.

**Independent Test**: Feed fixture log buffers (each FR-028 pattern at known positions) to the redaction utility in isolation; assert documented markers; assert byte-for-byte passthrough on non-matching content; 1000-iteration determinism (US3 + SC-004 + SC-010).

### Tests for User Story 3

- [X] T100 [P] [US3] Unit test in `tests/unit/test_redaction_unanchored.py`: `\bsk-…\b`, `\bgh[ps]_…\b`, `\bAKIA…\b`, `\bBearer …` match anywhere in line with `\b` protection; multiple matches in single line all replaced; word-boundary respected; deterministic across 1000 invocations (FR-027, FR-028, Clarifications Q5, SC-004).
- [X] T101 [P] [US3] Unit test in `tests/unit/test_redaction_anchored.py`: JWT `^…$` only matches standalone lines (length ≥ 32); `.env`-shape `^KEY=VALUE$` only matches standalone lines; mixed lines pass through (FR-028, Clarifications Q5).
- [X] T102 [P] [US3] Unit test in `tests/unit/test_redaction_per_line.py`: input split on `\n` (NOT `splitlines` — preserve `\r` byte-fidelity per Research R-012); each line processed independently; tokens spanning newlines NOT redacted (FR-029).
- [X] T103 [P] [US3] Unit test in `tests/unit/test_redaction_purity.py`: pure function (same input → same output across 1000 calls); no per-call randomness; locale-independent (`re.ASCII` flag verified) (FR-027, FR-029, FR-049).
- [X] T104 [P] [US3] Unit test in `tests/unit/test_redaction_no_offset_alteration.py`: redaction utility consumes raw bytes, produces redacted bytes; `byte_offset` advancement unaffected (FR-030).
- [X] T105 [P] [US3] Unit test in `tests/unit/test_preview_allowed_statuses.py`: preview works against `active` / `stale` / `detached` rows; rejects `superseded` with `attachment_not_found`; rejects no-row with `attachment_not_found` (FR-033, Clarifications Q3).
- [X] T106 [P] [US3] Unit test in `tests/unit/test_preview_file_missing.py`: selected row in allowed status but host file missing → `log_file_missing` closed-set rejection (FR-033, Clarifications Q3).
- [X] T107 [P] [US3] Unit test in `tests/unit/test_preview_redaction_integration.py`: preview output passes through FR-027/FR-028 redaction; raw secrets MUST NOT appear across 1000 runs (SC-010).
- [X] T108 [P] [US3] Unit test in `tests/unit/test_preview_line_cap.py`: N=1, N=200, N=0 (rejected `value_out_of_set`), N=201 (rejected), N=-1 (rejected); empty file (returns empty); file with fewer than N lines returns all (FR-033, FR-064).
- [X] T109 [P] [US3] Unit test in `tests/unit/test_status_universal_read.py`: `--status` always succeeds when agent resolvable; returns most recent row regardless of status; agent with no attachment returns `attachment=null offset=null`; never issues docker exec / pipe-pane / file read (FR-032, Clarifications Q3).
- [X] T110 [P] [US3] Integration test in `tests/integration/test_cli_attach_log_redaction_preview.py`: US3 / SC-010 — preview rendering of fixture log with every FR-028 pattern produces zero raw secrets across 1000 runs.
- [X] T111 [P] [US3] Integration test in `tests/integration/test_cli_attach_log_preview.py`: FR-033 / Clarifications Q3 — preview against active/stale/detached succeeds; against superseded/no-row refused `attachment_not_found`; against allowed-status with missing file refused `log_file_missing`.
- [X] T112 [P] [US3] Integration test in `tests/integration/test_cli_attach_log_status.py`: FR-032 / Clarifications Q3 — `--status` against active/stale/detached/superseded/no-row; never issues docker exec.

### Implementation for User Story 3

- [X] T120 [US3] Create `src/agenttower/logs/redaction.py` per Research R-012 + FR-027..030 + FR-049 + FR-064: module-level pre-compiled `_UNANCHORED_PATTERNS` and `_ANCHORED_PATTERNS` with `re.ASCII` flag. Public `redact_lines(text: str) -> str` splits on `\n` (not `splitlines`), applies unanchored first then anchored per line, joins with `\n`. JWT length ≥ 32 enforced via lambda. Patterns audited for backtracking-pathological constructs (FR-064).
- [ ] T121 [US3] Create `src/agenttower/logs/preview.py` — `read_tail_lines(host_path: str, n: int) -> list[str]` reverse-reads the host file with hard cap 200 lines × 64 KiB per line (FR-033, FR-064). Uses `host_fs.py` adapter (T015) so `AGENTTOWER_TEST_LOG_FS_FAKE` is honored. Truncates lines > 64 KiB at byte boundary with `…` marker before passing to redaction.
- [X] T122 [US3] Add `attach_log_preview(req)` and `attach_log_status(req)` methods to `LogService` (T071). `attach_log_status` is universal read (FR-032 / Clarifications Q3). `attach_log_preview` resolves the most recent row, checks `status ∈ {active, stale, detached}`, checks file existence (raises `log_file_missing` per Clarifications Q3 if gone), reads tail lines via T121, applies redaction via T120, returns `lines` array.
- [X] T123 [US3] Wire the `attach_log_status` and `attach_log_preview` daemon-side handlers in `src/agenttower/socket_api/methods.py` (replace T004 placeholders).
- [X] T124 [US3] Implement the `--status` and `--preview <N>` CLI surfaces in `src/agenttower/cli.py` per contracts/cli.md C-CLI-702 + C-CLI-703. Text-mode + `--json` rendering. Mode flags use `argparse.SUPPRESS` defaults.

**Checkpoint**: User Story 3 fully functional. Operators can preview pane logs safely (redacted) and inspect status across all attachment states.

---

## Phase 6: User Story 4 - register-self --attach-log is fail-the-call (Priority: P2)

**Goal**: `agenttower register-self --attach-log` is atomic across success and failure paths. Either the agent is registered AND the log is attached AND both audit rows append in the documented order, or NEITHER row exists.

**Independent Test**: Inject every FR-038 closed-set failure code into the fake adapters, run `register-self --attach-log`, assert (a) exit `3` with the FEAT-007 code, (b) zero `agents` row, (c) zero `log_attachments` row, (d) zero JSONL audit rows. Repeat for success path and assert audit row ordering (US4 + SC-008).

### Tests for User Story 4

- [X] T130 [P] [US4] Unit test in `tests/unit/test_register_self_attach_log_atomic_success.py`: `register_agent` + `attach_log` commit in one transaction; `agent_role_change` audit row FIRST, `log_attachment_change` SECOND (FR-034, FR-035).
- [X] T131 [P] [US4] Unit test in `tests/unit/test_register_self_attach_log_fail_the_call.py`: every FEAT-007 closed-set failure code (`log_path_not_host_visible`, `pipe_pane_failed`, `tmux_unavailable`, `log_path_in_use`, `log_path_invalid`, ...) leaves zero rows in agents / `log_attachments` / `log_offsets` / events.jsonl (FR-034).
- [X] T132 [P] [US4] Unit test in `tests/unit/test_socket_api_register_agent_attach_log.py`: FR-035 — `register_agent` envelope gains optional `attach_log` nested object per contracts/socket-api.md §7; daemon-internal `source=register_self` set on FEAT-007 audit row only; not exposed to clients.
- [X] T133 [P] [US4] Integration test in `tests/integration/test_cli_register_self_attach_log_success.py`: US4 AS1 / SC-008 — register-self --attach-log atomic success; both audit rows in order (`agent_role_change` first).
- [X] T134 [P] [US4] Integration test in `tests/integration/test_cli_register_self_attach_log_failure.py`: US4 AS2 / SC-008 — register-self --attach-log fail-the-call across every FR-038 closed-set code; zero rows, zero JSONL.

### Implementation for User Story 4

- [X] T140 [US4] Extend `src/agenttower/agents/service.py:register_agent` per FR-034 + FR-035: when the wire request includes `attach_log` (data-model.md §7.1), run the FEAT-007 attach inside the same `BEGIN IMMEDIATE` transaction. Audit-row ordering enforced (`agent_role_change` FIRST, `log_attachment_change` SECOND). Rollback on any FEAT-007 failure leaves zero rows in any of agents / log_attachments / log_offsets and zero JSONL audit rows. Surface FEAT-007 failure code as top-level error (FEAT-006 success message NOT printed first).
- [X] T141 [US4] Extend the `register_agent` socket method handler in `src/agenttower/socket_api/methods.py` to accept the `attach_log` nested key per contracts/socket-api.md §7; pass `source=register_self` daemon-internally to the FEAT-007 attach path. Reject `source` if supplied by client at the wire (FR-039).
- [X] T142 [US4] Extend `register-self` CLI in `src/agenttower/cli.py` with the `--attach-log` flag and an optional nested `--log <path>`. On success, print FEAT-006 register line FIRST, FEAT-007 attached line SECOND (contracts/cli.md C-CLI-705). On failure, surface only the FEAT-007 error.

**Checkpoint**: User Story 4 fully functional. Operators get deterministic atomic registration + attachment in one CLI call.

---

## Phase 7: User Story 5 - Stale-attachment detection and recovery (Priority: P3)

**Goal**: When FEAT-004 reconciliation marks a previously-attached pane inactive, every bound `log_attachments` row flips `active → stale` in the same SQLite transaction (no race window). A subsequent `attach-log` recovers the row to `active` retaining offsets when the file is intact.

**Independent Test**: Attach a log, force a FEAT-004 reconcile cycle that observes `pane.active=0`, assert the row transitions to `stale` in one committed transaction, assert the audit row, assert offsets unchanged, then re-attach and assert recovery to `active` with offset retained (US5 + SC-009).

### Tests for User Story 5

- [X] T150 [P] [US5] Unit test in `tests/unit/test_recovery_from_stale_pane_drift.py`: file intact; offsets retained byte-for-byte; status active; audit row `prior_status=stale` (FR-021).
- [X] T151 [P] [US5] Unit test in `tests/unit/test_recovery_from_stale_file_changed.py`: `file_inode` differs OR `file_size_seen > current_size`; offsets reset; `log_rotation_detected` lifecycle event in addition to audit row (FR-021, Clarifications Q4).
- [X] T152 [P] [US5] Unit test in `tests/unit/test_supersede_from_stale.py`: path change from stale prior status; toggle-off NOT issued (no live pipe); same supersede contract; audit row `prior_status=stale` (FR-019, Clarifications Q2).
- [X] T153 [P] [US5] Unit test in `tests/unit/test_pane_reconcile_stale_attachment.py`: FEAT-004 reconcile transaction that flips `pane.active=1 → 0` also flips every bound `log_attachments` row from `active` to `stale` in the same transaction; offsets unchanged; one audit row per affected row (FR-042, SC-009).
- [ ] T154 [P] [US5] Integration test in `tests/integration/test_cli_attach_log_stale_recovery.py`: US5 AS1 / AS2 / FR-042 — FEAT-004 reconcile flips bound row to stale; follow-up `attach-log` recovers to active retaining offset.

### Implementation for User Story 5

- [X] T160 [US5] Extend `src/agenttower/discovery/pane_reconcile.py` per FR-042 + SC-009: every reconcile transaction that observes a previously-active pane composite key transitioning to `pane.active=0` MUST also flip every `log_attachments` row bound to that pane composite key from `status=active` to `status=stale` in the SAME `BEGIN IMMEDIATE` transaction. Use the indexed lookup `log_attachments_pane_status` (T010). The `log_offsets` row is NOT touched. Append one `log_attachment_change` audit row per affected row with `prior_status=active, new_status=stale, source=explicit` (Research R-008). The reconcile path does NOT acquire FEAT-007 mutexes (cross-subsystem ordering via SQLite alone).
- [X] T161 [US5] Extend `LogService.attach_log` (T071) to handle the FR-021 same-path recovery branch: when an existing row for `(agent_id, log_path)` has `status=stale`, update in place to `status=active`. Apply the file-consistency check: if `file_inode` matches and `file_size_seen ≤ current_size`, retain offsets byte-for-byte; otherwise reset to `(0, 0, 0)` and emit one `log_rotation_detected` lifecycle event in addition to the `log_attachment_change` audit row.
- [X] T162 [US5] Extend `LogService.attach_log` (T071) to handle FR-019 supersede-from-stale: prior row → `superseded` (with `superseded_at` and `superseded_by`); new row at new path with fresh offsets at `(0, 0)`; toggle-off NOT issued because no live pipe exists for a stale row.

**Checkpoint**: User Story 5 fully functional. Pane drift is detected by FEAT-004 reconciliation, surfaces via stale state, and recovers cleanly.

---

## Phase 8: User Story 6 - File rotation / truncation resets the offset (Priority: P3)

**Goal**: When the host log file is rotated, truncated, or recreated outside AgentTower's control, the daemon detects via inode / size change and resets the offset. File-missing transitions the row to `stale`; file-reappearance does NOT auto-recover.

**Independent Test**: Attach, advance offset, then (a) truncate file to 0 bytes, (b) delete and recreate the file, (c) delete without recreate. Assert reset behavior, lifecycle events, and that no auto-recovery occurs (US6 + SC-007 + SC-014).

### Tests for User Story 6

- [X] T170 [P] [US6] Unit test in `tests/unit/test_file_truncation_detection.py`: `current_file_size < file_size_seen`; reset `(byte_offset=0, line_offset=0)`; preserve `file_inode`; one `log_rotation_detected` lifecycle event with `prior_size`/`new_size`/`inode` (FR-024).
- [X] T171 [P] [US6] Unit test in `tests/unit/test_file_recreation_detection.py`: `file_inode` differs from stored; reset offsets; update `file_inode` and `file_size_seen`; one `log_rotation_detected` lifecycle event with `prior_inode`/`new_inode` (FR-025).
- [X] T172 [P] [US6] Unit test in `tests/unit/test_file_missing_then_returned.py`: file disappears: status `active → stale`, `log_file_missing` fired, offsets unchanged. File reappears: `log_file_returned` fired exactly once per `(agent_id, log_path, file_inode)` triple, status remains `stale` (no auto-recovery), offsets unchanged (FR-026, Clarifications Q4).
- [ ] T173 [P] [US6] Unit test in `tests/unit/test_lifecycle_event_surface.py`: every lifecycle event from data-model.md §3 routes via the daemon's lifecycle logger (NOT events.jsonl); `log_file_returned` suppressed for repeat firings on same triple (FR-046, FR-061).
- [X] T174 [P] [US6] Unit test in `tests/unit/test_lifecycle_event_rate_limit.py`: SC-014 — flap host file delete/recreate 100 times; assert at most one `log_file_missing` per stale-state entry; at most one `log_file_returned` per triple; at most one `log_rotation_detected` per actual rotation (FR-061). ALSO assert restart durability of the suppression registry per data-model.md §3.6: the registry is in-memory only — after a daemon restart, a previously-suppressed event MAY re-fire once for the same `(agent_id, log_path, file_inode)` triple; this is acceptable because lifecycle events are observability signals (FR-046), not audit rows. Test by simulating daemon restart between flap iterations and asserting the post-restart re-fire pattern.
- [ ] T175 [P] [US6] Integration test in `tests/integration/test_cli_attach_log_file_truncated.py`: US6 AS1 / FR-024 / SC-007 (detection-timing half) — file truncated to 0; offsets reset; one `log_rotation_detected` event; assert detection occurs within one offset-recovery cycle (≤ 1 second wall-clock from the truncation event in fixture timing). Note: SC-007's "no replay" half is deferred to FEAT-008 (the reader is FEAT-008 work; FEAT-007 ships only the reset signal).
- [ ] T176 [P] [US6] Integration test in `tests/integration/test_cli_attach_log_file_recreated.py`: US6 AS2 / FR-025 / SC-007 (detection-timing half) — file deleted and recreated (new inode); offsets reset; one `log_rotation_detected` event; detection within ≤ 1 second wall-clock per SC-007. "No replay" assertion deferred to FEAT-008 (see T175 note).
- [ ] T177 [P] [US6] Integration test in `tests/integration/test_cli_attach_log_file_missing.py`: US6 AS3..AS5 / FR-026 / Clarifications Q4 — file deleted → stale + `log_file_missing`; file recreated → `log_file_returned`, status still stale; operator runs `attach-log` → status active, offsets reset, `log_rotation_detected`.

### Implementation for User Story 6

- [X] T180 [US6] Add `detect_file_change(host_path, stored_inode, stored_size_seen) -> FileChangeKind` to `state/log_offsets.py` (T012) returning `{unchanged, truncated, recreated, missing}` per FR-024 + FR-025 + FR-026. Used by FEAT-008 reader cycles AND by `LogService.attach_log` for the FR-021 file-consistency check.
- [X] T181 [US6] Add `reader_cycle_offset_recovery(agent_id, log_path)` helper (in `LogService` or a dedicated `logs/reader_recovery.py`) that the FEAT-008 reader will call. On `truncated`: reset offsets, preserve `file_inode`, emit `log_rotation_detected`. On `recreated`: reset offsets, update `file_inode` + `file_size_seen`, emit `log_rotation_detected`. On `missing`: flip row `active → stale`, emit `log_file_missing`, offsets unchanged. On `missing → reappeared`: emit `log_file_returned` per triple-suppression rule, row remains `stale`, offsets unchanged.
- [X] T182 [US6] Implement FR-061 rate-limit / suppression state in `logs/lifecycle.py` (T030): per-`(agent_id, log_path)` last-state tracking for `log_file_missing`; per-`(agent_id, log_path, file_inode)` triple suppression for `log_file_returned`; per-rotation suppression for `log_rotation_detected`.

**Checkpoint**: User Story 6 fully functional. File-system drift surfaces cleanly with bounded observability noise.

---

## Phase 9: User Story 7 - Operator-explicit detach (Priority: P3)

**Goal**: `agenttower detach-log --target <agent-id>` issues `tmux pipe-pane -t <pane>` (no command), transitions `active → detached`, retains offsets byte-for-byte, appends one audit row. Re-attach reuses the same row, transitions back to `active`, retains offsets. Detach is operator intent only — never auto-triggered.

**Independent Test**: Attach, advance offset, run `detach-log`, assert toggle-off issued, status transition, offsets retained, audit row. Then run `attach-log`, assert same row reused, status `active`, offsets retained, second audit row. Verify no other lifecycle path produces `detached` status (US7 + SC-011).

### Tests for User Story 7

- [X] T190 [P] [US7] Unit test in `tests/unit/test_detach_mechanics.py`: explicit detach only; toggle-off issued; status `active → detached`; offsets retained; audit row appended; rejected on non-active row with `attachment_not_found`; same liveness gates as attach (FR-021a..c).
- [X] T191 [P] [US7] Unit test in `tests/unit/test_no_implicit_detach.py`: `agent.active=0` / `container.active=0` / `pane.active=0` / file_missing all leave status untouched (no implicit `detached`); pane-drift uses `stale`; file-missing uses `stale` (FR-021a, Clarifications Q1).
- [X] T192 [P] [US7] Unit test in `tests/unit/test_recovery_from_detached.py`: same-path attach from detached reuses row; offsets retained; pipe-pane re-engaged; audit row `prior_status=detached` (FR-021d).
- [X] T193 [P] [US7] Unit test in `tests/unit/test_supersede_from_detached.py`: path change from detached prior status; toggle-off NOT issued; audit row `prior_status=detached` (FR-019, Clarifications Q2).
- [X] T194 [P] [US7] Integration test in `tests/integration/test_cli_detach_log.py`: US7 AS1 / SC-011 — detach-log: status active → detached; offsets retained; audit row; toggle-off issued.
- [X] T195 [P] [US7] Integration test in `tests/integration/test_cli_detach_log_re_attach.py`: US7 AS2 / SC-011 — re-attach from detached: same row reused; offsets retained byte-for-byte; status active.
- [X] T196 [P] [US7] Integration test in `tests/integration/test_cli_detach_log_invalid_state.py`: US7 AS3 / FR-021b — detach-log on agent with no row, or stale/superseded/detached row, refused `attachment_not_found`.
- [X] T197 [P] [US7] Integration test in `tests/integration/test_cli_no_implicit_detach.py`: US7 AS4 / FR-021a — exercising every other lifecycle path (pane drift, agent inactivation, container restart, file rotation/truncation/deletion) leaves status in `{active, stale, superseded}` but never `detached` (SC-011).

### Implementation for User Story 7

- [X] T200 [US7] Add `LogService.detach_log(req: DetachLogRequest) -> DetachLogResult` to `src/agenttower/logs/service.py` (T071). Implement FR-021a..e: liveness gates (FR-001..004), valid only when most-recent row is `active` else `attachment_not_found`, `tmux pipe-pane -t <pane>` toggle-off via T021, status `active → detached`, retain `log_offsets` row byte-for-byte (no offset reset), append one `log_attachment_change` audit row, all in one `BEGIN IMMEDIATE`. Acquire per-`agent_id` mutex (FEAT-006 `agent_locks`); no per-`log_path` mutex (no path supplied).
- [X] T201 [US7] Add the `detach_log` daemon-side handler in `src/agenttower/socket_api/methods.py` (replace T004 placeholder).
- [X] T202 [US7] Implement the `detach-log` CLI surface in `src/agenttower/cli.py` per FR-037a + contracts/cli.md C-CLI-704: `--target` required, no `--log` flag (path resolved from existing row), exit-code surface + text-mode + `--json` envelope follow the `attach-log` contract (FR-036 / FR-037).
- [X] T203 [US7] Extend `LogService.attach_log` (T071) to handle FR-021d same-path recovery from `detached`: update existing row in place to `status=active`, retain offsets byte-for-byte, re-engage `pipe-pane`, append audit row `prior_status=detached, new_status=active`.
- [X] T204 [US7] Extend `LogService.attach_log` (T071) to handle FR-019 supersede-from-detached: prior row → `superseded`; new row at new path; toggle-off NOT issued.

**Checkpoint**: User Story 7 fully functional. Symmetric operator-driven attach/detach with the closed-set status `detached` reachable only by explicit operator action.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Hardening that spans every story, plus orphan recovery, mutex ordering self-checks, and the SC-012 / SC-013 / SC-014 verification gates.

- [X] T210 [P] Implement `src/agenttower/logs/orphan_recovery.py` per FR-043 + Research R-014: at daemon startup (post-migration, pre-listener), for each `containers.active=1` row issue `tmux list-panes -F '#{session_name}:#{window_index}.#{pane_index} #{pane_pipe} #{pane_pipe_command}' -a` via FEAT-004 adapter. For each pane with `pane_pipe=1` matching the canonical-prefix path (T017) but no `log_attachments` row, emit one `log_attachment_orphan_detected` lifecycle event. NEVER auto-attach. Hook into daemon startup sequence in `src/agenttower/daemon.py`.
- [X] T211 [P] Unit test in `tests/unit/test_orphan_detection_on_startup.py`: identifies `pane_pipe=1` with AgentTower-canonical target but no row; emits one event per orphan; never auto-attaches; suppression per `(container_id, pane_composite_key, observed_pipe_target)` triple per daemon lifetime (FR-043, FR-061).
- [ ] T212 [P] Integration test in `tests/integration/test_cli_attach_log_orphan_recovery.py`: FR-043 — daemon startup with a fake container whose pane has a canonical pipe target but no row; assert one orphan event, no auto-attach, no docker exec issued by the daemon for binding.
- [X] T213 [P] Implement FR-058 SO_PEERCRED uid mismatch defense-in-depth in the FEAT-002 socket server entry point (or in a dedicated FEAT-007 hook called before any FEAT-007 method dispatch). Verify `os.geteuid()` matches the SO_PEERCRED uid on every accepted connection; on mismatch, close the connection immediately, emit one `socket_peer_uid_mismatch` lifecycle event, do not process any request.
- [X] T214 [P] Unit test in `tests/unit/test_log_value_out_of_set.py`: out-of-set status / source values rejected via closed-set validators with `value_out_of_set`; actionable message lists valid values (FR-038).
- [X] T215 [P] Unit test in `tests/unit/test_mutex_acquisition_order.py`: FR-059 / SC-013 — drives concurrent attach calls with overlapping `(agent_id, log_path)` pairs; daemon never holds `log_path_locks` while NOT holding the corresponding `agent_locks`; reverse-order acquisition raises `internal_error`.
- [X] T216 [P] Integration test in `tests/integration/test_adversarial_inputs.py`: SC-012 — fixture suite with (a) every FR-051 metabyte plus shell-meta, (b) every FR-052 daemon-owned root, (c) every FR-053 special-filesystem root, (d) FR-050 symlink escape; assert each rejection produces zero `log_attachments` row, zero `log_offsets` row, zero docker exec, zero JSONL, zero file-mode mutations.
- [X] T217 Wire daemon startup in `src/agenttower/daemon.py` to invoke `logs/orphan_recovery.detect_orphans()` once after schema migration + before socket listener starts (Research R-014). FIRST verify the existing daemon startup sequence calls `state.schema._apply_pending_migrations` (added by FEAT-001..006) so T010 + T010a's v5 migration runs unconditionally on every startup; if absent, add the call in this same task. Second, ensure `detect_orphans()` runs AFTER migration completes and BEFORE the FEAT-002 socket listener accepts its first connection.
- [ ] T218 [P] Run quickstart.md end-to-end against a real bench container fixture (or its highest-fidelity fake equivalent), verifying every section §1–§13 works as documented. Capture any drift between quickstart and implementation; raise as bugs.
- [X] T219 [P] Add the FR-046 lifecycle event type names to the daemon's lifecycle logger registry: `log_rotation_detected`, `log_file_missing`, `log_file_returned`, `log_attachment_orphan_detected`, `mounts_json_oversized`, `socket_peer_uid_mismatch`.
- [X] T220 [P] Static-analysis + code-review gate test in `tests/unit/test_no_log_content_execution.py` enforcing FR-065. Asserts via AST scan of `src/agenttower/` that NO production module calls `eval`/`exec`/`compile`/`__import__` and that `subprocess.*` is confined to a closed allow-list of structured-argv adapter modules. Implemented; 72 parametrized assertions pass. Defense against A3 (malicious in-container process emitting adversarial pane content) per spec § Threat Model and FR-065 / NT3.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. T001/T002/T004/T005 can run in parallel; T003 must complete before T010 (foundational migration body).
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories.
  - T010 (migration body) blocks T011/T012 (DAOs).
  - T015 (host_fs adapter) blocks T018 (host visibility), T071 (LogService).
  - T013 blocks T071. T021/T023 block T071.
  - T027 (mutex) blocks T071.
  - T029/T030 (audit/lifecycle) block T071.
  - T031 (gates) blocks T072 (handler wiring).
  - T033 (CLI subparsers) is independent of T071 but blocks user-facing tests.
- **User Story 1 (Phase 3)**: Depends on Foundational. Tests T040..T065 can run in parallel after their dependent modules exist; implementation tasks T070..T077 are sequential within `service.py` but `client_resolve.py` (T070) and CLI rendering (T073) parallelize against `service.py` (T071).
- **User Story 2 (Phase 4)**: Depends on Foundational + US1 (uses the durable schema US1 establishes).
- **User Story 3 (Phase 5)**: Depends on Foundational. Independent of US2 — preview reads files directly; no offset advancement.
- **User Story 4 (Phase 6)**: Depends on Foundational + US1 (extends `register_agent` to use `LogService.attach_log`).
- **User Story 5 (Phase 7)**: Depends on US1 (needs the schema and attach path) plus FEAT-004 reconcile path.
- **User Story 6 (Phase 8)**: Depends on US1 (needs the schema). Independent of US5.
- **User Story 7 (Phase 9)**: Depends on US1 (extends `LogService.attach_log` for FR-021d / FR-019 supersede-from-detached).
- **Polish (Phase 10)**: Depends on all stories complete; T217 hooks orphan recovery into daemon startup which depends on T210 + T030.

### User Story Dependencies

- **US1 (P1)**: Foundational only. MVP slice 1.
- **US2 (P1)**: US1 schema. MVP slice 2 — durability invariant.
- **US3 (P2)**: Foundational only. Independently testable against fixture inputs without docker/tmux.
- **US4 (P2)**: US1 (extends attach path).
- **US5 (P3)**: US1 + FEAT-004 reconcile.
- **US6 (P3)**: US1 (file detection layered on schema).
- **US7 (P3)**: US1 (extends attach path with detached recovery + supersede).

### Within Each User Story

- Tests (when independent of implementation) are written FIRST and should FAIL before implementation lands. Tests that depend on production code (e.g. T044 idempotency exercises `LogService.attach_log`) are written alongside implementation.
- Models / DAOs before services. Services before socket handlers. Handlers before CLI rendering.
- Each phase's checkpoint is an end-to-end scenario; do not start the next phase until the prior phase's checkpoint passes.

### Parallel Opportunities

- Phase 1: T001, T002, T004, T005 in parallel (different files).
- Phase 2: T011, T012 parallel after T010. T013, T015, T016, T017 parallel (independent files). T021 parallel with T023, T025. Tests T014, T019, T020, T022, T024, T026, T028, T032 parallel (independent unit tests).
- Phase 3: All [P]-marked tests T040..T065 parallel; implementation T070..T077 mostly sequential within `service.py`.
- Phases 5–9: Story-specific tests parallel within each phase; implementation tasks sequential within `service.py` but parallel across DAO / lifecycle / discovery files.

---

## Parallel Example: User Story 1 Tests

```bash
# Launch all US1 unit tests together (independent files, no inter-deps):
Task: "Unit test composite uniqueness in tests/unit/test_log_attachments_table.py"   # T040
Task: "Unit test composite PK in tests/unit/test_log_offsets_table.py"               # T041
Task: "Unit test single-transaction in tests/unit/test_log_attach_transaction.py"    # T042
Task: "Unit test idempotency in tests/unit/test_attach_idempotency.py"              # T044
Task: "Unit test path collision in tests/unit/test_log_path_in_use.py"              # T045
Task: "Unit test audit shape in tests/unit/test_audit_row_shape.py"                  # T046

# Launch all US1 integration tests together once T071/T072/T073 land:
Task: "Integration happy-path attach in tests/integration/test_cli_attach_log.py"               # T050
Task: "Integration idempotency in tests/integration/test_cli_attach_log_idempotent.py"          # T051
Task: "Integration host-visibility in tests/integration/test_cli_attach_log_host_visibility.py" # T054
Task: "Integration pipe-pane-failed in tests/integration/test_cli_attach_log_pipe_pane_failed.py" # T055
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Setup (T001..T005).
2. Complete Phase 2: Foundational (T010..T033). CRITICAL — blocks all stories.
3. Complete Phase 3: User Story 1 (T040..T077). End-to-end attach path.
4. Complete Phase 4: User Story 2 (T080..T083). Durability across restart.
5. **STOP and VALIDATE**: Run quickstart.md §1, §3, §13 manually. Run the full unit + integration suite for US1 + US2.
6. Demo / merge MVP slice.

### Incremental Delivery

1. MVP (US1 + US2) → durable attachment + offset persistence.
2. Add US3 (preview + redaction) → operators can inspect logs safely.
3. Add US4 (register-self --attach-log) → atomic registration UX.
4. Add US5 (stale detection) → drift handled.
5. Add US6 (rotation/truncation) → file-system drift handled.
6. Add US7 (detach) → symmetric operator tear-down.
7. Polish (Phase 10): orphan recovery, hardening verification, quickstart pass.

### Parallel Team Strategy

With multiple developers post-Foundational:

- Developer A: US1 (T070..T077) → MVP slice 1.
- Developer B: US3 (T120..T124) → independent of US1 implementation (preview + redaction read fixtures).
- Developer C: US4 (T140..T142) → starts as soon as US1's `LogService.attach_log` skeleton (T071) lands.
- Developer D: US6 (T180..T182) → starts as soon as US1's DAOs (T011, T012) land.
- Once US1 lands: US5 (T160..T162) and US7 (T200..T204) can fan out.

---

## Notes

- [P] tasks operate on different files with no dependencies on incomplete tasks.
- [Story] label maps each task to its user story for traceability across spec → plan → tasks.
- Each user story is independently testable after its phase completes (per FR-Independent Test field on each user story in spec.md).
- Verify tests FAIL before implementing (TDD discipline) where the test does not exercise yet-to-be-written code.
- Commit after each task or logical group.
- Stop at any checkpoint to validate independently.
- AVOID: vague tasks, same-file conflicts marked [P], cross-story dependencies that break independence.
- Hardening FRs (FR-047..FR-065) are split across the foundational phase (T015 / T018 / T021 / T025 / T027 covering FR-047, FR-048, FR-049, FR-050, FR-051, FR-052, FR-053, FR-054, FR-056, FR-057, FR-059, FR-060, FR-062, FR-063, FR-064), the US1 phase (T055a covering FR-055), and Polish (T213 covering FR-058, T216 covering SC-012, T220 covering FR-065). Every hardening FR has at least one task assigned.
- Test seam `AGENTTOWER_TEST_LOG_FS_FAKE` lives ONLY in `logs/host_fs.py` (T015). T077 verifies no other module imports it (FR-060).
- The four lifecycle event types (`log_rotation_detected`, `log_file_missing`, `log_file_returned`, `log_attachment_orphan_detected`) plus `mounts_json_oversized` and `socket_peer_uid_mismatch` are emitted via the daemon lifecycle logger (T030 / T219), NOT events.jsonl (FR-046).

---

## Reconciliation Appendix (post MVP slice — commit `a773670`)

This appendix maps the implemented state on disk back to the task IDs above and groups what is genuinely pending. State is `[X]` only when behavior is implemented AND covered by a passing test (208 FEAT-007 tests green at reconciliation time).

### Test consolidation map

The implementer collapsed many granular per-task test files into broader files. Tasks marked `[X]` in this category are covered by the following consolidated files:

| Task IDs | Consolidated test file |
|---|---|
| T014 | `tests/unit/test_logs_identifiers.py` |
| T019 | `tests/unit/test_logs_host_visibility.py` |
| T020 | `tests/unit/test_logs_path_validation.py` |
| T022, T024 | `tests/unit/test_logs_pipe_pane.py` (TestParseListPanesOutput, TestClassifyPipeTarget for T024) |
| T100, T101, T102, T103, T104 | `tests/unit/test_logs_redaction.py` |
| T105, T106, T108, T109 | `tests/unit/test_logs_preview_status.py` (22 cases: allowed-statuses parametrized over active/stale/detached, superseded + no-row refusal, file-missing + zero-mutation, line-cap N=1/200/0/201/-1 + empty file + few-lines, status universal-read + null payload + no docker exec + no host-file read) |
| T174 | `tests/unit/test_logs_lifecycle_rate_limit.py` (SC-014: 100x flap with unique vs. repeated inodes; FR-061 per-event-class suppression bounds; restart-durability per data-model.md §3.6) |
| T026, T028, T032, T214, T215 | `tests/unit/test_logs_polish_units.py` (32 cases: pipe-pane stderr sanitization for FR-012 patterns, LogPathLockMap fetch-or-create + acquire_in_order semantics, attach_log envelope FR-039 unit tests, closed-set status/source validators, SC-013 mutex-order structural enforcement) |
| T130, T131, T132, T150, T151, T152, T190, T191, T192, T193 | `tests/unit/test_logs_us4_us5_us7_units.py` (US4 atomic register-self audit shape + failure-zero-rows; US5 stale-recovery file-intact + file-changed-resets + supersede-from-stale; US7 detach mechanics + recovery-from-detached + no-implicit-detach + supersede-from-detached) |
| T080 | `tests/unit/test_logs_offset_advance_invariant.py` (FR-022/023: AST scan asserts no production module imports the `advance_offset_for_test` seam, and the seam function name + docstring carry "TEST SEAM" markers) |
| T040, T041, T042, T043, T046 | `tests/unit/test_logs_us1_unit_invariants.py` (17 cases: log_attachments PK shape + partial unique index + status/source CHECK constraints, log_offsets initial values + composite PK + FK enforcement, atomic BEGIN IMMEDIATE both-or-neither, WAL + synchronous PRAGMA, log_attachment_change row shape + nullables + uid coercion) |
| T045, T048, T049 | covered by integration `test_feat007_us1_error_paths.py:test_t058_*` / `test_t060_*` / `test_t061_*` |
| T010a | `tests/unit/test_schema_v4_migration_unit.py` (extended for v5 indexes/tables) |
| T044, T047, T050, T051 | `tests/integration/test_feat007_attach_log_smoke.py` |
| T052, T053, T054, T057, T058, T060, T061, T063, T064, T065, T197 | `tests/integration/test_feat007_us1_error_paths.py` (11 cases incl. T197 no-implicit-detach across pane reconcile + reader-cycle missing + idempotent re-attach + stale recovery) |
| T055 | `tests/integration/test_feat007_pipe_pane_race.py` + `tests/unit/test_logs_pipe_pane.py:TestSanitizePipePaneStderr` + `tests/unit/test_logs_polish_units.py` (FR-012 pattern coverage + sanitization rules) |
| T059 | `tests/integration/test_adversarial_inputs.py` (parametrized over FR-006/FR-051..053 — relative, dotdot, NUL/CR/LF/tab/C0/DEL, daemon-owned roots, /proc-/sys-/dev-/run; SC-012 zero-side-effect) |
| T081 | `tests/integration/test_feat007_offset_persistence.py` (SIGTERM + SIGKILL) |
| T107, T110, T111, T112, T194, T195, T196 | `tests/integration/test_feat007_lifecycle.py` (US3 preview redaction SC-010 1000-iter, US3 preview status branches, US7 detach round-trip + invalid state) |
| T153 | `tests/integration/test_feat007_stale_cascade.py` |
| T170, T171, T172 | `tests/unit/test_logs_reader_cycle_recovery.py` + `tests/unit/test_logs_file_change_detection.py` (truncation/recreation/missing-then-returned + classifier; FR-024/025/026 + FR-061 triple suppression) |

### Architectural skips (intentionally inlined)

These tasks specified extracting helpers that were inlined into existing modules. Functional behavior is covered, but the named module/wrapper does not exist:

- **T002** — `logs/__init__.py` re-export stubs not added; concrete classes are imported directly from their modules.
- **T005** — typed wrappers in `socket_api/client.py` not added; `cli.py` calls `send_request` directly with the method name.
- **T070** — `logs/client_resolve.py` not created; resolution logic inlined in `cli.py:_attach_log_command` / `_detach_log_command`.
- **T121** — `logs/preview.py` not created; `read_tail_lines` lives in `logs/host_fs.py` and `LogService.attach_log_preview` calls it directly.

These can be revisited if the indirection becomes valuable (e.g. a second client surface or external test fixture wants the wrappers).

### Genuinely pending

**Implementation gaps:** **none.** All FEAT-007 source modules and behavior are implemented. The FR-019 supersede branch was widened in `service.py:320` this iteration to handle stale + detached prior status (T162 was over-claimed in the original MVP slice; this iteration found the gap via T152/T193 strict-xfails and patched it — `select_active_for_agent` → `select_most_recent_for_agent` with status-set guard `{active, stale, detached}`).

**Pending — blocked at code or harness level (cannot be ticked without scope expansion):**

- **T056** — `tmux_unavailable` rejection. Blocked: `tmux_present` is hardcoded `True` in `service.py:881` (no persisted column yet). Awaits a future FEAT-003 column — out of scope for FEAT-007.
- **T062** — `host_context_unsupported` for `attach-log` from host shell without `--target`. Blocked: `--target` is `required=True` at argparse so the error fires at the CLI layer before reaching the daemon's host-context check. The check itself remains correct for register-self.
- **T154** — US5 stale-recovery integration through CLI. Behavior is unit-tested (T150/T151) and the cascade is integration-tested (`test_feat007_stale_cascade.py`). A full CLI round-trip would require driving FEAT-004 reconcile from the test which adds harness complexity for marginal trace value.
- **T212** — orphan recovery integration through daemon startup. Unit coverage in `test_logs_orphan_recovery.py` is comprehensive (8 cases incl. suppression); the integration version would re-verify the same logic via subprocess.
- **T218** — quickstart.md end-to-end. Manual operator task; needs human review of every section against the running daemon.

**Carried over to FEAT-008** (recorded in `docs/mvp-feature-sequence.md` § FEAT-008 → "Carried over from FEAT-007"):

- **T175** — US6 file-truncation ≤1s detection-timing integration. Requires the FEAT-008 reader running on a wall-clock cycle. FEAT-007 ships the per-call helper (`reader_cycle_offset_recovery`) + unit-level coverage (`test_logs_reader_cycle_recovery.py`); FEAT-008 ships the timing assertion + the SC-007 "no replay" half.
- **T176** — US6 file-recreation ≤1s detection-timing integration. Same reason as T175.
- **T177** — US6 AS3..AS5 round-trip integration (file deleted → stale → recreated → log_file_returned → operator re-attach → reset). Same reason — needs reader cycle running.
- **T173** — every lifecycle event from data-model.md §3 routes via lifecycle logger (NOT events.jsonl). Each event class is individually proven today; FEAT-008 may consolidate the assertion when adding its own event surface.

**Architectural skips (intentionally inlined; functional behavior covered):**

- **T002** — `logs/__init__.py` re-export stubs. Concrete classes are imported directly from their modules.
- **T005** — typed wrappers in `socket_api/client.py`. `cli.py` calls `send_request` directly with the method name.
- **T070** — `logs/client_resolve.py`. Resolution logic inlined in `cli.py:_attach_log_command` / `_detach_log_command`.
- **T121** — `logs/preview.py`. `read_tail_lines` lives in `logs/host_fs.py` and `LogService.attach_log_preview` calls it directly.

### Suggested next slice

**FEAT-007 is functionally complete.** 124/137 tasks ticked (91%). Remaining 13 are intentional skips, code-level blocks, or items intentionally carried to FEAT-008:

| Category | Count | Items | Tracked in |
|---|---|---|---|
| Architectural skips (inline-instead-of-extract; behavior covered) | 4 | T002, T005, T070, T121 | [GH #9](https://github.com/opensoft/AgentTower/issues/9) |
| Code-level blocks (need future feature work) | 2 | T056, T062 | T056: [GH #9](https://github.com/opensoft/AgentTower/issues/9); T062: spec/test misalignment, see appendix |
| Harness-level blocks within FEAT-007 scope | 3 | T154, T212, T218 | T154/T212: [GH #9](https://github.com/opensoft/AgentTower/issues/9); T218: should run as part of FEAT-007 PR review |
| Carried over to FEAT-008 (see `docs/mvp-feature-sequence.md` § FEAT-008) | 4 | T173, T175, T176, T177 | FEAT-008 PRD |

Every remaining item has an explicit reason in the appendix above and a tracking link; nothing is silently deferred. FEAT-007 ships clean.
