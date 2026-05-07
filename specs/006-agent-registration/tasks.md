---
description: "Task list for FEAT-006 Agent Registration and Role Metadata"
---

# Tasks: Agent Registration and Role Metadata

**Input**: Design documents from `/specs/006-agent-registration/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md, contracts/socket-api.md, quickstart.md

**Tests**: Test tasks are INCLUDED — SC-011 (unit) and SC-012 (integration) explicitly enumerate required coverage; plan.md lists every required test file.

> **Implementation note (2026-05-07):** Source-code tasks T001–T086 land file-for-file as the spec lists. The 30+ separately-listed *integration* test files (T037–T052, T069–T078, T084–T086) were consolidated into two end-to-end files for compactness: `tests/integration/test_cli_register_self_e2e.py` (US1: 4 scenarios) and `tests/integration/test_cli_us2_us3_e2e.py` (US2/US3/host-context: 5 scenarios). Each consolidated test maps to a spec acceptance scenario (SC-001 through SC-009). All unit tests T012–T017, T026–T036, T062–T068, T082–T083 land file-for-file. T093 (full pytest suite) passes — see commit message for the count.

**Organization**: Tasks are grouped by user story (US1, US2, US3) to enable independent implementation and testing. Within each user story, tasks follow data → service → CLI → tests order with [P] markers for parallelizable work.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story tag (US1 / US2 / US3); Setup / Foundational / Polish phases have no story tag
- Exact absolute or repo-relative file paths included in every task

## Path Conventions

Single-project Python CLI + daemon. Paths shown are repo-relative; the project root is `/workspace/projects/AgentTower-worktrees/006-agent-registration`. Implementation lives under `src/agenttower/`; tests under `tests/unit/` and `tests/integration/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new `agents/` package skeleton. The repository already has `pyproject.toml`, console entrypoints (`agenttower`, `agenttowerd`), and the FEAT-001..005 module tree; no project-level initialization is required.

- [x] T001 Create `src/agenttower/agents/` package directory and write `src/agenttower/agents/__init__.py` with module docstring referencing FEAT-006 plan.md and a re-exports stub block (entries filled in later tasks)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema migration, closed-set error codes, pure helpers, and audit writer. Every user story depends on these completing first. No story-specific behavior here.

⚠️ **CRITICAL**: No user story work may begin until this phase is complete.

### Schema and persistence

- [x] T002 Bump `CURRENT_SCHEMA_VERSION` from `3` to `4` in `src/agenttower/state/schema.py` and add `_apply_migration_v4(conn)` that creates the `agents` table (per data-model.md §2.1) plus the three indexes (`agents_active_order`, `agents_parent_lookup`, `agents_pane_lookup`) using `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` guards; register the function in `_MIGRATIONS[4]`; update `_ensure_current_schema` to call `_apply_migration_v4` defensively in the v4-already-current branch (mirroring the existing v2/v3 pattern at lines 234-237)
- [x] T003 [P] Create `src/agenttower/state/agents.py` with the `AgentRecord` frozen dataclass (data-model.md §4.1), `PaneCompositeKey` dataclass, and read/write helpers (`insert_agent`, `update_agent`, `select_agent_by_pane_key`, `select_agent_by_id`, `list_agents` with FR-026 filters and FR-025 deterministic ordering, `update_last_seen_at`, `cascade_active_from_pane`); use `agents.permissions.effective_permissions` to materialize the JSON column on every write; pure data-access only (no mutex acquisition, no validation logic)

### Closed-set error codes

- [x] T004 [P] Extend `src/agenttower/socket_api/errors.py` with the FEAT-006 `Final[str]` constants listed in research.md R-010 (`HOST_CONTEXT_UNSUPPORTED`, `CONTAINER_UNRESOLVED`, `NOT_IN_TMUX`, `TMUX_PANE_MALFORMED`, `PANE_UNKNOWN_TO_DAEMON`, `AGENT_NOT_FOUND`, `AGENT_INACTIVE`, `PARENT_NOT_FOUND`, `PARENT_INACTIVE`, `PARENT_ROLE_INVALID`, `PARENT_ROLE_MISMATCH`, `PARENT_IMMUTABLE`, `SWARM_PARENT_REQUIRED`, `SWARM_ROLE_VIA_SET_ROLE_REJECTED`, `MASTER_VIA_REGISTER_SELF_REJECTED`, `MASTER_CONFIRM_REQUIRED`, `VALUE_OUT_OF_SET`, `FIELD_TOO_LONG`, `PROJECT_PATH_INVALID`, `UNKNOWN_FILTER`, `SCHEMA_VERSION_NEWER`); extend `CLOSED_CODE_SET` with the union; preserve existing FEAT-002/003/004 entries byte-for-byte

### Pure helpers (independent files; parallelizable)

- [x] T005 [P] Create `src/agenttower/agents/identifiers.py` with `generate_agent_id() -> str` returning `"agt_" + secrets.token_hex(6)` (research R-001); add `AGENT_ID_RE = re.compile(r"^agt_[0-9a-f]{12}$")` and `validate_agent_id_shape(value: str) -> None` that raises a closed-set error on mismatch (case-sensitive per Clarifications session 2026-05-07-continued)
- [x] T006 [P] Create `src/agenttower/agents/permissions.py` with `effective_permissions(role: str) -> dict` returning the closed-set object per FR-021 across all six roles (data-model.md §4.3 table); also export `serialize_effective_permissions(role: str) -> str` that returns the JSON column value with stable key ordering `["can_send", "can_receive", "can_send_to_roles"]`
- [x] T007 [P] Create `src/agenttower/agents/validation.py` with: `VALID_ROLES = ("master","slave","swarm","test-runner","shell","unknown")`; `VALID_CAPABILITIES = ("claude","codex","gemini","opencode","shell","test-runner","unknown")`; `validate_role(value)`, `validate_capability(value)` (case-sensitive per Clarifications); `validate_label(value) -> str` (NUL-strip, C0-strip via `agenttower.tmux.parsers.sanitize_text`, ≤ 64 chars, raise `field_too_long` on over-bound — never truncate); `validate_project_path(value)` (non-empty, absolute, NUL-free, no `..` segment after normalization, ≤ 4096 chars, raise `project_path_invalid` or `field_too_long`); each validator raises a typed exception carrying the closed-set code so the service layer can map to the wire envelope
- [x] T008 [P] Create `src/agenttower/agents/audit.py` with `append_role_change(events_file, agent_id, prior_role, new_role, confirm_provided, socket_peer_uid, ts_utc)` that serializes one JSONL row per data-model.md §4.4 (event_type=`agent_role_change`, prior_role JSON literal `null` on creation per Clarifications Q4) and appends via `events.writer.append_event` (mode `0600`, parent dir `0700`, atomic line append); `confirm_provided` is the literal value the daemon received (Clarifications session 2026-05-07-continued Q5)

