# Feature Specification: Managed Session Creation and Lifecycle

**Feature Branch**: `013-managed-session-lifecycle`
**Created**: 2026-05-23
**Status**: Draft
**Input**: User description: "Create FEAT-013 to implement the managed session creation and lifecycle proposal from the updated AgentTower product docs."

## Clarifications

### Session 2026-05-24

- Q: Are `degraded` and `failed` distinct lifecycle states, or one state with a failure-detail field? → A: Distinct top-level states; `degraded` means recoverable/partly usable, `failed` means unusable until recreated.
- Q: When a managed pane is recreated, does it reuse the original record or get a new one? → A: New managed-pane record linked to its predecessor via `predecessor_id`; the prior record is archived in `removed` state and remains queryable.
- Q: What happens when two layout creation requests target the same bench container at the same time? → A: Serialize per container; the second request waits until the first finishes.
- Q: What is the uniqueness scope for managed-pane labels? → A: Unique within a single bench container across all managed layouts in that container.
- Q: What is the maximum number of panes per managed layout in MVP? → A: No spec-level cap; each layout template declares its own pane count.
- Q: What happens when the target tmux session name already exists in the selected container? → A: Fail with a `managed_session_name_conflict` diagnostic; no silent suffixing or session reuse.
- Q: A managed pane is discovered by the periodic scan before its registration workflow finishes — who wins? → A: The scan ignores panes carrying a pending-managed marker that the creation flow sets before spawning the pane.
- Q: A configured agent command exits immediately after pane creation — what state does the pane land in? → A: `degraded` (pane exists, agent unhealthy, recreate is the recovery path).
- Q: A created receiver pane's log path is not host-readable — what state does the pane land in? → A: `degraded`; the layout completes and the log gap is visible to the operator per SC-003.
- Q: How is managed-layout state handled across an `agenttowerd` restart? → A: Recover managed-layout/managed-pane records from durable storage and reattach to surviving tmux panes.
- Q: When the operator removes a managed pane, what happens to the underlying tmux pane? → A: Kill the tmux pane (`tmux kill-pane`) and unregister; audit/history records are preserved.
- Q: How long are removed-pane audit/history records retained in MVP? → A: Indefinitely; pruning is deferred to a later feature.
- Q: Is the *promote-adopted-to-managed* action in scope for FEAT-013? → A: Out of scope; the managed-pane state model reserves a `promoted_from_adopted` transition for a later feature.
- Q: Who can create managed layouts via the daemon socket in MVP? → A: Anyone with daemon socket access; no per-user/per-container scope in MVP.
- Q: Adopt a single canonical actor term across the spec? → A: Use "operator" everywhere, except the US1 persona line which retains "local multi-agent developer".

### Session 2026-05-24 (post-plan review)

- Q: Should the 5-minute pending-managed-marker TTL be surfaced as a system requirement? → A: Yes — new **FR-022** requires sweeping markers older than 5 minutes; the affected pane transitions to `failed` with the appropriate `failed_stage`.
- Q: Should the depth-16 recreate-chain bound be surfaced as a system requirement? → A: Yes — new **FR-023** bounds recreate chains at depth 16 with a specific actionable error.
- Q: Should operator-overridable templates and launch command profiles be documented? → A: Yes — record the canonical YAML paths in §Assumptions **and** add **FR-024** mandating the override capability.
- Q: Is "cancellation of in-flight layout creation" out of scope for MVP? → A: Yes — extend **FR-018** to name it explicitly.
- Q: Should the `failed_stage` enum be promoted into FR-013? → A: Yes — **FR-013** enumerates the closed set `{pane_create, launch_command, registration, log_attach, tmux_kill, recovery_reattach}`.
- Q: Should `recovery_reattach` outcomes be operator-readable from the normal managed-layout / managed-pane detail surfaces? → A: Yes — extend **FR-020** to require this **and** add **SC-009** with a measurable visibility window after restart.

### Session 2026-05-24 (alignment cleanup)

- Q: Should plan.md carry a back-reference to the post-plan Clarifications sub-session so FR-022/023/024/SC-009 have a one-hop audit trail? → A: Yes — plan.md Summary cites spec §Clarifications "Session 2026-05-24 (post-plan review)" as the origin.
- Q: How should FR-022 / FR-023 / FR-024 / SC-009 be traced to User Stories rather than left as system-level orphans? → A: Map each to its natural User Story — FR-022, FR-023, SC-009 → US3 (Manage Created Pane Lifecycle); FR-024 → US1 (Create a Standard Multi-Agent Layout). The inline `(traces to USx)` annotation is reserved for these four system-level requirements that lacked obvious US affinity at write-time; FR-001..FR-021 and SC-001..SC-008 do not carry the annotation by convention because their US affinity is evident from their text.
- Q: Are plan-review.md CHK036–CHK041 fully resolved by the post-plan spec edits alone? → A: The requirements gaps are closed, but FR-022 (TTL sweep), FR-020 (detail-surface readability), and SC-009 (5-second post-restart visibility) imply implementation work that MUST be captured as tasks during `/speckit.tasks`.
- Q: Should FR-022 TTL-driven failures surface a dedicated error code? → A: No — the operator-facing signal is the pane's `failed` state plus `failed_stage` from the FR-013 closed set; the TTL sweep itself is daemon-internal and uses no new closed-set vocabulary.
- Q: Should SC-006's "specific failed stage" wording be aligned with FR-013's closed enum? → A: Yes — SC-006 references the FR-013 closed `failed_stage` set instead of duplicating the enum.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create a Standard Multi-Agent Layout (Priority: P1)

