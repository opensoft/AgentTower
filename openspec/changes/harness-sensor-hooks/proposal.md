# Harness Sensor Hooks — Tier-1 Inbound for Claude Code and Codex

## Why

AgentTower learns what an agent is doing today by scraping pane scrollback and
running regex classifiers over it (`architecture.md` §13). That is the universal
Tier-0 floor, and it is also the weakest signal AgentTower has: `waiting_for_input`
and `completed` are *inferred* from text that the harness never promised to keep
stable, so the classifier is deliberately conservative and still both misses and
misfires. Both harnesses AgentTower already targets now ship a first-class
lifecycle **hook** surface — Claude Code (`~/.claude/settings.json`) and Codex CLI
(`~/.codex/hooks.json`) — that emits exactly the two signals the classifier
struggles with, as structured JSON, at the moment they happen. This change is
**Phase 1 of `agent-connection-tiers`** ("Tier-1 inbound via hooks"): the
lowest-risk, highest-value rung of the ladder, read-only, and independently
shippable ahead of the MCP server and any outbound work.

## What Changes

- **Harness hooks become sensors.** AgentTower ships hook declarations for Claude
  Code and Codex CLI that fire a single stable command per harness —
  `agenttower hook claude` / `agenttower hook codex` — on session, prompt, stop,
  failure, and permission/notification events. The lifecycle event is read from
  the stdin payload, so the declared command string never varies.
- **Hooks are strictly observational.** They always exit 0, never write stdout,
  never block, approve, deny, or steer the harness, and fail open: an unreachable
  daemon or unresolvable pane silently leaves the agent on the Tier-0 floor.
- **New socket method `events.report`** — the first client-pushed event path.
  Bench-container callers may invoke it (like every non-`app.*` method); the
  SO_PEERCRED uid gate is unchanged. It maps a harness lifecycle event onto the
  existing closed routable `event_type` set, performs an implicit registration
  upsert for the reporting pane, and returns an `accepted`/`reason` verdict.
- **Per-agent inbound tier bookkeeping** (schema v9, additive columns):
  `inbound_tier`, `hook_harness`, `harness_session_id`, `last_hook_event_at`, and
  an `integration` mode restricted in this phase to `auto | tmux-only`.
- **Scoped classifier suppression.** While an agent is at inbound Tier 1, the
  FEAT-008 log reader suppresses only its classifier-generated `waiting_for_input`
  and `completed` — precisely the two the hooks report exactly. Every other event
  type keeps flowing from the log path, so Tier 1 is an upgrade, never a loss.
- **Install / uninstall / status CLI** — `agenttower hooks install|uninstall|status`
  performs a marked, backed-up, atomic, idempotent edit of the harness config,
  touching only handlers whose command begins with `agenttower hook `.
- **App contract additive minor v1.2** — a `hooks_ingest` readiness subsystem,
  `inbound_tier` + `integration` on agent reads, and `counts.hooks` on
  `app.dashboard`. Additive, always-emit, no capability flag (FEAT-014 FR-028).
- **No new routable event type and no network listener.** The 10-value routable
  set stays frozen for FEAT-010; hooks reach the daemon over the existing mounted
  Unix socket only.

## Capabilities

### New Capabilities

- `harness-sensor-hooks`: how AgentTower installs, receives, maps, and governs
  observational lifecycle hooks from Claude Code and Codex CLI as a Tier-1
  inbound event source, including the `events.report` contract, inbound-tier
  lifecycle, classifier suppression scope, and hook config file management.

### Modified Capabilities

<!-- None. `openspec/specs/` contains no published capabilities yet, so this
     change introduces requirements only. -->

## Impact

- **Owner bench:** `py-bench` (daemon, thin client, local `app.*` contract).
  Flutter/desktop consumption of the new `inbound_tier` / `integration` /
  `counts.hooks` fields is a **separate `flutter-bench` follow-up feature**.
- **Code:** `socket_api/methods.py` (new `events.report` handler in `DISPATCH`),
  `state/schema.py` (schema v9 additive migration), `events/writer.py` and
  `events/reader.py` (hook-origin events + suppression), `agents/` registration
  and pane resolution, `cli.py` (`hook`, `hooks`, `set-integration`),
  `config.py` (`[hooks]` block), `app_contract/readiness.py` (`hooks_ingest`).
- **Prior features:** FEAT-006 (registration/capability), FEAT-008 (event
  pipeline), FEAT-011/014 (app contract) receive **additive pointer subsections
  only**; the canonical contract lives in the implementing Spec Kit feature's own
  `contracts/` directory, per the repo cross-feature spec-dir rule.
- **Governance:** this change records the decision and the handoff. Fine-grained
  implementation tasks are owned by the Spec Kit feature
  `specs/NNN-harness-sensor-hooks/` (number assigned at `/speckit.specify` time;
  015 and 016 are claimed, so expect 017). No code ships in this change.