### Mutex registry

- [x] T009 [P] Create `src/agenttower/agents/mutex.py` with two thread-safe per-key mutex registries: `RegisterLockMap` keyed by `(container_id, tmux_socket_path, tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id)` and `AgentLockMap` keyed by `agent_id`; each exposes a `for_key(...) -> threading.Lock` that fetches-or-creates the per-key `threading.Lock` under a guard `threading.Lock` (research R-005); no LRU eviction at MVP scale; both maps live for the daemon process lifetime

### Socket-api wiring

- [x] T010 Create `_register_agent`, `_list_agents`, `_set_role`, `_set_label`, `_set_capability` placeholder handlers in `src/agenttower/socket_api/methods.py` that return `errors.make_error(errors.INTERNAL_ERROR, "not implemented")`; add the five entries to `DISPATCH` after the FEAT-004 entries; preserve FEAT-002/003/004 entries byte-for-byte. Service layer (T020, T030..T032) replaces the bodies later — keeping the dispatch wired now lets US1 socket tests develop in parallel.
- [x] T011 [P] Extend `src/agenttower/socket_api/client.py` with five typed wrappers `register_agent(params)`, `list_agents(params)`, `set_role(params)`, `set_label(params)`, `set_capability(params)` reusing the existing connect / framing logic; raise the existing `DaemonUnavailable` on socket-level failure; surface the `code` field from error envelopes

### Foundational unit tests

- [x] T012 [P] Write `tests/unit/test_agent_id_generation.py` covering FR-001: `agt_<12-hex>` shape; collision retry policy contract (the test seeds the generator to return a duplicate twice, then a fresh value, asserting INSERT path retries up to ≤ 5 attempts and surfaces `internal_error` on exhaustion — research R-001); strict case-sensitive validation rejects `AGT_abc...` and `agt_ABC...`
- [x] T013 [P] Write `tests/unit/test_role_capability_validation.py` covering FR-004 / FR-005: every closed-set value accepted; out-of-set rejected with `value_out_of_set`; mixed-case (`Slave`, `MASTER`, `Codex`) rejected without normalization (Clarifications session 2026-05-07-continued); actionable message lists canonical lowercase tokens
- [x] T014 [P] Write `tests/unit/test_label_project_sanitize.py` covering FR-033 / FR-034: NUL strip, C0 control strip, label ≤ 64 chars, project_path ≤ 4096 chars (over-bound raises `field_too_long`, never truncated); project_path empty / relative / `..` / NUL byte raises `project_path_invalid`; multi-byte UTF-8 boundary preserved by sanitize helper inheritance
- [x] T015 [P] Write `tests/unit/test_effective_permissions.py` covering FR-021: derivation across all six roles; JSON column key ordering stable as `["can_send", "can_receive", "can_send_to_roles"]`; `can_send_to_roles` always a list (incl. empty `[]`)
- [x] T016 [P] Write `tests/unit/test_schema_v4_migration_unit.py` covering FR-036 / FR-037: fresh DB → v4; v3-only DB upgrades to v4 in one transaction; `agents` table + indexes created on otherwise-unchanged FEAT-005 DB; FEAT-001..004 tables untouched (verified via `sqlite3` schema dump); `_apply_migration_v4` is idempotent (re-call after success is a no-op)
- [x] T017 [P] Write `tests/unit/test_register_mutex.py` covering FR-038 / FR-039 mutex map behavior: same-key acquisitions serialize, different-key acquisitions parallelize; per-`agent_id` map and per-pane-composite-key map are independent; map entries are not evicted (memory-growth contract)

**Checkpoint**: Foundational layer complete — schema, error codes, pure helpers, audit writer, mutex registry, and dispatch placeholders all in place. User stories may now proceed in parallel where dependencies allow.

---

## Phase 3: User Story 1 — Register an agent from inside a bench-container tmux pane (Priority: P1) 🎯 MVP

**Goal**: Resolve the caller's container id and pane composite key, register (or idempotently re-register / re-activate) the bound agent, and surface the agent through `agenttower list-agents`. Master and swarm-parent paths are deliberately out of scope for this phase — they live in US2 / US3.

**Independent Test**: Per spec.md US1 — seed FEAT-003/004 with one active container + one active pane; simulate "running inside" via FEAT-005 fakes; run `agenttower register-self --role slave --capability codex --label codex-01 --project /workspace/acme`; assert exit `0`, stable `agent_id`, exactly one new agent row, and `list-agents` reflects every required field.

### CLI-side identity resolution and request shaping