As a local multi-agent developer, I want AgentTower to create a working master/slave agent layout for a selected bench container so I can start a coordinated session without manually creating tmux panes first.

**Why this priority**: This is the core value of FEAT-013: moving from adopting existing panes to creating an operable multi-agent workspace from the control panel.

**Independent Test**: Can be tested by selecting a running bench container, choosing a standard layout template, creating the layout, and verifying that every created pane appears as a registered AgentTower agent with the expected role and label.

**Acceptance Scenarios**:

1. **Given** the daemon is healthy and a bench container is running, **When** the operator creates a "1 master + 2 slaves" layout, **Then** AgentTower creates the required panes, launches the configured agent commands, registers the panes, and shows them in the agent surfaces.
2. **Given** the daemon is healthy and a bench container is running, **When** the operator creates a "2 masters + 2 slaves" layout, **Then** AgentTower creates two master agents and two slave agents that can be routed and monitored through the existing control surfaces.
3. **Given** a template creation request is in progress, **When** one pane or command launch fails, **Then** AgentTower reports which part failed and leaves a recoverable lifecycle state instead of silently presenting a complete layout.

---

### User Story 2 - Auto-Prepare Created Agents for Operations (Priority: P2)

As an operator, I want created panes to be automatically registered, logged, and visible in queues/routes/events so the managed layout is immediately usable with the same workflow as adopted panes.

**Why this priority**: Created panes are only valuable if they enter the same operational model already established by FEAT-011 and FEAT-012.

**Independent Test**: Can be tested by creating a managed layout and verifying that created agents appear in agent lists, can receive direct input, can be routed, and produce observable events without manual registration steps.

**Acceptance Scenarios**:

1. **Given** a managed slave pane is created, **When** it is ready for use, **Then** it has a role, capability, label, lifecycle state, and log attachment state.
2. **Given** a managed slave pane is created, **When** it emits output, **Then** the output can be classified and routed through the same event surfaces used by adopted panes.
3. **Given** managed and adopted agents exist in the same bench container, **When** the operator views agents, routes, queue, and events, **Then** both kinds of agents are visible without separate operating modes.

---

### User Story 3 - Manage Created Pane Lifecycle (Priority: P3)

As an operator, I want to remove or recreate panes that AgentTower created so I can cleanly recover from failed sessions, stale agents, or obsolete layouts without disrupting unrelated adopted panes.

**Why this priority**: Lifecycle controls are needed for repeatable demos and daily use, but they should only apply safely to panes AgentTower created or explicitly marked as managed.

**Independent Test**: Can be tested by creating a managed layout, removing one managed pane, recreating it, and verifying that unmanaged/adopted panes in the same container are unchanged.

**Acceptance Scenarios**:

1. **Given** a pane was created by AgentTower, **When** the operator removes it, **Then** AgentTower kills the underlying tmux pane, stops managing it, cleans up related routing/log state, and preserves audit history indefinitely.
2. **Given** a managed pane was removed or failed, **When** the operator recreates it, **Then** AgentTower creates a new managed-pane record linked to its predecessor via `predecessor_id`, with a fresh identity but the intended template role and label pattern.
3. **Given** a pane was only adopted and not created by AgentTower, **When** the operator manages created-pane lifecycle actions, **Then** AgentTower does not delete or recreate that adopted pane (promotion of adopted panes into managed scope is out of scope for this feature).

### Edge Cases

