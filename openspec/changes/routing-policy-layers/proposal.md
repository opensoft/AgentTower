# Add Layered Routing/Input Delivery Policies

## Why

AgentTower's delivery safety today is two coarse knobs: a per-pane
`send_input_allowed` boolean (FEAT-009) and a single global routing kill switch.
There is no way to say "this master may send at most N prompts per minute to a
slave", "hold deliveries to this target for approval", or "deny delivery from
this capability" without code changes. Databricks' Omnigent demonstrated the
value of *stacked, contextual* policies; AgentTower needs the same expressiveness
— but scoped to what a **router** legitimately controls: routing and input
*delivery* decisions, never the agent's own tool calls (which AgentTower cannot
observe; that is Tier 2 / Omnigent territory).

This change adds a layered policy model that resolves global → per-agent →
per-route rules deterministically and gates every outbound delivery, composing
with the connection tiers from `agent-connection-tiers` (which already requires
tier-independent outbound safety).

## What Changes

- **Introduce a layered policy model** resolved in a fixed precedence order:
  global → per-agent → per-route, with a deterministic merge.
- **Define router-appropriate policy types:** per-target delivery rate caps,
  require-approval (ask-before-deliver), allow/deny by source role + capability,
  target-busy / quiet holds, and the global kill switch modeled as the
  top-level global policy.
- **Audit every decision:** each allow / block / hold writes an `events.jsonl`
  record naming the deciding layer and rule.
- **Make policies declarative and inspectable** via an `agenttower policy`
  CLI surface and the FEAT-011 app backend.
- **Preserve backward compatibility:** the existing `send_input_allowed` flag
  and global kill switch map onto the new model as the base layer; with no
  policies defined, behavior is identical to today.

## Impact

- **New capability spec:** `routing-policy`.
- **Builds on:** FEAT-009 (permission gate + kill switch), FEAT-010 (routes),
  and `agent-connection-tiers` (every outbound tier passes the gate).
- **Touches (in implementing features):** the delivery path, SQLite schema (a
  policies table), the audit event surface, the CLI, and the app backend.
- **No code ships in this change** — spec/design proposal only.
- **Non-goals:** governing an agent's own shell/file/network actions (Tier 2 /
  Omnigent); LLM-based policy evaluation.
- **Open question:** fixed rule-types vs a small policy DSL for the first
  implementing feature.
