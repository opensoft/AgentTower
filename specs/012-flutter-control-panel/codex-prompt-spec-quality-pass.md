# Codex Prompt — Spec Quality Pass for FEAT-012 (via OpenSpec)

**Created**: 2026-05-23
**Target spec**: `specs/012-flutter-control-panel/spec.md`
**Workflow**: OpenSpec change proposal (propose → apply, do NOT archive)
**Authoring context**: This prompt was generated from a /speckit-checklist walkthrough of `requirements.md`, `handoff-flow.md`, `data-model.md`, and `state-persistence.md`. The 12 findings below are the Tier-1 set — items that materially affect FRs, the data model, or the testability of clarified behaviors.

> **F4 and F7 resolved:** Both findings were resolved by a follow-up `/speckit-clarify` round on 2026-05-23 (round 2). The prompt below now carries the resolved decisions, NOT guessed defaults, and no longer asks Codex to flag them in `design.md`. The clarification record is in the spec at `## Clarifications → ### Session 2026-05-23 (round 2)`.

---

# Prompt to give Codex

Copy everything inside the fenced block below into the Codex session running in the repo root.

````
# Mission

You are updating an existing Spec Kit feature spec to close 12 known
requirement-quality gaps. You will do this via the OpenSpec change workflow
(propose → apply → archive), NOT by editing the spec directly.

## Repository context

- Repo root: /workspace/projects/AgentTower-worktrees/012-flutter-control-panel
- Current branch: 012-flutter-control-panel (a feature worktree)
- Target spec: specs/012-flutter-control-panel/spec.md
- OpenSpec root: openspec/
- Both Spec Kit and OpenSpec coexist in this repo. The spec being updated is
  Spec Kit's; you are using OpenSpec workflow tooling to manage the change.

## What you are doing

Create ONE OpenSpec change proposal that captures all 12 spec updates as a
single coherent change. Then apply the change (edit spec.md). Do NOT archive
the change in this run — leave it in the `proposed → applied` state so a human
reviewer can inspect before archive.

Run `openspec-propose` (or `/opsx:propose` if available) first. Use this short
description when prompted:

  "Close 12 Tier 1 requirement-quality findings on FEAT-012 spec.md:
  acceptance scenarios for clarified behaviors, entity identity rules,
  lifecycle transition matrices, helper-policy contract, vocabulary
  normalization, doc-rendering cross-references, onboarding completion
  criteria, and doctor-check enumeration."

If `openspec-propose` asks for change name, use:
  `spec-quality-pass-feat-012`

After the proposal artifacts are generated, run `openspec-apply-change` (or
`/opsx:apply`) and walk through every task. The 12 findings below are the
authoritative work list — adapt the generated tasks to match them exactly.

# The 12 findings to address

For each finding, the spec section to modify, the problem, and the required
edit are given. Do not invent new behavior beyond what is specified. Where a
choice is required, make the marked decision and add a one-line note in the
OpenSpec change's design.md flagging the call for human review.

## F1. Add acceptance scenarios for 5 clarified behaviors

The spec was clarified (see `## Clarifications` → `### Session 2026-05-23` in
spec.md) but the User Stories did not gain matching Given/When/Then scenarios.
Add the following:

- **US1 (P1) Acceptance Scenarios** — append a new scenario for Q21
  (contract-version-incompatible bootstrap behavior, FR-002):
  Given the daemon's `app_contract_version` is below the app's minimum
  required version for the Routes view, When the operator opens the app,
  Then a global banner appears on every workspace naming the specific
  missing version and the upgrade path, the Routes view renders the
  documented "contract-version-incompatible" state, mutation actions on
  Routes are disabled with an inline explanation, and read-only Routes
  data still renders.

- **US2 (P2) Acceptance Scenarios** — append a new scenario for Q15 (FR-076
  first-launch project resolution):
  Given the persisted last-active project no longer resolves (project removed
  or repo path moved), When the operator launches the app, Then the app lands
  on the Projects view with no project selected and a non-blocking banner
  names the project that could not be restored.

