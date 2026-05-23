# Data Model Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate the user-facing data-model requirements (Key Entities + their FRs) for completeness, clarity, consistency, lifecycle coverage, and identity rules. Tests the requirements themselves, not the daemon's storage.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Project, Master Summary, Sub-agent, Pane, Adopted Agent, Feature/Change Status, Handoff, Drift Signal, Validation Entrypoint, Validation Run, Validation Target, Demo Readiness Summary, Attention Item, Notification, Operator History Entry, Workspace Selection.

## Identity & Uniqueness

- [ ] CHK001 - Is the identity rule for Project ("one project = one git repository", Assumption + FR-026) tied to a specific identifier (path? remote URL? daemon-issued id?) so duplicate inference cannot create two cards for the same repo? [Completeness, Spec §FR-026 / Assumptions]
- [ ] CHK002 - Is the identity rule for Adopted Agent specified (label uniqueness within container? globally unique daemon-side id?)? [Completeness, Gap, Spec §FR-015 / §FR-016 / Key Entities]
- [ ] CHK003 - Is the identity rule for Master Summary derived from the underlying agent identity, or does it have its own master-specific id? [Clarity, Spec §FR-030 / §FR-071 / Key Entities]
- [ ] CHK004 - Is the identity rule for Handoff (`handoff id`) defined as daemon-issued, app-issued, or shared? Does FR-042's "handoff id" guarantee monotonicity / uniqueness? [Clarity, Spec §FR-042]
- [ ] CHK005 - Is the identity rule for Drift Signal defined to remain stable across status transitions, or can repair_planned regenerate the id? [Clarity, Gap, Spec §FR-033 / §FR-034]
- [ ] CHK006 - Is the identity rule for Validation Entrypoint specified (per-daemon? per-project? per-target?)? [Completeness, Gap, Spec §FR-047 / Key Entities]
- [ ] CHK007 - Is the identity rule for Validation Run specified — does cancellation followed by re-trigger produce a new id or reuse? [Coverage, Gap, Spec §FR-048]

## Attribute Completeness Per Entity

- [ ] CHK008 - Does Project (Key Entities) include every attribute FR-025 says the project card shows, with no gaps? [Completeness, Spec §FR-025 / Key Entities]
- [ ] CHK009 - Does Master Summary include every attribute FR-030 requires, with no gaps? [Completeness, Spec §FR-030 / Key Entities]
- [ ] CHK010 - Does Adopted Agent include every attribute FR-016 captures at adoption (label, role, capability, project path, log-attach choice)? [Completeness, Spec §FR-016 / Key Entities]
- [ ] CHK011 - Does Handoff include every input from FR-036, every auto-filled field from FR-038, the generated prompt structure from FR-040, every editable field from FR-041, and every persisted field from FR-042? [Completeness, Spec §FR-036–FR-042 / Key Entities]
- [ ] CHK012 - Does Drift Signal include every attribute FR-033 requires, plus the lifecycle states FR-034 enumerates? [Completeness, Spec §FR-033 / §FR-034 / Key Entities]
- [ ] CHK013 - Does Validation Run include every state in FR-048 and every result in FR-048, plus the linkage to entrypoint and target? [Completeness, Spec §FR-048 / Key Entities]
- [ ] CHK014 - Does Demo Readiness Summary include every attribute FR-050 requires, plus the constraint "at most `at_risk` if any required entrypoint has not run on the current branch"? [Completeness, Spec §FR-050 / Key Entities]
- [ ] CHK015 - Does Attention Item include the resolution-target attribute (FR-054 says clicking navigates to a resolution surface — is the target a daemon-side pointer or app-resolved)? [Clarity, Spec §FR-054 / Key Entities]
- [ ] CHK016 - Does Notification include sufficient attributes to support the FR-057 grouping rule (event_class, agent_id, severity, timestamp)? [Completeness, Spec §FR-057 / Key Entities]
- [ ] CHK017 - Does Workspace Selection include all dimensions FR-069 says are persisted (window geometry, theme, density, etc.)? [Consistency, Spec §FR-069 / Key Entities]

## Relationships & Cardinality

- [ ] CHK018 - Is the Project → Adopted Agent relationship cardinality defined (1:N, with project inferred from agent `project_path` per Assumption)? [Completeness, Spec §Assumptions / Key Entities]
- [ ] CHK019 - Is the Master → Sub-agent relationship defined as 1:N with at most 2 visible levels (FR-015) — and is the deeper-depth flatten rule reflected in the data model? [Consistency, Spec §FR-015 / Key Entities]
- [ ] CHK020 - Is the Handoff → Feature/Change relationship multi-valued (selected work items + resolved work items + primary work item)? [Completeness, Spec §FR-042 / Key Entities]
- [ ] CHK021 - Is the Handoff → Master relationship 1:1 (FR-071: a handoff targets exactly one master) defined, or could a handoff fan out to multiple masters? [Clarity, Spec §FR-036 / §FR-042 / §FR-071]
- [ ] CHK022 - Is the Drift Signal → Feature/Change/Branch/Worktree relationship cardinality defined (optional one-to-many per scope type)? [Clarity, Spec §FR-033 / Key Entities]
- [ ] CHK023 - Is the Validation Run → Validation Target relationship defined to allow a single run to target multiple features (e.g. a smoke covering several FRs)? [Coverage, Gap, Spec §FR-048 / Key Entities]
- [ ] CHK024 - Is the Notification → underlying-event relationship defined so that the operator can navigate from a notification to its source event/agent? [Coverage, Gap, Spec §FR-056]

## Lifecycle & State Transitions

