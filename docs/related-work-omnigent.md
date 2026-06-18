# Related Work: Databricks Omnigent

Status: Research note (reference only) — v0.1
Date: 2026-06-18

> **Research only.** This is a related-work/reference note. It records no
> committed scope and modifies no canonical spec. Proposed AgentTower scope
> derived from this analysis lives under `openspec/changes/` (the OpenSpec
> change flow), not in this file. The connection-tier model in particular is
> formalized in `openspec/changes/agent-connection-tiers/`.

This note compares AgentTower with **Omnigent**, the open-source "meta-harness"
that Databricks released (Apache-2.0, mid-June 2026). The two tools share a
goal — coordinating multiple AI coding agents — but sit at opposite ends of the
coupling spectrum. This doc records the comparison and the Omnigent-derived
ideas that are candidates for AgentTower scope.

Primary sources:

- Databricks blog — "Introducing Omnigent: A Meta-Harness to Combine, Control
  and Share Your Agents"
- GitHub — `omnigent-ai/omnigent`

## 1. One-line framing

> **Omnigent is a meta-_harness_ — it runs your agents. AgentTower is a
> meta-_observer/router_ — it coordinates agents that are already running.**

Same neighbourhood, opposite ends of the coupling spectrum. AgentTower could
even observe panes that happen to be Omnigent-launched sessions.

## 2. What each tool is

**AgentTower** is a local control tower that **observes and routes between
agents that already exist** in tmux. It does not launch or wrap agents. It
discovers tmux panes inside bench containers, lets a human label them
`master` / `slave` / `swarm`, tails their output via `tmux pipe-pane`,
classifies events (`waiting_for_input`, `test_failed`, …), and safely routes
structured text notifications between panes via paste-buffers. Host daemon
(`agenttowerd`) plus thin container clients over a Unix socket; SQLite + JSONL;
no network listener; CLI-first.

**Omnigent** is a **meta-harness that wraps and launches agents** behind a
uniform API. A `runner` executes Claude Code / Codex / Cursor / Pi / OpenAI
agents inside OS sandboxes (macOS `seatbelt`, Linux `bubblewrap`, or cloud
sandboxes via Modal / Daytona / Islo), and an optional `server` adds policy
enforcement, a web UI (`localhost:6767`), and **live session sharing by URL** so
teammates can watch, co-drive, or fork a session from any device. Python 3.12+
with a TypeScript harness CLI; `uv` packaging.

## 3. Where they overlap

| Dimension | AgentTower | Omnigent |
| --- | --- | --- |
| Core goal | Coordinate many parallel agents | Coordinate many parallel agents |
| Multi-harness aware | Capabilities: claude, codex, gemini, opencode | Wraps claude code, codex, cursor, pi, openai |
| Governance | Permission gates, routing kill-switch, no-input-to-unknown | Stacked policies: ask-before-shell, spend caps, tool-call limits |
| Audit trail | JSONL event history | Policy checks every action (allow / block / ask) |
| Sandbox-conscious | Bench / devcontainer-first | Omnibox OS sandbox + cloud sandboxes |
| Local-first option | Yes (only option) | Yes (plus cloud / server modes) |

## 4. Where they fundamentally differ

| | AgentTower | Omnigent |
| --- | --- | --- |
| Relationship to the agent | Observer / router — agents run independently in tmux; AT attaches from outside | Harness / wrapper — AT _is_ the thing that launches and mediates the agent |
| Coupling | Loosely coupled; zero changes to Claude / Codex / tmux | Tightly coupled; agent runs _inside_ its runner with a uniform tool API |
| Who drives orchestration | A human-designated `master` agent pane drives; AT is just transport | The server / policy layer + uniform API drives composition |
| Control mechanism | tmux pane I/O (paste-buffer + Enter) | Programmatic API + OS sandbox interception (incl. network transforms) |
| Agent-state knowledge | Inferred from terminal output (conservative, rule-based) | Native (it owns the session) |
| Collaboration | None (single operator, CLI) | First-class: share session URL, co-attach, fork, OIDC multi-user |
| Deployment | Host daemon + container clients, no network listener | CLI + optional server, Docker / Render / Fly / Modal, reachable "from your phone" |
| Substrate scope | tmux + Docker bench containers specifically | Any wrapped harness, local or cloud sandbox |

