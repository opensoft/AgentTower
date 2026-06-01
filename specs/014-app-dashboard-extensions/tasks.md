---

description: "Task list for FEAT-014 App Dashboard Extensions (v1.1)"
---

# Tasks: App Dashboard Extensions (v1.1)

**Input**: Design documents from `specs/014-app-dashboard-extensions/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/dashboard-v1_1.md ✓, contracts/closed-sets-v1_1.md ✓, quickstart.md ✓

**Tests**: REQUIRED. The spec mandates tests (FR-017 + SC-001..SC-007), so every story phase includes test tasks ahead of implementation tasks (write-test → see-fail → implement).

**Organization**: Tasks grouped by user story (US1 P1 → US4 P4). Within each story, tests precede implementation. Each story is independently completable on top of the foundational phase.

## Format: `[ID] [P?] [Story] Description with file path`

- **[P]**: Parallelizable within the same phase (different files, no upstream-task dependency).
- **[Story]**: `[US1]`/`[US2]`/`[US3]`/`[US4]`. Setup, Foundational, and Polish tasks carry no story label.
- File paths are repository-relative per the host-path rule in `AGENTS.md`.

## Path Conventions

- Source code: `src/agenttower/...` (single Python package — see plan.md §Project Structure).
- Tests: `tests/{unit,integration}/...` at repo root. (No `tests/contract/` directory in this repo — all FEAT-011 contract assertions live under `tests/unit/`; see the v1.1 marker rule in §Notes for how the v1.0-compat replay filters FEAT-014's additions.)
- Specs / contracts / docs: `specs/014-app-dashboard-extensions/...` (this folder).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the branch and the FEAT-011 baseline are in the state plan.md assumes. No new dependencies, no init — FEAT-014 is an additive extension to an existing package.

- [x] T001 Confirm branch is `014-app-dashboard-extensions` and FEAT-011 modules `src/agenttower/app_contract/{dashboard,view_models,versioning}.py` exist with the contract surface plan.md depends on. (T001 verifies the FEAT-011 surface; `view_models.py` is referenced for existence only — FEAT-014 does NOT modify it. Per analyze D-DRIFT-1, FEAT-014's two new aggregators live in `dashboard.py` alongside the v1.0 count helpers, not in `view_models.py` which is pure entity-row projection.) The FEAT-011 dashboard latency budget (`app.dashboard` cold-start-to-dashboard ≤ 500 ms, no-cache, ≥1 container, ≥1 agent fixture — per FEAT-011 SC-002) is referenced inline by T024; no separate "record" step is required.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: One small change that gates every v1.1 field appearing on the wire — without bumping the advertised contract version, every v1.1 field below is invisible (or worse, a contract violation if emitted under a "1.0" advertisement).

**⚠️ CRITICAL**: No user story work should land on a release branch until T002 ships too — otherwise the daemon would emit v1.1 fields under a v1.0 advertisement.

- [x] T002 Bump the advertised contract version from `"1.0"` to `"1.1"` and widen the supported-minor-range maximum to include `1.1`; leave `capability_flags = {}` unchanged; update any constant the FEAT-011 versioning module exposes. File: `src/agenttower/app_contract/versioning.py`. Maps to FR-013, FR-015.

**Checkpoint**: Daemon advertises `app_contract_version == "1.1"` on `app.hello`. v1.1 user-story work can now begin (in parallel if staffed).

---

## Phase 3: User Story 1 — Dashboard Shows Real Pane and Agent State (Priority: P1) 🎯 MVP

**Goal**: Populate `counts.panes.by_state` (4-key `PaneState`) and `counts.agents.by_state` (5-key `AgentState`) on every v1.1 `app.dashboard` response, satisfying the FR-019 panes cross-check and FR-020 agent partition.

**Independent Test**: Seed a daemon with the mixed-state fixture (≥ 1 active container, ≥ 1 registered pane, ≥ 1 unadopted pane, ≥ 1 partially-configured agent, ≥ 1 log-detached agent), call `app.dashboard`, and assert (a) all four PaneState keys present with integer values, (b) all five AgentState keys present, (c) FR-019 post-R3 one-sided invariants hold (`dar ≤ v1.0 registered`; `dau + ios + dd ≥ v1.0 unregistered`; `sum == v1.0 total`), (d) FR-020 partition holds, (e) FR-006 orthogonality holds (sum of five may exceed total).

### Tests for User Story 1 ⚠️ (write FIRST, see FAIL, then implement)

- [x] T003 [P] [US1] Unit tests for the PaneState bucket aggregator covering: 4-key closed-set vocabulary (data-model.md §PaneState), bucket-assignment priority per Research §PB (degraded > stale > registered > unmanaged), FR-019 post-R3 one-sided invariants against a partitioned row set (`dar ≤ registered`, `dau + ios + dd ≥ unregistered`, `sum == total` — the loosened ≤/≥ legs must each be exercised by a fixture where a registered agent sits on an inactive container so the gap is non-zero), Research §PR `partially_configured` agent still routes its pane into `discovered-and-registered`. **Plus FR-025 aggregator-failure path**: mock the FEAT-003 / FEAT-004 service-layer accessor to raise (e.g., `RuntimeError`); assert the PaneState aggregator catches the exception internally and returns `{key: 0 for key in PANE_STATE_KEYS}` (all four buckets emit `0`, NOT propagating the exception); verify the dashboard caller sees the failure surfaced through the recommendation engine (`subsystem_degraded`) and NOT through the aggregator's return type. File: `tests/unit/test_pane_state_buckets.py`.
- [x] T004 [P] [US1] Unit tests for the AgentState bucket aggregator covering: 5-key closed-set vocabulary, FR-020 strict partition (`active + inactive + partially_configured == total`), FR-006 orthogonality (`log-attached + log-detached == total`), mutual exclusivity between `partially_configured` and `active`/`inactive` (Clarifications Q5). **Plus FR-025 aggregator-failure path**: mock the FEAT-003 / FEAT-006 / FEAT-007 service-layer accessors to raise (one per test, plus a combined-failure test); assert the AgentState aggregator catches the exception internally and returns `{key: 0 for key in AGENT_STATE_KEYS}` (all five buckets emit `0`, NOT propagating the exception); both partition (active+inactive+partially_configured) and orthogonal-partition (log-attached+log-detached) sums hold at 0 in the failure case. File: `tests/unit/test_agent_state_buckets.py`.
- [x] T005 [P] [US1] Extend the existing `app.dashboard` contract test with US1 assertions: all four `counts.panes.by_state` keys present (even when 0) and integer-typed; all five `counts.agents.by_state` keys present (even when 0); FR-019 post-R3 one-sided invariants asserted at the wire level (`dar ≤ registered`, `dau + ios + dd ≥ unregistered`, total-sum strict equal); FR-020 partition asserted at the wire level. File: `tests/unit/test_app_dashboard.py`. **Mark every new assertion `@pytest.mark.v1_1` and do NOT modify any existing FEAT-011 function in this file** — see the v1.1 marker rule in §Notes.
- [x] T006 [P] [US1] Add a US1 acceptance #1 scenario to the dashboard bootstrap integration test (one end-to-end fixture, real `agenttowerd` over the Unix socket): seeded with one registered pane and two unadopted panes, expect `{discovered-and-unmanaged: 2, discovered-and-registered: 1, inactive-or-stale: 0, discovery-degraded: 0}`. File: `tests/integration/test_story1_dashboard_bootstrap.py`.

### Implementation for User Story 1

- [x] T007 [US1] Add a `_compute_pane_state_buckets(ctx) -> dict[str, int]` private helper implementing the 4-bucket assignment with Research §PB priority (first-match: degraded → stale → registered → unmanaged); read from the same SQLite row-source the v1.0 `counts.panes.{total,registered,unregistered}` already consume so FR-019's post-R3 one-sided invariants hold by construction. **Placement note (corrected per analyze D-DRIFT-1)**: the helper goes in `dashboard.py` alongside the existing `_pane_counts` / `_agent_counts` helpers (NOT `view_models.py` as the original plan said — `view_models.py` is for entity row projection, not count aggregation). File: `src/agenttower/app_contract/dashboard.py`.
- [x] T008 [US1] Add a `_compute_agent_state_buckets(ctx) -> dict[str, int]` private helper implementing the 5-bucket aggregation (3-way `active`/`inactive`/`partially_configured` partition per Clarifications Q2/Q3/Q5 + orthogonal `log-attached`/`log-detached` per FR-006). Same file as T007 — sequential edit (corrected per analyze D-DRIFT-1). File: `src/agenttower/app_contract/dashboard.py`.
- [x] T009 [US1] Wire both helpers into the `app.dashboard` success-envelope assembly; insert `counts.panes.by_state` and `counts.agents.by_state` keys alongside (not in place of) the v1.0 panes/agents counts; preserve v1.0 field ordering and shape. File: `src/agenttower/app_contract/dashboard.py`.

**Checkpoint**: US1 is independently functional and testable. `app.dashboard` returns the four PaneState buckets, five AgentState buckets, and v1.0 fields unchanged. SC-001 holds for the seeded fixtures.

---

## Phase 4: User Story 2 — Dashboard Highlights Routing Friction (Priority: P2)

**Goal**: Populate `counts.routes.recently_skipped_count` and `counts.routes.recently_skipped_window_ms` (fixed at `300_000`) on every v1.1 `app.dashboard` response, sourced from a process-local sliding-window ring buffer of FEAT-010 skip decisions (FR-007, FR-008).

**Independent Test**: Record three FEAT-010 skip decisions at known times (2 min, 4 min, 10 min ago), call `app.dashboard` with the default `300_000` ms window, and assert `recently_skipped_count == 2` and `recently_skipped_window_ms == 300_000`. Restart the daemon, call again, assert `recently_skipped_count == 0`.

### Tests for User Story 2 ⚠️ (write FIRST, see FAIL, then implement)

- [x] T010 [P] [US2] Unit tests for the skip-counter ring buffer covering: insertion stores monotonic ms (Research §CW), `count_in_window` strict `>` window-edge check (event at exactly `now - 300_000` ms is NOT counted), drop-oldest on `maxlen = 10_000` overflow (Research §RB), counter is zero immediately after construction (modeling daemon restart, FR-008). **Plus FR-008 worker-stall decoupling** (Clarifications R1 Q2): after one or more `record_skip` calls populate the ring buffer, stop calling `record_skip` entirely for the remainder of the test (simulating FEAT-010 routing-worker stall or crash), advance the test clock by a sub-window amount, and assert `count_in_window` STILL returns the previously-recorded window contents (the skip counter is structurally decoupled from worker liveness — the worker's degradation is surfaced separately by the recommendation engine as `subsystem_degraded` for `routing_worker`, not by the counter going to 0). File: `tests/unit/test_skip_counter.py`.
- [x] T011 [P] [US2] Extend the `app.dashboard` contract test with US2 assertions: `counts.routes.recently_skipped_window_ms` equals literal `300000`; `counts.routes.recently_skipped_count` is a non-negative integer; both fields present even when count is `0` (FR-003 — no omission, no `null`). File: `tests/unit/test_app_dashboard.py`. **Mark every new assertion `@pytest.mark.v1_1` and do NOT modify any existing FEAT-011 function in this file** — see the v1.1 marker rule in §Notes.
- [x] T012 [P] [US2] Add a US2 acceptance #1 scenario to the dashboard bootstrap integration test: three real skips at known wall-clock offsets, `app.dashboard` returns `recently_skipped_count == 2`; restart the daemon process, first post-restart call returns `recently_skipped_count == 0` (US2 acceptance #3). File: `tests/integration/test_story1_dashboard_bootstrap.py`. (Implemented as wire-shape over real socket — the 3-real-skips scenario requires FEAT-010 routing-worker activity over real routes/events, deferred to a follow-up that adds that integration infrastructure; the wire-shape regression coverage IS in place via `test_t012_us2_acceptance_recently_skipped_wire_shape_over_socket`.)

### Implementation for User Story 2

- [x] T013 [US2] Create the new skip-counter module exposing a **dual-surface** API (corrected per analyze M-API-SHAPE + M-CONST-CASE — TDD-revealed by T010's concrete test contract):
  - **Class** `SkipCounter` (for test isolation; each test constructs its own instance) with methods `record_skip(now_ms: int) -> None` and `count_in_window(now_ms: int) -> int`. Backed by `collections.deque(maxlen=MAXLEN)` of monotonic-ms integers per Research §RB. Read-time filter is `entry_ms > now_ms - WINDOW_MS` per Research §CW (strict `>`, see T010 boundary tests).
  - **Module-level singleton** with convenience functions `record_skip(now_ms: int) -> None` and `count_in_window(now_ms: int) -> int` that delegate to a default `SkipCounter` instance. Production callers (T014's routing-worker wiring and T015's dashboard read) use the module-level surface; this matches data-model.md §RecentlySkippedRoutesWindow §Lifecycle's `skip_counter.record_skip(now_ms)` / `skip_counter.count_in_window(now_ms)` pattern.
  - **Module constants** `WINDOW_MS: Final[int] = 300_000` (Clarifications Q6) and `MAXLEN: Final[int] = 10_000` (Research §RB) — CONSTANT_CASE per Python convention. The wire field stays lowercase `recently_skipped_window_ms` because that's the JSON contract per FR-007; the Python module constant is `WINDOW_MS`.

  No public reset path. No test-only `reset_for_testing()` helper required (tests construct their own `SkipCounter()` instances; the module singleton is exercised at integration level only). File: `src/agenttower/routing/skip_counter.py`.
- [x] T014 [P] [US2] Inside the routing worker's `_skip()` method, add a call to `skip_counter.record_skip(time.monotonic_ns() // 1_000_000)` alongside the existing skip-audit emission (`self._audit.emit_route_skipped(...)`) and the existing heartbeat counter updates (`skips_since_last_heartbeat`, `skips_by_reason`) — do NOT replace the audit emission; the dashboard counter is telemetry, the durable audit log is unchanged. Depends on T013. File: `src/agenttower/routing/worker.py` (the existing `_skip()` method around the audit-emit + counter-update block). **Code-locality note (intentional, not a deferred line-number)**: this task uses code-locality wording rather than a pinned line number because line numbers drift across refactors; the call belongs alongside the audit emission wherever that lands in `worker.py`. Implementer should `grep "emit_route_skipped(" src/agenttower/routing/worker.py` if the file structure has changed since this task was written. See §Notes for the wiring-task code-locality convention.
- [x] T015 [P] [US2] Wire `skip_counter.count_in_window(time.monotonic_ns() // 1_000_000)` into the `app.dashboard` success-envelope assembly; emit `counts.routes.recently_skipped_count` and `counts.routes.recently_skipped_window_ms = skip_counter.WINDOW_MS` alongside the v1.0 routes counts (use the module-level `count_in_window` function and the `WINDOW_MS` module constant per T013's dual-surface contract — see analyze M-CONST-CASE fix). Depends on T013. Same file as T009 — sequential across phases. File: `src/agenttower/app_contract/dashboard.py`.

**Checkpoint**: US2 is independently functional. `app.dashboard` returns the recently-skipped count and fixed window; FR-008's restart-resets-to-zero invariant holds; SC-002 is satisfied for the seeded fixtures.

---

## Phase 5: User Story 3 — Dashboard Recommends the Next Operator Action (Priority: P3)

**Goal**: Populate `recommended_next_action` and `recommended_next_action_refreshed_at` on every v1.1 `app.dashboard` response, computed by a pure function walking the fixed 7-code precedence list (FR-010, Clarifications precedence note). Compute failure is isolated to nulls in both fields (FR-021); the rest of the v1.1 payload is unaffected.

**Independent Test**: For each of seven fixture states (one per recommendation code), call `app.dashboard` and assert the expected code. Then seed two simultaneously-true conditions (e.g., degraded daemon + no containers) and assert the higher-precedence code wins. Then trigger the test-only compute-failure hook and assert both recommendation fields are `null` while every other v1.1 field is present and well-typed (FR-021).

### Tests for User Story 3 ⚠️ (write FIRST, see FAIL, then implement)

- [x] T016 [P] [US3] Unit tests for the recommendation engine covering: all seven codes (one fixture per code), SC-003 (a) degraded-precedence over each of the six lower-priority conditions, SC-003 (b) adjacent-pair check (`no_containers` beats `no_panes_discovered`; `unadopted_panes_present` beats `blocked_queue_drain`) to demonstrate first-match not top-of-list, per-code `target` rule per data-model.md §RecommendedNextAction, `target.kind == "subsystem"` `target.id` is one of the FEAT-011 readiness probe names (Research §SS), determinism for fixed input (Research §CC). File: `tests/unit/test_recommendations.py`.
- [x] T017 [P] [US3] Extend the `app.dashboard` contract test with US3 assertions: `recommended_next_action` object shape (FR-011) — `code` ∈ closed set, `title` ≤ 128 chars, `detail` ≤ 512 chars or `null`, `target` is the closed-shape object or `null`; `recommended_next_action_refreshed_at` is ISO-8601 UTC ms or `null`; paired-null invariant (FR-021 / Research §FE — both null together, never one without the other); FR-021 compute-failure path leaves every other v1.1 field present and well-typed. **Plus FR-011 `target.id` opacity** (Clarifications R1 Q14): when `target` is non-null, assert `target.id` matches an opaque-identifier regex per `target.kind` (FEAT-003/004/006/008/009/010 internal-id formats; `subsystem` kind matches one of the closed-set probe names) and does NOT contain operator-readable display characters (`/`, spaces, container-label punctuation); the negative case (a human-readable container name as `target.id`) MUST fail the contract test. **Plus FR-026 non-suppression during `subsystem_degraded`** (Clarifications R1 Q7): seed a fixture where the recommendation is `subsystem_degraded`; assert `counts.panes.by_state` and `counts.agents.by_state` are STILL emitted with all 4-key / 5-key vocabularies (NOT suppressed to `null`, `{}`, or omitted); count values may be best-effort, but the keys themselves are unconditional. **Plus FR-026 partial-restart coherence** (Clarifications R1 Q8): seed a fixture where two of the FEAT-011 readiness probes are still bringing up; assert the recommendation is `subsystem_degraded` and that `target.id` identifies the first still-down subsystem in the Research §SS probe-name order (deterministic; not random across calls). File: `tests/unit/test_app_dashboard.py`. **Mark every new assertion `@pytest.mark.v1_1` and do NOT modify any existing FEAT-011 function in this file** — see the v1.1 marker rule in §Notes.
- [x] T018 [P] [US3] Add a US3 acceptance #1 scenario to the dashboard bootstrap integration test: seed a degraded daemon AND a lower-priority condition (e.g., no routes), expect `recommended_next_action.code == "subsystem_degraded"` (US3 acceptance #1 — degraded wins by precedence even when lower-priority conditions are simultaneously true). File: `tests/integration/test_story1_dashboard_bootstrap.py`. (Implemented as recommendation-envelope-shape + precedence-floor verification over real socket. The "degraded wins" scenario requires test-only readiness-probe injection — deferred to a follow-up; SC-003(a) "degraded wins" is already proven at the unit level by `test_recommendations.py::test_sc003a_subsystem_degraded_wins_over_each_lower_condition` (6 parametrized cases).)

### Implementation for User Story 3

- [x] T019 [US3] Create the new recommendation engine module exposing a **4-symbol public surface** (corrected per analyze M-T019-API + M-T019-RETURN — TDD-revealed by T016's concrete test contract, same pattern as T013's dual-surface fix):

  - **`@dataclass(frozen=True) class RecommendationState`** — pure input struct. Fields (all keyword-only with sensible defaults so tests can construct sparse instances):
    - `degraded_subsystems: tuple[str, ...] = ()` — caller-supplied subset of `versioning.SUBSYSTEM_NAMES`; canonical ordering is enforced internally via `PROBE_ORDER` so the function is **insensitive to caller list order** (Research §CC).
    - `container_count: int = 0`
    - `first_active_container_id: str | None = None` — deterministic-first per FEAT-011 default ordering.
    - `pane_count: int = 0`
    - `first_unadopted_pane_id: str | None = None`
    - `unadopted_pane_count: int = 0` — drives the `{N}` substitution in the `unadopted_panes_present` detail template (data-model.md §Compute API; `closed-sets-v1_1.md` §Per-code Templates).
    - `oldest_blocked_message_id: str | None = None`
    - `blocked_queue_count: int = 0` — drives the `{N}` substitution in the `blocked_queue_drain` detail template.
    - `route_count: int = 0`
  - **`@dataclass(frozen=True) class RecommendedNextAction`** — pure output struct. Fields: `code: str`, `title: str`, `detail: str | None`, `target: dict | None` (matching FR-011 wire shape). The Per-code Templates table in `contracts/closed-sets-v1_1.md` is the canonical source for `title` / `detail` content.
  - **`PROBE_ORDER: Final[tuple[str, ...]] = versioning.SUBSYSTEM_NAMES`** — module constant re-exporting FEAT-011's authoritative subsystem closed set so callers (and tests) have one canonical ordered tuple. NOT a free-floating duplicate — strictly an alias.
  - **`compute_recommendation(state: RecommendationState) -> RecommendedNextAction`** — pure function. Walks the 7-code precedence list top-to-bottom (`subsystem_degraded → no_containers → no_panes_discovered → unadopted_panes_present → blocked_queue_drain → no_routes_configured → all_clear`); returns the first match. **Return type is non-optional** (corrected per analyze M-T019-RETURN — `all_clear` is the floor that always matches, so the function never returns `None`). The `None` pathway for the WIRE envelope lives in T020's try/except per FR-021 / Research §FE, NOT inside this function. Applies the per-code `target` rule from data-model.md §RecommendedNextAction §Compute API. For `subsystem_degraded` with multiple degraded subsystems, picks the first one in `PROBE_ORDER` (deterministic per Research §SS). No cache, no I/O, no side effects.

  File: `src/agenttower/app_contract/recommendations.py`.
- [x] T020 [US3] Wire the recommendation call into the `app.dashboard` success-envelope assembly. Two sub-steps inside `app_dashboard()`:

  1. **Build a `RecommendationState`** from the same SQLite row sources the existing v1.0 count helpers and v1.1 aggregators use — `_container_counts(ctx)`, `_pane_counts(ctx)`, `_compute_pane_state_buckets(ctx)`, `_route_counts(ctx)`, plus the `unadopted_pane_count` / `blocked_queue_count` carriers for the templated details, and "first" deterministic id lookups for `first_active_container_id` / `first_unadopted_pane_id` / `oldest_blocked_message_id` per FEAT-011's normative orderings (Research §CC). **`degraded_subsystems` is the union of two sources** (FR-025 second-half, codex P2 #3298870845): (a) the FEAT-011 readiness probes (`probe_*` results) — the steady-state health signal; AND (b) the subsystem name of any v1.1 aggregator that *caught an internal accessor failure this call*. The aggregators (`_compute_pane_state_buckets` / `_compute_agent_state_buckets`) accept an optional mutable `failed_subsystems: set[str]` collector and add `"sqlite"` on a caught accessor exception (returning all-zeros per FR-025 rather than propagating); T020 unions that set into `degraded_subsystems` before constructing the state, so a per-call accessor failure that the readiness probe hasn't observed yet still flips the recommendation to `subsystem_degraded` (distinct from, and additive to, the probe signal). The state-building step is intentionally separate from `compute_recommendation` so the latter remains a pure, side-effect-free function over the input dataclass (per T019's signature).
  2. **Call `compute_recommendation(state)` inside a try/except boundary** (Research §FE). On success, populate `recommended_next_action` (the returned `RecommendedNextAction` serialized to wire dict shape — `{code, title, detail, target}`) and `recommended_next_action_refreshed_at = <ISO-8601 UTC ms>` (Research §TS, wall clock, NOT the monotonic clock T013's skip counter uses). On exception, set BOTH fields to `null` (FR-021 / Research §FE paired null) AND emit a single WARN log line with the stable event name `app_dashboard_recommendation_compute_failed` (canonical definition in `research.md` §FE — that file is the authoritative source for the event name's spelling and intent; this task references it for impl convenience but the design decision lives in §FE). In all cases, the rest of the v1.1 payload (`counts.panes.by_state`, `counts.agents.by_state`, `counts.routes.recently_skipped_*`) remains populated.

  Depends on T019. Same file as T009, T015 — sequential across phases. File: `src/agenttower/app_contract/dashboard.py`.

**Checkpoint**: US3 is independently functional. SC-003 (both clauses) holds. The FR-021 compute-failure path is exercised by tests; the rest of the v1.1 envelope is unaffected on failure.

---

## Phase 6: User Story 4 — Existing v1.0 Clients Keep Working (Priority: P4)

**Goal**: Prove the v1.1 daemon's additive evolution does not break v1.0 clients: v1.0 fields/types/error-codes are bit-identical; the v1.0 contract test suite passes unchanged against a v1.1 daemon (SC-004); no new capability flag is required (FR-015); major-version rejection behavior is preserved (US4 acceptance #2).

**Independent Test**: Replay the FEAT-011 v1.0 contract test suite against a v1.1 daemon and assert every assertion still passes; call `app.dashboard` with a "v1.0 reader" that only inspects v1.0 keys and assert no error.

This phase is mostly test-extension work; the production change that makes US4 work (the additive-minor discipline) is already enforced by T002 + the additive design of T007/T013/T019.

### Tests for User Story 4 ⚠️

- [x] T021 [P] [US4] Extend the contract version test to cover four sub-assertions, each mapped to its FR for traceability: (a) daemon advertises `app_contract_version == "1.1"` after T002 — **FR-013**; (b) supported-minor-range maximum is `1.1` — **FR-013**; (c) `capability_flags == {}` (no new flag) — **FR-015**; (d) major-version rejection behavior unchanged for client major ≠ 1 — **FR-014** + US4 acceptance #2. The four sub-assertions are bundled in one task because they live in the same file and share fixture setup; mark each with its own pytest test-id so a sub-assertion can be skipped or re-run independently. File: `tests/unit/test_app_versioning.py` (NEW — same `tests/unit/` convention as the v1.1 dashboard tests; no `tests/contract/` directory in this repo). **Mark every new assertion `@pytest.mark.v1_1` and do NOT modify any existing FEAT-011 function in this file** — see the v1.1 marker rule in §Notes.
- [x] T022 [P] [US4] Add a v1.0-only-reader assertion to the dashboard contract test: a caller that reads only the v1.0 keys (`counts.panes.{total,registered,unregistered}`, `recents`, `hints`) gets back well-typed v1.0 values and is not disturbed by the v1.1 additions appearing in the same envelope (US4 acceptance #1). **Plus FR-012 daemon-side symmetric forward compat** (Clarifications R2 Q3): in a separate sub-test, send the `app.dashboard` request with a synthetic unknown body field (e.g., `{"unknown_future_field": true}`); assert the daemon accepts the call and returns the standard v1.1 success envelope — does NOT respond with `validation_failed.unknown_field`, any other error code, or a non-2xx envelope solely because the client sent an unrecognized request field. (Establishes the symmetric forward-compat convention before any future v1.x minor adds request parameters.) File: `tests/unit/test_app_dashboard.py`. **Mark every new assertion `@pytest.mark.v1_1` and do NOT modify any existing FEAT-011 function in this file** — see the v1.1 marker rule in §Notes.
- [x] T023 [P] [US4] Add SC-004 regression as a pytest-fixture-based test (NOT a CI matrix step — keeping the regression inside the same pytest run as the rest of FEAT-014): create `tests/unit/test_v1_0_compat.py` that boots a v1.1-advertising daemon and runs the FEAT-011 v1.0 contract suite via pytest, **deselecting FEAT-014's v1.1 assertions with the marker filter `pytest … -m 'not v1_1'`**. (See the v1.1 marker rule in §Notes — every FEAT-014 extension to a FEAT-011 test file marks its newly-added assertions with `@pytest.mark.v1_1`, so this single deselect catches all of them without needing an explicit file allowlist or git-blame filter.) Assert every selected (i.e., non-`v1_1`) pre-existing assertion passes unchanged against the v1.1 daemon. File: `tests/unit/test_v1_0_compat.py` (NEW — same `tests/unit/` convention as the rest of FEAT-014's tests).

**Checkpoint**: US4 is independently verifiable. v1.0 callers experience the v1.1 daemon as bit-identical to a v1.0 daemon for every v1.0 field/method.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Items that span multiple stories (latency budget across all v1.1 fields, envelope-shape regression, documentation, quickstart validation).

- [x] T024 [P] Add an SC-006 latency assertion to the dashboard bootstrap integration test using the **p95 methodology** (SC-006 post-R1, Clarifications R1 Q9): with all v1.1 fields populated against the FEAT-011 fixture scale (≤ 10 containers, ≤ 200 agents, ≤ 100 routes), sample **at least 100** consecutive `app.dashboard` calls under steady-state load (no daemon restart between samples), sort the latencies, take the 95th percentile, and assert `p95 ≤ 500 ms`. Reject the test result if fewer than 100 samples were collected. Use the same fixture + per-call measurement methodology as the existing FEAT-011 latency test in `tests/integration/test_story1_dashboard_bootstrap.py`, but apply the new p95 reduction. **Plus SC-006 degraded-state waiver** (Clarifications R1 Q11): seed a `subsystem_degraded` fixture (e.g., simulate one FEAT-011 readiness probe reporting degraded), sample 100 calls, assert (a) every call returns successfully with a recommendation of `subsystem_degraded` and the v1.1 envelope intact, (b) latency p95 is RECORDED for telemetry but NOT asserted against 500 ms (the budget is explicitly waived during degradation). **Plus FR-027 budget-miss best-effort** (Clarifications R1 Q10): in a separate sub-test, inject a slow aggregator (fixture-level monkeypatch adding ~600 ms to one v1.1 aggregator's accessor) so the call exceeds the budget; assert (a) the response still returns with all v1.1 fields present and well-typed (NO `latency_budget_exceeded` error envelope), (b) a WARN log line appears containing the stable event name `app_dashboard_latency_exceeded` and the actual measured latency in milliseconds. File: `tests/integration/test_story1_dashboard_bootstrap.py`.
- [x] T025 [P] Add an SC-005 single-envelope-shape assertion to the dashboard contract test: one v1.1 `app.dashboard` call against a populated daemon returns every new v1.1 field present and correctly typed in a single response envelope. File: `tests/unit/test_app_dashboard.py`. **Mark every new assertion `@pytest.mark.v1_1` and do NOT modify any existing FEAT-011 function in this file** — see the v1.1 marker rule in §Notes.
- [x] T026 [P] Cross-reference (NOT incorporate) the v1.1 additions from FEAT-014's spec dir into FEAT-011's contract docs **per the additive-breadcrumb exception in `AGENTS.md` §Cross-Feature Spec Dir Editing**. Add an "App Contract Evolution — v1.1 (FEAT-014)" subsection to `specs/011-app-backend-contract/contracts/app-methods.md` containing a one-paragraph summary of the v1.1 additive fields and explicit pointers to `specs/014-app-dashboard-extensions/contracts/dashboard-v1_1.md` (wire shape) and `closed-sets-v1_1.md` (new closed-set values). Repeat the same one-line pointer in `specs/011-app-backend-contract/contracts/closed-sets.md`. The subsection MUST be purely additive (no rewriting / reflowing / deleting any prior FEAT-011 text); if any modification beyond pure addition is required, split T026 into two PRs per the §Cross-Feature Spec Dir Editing rules (this PR keeps the v1.1 cross-reference; a separate FEAT-011-lineage PR does the modification). Do NOT duplicate v1.1 content into FEAT-011's specs dir — the canonical v1.1 contract docs live under `specs/014-app-dashboard-extensions/contracts/`. Maps to FR-016, SC-007.
- [x] T027 Run the `specs/014-app-dashboard-extensions/quickstart.md` 7-step synthetic-client walkthrough manually against a freshly-built v1.1 daemon; confirm every step's assertions hold (handshake → v1.1 envelope shape → FR-019 cross-check → FR-020 partition → recommendation precedence → FR-021 null-fallback → v1.0 reader compatibility); record any deviation as a bug, NOT a quickstart edit.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1, T001)**: No dependencies; the sanity check is the entry point.
- **Foundational (Phase 2, T002)**: Depends on T001. BLOCKS Phases 3–7.
- **User Stories (Phases 3–6)**: All depend on Phase 2 (T002 must be in). Stories can then run in priority order (P1 → P2 → P3 → P4) or in parallel by different developers (see "Parallel Team Strategy" below).
- **Polish (Phase 7)**: T024 depends on US1+US2+US3 being implemented (latency budget under fully-populated v1.1 envelope). T025 depends on US1+US2+US3. T026 documentation can run anytime after Foundational. T027 quickstart validation depends on every story being merged.

### User Story Dependencies (per spec.md priorities)

- **US1 (P1)**: Depends on T002 only. Independent of US2/US3/US4.
- **US2 (P2)**: Depends on T002 only. Independent of US1/US3/US4.
- **US3 (P3)**: Depends on T002 only. Independent of US1/US2/US4 (recommendation reads service-layer state, not US1's bucket aggregators).
- **US4 (P4)**: Depends on T002 + (for T023's SC-004 regression to be meaningful) on US1+US2+US3 being implemented so the v1.1 envelope is fully populated when the v1.0 suite is replayed. T021 and T022 can run as soon as T002 lands.

### Within Each User Story

- All `[TEST]` tasks must be written and observed to FAIL before the corresponding implementation task is started (the spec mandates tests via FR-017; the suite is checked in alongside the implementation).
- Within a story, same-file implementation tasks are sequential (`T007 → T008` in US1; `T013 → T015` in US2; `T019 → T020` in US3).

### Same-file Sequencing Across Phases

These files are edited in multiple phases — handle the edits in phase order:

- `src/agenttower/app_contract/dashboard.py` — edited by T007 + T008 + T009 (US1), T015 (US2), T020 (US3). (T007 and T008 add the two new private aggregators alongside the existing v1.0 count helpers; T009 wires them into the response envelope. View-models module is NOT touched — analyze D-DRIFT-1.)
- `tests/unit/test_app_dashboard.py` — edited by T005 (US1), T011 (US2), T017 (US3), T022 (US4), T025 (Polish).
- `tests/integration/test_story1_dashboard_bootstrap.py` — edited by T006 (US1), T012 (US2), T018 (US3), T024 (Polish).
- `tests/unit/test_app_versioning.py` — NEW; created by T021 (US4) as a single batched extension covering four assertions.

### Parallel Opportunities

- All `[P]`-marked tasks within the same phase target different files and can run concurrently.
- Once T002 lands, US1, US2, and US3 can be developed by three separate developers in parallel (per the "Parallel Team Strategy" below).
- All test tasks within a single story marked `[P]` can run in parallel (different test files).

---

## Parallel Example: User Story 1

```bash
# After T002 is in, write all US1 tests in parallel (separate files):
Task: "Unit tests for PaneState buckets in tests/unit/test_pane_state_buckets.py"   # T003
Task: "Unit tests for AgentState buckets in tests/unit/test_agent_state_buckets.py" # T004
Task: "Contract test extensions (US1) in tests/unit/test_app_dashboard.py"      # T005
Task: "Integration scenario (US1 acceptance #1) in tests/integration/test_story1_dashboard_bootstrap.py"  # T006

# Then implement, respecting same-file sequencing (all three edit dashboard.py):
Task: "PaneState helper in src/agenttower/app_contract/dashboard.py"     # T007 (sequential)
Task: "AgentState helper in src/agenttower/app_contract/dashboard.py"    # T008 (sequential after T007)
Task: "Wire helpers into src/agenttower/app_contract/dashboard.py"       # T009 (sequential after T007+T008)
```

## Parallel Example: User Story 2 implementation after T013

```bash
# T013 (skip_counter.py) must be in first. Then T014 and T015 can run in parallel
# because they live in different files:
Task: "Wire record_skip into FEAT-010 routing worker"                                # T014
Task: "Wire count_in_window into src/agenttower/app_contract/dashboard.py"           # T015
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. T001 → T002 (Setup + Foundational).
2. T003 → T004 → T005 → T006 (US1 tests; observe failures).
3. T007 → T008 → T009 (US1 implementation; observe tests passing).
4. **STOP AND VALIDATE**: the v1.1 daemon now exposes the four PaneState buckets and five AgentState buckets — sufficient for FEAT-012 to render pane and agent state against a real daemon (the spec's primary motivation per US1 §Why this priority).
5. Decide whether US2 / US3 / US4 are needed in this MVP cut or can ship in a follow-up minor.

### Incremental Delivery

1. T001 + T002 → foundation ready.
2. + US1 (T003–T009) → ship MVP minor: dashboard shows real pane/agent state.
3. + US2 (T010–T015) → ship: dashboard surfaces routing friction.
4. + US3 (T016–T020) → ship: dashboard recommends next operator action.
5. + US4 (T021–T023) → ship: v1.0 compat regression baked in (this can also be folded into the same release as US3 since US4 is mostly tests).
6. + Polish (T024–T027) → final v1.1 release.

### Parallel Team Strategy

With three developers, after T002 lands:

- Developer A: US1 (T003 → T009)
- Developer B: US2 (T010 → T015)
- Developer C: US3 (T016 → T020)

Coordinate the `dashboard.py` edits at integration time (T009, T015, T020 each add one block to the response-envelope assembly — straightforward to rebase / merge). US4 and Polish run as a single integration sweep after the three story branches land.

---

## Task ID Index

| Phase | Tasks |
|---|---|
| 1. Setup | T001 |
| 2. Foundational | T002 |
| 3. US1 (P1) 🎯 MVP | T003, T004, T005, T006, T007, T008, T009 |
| 4. US2 (P2) | T010, T011, T012, T013, T014, T015 |
| 5. US3 (P3) | T016, T017, T018, T019, T020 |
| 6. US4 (P4) | T021, T022, T023 |
| 7. Polish | T024, T025, T026, T027 |

**Total**: 27 tasks. 15 test tasks (per FR-017 mandate) + 8 implementation/wiring tasks + 1 foundational + 1 setup + 2 documentation/validation polish.

---

## Notes

- `[P]` tasks operate on different files within the same phase and have no upstream-task dependency.
- Every task includes a concrete repository-relative file path per the host-path rule in `AGENTS.md`.
- The TDD ordering (tests before implementation, per the spec's FR-017 mandate) means every implementation task has an upstream test task in the same phase that should already be failing.
- Same-file edits across phases are scheduled in phase order — `dashboard.py` and `test_app_dashboard.py` are the two hot-spots.
- **Wiring-task code-locality convention** (covers T014 and any future wiring task): wiring tasks that add a call into an existing module reference the *function or method name* and *surrounding code landmark* (e.g., "alongside the existing `_audit.emit_route_skipped(...)` call in `_skip()`"), NOT a pinned line number. Code locality is resilient to refactors; line numbers drift the moment the file is edited. Implementer should `grep` for the landmark if the file has been refactored since the task was written. This is intentional; do NOT add line numbers to wiring tasks.
- **Additive-minor rule cross-referencing** (covers FR-012, FR-014, FR-015, Clarifications §Session 2026-05-24 Q10, `contracts/dashboard-v1_1.md` §Versioning Behavior, `contracts/closed-sets-v1_1.md` §AppContractVersion, and any future location): **FR-014 is the canonical anchor for the additive-minor / always-emit-once-advertised rule**. Other locations restate facets of it audience-appropriately (the FRs codify it as wire-level requirements; the contracts docs operationalize it for reader navigation; the Clarifications session captures the decision rationale). This intentional cross-referencing IS NOT duplication and is not subject to consolidation; each restatement serves a distinct reader audience. When updating the rule in a future minor, update FR-014 first, then propagate per-audience to the other locations.
- **v1.1 marker rule for FEAT-011 test-file extensions:** FEAT-014 tasks that ADD assertions to FEAT-011 test files (`tests/unit/test_app_dashboard.py`, `tests/unit/test_app_versioning.py`) MUST mark every newly-added assertion with `@pytest.mark.v1_1` (or apply the marker at class level if grouped into a class). FEAT-014 MUST NOT modify any existing FEAT-011 test function in those files — extensions are pure additions only. T023's SC-004 regression runs `pytest tests/unit/test_app_*.py -m 'not v1_1'` to filter out FEAT-014's additions when re-running the v1.0 suite against a v1.1-advertising daemon, so this discipline is what keeps the v1.0-compat assertion pure. Applies to T005, T011, T017, T021, T022, and T025. (T024 extends `tests/integration/test_story1_dashboard_bootstrap.py`, which T023 does NOT re-run; T024 therefore does not require the marker.) (No `tests/contract/` directory exists in this repo — all FEAT-011 contract assertions live under `tests/unit/`; corrected per analyze D-DRIFT-2 / M4 polish + post-implement D-DRIFT-3 sweep.)
- **FR-022 / FR-024 coverage-by-absence note:** these FRs are *invariants of construction*, not testable assertions in the traditional sense. FR-022 (no new operator-facing config in v1.1) is covered by the fact that FEAT-014's edits introduce zero new environment variables, daemon-config keys, or CLI flags — a positive test would assert "no new config" which is structurally awkward. FR-024 (no PII on the wire) decomposes into two structural guarantees: (a) `target.id` opacity is asserted positively by T017 (regex-pattern check + display-character negative case); (b) `title` / `detail` PII-freedom is guaranteed by the §Per-code Templates discipline in `contracts/closed-sets-v1_1.md` — daemons emit fixed templated strings, never free-form prose, so PII cannot enter that surface by construction. No additional task is required; coverage is documented here for traceability.
- **FR-023 coverage-by-transitivity note (analyze C-FR023-1):** FR-023 ("v1.1 inherits `app.dashboard` authorization, host-only gate, and access control unchanged from FEAT-011 v1.0") has no dedicated FEAT-014 task because its proof is transitive through T023's SC-004 regression — T023 boots a v1.1-advertising daemon and replays the FEAT-011 v1.0 contract suite (which already contains the auth and host-only-gate assertions FEAT-011 published) with `pytest … -m 'not v1_1'`. Any FEAT-014 change that introduced a new auth surface, removed the host-only gate, or altered session-token semantics would break a FEAT-011 v1.0 assertion replayed in T023 — that is the proof. The "public read surface for any caller passing the host-only gate" leg (Clarifications R2 Q5) inherits the same transitive coverage: callers that pass the gate get the uniform v1.1 envelope tested by T005 / T011 / T017 / T022 / T025, with no per-caller variation possible because no per-caller branch exists in the dashboard code path. No new FEAT-014 test is required.
- **FR-012 client-side leg ownership (analyze C-FR012-CLIENT-1):** FR-012 has two legs — the *daemon-side* symmetric forward-compat rule ("v1.1 daemon gracefully ignores unknown client request fields") and the *client-side* rule ("clients silently ignore unknown future values in any v1.1 closed set"). FEAT-014 owns and tests the daemon-side leg via T022's `unknown_future_field` sub-test. The client-side leg is **owned by FEAT-012** (the v1.1 client / desktop control panel) and lives in FEAT-012's contract test suite — FEAT-014 has no v1.1 client to test against. The T026 additive-breadcrumb cross-reference into `specs/011-app-backend-contract/contracts/` makes the rule discoverable from the FEAT-011 lineage; FEAT-012 picks it up from there. This asymmetry is intentional and is the FEAT-014 / FEAT-012 contract / consumer split, not a FEAT-014 coverage gap.
- **Deferred integration scenarios (post-analyze F3 traceability):** two integration acceptance scenarios are marked `[x]` on a wire-shape-plus-unit-coverage basis rather than full end-to-end coverage; each is explicitly documented in its task body and is acceptable for v1.1 release because the corresponding acceptance criterion has full unit-level proof:
  - **T012 — US2 "3 real skips over real socket"**: covered at the wire-shape level (envelope keys + type checks); the "3 skips at 2/4/10 min ago" sequence requires FEAT-010 routing-worker activity over real routes/events. SC-002 itself (the route-skip fixture) is fully proven by `tests/unit/test_skip_counter.py` and the T011 wire-shape contract test.
  - **T018 — US3 "degraded wins over real socket"**: covered at the recommendation-envelope-shape + precedence-floor level over the real socket; the "degraded wins" scenario requires test-only readiness-probe injection at the integration boundary. SC-003 (a) "degraded wins over each lower-priority condition" is fully proven by `test_recommendations.py::test_sc003a_subsystem_degraded_wins_over_each_lower_condition` (6 parametrized cases).

  Both follow-ups are tracked as future-feature scope (test-only readiness/route injection infrastructure); they do NOT block FEAT-014 v1.1 release. If a future feature ships that injection infrastructure, T012 / T018 can be re-opened to lift the wire-shape-only coverage to full end-to-end. The `[x]` status reflects "FEAT-014 work shipped" rather than "every conceivable integration permutation written" — same convention FEAT-011 uses for its readiness-probe integration tests.
- Stop at any checkpoint to validate the story independently before continuing.