- **US3 (P3) Acceptance Scenarios** — append TWO new scenarios:

  Scenario for Q9 (FR-072 handoff failure tiers):
  Given the operator submits a handoff and the daemon rejects submission,
  When the rejection is received, Then the handoff stays in `drafted` state
  with the daemon error attached inline and the operator can amend and retry
  without losing input.

  Scenario for Q23 (FR-081 supersede semantics):
  Given a feature is being driven by master M1 under handoff H1 and the
  operator submits a second handoff H2 for the same feature with master M2 and
  chooses "supersede", When supersede completes, Then H1 transitions to
  `superseded`, H2 records `superseded_by_handoff_id` pointing to H1, and any
  in-flight queue rows from H1 are left intact (not auto-cancelled).

- **US6 (P3) Acceptance Scenarios** — append a new scenario for Q19 (FR-057
  concrete grouping rule):
  Given the notifications panel receives 5 notifications within 30 seconds
  that share `event_class = route_skipped`, `agent_id = agent-42`, and
  severity `warning`, When the panel updates, Then those 5 notifications
  appear as a single grouped row showing count and most recent timestamp;
  given the operator then expands the row, Then all 5 individual notifications
  are visible.

## F2. Add identity rules to 7 Key Entities

In the `## Key Entities` section, add an "Identity" line to each entity below
as the first sentence after the existing description. Use exactly these
identity rules (consistent with FEAT-011 contract assumptions):

- **Project** — Identity: daemon-issued project id, derived from the
  canonicalized repository absolute path; two registrations of the same
  repository path resolve to the same project id.
- **Adopted Agent** — Identity: daemon-issued agent id; the operator-supplied
  label is mutable and not used for identity.
- **Master Summary** — Identity: the underlying Adopted Agent's id; Master
  Summary is a view, not a separate entity, and exists only for agents
  satisfying FR-071.
- **Handoff** — Identity: daemon-issued handoff id assigned at submission
  time; drafts before submission have a transient client-side draft id.
- **Drift Signal** — Identity: daemon-issued finding id, stable across
  lifecycle transitions; a recurrence of a previously-resolved finding
  receives a new id.
- **Validation Entrypoint** — Identity: daemon-issued entrypoint id, stable
  per project; an entrypoint disabled then re-enabled retains its id.
- **Validation Run** — Identity: daemon-issued run id, unique per execution;
  cancellation followed by re-trigger produces a new id.

## F3. Add transition matrices to 4 lifecycle FRs

Append an "Allowed transitions:" sentence to each:

- **FR-014 (Pane states)** — Append:
  Allowed transitions: `discovered-and-unmanaged ↔ discovered-and-registered`
  (adoption / de-adoption); any state may transition to `inactive/stale` on
  pane disappearance and may return to its prior state on rediscovery; any
  state may transition to `discovery-degraded` on probe failure and back on
  recovery. There are no terminal pane states.

- **FR-034 (Drift Signal lifecycle)** — Append:
  Allowed transitions: `new → review_needed → confirmed → repair_planned →
  resolved` is the canonical forward path; states may also transition to
  `accepted_as_built` or `dismissed` from any non-terminal state; `resolved`,
  `accepted_as_built`, and `dismissed` are terminal. Transitions may NOT skip
  states except into the terminal pair.

- **FR-044 (Handoff assignment-state lifecycle)** — Append:
  Allowed transitions: `drafted → submitted → accepted → active`; from
  `active` the state may transition to `waiting`, `blocked`, `completed`, or
  `cancelled`; `waiting` and `blocked` may return to `active`; `submitted`
  and `accepted` may transition directly to `cancelled` or `superseded`;
  `completed`, `cancelled`, and `superseded` are terminal. Operator-driven
  transitions and daemon-driven transitions are both permitted; the daemon
  is authoritative on conflicts.

- **FR-048 (Validation Run lifecycle)** — Append:
  Allowed transitions: `queued → running → completed`; from `queued` or
  `running` the run may transition to `cancelled`; from `queued` only it
  may transition to `failed_to_start`. The `result` field is only meaningful
  in terminal states (`completed`, `cancelled`, `failed_to_start`).
  `completed`, `cancelled`, and `failed_to_start` are terminal.

## F4. Define helper-agent policy contract

Currently FR-037, FR-038, and FR-042 reference helper-policy fields/defaults
without defining them. The clarifications round of 2026-05-23 (round 2)
resolved every open question; the FR text below reflects those decisions.

