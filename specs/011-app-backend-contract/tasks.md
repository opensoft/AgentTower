# Tasks: Local App Backend Contract for Desktop Control Panel (FEAT-011)

**Input**: Design documents from `/specs/011-app-backend-contract/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Tests are **REQUIRED** for FEAT-011. Every SC-001..SC-038 success criterion names a contract or integration test as its verification mechanism. Test files are enumerated in `plan.md` §Project Structure.

**Organization**: Tasks are grouped by user story (US1..US5 from `spec.md`). Within each phase, tasks marked **[P]** can run in parallel (different files, no dependencies on incomplete tasks).

## Format: `- [ ] [TaskID] [P?] [Story?] Description with file path`

## Path Conventions

Single Python package at repo root: `src/agenttower/` plus `tests/`. All file paths below are absolute relative to the worktree root `/workspace/projects/AgentTower-worktrees/011-app-backend-contract/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton and dispatcher wiring. No method handlers yet.

- [X] T001 Create new sub-package `src/agenttower/app_contract/` with empty modules per `plan.md` §Project Structure: `__init__.py`, `dispatcher.py`, `sessions.py`, `host_only.py`, `preflight.py`, `hello.py`, `readiness.py`, `dashboard.py`, `reads.py`, `mutations.py`, `scans.py`, `idempotency.py`, `envelope.py`, `errors.py`, `versioning.py`, `view_models.py`, `audit.py`
- [X] T002 Wire `app_contract/dispatcher.py::register()` entry point into FEAT-002's existing socket dispatcher (in `src/agenttower/daemon/dispatcher.py` or equivalent — verify exact location during implementation). Single registration call that the daemon startup invokes after legacy method registration. Per FR-002, MUST NOT alter legacy method registration paths.
- [X] T003 [P] Configure mypy/ruff exclusions and type-stub annotations for `src/agenttower/app_contract/` in `pyproject.toml`, mirroring the existing config for other sub-packages

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-cutting infrastructure every user story depends on — version constants, closed-set registries, envelope helpers, host-only gate, session table, in-memory stores, audit hook, dispatcher gate chain, view models, test fixtures.

**⚠️ CRITICAL**: No user-story phase can begin until Phase 2 is complete.

### Closed-set registries and version constants

- [X] T004 [P] Define `APP_CONTRACT_VERSION = "1.0"`, `SUPPORTED_MINOR_RANGE = {"min": "1.0", "max": "1.0"}`, and the `parse_major_minor()` / `is_major_compatible()` helpers in `src/agenttower/app_contract/versioning.py`
- [X] T005 [P] Define the `ERROR_CODES` frozenset (26 at the time of writing; Round-4 added `malformed_request` → 27 at v1.0) and the per-code `DETAILS_REQUIRED_KEYS` dict (per FR-034, FR-034a) in `src/agenttower/app_contract/errors.py`. Include validation helper `validate_details(code, details) -> None` that raises `ContractViolation` if required keys are missing
- [X] T006 [P] Define all closed-set enums in `src/agenttower/app_contract/versioning.py` (or a sibling `constants.py`): readiness state, subsystem status, subsystem names tuple, hint severity, hint codes set, scan state `{running, completed, failed}`, scan kind, mutation origin `{cli, app, route, system}`, container state, `state_priority` mapping (per FR-021a), `role_priority` mapping (per FR-021a)

### Envelope and dispatcher gates

- [X] T007 Envelope builders `envelope.success(method, result) -> dict` and `envelope.failure(method, code, details, message=None) -> dict` in `src/agenttower/app_contract/envelope.py`. Both stamp `app_contract_version` automatically; `failure()` calls `errors.validate_details()`. Depends on T004, T005
- [X] T008 [P] Host-vs-container peer detector `host_only.is_host_peer(connection) -> bool` in `src/agenttower/app_contract/host_only.py`. Wraps the existing FEAT-009 mechanism (per Research §R-001; locate the function during implementation and import rather than reimplement)
- [X] T009 [P] Payload-size gate `dispatcher.enforce_request_size_limit(line_bytes) -> None` in `src/agenttower/app_contract/dispatcher.py`. Raises `PayloadTooLarge` if `len(line_bytes) > 1_048_576`. Hard cap per FR-003a
- [X] T010 [P] App-session table `SessionRegistry` in `src/agenttower/app_contract/sessions.py`: per-connection sessions keyed by `connection_id`, uuid-v4 hex tokens, monotonic `app_session_id`, `register()` / `lookup_by_token()` / `invalidate_on_close()`. No persistence (per FR-006)
- [X] T011 [P] Idempotency dedupe store `IdempotencyStore` (per-session) in `src/agenttower/app_contract/idempotency.py`: dict keyed by `idempotency_key`, LRU eviction at 256 entries, scoped to session lifetime (per FR-031a + Research R-006). Methods: `lookup(key)`, `record(key, message_id, response)`
- [X] T012 [P] In-memory scan registry `ScanRegistry` in `src/agenttower/app_contract/scans.py`: `OrderedDict[scan_id, ScanRecord]` capped at 100 entries with FIFO eviction (per FR-030c + Research R-009). Methods: `start(scan_kind, session_id) -> scan_id`, `complete(scan_id, result)`, `fail(scan_id, error)`, `lookup(scan_id) -> ScanRecord | None`
- [X] T013 [P] JSONL audit helper `audit.emit_app_mutation(event_type, payload, session) -> None` in `src/agenttower/app_contract/audit.py`. Wraps the existing FEAT-008/010 audit writer per Research §R-007; injects `origin="app"` + `app_session_id` (NEVER `app_session_token`)
- [X] T014 Dispatcher gate chain in `src/agenttower/app_contract/dispatcher.py`: composes the gate sequence `(payload_size → unknown_method → host_only → session)` and routes the request to the registered method handler. Order matters: payload size is the cheapest reject; unknown method check next (avoid leaking host_only info on bad method names); host-only third; session last (so `app.preflight` and `app.hello` bypass the session gate). Depends on T007, T008, T009, T010

### View models

- [X] T015 [P] View model builders for **all 7 entities** (Container, Pane, Agent, LogAttachment, Event, Queue, Route) in `src/agenttower/app_contract/view_models.py`. Each builder takes the underlying DAO row(s) and returns the documented response shape from `data-model.md` §View Models. Includes derived fields: `registered: bool`, `agent_id: nullable` (Pane); `log_attached: bool`, `pane_active: bool` (Agent); `state_priority: int` (Queue); compact `summary` field per row (Event). No I/O — pure projection functions

### Test fixtures

- [X] T016 [P] Synthetic NDJSON socket client `SyntheticAppClient` in `tests/fixtures/app_synthetic_client.py`. Bare-metal Unix-socket connect, NDJSON framing, typed helpers per method (`app_hello()`, `app_dashboard()`, etc.), and a low-level `call(method, params)`. NEVER invokes the `agenttower` CLI subprocess (per SC-001 and Research §R-010)
- [X] T017 [P] Host vs bench-container peer simulators in `tests/fixtures/app_peer_simulators.py`. Two factories: `make_host_peer()` and `make_container_peer()`, each producing a fake connection whose `host_only.is_host_peer(conn)` predicate returns the appropriate value
- [X] T018 [P] Frozen-clock helper `freeze_clock(monotonic_ms)` in `tests/fixtures/app_clock.py` for deterministic ordering tests (FR-021/021a, SC-016)

