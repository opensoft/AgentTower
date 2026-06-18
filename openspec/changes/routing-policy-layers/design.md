# Design: Layered Routing/Input Delivery Policies

## Context

AgentTower is a router: it delivers structured prompts/notifications between tmux
panes, gated by FEAT-009's permission model (per-pane `send_input_allowed`
derived from role) and a single global routing kill switch (`daemon_state.
routing_enabled`). FEAT-010 adds route subscriptions that enqueue through the
same gate. There is no graduated, contextual control between "fully allowed" and
"globally off". This design adds a layered policy model that sits in the
delivery path without changing AgentTower's router identity.

## Goals / Non-Goals

**Goals**
- A deterministic, auditable policy stack (global → per-agent → per-route).
- Policy types that a router can actually enforce on delivery.
- Full backward compatibility with FEAT-009 defaults.

**Non-Goals**
- Governing an agent's own tool calls / shell / file / network actions — that is
  Tier 2 (Omnigent), per `agent-connection-tiers`.
- LLM-based or semantic policy evaluation.
- Per-agent explicit grant *identity* models beyond role+capability (future).

## Decision 1 — Layered resolution and precedence

Policies attach at three scopes and resolve in a fixed order:

1. **global** — applies to all deliveries (the kill switch is the canonical
   global policy).
2. **per-agent** — keyed by target `agent_id` (and optionally source).
3. **per-route** — keyed by `route_id` (FEAT-010).

Resolution is **most-specific-wins for allow/deny, most-restrictive-wins for
limits**: a deny at any layer blocks; a numeric cap takes the minimum across
layers. This avoids "which rule won" ambiguity and keeps the global kill switch
absolute (a global deny can never be overridden by a lower layer).

Rationale: deterministic, explainable, and safe-by-default — broadening requires
an explicit higher-specificity allow, never an implicit one.

## Decision 2 — Router-appropriate policy types (MVP set)

- **rate cap** — max N deliveries per target per time window.
- **require-approval** — hold delivery in a pending state until an operator
  approves (reuses the FEAT-009 queue states: queued/blocked/approved).
- **allow/deny by source** — match on source role + capability.
- **target-busy / quiet hold** — defer delivery while the target is mid-command
  or within a configured quiet window (conservative; ties to the `architecture.
  md` §16 idle question).
- **global kill switch** — the existing switch, modeled as the top global deny.

All default to the *least-surprising* behavior: absent any policy, deliveries
behave exactly as FEAT-009 today.

## Decision 3 — Every decision is audited

Each evaluation emits one `events.jsonl` record: `policy_allowed` /
`policy_blocked` / `policy_held`, carrying the deciding layer, the matched rule
id, and the target/route. This mirrors FEAT-010's `route_matched` /
`route_skipped` auditability so the full delivery chain stays inspectable via
`agenttower events`.

## Decision 4 — Backward compatibility

`send_input_allowed` and `routing_enabled` are re-expressed as the base layer of
the model: an `unknown` target carries an implicit per-agent deny; the kill
switch is the global deny. A deployment with no user-defined policies produces
byte-identical delivery behavior to pre-policy AgentTower.

## Risks / Trade-offs

- **Complexity vs predictability** — mitigated by the fixed precedence + the two
  simple merge rules (deny-wins, min-wins).
- **Hold/approval UX** — pending-approval deliveries must be visible and
  cancellable (reuse `agenttower queue`).
- **Policy DSL scope creep** — MVP should ship fixed rule-types; a DSL is an
  open question, not a commitment.

## Migration / Phasing

1. Schema: add a `policies` table + the three scope keys.
2. Evaluate policies in the existing delivery path (no new delivery surface).
3. CLI + app-backend read/write.
4. Backward-compat mapping of FEAT-009 defaults.

## Open Questions

- Fixed rule-types only, or a minimal policy DSL, for the first implementing
  feature?
- Should rate-cap windows be per-source, per-target, or per-(source,target)
  pair by default?
