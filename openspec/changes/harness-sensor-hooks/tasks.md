# Tasks: Harness Sensor Hooks (Tier-1 Inbound)

> This change is the governed decision + handoff for Phase 1 of
> `agent-connection-tiers`. Fine-grained implementation tasks are owned by the
> Spec Kit feature `specs/NNN-harness-sensor-hooks/` (number assigned at
> `/speckit.specify` time; 015 and 016 are already claimed by the open spec-only
> branches `015-discovery-backends` and `016-routing-policy-layers`, so expect
> 017). Items marked **(impl → Spec Kit feature)** are a coarse outline to be
> expanded there, not work that lands with this change's merge.
> Owner bench: **`py-bench`**. Flutter/desktop consumption of the new fields is a
> separate **`flutter-bench`** follow-up feature.

## 1. Spec authoring and acceptance (this change)

- [ ] 1.1 Author the `harness-sensor-hooks` capability delta covering all 18
      requirements; verify `openspec validate harness-sensor-hooks --strict` is
      clean and every `### Requirement:` has at least one `#### Scenario:`.
- [ ] 1.2 Cross-check every requirement against `agent-connection-tiers`
      (Tier-0 floor never removed, two independent axes, router-not-puppeteer,
      no network listener); verify by reading that change's spec delta and
      confirming no requirement here contradicts or restates it.
- [ ] 1.3 Confirm the event mapping introduces no new routable `event_type` and
      that every `hook.*` rule id matches the existing `classifier_rule_id`
      regex; verify by diffing the mapped types against the ten-value closed set
      in the FEAT-008/FEAT-010 specs and running the pattern over each literal id.
- [ ] 1.4 Confirm no artifact in this change contains a host-absolute path;
      verify with a grep over the change directory for the usual host root
      prefixes (POSIX home and workspace roots, Windows drive letters),
      expecting no hits.
- [ ] 1.5 Confirm the change respects the MVP constitution in
      `openspec/config.yaml` (no network listener; AgentTower routes rather than
      executes workflow logic) and that bench ownership is recorded as
      `py-bench` with the Flutter split called out; verify against that file and
      the Bench ownership section of `openspec/changes/README.md`.

## 2. Pre-implementation confirmations (before Spec Kit tasks are generated)

- [ ] 2.1 Spike: confirm whether Claude Code ever rewrites
      `~/.claude/settings.json` and drops third-party `hooks` entries. Verify by
      installing a marked handler, exercising settings-mutating flows, and
      re-reading the file; record the result and, if it drops, switch the Claude
      delivery vehicle to a local plugin `hooks.json`.
- [ ] 2.2 Spike: confirm `$TMUX` and `$TMUX_PANE` are visible to a hook process
      launched by each harness. Verify with a probe hook that records its
      environment; if absent, adopt the ancestor-pid → `pane_pid` fallback.
      (Partial evidence already in hand: on 2026-09-06 a child process of a
      Claude Code session inside the devBench saw both `TMUX` and `TMUX_PANE`;
      Codex remains unconfirmed.)
- [ ] 2.3 Confirm Claude settings files are parsed as strict JSON (not
      JSON5/JSONC). Verify by writing a trailing comma into a scratch copy and
      observing whether the harness accepts it; the install path's refusal
      behaviour depends on the answer.
- [ ] 2.4 Confirm whether either harness snapshots hook declarations at session
      start. Verify by installing hooks mid-session and checking whether they
      fire; record the result as the documented "restart the session" caveat.
- [ ] 2.5 Confirm the exact Codex trust flow and that a re-declared identical
      definition retains trust. Verify by installing, trusting via Codex's
      `/hooks`, reinstalling identically, and checking hooks still fire.
- [ ] 2.6 Capture fixture payloads for every subscribed event of both harnesses
      from the vendor docs, with the doc version recorded. Verify each fixture
      parses into the `events.report` parameter shape.
- [ ] 2.7 Confirm the reserved `integration` values `native` and `omnigent` are
      still owned by later phases of `agent-connection-tiers`. Verify against
      that change's per-agent integration mode requirement.

## 3. Implementation outline **(impl → Spec Kit feature)**

- [ ] 3.1 Schema v9 additive migration adding `inbound_tier`, `hook_harness`,
      `harness_session_id`, `last_hook_event_at`, and `integration` to `agents`.
      Verify with a migration test from a v8 database that preserves rows.
- [ ] 3.2 `events.report` handler registered in the socket dispatch table,
      accepting bench-container callers with the uid gate unchanged, with full
      parameter validation (per-harness closed sets, unknown-key rejection,
      length caps, `schema_version_newer`). Verify with handler tests for the
      accepted path and a table test covering one rejection per rule.
- [ ] 3.3 Implicit registration upsert (create with role `unknown`; promote
      capability only from `unknown`; never touch role or label; never create
      `master`). Verify with tests for create, unchanged-capability, and
      master-refusal cases.
- [ ] 3.4 Event mapping + per-(harness, event, subtype) excerpt templates with
      `hook.` rule ids. Verify with fixture-driven tests asserting the mapped
      `event_type`, rule id, and that no payload content appears in the excerpt.
