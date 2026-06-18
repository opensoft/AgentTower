# Tasks: Agent Connection-Strength Tier Model

> This change is a spec/design proposal. Implementation is sequenced into later
> features; the tasks below capture the spec-acceptance and the ordered
> implementation hand-off. Items marked **(impl)** belong to a future
> implementing feature, not to this change's merge.

## 1. Spec authoring (this change)

- [ ] 1.1 Define the `agent-integration` capability spec with the tier ladder,
      two-axis negotiation, router-first boundary, adoption story,
      no-listener invariant, integration modes, and tier-independent safety.
- [ ] 1.2 Cross-check the spec against existing constraints: `architecture.md`
      §13 (classification), §16 (delivery), §23 (security/no-listener), §4.1
      (UID invariant), FEAT-009 (permission gate + kill switch).
- [ ] 1.3 Confirm no requirement contradicts the MVP constitution in
      `openspec/config.yaml` (no network listener; AT routes, does not execute
      workflow logic).

## 2. Pre-implementation confirmations

- [ ] 2.1 Confirm Codex exact flag spellings (headless `exec`, JSON output
      mode, MCP server mode) against current Codex docs. Record findings before
      any Codex task is written.
- [ ] 2.2 Confirm Claude Code hook event names and payloads
      (PreToolUse / PostToolUse / Notification / Stop) and the MCP stdio
      server registration shape against current Claude Code docs.
- [ ] 2.3 Decide whether negotiated tier is surfaced via the FEAT-011 `app.*`
      backend in phase 1 or deferred.

## 3. Phase 1 — Tier-1 inbound via hooks **(impl, future feature)**

- [ ] 3.1 Ship AgentTower hook scripts (host-path-safe; relative/runtime paths).
- [ ] 3.2 Add an `agenttower report-event` CLI subcommand + daemon socket method
      that maps harness hook events to AgentTower event types.
- [ ] 3.3 Per-agent `inbound_tier` negotiation with fall-back to tmux scraping.
- [ ] 3.4 Prove exact `waiting_for_input` / `completed` events replace inferred
      classification for an instrumented agent (retires §13 problem for it).

## 4. Phase 2 — AgentTower-hosted MCP server **(impl, future feature)**

- [ ] 4.1 stdio MCP server bridging to the existing Unix socket (no listener).
- [ ] 4.2 `report_status` / `request_route` tools (agent reports IN; AT never
      drives the agent).
- [ ] 4.3 Pre-instrumented adoption path: an adopted pane with the AT MCP server
      configured lights up Tier 1; uninstrumented panes stay on the floor.

## 5. Phase 3 — Tier-1 outbound structured delivery **(impl, future feature)**

- [ ] 5.1 Per-agent `outbound_tier` negotiation, independent of `inbound_tier`.
- [ ] 5.2 Structured delivery adapter for the native harness inbox.
- [ ] 5.3 Route delivery through the FEAT-009 permission gate + kill switch +
      `events.jsonl` audit for every tier (no bypass).

## 6. Phase 4 — Tier-2 Omnigent hand-off **(impl, future feature)**

- [ ] 6.1 Per-agent `integration=omnigent` mode + Omnigent session correlation.
- [ ] 6.2 Consume Omnigent structured events as the inbound source; AT routes
      around the Omnigent-driven agent.
- [ ] 6.3 Document the two-policy-layer precedence (AT routing vs Omnigent
      action policy).

## 7. Validation

- [ ] 7.1 Run `openspec validate agent-connection-tiers --strict` when the CLI
      is available.
- [ ] 7.2 Confirm each ADDED requirement has at least one `#### Scenario:`.