- The selected bench container disappears, restarts, or becomes unreachable during layout creation.
- The target tmux session name already exists in the selected container → layout creation fails with `managed_session_name_conflict`; no silent suffixing or session reuse.
- A configured agent command is missing, exits immediately, or prompts before registration completes → the affected pane lands in `degraded` state; the rest of the layout completes.
- Log attachment fails because the log path is not host-readable → the affected pane lands in `degraded` state; the layout completes and the log gap is visible per SC-003.
- A partial layout exists from a previous failed creation attempt → retry resumes the same pending layout via its pending-managed markers without creating duplicate ready agents.
- Multiple layout creation requests target the same container at the same time → requests are serialized per bench container; the second waits until the first finishes.
- Created panes are later discovered by scan before the registration workflow completes → the scan ignores panes carrying the pending-managed marker set by the creation flow before pane spawn.
- The operator attempts to delete or recreate an adopted pane that AgentTower did not create → the destructive action is refused (adopted-to-managed promotion is out of scope for FEAT-013).
- `agenttowerd` restarts while managed layouts exist → managed-layout records are recovered from durable storage and reattached to surviving tmux panes.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST let the operator create a managed agent layout in a selected running bench container from at least two standard templates: "1 master + 2 slaves" and "2 masters + 2 slaves".
- **FR-002**: System MUST let the operator provide or select configured launch commands for each created agent role and capability before creating a layout.
- **FR-003**: System MUST create panes with deterministic human-readable labels that identify the layout, role, and ordinal position; labels MUST be unique within a single bench container across all managed layouts in that container.
- **FR-004**: System MUST register every successfully created pane as an AgentTower agent without requiring a separate manual adoption step.
- **FR-005**: System MUST distinguish managed-created agents from adopted agents in agent metadata and operator-facing surfaces.
- **FR-006**: System MUST attach logs automatically for created receiver/worker panes when the environment supports host-readable pane logs; when log attachment fails, the affected pane MUST land in `degraded` state and the layout MUST still complete.
- **FR-007**: System MUST expose lifecycle state for each managed layout and managed pane using these distinct states: `creating`, `ready`, `degraded` (recoverable / partly usable), `failed` (unusable until recreated), and `removed`. Recreation MUST produce a new managed-pane record in `creating` state linked to its predecessor via `predecessor_id`; the state model MUST reserve a `promoted_from_adopted` transition for a later feature.
- **FR-008**: System MUST route created agents through the same registry, queue, route, event, health, and direct-send surfaces used by adopted agents.
- **FR-009**: System MUST allow managed and adopted agents to coexist in the same bench container without changing adopted-pane identity or lifecycle ownership.
- **FR-010**: System MUST allow the operator to remove a managed-created pane, killing the underlying tmux pane (`tmux kill-pane`), cleaning up active routes/log attachments, and preserving durable audit/history records.
- **FR-011**: System MUST allow the operator to recreate a removed or failed managed pane by creating a new managed-pane record linked to its predecessor via `predecessor_id`, using the same intended role, capability, label pattern, and template context.
- **FR-012**: System MUST prevent destructive lifecycle actions on adopted panes; adopted-to-managed promotion is out of scope for this feature.
- **FR-013**: System MUST report partial failures with enough detail for the operator to identify the failed pane, failed stage, and suggested recovery action. The reported `failed_stage` MUST be one of the closed set `{pane_create, launch_command, registration, log_attach, tmux_kill, recovery_reattach}`. Transient recoverable failures (launch command immediate exit, log attachment failure) MUST place the affected pane in `degraded`; non-recoverable failures MUST place it in `failed`.
- **FR-014**: System MUST make layout creation idempotent enough that retrying after a partial failure does not silently duplicate ready agents from the same pending layout. The creation flow MUST set a pending-managed marker on each pane before spawn so that periodic discovery does not adopt or double-register an in-flight managed pane.
- **FR-015**: System MUST emit observable lifecycle events for layout creation, pane creation, agent launch, registration, log attachment, removal, recreation, and failure.
- **FR-016**: System MUST reject layout creation when the daemon, selected container, or pane-control path is unhealthy and return an actionable diagnostic. When the target tmux session name already exists in the selected container, System MUST fail with a specific `managed_session_name_conflict` diagnostic rather than silently suffix the name or reuse the existing session.
- **FR-017**: System MUST keep the MVP local-first with no hosted control plane or remote network listener required.
- **FR-018**: System MUST keep non-tmux agent backends, semantic task planning, cross-host orchestration, adopted-to-managed pane promotion, and cancellation of in-flight layout creation out of scope for this feature.
- **FR-019**: System MUST serialize layout creation per bench container; when two creation requests target the same container, the second request MUST wait until the first finishes before proceeding.
- **FR-020**: System MUST recover managed-layout and managed-pane records from durable storage when `agenttowerd` restarts and MUST reattach to surviving tmux panes whose identity still matches the recovered records. The per-layout and per-pane recovery outcomes (successfully reattached vs failed reattach) MUST be readable from the same managed-layout and managed-pane detail surfaces used during normal operation — not only from event logs.
- **FR-021**: System MUST preserve managed-layout and managed-pane audit / lifecycle event records indefinitely in MVP; retention pruning is deferred to a later feature.
- **FR-022** (traces to US3): System MUST sweep pending-managed markers (introduced in FR-014) whose age exceeds 5 minutes; the affected pane MUST transition to `failed` with `failed_stage = pane_create` when no tmux pane backs the record, or `failed_stage = registration` when a pane exists but never registered.
- **FR-023** (traces to US3): System MUST bound managed-pane recreate chains at a maximum depth of 16; attempts to recreate past the bound MUST return a specific actionable error (no silent acceptance, no truncation of recreate history).
- **FR-024** (traces to US1): System MUST allow the operator to override or extend layout templates and launch command profiles through YAML files at canonical configuration paths; operator-supplied overrides MUST take precedence over built-in defaults when their `name` collides.