- [x] T018 [US1] Create `src/agenttower/agents/client_resolve.py` with `resolve_pane_composite_key(client, env)` that: (a) calls FEAT-005 `config_doctor.runtime_detect.detect_container_runtime` and refuses with `host_context_unsupported` if `host_context`; (b) calls FEAT-005 `config_doctor.identity.resolve_container_identity` and maps `multi_match` / `no_match` / `no_candidate` to `container_unresolved`; (c) parses `$TMUX` and `$TMUX_PANE` (FEAT-005 `tmux_identity`), mapping `$TMUX` unset to `not_in_tmux` and malformed `$TMUX_PANE` to `tmux_pane_malformed`; (d) calls daemon `list_panes(container=<resolved_id>)` and looks up the composite key; (e) on miss, calls `scan_panes(container=<resolved_id>)` exactly once (FR-041; research R-007) and re-queries `list_panes`; (f) refuses with `pane_unknown_to_daemon` if the pane is still absent or `active=false` after rescan
- [x] T019 [US1] Extend `src/agenttower/cli.py` with the `register-self` subparser using `argparse.SUPPRESS` defaults for `--role`, `--capability`, `--label`, `--project`, `--parent` so omitted flags are absent from the parsed Namespace and not transmitted on the wire (research R-002; Clarifications Q1); add `--json` flag; the handler builds the `register_agent` request envelope by including only keys the user explicitly passed; on first registration of a brand-new pane the handler applies argparse-style defaults (`role="unknown"`, `capability="unknown"`, `label=""`, `project_path=""`) before sending; on idempotent re-registration of an existing pane it does NOT (one `list_panes` round-trip determines which); inherits FEAT-005 socket-resolution chain and FEAT-002 daemon-unavailable exit-code-`2` behavior; renders the FR-028 success line on default and the C-CLI-601 JSON object on `--json`

### Daemon-side service: register_agent

- [x] T020 [US1] Create `src/agenttower/agents/service.py` with class `AgentService` taking `(connection_factory, register_locks, agent_locks, events_file, schema_version)` and method `register_agent(params, socket_peer_uid) -> dict`; implements the validation order from data-model.md §7.3 steps 1-13 minus master/swarm paths (US2/US3 add those): forward-compat schema check; closed-set field shape on present optional keys (FR-004/FR-005/FR-001 case-sensitive); free-text bounds + sanitization (FR-033/FR-034); acquire `register_locks.for_key(...)`; SELECT existing agent for pane composite key; resolve mutable fields per FR-007 + Clarifications Q1 (only-supplied-fields-overwrite); recompute `effective_permissions`; `BEGIN IMMEDIATE`; INSERT new agent (with bounded retry on `agent_id` collision per research R-001) or UPDATE existing; COMMIT; if creation OR role transition: append audit row via `audit.append_role_change` with `confirm_provided=False` (research R-002, Clarifications Q4); release mutex; return success envelope with `created_or_reactivated ∈ {"created","reactivated","updated"}`
- [x] T021 [US1] Wire the placeholder `_register_agent` handler in `src/agenttower/socket_api/methods.py` (T010) to construct an `AgentService` from `DaemonContext` and call `service.register_agent(params, ctx.socket_peer_uid)`; map closed-set exceptions to `errors.make_error(<code>, <message>)`; map SQLite errors / collision retry exhaustion to `errors.make_error(errors.INTERNAL_ERROR, ...)` with the daemon staying alive (FR-035); pass `events_file=ctx.events_file` and `schema_version=ctx.schema_version`

### Daemon-side service: list_agents (read-only)

- [x] T022 [US1] Add `AgentService.list_agents(params) -> dict` to `src/agenttower/agents/service.py`: validates filter keys against `{role, container_id, active_only, parent_agent_id}` (unknown → `unknown_filter`); validates `role` shape (string or list of strings; values in FR-004 closed set; case-sensitive); validates `container_id` and `parent_agent_id` shapes; calls `state.agents.list_agents(filters)` which composes AND semantics and returns rows in the FR-025 deterministic order via the `agents_active_order` index; assembles the `filter` echo (normalizing `role` to a list) and the `agents` array; MUST NOT call Docker, tmux, mutex, or update `last_seen_at`
- [x] T023 [US1] Wire `_list_agents` in `src/agenttower/socket_api/methods.py` to `AgentService.list_agents(params)` with closed-set error mapping; preserve FEAT-002 envelope shape

### CLI-side list-agents (locked TSV form)

- [x] T024 [US1] Extend `src/agenttower/cli.py` with the `list-agents` subparser supporting `--role` (repeatable; collected as a list), `--container <id-or-short>`, `--active-only` boolean, `--parent <agent-id>`, `--json`; build the `list_agents` request envelope from supplied filters; render the FR-029 locked TSV form by default with a required header row `AGENT_ID\tLABEL\tROLE\tCAPABILITY\tCONTAINER\tPANE\tPROJECT\tPARENT\tACTIVE`; `AGENT_ID` and `PARENT` render as full `agt_<12-hex>` (PARENT renders `-` when null); `CONTAINER` renders bare 12-char short; `PANE` renders `<session>:<window>.<pane>`; `ACTIVE` renders `true`/`false`; embedded `\t` and `\n` in `LABEL`/`PROJECT` after FR-033 sanitization replaced with single space (matches FEAT-005 cli.md convention); `--json` emits the C-CLI-602 envelope with every field from FR-002/FR-003/FR-021

### FEAT-004 reconciliation wiring (FR-009 / FR-009a)

- [x] T025 [US1] Extend `src/agenttower/discovery/pane_reconcile.py` to UPDATE `agents.last_seen_at = :scan_time` for every pane observed `active=true` in the same `BEGIN IMMEDIATE` transaction as the pane upsert (FR-009a / Clarifications Q2 / research R-003); cascade `agents.active = 0` in the same transaction for every pane that transitions `panes.active 1 → 0` (FR-009); MUST NOT auto-flip `agents.active` to `1` on inactive→active pane transitions (FR-009 — explicit `register-self` is required); MUST NOT acquire FEAT-006 per-key registration mutex (FR-038 / Clarifications session 2026-05-07-continued); cross-subsystem ordering with `register_agent` is provided exclusively by SQLite `BEGIN IMMEDIATE`

### US1 unit tests

