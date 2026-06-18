# Feature Specification: Pluggable Discovery / Substrate Backends

**Feature Branch**: `015-discovery-backends`
**Created**: 2026-06-18
**Status**: Draft
**Owning bench**: `py-bench` (Python daemon only; no Flutter work in this feature)
**Source change**: `openspec/changes/discovery-backends/` (authoritative scope — proposal, design, `discovery-backends` capability spec, tasks)
**Input**: Generate the FEAT from the merged OpenSpec change `discovery-backends`; mirror its requirements/scenarios, do not invent new scope.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Bench discovery behind a backend interface, unchanged (Priority: P1)

The operator runs AgentTower exactly as today and discovers panes/agents in bench
containers. Internally, that discovery now flows through a pluggable backend
interface, but nothing the operator observes changes.

**Why this priority**: This is the foundational refactor that unlocks every later
backend. It must land first and prove "no observable behavior change" before any
second substrate is added.

**Independent Test**: With only the bench backend enabled, run the existing
discovery flow and confirm the discovered containers/panes/agents are identical
to pre-refactor AgentTower.

**Acceptance Scenarios**:

1. **Given** only the bench-container backend is enabled, **When** discovery runs, **Then** the discovered containers, panes, and agents match pre-refactor behavior exactly.
2. **Given** the registry/event/routing layers, **When** panes are discovered, **Then** they enter the registry through the backend interface, with no layer above discovery calling Docker directly.

---

### User Story 2 - Run multiple backends without collision (Priority: P2)

The operator enables both bench-container discovery and host-only tmux discovery
at the same time. Panes from each substrate appear distinctly, even when they
share a tmux pane id, and a failure in one substrate does not affect the other.

**Why this priority**: Proves the abstraction with a real second backend and
delivers the long-deferred host-only tmux discovery, while guaranteeing the two
cannot corrupt each other's identities or availability.

**Independent Test**: Enable bench + host-only backends, induce a `%4` pane id in
both, and confirm two distinct agents; then take one backend's runtime down and
confirm the other keeps discovering.

**Acceptance Scenarios**:

1. **Given** a host-only backend reporting pane `%4` and a bench backend reporting pane `%4`, **When** both scan, **Then** AgentTower tracks two distinct agents, namespaced by backend.
2. **Given** the bench backend's Docker runtime is unavailable and a host-only backend is healthy, **When** discovery runs, **Then** the bench backend is reported degraded and the host-only backend still discovers panes.

---

### User Story 3 - Enable/disable backends by configuration (Priority: P3)

The operator turns a backend on or off in configuration to control which
substrates AgentTower scans.

**Why this priority**: Operational control; lower urgency than the interface and
the second backend, but needed for a usable multi-backend system.

**Independent Test**: Disable a backend in config and confirm it performs no
scans and surfaces no panes.

**Acceptance Scenarios**:

1. **Given** a backend is disabled in configuration, **When** discovery runs, **Then** AgentTower performs no discovery through that backend and surfaces none of its panes.

---

### User Story 4 - Seamless upgrade of an existing bench-only deployment (Priority: P2)

An operator upgrades a deployment that predates backend namespacing. Their
existing agents, events, and queue history remain intact and become part of the
`bench` namespace automatically, with no manual steps.

**Why this priority**: Without a clean migration, namespacing would orphan
existing registry rows and break references — a blocker for shipping the refactor
to any real deployment.

**Independent Test**: Take a pre-namespacing database, run the upgrade, and
confirm every agent/pane identity is stamped `bench` with all events/offsets/queue
references preserved and no operator action required.

**Acceptance Scenarios**:

1. **Given** a deployment created before namespacing, **When** it is upgraded, **Then** a one-time idempotent migration stamps every existing identity into the `bench` namespace with history preserved and no operator action.
2. **Given** the migration has already run, **When** the daemon restarts, **Then** the migration is a no-op (idempotent) and a legacy unprefixed key encountered during the transition resolves as `bench:<key>`.

### Edge Cases