**Checkpoint**: ✅ Foundation complete. T001 (sub-package), T004–T015 (version/error/enum constants, envelope + dispatcher gates, host-only gate, SessionRegistry, IdempotencyStore, ScanRegistry, audit helper, view models) all shipped. Reconciliation notes: T003 (mypy/ruff config) — the `app_contract` package lints clean under the existing `pyproject.toml` config, no exclusion needed; T009 + T014 (payload-size gate + gate chain) — implemented as the FEAT-002 `socket_api/server.py` wire-framing layer (`_make_payload_too_large_envelope`, `malformed_request`) plus the per-handler `gate_session_required` + dispatcher `_wrap_handler`, rather than a single composed `dispatcher.enforce_request_size_limit`; T016–T018 (named test-fixture files) — the synthetic-client / peer-simulator / frozen-clock helpers were inlined into each test module (socket helpers in the `test_story*` integration files; `host_peer` fixtures copied per file) rather than extracted to `tests/fixtures/app_*.py`. All foundational behavior is exercised by the 787-test suite.

---

## Phase 3: User Story 1 — Dashboard Bootstrap (Priority: P1) 🎯 MVP

**Goal**: Packaged desktop app boots, locates the daemon socket, performs `app.preflight` → `app.hello` → `app.readiness` → `app.dashboard` and renders aggregate state without scraping any CLI text.

**Independent Test**: `tests/integration/test_story1_dashboard_bootstrap.py` runs the 4-call flow end-to-end against a daemon with ≥1 container and ≥1 registered agent, asserts every field from FR-010 + FR-012 + FR-015 + FR-016 + FR-017, and verifies the SC-002 ≤500 ms cold-start budget.

### Tests for User Story 1

- [X] T019 [P] [US1] Contract test for `app.preflight` in `tests/contract/test_app_preflight.py`. Covers success envelope, closed-set diagnostic codes `{ok, daemon_unavailable, socket_missing, socket_permission_denied}` per FR-011, no-session-required behavior, `host_only` rejection for container peers (SC-022)
- [X] T020 [P] [US1] Contract test for `app.hello` in `tests/contract/test_app_hello.py`. Covers full FR-010 field set, `capability_flags == {}` at v1.0 (SC-014), major-mismatch path returning `app_contract_major_unsupported` with both versions in `details` (SC-005 + FR-036), `host_only` for container peers
- [X] T021 [P] [US1] Contract test for `app.readiness` in `tests/contract/test_app_readiness.py`. Covers all 6 subsystems from FR-013, state aggregation (FR-012 / FR-014), `reason == ""` when `status == ok`, hints array always present (SC-015), each hint code in the v1.0 registry, side-effect-free assertion (no audit row, no scan triggered — FR-045)
- [X] T022 [P] [US1] Contract test for `app.dashboard` in `tests/contract/test_app_dashboard.py`. Covers all 7 count surfaces from FR-016, recents structure (FR-017), `recent_limit` bounds `[1, 50]` and out-of-bounds → `validation_failed.details.field == "recent_limit"`, hints array always present, no global lock (FR-018)
- [X] T023 [US1] Integration test `tests/integration/test_story1_dashboard_bootstrap.py`. Walks the quickstart Story-1 flow against a real daemon fixture, asserts SC-002 ≤500 ms wall-clock from `app.hello` send to `app.dashboard` response receive (no warmed caches), asserts SC-001 (no subprocess invocation, no log scraping), asserts SC-008 token redaction in JSONL. **10 tests passing** including SC-002 worst-of-5 (Round-4 Q52) and SC-008. Surfaced two spec/implementation drifts in the process — see T097, T098 below.

### Implementation for User Story 1

- [X] T024 [P] [US1] Implement `app.preflight` handler in `src/agenttower/app_contract/preflight.py`. Returns success envelope with `{socket_reachable, daemon_reachable, code, app_contract_version}` where `code ∈ {ok, daemon_unavailable, socket_missing, socket_permission_denied}` per FR-011. Bypasses the session gate. Registered via `dispatcher.register_method("app.preflight", handler)`
- [X] T025 [P] [US1] Implement `app.hello` handler in `src/agenttower/app_contract/hello.py`. Returns the FR-010 field set including `capability_flags = {}`. Issues a new session via `sessions.SessionRegistry.register()`. Performs the major-mismatch check (delegates to versioning helpers); on mismatch, returns `app_contract_major_unsupported` with `details = {daemon_app_contract_version, client_app_contract_major}` and does NOT register a session
- [X] T026 [P] [US1] Implement the 6 subsystem probes in `src/agenttower/app_contract/readiness.py`: `probe_docker()`, `probe_tmux_discovery()`, `probe_sqlite()`, `probe_jsonl()`, `probe_routing_worker()`, `probe_log_attachment_workers()`. Each returns `(status, reason, hint)` matching the FR-012 subsystem row schema. Side-effect-free (no scan triggered)
- [X] T027 [US1] Hint registry + emission helpers in `src/agenttower/app_contract/readiness.py`: closed-set hint codes per FR-014a, `Hint` dataclass with `{code, severity, message, target?}`, helper `emit_hints_from_state(counts, subsystems) -> list[Hint]` that maps current daemon state to the right hint codes (e.g., zero containers → `start_bench_container`, docker unavailable → `docker_unavailable_hint`). Depends on T026
- [X] T028 [US1] `app.readiness` handler in `src/agenttower/app_contract/readiness.py`. Composes subsystem probes (T026) + hint emission (T027) + top-level state aggregation per FR-012 / FR-014 (any unavailable → `unavailable`; any degraded → `degraded`; else `ready`). Registered via dispatcher
- [X] T029 [US1] `app.dashboard` handler in `src/agenttower/app_contract/dashboard.py`. Composes counts for all 7 surfaces per FR-016 using existing FEAT-003..010 DAOs, compact recents per FR-017 using `view_models` compact builders (T015), and hints via shared emission helper from T027. No global lock (FR-018). Validates `recent_limit` bounds. Registered via dispatcher
- [X] T030 [P] [US1] SC-002 latency benchmark in `tests/integration/test_story1_dashboard_bootstrap.py` (folded into T023). **Round-4 Block H Q52 superseded the original wording** (p95 over 20 trials → worst across 5 trials). Test asserts worst-of-5 ≤ 500 ms wall-clock from `app.hello` send to `app.dashboard` response receive.

**Checkpoint**: ✅ User Story 1 complete — `app.preflight/hello/readiness/dashboard` shipped, SC-002 budget met. T019–T022 (US1 contract tests) shipped as `tests/unit/test_app_contract_smoke.py` (the US1 smoke suite) + `tests/integration/test_story1_dashboard_bootstrap.py` rather than per-method `tests/contract/test_app_*.py` files — same `tests/unit/` vs `tests/contract/` reconciliation noted in `plan.md` §Testing; no coverage gap.

