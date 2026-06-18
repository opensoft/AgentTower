# Design: Agent Connection-Strength Tier Model

## Context

AgentTower is a non-invasive observer/router over tmux panes in bench
containers (host daemon + thin clients over a Unix socket; SQLite + JSONL; no
network listener). Its only connection mechanism today is the tmux floor:
`pipe-pane` for observation, paste-buffer for delivery. The harnesses it targets
expose stronger structured surfaces, and Databricks' Omnigent provides a full
agent-driving runtime. This design defines how AgentTower opportunistically uses
stronger channels without giving up the universal floor or its router identity.

## Goals / Non-Goals

**Goals**
- A per-agent ladder from the tmux floor to native harness integration to an
  Omnigent hand-off.
- Independent negotiation of inbound (events) and outbound (delivery).
- A settled, documented role boundary (router vs puppet master).
- First-class Tier-1 for both managed launches and adopted pre-instrumented
  panes.

**Non-Goals**
- AgentTower does not drive an agent's task loop or intercept its tool calls.
- AgentTower does not embed or re-implement the Omnigent runner.
- No tier introduces a network listener.
- No code lands in this change (spec/design only).

## The connection-strength ladder

| Tier | Channel | Inbound (events) | Outbound (delivery) | Works on |
| --- | --- | --- | --- | --- |
| **0 — tmux** | `pipe-pane` + paste-buffer | scraped output, rule-classified | paste-buffer + Enter | _anything_ (universal floor; ships today) |
| **1 — native harness** | hooks / MCP / stream-json | exact harness events (Notification ⇒ `waiting_for_input`, Stop ⇒ `completed`) | structured message the harness accepts | Claude / Codex, per capability |
| **2 — Omnigent** | Omnigent session API / SSE | uniform structured events | hand off to Omnigent to drive | any harness Omnigent wraps |

Tier 0 is the guaranteed floor and is never removed. Tiers 1–2 are upgrades.

## Decision 1 — Two independent axes

Inbound (observation/events) and outbound (delivery) negotiate **separately**.
A discovered interactive Claude pane can keep its human-in-the-loop TUI, upgrade
its *events* to Tier 1 via hooks, and keep its *input* on the Tier-0
paste-buffer. This asymmetric state is the expected common case.

Rationale: it lets the lowest-risk, highest-value upgrade (read-only event
reporting) ship independently of structured delivery, and it matches the reality
that observation and delivery have very different safety profiles.

## Decision 2 — Router, not puppeteer

AgentTower stays the router:
- **Inbound:** agents *push* events via hooks, and/or *self-report* via an MCP
  **server** AgentTower hosts (tools like `report_status`, `request_route`).
  AgentTower is the MCP server; the agent is the client calling in. AgentTower
  does **not** act as an MCP client that drives the agent.
- **Outbound (Tier 1):** still *message routing* — delivering a prompt/
  notification through whatever structured inbox the harness accepts — not
  taking over the task loop or governing tool calls.
- **Action-level driving, sandboxing, and policy over an agent's own tool calls
  is Tier 2 (Omnigent).** AgentTower hands the agent off and continues to
  observe/route around it.

Rationale: this preserves AgentTower's value proposition (coordinate *unmodified*
agents) and avoids it becoming a competing runtime to Omnigent or Claude Code.

## Decision 3 — Adoption of pre-running panes is first-class

Strong integration generally requires control at session **startup** (hooks and
MCP wiring load at start; a running TUI can't switch into `stream-json`
mid-flight). AgentTower supports two entry points:

- **Managed launch (FEAT-013):** AgentTower sets flags/settings/hooks/MCP config
  when it spawns the pane and freely chooses Tier 1 or Tier 2.
- **Adopted pre-instrumented panes:** AgentTower ships its own hook scripts + MCP
  server, so pre-instrumenting a session is just adding AgentTower to the
  harness settings. Such a pane lights up Tier 1 on adoption; an uninstrumented
  pane stays at the tmux floor. Adoption never downgrades below the floor.

## Decision 4 — No-network-listener invariant preserved

Both Tier-1 mechanisms bridge to the daemon through the **existing Unix socket /
thin client**:
- Hook scripts run `agenttower` CLI subcommands that talk to the host daemon
  over the mounted Unix socket.
- AgentTower's MCP server is a **stdio** subprocess (launched by the harness)
  that bridges to the same Unix socket.

AgentTower remains a *client* of any external server, including Omnigent's
localhost server. No tier opens a network listener. This keeps the MVP
constitution (`architecture.md` §23) intact.

## Decision 5 — Per-agent integration mode + tier-independent safety

A per-agent `integration` field, negotiated at register/launch:
- `auto` (default): probe capability, use the strongest available axis-by-axis,
  fall back to tmux.
- `tmux-only`: force the non-invasive floor (audit / maximum-safety mode).
- `native`: require Tier 1; fail loudly if unsupported.
- `omnigent`: route through Omnigent (Tier 2).

The FEAT-009 permission gate and the global routing kill switch sit in front of
*every* outbound tier; upgrading the channel never bypasses the gate or the
`events.jsonl` audit trail.

## Native harness surfaces (Tier 1)

**Claude Code** — `-p` / `--print` headless with `--output-format stream-json` +
`--input-format stream-json` (managed/headless workers); **hooks**
(PreToolUse / PostToolUse / Notification / Stop) as the primary inbound channel;
**MCP** server hosted by AgentTower for self-report.

**Codex** — headless `exec`, a JSON output mode, and an MCP server mode (same
shape as Claude). **Exact flag spellings to be confirmed before implementation.**

## Related work — why Omnigent is Tier 2

Databricks open-sourced Omnigent (Apache-2.0), a meta-*harness* that *wraps and
launches* agents (Claude Code, Codex, Cursor, Pi, OpenAI) inside OS sandboxes
behind a uniform API, with stacked policies and live session sharing. AgentTower
is a meta-*observer/router* that coordinates agents it does not own. They sit at
opposite ends of the coupling spectrum and are complementary: Omnigent owns and
drives the agent (puppet master); AgentTower observes and routes around it
(router). That is precisely why Omnigent is the top tier AgentTower *hands off*
to rather than something it reimplements.

## Risks / Trade-offs

- **Version skew** with harness hook/MCP schemas and the Omnigent API — isolate
  each tier behind an adapter so a breaking upstream change is contained.
- **Two policy layers** at Tier 2 (Omnigent governs agent actions; AgentTower
  governs routing/delivery) — document precedence to avoid "who blocked this?"
  debugging traps. They are orthogonal: AgentTower decides *whether to send*,
  Omnigent decides what the agent may *do*.
- **Cloud Omnigent sandboxes** break the host-visible-log + UID invariant
  (`architecture.md` §4.1) and `docker exec` discovery — out of scope here;
  flagged for a dedicated future decision.

## Migration / Phasing

1. Tier-1 inbound via hooks (read-only; retires §13 classifier problem).
2. AgentTower-hosted MCP server (stdio → socket); enables pre-instrumented
   adoption.
3. Tier-1 outbound structured delivery behind the FEAT-009 gate.
4. Tier-2 Omnigent hand-off.

## Open Questions

- Codex exact flag spellings (`exec` / JSON / MCP) — confirm before tasks.
- Should an agent's negotiated tier be surfaced through the FEAT-011 `app.*`
  backend in the first implementing feature, or deferred?
- Cloud Omnigent sandboxes as a separate substrate backend — defer to its own
  change.
