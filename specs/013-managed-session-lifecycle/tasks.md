---
description: "Task list for FEAT-013 Managed Session Creation and Lifecycle"
---

# Tasks: Managed Session Creation and Lifecycle

**Input**: Design documents from `/specs/013-managed-session-lifecycle/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md
**Tests**: Included — plan.md §Testing explicitly enumerates contract tests under `tests/contract/test_managed_*.py` and integration tests under `tests/integration/test_story{1,2,3}_*.py` + `test_managed_edge_cases.py`. Negative-path and concurrency tests are required for FR-012, FR-014, FR-019.
**Organization**: Tasks are grouped by user story so each story can be implemented + tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: `[US1]`, `[US2]`, `[US3]` for user-story-phase tasks (no label for Setup / Foundational / Polish)
- Exact file paths in every task

## Path Conventions

Single Python package: `src/agenttower/managed_sessions/`. Tests under `tests/contract/`, `tests/integration/`, `tests/fixtures/`. SQLite migration registered in FEAT-001 `src/agenttower/state/schema.py` as `_apply_migration_v9` (no separate `migrations/` directory; FEAT-001 uses an in-Python migration registry). Operator-overridable YAML under `~/.config/opensoft/agenttower/managed_templates/` and `…/launch_commands/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton, migration file, fixture scaffolding.

- [x] T001 Create the sub-package `src/agenttower/managed_sessions/` with empty module stubs (`__init__.py`, `service.py`, `state_machine.py`, `templates.py`, `launch_profiles.py`, `tmux_create.py`, `pending_marker.py`, `serializer.py`, `recovery.py`, `view_models.py`, `events.py`, `errors.py`) and `src/agenttower/managed_sessions/handlers/` (`__init__.py`, `cli.py`, `app.py`). Migration registration lives in FEAT-001's existing `src/agenttower/state/schema.py` registry (not a separate `migration.py` in this sub-package; see T002).
- [x] T002 Add `_apply_migration_v9(conn)` to `src/agenttower/state/schema.py` containing the DDL from data-model.md (managed_layout, managed_pane, all indexes, all CHECK constraints; `IF NOT EXISTS` throughout; **no existing table altered**); register it in `_MIGRATIONS` and bump `CURRENT_SCHEMA_VERSION` from 8 to 9; add `_apply_migration_v9(conn)` to the fresh-init cascade. **Touches the existing FEAT-001 file `state/schema.py`** — see Notes for the existing-file modification list.
- [x] T003 [P] Ship example YAMLs under `examples/managed_templates/1m-2s.example.yaml` and `examples/launch_commands/bash-placeholder.example.yaml` (NOT installed; reference only per FR-024 no-auto-create). Do NOT create files in `~/.config/opensoft/agenttower/` — the operator's home dirs stay untouched per FR-024.
- [x] T004 [P] Scaffold the new test fixtures: empty files `tests/fixtures/managed_template_fixtures.py`, `tests/fixtures/managed_clock.py`, `tests/fixtures/managed_tmux_recorder.py`

