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

### Requirement: Default role and server-side operator promotion

AgentTower SHALL default every new app session to `observer`. A session SHALL
become `operator` only through an explicit, server-side promotion recorded by
the daemon; a client SHALL NOT be able to self-select `operator` (e.g. via an
`app.hello` parameter). Because all sessions already share the FEAT-011
same-host-UID trust model, this role is a **coordination control** to prevent
accidental concurrent co-drive, not a privilege boundary; existing pre-role
clients that predate this capability SHALL be treated as `observer` until
promoted.

#### Scenario: New session defaults to observer

- **WHEN** an app session is established (including a client that predates this
  capability)
- **THEN** it is `observer` until an explicit server-side promotion occurs

#### Scenario: Client cannot self-select operator

- **WHEN** a client attempts to declare itself `operator` at connection time
- **THEN** AgentTower keeps it as `observer` and requires an explicit server-side
  promotion to grant `operator`

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
and SHALL reject mutating calls from `observer` sessions by reusing the existing
FEAT-011 closed-set error code `permission_denied` with
`details.reason = "observer_read_only"` (no new top-level error code is
introduced). Enforcement SHALL be server-side and SHALL NOT depend on client
cooperation.

#### Scenario: Observer mutation is rejected

- **WHEN** an `observer` session calls a mutating `app.*` method
- **THEN** AgentTower rejects the call with `permission_denied` /
  `details.reason = "observer_read_only"` and performs no mutation

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
