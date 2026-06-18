# AgentTower Integration Tiers

Status: Research note (reference only) — v0.1
Date: 2026-06-18

> **Research only.** This is design-context/reference material. It records no
> committed scope and modifies no canonical spec. The connection-tier model
> described here is formalized as a proposal under
> `openspec/changes/agent-connection-tiers/` — that OpenSpec change, not this
> note, is the authoritative source for adopted scope.

This note defines AgentTower's **connection-strength model**: how AgentTower
connects to an agent ranges from a universal, fully non-invasive tmux floor up
to a uniform meta-harness channel, negotiated per agent. It generalizes the
Omnigent comparison (`docs/related-work-omnigent.md`) — Omnigent is **Tier 2**
of this broader architecture, not a standalone bolt-on.

It records two settled decisions:

1. **AgentTower is the router, not the puppeteer.** Even at strong tiers,
   AgentTower observes and routes; agents report *into* it. It does not drive an
   agent's task loop or intercept its tool calls.
2. **Omnigent is the puppet master.** When an agent needs to be driven,
   sandboxed, and governed at the action level, that role belongs to Omnigent
   (Tier 2). AgentTower hands the agent off; it does not try to become a
   competing runtime.

## 1. The connection-strength ladder

Per agent, AgentTower negotiates the strongest available channel and always
falls back to the tmux floor.

| Tier | Channel | Inbound (events) | Outbound (delivery) | Works on |
| --- | --- | --- | --- | --- |
| **0 — tmux** | `pipe-pane` + paste-buffer | scraped output, rule-classified | paste-buffer + Enter | _anything_ (universal floor; ships today) |
| **1 — native harness** | hooks / MCP / stream-json | exact harness events (Notification ⇒ `waiting_for_input`, Stop ⇒ `completed`) | structured message delivery the harness accepts | Claude / Codex, per capability |
| **2 — Omnigent** | Omnigent session API / SSE | uniform structured events | hand off to Omnigent to drive | any harness Omnigent wraps |

Tier 0 is the guaranteed floor and never goes away. Tiers 1–2 are upgrades.

## 2. Two independent axes

"Strong integration" is **not** a single switch. The inbound (observation) and
outbound (delivery) axes negotiate **independently** per agent.

A discovered interactive Claude pane can keep its human-in-the-loop TUI, upgrade
its *events* to Tier 1 via hooks, while its *input* stays Tier 0 paste-buffer.
That asymmetric state is the expected common case, not a degenerate one.

This split directly retires two pain points baked into the current
architecture:

- **`architecture.md` §13 conservative classification** — Tier-1 inbound makes
  `waiting_for_input` / `completed` *exact* (the harness fires the event)
  instead of inferred from scrollback.
- **`architecture.md` §16 idle detection / paste races** — a Tier-1 outbound
  delivery path removes the "is the pane ready?" guess.

## 3. Per-agent integration mode

A per-agent `integration` field, negotiated at register/launch time:

- `auto` (default) — probe capability, use the strongest available axis-by-axis,
  fall back to tmux.
- `tmux-only` — force the non-invasive floor (audit / maximum-safety mode).
- `native` — require Tier 1; fail loudly if the harness/session cannot support
  it.
- `omnigent` — route through Omnigent (Tier 2).

**The safety layer is tier-independent.** AgentTower's permission gate
(FEAT-009) and the global routing kill switch sit in front of *every* outbound
tier. Upgrading the channel never bypasses the gate or the audit trail; every
delivered message is still recorded in `events.jsonl`.

## 4. Native harness surfaces (Tier 1)

**Claude Code**

- `-p` / `--print` headless mode, with `--output-format stream-json` +
  `--input-format stream-json` for a bidirectional structured stdio channel
  (managed/headless workers).
- **Hooks** (PreToolUse / PostToolUse / Notification / Stop) — the agent
  *pushes* structured lifecycle events out. Primary Tier-1 **inbound** channel.