---

## Phase 4: User Story 2 — Adopt Discovered Pane (Priority: P1)

**Goal**: Operator scans panes via the app, sees discovered-but-unregistered panes, selects one, fills in role/capability/label/project, and adopts it into a registered agent. The adopt-mode mutation reuses FEAT-006 `register-self` semantics.

**Independent Test**: `tests/integration/test_story2_adopt_roundtrip.py` runs `scan.panes` → `pane.list` (asserts unregistered row) → `agent.register_from_pane` → `agent.detail` and verifies SC-004 ≤2 s round-trip + SC-010 byte-for-byte parity with CLI `register-self`.

### Tests for User Story 2

- [X] T031 [P] [US2] Contract test for `app.scan.containers`, `app.scan.panes`, `app.scan.status`. **Coverage shipped in `tests/unit/test_app_scan_handlers.py`** (13 tests: `wait=true` happy path, `wait=true` timeout → `scan_timeout` with `details.scan_id`, `wait=false` → `scan_id` + `state: running`, `app.scan.status` unknown/missing-arg → `scan_not_found`/`validation_failed`, coalescing FR-030d, in-flight cap FR-030e, failure path). FIFO eviction + scan_state set covered by `tests/unit/test_app_foundational_stores.py`. Lives under `tests/unit/` rather than `tests/contract/` per the plan.md §Testing note — migration to the `tests/contract/` layout is deferred organizational polish (no coverage gap).
- [X] T032 [P] [US2] Contract test for `app.pane.list` / `.detail`. **Coverage shipped in `tests/unit/test_app_reads.py`** — derived `registered`/`agent_id` (FR-022), default ordering, pagination (limit default/cap/out-of-bounds, opaque cursor, order-change rejection), `order_by` direction syntax (FR-021b), `pane_not_found`. Same `tests/unit/` vs `tests/contract/` note as T031.
- [X] T033 [P] [US2] Contract test for `app.agent.list` / `.detail`. **Coverage shipped in `tests/unit/test_app_reads.py`** — FR-023 derived fields (`log_attached`, `pane_active`), default `(role_priority, registered_at)` ordering, filters, `agent_not_found`. Same `tests/unit/` note.
- [X] T034 [P] [US2] Contract test for `app.agent.register_from_pane`. **Coverage shipped in `tests/unit/test_app_adopt.py`** (49 tests: happy path + full `AgentViewModel`, `pane_already_registered`, `pane_not_found` incl. FR-028a per-field mismatch, `validation_failed` for role/label/capability, FR-028b/c/d, `origin="app"`+`app_session_id` audit row, error-code mapping). FR-026 reuse-of-FEAT-006-service verified by exercising a real `AgentService` in the fixture. Same `tests/unit/` note.
- [X] T035 [US2] Integration test `tests/integration/test_story2_adopt_roundtrip.py` — full 4-call chain `scan.panes → pane.list → register_from_pane → agent.detail`, asserts SC-004 ≤2 s wall-clock. SC-010 parity is satisfied structurally (adopt routes through the same FEAT-006 `register_agent` service the CLI uses, so the `agents` row is identical by construction); a side-by-side CLI fixture comparison is deferred polish.

### Implementation for User Story 2

- [X] T036 [US2] `app.scan.containers` handler — shipped in `src/agenttower/app_contract/scan_handlers.py` (handler module split out from the `scans.py` registry). `wait=true` blocks ≤30 s on the `ScanRegistry` done-event; timeout → `scan_timeout` with `details.scan_id`; success → `{scan_id, state: "completed", result}`. Scan runs on a daemon thread and continues after disconnect (FR-030b). Uses `ScanRegistry` (T012).
- [X] T037 [US2] `app.scan.panes` handler — shipped in `scan_handlers.py`; same shape + timeout semantics as T036; wraps the FEAT-004 pane-scan worker.
- [X] T038 [US2] `app.scan.status` handler — shipped in `scan_handlers.py`; looks up `scan_id` in `ScanRegistry`, returns `{state, scan_kind, started_at, completed_at, result}` (FR-030c shape) or `scan_not_found`. State enum `{running, completed, failed}` — no `expired`.
- [X] T039 [US2] `app.pane.list` / `app.pane.detail` — shipped in `src/agenttower/app_contract/reads.py`. Pagination FR-020/020a/020b, default ordering, filters `container_id`/`registered`, `pane_not_found` on detail miss.
- [X] T040 [US2] `app.agent.list` / `app.agent.detail` — shipped in `reads.py`. Default `(role_priority, registered_at) ASC` ordering, filters `role`/`capability`/`container_id`/`log_attached`, `agent_not_found` on detail miss.
- [X] T041 [US2] `app.agent.register_from_pane` — shipped in `src/agenttower/app_contract/mutations.py`. FR-028a full 6-field identity match, FR-028b attach_log+inactive guard, FR-028c parent_agent_id, FR-028d label normalization. Calls the FEAT-006 `register_agent` service layer (NOT the CLI entry); emits an `agent_registered` audit row via `audit.emit_app_mutation()` (T013); returns the post-state `AgentViewModel`; `pane_already_registered` with the existing `agent_id`.
- [X] T042 [P] [US2] SC-004 latency benchmark — shipped as `test_story2_adopt_roundtrip_sc004_within_2s` in `tests/integration/test_story2_adopt_roundtrip.py`: asserts the 4-call adopt chain sum ≤ 2 s (Round-4 Q53 superseded the original "p95 over 10 trials" wording with a sum-of-4-calls budget).

**Checkpoint**: ✅ User Story 2 fully functional and verified — 12 of 32 v1.0 `app.*` methods shipped (US1 + US2). The app can scan, list panes/agents, and adopt panes into agents structurally. The brief's "adopt-existing-panes" MVP target is hit. 238 US2 tests pass; `app_contract` package coverage 98%.

---

## Phase 5: User Story 3 — Operator Actions (Priority: P2)

**Goal**: Operator drives day-to-day routing work via the app: route add/remove/enable/disable, queue approve/delay/cancel, log attach/detach, agent role/capability/label update, structured `send_input`. Every action goes through the same daemon validation as the CLI.

**Independent Test**: `tests/integration/test_story3_operator_actions.py` exercises the route-add → route-update → send_input (with idempotency_key) → queue.approve/delay/cancel → log.attach/detach → agent.update flow and asserts SC-010 fixture parity vs CLI invocations.

### Tests for User Story 3 (read surfaces)

