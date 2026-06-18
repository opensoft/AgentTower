# app-collaboration

Capability: let multiple operators connect to the same local AgentTower daemon
and share one live view, with a server-enforced split between read-only watchers
and permitted co-drivers. Local, same-host only; no new network listener.

## ADDED Requirements

### Requirement: App session roles

AgentTower SHALL assign each app session a role of `observer` (read-only) or
`operator` (may perform mutations), established under the existing FEAT-011
same-host-UID trust model without introducing a new listener or persisted
credential.

#### Scenario: Observer and operator sessions coexist

- **WHEN** two app sessions connect, one as `observer` and one as `operator`
- **THEN** both are tracked in the session registry with their respective roles

### Requirement: Consistent shared live view

AgentTower SHALL present all connected app sessions with the same registry state
and the same event stream, sourced from the single daemon, so connected clients
converge on identical state.

#### Scenario: Both sessions see a new event

- **WHEN** a new event is emitted while an observer and an operator are both
  connected
- **THEN** both sessions observe that event from the shared daemon stream

### Requirement: Server-side co-drive enforcement

AgentTower SHALL permit mutating `app.*` methods only for `operator` sessions
and SHALL reject mutating calls from `observer` sessions with a closed-set error.
Enforcement SHALL be server-side and SHALL NOT depend on client cooperation.

#### Scenario: Observer mutation is rejected

- **WHEN** an `observer` session calls a mutating `app.*` method
- **THEN** AgentTower rejects the call with a closed-set error and performs no
  mutation

#### Scenario: Operator mutation is allowed

- **WHEN** an `operator` session calls a mutating `app.*` method
- **THEN** AgentTower performs the mutation through the same validation path as
  the CLI

### Requirement: Cross-session mutation audit

AgentTower SHALL record the originating app session id on every mutation so that
"who did what" is answerable when multiple operators are connected.

#### Scenario: Mutation records its session

- **WHEN** an `operator` session performs a mutation
- **THEN** the audit record for that mutation identifies the originating app
  session id

### Requirement: Local-only collaboration boundary

AgentTower SHALL scope collaboration to same-host app sessions over the existing
Unix socket. Remote, URL-based, or mobile sharing SHALL NOT be provided by this
capability and SHALL require a separately decided authenticated transport.

#### Scenario: No remote sharing surface is exposed

- **WHEN** collaboration is enabled
- **THEN** no network listener is opened and collaboration is reachable only
  from same-host app sessions over the existing socket