### Key Entities *(include if feature involves data)*

- **Managed Layout**: An operator-created group of related panes in a bench container, based on a selected template and tracked through lifecycle states. Creation against a given bench container is serialized; the template declares the pane count.
- **Managed Pane**: A tmux-backed pane created by AgentTower, with intended role, capability, label (unique within its bench container), launch command, lifecycle state (`creating` | `ready` | `degraded` | `failed` | `removed`), optional `predecessor_id` linking to the prior record when this pane was produced by a recreate action, and relationship to a managed layout. A pending-managed marker is set on the pane before spawn so the periodic scan does not adopt or double-register it.
- **Launch Command Profile**: A named or selected command configuration used to start an agent role in a managed pane.
- **Lifecycle Event**: An observable event describing a creation, registration, log attachment, removal, recreation, or failure transition. Retained indefinitely in MVP.
- **Adopted Agent**: An existing pane registered through adoption rather than created by AgentTower; it can coexist with managed panes but is protected from managed-pane destructive actions. Promotion of an adopted pane to managed scope is out of scope for FEAT-013 (the managed-pane state model reserves a `promoted_from_adopted` transition for a later feature).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can create a "1 master + 2 slaves" managed layout from the control panel in under 2 minutes on a healthy bench container.
- **SC-002**: 100% of successfully created panes appear as registered agents with role, capability, label, lifecycle state, and managed/adopted origin visible to the operator.
- **SC-003**: Created slave/receiver panes have log attachment attempted automatically, and any attachment failure surfaces the affected pane as `degraded` within 10 seconds of layout creation completion.
- **SC-004**: Managed and adopted agents in the same container can both be listed, routed, sent input, and observed through the existing app surfaces without separate workflows.
- **SC-005**: Removing or recreating a managed-created pane never deletes, recreates, or changes lifecycle ownership for an adopted pane in the same container.
- **SC-006**: A failed or partial layout creation produces a `degraded` (recoverable) or `failed` (non-recoverable) state with a `failed_stage` from the FR-013 closed set and a recovery action visible to the operator.
- **SC-007**: Re-running a layout creation or recovery action after a partial failure does not create duplicate ready agents for the same intended managed pane slot.
- **SC-008**: After `agenttowerd` restarts, managed-layout and managed-pane records reappear from durable storage and reattach to surviving tmux panes without operator intervention; reattach for up to 4 managed layouts MUST complete before the socket starts accepting requests, with a target of ≤5 seconds from daemon process start.
- **SC-009** (traces to US3): After `agenttowerd` restarts, the recovery outcome (reattached / failed-to-reattach) for every recovered managed layout and managed pane is visible from the existing managed-layout and managed-pane detail surfaces within 5 seconds of the socket becoming ready — without log inspection. (Begins after SC-008's reattach phase completes; SC-008 and SC-009 are sequential, not parallel, so the worst-case cold-start observability budget is SC-008 + SC-009 ≤ 10 seconds.)

## Assumptions

- FEAT-011 provides stable app-facing daemon contracts for panes, agents, events, routes, queues, health, and mutations.
- FEAT-012 provides the control panel surfaces where layout creation and managed lifecycle actions will be exposed.
- The MVP continues to use a host daemon with thin container clients over a mounted local socket.
- Bench containers remain the target runtime for FEAT-013; host-only tmux discovery stays later.
- Standard layout templates are enough for this feature; fully custom drag-and-drop topology design is later. Each template declares its own pane count; the spec does not impose a separate per-layout pane cap.
- Operator-overridable layout templates live in `~/.config/opensoft/agenttower/managed_templates/*.yaml`; operator-overridable launch command profiles live in `~/.config/opensoft/agenttower/launch_commands/*.yaml`. Built-in defaults ship with the daemon; operator files with the same `name` override the built-in.
- The first managed lifecycle actions apply only to panes created by AgentTower, not arbitrary adopted panes. Adopted-to-managed pane promotion is deferred; the managed-pane state model reserves a `promoted_from_adopted` transition for that later feature.
- Historical records (managed-layout and managed-pane lifecycle events) are preserved indefinitely in MVP so audit/event views remain coherent; retention pruning is a later feature.
- MVP authorization is socket-access based: any caller with access to the host daemon's local socket can create managed layouts. Per-user or per-container scoping is a later hardening feature.