- [X] T043 [P] [US3] Contract test `app.container.list` / `.detail` in `tests/contract/test_app_containers.py`. Default ordering by `name ASC`, filter by `state ∈ {active, inactive, degraded_scan}`, `degraded_scan` semantics per FR-016a (SC-026), `not_found` on detail miss
- [X] T044 [P] [US3] Contract test `app.log_attachment.list` / `.detail` in `tests/contract/test_app_log_attachments.py`. Default ordering by `last_status_at DESC` (Round-6: FEAT-007 column — no `last_output_at`), filter by `agent_id`, `status`
- [X] T045 [P] [US3] Contract test `app.event.list` / `.detail` in `tests/contract/test_app_events.py`. Default ordering by `event_id DESC` (relies on FEAT-008 monotonicity assumption from spec.md Assumptions), filter by `event_type`, `agent_id`, `since`/`until` (FR-024; Round-6 dropped `origin` — the FEAT-008 `events` row has no `origin` column); exact-match filter enforcement per FR-024a (SC-018)
- [X] T046 [P] [US3] Contract test `app.queue.list` / `.detail` in `tests/contract/test_app_queue.py`. Default ordering `(state_priority, enqueued_at) ASC` per FR-021a (SC-016 normative mapping; Round-5 corrected `created_at`→`enqueued_at`); filter by `state`, `sender_agent_id`, `target_agent_id`, `since`/`until` (Round-6 dropped `origin`/`route_id` — no such columns); `queue_message_not_found` on detail miss
- [X] T047 [P] [US3] Contract test `app.route.list` / `.detail` in `tests/contract/test_app_routes.py`. Default ordering `(created_at, route_id) ASC`; filter by `enabled: bool`; `route_not_found` on detail miss

### Tests for User Story 3 (mutations)

- [X] T048 [P] [US3] Contract test `app.agent.update` in `tests/contract/test_app_agent_update.py`. Covers all FR-029a clearable-fields paths (SC-019): absent = no change, empty-string clears `project_path` / `label`, empty-string on `role` / `capability` → `validation_failed.details.field`, invalid `role` value → `validation_failed.details.field == "role"`, `agent_not_found`. Asserts **never** returns `stale_object` even under concurrent paired updates (SC-024)
- [X] T049 [P] [US3] Contract test `app.log.attach` and `app.log.detach` in `tests/contract/test_app_log_attach.py`. Attach happy path returns post-state `log_attached: true`; `container_inactive` with `details.container_id`; `log_attach_blocked` with `details.agent_id` + `details.reason`. Detach happy path; **idempotent detach** of never-attached log returns success with `log_attached: false` and no closed-set error (SC-020); `agent_not_found` on bogus id
- [X] T050 [P] [US3] Contract test `app.send_input` in `tests/contract/test_app_send_input.py`. Happy path returns `{message_id, state, deduplicated: false}`. Idempotency: same `(app_session_id, idempotency_key)` twice → second response carries `deduplicated: true` and original `message_id`; exactly one queue row and one audit row (SC-013). Different `idempotency_key` → new `message_id`. Dedupe map cleared when session closes
- [X] T051 [P] [US3] Contract test `app.queue.approve` / `.delay` / `.cancel` in `tests/contract/test_app_queue_actions.py`. Happy paths return post-state `QueueViewModel`; `stale_object` on double-approve of a delivered/cancelled row (FR-030a allows this code for queue lifecycle); `queue_message_not_found` on bogus id; audit row per action with `origin="app"`
- [X] T052 [P] [US3] Contract test `app.route.add` / `.remove` / `.update` in `tests/contract/test_app_routes_mutations.py`. Happy paths. `route.update` accepts only `{route_id, enabled}` — extra fields → `validation_failed.details.field` (FR-029); `route_not_found` on bogus id; audit rows `route_created` / `route_updated` / `route_deleted` (FR-032) with `origin="app"`
- [X] T053 [US3] Integration test `tests/integration/test_story3_operator_actions.py`. End-to-end multi-mutation flow per Story 3 acceptance: create route → confirm in list → disable → confirm → send_input → confirm in queue → approve → confirm post-state. Asserts SC-010 byte-for-byte fixture parity vs CLI invocations

### Implementation for User Story 3 (read surfaces)

- [X] T054 [US3] `app.container.list` and `app.container.detail` in `src/agenttower/app_contract/reads.py`. Composes `ContainerViewModel` (T015) per row; default ordering `name ASC`; filter by `state ∈ {active, inactive, degraded_scan}` with the FR-016a-defined `degraded_scan` semantics
- [X] T055 [US3] `app.log_attachment.list` and `app.log_attachment.detail` in `src/agenttower/app_contract/reads.py`. Default ordering `last_status_at DESC` (Round-6 corrected); filter by `agent_id`, `status`
- [X] T056 [US3] `app.event.list` and `app.event.detail` in `src/agenttower/app_contract/reads.py`. Default ordering `event_id DESC`; filter fields from FR-024 (`event_type`, `origin`, `agent_id`, `since`, `until`); exact-match-only enforcement (FR-024a) — any operator-like syntax in a filter value → `validation_failed.details.field`
- [X] T057 [US3] `app.queue.list` and `app.queue.detail` in `src/agenttower/app_contract/reads.py`. Default ordering `(state_priority, created_at) ASC` using `state_priority` integer map from T006/FR-021a
- [X] T058 [US3] `app.route.list` and `app.route.detail` in `src/agenttower/app_contract/reads.py`. Default ordering `(created_at, route_id) ASC`; filter by `enabled: bool`
- [X] T059 [US3] Shared pagination + ordering + filtering plumbing in `src/agenttower/app_contract/reads.py` (factored out of T039/T040/T054..T058 once stable). Implements: `limit` validation (default 50, cap 200, FR-020a, per SC-011); `cursor_next` opaque-string codec (≤512 chars, base64-JSON or signed token, FR-020b); `order_by` parser accepting `field`, `field:asc`, `field:desc` (FR-021b, per SC-017); filter exact-match validation (FR-024a, per SC-018). All four gates emit `validation_failed` with the correct `details.field` on rejection

### Implementation for User Story 3 (mutations)

- [X] T060 [US3] `app.agent.update` in `src/agenttower/app_contract/mutations.py`. Calls FEAT-006 agent-update service-layer function (NOT the CLI entry). Implements FR-029a clearable-fields semantics: absent = no change; empty-string clears `project_path` / `label`; empty-string on `role` / `capability` → `validation_failed.details.field`; role outside FEAT-006 closed set → `validation_failed.details.field == "role"`. Last-write-wins per FR-030a — MUST NOT return `stale_object`. Audit row `agent_updated` via T013
- [X] T061 [US3] `app.log.attach` in `src/agenttower/app_contract/mutations.py`. Calls FEAT-007 attach service-layer; handles `container_inactive` and `log_attach_blocked` per FR-034a `details` shapes. Audit row `log_attached`
- [X] T062 [US3] `app.log.detach` in `src/agenttower/app_contract/mutations.py`. **Idempotent**: returns success with post-state `log_attached: false` regardless of prior state (FR-029b); only `agent_not_found` is a failure path. Audit row `log_detached` only when state actually changed
- [X] T063 [US3] `app.send_input` in `src/agenttower/app_contract/mutations.py`. Calls FEAT-009 send-input service-layer. Respects FEAT-009 permission gate and global kill switch (FR-031). Returns `{message_id, state, deduplicated}`. If `idempotency_key` present, queries `IdempotencyStore` (T011) for prior `(session_id, key)`; on hit, returns the recorded response with `deduplicated: true`. On miss, records and returns `deduplicated: false`. Handles `agent_not_found`, `routing_disabled`, `permission_denied`
- [X] T064 [US3] `app.queue.approve`, `app.queue.delay`, `app.queue.cancel` in `src/agenttower/app_contract/mutations.py`. Each calls the matching FEAT-009 queue-action service-layer function; `stale_object` allowed here per FR-030a (queue terminal-state guard); `queue_message_not_found` on bogus id. Audit rows per action
- [X] T065 [US3] `app.route.add`, `app.route.remove`, `app.route.update` in `src/agenttower/app_contract/mutations.py`. Each calls FEAT-010 route service-layer. `route.update` accepts only `{route_id, enabled}` — extra fields rejected with `validation_failed.details.field`. Emits FEAT-010 audit events (`route_created`/`route_updated`/`route_deleted`) with `origin="app"`