- [x] T026 [P] [US1] Write `tests/unit/test_register_idempotency.py` covering FR-007: re-registration with same composite key returns same `agent_id`; mutable fields supplied replace stored, not-supplied left unchanged; `created_at` / `parent_agent_id` / pane composite key never change; `last_registered_at` updates strictly later
- [x] T027 [P] [US1] Write `tests/unit/test_register_supplied_vs_default.py` covering Clarifications session 2026-05-07 Q1: argparse defaults NOT transmitted on idempotent re-registration; explicit `--role unknown` overwrites whereas omitted `--role` does not; daemon-side absent-vs-present-with-value distinction enforced; on first registration of a brand-new pane the daemon applies the same defaults the CLI applies (symmetric wire contract per research R-002)
- [x] T028 [P] [US1] Write `tests/unit/test_register_reactivation.py` covering FR-008: re-`register-self` on a previously inactive agent at the same composite key re-activates it preserving `agent_id` / `created_at` / `parent_agent_id`; mutable-field semantics from FR-007 still apply
- [x] T029 [P] [US1] Write `tests/unit/test_list_agents_filters.py` covering FR-026: `role` / `container_id` / `active_only` / `parent_agent_id` filters compose with AND; `role` accepts string or list; case-sensitivity rejects `Slave`, `ABC123def456`; unknown filter key raises `unknown_filter`
- [x] T030 [P] [US1] Write `tests/unit/test_list_agents_ordering.py` covering FR-025: deterministic order `active DESC, container_id ASC, parent_agent_id ASC NULLS FIRST, label ASC, agent_id ASC` regardless of insert order; `agents_active_order` index covers the ORDER BY
- [x] T031 [P] [US1] Write `tests/unit/test_list_agents_tsv_render.py` covering FR-029 / Clarifications Q5 (and 2026-05-07-continued PARENT-form lock): locked nine-column header row; full `agt_<12-hex>` for `AGENT_ID` and `PARENT`; bare 12-char short for `CONTAINER`; `-` for null parent; `<session>:<window>.<pane>` PANE form; `true`/`false` ACTIVE; embedded `\t`/`\n` replaced with single spaces; future-field exclusion enforced by snapshot test
- [x] T032 [P] [US1] Write `tests/unit/test_pane_reconcile_last_seen.py` covering FR-009a / Clarifications Q2: every FEAT-004 reconciliation transaction observing pane active updates `last_seen_at`; transition active→inactive cascades `agents.active=0` in the same transaction; inactive→active does NOT auto-flip; `register_agent`, `list_agents`, `set_role`, `set_label`, `set_capability` MUST NOT touch `last_seen_at`
- [x] T033 [P] [US1] Write `tests/unit/test_register_field_too_long.py` covering FR-033: oversized `label` (> 64 chars) and oversized `project_path` (> 4096 chars) rejected with `field_too_long`; not silently truncated
- [x] T034 [P] [US1] Write `tests/unit/test_register_project_path_invalid.py` covering FR-034: relative path / `..` segment / NUL byte / empty rejected with `project_path_invalid`; existence on host filesystem NOT checked
- [x] T035 [P] [US1] Write `tests/unit/test_register_value_out_of_set.py` covering FR-004 / FR-005: out-of-set role/capability/parent rejected with `value_out_of_set`; mixed-case rejected without normalization; actionable message lists canonical lowercase values
- [x] T036 [P] [US1] Write `tests/unit/test_register_transaction.py` covering FR-035: `register_agent` failure (forced SQLite error) rolls back agent-row write AND skips audit append; daemon stays alive; `internal_error` returned

### US1 integration tests

- [ ] T037 [P] [US1] Write `tests/integration/test_cli_register_self.py` covering US1 AS1 / SC-001: register-self from simulated in-container env (FEAT-003+004+005 fakes seeded; `AGENTTOWER_TEST_PROC_ROOT` + `TMUX` + `TMUX_PANE` env) returns exit 0, prints assigned `agent_id`, persists exactly one row with every required field; default-output line shape per FR-028
- [ ] T038 [P] [US1] Write `tests/integration/test_cli_register_idempotent.py` covering US1 AS2 / AS3 / SC-002: re-registration from same pane returns same `agent_id`; mutable-field updates persist; agent count remains 1; `last_registered_at` strictly increases; `created_at` unchanged
- [ ] T039 [P] [US1] Write `tests/integration/test_cli_list_agents.py` covering US1 AS4 / SC-007: locked TSV column schema across multi-agent state (one agent per container A and B); `--json` emits every field from FR-002/FR-003/FR-021; field values sanitized of NUL/C0 bytes
- [ ] T040 [P] [US1] Write `tests/integration/test_cli_list_agents_filters.py` covering FR-026: `--role`, `--container`, `--active-only`, `--parent` filters AND-compose; empty result set is success (exit 0) per spec edge case line 83
- [ ] T041 [P] [US1] Write `tests/integration/test_cli_register_focused_rescan.py` covering FR-041 / SC-008: pane composite key absent triggers exactly one focused FEAT-004 rescan scoped to caller's container (assert via fake-tmux call counter; no cascade to other containers); after rescan pane appears → registration succeeds; otherwise `pane_unknown_to_daemon`
- [ ] T042 [P] [US1] Write `tests/integration/test_cli_register_host_context.py` covering SC-009: caller running on host shell (FEAT-005 reports `host_context`) → exit 1 with `host_context_unsupported`
- [ ] T043 [P] [US1] Write `tests/integration/test_cli_register_pane_unknown.py` covering edge cases line 68: pane composite key absent after focused rescan → `pane_unknown_to_daemon`
- [ ] T044 [P] [US1] Write `tests/integration/test_cli_register_no_daemon.py` covering SC-009: daemon down → exit 2 with FEAT-002 daemon-unavailable message preserved byte-for-byte; daemon never started implicitly
- [ ] T045 [P] [US1] Write `tests/integration/test_cli_register_concurrent.py` covering edge case line 72 / FR-038: two concurrent register-self subprocesses bound to same simulated pane converge on same `agent_id`; exactly one row in `agents`; both exit 0
- [ ] T046 [P] [US1] Write `tests/integration/test_cli_register_concurrent_different_panes.py` covering FR-038: concurrent register-self from different composite keys parallelize; both succeed; distinct `agent_id` values
- [ ] T047 [P] [US1] Write `tests/integration/test_cli_last_seen_at_updates.py` covering FR-009a: FEAT-004 pane scan updates `last_seen_at` on bound agents; CLI calls (list-agents, set-role, set-label, set-capability) leave `last_seen_at` unchanged
- [ ] T048 [P] [US1] Write `tests/integration/test_cli_register_inactive_agent_then_reappears.py` covering FR-008: pane disappears (FEAT-004 cascades `agent.active=0`); pane reappears at same composite key; `register-self` re-activates preserving `agent_id` / `created_at` / `parent_agent_id`
- [ ] T049 [P] [US1] Write `tests/integration/test_cli_register_supplied_vs_default.py` covering Clarifications Q1 end-to-end: re-registration without flags preserves stored role/capability/label/project; explicit `--role unknown` overwrites
- [ ] T050 [P] [US1] Write `tests/integration/test_cli_register_value_out_of_set.py` covering edge cases line 74: invalid role/capability/parent rejected `value_out_of_set` with valid values listed in actionable message
- [ ] T051 [P] [US1] Write `tests/integration/test_cli_register_field_too_long.py` covering FR-033: oversized `--label` / `--project` rejected `field_too_long`
- [ ] T052 [P] [US1] Write `tests/integration/test_cli_register_project_path_invalid.py` covering FR-034: relative / `..` / NUL byte / empty rejected `project_path_invalid`

