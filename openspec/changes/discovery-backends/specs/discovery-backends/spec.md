# discovery-backends

Capability: abstract *where AgentTower discovers panes/agents from* behind a
pluggable backend interface, so multiple substrates (bench containers, host-only
tmux, future remote benches) feed the same registry without rewriting it.

## ADDED Requirements

### Requirement: Discovery backend interface

AgentTower SHALL define a discovery backend interface that enumerates targets
(hosts/containers), enumerates tmux panes within a target, probes host-visible
log-attachment capability per pane, and produces a stable identity key. The
registry, log, event, and routing layers SHALL consume panes through this
interface rather than calling a specific substrate (Docker) directly.

#### Scenario: Registry consumes panes via the interface

- **WHEN** a backend enumerates panes
- **THEN** the panes enter the registry through the backend interface, with no
  layer above discovery calling Docker directly

### Requirement: Bench-container discovery as a backend

AgentTower SHALL provide bench-container discovery (FEAT-003 / FEAT-004) as a
backend implementation with no observable change in behavior versus the current
hardwired discovery.

#### Scenario: Bench backend behavior is unchanged

- **WHEN** only the bench-container backend is enabled
- **THEN** the panes and containers discovered are identical to the pre-refactor
  behavior

### Requirement: Backend identity namespacing

AgentTower SHALL namespace pane/agent identities by backend so two backends
cannot collide on tmux pane ids. The registry key SHALL include the backend id
in addition to the existing tmux coordinates.

#### Scenario: Same pane id across backends does not collide

- **WHEN** a host-only backend reports pane `%4` and a bench backend reports
  pane `%4`
- **THEN** AgentTower treats them as two distinct agents, namespaced by backend

### Requirement: Per-backend degraded isolation

AgentTower SHALL run and degrade each backend independently. A backend that
fails (e.g. its runtime is unavailable) SHALL be marked degraded with an
actionable status while other backends continue scanning.

#### Scenario: One backend down does not stop others

- **WHEN** the bench backend's Docker runtime is unavailable but a host-only
  backend is healthy
- **THEN** the bench backend is reported degraded and the host-only backend
  still discovers panes

### Requirement: Backend enablement configuration

AgentTower SHALL allow each backend to be enabled or disabled in configuration.
A disabled backend SHALL produce no scans and no discovered panes.

#### Scenario: Disabled backend produces no scans

- **WHEN** a backend is disabled in configuration
- **THEN** AgentTower performs no discovery through that backend