- A backend returns a target it can observe but cannot attach host-visible logs to → the backend reports its attach-log capability per pane so the log layer degrades gracefully rather than failing globally.
- The same physical host is visible to two backends → identity namespacing keeps the two views distinct without aliasing.
- A backend partially fails mid-scan → only that backend is marked degraded; previously discovered records from other backends are unaffected.
- A legacy unprefixed identity key appears after the migration window → resolved via the transition read-time shim until the shim is retired.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: AgentTower MUST define a discovery backend interface that enumerates targets (hosts/containers), enumerates tmux panes within a target, probes host-visible attach-log capability per pane, and produces a stable identity key.
- **FR-002**: The registry, log, event, and routing layers MUST consume discovered panes through the backend interface rather than calling a specific substrate (e.g., Docker) directly.
- **FR-003**: AgentTower MUST provide bench-container discovery (current FEAT-003 / FEAT-004 behavior) as a backend implementation with no observable change in behavior.
- **FR-004**: AgentTower MUST namespace pane/agent identities by a backend id so two backends cannot collide on tmux pane ids; the registry key MUST include the backend id in addition to the existing tmux coordinates.
- **FR-005**: AgentTower MUST run and degrade each backend independently; a backend that fails MUST be marked degraded with an actionable status while other backends continue scanning.
- **FR-006**: AgentTower MUST allow each backend to be enabled or disabled in configuration; a disabled backend MUST produce no scans and no discovered panes.
- **FR-007**: AgentTower MUST provide a host-only tmux discovery backend as a second reference backend.
- **FR-008**: On upgrade of a pre-namespacing deployment, AgentTower MUST run a one-time, idempotent, history-preserving migration that stamps existing agent/pane/offset rows with backend id `bench`, tied to the schema-version bump, preserving events, offsets, and queue references.
- **FR-009**: During the migration transition, AgentTower MUST treat a legacy unprefixed identity key as belonging to the `bench` namespace (read-time shim) until the shim is retired.
- **FR-010**: AgentTower MUST NOT introduce a network listener and MUST remain a router; discovery backends only observe substrates, they do not drive agents.

### Out of Scope

- Implementing a cloud/remote bench backend (this feature ships the interface plus the host-only reference backend only).
- Treating Omnigent sessions as a discovery backend — Omnigent is the Tier-2 hand-off defined in the `agent-connection-tiers` change, not a substrate here.

### Key Entities *(include if feature involves data)*

- **Discovery backend**: a named source of substrate discovery (`bench`, `host`, …) implementing the interface; has enable/disable config and a health/degraded status.
- **Backend-namespaced identity**: a pane/agent identity key prefixed by backend id, combined with the existing tmux coordinates, used as the registry key.
- **Migration record**: the one-time schema-version-tied operation that stamps pre-namespacing rows into the `bench` namespace.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With only the bench backend enabled, discovery output (containers, panes, agents) is identical to pre-refactor AgentTower in 100% of compared cases.
- **SC-002**: When two backends report the same tmux pane id, they are always tracked as two distinct agents (0 collisions).
- **SC-003**: When one backend's runtime is unavailable, every other enabled backend continues to discover with no degradation attributable to the failed backend.
- **SC-004**: A disabled backend performs zero scans and surfaces zero panes.
- **SC-005**: Upgrading a pre-namespacing deployment preserves 100% of existing agents, events, offsets, and queue references, with zero operator actions required, and re-running the upgrade changes nothing (idempotent).

## Assumptions

- Owning bench is `py-bench`; all implementation is Python daemon/CLI work with no Flutter/app changes in this feature.
- The authoritative scope is the merged OpenSpec change `discovery-backends`; this spec mirrors its requirements and scenarios.
- The existing FEAT-003/FEAT-004 integration tests are available to guard the behavior-preserving bench-backend refactor.
- The host-visible-log invariant (FEAT-007 / architecture §4.1) is treated as a per-backend capability rather than a global assumption.
- MVP constitution holds: no network listener; AgentTower observes and routes, it does not drive agents.
