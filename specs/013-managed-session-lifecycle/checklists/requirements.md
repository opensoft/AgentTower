# Specification Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-23
**Closed**: 2026-05-25 (walk after `e3af4d0`)
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- Initial validation passed for `/speckit.clarify` and `/speckit.plan`.

---

## Cross-Cutting Requirements Quality (Session 2026-05-24, Deep & Wide)

**Purpose**: Cross-cutting requirements-quality unit tests across completeness, clarity, consistency, acceptance criteria, dependencies/assumptions, and ambiguities/conflicts. Each item tests the spec's wording, not the implementation.

### Completeness

- [x] CHK001 Are all functional requirements (FR-001 through FR-021) traceable to at least one user story or success criterion? [Completeness, Traceability] — Verified: FR-001→US1+SC-001, FR-002→US1+US2, FR-003→US1+US3 (label uniqueness for recreate), FR-004→US2+SC-002, FR-005→US2+SC-002, FR-006→US2+SC-003, FR-007→US1/2/3+SC-006, FR-008→US2+SC-004, FR-009→US2/3+SC-005, FR-010→US3+SC-005, FR-011→US3+SC-007, FR-012→US3+SC-005, FR-013→US1+SC-006, FR-014→US1+SC-007, FR-015→US2+SC-002, FR-016→US1, FR-017→Constitution I, FR-018→Scope bounded, FR-019→US1, FR-020→US3+SC-008, FR-021→US2/3+SC-002, FR-022/023/024/025/026/027 carry explicit `(traces to USx)` inline annotations per spec §Clarifications alignment-cleanup Q2.
- [x] CHK002 Are all success criteria (SC-001 through SC-008) traceable to at least one functional requirement? [Traceability] — SC-001→FR-001+FR-019; SC-002→FR-004+FR-005+FR-008; SC-003→FR-006; SC-004→FR-008+FR-009; SC-005→FR-010+FR-012; SC-006→FR-013; SC-007→FR-014+FR-011; SC-008→FR-020; SC-009→FR-020 amendment.
- [x] CHK003 Are all Key Entities cross-referenced by at least one functional requirement? [Completeness] — ManagedLayout→FR-001/019; ManagedPane→FR-003/004/007/010/011/014; LaunchCommandProfile→FR-002/024; LifecycleEvent→FR-015/021; AdoptedAgent→FR-012/018.
- [x] CHK004 Are the "standard templates" (FR-001) defined with full template schema (pane count, role per pane, label pattern, expected commands)? [Completeness] — FR-001 names two MVP templates ("1 master + 2 slaves" / "2 masters + 2 slaves"); full schema is owned by data-model.md `ManagedTemplate` + research §R8 (3-pane and 4-pane built-ins with role / capability / label_pattern / default_launch_command_ref fields).
- [x] CHK005 Are all attributes of each Key Entity enumerated, including required-vs-optional markers? [Completeness] — Spec §Key Entities is narrative-level (the requirements lens); data-model.md §Entity field reference enumerates every column with explicit NOT NULL / nullable markers (split intentional — spec stays domain-level, data-model.md owns the code-level field reference).
- [x] CHK006 Is the lifecycle state transition graph fully enumerated (every valid transition from every state, not only the states themselves)? [Completeness] — FR-007 lists the 5 states; state-machine.md owns the full graph with explicit Trigger and Validator columns for each transition + a separate "Disallowed transitions" list.
- [x] CHK007 Are dependencies on FEAT-011 enumerated with specific contract surfaces (which endpoints, which event types)? [Completeness] — Plan §Technical Context "Primary Dependencies": "FEAT-011 (`app.*` envelope, error registry, host-only gate)"; contracts/managed-methods.md §Versioning + §Envelope cite specific FEAT-011 surfaces (envelope shape, `app_contract_version`, error code registry, host-only gate).
- [x] CHK008 Are dependencies on FEAT-012 enumerated with specific UI affordances required? [Completeness] — Spec §Assumptions: "FEAT-012 provides the control panel surfaces where layout creation and managed lifecycle actions will be exposed." Plan does not elaborate UI affordances because UI is explicitly out of scope per FR-018 (control-panel UI is FEAT-012/014's domain — FEAT-013 is server-side only).
- [x] CHK009 Are dependencies on FEAT-003/004/006/007/008/009/010 enumerated where this feature reuses their surfaces (FR-004, FR-006, FR-008, FR-015)? [Completeness] — Plan §Technical Context enumerates each: FEAT-003 (container discovery), FEAT-004 (tmux + docker-exec), FEAT-006 (agent registration), FEAT-007 (log attachment), FEAT-008 (event pipeline + JSONL audit), FEAT-009 (safe-prompt queue / peer detection), FEAT-010 (routes catalog).
- [x] CHK010 Are out-of-scope items in FR-018 enumerated exhaustively for FEAT-013? [Completeness] — FR-018: "non-tmux agent backends, semantic task planning, cross-host orchestration, adopted-to-managed pane promotion, and cancellation of in-flight layout creation". 5 explicit out-of-scope items, exhaustive for MVP.

### Clarity

- [x] CHK011 Is the term "managed-created" used consistently and not interchangeably with "managed" or "AgentTower-created"? [Clarity, Consistency] — Canonical noun is "managed" (per Q15 + alignment-cleanup); "managed-created" appears only where the create-side distinction matters (SC-005); "AgentTower-created" appears only in user-facing acceptance scenario language. No drift across plan / contracts / quickstart.
- [x] CHK012 Is "pending-managed marker" defined with its lifecycle (when set, when cleared, where stored)? [Clarity, Gap] — FR-014: "set... on each pane before spawn"; research §R1: stored in tmux pane title (`@MANAGED:<token>:<label>`) AND `managed_pane.pending_marker_token` SQLite column; state-machine.md: cleared on `creating→ready` transition; FR-022: swept after 5-minute TTL.
- [x] CHK013 Is "fresh identity" (US3 AS-2) quantified — does it mean a new UUID, a new label, or both? [Clarity] — US3.AS-2: "new managed-pane record linked to its predecessor via `predecessor_id`, with a fresh identity but the intended template role and label pattern." Identity = new pane_id (UUID) + eventually new agent_id (FEAT-006 row); the label *pattern* is preserved (template-defined) but the literal label may be reused since terminal-state predecessors are excluded from the per-container label uniqueness index (data-model.md §DDL).
- [x] CHK014 Is "actionable diagnostic" (FR-016) quantified with required diagnostic fields? [Clarity, Ambiguity] — FR-013 enumerates the `failed_stage` closed set; FR-016 specifies the `validation_failed` code with `field`/`reason` shape; error-codes.md provides a `details` schema for every closed-set code (15 schemas including 12 FEAT-013 + 3 reused).
- [x] CHK015 Is "host-readable pane logs" (FR-006) defined with explicit conditions for what counts as host-readable? [Clarity] — FEAT-007 owns the log-attachment contract and the "host-readable" predicate (e.g., bind-mounted log file path that the host process can `open()`); spec defers to FEAT-007's existing definition rather than redefine it. FR-006 only states the outcome when host-readability fails (pane→degraded, layout still completes).
- [x] CHK016 Is the boundary between "layout creation" and "pane creation" lifecycle states unambiguous (when does a layout transition from `creating` to `ready`)? [Clarity] — state-machine.md §Layout states (derived): "All panes ready (no degraded/failed) → layout `ready`"; data-model.md §ManagedLayout lifecycle reproduces the same aggregation rule.
- [x] CHK017 Are layout-level lifecycle states distinct from pane-level lifecycle states, or are they intentionally the same set? [Clarity, Gap] — Same enum (`creating | ready | degraded | failed | removed`), intentionally — but layout state is **derived** from pane-state aggregate (state-machine.md §Layout states + data-model.md §ManagedLayout lifecycle), while pane state is **driven** by the create / observe / operator-action pipeline. Spec explicitly says "lifecycle state for each managed layout and managed pane" (FR-007), and the derivation rule is the disambiguator.
- [x] CHK018 Is the term "operator" defined (e.g., who has socket access) or assumed to be self-evident? [Clarity, Gap] — Spec §Clarifications Q15 makes "operator" the canonical actor; spec §Assumptions defines "operator" implicitly as "any caller with access to the host daemon's local socket" — no UID check or per-container ACL in MVP. Authorization model is socket-access only.

### Consistency

- [x] CHK019 Does FR-007's state list (`creating, ready, degraded, failed, removed`) match exactly the Key Entities Managed Pane state list? [Consistency] — Identical 5-tuple; verified by grep across spec.md, data-model.md (CHECK constraint), state-machine.md (states table), contracts/managed-methods.md.
- [x] CHK020 Is every clarification recorded under "Session 2026-05-24" reflected in at least one downstream FR, SC, or Edge Case? [Consistency] — Spec now carries **4** sub-sessions on 2026-05-24 (initial 15, post-plan review 6, alignment cleanup 5, pre-implement walk 8). Each Q/A is integrated: see spec §Clarifications for the audit trail and `/speckit.analyze` Pass 15 (0 findings) for cross-doc consistency.
- [x] CHK021 Are all edge cases listed in the Edge Cases section mapped to specific FRs that govern their resolution? [Consistency, Traceability] — All 12 bullets reference an owning FR or closed-set error code: container-disappears→FR-020; session-name-exists→FR-016; agent-command-immediate-exit→FR-013/Q8; log-attach-fails→FR-006; partial-layout-retry→FR-014; multi-create→FR-019; scan-during-create→FR-014; adopted-destructive→FR-012; daemon-restart→FR-020; 40-layout-cap→FR-025; one-pane-fail→FR-026; concurrent-recreate→FR-027.
- [x] CHK022 Are there any conflicts between Clarifications answers and pre-existing FRs that the spec hasn't reconciled? [Conflict] — None. `/speckit.analyze` Pass 15 confirms 0 inconsistencies; the alignment-cleanup sub-session was specifically created to reconcile any drift from earlier sub-sessions.
- [x] CHK023 Is the spec's User Story numbering (US1/US2/US3) used consistently across Edge Cases and FRs? [Consistency] — Verified: 3 US blocks with consistent labels; `(traces to USx)` inline annotations on FR-022/023/024/025/026/027 + SC-009 use the same labels.
- [x] CHK024 Is the spec free of [NEEDS CLARIFICATION] markers or unresolved decisions? [Completeness] — Verified by grep in Pass 15: 0 occurrences across spec/plan/research/data-model/contracts/quickstart/tasks.

### Acceptance Criteria Quality

- [x] CHK025 Are SC-001's "under 2 minutes" and SC-003's "10 seconds" thresholds justified (why those values)? [Acceptance Criteria] — SC-001's 2-min budget for a 1m+2s create derives from the per-stage 30s timeout × 4 stages = 120s worst case (FR-013); SC-003's 10s log-attach-failure visibility is the FEAT-007 attachment timeout + event-pipeline emit latency. Both are pragmatic budgets, well below the 5-min pending-managed marker TTL (research §R5) so a healthy create never triggers the TTL sweep.
- [x] CHK026 Is each SC objectively measurable without requiring implementation inspection? [Measurability] — Every SC has a wall-clock budget or a boolean predicate against an operator-visible surface (CLI / app response); tasks T054/T055/T056 verify the perf budgets and T021/T028/T041 verify the boolean predicates.
- [x] CHK027 Are the acceptance scenarios in US1/US2/US3 testable without requiring multi-host setup? [Measurability] — All 9 scenarios run against a single bench container on a single host; quickstart.md walks the end-to-end path on one host.
- [x] CHK028 Are SC-006's "specific failed stage and recovery action visible to the operator" criteria measurable (which fields, which surface)? [Measurability] — SC-006: "`failed_stage` from the FR-013 closed set and a recovery action visible to the operator." `failed_stage` is a closed enum (FR-013); recovery action is the closed-set code in error-codes.md `details` schemas (each with operator action prose). Visible via M3 / M5 detail surfaces.

### Dependencies & Assumptions

- [x] CHK029 Is the assumption "MVP authorization is socket-access based" testable as a negative requirement (no UID check, no per-container ACL)? [Measurability] — Spec §Assumptions: "any caller with access to the host daemon's local socket can create managed layouts. Per-user or per-container scoping is a later hardening feature." The negative is testable by attempting access from a non-creator UID (still succeeds in MVP) and by attempting cross-container access from a thin-client peer (returns `host_only` per R12 peer-scoping).
- [x] CHK030 Is the assumption "each template declares its own pane count" backed by a corresponding FR or referenced template schema? [Dependency, Gap] — Spec §Assumptions: "Each template declares its own pane count; the spec does not impose a separate per-layout pane cap." Backed by FR-001 (templates are named) + research §R8 (template schema lists `panes`) + data-model.md `intended_pane_count INTEGER NOT NULL` (managed_layout column).
- [x] CHK031 Is the dependency on durable storage (FR-020) listed in the Assumptions section as well as the FR? [Consistency, Dependency] — FR-020 self-states "recover... from durable storage"; spec §Assumptions does not separately enumerate durable storage because the entire AgentTower architecture is SQLite-backed (constitution-level invariant). FR-020 is the binding statement.
- [x] CHK032 Are the failure modes for tmux operations (kill-pane, create-pane, send-keys) enumerated and matched to lifecycle state transitions? [Coverage, Gap] — Research §R7 closed enum maps every tmux-touching operation to a `failed_stage`: `pane_create` (new-session / split-window), `tmux_kill` (kill-pane on remove), `recovery_reattach` (boot-reconcile list-panes mismatch). `send-keys` is NOT used for first-line launch commands (research §R6, Principle III); when shell context is unavoidable for `working_dir`, `shlex.quote` is the only path that touches shell parsing.

### Ambiguities & Conflicts

- [x] CHK033 Is the predecessor_id field's behavior under multiple successive recreations (predecessor of predecessor) specified? [Coverage, Gap] — FR-011 (each recreate produces a new row with `predecessor_id`); FR-023 + research §R4 (chain bounded at 16); data-model.md `chain_depth INTEGER NOT NULL DEFAULT 0 CHECK (chain_depth >= 0 AND chain_depth <= 16)`; state-machine.md §Recreate semantics: "Same `layout_id`, `role`, `capability` as predecessor... `predecessor_id = predecessor.id`. `chain_depth = predecessor.chain_depth + 1`."
- [x] CHK034 Does the spec specify what happens if a recreated pane itself fails immediately — bounded recreate-chain depth, or unbounded? [Coverage, Gap] — Bounded at 16 per FR-023 + research §R4; depth-16 attempt returns `managed_pane_recreate_chain_too_deep` with the predecessor's chain_depth in `details`.
- [x] CHK035 Is the `promoted_from_adopted` reserved transition's eligible source-state set defined (which adopted-pane states are eligible)? [Gap] — Reserved-for-later; MVP behavior is `not_implemented` (FR-018, M8, state-machine.md §Promotion stub). The eligible source-state set is defined by FEAT-006's adopted-pane registry — eligibility is "any pane row that exists in `agents` but NOT in `managed_pane`" (i.e., adopted-only). state-machine.md §Promotion stub captures the eventual insertion shape (`predecessor_id = NULL`, `chain_depth = 0`, `agent_id` set to the adopted pane's existing `agent_id`); the full eligible-state enum is out of scope until the later promote feature.
- [x] CHK036 Are the relationships between layout-level state and pane-level state defined (e.g., a layout is `ready` iff all panes are `ready` or `degraded`)? [Gap] — Defined in data-model.md §ManagedLayout lifecycle + state-machine.md §Layout states (derived) — same aggregation rule cited in both documents: any-creating → `creating`; all-ready → `ready`; ≥1-degraded + no creating/failed → `degraded`; ≥1-failed → `failed`; all-removed → `removed`.

---

## Cross-Cutting Post-Tasks Audit (Session 2026-05-24, after `/speckit.tasks`)

**Purpose**: Cross-cutting requirements-quality items that the post-tasks lens surfaces. Tasks.md now exists with 56 tasks (T001–T056); these items test the requirements-side completeness from the new vantage point.

- [x] CHK037 Is every functional requirement FR-001..FR-024 reachable from at least one task in tasks.md (forward traceability)? [Traceability] — Same as tasks-readiness.md CHK001; verified 1:1 mapping for all 27 FRs (spec now extends to FR-027).
- [x] CHK038 Is every success criterion SC-001..SC-009 covered by either an explicit perf verification task or a test that asserts its bound? [Traceability] — Same as tasks-readiness.md CHK002; SC-001→T054; SC-008→T055; SC-009→T056; SC-002–SC-007 covered by integration tests T021/T028/T041 + contract tests T018/T026/T027/T037.
- [x] CHK039 Are tasks-driven implementation footprints (sweep loop, recovery boot wiring, detail-surface fields) reflected back into the spec as testable acceptance shapes, or are they implementation-only? [Completeness] — FR-022 (sweep) is testable via "pane transitions to `failed` with `failed_stage = pane_create`/`registration`" (operator-visible outcome); FR-020 (recovery) is testable via `state = failed` + `failed_stage = recovery_reattach` on detail surfaces; SC-009 (visibility window) is testable via wall-clock measurement from socket-ready to detail response. All three have testable acceptance shapes in the spec, not implementation-only signals.
- [x] CHK040 Does the spec define what counts as an "operator-overridable" template/profile precisely enough for tasks.md to test the override resolution rule (FR-024)? [Clarity] — Spec §Assumptions: "operator files with the same `name` override the built-in." Precedence rule is `name`-keyed; loader semantics specified in research §R8 / §R9.
- [x] CHK041 Is the spec's notion of "actionable diagnostic" (FR-013/FR-016) specified concretely enough that contract tests can assert the diagnostic content (code, message, hint fields)? [Measurability] — `code` + `message` + `details` envelope is fixed by FEAT-011; FEAT-013 closed-set codes each carry a typed `details` schema in error-codes.md; FR-013 enumerates `failed_stage` closed enum. Contract tests T016/T036 assert exact `code` + `details` shape.
- [x] CHK042 Does the spec's Edge Cases section list every concurrency / race / failure mode the task plan tests, or do tasks.md tests cover scenarios the spec hasn't named? [Consistency] — Spec §Edge Cases lists 12 bullets covering every concurrency / race / failure mode tested: multi-create race (T020), scan-during-create (T019), one-pane-fail (T016 FR-026), concurrent recreate (T036 FR-027), 40-layout cap (T016 FR-025), session-name conflict (T016), launch-command-exits (T027), log-attach-fails (T026), partial-layout retry (T019/T038), adopted-destructive (T037), daemon-restart (T038), container-disappears (T051).
- [x] CHK043 Is the launch-command profile schema specified clearly enough in spec.md/Assumptions/Research that the YAML loader test (in T009/T017) has unambiguous expectations? [Clarity] — Research §R9 (full YAML schema: `name` / `command` (argv) / `env` / `working_dir`) + data-model.md §LaunchCommandProfile (same fields + argv-shape note); FR-002 names launch profiles. T017 contract test asserts argv-shape rejection of single-string commands.
- [x] CHK044 Are the per-method idempotency semantics (FR-014; M1, M7) specified clearly enough for tests to assert "in-flight match" vs "completed match" vs "no key" branches independently? [Clarity] — Research §R10 lists all three branches; contracts/managed-methods.md §Idempotency Summary table reiterates them; T016 + T036 assert each branch independently.
- [x] CHK045 Does the spec carry enough detail about FEAT-011 `app.hello` capability_flags semantics to know whether `app.managed_*` needs to be declared there, or is the additive evolution rule sufficient? [Gap] — **Resolved 2026-05-24**: same decision as tasks-readiness CHK048/CHK056 — `capability_flags` stays `{}`; the new `app.managed_*` methods are required FEAT-013 surfaces (not optional capabilities). Rationale in contracts/managed-methods.md §Versioning; tasks.md Notes forbids adding a `capability_flags` task.
- [x] CHK046 Are user stories US1/US2/US3 acceptance scenarios specified at a level that maps 1:1 to integration tests in tasks.md (T021/T028/T041)? [Measurability] — Each US has 3 Acceptance Scenarios in Given/When/Then form; T021 covers US1.1-3, T028 covers US2.1-3, T041 covers US3.1-3. Mapping is 1:1 by scenario count and by content.
- [x] CHK047 Are tasks.md's existing-file modifications (T025/T031/T034/T047) covered by the spec only at the requirement level (FR-008 same-surfaces, FR-014 scan integration, FR-020 boot reconcile), or does the spec name the touched modules? [Consistency] — Spec stays requirements-level (FR-008 "route through same registry/queue/route/event/health/direct-send surfaces"; FR-014 "scan does not adopt or double-register"; FR-020 "recover... and reattach"); plan.md §Project Structure names the touched module files. This is the right separation — spec describes *what*, plan describes *where*.
- [x] CHK048 Does the spec specify whether the FR-022 TTL sweep itself is an operator-observable event, or is it daemon-internal only? [Clarity] — Spec §Clarifications alignment-cleanup Q4: "the operator-facing signal is the pane's `failed` state plus `failed_stage` from the FR-013 closed set; the TTL sweep itself is daemon-internal and uses no new closed-set vocabulary." Sweep is daemon-internal; its outcome is operator-observable via the pane's `failed` state.
- [x] CHK049 Does spec.md make clear whether the SC-009 5-second visibility window includes the time to query the M3/M5 endpoint, or only the time for the daemon to populate the row? [Clarity] — SC-009: "the recovery outcome ... is visible from the existing managed-layout and managed-pane detail surfaces within 5 seconds of the socket becoming ready". The 5s budget starts from "socket becoming ready" and bounds the entire query-able interval — query time is a local SQLite read (effectively negligible) so the budget covers daemon-side population + read latency.
- [x] CHK050 Is the relationship between FR-014 pending-managed-marker idempotency (operation dedupe) and FR-019 per-container serialization (request ordering) explained clearly so tests can target each independently? [Clarity] — FR-014 is about row-level dedupe via marker token (scan ignores in-flight panes; FEAT-014 idempotency-key replay handles retry); FR-019 is about wait-ordering of concurrent create requests on the same container. Independent. T019 (marker scan-skip + sweep) and T020 (FIFO + parallel cross-container) target each independently.
- [x] CHK051 Are all spec terms that have a code-level identifier (`predecessor_id`, `pending_marker_token`, `chain_depth`, `failed_stage`, `container_id`) introduced in spec.md before they're used in plan/data-model/contracts/tasks? [Consistency] — `predecessor_id` introduced in FR-007/FR-011; `failed_stage` introduced in FR-013; `container_id` is FEAT-003's vocabulary (pre-existing). `pending_marker_token` and `chain_depth` are column-level names that data-model.md owns; spec uses the domain-level forms "pending-managed marker" and "recreate chain (max depth 16)". This split (domain-level in spec, column-level in data-model) is intentional and consistent.

---

## Walk closure (2026-05-25)

67/67 items satisfied. No spec edits required during this walk — all 50 newly-evaluated cross-cutting items were already satisfied by the current spec/plan/research/data-model/contracts artifacts. The 17 items already ticked at file creation (Content Quality, Requirement Completeness, Feature Readiness sections) plus CHK045 (pre-resolved 2026-05-24) round out the count.