**Checkpoint**: Skeleton compiles; migration file exists but not yet wired.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Building blocks every user story needs — closed-set vocab, state machine, storage, tmux adapter, serializer, marker. **⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T005 [P] Implement closed-set error code constants and `details` schemas (**12** new codes: `managed_session_name_conflict`, `managed_template_not_found`, `managed_launch_command_not_found`, `managed_layout_not_found`, `managed_pane_not_found`, `managed_pane_protected_adopted`, `managed_pane_illegal_transition`, `managed_pane_illegal_recreate_source`, `managed_pane_recreate_chain_too_deep`, `managed_layout_capacity_exceeded` (FR-025), `managed_pane_concurrent_recreate` (FR-027), `managed_pane_label_conflict` (FR-003; Phase 3b addition)) in `src/agenttower/managed_sessions/errors.py`
- [x] T006 [P] Implement lifecycle state machine (5 states + transition table + validators; reject `degraded → ready`, `removed → *`, `* → promoted_from_adopted`; reserved `PROMOTE_FROM_ADOPTED` constant) in `src/agenttower/managed_sessions/state_machine.py`
- [x] T007 Verify migration v9 idempotency in `tests/contract/test_managed_migration.py`: the DDL added in T002 uses `CREATE TABLE IF NOT EXISTS` and `CREATE [UNIQUE] INDEX IF NOT EXISTS` so re-running `_apply_migration_v9` against an already-migrated DB MUST (a) not raise, (b) leave `schema_version` at 9, (c) introduce zero row mutations on the second run. Depends on T002.
- [x] T008 [P] Implement layout template registry in `src/agenttower/managed_sessions/templates.py`: built-in `1m+2s` (3 panes) and `2m+2s` (4 panes) `ManagedTemplate` instances; YAML loader for `~/.config/opensoft/agenttower/managed_templates/*.yaml` with override-by-name semantics (FR-024); schema validator; `TemplateNotFoundError` raised by lookup
- [x] T009 [P] Implement launch command profile YAML loader in `src/agenttower/managed_sessions/launch_profiles.py`: parses `~/.config/opensoft/agenttower/launch_commands/*.yaml`, argv-shape enforcement (R9), lookup-by-name with override-by-name semantics (FR-024)
- [x] T010 [P] Implement per-container serializer in `src/agenttower/managed_sessions/serializer.py`: `dict[container_id, asyncio.Lock]` with FIFO waiter semantics (research §R2); no wait-time cap; cross-container calls run in parallel
- [x] T011 [P] Implement tmux command composer in `src/agenttower/managed_sessions/tmux_create.py`: argv-first wrappers for `tmux new-session -d -s <name> -- <argv>`, `tmux split-window -t … -- <argv>`, `tmux select-pane -T <title>`, `tmux kill-pane -t …`, `tmux list-panes -t <container> -F …`; invokes through the existing FEAT-004 `docker exec -u "$USER"` channel; `shlex.quote` fallback only when env / working_dir requires it (Principle III safety). Each tmux RPC MUST enforce the per-stage 30-second timeout from FR-013 with 2x transient retry (1s / 2s back-off); on timeout the call returns a stage-specific error so the service can attribute the `failed_stage`
- [x] T012 [P] Implement pending-managed marker module in `src/agenttower/managed_sessions/pending_marker.py`: set/read/clear `@MANAGED:<token>:<label>` tmux pane title (via tmux_create) AND `managed_pane.pending_marker_token` SQLite column; sweep helper `sweep()` (boot + periodic 60s) implementing FR-022 5-minute TTL transitioning stale rows to `failed` with appropriate `failed_stage`
- [x] T013 [P] Implement managed-layout / managed-pane view models in `src/agenttower/managed_sessions/view_models.py`: row shapes for list/detail surfaces with `origin = "managed"` distinction, `failed_stage`, `predecessor_id`, `chain_depth`, `log_attached` derived fields (FR-005)
- [x] T014 [P] Implement lifecycle event emitter in `src/agenttower/managed_sessions/events.py`: 12 event types from research §R11 (`managed_layout_created`, `managed_layout_state_changed`, `managed_pane_*`, …) wired into the existing FEAT-008 JSONL audit pipeline with `origin = "managed"` (FR-015, FR-021). Enforce per-pane FIFO and per-layout FIFO ordering (FR-015 amendment); event payloads MUST redact env-var **values** whose key matches the case-insensitive closed set `*TOKEN*` / `*SECRET*` / `*KEY*` / `*PASSWORD*` (FR-021 amendment); command argv and `working_dir` are NOT redacted
- [x] T015 [P] Implement test fixtures: `tests/fixtures/managed_template_fixtures.py` (canonical 1m+2s, 2m+2s + a custom override), `tests/fixtures/managed_clock.py` (frozen-time helper), `tests/fixtures/managed_tmux_recorder.py` (records the exact tmux argv sequences for assertions)

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel.

---

## Phase 3: User Story 1 — Create a Standard Multi-Agent Layout (Priority: P1) 🎯 MVP

**Goal**: Operator selects a running bench container + template (`1m+2s` or `2m+2s`) and AgentTower creates the panes, runs configured launch commands, registers each pane as an agent, with per-container serialization and `managed_session_name_conflict` rejection.

**Independent Test**: Run `app.managed_layout_create` against a healthy bench container with a fresh `tmux_session_name`; poll `app.managed_layout_detail` until `state == "ready"`; verify three (or four) panes exist with `origin = "managed"`, expected `role`, expected `label`, registered `agent_id`. Quickstart §US1 covers this exact path.

