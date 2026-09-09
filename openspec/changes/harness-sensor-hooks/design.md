# Design: Harness Sensor Hooks (Tier-1 Inbound)

## Context

See `proposal.md` — Why. This change implements Phase 1 of
`agent-connection-tiers` ("Tier-1 inbound via hooks") and inherits that change's
settled model: Tier 0 is the permanent tmux floor, inbound and outbound
negotiate independently, AgentTower is the **router** (agents report *in*), and
no tier opens a network listener.

The constraints that shape the design are all existing AgentTower behaviour:
newline-delimited JSON over `AF_UNIX` with a 64 KiB line cap and one request per
connection; a peer-credential uid gate; `app.*` methods host-only while other
dotted methods accept bench-container callers; one agent per six-tuple pane
composite key; a closed ten-value routable `event_type` set frozen for FEAT-010
routing; a `classifier_rule_id` pattern; events produced *only* daemon-side by
the log reader plus regex classifier, with **no client-push event path today**;
and an `app_contract_version` of `1.1` whose additive-minor rules FEAT-014
already fixed.

Two harness surfaces are the input. Claude Code hooks are declared under `hooks`
in `~/.claude/settings.json` (and other layers, all of which merge), with
per-handler `command`, `timeout`, and `async`. Codex CLI hooks live in
`~/.codex/hooks.json` (or inline `[hooks]` in `config.toml`), share the same
three-level shape and event names, have a stricter 1 s default `SessionEnd`
timeout, have **no** `Notification` event, and — critically — require the user to
review and **trust** a hook definition from inside Codex before it runs, with
trust recorded against the definition's hash.

## Goals / Non-Goals

**Goals**

- A single, stable, `PATH`-relative hook command per harness that never changes
  as the subscribed event set evolves.
- A first client-pushed event path (`events.report`) that is safe for
  container-local callers and adds no new routable event type.
- Exact `waiting_for_input` / `completed` for instrumented agents, replacing the
  inferred classifications for those agents only.
- Config-file edits that a cautious operator would be willing to run against
  their own `~/.claude/settings.json`.

**Non-Goals (design-level)**

- Any outbound/structured delivery, the AgentTower-hosted MCP server, and the
  Omnigent hand-off — later phases of `agent-connection-tiers`.
- Managing hooks the *user* owns, project-scope installation
  (`.claude/settings.json`, repo `.codex/`), Gemini/OpenCode adapters, and
  desktop AI apps.
- Codex's older `notify` mechanism: hooks supersede it for this purpose and
  `notify` carries no `SessionStart` or permission signal at all.
- Any **new routable event type** — the ten-value set must stay stable so
  FEAT-010 routing rules keep matching.
- Flutter/desktop UI consumption of the new fields — a separate `flutter-bench`
  follow-up.

## Decisions

### D1 — One command per harness; the event comes from stdin

`agenttower hook claude` and `agenttower hook codex`, byte-identical across every
declared event. Alternative considered: one subcommand per event
(`agenttower hook claude stop`). Rejected because Codex records trust against the
hook definition's hash — a per-event command multiplies the definitions an
operator must trust and re-trust — and because a single token also keeps the
declaration `PATH`-relative, satisfying the repo's no-host-absolute-path rule
with nothing else to parameterise.

### D2 — Passive by construction

The hook reads stdin, resolves container and pane from `$TMUX` / `$TMUX_PANE`
through the existing client-side resolver, calls `events.report`, and **always
exits 0 with an empty stdout**. Budget: ≤ 1 s wall clock (0.5 s connect / 0.5 s
read) so it fits inside Codex's 1 s `SessionEnd` default; declared `async` where
the harness supports it, with a 5 s Claude timeout and 3 s for Codex
`SessionEnd`. Silence on stdout is not stylistic: Codex's `Stop` interprets any
stdout as a JSON decision, so writing nothing is the only way to guarantee the
hook cannot alter the turn. Failure is fail-open by definition — the Tier-0 floor
still observes the pane, so a lost report costs precision, never coverage.

### D3 — Mapping, and why no new event type

Notification(`permission_prompt` | `idle_prompt` | `agent_needs_input`) and Codex
`PermissionRequest` → `waiting_for_input`; `Stop` and
Notification(`agent_completed`) → `completed`; `UserPromptSubmit` → `activity`;
`StopFailure` → `error`. `SessionStart` is a registration upsert and
`SessionEnd` a teardown; neither is routable. Rule ids use a `hook.` prefix
(`hook.claude_notification.v1`, `hook.codex_permission_request.v1`, …), which
already satisfies the existing rule-id pattern, so downstream consumers can tell
hook-origin from classifier-origin without a schema change.

Excerpts are **fixed daemon-side templates** keyed by (harness, event, subtype).
No prompt text, assistant text, tool input, transcript path, or cwd is ever
persisted. This mirrors FEAT-014's template discipline and is the whole privacy
story: content the operator never asked AgentTower to store cannot leak onto the
wire or into `events.jsonl`, so an agent's hook payload is not a new PII surface.

### D4 — `events.report`, the first inbound method

A dotted method beside `events.list` / `events.follow_open`, dispatched from the
same `DISPATCH` table, accepting bench-container callers exactly like
`register_agent` does; the uid gate is untouched. Errors are reserved for
malformed input (`bad_request`, `value_out_of_set`, `field_too_long`,
`schema_version_newer`), with unknown keys rejected per the FEAT-006
forbidden-key posture. Everything else — disabled, rate-limited, tmux-only,
pane-not-found — is a **successful response with `accepted: false` and a
reason**. That split matters because the caller is a hook that must exit 0
regardless: modelling policy refusals as errors would push policy into an
exit-code channel nobody reads.