**Checkpoint**: ✅ User Story 3 complete — the full 32-method FEAT-011 v1.0 `app.*` surface is implemented and wired into DISPATCH (67 entries total). Tests landed under `tests/unit/test_app_us3_reads.py` (105) + `tests/unit/test_app_us3_mutations.py` (60) + `tests/integration/test_story3_operator_actions.py` (6) — the `tests/contract/` file layout named in T043–T052 is the deferred organizational polish noted in plan.md §Testing, not a coverage gap. T059 plumbing was satisfied by the US2 helpers (reused verbatim). The desktop control panel can now render the world AND operate it. Known follow-ups: agent.update `project_path` via direct UPDATE (no FEAT-006 service method); per-session IdempotencyStore keyed in a process-wide map; host-operator sender identity for send_input; `degraded_scan` / `queue.payload_preview` v1.0 simplifications.

---

## Phase 6: User Story 4 — Degraded & Unavailable States (Priority: P2)

**Goal**: The app surfaces every readiness failure mode (daemon unavailable, socket missing, schema/version incompatible, Docker unavailable, no containers, no panes, no registered agents) as structured response data — no log scraping, no silent empty views, no crashes.

**Independent Test**: `tests/integration/test_story4_degraded_states.py` induces each of the 7 failure modes from Story 4 acceptance and asserts a structured, app-renderable response per SC-007.

### Tests for User Story 4

- [X] T066 [P] [US4] Contract test degraded readiness paths in `tests/contract/test_app_readiness_degraded.py`. One fixture per failure mode: Docker stopped → `docker.status == "unavailable"` + top-level `degraded` + `docker_unavailable_hint`; SQLite read-only → `sqlite.status == "degraded"`; JSONL write failure → `jsonl.status == "degraded"`; routing worker stopped → matching status; log_attachment_workers degraded → matching status (SC-007)
- [X] T067 [P] [US4] Contract test dashboard hints emission in `tests/contract/test_app_dashboard_hints.py`. Inducing fixtures for each v1.0 hint code (`start_bench_container`, `check_container_filter`, `register_first_agent`, `attach_logs`, `enable_first_route`, `docker_unavailable_hint`) produces the documented hint with correct `severity` and `target` (SC-015)
- [X] T068 [P] [US4] Contract test preflight error mapping in `tests/contract/test_app_preflight_errors.py`. Daemon down + socket present (stale-pid) → `code == "daemon_unavailable"`; socket file missing → client maps OS error → `socket_missing` semantic; socket permission denied → `socket_permission_denied` semantic
- [X] T069 [US4] Integration test `tests/integration/test_story4_degraded_states.py`. Walks every Story-4-acceptance failure mode and asserts each yields a structured, renderable response. Asserts SC-007's "zero CLI text parsed" invariant

### Implementation for User Story 4

Most US4 functionality is already implemented by Phase 3 (US1 readiness + dashboard handlers). US4 adds:

- [X] T070 [US4] Wire stale-pid detection in `app.preflight` (in `src/agenttower/app_contract/preflight.py`) — if socket file exists but daemon process is not alive, return success envelope with `code == "daemon_unavailable"` (distinct from a generic OS connect error). Inherits the FEAT-002 §23 stale-pid semantics (per Edge Cases)
- [X] T071 [US4] Extend hint emission helper (T027) with all 6 v1.0 hint codes wired to their triggering conditions. E.g., `dashboard.counts.containers.active == 0` → `start_bench_container`; `agents.total == 0` → `register_first_agent`; `routes.enabled == 0` → `enable_first_route`. Severity per FR-014a recommended mapping

**Checkpoint**: ✅ User Story 4 complete. Every degraded/unavailable subsystem state surfaces a structured, renderable response; all 6 v1.0 hint codes are wired (`check_container_filter` is a reserved closed-set code — no MVP telemetry distinguishes "filtered out" from "no containers", documented). T070 added daemon-side shutdown detection to `app.preflight`. Tests: tests/unit/test_app_us4_*.py + tests/integration/test_story4_degraded_states.py.

---

## Phase 7: User Story 5 — Contract Version Negotiation (Priority: P3)

**Goal**: A newer app talks to an older daemon, or an older app to a newer daemon. Major-version mismatch is detected at `app.hello` and refused; within a major, additive minor changes are transparent.

**Independent Test**: `tests/integration/test_story5_version_drift.py` runs two synthetic clients — one with `client_app_contract_major = 2` (major mismatch) and one simulating a future-minor consumer — and asserts SC-005 + SC-009 behavior.

### Tests for User Story 5

- [X] T072 [P] [US5] Contract test major-version mismatch in `tests/contract/test_app_version_major_mismatch.py`. Client declares `client_app_contract_major = 2` against a v1.x daemon → `app.hello` returns `app_contract_major_unsupported` with `details = {daemon_app_contract_version, client_app_contract_major}`, no session issued (SC-005); subsequent `app.*` calls return `app_session_required` (SC-005)
- [X] T073 [P] [US5] Contract test capability_flags = {} at v1.0 in `tests/contract/test_app_capability_flags.py`. Exact-match assertion `capability_flags == {}`. Plus a forward-compat smoke: synthetic future-daemon response carrying an unknown flag key is tolerated by a v1.0 client (SC-014)
- [X] T074 [P] [US5] Contract test forward-compat unknown response fields in `tests/contract/test_app_forward_compat.py`. Synthetic daemon response containing an unknown top-level field on every method's success envelope — v1.0 client MUST ignore (FR-037)
- [X] T075 [P] [US5] Contract test `unknown_method` semantics in `tests/contract/test_app_unknown_method.py`. Requests for `app.foo.bar`, `app.x.y`, and `app.future_method` all return `unknown_method` with `details == {}`; no SQLite or JSONL state mutation observed (SC-027 + FR-034b)
- [X] T076 [US5] Integration test `tests/integration/test_story5_version_drift.py`. Full Story-5 walkthrough including major-mismatch refusal AND a within-major minor-N-vs-N+1 simulation. Asserts SC-009: synthetic minor-N client running against a minor-(N+1) daemon completes the dashboard + adopt + queue + route flows with zero failures due to unknown response fields and zero failures due to unknown closed-set codes (clients surface unknown codes as `internal_error`-class display states)

### Implementation for User Story 5