## 5. Why they don't really compete

- **Omnigent owns the agent.** It is an SDK / framework — you build _on_ it, and
  the agent exists only because Omnigent launched it inside its sandbox with its
  tool API. That is why it can do clean policy interception and URL sharing: it
  sits _in_ the request path.
- **AgentTower watches agents it does not own.** It is deliberately
  non-invasive (PRD non-goal #1: don't replace Claude / Codex / tmux; success
  metric: "without requiring changes to Claude, Codex, tmux, or Docker"). That
  is why it must _infer_ state from terminal scrollback and route via
  safe-but-fragile paste-buffers. It sits _beside_ the path.

So AgentTower is closer to a **tmux-native NOC / observability layer + message
bus**, while Omnigent is a **multi-harness agent runtime / SDK**. Omnigent's
`runner` is precisely the part AgentTower deliberately refuses to be.

**Guardrail for AgentTower:** do not converge toward Omnigent's tight coupling.
The value proposition is coordinating _unmodified_ agents in _existing_
tmux/bench setups. Adopting a wrapping runner would turn AgentTower into a
competitor of both Omnigent and Claude Code, rather than a complement.

## 6. Omnigent-derived features (candidate scope)

The following ideas fit AgentTower's non-invasive thesis. They are **candidates
only** — not committed scope and not yet written into any canonical spec. They
are the raw input for a comprehensive OpenSpec proposal; any adopted item will
be captured under `openspec/changes/`. They are listed here with the
AgentTower-appropriate framing.

1. **Layered / stacked policies.** Omnigent stacks policies at server, per-agent,
   and per-session levels (ask-before-shell, token-spend caps, tool-call
   limits). AgentTower today has a per-pane `send_input_allowed` boolean plus a
   global routing kill switch. A layered policy model (global → per-agent →
   per-route) generalises this and lands the existing "explicit per-agent
   permission grants" item in architecture §24. AgentTower's version governs
   _routing/input delivery_, not agent tool calls (which it cannot see).

2. **Session sharing / co-attach / fork.** Omnigent's headline collaboration
   feature: share a live session by URL, let a teammate co-drive, or fork the
   conversation. For AgentTower this maps onto multi-operator support over the
   FEAT-011 `app.*` backend — multiple humans observing the same registry/event
   stream, with read-only "watch" vs. permitted "co-drive". This is the natural
   answer to PRD Open Question #2 (TUI vs. web vs. CLI) and is V2 because MVP has
   no network listener.

3. **Pluggable execution-sandbox backends.** Omnigent treats local OS sandboxes
   and cloud sandboxes (Modal / Daytona) as interchangeable execution targets.
   AgentTower's analogue is treating the bench container as one _substrate
   backend_ among several (host-only tmux, future remote/cloud bench) behind the
   discovery interface — additive to the existing "host-only tmux discovery"
   backlog item.

4. **Reachable-from-anywhere / mobile surface.** Omnigent makes sessions
   reachable from a phone. AgentTower's MVP is explicitly no-network-listener;
   this is a deliberate V2 item, gated behind an authenticated transport, and
   should reuse the FEAT-011 contract rather than scrape CLI output.

5. **Network-egress policy at the boundary.** Omnigent's Omnibox can transform /
   restrict agent network requests. AgentTower cannot intercept an unmodified
   agent's syscalls, but it _can_ record this as a known capability gap and, if
   ever needed, document an opt-in container-network-policy recommendation
   rather than implement interception itself.

Items 1–3 are the highest-leverage and lowest-risk for AgentTower's model.
Items 4–5 are noted for completeness but carry the most tension with the
local-first, non-invasive constitution and should not be pursued without an
explicit decision.