Add a new functional requirement immediately after FR-038, numbered
**FR-038a**:

  FR-038a: Helper-agent policies MUST be exposed by the daemon through the
  `app.*` namespace (e.g. `app.helper_policies.list`,
  `app.helper_policies.resolve`); the app MUST NOT read helper-policy
  files directly from disk. A helper-agent policy MUST carry at minimum
  these fields: `policy_id` (stable string), `allowed_helper_capabilities`
  (set of capability tokens), `default_helper_capability` (single token),
  and `policy_source` (`baked_default` | `operator_override` |
  `repo_override`). On handoff submission the daemon MUST snapshot the
  resolved policy into the handoff record's `helper_policy_snapshot` so
  the handoff is reproducible even if defaults change later.

  Override scope is per-handoff only: operator overrides set via FR-037
  apply ONLY to the current submission and MUST be recorded in the
  snapshot as `policy_source = operator_override`. The app MUST NOT
  expose per-master, per-project, or global operator-policy persistence
  in this release.

  Repo-level overrides are permitted: a project repository MAY provide a
  conventional override file (e.g. `agenttower/helper-policy.yaml`) that
  the daemon discovers and surfaces via `app.*`. A resolved policy that
  originated from a repo override MUST be recorded in the handoff
  snapshot as `policy_source = repo_override`.

Do NOT add a flag note to `design.md` for F4 — the contract is resolved.

## F5. Master state vs Agent state relationship

In FR-030, append one sentence at the end:

  Master `current_status` (the master-specific state machine above) is a
  projection over the underlying adopted-agent state defined in FR-015:
  every master is an adopted agent in the `active` agent state; the master
  `current_status` adds the operational status dimension (waiting_for_input,
  blocked, reviewing, idle, offline, degraded) that is meaningful only for
  agents satisfying the master criteria in FR-071.

## F6. Vocabulary normalization: runtime-unavailable → runtime-unreachable

In the `### Edge Cases` section, replace every occurrence of "runtime
unavailable" with "runtime-unreachable" (the canonical term from FR-004).
Expected occurrences: 2 (in the daemon-unreachable edge case and in the
US1 §6 acceptance scenario). Verify by grep after edit.

## F7. Resolve "deferred" feature stage

FR-039 and SC-004 reference "deferred" features but FR-028's stage enum does
not include `deferred`. The clarifications round of 2026-05-23 (round 2)
resolved the open questions; apply all three sub-edits below.

**Sub-edit F7-a — Add the stage value.** Update FR-028's stage enum to:

  `definition`, `spec_ready`, `engineering`, `review`, `validation`,
  `merge_ready`, `merged`, `deferred`, `drift_repair`.

**Sub-edit F7-b — Add the transition rule for `deferred`.** Append to
FR-028, after the existing layered-status sentence:

  The `deferred` stage is non-terminal: a feature/change in `deferred`
  MAY transition back to `definition` or `spec_ready` via an explicit
  un-defer action; no other transitions from `deferred` are allowed.
  The feature/change id is preserved across un-defer.

**Sub-edit F7-c — Specify the FR-039 rendering rule for excluded items.**
In FR-039, after the existing sentence about resolving the explicit
ordered list, insert:

  Excluded items (deferred or merged) MUST appear in the resolved list
  with an explicit exclusion annotation in the form
  `FEAT-N (excluded: deferred)` or `FEAT-N (excluded: merged)`; the
  master receives the resolved list and excluded items are present in
  it as annotated entries, not silently omitted.

**Sub-edit F7-d — Update Key Entities.** If the Feature/Change Status
entity description enumerates stages, update it to include `deferred`
and to note the non-terminal transition rule above.

Do NOT add a flag note to `design.md` for F7 — the questions are resolved.

## F8. Add feature-range syntax to FR-039

In FR-039, after the first sentence (which gives the example `FEAT-N`
through `FEAT-M`), insert:

  The canonical range syntax is `FEAT-N..FEAT-M`, inclusive at both ends;
  the resolver MUST treat the range as defined by ascending numeric order
  of the FEAT id even if the operator inputs them in reverse.

## F9. Cross-reference FR-079 from Changes view and US2 §3

- In FR-032 (Changes view), append at end:
  Document open behavior MUST follow FR-079.

- In US2 (P2) Acceptance Scenarios, find scenario §3 (the operator chooses
  "Open current feature" and the Specs view opens). Append at end of that
  scenario's Then-clause:
  ...and document open behavior follows FR-079.