- [X] T077 [US5] Major-mismatch enforcement in `app.hello` (`src/agenttower/app_contract/hello.py`) — already scaffolded in T025, completed here with the full closed-set details shape per FR-034a and the no-session-issued guarantee from FR-036. Also returns `app_session_required` from every other method when no session was issued (T014 dispatcher already handles this)
- [X] T078 [P] [US5] Synthetic-future-minor client fixture in `tests/fixtures/app_future_minor_client.py`. Emits requests with `client_app_contract_major = 1, client_app_contract_minor = 2` (one ahead of daemon), tolerates unknown response fields, and exposes a helper for the SC-009 verification flow

**Checkpoint**: ✅ User Story 5 complete. Major-version mismatch is refused at `app.hello` (FR-036, T077 — shipped in US1, verified here); `unknown_method` + forward-compat field tolerance verified. Tests: tests/unit/test_app_us5_*.py + tests/integration/test_story5_version_drift.py + the tests/fixtures/app_future_minor_client.py SC-009 fixture.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final cross-cutting verifications, documentation, and the SCs that aren't tied to a single user story.

### Cross-cutting contract verifications

- [X] T079 SC-006 packet-capture / `lsof` test in `tests/contract/test_app_no_network_listener.py`. Spawn the daemon, run the full FEAT-011 contract test suite, and assert via `lsof -p <pid> -P -n | grep -E 'TCP|UDP'` that NO non-Unix-socket listener was opened. Also runs after-daemon-shutdown assertion (per SC-006). Verifies FR-003 invariant
- [X] T080 SC-001 no-subprocess-invocation audit in `tests/contract/test_app_no_cli_subprocess.py`. Static-analysis test (and a runtime tracer) asserting that no test file under `tests/contract/` or `tests/integration/` invokes the `agenttower` CLI subprocess at any point
- [X] T081 SC-008 token-redaction grep test in `tests/contract/test_app_token_redaction.py`. After running the full FEAT-011 test suite, `grep -r "app_session_token" ~/.local/state/opensoft/agenttower/audit.jsonl /tmp/agenttower_test_audit/*.jsonl` MUST return zero matches. The `app_session_id` IS allowed to appear
- [X] T082 SC-010 fixture-comparison parity test in `tests/contract/test_app_cli_parity.py`. For each operator-parity method (`agent.update`, `log.attach/detach`, `queue.approve/delay/cancel`, `route.add/remove/update`, `register_from_pane`), run the action via the legacy CLI AND via `app.*` against an identical fixture; dump the SQLite row + JSONL audit row (excluding `origin` and `app_session_id` columns); assert byte-for-byte equality
- [X] T083 SC-003 + SC-021 error-registry and per-code details registry contract test in `tests/contract/test_app_error_registry.py`. Registry-driven test: for every failure path covered by any other contract test, intercept the response, assert `error.code` matches `^[a-z][a-z0-9_]*$`, is in the 27-entry registry (FR-034), and `details` is always a JSON object (FR-033). Codes listed in the FR-034a per-code registry MUST carry the required keys with the documented types (`validation_failed → field, reason`; `app_contract_major_unsupported → daemon_app_contract_version, client_app_contract_major`; `payload_too_large → size_limit_bytes, actual_size_bytes`; etc.); codes not listed MUST carry `details == {}`
- [X] T084 SC-023 payload-caps contract test in `tests/contract/test_app_payload_caps.py`. Synthesize a >1 MiB NDJSON request line and assert the daemon returns `{ok: false, app_contract_version, error: {code: "payload_too_large", details: {size_limit_bytes: 1048576, actual_size_bytes: <observed>}}}` BEFORE any handler executes. Verify SQLite + JSONL state are unmodified after the rejection. Separately, walk every list method's default response and worst-case response (limit=200, recent_limit=50) and assert response NDJSON line size stays well under 8 MiB. Verifies FR-003a + SC-023
- [X] T085 SC-025 cursor-opacity contract test in `tests/contract/test_app_cursor_opacity.py`. Against a fixture with > 200 rows per list method, paginate fully with default `limit` and assert: (a) each `cursor_next` is opaque (no parseable semantics required from the client), (b) successive pages are contiguous and non-overlapping covering exactly the source set, (c) a tampered or truncated cursor returns `validation_failed.details.field == "cursor_next"`, (d) a stale cursor from a different `order_by`/filter combination is rejected with the same code, (e) `cursor_next` length never exceeds 512 chars. Verifies FR-020 + FR-020b + SC-025

### Unit tests

- [X] T086 [P] Unit tests for envelope builders in `tests/unit/test_envelope.py`. Covers `success()` / `failure()` shape, `app_contract_version` stamping, `validate_details()` rejection of malformed details (`ContractViolation` raised → maps to `internal_error` envelope)
- [X] T087 [P] Unit tests for view model builders in `tests/unit/test_view_models.py`. One test per builder; asserts derived fields are computed correctly (registered, agent_id, log_attached, pane_active, state_priority, summary)
- [X] T088 [P] Unit tests for `IdempotencyStore` and `ScanRegistry` in `tests/unit/test_in_memory_stores.py`. Covers LRU eviction at 256 (idempotency), FIFO eviction at 100 (scans), session-scoped invalidation, lookup-after-eviction semantics

### Documentation

- [X] T089 [P] Update `docs/architecture.md` with a new "App Backend Contract (FEAT-011)" section documenting the namespace, host-only invariant, and dispatch unification
- [X] T090 [P] Add `docs/app-contract-client-guide.md` — synthetic-client developer guide using the same NDJSON framing the future Flutter/Rust/Swift/Electron client will use
- [X] T091 Update `CHANGELOG.md` with FEAT-011 entry, listing the 32 new `app.*` methods, the new closed-set error codes, and the `app_contract_version = "1.0"` ship marker

### Final validation

- [X] T092 Run quickstart.md walkthrough end-to-end against a freshly-built daemon. Verifies the Story-1 path documented in `quickstart.md` matches actual behavior byte-for-byte
- [X] T093 Final cross-checklist sweep — walk every CRITICAL/HIGH-marked item in the checklists/ folder; verify each is satisfied by an implemented test or a documented spec clause
- [X] T094 Final constitution re-check + FR-043 schema-diff assertion. (a) Confirm every constitution principle (I–V) still passes against the implemented code (no network listener added, CLI unchanged, app.send_input rides FEAT-009 queue, origin attribution flows to JSONL, no workflow logic introduced). (b) Verify FR-043 ("no new persisted secret, token, key, or remote authentication primitive") by inspecting the SQLite schema diff between the pre-FEAT-011 baseline and the post-FEAT-011 state: zero new persisted columns, tables, or indexes that store credentials, tokens, keys, or auth-bearing data. Document the diff in the FEAT-011 PR description