### Tests for User Story 1

> Write tests FIRST and confirm they FAIL before implementation.

- [x] T016 [P] [US1] Contract test in `tests/contract/test_managed_layout_create.py` covering FR-001 templates, FR-002 launch overrides, FR-003 label uniqueness scope, FR-019 per-container serialization (second request waits), the `managed_session_name_conflict` rejection path (FR-016), the FR-016 character/length validation on `tmux_session_name` / `label_pattern` / `launch_command_overrides` keys (`validation_failed` before any tmux RPC), the FR-025 capacity-exceeded path at the 41st concurrent layout (`managed_layout_capacity_exceeded`), and the FR-026 no-cascade-kill rollback assertion (when one pane fails mid-create, the other panes complete and the layout-level state derives from the worst child). Use the `managed_clock.py` fixture (T015) + a recorded failing tmux RPC to assert the **FR-013 per-stage 30-second timeout and 2x retry (1s / 2s back-off) policy** fires correctly across the four pipeline stages (`pane_create`, `launch_command`, `registration`, `log_attach`); also assert that the transient-failure closed set from spec §Assumptions retries while non-transient failures (e.g., `validation_failed`, `managed_template_not_found`) surface immediately without retry
- [x] T017 [P] [US1] Contract tests for the two YAML loaders, in two parallel-safe files: (a) `tests/contract/test_managed_templates.py` covering built-in `1m+2s` + `2m+2s` shape, YAML override merge with `name`-wins precedence (FR-024), `managed_template_not_found` rejection; (b) `tests/contract/test_managed_launch_profiles.py` covering invalid YAML, missing required fields, argv-shape violations per research §R9 (`command` MUST be a list of strings, never a single shell string), lookup-by-name, operator override-by-name precedence (FR-024), and `managed_launch_command_not_found` rejection. Both tests MUST also include a **no-auto-create post-condition assertion** (FR-024 amendment): run the loader against a fresh `tmpdir` HOME where the override directories (`~/.config/opensoft/agenttower/managed_templates/`, `…/launch_commands/`) do not exist; after the loader completes, assert that neither directory was created on disk by the daemon
- [x] T018 [P] [US1] Contract test in `tests/contract/test_managed_state_machine.py` covering every legal transition + every illegal transition rejection (`degraded → ready`, `removed → *`, `* → promoted_from_adopted`) per FR-007 / state-machine.md
- [x] T019 [P] [US1] Contract test in `tests/contract/test_managed_pending_marker.py` covering marker-set-before-spawn, marker-cleared-on-ready, FEAT-004 scan skips pending-managed panes (FR-014), and FR-022 TTL sweep transitions stale markers to `failed`
- [x] T020 [P] [US1] Contract test in `tests/contract/test_managed_serializer.py` covering FR-019 FIFO ordering on same container, parallel execution across different containers, lock release on operator disconnect
- [x] T021 [P] [US1] Integration test in `tests/integration/test_story1_create_standard_layout.py` covering US1 acceptance scenarios 1–3 (1m+2s healthy, 2m+2s healthy, partial-failure recoverable lifecycle state)

### Implementation for User Story 1

