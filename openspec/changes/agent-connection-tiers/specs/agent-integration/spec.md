# agent-integration

Capability: how AgentTower connects to each agent, on a per-agent
connection-strength ladder, while remaining the router (not the puppeteer).

## ADDED Requirements

### Requirement: Per-agent connection-strength ladder

AgentTower SHALL connect to each agent on a tiered ladder — Tier 0 (tmux floor:
`pipe-pane` observation + paste-buffer delivery), Tier 1 (native harness
integration), Tier 2 (Omnigent meta-harness hand-off) — and SHALL select a tier
per agent rather than globally. Tier 0 SHALL always be available and SHALL never
be removed.

#### Scenario: Tier 0 is the universal floor

- **WHEN** an agent supports no stronger channel
- **THEN** AgentTower connects at Tier 0 (pipe-pane observation + paste-buffer
  delivery) and the agent is fully usable

#### Scenario: Strongest available tier is selected per agent

- **WHEN** two agents are registered, one Tier-1-capable and one not
- **THEN** AgentTower connects the capable agent at Tier 1 and the other at
  Tier 0, independently

### Requirement: Independent inbound and outbound axes

AgentTower SHALL negotiate the inbound (observation/events) axis and the
outbound (delivery) axis independently per agent. An agent MAY have a higher
inbound tier than its outbound tier, or vice versa.

#### Scenario: Asymmetric tiers on one agent

- **WHEN** an interactive agent exposes Tier-1 inbound events but no structured
  delivery inbox
- **THEN** AgentTower uses Tier-1 events for that agent while delivery remains on
  the Tier-0 paste-buffer

### Requirement: Router-first role boundary

AgentTower SHALL act as the router: agents report *in* via hooks and/or an
AgentTower-hosted MCP server, and AgentTower SHALL NOT drive an agent's task loop
or intercept its tool calls. Action-level driving, sandboxing, and policy over an
agent's own tool calls SHALL be delegated to Omnigent (Tier 2).

#### Scenario: AgentTower hosts the MCP server, agent is the client

- **WHEN** an agent self-reports status via MCP
- **THEN** AgentTower receives the report as the MCP server and the agent acts as
  the MCP client; AgentTower issues no command that drives the agent's task loop

#### Scenario: Driving is delegated to Omnigent

- **WHEN** an operator needs an agent driven and governed at the action level
- **THEN** AgentTower hands the agent off to Omnigent (Tier 2) and continues to
  observe and route around it, rather than driving the agent itself

### Requirement: Per-agent integration mode

Each agent SHALL have an `integration` mode of `auto`, `tmux-only`, `native`, or
`omnigent`. `auto` SHALL be the default and SHALL probe for the strongest
available channel per axis and fall back to Tier 0 when probing fails or a
stronger tier is unsupported.

#### Scenario: auto falls back to the floor

- **WHEN** an agent's `integration` is `auto` and no stronger channel is
  detected
- **THEN** AgentTower connects the agent at Tier 0 without error

#### Scenario: native requires Tier 1

- **WHEN** an agent's `integration` is `native` but Tier 1 cannot be established
- **THEN** AgentTower reports an actionable failure rather than silently
  downgrading

#### Scenario: tmux-only forces the floor

- **WHEN** an agent's `integration` is `tmux-only`
- **THEN** AgentTower connects only at Tier 0 even if a stronger channel is
  available

### Requirement: First-class adoption of pre-running panes

AgentTower SHALL support upgrading adopted (already-running) panes to Tier 1 when
they were started pre-instrumented with AgentTower's shipped hook scripts and/or
MCP server. Adoption SHALL NOT downgrade an agent below the Tier-0 floor.

#### Scenario: Pre-instrumented adopted pane lights up Tier 1

- **WHEN** an already-running pane that was started with AgentTower's hook
  scripts / MCP server configured is adopted
- **THEN** AgentTower negotiates Tier 1 for it on adoption

#### Scenario: Uninstrumented adopted pane stays on the floor

- **WHEN** an already-running pane without AgentTower instrumentation is adopted
- **THEN** AgentTower connects it at Tier 0 and it remains fully usable

### Requirement: No-network-listener invariant for all tiers

No connection tier SHALL introduce a network listener. Tier-1 hook scripts SHALL
reach the daemon by invoking the `agenttower` CLI over the existing mounted Unix
socket, and the AgentTower MCP server SHALL be a stdio subprocess that bridges to
that same socket. AgentTower SHALL remain a client of any external server,
including Omnigent's localhost server.

#### Scenario: Hooks reach the daemon over the Unix socket

- **WHEN** a harness hook fires on an instrumented agent
- **THEN** the hook script delivers the event by calling the `agenttower` CLI
  over the mounted Unix socket, opening no network listener

#### Scenario: MCP server bridges over stdio to the socket

- **WHEN** a harness launches AgentTower's MCP server
- **THEN** the server runs as a stdio subprocess and bridges to the host daemon
  over the existing Unix socket, opening no network listener

### Requirement: Tier-independent outbound safety

Every outbound delivery, at every tier, SHALL pass the FEAT-009 permission gate
and respect the global routing kill switch, and SHALL be recorded in
`events.jsonl`. Upgrading the outbound tier SHALL NOT bypass the gate, the kill
switch, or the audit trail.

#### Scenario: Tier-1 delivery still honors the kill switch

- **WHEN** the global routing kill switch is engaged
- **THEN** an outbound Tier-1 structured delivery is blocked exactly as a Tier-0
  paste-buffer delivery would be

#### Scenario: Every tier's delivery is audited

- **WHEN** a message is delivered at any tier
- **THEN** an audit record for that delivery is written to `events.jsonl`