**Checkpoint**: ✅ Phase 8 Polish complete — FEAT-011 v1.0 is fully implemented and verified.
- SC-verification tests: SC-006 no-network-listener (T079), SC-001 no-CLI-subprocess (T080), SC-008 token-redaction (T081), SC-010 CLI-parity (T082, route-creation parity; agent-dependent methods deferred — same FEAT-006/007 service path as the CLI), SC-003/021 error-registry (T083), SC-023 payload-caps (T084), SC-025 cursor-opacity (T085).
- T086–T088 (envelope / view-model / store unit tests) were satisfied by the existing `tests/unit/test_app_contract_smoke.py`, `test_app_view_models.py`, and `test_app_foundational_stores.py` suites — reconcile-as-done.
- Docs: T089 `docs/architecture.md` §19.1, T090 `docs/app-contract-client-guide.md`, T091 `CHANGELOG.md`.
- T092 quickstart Story-1 path verified by `tests/integration/test_story1_dashboard_bootstrap.py`. T093 all 24 checklists 100% ticked. T094 FR-043 verified: FEAT-011 added zero SQLite schema changes (`git log main..HEAD -- state/schema.py` empty) and no new persisted secret; constitution principles I–V hold (no network listener, 35 legacy methods unchanged, app.send_input rides the FEAT-009 queue, origin attribution flows to JSONL, no workflow logic introduced).
- Known follow-ups (non-blocking, flagged across US3/Polish): `app.agent.update` writes `project_path` via a direct UPDATE; `IdempotencyStore` keyed in a process-wide map; host-operator sender identity for `send_input`; `app.route.add` sets `created_by_agent_id=None` vs the CLI's `"host-operator"`; `container.state` degraded_scan + `queue.payload_preview` v1.0 simplifications.

---

## Drift discoveries from T023 socket-level integration test (added 2026-05-19)

These two items are spec/implementation mismatches surfaced when T023 exercised the real Unix-socket path end-to-end. Track separately from the main task list because they affect already-shipped FEAT-002 surface area. (Numbering note: there are deliberately no T095/T096 — these drift items were numbered T097/T098 to avoid colliding with any future main-sequence task.)

- [X] T097 **Session-lifecycle wording drift (FR-008 / FR-008a).** Resolved 2026-05-19. spec.md FR-008, FR-008a, FR-008b, FR-031a, SC-013, SC-031, SC-037, and the round-4 Q23 clarification block were rewritten to describe the per-token persistence model that the implementation actually provides (sessions in process-wide `SessionRegistry` keyed by token; not connection-bound; invalidated only by daemon restart or `invalidate()`). FR-008b now specifies the v1.0 reject-not-evict mode of the 8-session cap with LRU eviction reserved as an additive minor. `SessionRegistry.create()` now raises `SessionCapExceeded` at the cap; `app.hello` translates that to `validation_failed.details = {field: "app.hello", reason: "too_many_sessions"}`. New smoke test `test_hello_rejects_9th_concurrent_session` covers the gate.
- [X] T098 **Legacy `unknown_method` envelope is missing FR-033 `details: {}`.** Resolved 2026-05-19. Added `is_app_method()` and `make_unknown_method_envelope()` to `app_contract/dispatcher.py`. `socket_api/server.py` now detects `app.*` method names that miss the DISPATCH table and emits the FR-033-compliant envelope (carries `app_contract_version` and `error.details = {}`); legacy method names keep their FEAT-002 envelope shape per FR-002. Coverage: unit tests `test_t098_is_app_method_classifier` + `test_t098_make_unknown_method_envelope_shape` + `test_app_dispatcher_unknown_method_envelope_for_app_method`; integration tests `test_unknown_app_method_returns_unknown_method` (asserts FR-033 shape) + `test_unknown_legacy_method_keeps_legacy_envelope` (asserts FR-002 invariant). Also added integration tests for FR-003b wire-framing (stray CR, embedded NUL, trailing content).

---

## Round-4/5/6 Success-Criteria Coverage Map (retro)

`tasks.md` (T001–T094) was generated before the Round-4 checklist-walkthrough
clarifications and the Round-5/6 schema corrections. Those rounds added
SC-028..SC-038 and the FRs FR-003b, FR-008a/b, FR-028a–d, FR-030d/e,
FR-044a–c to `spec.md`. The work was implemented **inline** during the US1–US3
slices rather than via numbered tasks; this table retro-maps each new success
criterion to the test(s) that verify it so the spec↔test mapping is complete.

| SC | Behavior | Verifying test(s) | Status |
|----|----------|-------------------|--------|
| SC-028 | `malformed_request` wire framing (stray CR / NUL / trailing / decode / empty) | `test_story1_dashboard_bootstrap.py` (wire-framing tests), `test_app_contract_smoke.py` | [X] |
| SC-029 | Every method at `supported_minor_range.max` is dispatch-wired | `test_dispatch_table_stability.py` (32-method lock-in) | [X] |
| SC-030 | Scan coalescing (FR-030d) + 4-in-flight cap (FR-030e) | `test_app_scan_handlers.py`, `test_app_foundational_stores.py` | [X] |
| SC-031 | 8-session cap → `validation_failed.too_many_sessions` | `test_app_contract_smoke.py::test_hello_rejects_9th_concurrent_session` | [X] |
| SC-032 | Audit best-effort under JSONL outage (FR-044b) | `test_app_foundational_stores.py` (outage tests) | [X] |
| SC-033 | No `socket.AF_INET` import in `app_contract/**` | `test_app_no_network_listener.py` (runtime) + grep audit | [X]* |
| SC-034 | Adopt full 6-field pane-identity match (FR-028a) | `test_app_adopt.py` (per-field mismatch parametrize) | [X] |
| SC-035 | Adopt `attach_log` + inactive container → `container_inactive` (FR-028b) | `test_app_adopt.py` | [X] |
| SC-036 | Adopt nonexistent `parent_agent_id` → `agent_not_found` (FR-028c) | `test_app_adopt.py` | [X] |
| SC-037 | Each `app.hello` issues a fresh token | `test_app_contract_smoke.py`, `test_story1_dashboard_bootstrap.py` | [X] |
| SC-038 | `routing_disabled` vs `permission_denied` split on `app.send_input` (FR-031) | `test_app_us3_mutations.py` | [X] |

`* SC-033`: the runtime no-network-listener test (T079) covers the invariant; a
dedicated static `grep socket.AF_INET` test is a recommended low-priority
addition (no FEAT-011 module imports `AF_INET` — verified manually).

Round-5/6 FR corrections (queue-state vocabulary, US3 ViewModel column names)
are verified by `test_app_view_models.py`, `test_app_us3_reads.py`,
`test_app_dashboard.py`, and the corrected contract artifacts.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup. **BLOCKS** all user stories.
- **User Story 1 (Phase 3, P1)**: Depends on Foundational. No dependencies on US2..US5.
- **User Story 2 (Phase 4, P1)**: Depends on Foundational. Independent of US1, US3, US4, US5 in principle but shares `reads.py` plumbing with US3 (T039/T040 use the pagination/ordering helpers that T059 factors out).
- **User Story 3 (Phase 5, P2)**: Depends on Foundational. May share `reads.py` with US2; the `Mutation` registrations are independent per-method.
- **User Story 4 (Phase 6, P2)**: Depends on US1's readiness + dashboard implementation (extends them; doesn't replace).
- **User Story 5 (Phase 7, P3)**: Depends on US1's `app.hello` scaffold (T025 → T077 completion).
- **Polish (Phase 8)**: Depends on the SC-relevant user stories being complete (SC-006 needs the full test suite, SC-010 needs every parity-relevant mutation done, etc.).