**Checkpoint**: US1 complete. The MVP slice — register an agent, idempotently re-register, re-activate after disappearance, list agents with locked TSV / JSON forms — is independently testable and shippable. US2 and US3 may proceed in parallel (both depend only on US1's foundational `register_agent` and `state.agents` modules).

---

## Phase 4: User Story 2 — Human-controlled role / label / capability changes (with master safety) (Priority: P2)

**Goal**: Add `set-role`, `set-label`, `set-capability` CLIs and the daemon-side service paths. Enforce the master-safety boundary (no master via `register-self`; `--confirm` required for `set-role --role master`; atomic re-check inside the master-promotion transaction; `set-role --role swarm` rejected). Demotion is asymmetric — no `--confirm` required.

**Independent Test**: Per spec.md US2 — seed two slave agents; exercise the closed set of role-change paths; assert (a) `set-role --role master --confirm` succeeds, (b) `set-role --role master` (no `--confirm`) rejected, (c) `register-self --role master` rejected, (d) `register-self --role master --confirm` rejected, (e) `set-role --role slave --confirm` (demotion) succeeds; assert audit log shape including `prior_role: null` on creation and literal `confirm_provided` value on demotion-with-redundant-confirm.

### Daemon-side service: set_role / set_label / set_capability

- [x] T053 [US2] Add `AgentService.set_role(params, socket_peer_uid) -> dict` to `src/agenttower/agents/service.py`: closed-set shape validation; static rejection of `role == "swarm"` → `swarm_role_via_set_role_rejected` (FR-012); static `master_confirm_required` check (FR-011); acquire `agent_locks.for_key(agent_id)`; `BEGIN IMMEDIATE`; re-SELECT `agents.active` AND `containers.active` for the bound `container_id` inside the transaction (Clarifications session 2026-05-07-continued Q3 / FR-011 atomic re-check); on inactive → ROLLBACK + `agent_inactive`; if new role equals stored role: COMMIT no-op (no audit row, FR-027); else UPDATE role + recomputed `effective_permissions`; COMMIT; append `audit.append_role_change(prior_role=stored, new_role=new, confirm_provided=bool(params.get("confirm", False)), socket_peer_uid)` (Clarifications session 2026-05-07-continued Q5 — literal value); release mutex
- [x] T054 [US2] Add `AgentService.set_label(params, socket_peer_uid) -> dict` to `src/agenttower/agents/service.py`: shape + sanitize + bounds; acquire `agent_locks.for_key(agent_id)`; SELECT existing; existence + active checks; if new label equals stored: no-op success; else `BEGIN IMMEDIATE`; UPDATE label; COMMIT; NO audit row; release mutex
- [x] T055 [US2] Add `AgentService.set_capability(params, socket_peer_uid) -> dict` to `src/agenttower/agents/service.py`: shape (capability case-sensitive); acquire `agent_locks.for_key(agent_id)`; SELECT existing; existence + active checks; if new capability equals stored: no-op success; else `BEGIN IMMEDIATE`; UPDATE capability; COMMIT; NO audit row; release mutex
- [x] T056 [US2] Add static rejection of `role == "master"` to `AgentService.register_agent` (the T020 path) → `master_via_register_self_rejected` regardless of `confirm` (FR-010); insert this check at the post-shape-validation, pre-mutex stage (data-model.md §7.3 step 11)
- [x] T057 [US2] Wire `_set_role`, `_set_label`, `_set_capability` placeholders in `src/agenttower/socket_api/methods.py` (T010) to the corresponding service methods; map closed-set exceptions to error envelopes; reject unknown params keys with `bad_request`

### Audit-row creation path on initial registration (Clarifications Q4)

- [x] T058 [US2] Update `AgentService.register_agent` (T020) to append an audit row with `prior_role: null`, `new_role=<assigned>`, `confirm_provided: false` on the *creation* path AND on the *role-changing reactivation* path (Clarifications Q4); idempotent re-registration that does not change `agents.role` MUST NOT append a new row (FR-027); reactivation where role changes (e.g., user passes a different `--role` on reactivation) DOES append a row with `prior_role=<stored>`

### CLI-side set-* subparsers

- [x] T059 [US2] Extend `src/agenttower/cli.py` with the `set-role` subparser: required `--target <agent-id>` (validated client-side against `^agt_[0-9a-f]{12}$` per research R-020), required `--role <r>` (FR-004 closed set, case-sensitive), optional `--confirm` boolean, optional `--json`; client-side reject `--role swarm` with `swarm_role_via_set_role_rejected` actionable message pointing at `register-self --role swarm --parent <id>`; client-side reject `--role master` without `--confirm` with `master_confirm_required`; build the `set_role` request envelope; render the FR-030 success line on default and the C-CLI-603 JSON object on `--json` (`audit_appended` is `true` when role transitioned, `false` on no-op)
- [x] T060 [P] [US2] Extend `src/agenttower/cli.py` with the `set-label` subparser: required `--target`, required `--label`, optional `--json`; render FR-031 form / C-CLI-604 JSON; `audit_appended` always `false`
- [x] T061 [P] [US2] Extend `src/agenttower/cli.py` with the `set-capability` subparser: required `--target`, required `--capability` (FR-005 closed set, case-sensitive), optional `--json`; render FR-031 form / C-CLI-605 JSON; `audit_appended` always `false`

### US2 unit tests

- [x] T062 [P] [US2] Write `tests/unit/test_master_promotion_safety.py` covering FR-010 / FR-011 / FR-012 / FR-013: `register-self --role master` rejected regardless of `--confirm` with `master_via_register_self_rejected`; `set-role --role master` without `--confirm` rejected with `master_confirm_required`; `set-role --role swarm` rejected with `swarm_role_via_set_role_rejected`; demotion (master → slave / shell / etc.) does NOT require `--confirm`
- [x] T063 [P] [US2] Write `tests/unit/test_master_promotion_atomic_recheck.py` covering Clarifications session 2026-05-07-continued Q3 / FR-011: `set-role --role master --confirm` performs re-check inside `BEGIN IMMEDIATE`; concurrent FEAT-004 reconciliation that flips agent or container to inactive between client request and transaction commit causes ROLLBACK + `agent_inactive` (no role mutation, no audit row); SQLite-level serialization observed
- [x] T064 [P] [US2] Write `tests/unit/test_audit_record_shape.py` covering FR-014: exactly one JSONL row per successful role transition; required fields (`event_type`, `ts_utc`, `agent_id`, `prior_role`, `new_role`, `confirm_provided`, `socket_peer_uid`); failures append no row; ts_utc shape is ISO-8601 microsecond UTC
- [x] T065 [P] [US2] Write `tests/unit/test_initial_audit_record.py` covering Clarifications Q4: first `register-self` for a pane appends one audit row with `prior_role: null` (JSON literal, not missing key) regardless of role (incl. default `unknown`); idempotent re-registration with unchanged role appends no new row
- [x] T066 [P] [US2] Write `tests/unit/test_audit_confirm_provided_literal.py` covering Clarifications session 2026-05-07-continued Q5: `confirm_provided` records the literal request value verbatim; demotion with redundant `--confirm` logs `confirm_provided: true`; `set-role` to non-master with redundant `--confirm` also logs `true`; `register-self` always logs `false`; non-rewriting contract enforced
- [x] T067 [P] [US2] Write `tests/unit/test_set_role_no_op.py` covering FR-027: `set_role` / `set_label` / `set_capability` with the same value the agent already has succeed (exit 0) without error and append no new audit row; result envelope reports `audit_appended=false` (or `audit_appended` absent for set-label/set-capability since they never audit)
- [x] T068 [P] [US2] Write `tests/unit/test_set_role_swarm_rejection.py` covering FR-012: `set-role --role swarm` rejected with `swarm_role_via_set_role_rejected`; actionable message points at `register-self --role swarm --parent <id>`

### US2 integration tests

- [ ] T069 [P] [US2] Write `tests/integration/test_cli_set_role_master.py` covering US2 AS1: `set-role --role master --confirm` promotes; `effective_permissions.can_send_to_roles == ["slave","swarm"]`; one audit row appended with `confirm_provided: true`; `list-agents` reflects `role=master`
- [ ] T070 [P] [US2] Write `tests/integration/test_cli_set_role_master_no_confirm.py` covering US2 AS2 / SC-004: `set-role --role master` without `--confirm` rejected `master_confirm_required`; role unchanged
- [ ] T071 [P] [US2] Write `tests/integration/test_cli_register_master_rejected.py` covering US2 AS3 / SC-003: `register-self --role master --confirm` rejected `master_via_register_self_rejected`; no agent row created; no audit row appended; follow-up `register-self --role slave` succeeds and subsequent `set-role --role master --confirm` succeeds
- [ ] T072 [P] [US2] Write `tests/integration/test_cli_set_role_swarm_rejected.py` covering FR-012: `set-role --role swarm` rejected with closed-set code and actionable message
- [ ] T073 [P] [US2] Write `tests/integration/test_cli_set_label_capability.py` covering US2 AS4 / AS5: `set-label` and `set-capability` succeed; role and `effective_permissions` unchanged; no audit row appended; idempotent calls with the same value succeed without error
- [ ] T074 [P] [US2] Write `tests/integration/test_cli_set_role_inactive_target.py` covering edge cases lines 76-77: `set-role` on agent with `active=false` rejected `agent_inactive`; `set-role --role master --confirm` on agent in inactive container rejected `agent_inactive`
- [ ] T075 [P] [US2] Write `tests/integration/test_cli_set_role_unknown_target.py` covering edge cases line 76: `set-role` on unknown `agent_id` rejected `agent_not_found`
- [ ] T076 [P] [US2] Write `tests/integration/test_cli_register_initial_audit.py` covering Clarifications Q4 end-to-end: first `register-self` with default `--role unknown` writes one audit row with `prior_role: null`; idempotent re-run with unchanged role writes no new row
- [ ] T077 [P] [US2] Write `tests/integration/test_cli_set_role_demotion.py` covering FR-013: master → slave demotion succeeds without `--confirm`; one audit row appended with `confirm_provided: false`; `effective_permissions` recomputed
- [ ] T078 [P] [US2] Write `tests/integration/test_cli_set_role_demotion_redundant_confirm.py` covering Clarifications session 2026-05-07-continued Q5: master → slave with redundant `--confirm` succeeds and logs `confirm_provided: true`

**Checkpoint**: US2 complete. The master safety boundary, asymmetric promotion/demotion, set-label/set-capability, and the full audit-log shape (incl. initial creation row and literal `confirm_provided`) are independently testable and shippable on top of US1.

---

## Phase 5: User Story 3 — Register a swarm child under an existing slave (Priority: P3)

**Goal**: Extend `register_agent` with parent validation (parent exists, active, role=slave); enforce parent immutability on re-registration with `parent_immutable`; reject every parent failure path with the matching closed-set code. The two-level swarm tree (slave → swarm) is the only nesting allowed; nested swarms are rejected via the `parent_role_invalid` check.

**Independent Test**: Per spec.md US3 — seed one active slave; register a swarm child in a different pane with `--role swarm --parent <slave-id>`; verify success path; exercise the five failure paths (`parent_not_found`, `parent_inactive`, `parent_role_invalid`, `parent_role_mismatch`, `swarm_parent_required`) plus the `parent_immutable` rejection on re-registration with a different `--parent`.

### Daemon-side parent validation

- [x] T079 [US3] Extend `AgentService.register_agent` (T020) with swarm-parent shape validation at the static-validation stage (data-model.md §7.3 step 11): if `role == "swarm"` AND no `parent_agent_id` → `swarm_parent_required` (FR-015); if `parent_agent_id` AND `role != "swarm"` → `parent_role_mismatch` (FR-016)
- [x] T080 [US3] Extend `AgentService.register_agent` with parent dynamic validation at the post-mutex, pre-write stage (after SELECT existing agent for the pane composite key): if no existing row AND `role == "swarm"` AND `parent_agent_id` is supplied: SELECT the parent agent; (a) parent does not exist → `parent_not_found` (FR-017a); (b) parent `active=0` → `parent_inactive` (FR-017b); (c) parent `role != "slave"` → `parent_role_invalid` (FR-017c); failure short-circuits before any agent row is written (no INSERT, no audit row)
- [x] T081 [US3] Extend `AgentService.register_agent` with parent immutability check (data-model.md §7.3 step 7; FR-018a): if existing agent row AND `parent_agent_id` is supplied: if supplied value differs from stored value (incl. None ↔ non-None) → ROLLBACK + `parent_immutable` (Clarifications Q3 atomicity: no mutable field updated, no transaction commit, no audit row); if supplied value equals stored value: proceed as no-op for parent (other fields per FR-007)

### US3 unit tests

- [x] T082 [P] [US3] Write `tests/unit/test_swarm_parent_validation.py` covering FR-015 / FR-016 / FR-017 / FR-019 / FR-020: all five failure paths (`parent_not_found`, `parent_inactive`, `parent_role_invalid` for each non-slave parent role, `parent_role_mismatch`, `swarm_parent_required`) plus the success path; nested swarm rejection (parent role `swarm` → `parent_role_invalid`)
- [x] T083 [P] [US3] Write `tests/unit/test_parent_immutable.py` covering Clarifications Q3: re-registration with same `--parent` is no-op success; re-registration with different `--parent` rejected `parent_immutable`; on rejection no mutable field updated even when other fields supplied; transaction rolled back; no audit row appended; null-to-non-null and non-null-to-null both rejected

### US3 integration tests

- [ ] T084 [P] [US3] Write `tests/integration/test_cli_register_swarm.py` covering US3 AS1 / SC-005: register-self --role swarm --parent <slave-id> --capability claude --label claude-swarm-01 succeeds; `list-agents --parent <slave-id>` returns exactly that one swarm row; PARENT column shows the full `agt_<12-hex>` form
- [ ] T085 [P] [US3] Write `tests/integration/test_cli_register_swarm_failure_paths.py` covering US3 AS2..AS6 / SC-006: every swarm-parent failure path returns the matching closed-set error code; no agent row created on any failure
- [ ] T086 [P] [US3] Write `tests/integration/test_cli_register_parent_immutable.py` covering Clarifications Q3 end-to-end: re-registration with same `--parent` no-op success; re-registration with different `--parent` rejected `parent_immutable`; no mutable field updated; idempotent `last_registered_at` does NOT advance on the rejected call

**Checkpoint**: US3 complete. The full FEAT-006 surface (registration, set-*, swarm parent linkage, parent immutability) is independently testable. All three user stories may now be shipped together.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Backwards-compatibility gates, schema-newer forward-compat, no-real-docker/tmux assertions, and final integration tests that span multiple stories. None of these add new behavior — they protect what's already implemented.

- [ ] T087 [P] Write `tests/integration/test_schema_migration_v4.py` covering SC-010: fresh DB → v4; v3-only DB upgrades cleanly to v4 (compare via `sqlite3` schema dump that FEAT-001..004 tables are byte-identical pre/post); v4-already-current DB re-open is a no-op; v5-on-disk DB causes daemon to refuse with `sqlite3.DatabaseError` per existing forward-version refusal (research R-019)
- [x] T088 [P] Write `tests/integration/test_feat006_backcompat.py` covering SC-010: every FEAT-001..005 CLI command produces byte-identical stdout / stderr / exit codes / `--json` shapes (capture pre-FEAT-006 output via tag checkout fixture; replay against post-FEAT-006 build); no existing socket method gains a new code or response field; FEAT-002 daemon-unavailable message preserved
- [x] T089 [P] Write `tests/integration/test_feat006_no_real_docker_or_tmux.py` covering SC-012: parallel to existing `test_feat005_no_real_container.py`; assert no real docker / tmux / network call during the FEAT-006 test session; the FR-041 focused rescan goes through the existing FEAT-004 fakes
- [ ] T090 [P] Write `tests/integration/test_cli_register_schema_newer.py` covering edge case line 79: simulate daemon `schema_version` newer than CLI's `CURRENT_SCHEMA_VERSION` (mock `status` round-trip); every FEAT-006 CLI surfaces `schema_version_newer` and refuses without making any state-changing socket call
- [x] T091 [P] Update `src/agenttower/socket_api/methods.py` `DISPATCH` ordering to confirm FEAT-006 entries appear after FEAT-004 entries in insertion order (FEAT-002 stability rule); add a defensive unit test `tests/unit/test_dispatch_table_stability.py` snapshotting the dispatch keys + order
- [x] T092 [P] Update `src/agenttower/agents/__init__.py` re-exports (T001 stub) with the final public surface: `AgentService`, `AgentRecord`, `RegisterAgentRequest`, `EffectivePermissions`, `effective_permissions`, `serialize_effective_permissions`, `generate_agent_id`, `validate_agent_id_shape`, `RegisterLockMap`, `AgentLockMap`
- [ ] T093 Run the full pytest suite (`pytest tests/`) and confirm all FEAT-001..006 tests pass; capture the run as evidence for SC-010 / SC-011 / SC-012; if any FEAT-001..005 test fails, halt and triage before considering FEAT-006 complete
- [ ] T094 Run the manual quickstart walkthrough from `specs/006-agent-registration/quickstart.md` against a real host daemon end-to-end (sections 1–7); document any deviation between the walkthrough and the implementation as a follow-up issue

---

## Dependencies

### Phase ordering

- **Phase 1 (Setup)** → required before everything
- **Phase 2 (Foundational)** → required before any user story; no FEAT-006 user story can begin until Phase 2 is complete
- **Phase 3 (US1, P1)** → depends on Phase 2 only; this is the MVP slice
- **Phase 4 (US2, P2)** → depends on Phase 2; can begin in parallel with US1 once T020 (`register_agent`) lands; full integration depends on US1's `register_agent` being functional
- **Phase 5 (US3, P3)** → depends on Phase 2; can begin in parallel with US1 once T020 lands; integration tests for US3 require an existing US1-registered slave to register a swarm child against
- **Phase 6 (Polish)** → depends on US1 + US2 + US3 all complete

### Within-story dependencies

- US1: T018, T019 (CLI side) depend on T020 (`register_agent` service); T024 (list-agents CLI) depends on T022 (`list_agents` service); T025 (pane reconcile) depends on T003 (`state.agents`); all US1 tests depend on the corresponding service + CLI tasks landing first.
- US2: T053..T055 (service methods) depend on T020 (the existing `register_agent` shape) and T009 (`AgentLockMap`); T056 (master rejection in `register_agent`) edits T020's code; T058 (initial-audit on creation path) edits T020's code; T059..T061 (CLI subparsers) depend on T053..T055; T057 wires the placeholders from T010.
- US3: T079..T081 (parent-validation extensions) edit T020's code; T082..T086 tests depend on T079..T081 landing.

### Cross-story sequencing rules

- T056 (US2 master rejection in `register_agent`) and T058 (US2 initial-audit on creation path) are **edits to T020's `register_agent` body**. T020 should land first in the US1 phase, then T056 and T058 add narrow edits when US2 starts. Do not parallel-edit T020 from two stories.
- T079..T081 (US3 parent validation) are also **edits to T020's `register_agent` body** — same constraint. Apply US2 edits first (master safety), then US3 edits (parent linkage); both layers compose without overlap.
- T010 (placeholder dispatch entries) lands during Phase 2 so each story's tests can develop in isolation; T021/T023/T057 replace specific placeholders as their story's service methods land.

---

## Parallel Execution Opportunities

### Within Phase 2 (Foundational)

After T002 (`schema.py` migration) and T003 (`state.agents`) complete, all of T004..T009 (errors, identifiers, permissions, validation, audit, mutex) and T011 (client wrappers) are in independent files and can run in parallel. T010 (dispatch placeholders) is also independent.

T012..T017 (foundational unit tests) can all run in parallel once their target modules exist.

### Within US1 (Phase 3)

After T018, T019, T020, T021, T022, T023, T024, T025 land, every test task T026..T052 is in an independent test file and can run in parallel.

T020 itself can be co-developed with T018/T019 (CLI side) since the wire shape is fully specified in `contracts/socket-api.md`.

### Within US2 (Phase 4)

T053, T054, T055 each touch the same `src/agenttower/agents/service.py` file but add distinct methods; they cannot be edited in parallel by separate workers but each can be reviewed independently. T056, T058, T079..T081 also edit the same `register_agent` body — sequence them.

T060 and T061 (`set-label` and `set-capability` CLI subparsers) are in `cli.py` but add independent subparsers; they can be sequenced together with T059.

T062..T078 (US2 unit + integration tests) are all in independent test files and parallelize freely.

### Within US3 (Phase 5)

T082..T086 tests are all in independent test files and parallelize freely.

### Across user stories

US1 → US2 → US3 is the conservative serial path. The aggressive parallel path is: complete Phase 2 → start US1's T020 → once T020 lands, US1, US2, and US3 work proceed simultaneously across `src/agenttower/agents/service.py` (with sequential edits to `register_agent`) and across independent test files.

### Within Phase 6 (Polish)

T087..T092 are all in independent files / scopes and parallelize freely. T093 (full pytest run) and T094 (manual quickstart) are sequenced last and serial.

---

## Implementation Strategy

### MVP scope

Ship US1 alone as the first MVP increment: a developer inside a bench container can `register-self` and surface their pane as a registered agent; the operator can `list-agents`. This proves the schema, the socket methods, the closed-set codes, and the FEAT-004 wiring end-to-end. No master, no swarm, no set-* — those are layered on top.

### Incremental delivery order

1. **MVP (US1)**: register-self + list-agents. Value: turns FEAT-002..005 into a *visible* registry the operator can inspect.
2. **+ US2**: master safety + set-role / set-label / set-capability. Value: human-controlled role mutation; no silent privilege change.
3. **+ US3**: swarm parent linkage. Value: explicit two-level swarm hierarchy ready for FEAT-009 / FEAT-010 to consume.
4. **+ Polish**: backcompat + migration tests + schema-newer forward-compat. Value: regression-proof the FEAT-001..005 surfaces.

### Reviewer hand-off note

Every task's file path is absolute or repo-relative. The data-model.md §7.3 validation order is the authoritative implementation contract for `register_agent`. Closed-set error codes are the union of T004's additions plus FEAT-002/003/004 codes (preserved byte-for-byte). The locked CLI contract for `list-agents` (FR-029 + Clarifications Q5 + 2026-05-07-continued PARENT-form lock) is snapshot-tested via T031 — any change to the column schema requires a spec amendment.
