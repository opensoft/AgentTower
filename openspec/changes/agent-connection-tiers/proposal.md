# Add Agent Connection-Strength Tier Model

## Why

AgentTower connects to every agent through a single mechanism today: tmux
`pipe-pane` for observation and paste-buffer for delivery. That floor is
universal and fully non-invasive, but it is also the weakest possible channel —
events are *inferred* from scraped scrollback (the `architecture.md` §13
conservative-classifier problem) and delivery *guesses* whether a pane is ready
(`architecture.md` §16). Meanwhile the harnesses AgentTower already targets
expose far stronger, structured surfaces: Claude Code has hooks, an MCP
interface, and headless `stream-json`; Codex has a headless/JSON/MCP surface;
and Databricks' open-source Omnigent meta-harness can drive an agent's full
action loop under policy and sandboxing.

AgentTower should be able to *use* the strongest channel an agent supports
without abandoning the tmux floor for agents that support nothing. This change
defines that ladder and the role boundaries around it, so later features
implement against a settled model instead of ad-hoc per-harness hacks.

## What Changes

- **Introduce a per-agent connection-strength ladder.** Tier 0 = tmux floor
  (today). Tier 1 = native harness integration (Claude hooks + an
  AgentTower-hosted MCP server + headless `stream-json`; Codex exec/json/MCP).
  Tier 2 = Omnigent meta-harness hand-off.
- **Negotiate inbound (events) and outbound (delivery) independently** per
  agent, so a pane can have exact event reporting while delivery stays on the
  paste-buffer floor.
- **Settle the role boundary:** AgentTower stays the **router** — agents report
  *in* via hooks and an AgentTower-hosted MCP **server**; AgentTower does not
  drive an agent's task loop or intercept its tool calls. **Omnigent is the
  puppet master** that AgentTower hands off to for action-level
  driving/sandboxing/policy.
- **Make adoption of pre-running panes first-class.** AgentTower ships its own
  hook scripts + MCP server, so a pane started pre-instrumented lights up Tier 1
  on adoption; an uninstrumented pane stays at the tmux floor. Adoption never
  downgrades an agent below the floor.
- **Add a per-agent `integration` mode:** `auto` (default; probe, then fall back
  to tmux), `tmux-only`, `native`, `omnigent`.
- **Preserve the no-network-listener invariant.** Hook scripts call the
  `agenttower` CLI over the existing Unix socket; the MCP server is a stdio
  subprocess bridging to that same socket; AgentTower remains a *client* of any
  external server (including Omnigent's localhost server). No new listener.
- **Keep the safety layer tier-independent.** The FEAT-009 permission gate and
  global routing kill switch sit in front of *every* outbound tier; every
  delivery is still audited in `events.jsonl`.

## Impact

- **New capability spec:** `agent-integration` (this change's spec delta).
- **Touches (in later implementing features, not in this change):**
  capability/role metadata (FEAT-006), event pipeline (`architecture.md` §13),
  input delivery (`architecture.md` §16 / FEAT-009 gate), managed session
  creation (FEAT-013), and the app backend (FEAT-011) for surfacing tier state.
- **Phasing (recommended, each a later implementing feature):**
  1. Tier-1 inbound via hooks — read-only, lowest risk, retires the §13
     classifier problem on its own.
  2. AgentTower-hosted MCP server (stdio → socket) — enables pre-instrumented
     adoption and structured self-report.
  3. Tier-1 outbound structured delivery — behind the FEAT-009 gate.
  4. Tier-2 Omnigent hand-off.
- **No code ships in this change** — it is a spec/design proposal only.
- **Open item:** Codex exact flag spellings (`exec`, JSON mode, MCP mode) MUST
  be confirmed against current Codex docs before they enter an implementing
  feature's tasks.
- **Related work:** see `design.md` for the Omnigent (Databricks open-source
  meta-harness) comparison that frames Tier 2.

## Tooling note

The `openspec` CLI is not available in this environment (no binary on PATH;
`npx openspec` could not fetch the package under the network policy). This
change was authored to the OpenSpec file conventions by hand. Run
`openspec validate agent-connection-tiers --strict` when the CLI is available.