- [x] T022 [US1] Implement `service.create_layout(container_id, template_name, tmux_session_name, launch_command_overrides, idempotency_key)` in `src/agenttower/managed_sessions/service.py`: acquires per-container lock (serializer), resolves template + launch profiles, inserts `managed_layout` + `managed_pane` rows (with denormalized `container_id`), sets pending-managed markers (pending_marker), composes tmux commands (tmux_create), kicks off background spawn/registration. Returns layout + pane summary after row insertion (before tmux spawn completes). Implements idempotency-key replay semantics from research §R10. MUST enforce the FR-025 capacity check (count non-terminal `managed_layout` rows; reject the 41st with `managed_layout_capacity_exceeded`). MUST apply the FR-026 no-cascade-kill rollback policy in the background spawn task: when one pane transitions to `failed`, sibling in-flight panes continue to their natural state and the layout's aggregate state derives from the worst child. MUST apply the FR-016 character/length validation on operator-supplied identifiers before any tmux RPC
- [ ] T023 [US1] Implement legacy CLI handler `managed.layout.create` (+ list / detail / pane.list / pane.detail) in `src/agenttower/managed_sessions/handlers/cli.py`: applies thin-client peer scoping per research §R12 (caller's container_id MUST match `request.container_id` else `host_only`); verifies `request.container_id` exists in the FEAT-003 container registry before calling `service.create_layout` (else `container_not_found` per contracts/managed-methods.md M1); calls into `service.py`; emits envelopes matching `FEAT-002` legacy shape; translates `ValidationFailedError` → `validation_failed` envelope and `ManagedSessionsError` → its closed-set code envelope
- [ ] T024 [US1] Implement app contract handler `app.managed_layout_create` (+ list / detail / pane.list / pane.detail) in `src/agenttower/managed_sessions/handlers/app.py`: rides FEAT-011 host-only gate (`host_only` rejection for bench-container peers); verifies `request.container_id` exists in the FEAT-003 container registry before calling `service.create_layout` (else `container_not_found`); applies FEAT-011 envelope (`ok` + `app_contract_version` + `result` / `error`); translates `ValidationFailedError` and `ManagedSessionsError` to the appropriate closed-set envelope shape
- [ ] T025 [US1] Register the new managed.* and app.managed_* handlers with the existing dispatchers: edit `src/agenttower/dispatcher.py` (FEAT-002) registration call site to import `managed_sessions.handlers.cli.register()` and `src/agenttower/app_contract/dispatcher.py` (FEAT-011) call site to import `managed_sessions.handlers.app.register()`. **This is the only existing-file modification in Phase 3.**

**Checkpoint**: US1 fully functional and independently testable. Quickstart §US1 walkthrough should run green end-to-end against a real bench container.

---

## Phase 4: User Story 2 — Auto-Prepare Created Agents for Operations (Priority: P2)

**Goal**: Every managed-created pane is automatically registered with FEAT-006, log-attached via FEAT-007, visible in the FEAT-008/009/010 surfaces (agents, routes, queues, events) with `origin = "managed"`; managed agents share the same operator workflow as adopted agents.

**Independent Test**: After US1 creates a layout, verify each managed pane appears in `app.agent.list` with `origin = "managed"`, can receive input via `app.send_input` (FEAT-009), can be routed via `app.route.add` (FEAT-010), and produces events via `app.event.list` (FEAT-008). Quickstart §US2 covers this.

### Tests for User Story 2

- [ ] T026 [P] [US2] Contract test in `tests/contract/test_managed_log_attach_failure.py` covering FR-006 (log-attach failure → pane lands in `degraded`; layout completes) and SC-003 (failure surfaces within 10s of layout completion)
- [ ] T027 [P] [US2] Contract test in `tests/contract/test_managed_launch_failure.py` covering Q8 / FR-013 (launch command immediate-exit → `degraded`, `failed_stage = launch_command`; non-recoverable cases → `failed`)
- [ ] T028 [P] [US2] Integration test in `tests/integration/test_story2_auto_prepare_operations.py` covering US2 acceptance scenarios 1–3 (managed pane has role/capability/label/state/log-attach state; output classified + routable through same event surfaces; managed + adopted coexist without separate workflows). Additionally assert: (a) **FR-015 per-pane FIFO + per-layout FIFO ordering** of lifecycle events by recording the event sequence from a layout creation and verifying that all events for any single pane / layout appear in state-transition order; (b) **FR-021 env-var redaction policy** — emit a layout whose launch profile includes env vars with keys `AWS_SECRET_TOKEN`, `MY_KEY`, `OPERATOR_PASSWORD`, `LOG_LEVEL`, `PATH`; after creation assert the JSONL audit record redacts the first three (key-match against `*TOKEN*` / `*SECRET*` / `*KEY*` / `*PASSWORD*`, case-insensitive substring) and preserves the last two **and** the argv + `working_dir` unredacted

### Implementation for User Story 2

- [ ] T029 [US2] Wire automatic FEAT-006 registration into the background spawn task started by `service.create_layout`: import `agents.service.register_self_path` and call it for each spawned pane; on success set `managed_pane.agent_id`, clear pending-managed marker, transition to `ready` (or `degraded` if a recoverable sub-step failed). Update `src/agenttower/managed_sessions/service.py`
- [ ] T030 [US2] Wire FEAT-007 log attachment into the same background spawn task: attempt log attach per pane; on failure transition the affected pane to `degraded` with `failed_stage = log_attach`; emit `managed_pane_log_attach_failed`. Update `src/agenttower/managed_sessions/service.py`
- [ ] T031 [US2] Extend `view_models.py` to surface `origin = "managed"` on the managed-pane row and ensure the existing FEAT-011 `app.agent.list` / `app.agent.detail` response shapes include `origin` for managed panes (FR-005). Edit `src/agenttower/app_contract/view_models.py` to thread `origin` through if not already, and ensure `view_models.py` (managed_sessions) is consistent
- [ ] T032 [US2] Connect lifecycle event emission to every state-machine transition in `service.py`: every `state_machine.transition()` call MUST emit the corresponding event from `events.py`; verify event order matches state-machine.md transition table
- [ ] T033 [US2] Wire managed.layout.list / .detail and managed.pane.list / .detail handlers in cli.py + app.py with proper filtering (FR-008 — managed surfaces appear alongside adopted in the existing agent/route/queue/event endpoints) and pagination default-50 / cap-200 inherited from FEAT-011
- [ ] T034 [US2] Update the FEAT-004 scan to honor the pending-managed marker: extend the existing `panes/scan.py` `list-panes -F` format to include `#{pane_title}` and skip any pane whose title starts with `@MANAGED:`. Update `src/agenttower/panes/scan.py` (this is the only FEAT-004 change required by FEAT-013, per research §R1)

**Checkpoint**: US1 + US2 both fully functional. Operator can create a layout and use every existing operational surface uniformly across managed + adopted agents.

---

## Phase 5: User Story 3 — Manage Created Pane Lifecycle (Priority: P3)

**Goal**: Operator can remove a managed pane (kill underlying tmux pane + cleanup) and recreate it with `predecessor_id` linkage; adopted panes are protected from managed-pane destructive actions; `agenttowerd` recovers managed layouts on restart and surfaces the recovery outcome from the detail surfaces.

**Independent Test**: After US1+US2, exercise quickstart §US3 — remove pane, verify tmux kill + route/log cleanup + audit retained; recreate pane, verify `predecessor_id` + fresh `agent_id`; attempt to remove an adopted pane, verify `managed_pane_protected_adopted`; restart the daemon, verify reattach and read recovery outcome via `app.managed_layout_detail`.

### Tests for User Story 3

- [ ] T035 [P] [US3] Contract test in `tests/contract/test_managed_pane_remove.py` covering FR-010 (kill underlying tmux pane, cleanup routes/logs, retain audit) including the tmux-already-killed idempotent success path
- [ ] T036 [P] [US3] Contract test in `tests/contract/test_managed_pane_recreate.py` covering FR-011 (new record with `predecessor_id` + `chain_depth + 1`), FR-023 (chain depth ≤ 16; `managed_pane_recreate_chain_too_deep` at the boundary), `managed_pane_illegal_recreate_source` for non-removed/non-failed predecessors, and FR-027 concurrent-recreate path: two recreates of the same predecessor in flight — first wins, second returns `managed_pane_concurrent_recreate` with the in-flight successor's `pane_id` in `details`
- [ ] T037 [P] [US3] Contract test in `tests/contract/test_managed_protect_adopted.py` covering FR-012 (adopted pane returns `managed_pane_protected_adopted`; adopted pane unchanged after attempted remove)
- [ ] T038 [P] [US3] Contract test in `tests/contract/test_managed_recovery.py` covering FR-020 + SC-008 (boot-time reconcile, reattach to surviving tmux panes ≤5s, no operator intervention; missing-tmux-pane → `failed_stage = recovery_reattach`)
- [ ] T039 [P] [US3] Contract test in `tests/contract/test_managed_recovery_visibility.py` covering SC-009 (recovery outcome readable from `app.managed_layout_detail` and `app.managed_pane_detail` within 5s of socket-ready; failed reattach surfaces as `state = failed` + `failed_stage = recovery_reattach` without log inspection)
- [ ] T040 [P] [US3] Contract test in `tests/contract/test_managed_promote_stub.py` covering FR-018 (promote_from_adopted returns `not_implemented` with `details.reserved_since = "FEAT-013"`; state machine `PROMOTE_FROM_ADOPTED` constant exists but is gated off)
- [ ] T041 [P] [US3] Integration test in `tests/integration/test_story3_lifecycle_operations.py` covering US3 acceptance scenarios 1–3 (remove preserves audit; recreate fresh identity + predecessor link; adopted pane unaffected by managed action)

### Implementation for User Story 3

- [ ] T042 [US3] Implement `service.remove_pane(pane_id)` in `src/agenttower/managed_sessions/service.py`: per-container lock, refuse if not in managed_pane table (`managed_pane_protected_adopted`), refuse if `state = 'creating'` (`managed_pane_illegal_transition`), `tmux kill-pane` via tmux_create (idempotent — already-killed counts as success), cleanup routes via FEAT-010, detach logs via FEAT-007, emit `managed_pane_removed`, transition state to `removed`
- [ ] T043 [US3] Implement `service.recreate_pane(predecessor_pane_id, launch_command_override, idempotency_key)` in `service.py`: validate predecessor state ∈ `{removed, failed}` (else `managed_pane_illegal_recreate_source`), enforce `chain_depth < 16` (else `managed_pane_recreate_chain_too_deep`), detect an existing in-flight successor for the same `predecessor_id` (a managed_pane row with `predecessor_id = X` in `creating` state) and reject with `managed_pane_concurrent_recreate` (FR-027), insert new managed_pane row with `predecessor_id` + `chain_depth + 1`, pending-managed marker (idempotency_key or uuid4), run the same spawn / register pipeline as create_layout, emit `managed_pane_recreated`
- [ ] T044 [US3] Implement adopted-pane protection in `service.py`: any pane_id passed to `remove_pane` / `recreate_pane` that does NOT have a `managed_pane` row returns `managed_pane_protected_adopted` with `is_adopted: true` in `details`
- [ ] T045 [US3] Implement `service.promote_from_adopted(agent_id)` stub in `service.py`: always returns `not_implemented` envelope with `details = {"reserved_since": "FEAT-013"}` (FR-018 / state-machine.md §Promotion stub)
- [ ] T046 [US3] Implement boot-time recovery reconcile in `src/agenttower/managed_sessions/recovery.py`: load every `managed_layout` + `managed_pane` row with non-terminal state, group by `container_id`, invoke `tmux_create.list_panes(container_id)`, match by `(tmux_session_name, tmux_pane_index)`, apply state-machine.md §Recovery rules (creating + marker + age<TTL → resume; creating + age≥TTL → `failed`; ready/degraded matched → reattach; no match → `failed_stage = recovery_reattach`). Emit `managed_layout_recovery_reattached` / `managed_layout_recovery_failed`. GC any stale `pending_marker_token`
- [ ] T047 [US3] Wire `recovery.reconcile()` into the daemon-boot sequence in `src/agenttower/daemon.py`: invoke BEFORE the FEAT-002 socket starts accepting requests (Principle: SC-008 + SC-009 require reattach + visibility ≤ socket-ready). Hold per-container locks during reconcile; release once complete
- [ ] T048 [US3] Wire managed.pane.remove / managed.pane.recreate / managed.pane.promote_from_adopted into cli.py + app.py with the closed-set error code list specified per method in contracts/managed-methods.md
- [ ] T049 [US3] Implement detail-surface readability for recovery outcomes in `view_models.py` and the M3/M5 response shapes: ensure `state = "failed"` + `failed_stage = "recovery_reattach"` round-trips through `app.managed_pane_detail` / `app.managed_layout_detail` exactly as documented in contracts/managed-methods.md §M3 sample variant (FR-020 / SC-009)

**Checkpoint**: US1 + US2 + US3 all functional. Daemon-restart recovery is observable from detail surfaces alone.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T050 [P] Wire `pending_marker.sweep()` into the daemon's existing periodic task scheduler (60s cadence per research §R5) and verify boot-time GC fires before the socket opens. Update `src/agenttower/daemon.py` (periodic task registration only)
- [ ] T051 [P] Integration test for the Edge Cases section bullets (container disappears mid-create, session-name collision, discovery race, log-path unreadable, partial layout retry, multi-create race, adopted-pane destructive attempt) in `tests/integration/test_managed_edge_cases.py`
- [ ] T052 [P] Run the quickstart.md walkthrough end-to-end against a real bench container; record any drift between the spec/contracts and observed behavior; file follow-up tickets if needed (no spec changes during this task — quickstart drift is a signal to fix code, not the spec)
- [ ] T053 [P] Add operator-facing documentation in `docs/managed-sessions.md`: a short overview of templates, launch profiles, and lifecycle states; the **canonical config paths** verbatim from spec §Assumptions (`~/.config/opensoft/agenttower/managed_templates/*.yaml` and `…/launch_commands/*.yaml`); the full **method list** for both namespaces (`managed.layout.create`, `managed.layout.list`, `managed.layout.detail`, `managed.pane.list`, `managed.pane.detail`, `managed.pane.remove`, `managed.pane.recreate`, `managed.pane.promote_from_adopted` and their `app.managed_*` counterparts); at least **one example managed template YAML** (mirroring the built-in `1m+2s`) and **one example launch command profile YAML** (matching the `LaunchCommandProfile` schema in data-model.md); and cross-links to spec.md / quickstart.md / contracts/managed-methods.md. Also extend `docs/app-contract-client-guide.md` (FEAT-011's existing method-list surface) with a one-section pointer to the new `app.managed_*` methods so the client guide stays the single discoverable index; README.md and CLAUDE.md require **no** method-list update (neither carries one)
- [ ] T054 Verify SC-001 (layout-create p95 ≤ 120s on a healthy bench) is measurable in CI with the new test fixtures; add a perf marker to `test_story1_create_standard_layout.py` that times the full create flow
- [ ] T055 Verify SC-008 (≤5s daemon-restart reattach for ≤4 layouts) is measurable in `test_managed_recovery.py` via a frozen-clock + recorded tmux state fixture
- [ ] T056 Verify SC-009 (≤5s post-restart recovery-outcome visibility from detail surface) is measurable in `test_managed_recovery_visibility.py` by asserting `app.managed_layout_detail` returns the recovery outcome within 5s of socket-ready

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no dependencies; can start immediately.
- **Phase 2 (Foundational)**: depends on Phase 1; **BLOCKS all user-story phases**.
- **Phase 3 (US1)**: depends on Phase 2.
- **Phase 4 (US2)**: depends on Phase 2; integrates with US1 at the runtime level but US2 tests are independently runnable (test fixtures mock the create-layout entry where US2's surfaces don't require a fresh layout).
- **Phase 5 (US3)**: depends on Phase 2; same integration story as US2.
- **Phase 6 (Polish)**: depends on US1 + US2 + US3 being complete (or at least US3 for the SC-008/SC-009 perf checks).

### Within-phase critical dependencies

- **T007** depends on **T002** (migration file must exist before the runner can register it).
- **T022** (US1 service entry) depends on Phase 2 building blocks (T005 errors, T006 state machine, T010 serializer, T011 tmux_create, T012 pending_marker, T013 view_models, T014 events). Phase 2 must be complete before any US1 implementation task can begin.
- **T029**, **T030** (US2 FEAT-006 / FEAT-007 wiring) depend on **T022** (US1 spawn pipeline) being in place.
- **T046**, **T047** (US3 recovery) depend on **T012** (pending_marker module — recovery uses the marker store) and **T022** (the spawn pipeline's row layout).
- **T050** (sweep wiring) depends on **T012** (sweep helper must exist).

### User Story Dependencies

- **US1** is the MVP: every test passes against a fresh bench container without US2 or US3.
- **US2** integrates with US1 but its contract tests use injected layouts; US2 can be developed in parallel with US3 once US1's `create_layout` pipeline is stable.
- **US3** can be developed in parallel with US2 (its tests don't require US2's log-attach or registration to be wired — they target the lifecycle actions only).

### Parallel Opportunities

- **Phase 1**: T002, T003, T004 in parallel.
- **Phase 2**: T005, T006, T008, T009, T010, T011, T012, T013, T014, T015 in parallel (10 tasks). T007 serializes against T002.
- **US1 tests** (T016–T021): all six in parallel.
- **US2 tests** (T026–T028): all three in parallel.
- **US3 tests** (T035–T041): all seven in parallel.
- **Polish** (T050, T051, T052, T053): four in parallel.
- After Foundational completes, **US1 + US2 + US3 implementation streams can run in parallel** by different developers; the only existing-module edits are at T025 (registration), T031 (`view_models.py` cross-package threading), T034 (FEAT-004 scan), and T047 (daemon boot) — coordinate those four edits via PR ordering.

---

## Parallel Example: User Story 1 tests

```bash
# Launch all 6 US1 tests together (different files, no shared state).
# T017 writes 2 sibling files in parallel (templates + launch profiles).
Task: "Contract test in tests/contract/test_managed_layout_create.py"
Task: "Contract tests for YAML loaders in tests/contract/test_managed_templates.py + tests/contract/test_managed_launch_profiles.py"
Task: "Contract test in tests/contract/test_managed_state_machine.py"
Task: "Contract test in tests/contract/test_managed_pending_marker.py"
Task: "Contract test in tests/contract/test_managed_serializer.py"
Task: "Integration test in tests/integration/test_story1_create_standard_layout.py"
```

## Parallel Example: Phase 2 Foundational

```bash
# Launch the 10 parallelizable Phase 2 tasks together:
Task: "Implement errors.py with 9 closed-set codes"
Task: "Implement state_machine.py with 5-state transition table"
Task: "Implement templates.py with built-ins + YAML loader"
Task: "Implement launch_profiles.py YAML loader"
Task: "Implement serializer.py asyncio.Lock map"
Task: "Implement tmux_create.py argv-first composer"
Task: "Implement pending_marker.py marker store + sweep helper"
Task: "Implement view_models.py row shapes"
Task: "Implement events.py FEAT-008 emitter"
Task: "Implement test fixtures (3 files)"
# T007 runs after T002 + the framework wires up
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup (T001–T004).
2. Complete Phase 2: Foundational (T005–T015).
3. Complete Phase 3: US1 (T016–T025).
4. **STOP and VALIDATE**: run quickstart §US1 end-to-end against a real bench container. Confirm `create_layout` → `ready` works, `managed_session_name_conflict` fires correctly, FR-019 serialization is observable.
5. Ship MVP / demo.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → demo "create a managed layout" (MVP).
3. US2 → demo "managed agents in the same surfaces as adopted" (operator parity).
4. US3 → demo "remove, recreate, and survive a daemon restart" (operational completeness).
5. Polish → cross-cutting: TTL sweep, edge cases, perf SLAs, docs.

### Parallel Team Strategy

After Phase 2 completes, three streams can run in parallel:

- **Developer A — US1 (T016–T025)**: owns the create-layout pipeline and the dispatcher wiring at T025.
- **Developer B — US2 (T026–T034)**: owns the auto-prepare integration; coordinates with Dev A on `view_models.py` (T031) and with the FEAT-004 owner on `panes/scan.py` (T034).
- **Developer C — US3 (T035–T049)**: owns lifecycle + recovery; coordinates with Dev A on `service.py` since Phase 5 extends it, and with the daemon owner on `daemon.py` (T047).

Polish (T050–T056) is best handled by whichever stream finishes first.

---

## Notes

- `[P]` tasks = different files, no dependencies on incomplete tasks.
- `[US?]` label maps the task to its user-story phase for traceability.
- The existing-file modifications are T002 (FEAT-001 `state/schema.py` — adds migration v9), T025 (FEAT-002 + FEAT-011 dispatchers), T031 (FEAT-011 view models cross-thread), T034 (FEAT-004 scan), T047 (daemon boot). All other tasks touch only the new `src/agenttower/managed_sessions/` sub-package, the new test files, the new example YAMLs, or the new docs file.
- The 5-minute pending-managed marker TTL (FR-022) and the 16-deep recreate chain bound (FR-023) are surfaced as explicit closed-set error / state-transition behaviors and have dedicated tests (T019 sweep, T036 chain bound).
- SC-001, SC-008, SC-009 each have a dedicated perf verification task in Phase 6 (T054, T055, T056). SC-006 testability is covered by T018 (illegal-transition rejection) + T027 (failed_stage enum exposure).
- The `promote_from_adopted` stub (FR-018) ships in MVP with `not_implemented` semantics so the contract surface is complete even though the transition is reserved for a later feature.
- FEAT-013 makes **no** change to FEAT-011's `app.hello` `capability_flags` response. The new `app.managed_*` methods are **required** FEAT-013 surfaces (not optional capabilities); clients reach them via FEAT-011's additive-evolution rule under `app_contract_version = "1.0"`. **Implementers MUST NOT add a `capability_flags` update task.** See contracts/managed-methods.md §Versioning.