## F10. Expand Workspace Selection entity

Replace the current Workspace Selection entity definition in `## Key Entities`
with this expanded version:

  - **Workspace Selection** — The operator's persisted UX state, restored
    on a "compatible app launch" (FR-070). Attributes: current workspace,
    current sub-view per workspace, current project, per-view sort/filter
    (per FR-078), theme + density (FR-009), notifications-grouping toggle
    (FR-057), OS-native-notification toggle (FR-058), window geometry, and
    Settings values (per FR-009). Identity: per-OS-user singleton in the
    OS user's standard config directory (per FR-061a). The Workspace
    Selection is the only app-owned persisted entity; all other Key
    Entities are daemon-owned and MUST NOT be persisted by the app
    (per FR-005, FR-069).

## F11. Add completion criteria to onboarding milestones

Replace FR-010's milestone list with an enumerated table specifying each
milestone's completion criterion. The replacement text:

  - **FR-010**: The app MUST package and run as a single-window desktop
    application on Windows, macOS, and Linux; first-launch onboarding MUST
    walk the operator through the eight milestones below, each with an
    automatically-detectable completion criterion the app can observe
    without requiring explicit operator confirmation:

      1. Daemon reachable — complete when the bootstrap (`app.hello`-
         equivalent) returns success.
      2. Bench container check — complete when the daemon reports at least
         one container in the discovery list.
      3. Pane discovery check — complete when the daemon reports at least
         one pane in any state other than `discovery-degraded`.
      4. First pane adoption — complete when the daemon confirms at least
         one pane transition to `discovered-and-registered`.
      5. First agent registration — complete when the daemon's adopted-agent
         list contains at least one entry.
      6. First log attachment — complete when at least one adopted agent's
         log-attachment status is `active`.
      7. First direct send — complete when the daemon acknowledges at least
         one Direct Send (FR-018) with a non-failure response.
      8. First route creation — complete when the daemon's routes list
         contains at least one route in `enabled` state, regardless of
         whether the route has yet matched.

    Onboarding MUST be skippable from any step via an explicit "Skip
    onboarding" affordance; skipped (incomplete) milestones MUST reappear
    as actionable nudges on the Dashboard until completed; per-milestone
    completion state MUST be persisted (and is included in the FR-069
    persisted set) so a completed milestone is not re-prompted after
    completion.

## F12. Enumerate doctor / preflight checks

Replace FR-009 with this expanded version:

  - **FR-009**: The app MUST provide a Settings surface that includes at
    minimum: daemon socket path, contract version display, notifications
    grouping toggle, OS-native notification integration toggle, theme
    selection (Light / Dark / System), density selection (Comfortable /
    Compact), an "Open log folder" affordance (per FR-074), a "Copy
    diagnostics bundle" affordance (per FR-074), and a config doctor /
    preflight check action. The doctor action MUST run AT MINIMUM these
    checks and present a per-check pass/fail with a human-readable
    explanation on failure:

      1. Daemon socket reachable at the configured path.
      2. Daemon socket peer UID matches the current OS user (per FR-061).
      3. `app_contract_version` satisfies the app's minimum required
         versions for every primary workspace surface.
      4. Per-OS-user app-data directory is writable (per FR-061a, FR-074).
      5. Rotating log file is writable and not at its size cap.
      6. OS-native notification permission is granted IF the FR-058 toggle
         is enabled (skipped otherwise).

    Doctor output MUST be includable verbatim in the FR-074 diagnostics
    bundle and MUST also be reachable from the FR-075 command palette.

# OpenSpec workflow steps to follow

1. From repo root, run `openspec-propose` (or `/opsx:propose` if that is the
   available command) with the description shown at the top of this prompt.
2. When the skill creates the change directory under `openspec/changes/`,
   walk the generated `tasks.md` and replace it with a list of 12 tasks,
   one per finding (F1..F12), in that order.
3. The skill will also generate `design.md` and per-spec deltas. Make sure
   the affected-spec delta names ONLY `specs/012-flutter-control-panel/spec.md`
   — do NOT generate deltas for any other spec.
4. No "open questions" stubs are required: F4 and F7 are both resolved by
   the 2026-05-23 round 2 clarifications. The `design.md` need not carry
   flag notes for them.