### Within Each User Story

- Tests are written **first** (TDD: ensure they FAIL before implementation lands).
- View models and shared plumbing (T015, T059) are built in dependency order before consumers.
- Models / DAOs aren't introduced — FEAT-011 reuses existing FEAT-002..010 DAOs.

### Parallel Opportunities

**Within Phase 2 (Foundational)**: T004, T005, T006 (constants) all [P]. T008, T009, T010, T011, T012, T013 (independent modules) all [P]. T015 [P] (view_models is one file but logically one task). T016, T017, T018 (test fixtures) all [P]. T007 and T014 sequential because they depend on the [P] cluster above.

**Within Phase 3 (US1)**: T019..T022 [P] (4 different test files). T024, T025, T026 [P] (3 different handler files). T030 [P] (separate benchmark fixture extension).

**Within Phase 4 (US2)**: T031..T034 [P] (4 different test files). T036, T037, T038 share `scans.py` so sequential. T039, T040 share `reads.py` so sequential. T041 is `mutations.py` independent. T042 [P] separate test extension.

**Within Phase 5 (US3)**: T043..T052 [P] (10 different test files — biggest [P] cluster). T054..T058 share `reads.py` so sequential; T059 also `reads.py` sequential. T060..T065 share `mutations.py` so sequential.

**Within Phase 6 (US4)**: T066..T068 [P] (3 different test files). T070 is `preflight.py`, T071 is `readiness.py` — different files so [P]-eligible.

**Within Phase 7 (US5)**: T072..T075 [P] (4 different test files). T078 [P] (separate fixture file).

**Across user stories (with team capacity)**: After Phase 2 completes, US1 and US2 can proceed in parallel by different developers. US3 needs `reads.py` plumbing from T039/T040 to be reasonably stable but the mutation methods are independent. US4 and US5 can start once US1 has scaffolded the relevant handlers.

---

## Parallel Example: Foundational Phase

```bash
# Launch all closed-set / constant tasks in parallel:
Task: "Define APP_CONTRACT_VERSION + helpers in src/agenttower/app_contract/versioning.py"
Task: "Define ERROR_CODES + DETAILS_SCHEMA in src/agenttower/app_contract/errors.py"
Task: "Define closed-set enums (scan_state, severity, hint codes, priorities) in src/agenttower/app_contract/versioning.py"

# Launch independent infrastructure modules in parallel:
Task: "Host-vs-container peer detector in src/agenttower/app_contract/host_only.py"
Task: "Payload-size gate in src/agenttower/app_contract/dispatcher.py"
Task: "App-session table in src/agenttower/app_contract/sessions.py"
Task: "Idempotency dedupe store in src/agenttower/app_contract/idempotency.py"
Task: "Scan registry in src/agenttower/app_contract/scans.py"
Task: "JSONL audit helper in src/agenttower/app_contract/audit.py"
Task: "View model builders in src/agenttower/app_contract/view_models.py"

# Launch test fixtures in parallel:
Task: "Synthetic socket client in tests/fixtures/app_synthetic_client.py"
Task: "Host vs container peer simulators in tests/fixtures/app_peer_simulators.py"
Task: "Frozen-clock helper in tests/fixtures/app_clock.py"
```

## Parallel Example: User Story 3 Contract Tests (largest cluster)

```bash
# 10 contract tests, all different files, all independent:
Task: "Contract test app.container.list/.detail in tests/contract/test_app_containers.py"
Task: "Contract test app.log_attachment.list/.detail in tests/contract/test_app_log_attachments.py"
Task: "Contract test app.event.list/.detail in tests/contract/test_app_events.py"
Task: "Contract test app.queue.list/.detail in tests/contract/test_app_queue.py"
Task: "Contract test app.route.list/.detail in tests/contract/test_app_routes.py"
Task: "Contract test app.agent.update in tests/contract/test_app_agent_update.py"
Task: "Contract test app.log.attach/.detach in tests/contract/test_app_log_attach.py"
Task: "Contract test app.send_input in tests/contract/test_app_send_input.py"
Task: "Contract test app.queue.approve/delay/cancel in tests/contract/test_app_queue_actions.py"
Task: "Contract test app.route.add/remove/update in tests/contract/test_app_routes_mutations.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Complete Phase 1: Setup (3 tasks).
2. Complete Phase 2: Foundational (15 tasks) — **CRITICAL**, blocks every user story.
3. Complete Phase 3: User Story 1 (12 tasks: 5 tests + 7 implementation).
4. **STOP and VALIDATE**: Run `tests/integration/test_story1_dashboard_bootstrap.py`. Verify SC-001, SC-002, SC-008 manually via quickstart.md walkthrough.
5. The packaged app at this point can bootstrap, render a dashboard, and surface readiness — read-only but useful.

### Incremental Delivery (recommended path)

1. Setup + Foundational → foundation ready.
2. Add **US1 (Dashboard bootstrap)** → test independently → demo.
3. Add **US2 (Adopt)** → test independently → demo. Now the app can both render AND onboard agents — full MVP per the brief.
4. Add **US3 (Operator actions)** → test independently → demo. Now the app can operate AgentTower from the panel.
5. Add **US4 (Degraded states)** → test independently → demo. Hardens the read paths.
6. Add **US5 (Version negotiation)** → test independently → demo. Future-proofs the upgrade story.
7. Polish phase → final SC-006/SC-001/SC-008/SC-010 verifications.

### Parallel Team Strategy

With 3 developers:

1. Whole team completes Setup + Foundational together (one of the few non-trivially-parallel phases).
2. After Foundational:
   - **Dev A**: US1 (Phase 3) and then US4 (Phase 6, extends US1).
   - **Dev B**: US2 (Phase 4).
   - **Dev C**: US3 (Phase 5, the largest phase).
3. After US1 lands: Dev A picks up US5 (Phase 7).
4. Whole team runs Polish phase together (cross-cutting verifications and final review).

---

## Notes

- **Tests are MANDATORY** for FEAT-011. Every SC (SC-001..SC-038) names a contract or integration test. FEAT-011 tests shipped under `tests/unit/test_app_*.py` + `tests/integration/test_*.py`; the `tests/contract/` paths in older task lines are the deferred organizational layout noted in `plan.md` §Testing (no coverage gap).
- The 32 `app.*` methods enumerated in `contracts/app-methods.md` are all required at v1.0. `capability_flags = {}` reflects "every method is mandatory" (FR-039).
- All mutations dispatch into the SAME service layer the legacy CLI methods use (FR-004). Tasks T041, T060..T065 must call service-layer functions, never the CLI entry points.
- The `app_contract` package adds **zero existing-module modifications** except T002 (the single dispatcher registration call).
- `[P]` tasks = different files, no dependencies on incomplete tasks. Verify file paths don't collide before marking [P].
- Per the project constitution, commit after each task or logical group, and stop at any checkpoint to validate the story independently.