- **MCP** — AgentTower exposes a server the agent reports into. Primary Tier-1
  channel for self-report (see §6).

**Codex**

- Headless `exec` mode, a JSON output mode, and an MCP server mode. Same shape
  as Claude. Exact flag spellings to be confirmed when this reaches a spec.

## 5. The realism constraint: where strong tiers are reachable

Strong integration generally requires control at session **startup**, because
hooks and MCP wiring load when a session starts and a running TUI cannot be
switched into stream-json mid-flight. AgentTower supports both entry points:

- **Managed launch (FEAT-013).** AgentTower sets the flags / settings / hooks /
  MCP config when it spawns the pane, so it can choose Tier 1 or Tier 2 freely.
- **Adopted, pre-running panes — first-class.** We explicitly support upgrading
  adopted panes. The enabler is that **AgentTower ships its own MCP server and
  hook scripts** as part of the package, so "pre-instrumenting" a session is
  just adding AgentTower to the harness's settings. A pane started that way
  lights up Tier 1 on adoption; a pane started without it stays at the Tier 0
  floor (still fully useful). Adoption never *downgrades* an agent — at worst it
  stays on the floor.

So: **tmux is the universal floor; managed launch and pre-instrumented adoption
both unlock Tier 1; Omnigent is the uniform Tier 2 for agents that need
driving.**

## 6. Router-first wiring (the settled division of labor)

AgentTower stays the router. Concretely:

- **Inbound** is the priority and the lowest-risk upgrade: agents *push* events
  to AgentTower via hooks, and/or *self-report* via an MCP **server** that
  AgentTower exposes (tools like `report_status`, `request_route`). AgentTower
  is the MCP server; the agent is the client calling in. AgentTower does **not**
  act as an MCP client that drives the agent — that is the puppet-master role,
  reserved for Omnigent.
- **Outbound** at Tier 1 is still *message routing* — delivering a prompt or
  notification through whatever structured inbox the harness accepts — not
  taking over the agent's task loop, decomposing work, or governing its tool
  calls.
- **Action-level driving, sandboxing, and policy enforcement over an agent's
  own tool calls is Tier 2 (Omnigent).** When that is wanted, AgentTower hands
  the agent to Omnigent and continues to observe/route around it. See
  `docs/related-work-omnigent.md` §5–6 for why AgentTower deliberately does not
  become the runtime itself.

### No-network-listener invariant is preserved

Both Tier-1 mechanisms bridge to the daemon through the **existing Unix socket /
thin client**, so no new listener is introduced:

- Hook scripts run `agenttower` CLI subcommands that talk to the host daemon
  over the mounted Unix socket.
- AgentTower's MCP server is a **stdio** subprocess (launched by the harness)
  that bridges to the same Unix socket.

AgentTower remains a client of any external server (including Omnigent's
localhost server); it never opens a network listener of its own. This keeps the
MVP constitution (`architecture.md` §23) intact.

## 7. Recommended phasing

1. **Tier-0 floor** — shipped today (pipe-pane + paste-buffer).
2. **Tier-1 inbound via hooks (first real upgrade).** Read-only, lowest risk,
   and it retires the conservative-classifier problem on its own. Ship the
   AgentTower hook scripts and a `report-event` CLI/socket method.
3. **Tier-1 inbound + self-report via the AgentTower MCP server.** Enables
   pre-instrumented adoption.
4. **Tier-1 outbound structured delivery** behind the existing permission gate.
5. **Tier-2 Omnigent hand-off** for agents that need a puppet master
   (`docs/related-work-omnigent.md` phases).

## 8. Non-goals

- AgentTower does not drive an agent's task loop or intercept its tool calls
  (that is Omnigent's puppet-master role).
- AgentTower does not embed or re-implement the Omnigent runner.
- No tier requires a network listener.
- Adoption never downgrades an agent below the tmux floor.
