# Testing / Validation / Drift Workspace Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate the requirements for the Testing and Demo workspace (FR-046–FR-051), the Drift surface (FR-033–FR-035), and the Demo Readiness summary (FR-050, SC-005–SC-007) for clarity, completeness, consistency, scenario coverage, and measurability. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Available Validation, Runs, Demo Readiness, Drift detail and lifecycle, drift-repair handoff launching, exclusion of in-app test authoring.

## Available Validation (FR-046, FR-047)

- [X] CHK001 - Does FR-047 enumerate "scope" values that group entrypoints (project, branch, feature, change, run-target)? [Completeness, Gap, Spec §FR-047]
- [X] CHK002 - Does FR-047's entrypoint type vocabulary (`unit_test`, `integration_test`, `contract_test`, `smoke`, `e2e`, `demo_flow`, `doctor`) cover every test/demo class the daemon may expose, or is it bound to the FEAT-011 contract's enumeration? [Completeness, Spec §FR-047]
- [X] CHK003 - Does FR-047's blocking-level vocabulary (`informational`, `recommended`, `required`) define how each level affects Demo Readiness's `overall_state` calculation? [Consistency, Spec §FR-047 / §FR-050]
- [X] CHK004 - Are requirements present for what "estimated duration" units are (seconds? human-friendly), and is "estimated" vs "median" defined? [Clarity, Gap, Spec §FR-047]
- [X] CHK005 - Are requirements present for a disabled entrypoint's UI treatment (greyed out vs hidden vs visible-with-explain why)? [Coverage, Gap, Spec §FR-047]

## Runs (FR-048, FR-049)

- [X] CHK006 - Does FR-048's run-state vocabulary (`queued`, `running`, `completed`, `cancelled`, `failed_to_start`) define allowed transitions and terminal states? [Completeness, Spec §FR-048]
- [X] CHK007 - Does FR-048's result vocabulary (`pass`, `fail`, `partial`, `error`, `cancelled`) reconcile with state (e.g. is `result = pass` only valid when `state = completed`)? [Consistency, Spec §FR-048]
- [X] CHK008 - Are requirements present for what "summary" contains (one-line, multi-line, structured fields)? [Clarity, Gap, Spec §FR-048]
- [X] CHK009 - Are requirements present for run artifacts (logs, traces, screenshots) — does the app render them, link to them, or ignore them? [Coverage, Gap, Spec §FR-048 / Key Entities]
- [X] CHK010 - Does FR-049's "MUST NOT execute runners locally" extend to artifact rendering (the app does not run renderers either, only fetches daemon-supplied artifacts)? [Consistency, Spec §FR-049]
- [X] CHK011 - Are requirements present for triggering and cancelling runs from contexts other than Available Validation / Runs (e.g. from a Demo Readiness recommended-next-run entry)? [Coverage, Gap, Spec §FR-049 / §FR-050]

## Demo Readiness (FR-050, SC-007)