Implicit registration keeps adoption zero-touch: an unregistered pane that starts
reporting becomes an agent with role `unknown`, capability = harness, empty
label. Capability is only ever promoted *from* `unknown`, never overwritten; role
and label are never touched; `master` is never created or promoted. Alternative
considered: a `capability_source` column so hooks could reclaim a capability an
operator had set. Rejected as unnecessary state — `set-capability` already gives
the operator the last word.

### D5 — Tier bookkeeping (schema v9)

Additive columns on `agents`: `inbound_tier`, `hook_harness`,
`harness_session_id`, `last_hook_event_at`, `integration`. `integration` takes
the parent change's vocabulary but accepts only the Phase-1 subset
`auto | tmux-only`; `native` and `omnigent` are rejected with `value_out_of_set`
until their phases land, so the field can be introduced once rather than
migrated later. Tier 1 is set on the first accepted report of a session and reset
on `SessionEnd`, on pane-reconciliation deactivation, or on `set-integration
tmux-only`. Deliberately **no freshness timeout**: an idle Tier-1 session is
still a correct Tier-1 session, and a timeout would silently resurrect the
duplicate classifier events that suppression exists to remove.

### D6 — Suppression is deliberately narrow

At Tier 1 the log reader suppresses only classifier `waiting_for_input` and
`completed` for that agent — exactly the two the hooks report precisely. Every
other type keeps flowing from the log path, because hooks say nothing about test
results, long-running work, or pane exit. Suppressed classifications are counted,
not stored, so an operator can see how much duplication Tier 1 removed. A
`classifier_suppression` config flag turns it off independently of ingest, which
is the debugging escape hatch when a mapping is suspected to be wrong.

### D7 — Config editing an operator can trust

The `agenttower hook ` command prefix **is** the ownership marker; no sentinel
comments, no separate index file. Install is read-modify-write with a timestamped
backup, an atomic temp-plus-rename, and a verifying re-read; it refuses outright
if `~/.claude/settings.json` is not strict JSON or not an object rather than
guessing at JSON5/JSONC; it is idempotent; it touches no other key. Uninstall
removes exactly the marked handlers plus any matcher group left empty. For Codex
we write `~/.codex/hooks.json` and never touch `config.toml`, because Codex loads
both and warns when a layer defines hooks twice.

This runs where the harness config lives — normally inside the bench container —
and needs no daemon, since it is a local file edit. `hooks status` reports the
local facts unconditionally and daemon counters when reachable, with Codex trust
state reported as `unknown` because it cannot be read from outside Codex.

### D8 — App contract v1.2, additive

A `hooks_ingest` readiness subsystem appended to the ordered subsystem list,
`inbound_tier` + `integration` on agent reads, `counts.hooks` on
`app.dashboard`. All host-only `app.*`, all always-emit with no capability flag
per FEAT-014 FR-028's rule for plain additive read-side fields.

### D9 — Cross-feature documentation boundary

The canonical contract text for `events.report`, the schema-v9 columns, and the
v1.2 minor lives in the implementing Spec Kit feature's own
`specs/NNN-harness-sensor-hooks/contracts/`. FEAT-006, FEAT-008, and FEAT-011/014
receive **additive pointer subsections only** — a new heading pointing at the new
contracts directory, rewriting nothing — per the repo's "Cross-Feature Spec Dir
Editing" rule. A change that needed to *modify* a prior feature's spec dir would
have to be split into a second, separately-owned PR.

## Risks / Trade-offs

- **Claude Code may rewrite `settings.json` and drop our fragment** → resolve
  with a pre-implementation spike; if confirmed, ship the Claude hooks as a local
  plugin `hooks.json` instead. That alternative is rejected as the v1 default
  only because it drags in the plugin enable flow.
- **`$TMUX_PANE` may not be inherited by the harness process** → the docs do not
  enumerate env passthrough, so a probe hook in both harnesses is a
  pre-implementation confirmation. Fallback: match the hook process's ancestor
  pid against `pane_pid` from pane discovery. The resolver interface is designed
  to allow that second strategy without a contract change.
- **Codex trust friction** — hooks silently do nothing until trusted, and a
  changed definition needs re-trust → mitigated by D1's stable command string,
  explicit install output, and a status hint.
- **Hook storms** on a chatty agent → per-agent rate limit (20 reports / 10 s)
  returning `accepted: false, reason: rate_limited`, plus `async` hooks so the
  harness never waits.
- **Harness schema drift** → per-harness adapter modules with fixture payloads
  copied from the vendor docs and a recorded doc version, so drift shows up as a
  fixture test failure rather than silent mis-mapping.
- **Sequential sessions in one pane** (exit Claude, start Codex) → the
  `harness_session_id` change drives a registration `updated`; capability swaps
  only when the stored value is `unknown`, per D4.
- **Lost reports while the daemon is down** → accepted degradation to Tier 0. No
  client-side spool in v1: a spool would need durability, ordering, and its own
  failure modes for events whose value is almost entirely in being timely.

## Migration Plan

Schema v9 is additive columns with defaults, so an older-daemon rollback leaves
the columns unread and harmless. `[hooks] enabled = false` turns `events.report`
into `accepted: false, reason: hooks_disabled` while installed hooks keep exiting
0, which is the fastest kill switch and needs no config-file edit.
`agenttower hooks uninstall` removes the declarations, and the timestamped
backups let an operator restore a config file by hand. Rollback of the app
contract minor follows the FEAT-011 additive-minor rules.

## Open Questions

- Whether hook-origin events should eventually carry an explicit origin field on
  the event row rather than relying on the `hook.` rule-id prefix. Deferrable:
  the prefix is sufficient for every consumer in this phase, and adding a field
  later is an additive minor.