- [ ] 3.5 Inbound tier lifecycle: set on first accepted report of a session;
      reset on `SessionEnd`, on reconciliation deactivation, and on
      `integration=tmux-only`; no freshness timeout. Verify with lifecycle tests
      including a long-idle session that stays at Tier 1.
- [ ] 3.6 Classifier suppression limited to `waiting_for_input` and `completed`
      for Tier-1 agents, with a suppression counter. Verify with a reader test
      that other event types still store while those two do not.
- [ ] 3.7 `[hooks]` daemon config: `enabled`, `classifier_suppression`, and
      `rate_limit_per_agent`. Verify with config-parsing tests plus a
      kill-switch test showing `accepted: false, reason: hooks_disabled`.
- [ ] 3.8 Per-agent rate limiter returning `reason: rate_limited`. Verify with a
      test that drives the configured threshold and asserts no error envelope.
- [ ] 3.9 `agenttower hook claude|codex`: stdin parse, pane resolution, bounded
      timeouts, always exit 0, never write stdout, stderr only under the debug
      env var. Verify with CLI tests for the daemon-down, pane-unresolvable, and
      malformed-stdin paths all exiting 0 with empty stdout.
- [ ] 3.10 Pane resolution behind an interface that can take either the
      `$TMUX_PANE` strategy or the ancestor-pid fallback from task 2.2. Verify
      with tests for both strategies against a stubbed pane list.
- [ ] 3.11 Claude hook config writer: strict-JSON read, marker-scoped edit,
      timestamped backup, atomic temp+rename, verifying re-read, idempotent.
      Verify with tests for second-install-no-change, unrelated-key
      preservation, and malformed-file refusal.
- [ ] 3.12 Codex hook config writer for `~/.codex/hooks.json` (create or merge),
      never touching `config.toml`. Verify with create-and-merge tests plus a
      test asserting the TOML file is untouched.
- [ ] 3.13 `agenttower hooks uninstall`: remove exactly marked handlers and
      emptied matcher groups. Verify with a test that a third-party handler under
      the same event survives.
- [ ] 3.14 `agenttower hooks status [--json]`: local facts always, daemon
      counters when reachable, Codex `trust_state: unknown`, PATH preflight
      warning. Verify with tests for the daemon-up and daemon-down shapes.
- [ ] 3.15 `agenttower set-integration <agent_id> auto|tmux-only`, with
      later-phase values rejected as `value_out_of_set`; `list-agents` shows
      `inbound_tier` and `integration`. Verify with CLI tests for both.
- [ ] 3.16 App contract minor v1.2: `hooks_ingest` appended to the ordered
      subsystem list with ok/degraded/unavailable probes, `inbound_tier` +
      `integration` on agent reads, `counts.hooks` on `app.dashboard`, all
      always-emit. Verify with contract tests asserting the version bump and the
      unflagged presence of each field.
- [ ] 3.17 JSONL audit for accepted hook events and for implicit registration
      side effects. Verify with tests asserting the appended record shapes.
- [ ] 3.18 End-to-end proof on a real instrumented pane per harness: an exact
      `waiting_for_input` and `completed` arrive from hooks while the classifier
      duplicates are suppressed. Verify by capturing the event stream for one
      full session of each harness.

## 4. Handoff to the Spec Kit feature

- [ ] 4.1 Run `/speckit.specify` from the root checkout on `main` for
      `harness-sensor-hooks` and record the assigned feature number and worktree
      path. Verify with `git rev-parse --abbrev-ref HEAD` in the new worktree.
- [ ] 4.2 Carry decisions D1–D10 from `design.md` into the feature's `plan.md`
      as settled constraints, not open questions. Verify by cross-reading the two
      documents for contradictions.
- [ ] 4.3 Author the canonical contract docs — `events.report`, the schema-v9
      columns, and app contract v1.2 — in the feature's own
      `specs/NNN-harness-sensor-hooks/contracts/`. Verify the files exist and are
      referenced from the feature plan.
- [ ] 4.4 Add **additive pointer subsections only** to the prior features'
      contract docs (FEAT-006, FEAT-008, FEAT-011/014) pointing at 4.3. Verify
      with a diff showing only new headings and no modified prior text, per the
      repo "Cross-Feature Spec Dir Editing" rule.
- [ ] 4.5 Confirm the feature is recorded against the `py-bench` owner bench and
      that the Flutter/desktop surfacing of `inbound_tier`, `integration`, and
      `counts.hooks` is filed as a separate `flutter-bench` follow-up. Verify by
      the recorded owner in the feature spec and the follow-up issue link.
- [ ] 4.6 Run `/speckit.checklist` for at least the config-file-safety and
      privacy/PII topics before `/speckit.tasks`. Verify the checklist files
      exist under the feature directory.
- [ ] 4.7 Run `/speckit.taskstoissues` for any task deferred beyond the
      implementing feature and record the issue links in the handoff. Verify the
      issue IDs appear in the feature's handoff notes.

## 5. Validation

- [ ] 5.1 Run `openspec validate harness-sensor-hooks --strict` and confirm it
      reports the change as valid.
- [ ] 5.2 Run `openspec status --change harness-sensor-hooks` and confirm all
      four artifacts are present.
- [ ] 5.3 Confirm this change touches no file outside
      `openspec/changes/harness-sensor-hooks/`. Verify with `git status
      --porcelain` showing only paths under that directory.
