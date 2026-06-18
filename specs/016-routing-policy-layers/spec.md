# Feature Specification: Layered Routing / Input-Delivery Policies

**Feature Branch**: `016-routing-policy-layers`
**Created**: 2026-06-18
**Status**: Draft
**Owning bench**: `py-bench` (Python daemon only; no Flutter work in this feature)
**Source change**: `openspec/changes/routing-policy-layers/` (authoritative scope — proposal, design, `routing-policy` capability spec, tasks)
**Input**: Generate the FEAT from the merged OpenSpec change `routing-policy-layers`; mirror its requirements/scenarios, do not invent new scope.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Restrict deliveries with layered policies (Priority: P1)

An operator defines policies at the global, per-agent, and per-route scopes to
restrict how prompts/notifications are delivered — for example denying a source,
capping delivery rate, or requiring approval — and AgentTower enforces the most
restrictive applicable rule on every delivery.

**Why this priority**: This is the core capability and the reason the feature
exists: graduated, contextual control between "fully allowed" and the single
global kill switch that exists today.

**Independent Test**: Configure a per-target rate cap and a per-route deny, then
attempt deliveries and confirm each is allowed/blocked/held according to the most
restrictive matching rule.

**Acceptance Scenarios**:

1. **Given** a per-agent layer denies delivery and a per-route layer allows it, **When** a delivery is evaluated, **Then** delivery is blocked (deny-wins), regardless of the per-route allow.
2. **Given** a per-agent rate cap of 10/min and a per-route rate cap of 3/min both apply, **When** deliveries are evaluated, **Then** the effective cap is 3/min (most-restrictive-wins).
3. **Given** a per-target rate cap of 3/min, **When** a fourth delivery to that target is attempted within the window, **Then** the fourth delivery is blocked until the window resets.
4. **Given** a require-approval policy matches a delivery, **When** it is evaluated, **Then** the delivery is held (in the FEAT-009 `blocked` state) and is not delivered until an operator approves it via `queue approve`.
5. **Given** a global deny (kill switch engaged), **When** any delivery is evaluated, **Then** it is blocked and no lower-layer policy can override it.

---

### User Story 2 - Audit every policy decision (Priority: P2)

An operator inspects the audit trail to see which policy allowed, blocked, or held
each delivery, and at which layer.

**Why this priority**: Policy without auditability is undebuggable; operators must
be able to answer "why was this blocked/held?" — but auditing must not pollute the
no-policy path.

**Independent Test**: Trigger a per-route deny and confirm a single audit record
naming the deciding layer and matched rule; then run a delivery with no
user-defined policy and confirm no policy audit record is written.

**Acceptance Scenarios**:

1. **Given** a delivery blocked by a per-route deny, **When** it is evaluated, **Then** an audit record (`policy_blocked`) is appended naming the per-route layer and matched rule.
2. **Given** a delivery allowed where no user-defined policy participated, **When** it is evaluated, **Then** no policy audit record is written and the event stream matches pre-policy AgentTower exactly.

---

### User Story 3 - Zero impact when no policies are defined (Priority: P1)

An operator who defines no policies sees AgentTower behave exactly as it does
today (FEAT-009 permission gate + global kill switch), with a byte-identical event
stream.

**Why this priority**: Backward compatibility is a hard guarantee — the feature
must be safe to ship to existing deployments that adopt no policies.

**Independent Test**: With no user-defined policies, run the full delivery suite
and diff behavior + `events.jsonl` against pre-policy AgentTower.

**Acceptance Scenarios**:

1. **Given** no user-defined policies, **When** deliveries are evaluated, **Then** they are gated exactly as the FEAT-009 permission model and global kill switch would gate them.
2. **Given** a delivery target with role `unknown`, **When** evaluated, **Then** the base layer denies delivery as it does today.

### Edge Cases