5. Then run `openspec-apply-change` (or `/opsx:apply`) and process tasks one
   at a time. For each task, edit `specs/012-flutter-control-panel/spec.md`
   exactly as specified above.
6. After all 12 tasks are complete, STOP. Do NOT run
   `openspec-archive-change`. Leave the change in the proposed-applied
   state with an explicit hand-off note in the change's README (or
   equivalent) for human review.

# Quality guardrails

- Do not change unrelated spec text. Only edit the sections / FRs / scenarios
  named above.
- Preserve FR numbering. Do not renumber existing FRs. New FRs are FR-038a
  (already specified) only — no others are added by this pass.
- Keep markdown formatting consistent with the surrounding spec (MUST/MUST
  NOT for normative statements, `code` for identifiers).
- After every edit, re-run `grep -n "^- \*\*FR-0" specs/012-flutter-control-panel/spec.md`
  and confirm no FR was accidentally removed or renumbered.
- After F6, re-run `grep -n "runtime unavailable" specs/012-flutter-control-panel/spec.md`
  and confirm zero matches.
- Do not edit `clarify-questions.md`, `clarify-questions-f4-f7.md`,
  `checklists/*.md`, or any other file besides
  `specs/012-flutter-control-panel/spec.md` and the OpenSpec change artifacts.
- Do not commit, push, or open a PR. Just leave the working tree dirty for
  human review.

# Definition of done

- One OpenSpec change exists under `openspec/changes/spec-quality-pass-feat-012/`
  in proposed-applied (not archived) state.
- `specs/012-flutter-control-panel/spec.md` has been edited for all 12
  findings exactly as specified, including the F7 sub-edits (F7-a stage
  value, F7-b transition rule, F7-c FR-039 annotation rule, F7-d Key
  Entities update).
- FR numbering is intact: FR-001 through FR-082 still present, plus the new
  FR-038a.
- Grep for "runtime unavailable" returns no matches.
- Grep for "FR-079" returns matches in FR-027, FR-031, FR-032, and at least
  one US2 scenario.
- Grep for "FR-038a" returns at least one match.
- Grep for "`deferred`" (in backticks) returns matches in FR-028 and FR-039.
- `git status` shows ONLY changes to `specs/012-flutter-control-panel/spec.md`
  and new files under `openspec/changes/spec-quality-pass-feat-012/`. No
  other files are modified.
- A brief human-readable handoff note (in the change's README or in chat
  output) summarizes which 12 findings were addressed. No open questions
  remain for human review — F4 and F7 were resolved before this run.

Begin now.
````

---

## How to use this document

1. Open a Codex session with working directory set to the repo root: `/workspace/projects/AgentTower-worktrees/012-flutter-control-panel`.
2. Confirm Codex is on branch `012-flutter-control-panel`.
3. Copy the contents of the fenced block above (everything between the triple-backtick lines) and paste it into Codex's prompt input.
4. Let Codex run through the OpenSpec propose → apply workflow. It will stop before archive.
5. Review the resulting change under `openspec/changes/spec-quality-pass-feat-012/` and the edits to `specs/012-flutter-control-panel/spec.md`.
6. Address the two flagged items in `design.md` (F4 helper-policy + F7 deferred stage) — either accept Codex's defaults, edit the spec to match your real decisions, or re-run `/speckit-clarify` to formalize the answers.
7. When satisfied, run `openspec-archive-change` (or the equivalent) to finalize.

## Note on F4 and F7 — RESOLVED

Both findings were resolved by `/speckit-clarify` round 2 on 2026-05-23. The prompt above now bakes in the resolved decisions:

- **F4** — helper-policy is exposed via `app.*` (daemon-side resource, no file reads from app); fields are `policy_id`, `allowed_helper_capabilities`, `default_helper_capability`, `policy_source`; override scope is per-handoff only; repo-level overrides allowed via `agenttower/helper-policy.yaml`.
- **F7** — `deferred` is added to FR-028's stage enum (F7-a); it is non-terminal with explicit un-defer to `definition` or `spec_ready` (F7-b); FR-039 renders excluded items as `FEAT-N (excluded: deferred|merged)` annotations in the resolved list (F7-c); Key Entities Feature/Change Status updated to match (F7-d).

The clarification record is in the spec at `## Clarifications → ### Session 2026-05-23 (round 2)`. No further human input is required before Codex runs.
