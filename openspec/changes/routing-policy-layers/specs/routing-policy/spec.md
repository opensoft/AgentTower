# routing-policy

Capability: layered, contextual control over routing and input *delivery*
decisions in AgentTower. Scoped to what a router controls; it does not govern an
agent's own tool calls.

## ADDED Requirements

### Requirement: Layered policy resolution

AgentTower SHALL resolve delivery policies across three scopes in fixed
precedence — global, then per-agent, then per-route — using deny-wins for
allow/deny rules and most-restrictive-wins (minimum) for numeric limits. A deny
at any layer SHALL block delivery, and a global deny SHALL NOT be overridable by
a lower layer.

#### Scenario: Global deny is absolute

- **WHEN** a global policy denies routing (the kill switch is engaged)
- **THEN** delivery is blocked regardless of any per-agent or per-route policy

#### Scenario: Most-restrictive numeric limit wins

- **WHEN** a per-agent rate cap of 10/min and a per-route rate cap of 3/min both
  apply to a delivery
- **THEN** the effective cap is 3/min

### Requirement: Router-scoped policy types

AgentTower SHALL support delivery policy types that a router can enforce:
per-target rate caps, require-approval holds, allow/deny by source role and
capability, and target-busy / quiet holds. Policies SHALL NOT attempt to govern
an agent's own shell, file, or network actions.

#### Scenario: Rate cap blocks excess deliveries

- **WHEN** a per-target rate cap of 3 per minute is configured and a fourth
  delivery to that target is attempted within the window
- **THEN** the fourth delivery is blocked until the window resets

#### Scenario: Require-approval holds delivery

- **WHEN** a require-approval policy matches a delivery
- **THEN** the delivery is held in a pending state and is not delivered until an
  operator approves it

#### Scenario: Deny by source capability

- **WHEN** a policy denies delivery from source capability `shell`
- **THEN** a delivery originating from a `shell`-capability agent is blocked

### Requirement: Policy decision auditing

AgentTower SHALL write an audit record to `events.jsonl` for every policy
decision, naming the outcome (allowed / blocked / held), the deciding layer, and
the matched rule.

#### Scenario: Blocked delivery is audited

- **WHEN** a delivery is blocked by a per-route deny
- **THEN** an audit record is appended to `events.jsonl` identifying the
  per-route layer and the matched rule

### Requirement: Backward-compatible defaults

AgentTower SHALL express the existing `send_input_allowed` permission and global
routing kill switch as the base layer of the policy model. With no user-defined
policies present, delivery behavior SHALL be identical to pre-policy AgentTower.

#### Scenario: No policies means unchanged behavior

- **WHEN** no user-defined policies exist
- **THEN** deliveries are gated exactly as the FEAT-009 permission model and
  global kill switch would gate them

#### Scenario: Unknown target stays denied

- **WHEN** the delivery target has role `unknown`
- **THEN** the base layer denies delivery as it does today