- Overlapping caps at multiple layers → the minimum cap applies (most-restrictive-wins).
- A more-specific allow against a broader deny → blocked; a more specific layer can only narrow delivery, never re-open it.
- Approval never arrives for a held delivery → it remains in `blocked` and visible/cancellable via `agenttower queue` (no silent delivery, no silent drop).
- Policy references an agent/route that no longer exists → policy does not match; delivery falls through to remaining layers / base layer.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: AgentTower MUST compute each delivery decision across all applicable policy layers (global, per-agent, per-route) using most-restrictive-wins: deny-wins for allow/deny rules and minimum-wins for numeric limits.
- **FR-002**: A deny at any layer MUST block delivery, and a global deny MUST be absolute (never overridable by a lower-specificity layer).
- **FR-003**: The scope order (global → per-agent → per-route) MUST affect only audit attribution and tie-break labeling, never the outcome.
- **FR-004**: AgentTower MUST support these router-scoped policy types: per-target delivery rate caps, require-approval holds, allow/deny by source role + capability, and target-busy / quiet holds.
- **FR-005**: Policies MUST NOT attempt to govern an agent's own shell, file, or network actions (router scope only).
- **FR-006**: A require-approval hold MUST map onto the existing FEAT-009 queue model — the message sits in the `blocked` state and is released via `agenttower queue approve` (no new queue state; FEAT-009's closed set is `queued`, `blocked`, `delivered`, `canceled`, `failed`).
- **FR-007**: AgentTower MUST write an audit record (`policy_allowed` / `policy_blocked` / `policy_held`) to `events.jsonl` for every decision in which a user-defined policy participates, naming the deciding layer and matched rule.
- **FR-008**: When only the FEAT-009 base layer applies (no user-defined policy participates), AgentTower MUST NOT emit any policy audit record, keeping the no-policy event stream byte-identical to pre-policy AgentTower.
- **FR-009**: AgentTower MUST express the existing `send_input_allowed` permission and global routing kill switch as the base layer of the model, so that with no user-defined policies, delivery behavior is identical to pre-policy AgentTower.
- **FR-010**: Operators MUST be able to list, add, remove, and inspect policies (via CLI and the FEAT-011 app backend).
- **FR-011**: Every outbound delivery, at every connection tier, MUST pass the policy evaluation in front of the FEAT-009 gate; upgrading the delivery tier MUST NOT bypass policies or the audit trail.

### Out of Scope

- Governing an agent's own tool calls / shell / file / network actions — that is the Tier-2 (Omnigent) hand-off in the `agent-connection-tiers` change.
- LLM-based or semantic policy evaluation.

### Key Entities *(include if feature involves data)*

- **Policy**: a rule attached at a scope (global / per-agent / per-route) with a type (rate cap, require-approval, allow/deny by source, quiet hold) and parameters.
- **Policy decision**: the computed allow/block/hold outcome for a delivery, with the deciding layer and matched rule, emitted to the audit trail when a user-defined policy participates.
- **Base layer**: the FEAT-009 `send_input_allowed` permission + global kill switch, expressed as the lowest policy layer.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For any delivery, the enforced outcome equals the most restrictive applicable rule across all layers in 100% of evaluated cases (deny-wins; min cap).
- **SC-002**: A global deny blocks 100% of deliveries regardless of lower-layer policies.
- **SC-003**: With no user-defined policies, delivery behavior and `events.jsonl` are byte-identical to pre-policy AgentTower.
- **SC-004**: Every decision in which a user-defined policy participates produces exactly one audit record naming the deciding layer and rule; decisions with no user-defined policy produce zero policy audit records.
- **SC-005**: A held (require-approval) delivery is never delivered without an explicit approval and is always visible and cancellable in the queue.

## Assumptions

- Owning bench is `py-bench`; all implementation is Python daemon/CLI work with no Flutter/app changes in this feature.
- The authoritative scope is the merged OpenSpec change `routing-policy-layers`; this spec mirrors its requirements and scenarios.
- Builds on FEAT-009 (permission gate + global kill switch + queue states) and FEAT-010 (routes); composes with the tier-independent outbound safety from the `agent-connection-tiers` change.
- MVP constitution holds: no network listener; AgentTower remains a router and does not govern agent actions.
