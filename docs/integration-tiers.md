# AgentTower Integration Tiers (research note)

Status: Research note (reference only) — v0.2
Date: 2026-06-18

> **Research only — not the authoritative source.** The connection-tier model is
> formalized in the OpenSpec change `openspec/changes/agent-connection-tiers/`
> (`proposal.md`, `design.md`, and the `agent-integration` spec delta). For any
> normative description of the tiers, the two axes, integration modes, the
> router-vs-puppeteer boundary, the adoption story, or the no-network-listener
> invariant, read that change — **not this note.** This file is kept only as an
> orientation/on-ramp plus a little extra comparative context, to avoid the two
> drifting apart.

## Orientation: the connection-strength ladder

Per agent, AgentTower negotiates the strongest available channel and always
falls back to the tmux floor. (Full normative model: `agent-connection-tiers`.)

| Tier | Channel | Inbound (events) | Outbound (delivery) | Works on |
| --- | --- | --- | --- | --- |
| **0 — tmux** | `pipe-pane` + paste-buffer | scraped output, rule-classified | paste-buffer + Enter | _anything_ (universal floor; ships today) |
| **1 — native harness** | hooks / MCP / stream-json | exact harness events | structured message delivery the harness accepts | Claude / Codex, per capability |
| **2 — Omnigent** | Omnigent session API / SSE | uniform structured events | hand off to Omnigent to drive | any harness Omnigent wraps |

Two settled decisions anchor the model (both specified normatively in the
design): **AgentTower is the router, not the puppeteer** (agents report *into*
it; it never drives an agent's task loop or intercepts tool calls), and
**Omnigent is the puppet master** AgentTower hands off to for action-level
driving.

## What the authoritative change covers

Rather than restate it here, see `openspec/changes/agent-connection-tiers/` for:

- the tier ladder and Tier-0-as-floor guarantee;
- independent inbound/outbound axis negotiation;
- the per-agent `integration` mode (`auto` / `tmux-only` / `native` /
  `omnigent`);
- tier-independent outbound safety (FEAT-009 gate + kill switch in front of
  every tier);
- first-class adoption of pre-instrumented panes;
- the no-network-listener invariant (hooks call the CLI over the Unix socket;
  the MCP server is a stdio bridge to that socket).

## Extra comparative context (the part not in the design)

This is the background that motivated the model and is not duplicated in the
normative change:

- **Why Omnigent is Tier 2, not a competitor.** See
  `docs/related-work-omnigent.md` — Omnigent *wraps and drives* agents; AgentTower
  *observes and routes* unmodified ones. Tier 2 is the deliberate hand-off seam,
  not a merge of the two products.
- **Native harness surfaces that make Tier 1 possible.** Claude Code exposes
  `-p`/`--print` headless with `--output-format stream-json` /
  `--input-format stream-json`, lifecycle **hooks** (PreToolUse / PostToolUse /
  Notification / Stop), and **MCP**. Codex exposes a headless `exec` mode, a JSON
  output mode, and an MCP server mode. **Codex exact flag spellings must be
  confirmed before they enter any implementing feature's tasks** (tracked in the
  change's tasks).
- **The realism constraint.** Strong tiers generally require control at session
  *startup* (hooks/MCP load at start; a running TUI can't switch into
  stream-json mid-flight). That is why managed launch and pre-instrumented
  adoption are the two unlock points, and why Tier-1 inbound via hooks is the
  recommended first step.