- [ ] CHK025 - Is the Pane state machine (discovered-and-unmanaged → discovered-and-registered, plus inactive/stale and discovery-degraded) defined with allowed transitions (e.g. can a registered pane become discovery-degraded)? [Completeness, Spec §FR-014 / Key Entities]
- [ ] CHK026 - Is the Adopted Agent lifecycle defined for de-adoption (does removal of the registration produce a "discovered-and-unmanaged" pane again)? [Coverage, Gap, Spec §FR-016]
- [ ] CHK027 - Is the Drift Signal lifecycle (`new → review_needed → confirmed → repair_planned → resolved`, plus `accepted_as_built` and `dismissed`) constrained — can a finding skip states? [Clarity, Spec §FR-034]
- [ ] CHK028 - Is the Handoff lifecycle (FR-044: drafted, submitted, accepted, active, waiting, blocked, completed, cancelled, superseded) defined with allowed transitions and terminal states? [Clarity, Spec §FR-044]
- [ ] CHK029 - Is the Validation Run lifecycle (queued → running → completed / cancelled / failed_to_start) defined to disallow result before completed (e.g. can a `queued` run have a result)? [Clarity, Spec §FR-048]
- [ ] CHK030 - Is the Feature/Change three-layer status model (FR-028: stage + execution status + optional subphase) defined with the matrix of allowed combinations (e.g. is `merged + active` valid)? [Coverage, Spec §FR-028]
- [ ] CHK031 - Is the Notification lifecycle (incoming → processed → notification history) defined with reversibility (can a processed notification be re-flagged as unread)? [Coverage, Gap, Spec §FR-056]
- [ ] CHK032 - Is the Operator History Entry lifecycle defined (append-only? mutable? rollups recompute on new sub-agent events)? [Coverage, Gap, Spec §FR-055]

## Reference Integrity

- [ ] CHK033 - Is the rule defined for what happens to a Handoff record when the target Master is later removed/un-adopted (cascade? orphan with placeholder?)? [Coverage, Gap, Spec §FR-042]
- [ ] CHK034 - Is the rule defined for what happens to a Drift Signal when the linked Feature/Change is merged or removed? [Coverage, Gap, Spec §FR-033]
- [ ] CHK035 - Is the rule defined for what happens to a Validation Run when its Validation Entrypoint is disabled or removed? [Coverage, Gap, Spec §FR-048]
- [ ] CHK036 - Is the rule defined for `superseded_by_handoff_id` integrity — does the new handoff's id resolve, and does the prior handoff still surface in handoff queries? [Coverage, Spec §FR-042 / §FR-081]

## Volume, Pagination, and Scale Assumptions

- [ ] CHK037 - Is the scale assumption "~5 or fewer projects" (FR-024) restated in any data-model expectation that limits per-project memory residency? [Coverage, Spec §FR-024]
- [ ] CHK038 - Are scale expectations specified for live event/queue/notification throughput so the FR-080 virtualized list and FR-064 2-second live-update budget remain meaningful? [Coverage, Gap, Spec §FR-064 / §FR-080]
- [ ] CHK039 - Are scale expectations specified for handoff record growth so FR-045 query filters remain responsive (and so date-range default windows are sized correctly)? [Coverage, Gap, Spec §FR-045]

## Persistence Boundaries

- [ ] CHK040 - Is the boundary clear between "daemon-owned, never persisted by the app" (FR-069) and "app-owned UX state, persisted" — and does the boundary map cleanly to the Key Entities list? [Consistency, Spec §FR-069 / Key Entities]
- [ ] CHK041 - Is "Workspace Selection" the only Key Entity the app persists, or are there others (e.g. Settings, theme, density) that also need first-class entity status? [Coverage, Gap, Spec §FR-069 / Key Entities]

## Terminology Across Entities

- [ ] CHK042 - Is "master" used consistently as an attribute of an Adopted Agent (FR-071) and as a first-class entity (Master Summary, Key Entities) without confusion about which is the source of truth? [Consistency, Spec §FR-071 / Key Entities]
- [ ] CHK043 - Is "feature/change" used consistently across the data model — does it mean "feature OR change" or "feature-or-change pair"? [Clarity, Spec §FR-027 / §FR-028 / Key Entities]
- [ ] CHK044 - Is "operator" defined as a daemon-side identity, an app-side label, or the implicit single OS user (per FR-061a)? [Clarity, Spec §FR-061a / §FR-042 / Key Entities]

## Scenario Class Coverage (Data Model)

- [ ] CHK045 - Are Primary-flow data requirements complete enough that every User Story scenario can be reconstructed from the entity definitions? [Coverage, Spec §User Scenarios / Key Entities]
- [ ] CHK046 - Are Alternate-flow data requirements present for unusual states (project with zero features, master with zero sub-agents, handoff with empty resolved-list)? [Coverage, Gap]
- [ ] CHK047 - Are Exception-flow data requirements present for partial-data scenarios (a Pane discovered without a container name, an Agent with no recorded last activity)? [Coverage, Gap]
- [ ] CHK048 - Are Recovery-flow data requirements present for re-fetching after disconnect — do entities carry a `as_of` timestamp the app can use to detect staleness? [Coverage, Gap, Spec §FR-003]

## Measurability

- [ ] CHK049 - Can each entity's attribute set be tested against the daemon's `app.*` response shapes for completeness? [Measurability, Gap, Spec §Key Entities / §FR-005]
- [ ] CHK050 - Can the lifecycle constraints (FR-014, FR-028, FR-034, FR-044, FR-048) be encoded as a state-machine assertion the app can verify on every update? [Measurability, Spec §FR-014 / §FR-028 / §FR-034 / §FR-044 / §FR-048]