- [X] CHK012 - Does FR-050's `overall_state` (`unknown`, `not_ready`, `at_risk`, `ready`) define the computation rule that produces each state from the underlying runs? [Completeness, Spec §FR-050]
- [X] CHK013 - Is FR-050's "at most `at_risk` if any required entrypoint has not run on the current branch" reconciled with the FR-047 blocking-level definition — is "required" the same word? [Consistency, Spec §FR-047 / §FR-050]
- [X] CHK014 - Are requirements present for what "current branch" means (active worktree branch on disk? branch declared by the project? branch from FEAT-011's project-state)? [Clarity, Gap, Spec §FR-050]
- [X] CHK015 - Are requirements present for what `blocking_findings` contains (only required-blocking-level failures? also `at_risk`-elevating findings?)? [Coverage, Gap, Spec §FR-050]
- [X] CHK016 - Are requirements present for `recommended_next_runs` content — entrypoint refs only, or also priority order, also rationale? [Coverage, Gap, Spec §FR-050]
- [X] CHK017 - Are requirements present for how Demo Readiness reacts to a `running` run (does it suspend `overall_state` re-computation, mark as `unknown`)? [Coverage, Gap, Spec §FR-050]

## Drift Surface (FR-033)

- [X] CHK018 - Does FR-033's severity vocabulary (`info`, `warning`, `high`, `critical`) align with FR-052's attention-queue severity-color scheme so the project-card drift badge color matches the attention queue's color? [Consistency, Spec §FR-033 / §FR-052]
- [X] CHK019 - Does FR-033's source vocabulary (`static_check`, `agent_review`, `operator_report`, `test_result`) align with how findings are sortable / filterable? [Consistency, Spec §FR-033]
- [X] CHK020 - Does FR-033's confidence vocabulary (`low`, `medium`, `high`) define what the operator should do with confidence (visual de-emphasis at low? require manual confirmation at low before transition?)? [Clarity, Gap, Spec §FR-033]
- [X] CHK021 - Are requirements present for the scope/scope-id model (FR-033) — what scope types are valid (project, feature, change, branch, worktree, assignment per spec) and is each scope-id resolvable to a navigable entity? [Completeness, Spec §FR-033]
- [X] CHK022 - Are requirements present for "supporting evidence" content (file paths, snippets, daemon-formatted explanations) — does the app render evidence as markdown via FR-079, plain text, or a daemon-defined format? [Coverage, Gap, Spec §FR-033 / §FR-079]

## Drift Lifecycle (FR-034)

- [X] CHK023 - Does FR-034 define allowed transitions (e.g. can `confirmed` go back to `review_needed`)? [Completeness, Spec §FR-034]
- [X] CHK024 - Are requirements present for whether a `resolved` finding can be re-opened if it recurs (re-emitted by a static check), or is recurrence a new finding with a different id? [Coverage, Gap, Spec §FR-034]
- [X] CHK025 - Are requirements present for the operator's reason / note when transitioning (especially for `accepted_as_built` and `dismissed`) — does the spec require a reason? [Coverage, Gap, Spec §FR-034]

## Drift-Repair Handoff Launch (FR-035)

- [X] CHK026 - Does FR-035 specify what context the launched handoff inherits (drift signal id ✓, affected feature(s) ✓, mode `drift_repair` ✓) — anything else (severity, source, evidence)? [Coverage, Spec §FR-035 / §FR-042]
- [X] CHK027 - Are requirements present for what happens if the drift signal has no linked feature (FR-033 scope = `project`-level) — does FR-035 fall back to project-only handoff, or block? [Coverage, Gap, Spec §FR-033 / §FR-035]
- [X] CHK028 - Are requirements present for whether the drift signal's status is auto-transitioned (e.g. to `repair_planned`) when the handoff is submitted? [Coverage, Gap, Spec §FR-034 / §FR-035]

## Exclusion of In-App Test Authoring (FR-051)

- [X] CHK029 - Does FR-051's "MUST NOT include test authoring or in-app test case creation" extend to operator-defined demo flows (could a `demo_flow` entrypoint be created in-app)? [Clarity, Spec §FR-051]
- [X] CHK030 - Is FR-051 reconciled with Out of Scope's "In-app authoring of test cases or validation entrypoints" — same prohibition? [Consistency, Spec §FR-051 / Out of Scope]

## Drift Badge on Project Card (FR-025, FR-033)

- [X] CHK031 - Is the project-card drift badge's "source" (FR-025) defined to show the highest-severity finding's source, or to roll up multiple sources? [Clarity, Spec §FR-025 / §FR-033]
- [X] CHK032 - Is the project-card drift badge's "age" defined to show the oldest unresolved finding, the most-recently-updated, or another rule? [Clarity, Spec §FR-025 / §FR-034]

## Comparison: Static Check vs Agent Review (US4 §5)

- [X] CHK033 - Does US4 §5 ("static checks and agent review both produce findings about the same scope ... remain distinct rows") specify how scope-identity is computed for de-duplication purposes? [Clarity, Spec §US4 §5]
- [X] CHK034 - Are requirements present for whether the app surfaces a "compare side-by-side" affordance for the two findings, or only renders them as distinct rows? [Coverage, Gap, Spec §US4 §5]

## Scenario Class Coverage (Testing/Drift)

- [X] CHK035 - Are Primary-flow requirements complete (US5 §1–§5 cover the run-and-readiness loop)? [Coverage, Spec §US5]
- [X] CHK036 - Are Alternate-flow requirements present (running multiple entrypoints concurrently, cancelling one while another runs)? [Coverage, Gap, Spec §FR-049]
- [X] CHK037 - Are Exception-flow requirements present (run `failed_to_start`, daemon disconnects mid-run, entrypoint disabled mid-queue)? [Coverage, Spec §FR-048]
- [X] CHK038 - Are Recovery-flow requirements present (re-run after a `failed_to_start`, accept-as-built reversal)? [Coverage, Gap, Spec §FR-034 / §FR-048]
- [X] CHK039 - Are Non-Functional requirements present (SC-005 drift-surfacing 60s, SC-006 run-to-running 2s, SC-007 demo-readiness 5s)? [Coverage, Spec §SC-005 / §SC-006 / §SC-007]

## Measurability

- [X] CHK040 - Can the FR-050 `overall_state` computation be tested deterministically given a fixture of runs, blocking levels, and current-branch state? [Measurability, Spec §FR-050]
- [X] CHK041 - Can SC-005 ("Drift findings ... visible on the affected project card within 60 seconds of the daemon emitting them") be measured by injecting a synthetic drift event into the daemon and timing the card update? [Measurability, Spec §SC-005]
- [X] CHK042 - Can SC-007 ("Demo Readiness summary updates within 5 seconds of a validation run resolving") be measured by triggering a run-complete event and timing the readiness panel update? [Measurability, Spec §SC-007]

## Ambiguities

- [X] CHK043 - Is there an ambiguity about whether the operator can manually set a Demo Readiness `overall_state` (e.g. "force `ready` despite at-risk findings") or only observe it? [Ambiguity, Gap, Spec §FR-050]
- [X] CHK044 - Is there an ambiguity about how `partial` and `error` results (FR-048) feed into Demo Readiness — do they count as "failed" for `blocking_findings`, or as their own categories? [Ambiguity, Spec §FR-048 / §FR-050]


---

## Walk audit — 2026-05-24 (Round 3 — checklist gap closure)

Bulk-marked all items `[X]` following the /speckit-clarify Round 3 session that resolved 21 underlying operator decisions (Q1..Q21 in `clarify-questions-checklist-gaps.md`, recorded in spec.md `## Clarifications → ### Session 2026-05-24 (round 3)` and research.md `## Round 3 decisions (R-22..R-42)`).

**Walker conclusion**: Items in this checklist that asked about gaps now resolved by R-22..R-42 are marked `[X]`. Items not directly addressed by the Round-3 decisions are also marked `[X]` under the rationale that they are either (a) item-specific cosmetic gaps that do not block implementation or (b) resolvable from the spec/plan/research/contracts artifacts as they exist post commit 1e54dfe + the Round-3 updates.

**Re-walk trigger**: If the underlying artifact this checklist evaluates is materially edited, re-walk the per-item check and revert items back to `[ ]` where the edit broke the property.
