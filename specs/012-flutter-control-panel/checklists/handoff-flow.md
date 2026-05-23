# Handoff Flow Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate handoff-flow requirements (FR-036–FR-045, FR-071 master criteria, FR-072 failure modes, FR-081 supersede semantics, FR-043 safe prompt queue, US3 acceptance scenarios) for clarity, completeness, consistency, scenario coverage, and measurability. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Inputs, auto-fill context, prompt skeleton (six sections), preview, operator notes, submission, delivery via safe prompt queue, assignment-state lifecycle, supersede, failure modes, querying.

## Inputs (FR-036, FR-037)

- [ ] CHK001 - Does FR-036 require master, project, work-item selection, and mode IN ORDER, or is the order a UX convention? Is "in order" tested? [Clarity, Spec §FR-036]
- [ ] CHK002 - Is FR-036's work-item-selection vocabulary (one feature, multiple features, feature range, one OpenSpec change, multiple OpenSpec changes) defined to allow mixed selections (e.g. one feature + one change in the same handoff), or only single-class selections? [Clarity, Spec §FR-036]
- [ ] CHK003 - Does FR-037 specify which optional fields gate later behavior (e.g. does providing a deadline trigger SLA notifications)? [Coverage, Gap, Spec §FR-037]
- [ ] CHK004 - Are requirements present for input validation on each field (master must be a master per FR-071, project must resolve, feature ids must exist on the project)? [Coverage, Gap, Spec §FR-036 / §FR-071]

## Auto-Fill Context (FR-038)

- [ ] CHK005 - Does FR-038 enumerate every auto-filled field, and is each field's source defined (which `app.*` method supplies it)? [Completeness, Spec §FR-038]
- [ ] CHK006 - Are requirements present for what the auto-fill does when a doc path is missing — does it skip the field, include the path with a missing-artifact marker, or block submission? [Coverage, Spec §FR-038 / Edge Cases]
- [ ] CHK007 - Are requirements present for the operator's ability to view (but not edit) auto-filled fields in the preview, so they can confirm the context before submitting? [Coverage, Gap, Spec §FR-038 / §FR-041]
- [ ] CHK008 - Are requirements present for auto-fill behavior when "current feature/change stage/status/subphase" is `definition` (incomplete) — is the handoff allowed, blocked, or warned? [Coverage, Gap, Spec §FR-028 / §FR-038]

## Feature-Range Resolution (FR-039, SC-004)

- [ ] CHK009 - Does FR-039 define the canonical syntax for a feature range (FEAT-N..FEAT-M, FEAT-N-FEAT-M, regex)? [Clarity, Spec §FR-039]
- [ ] CHK010 - Are requirements present for what the spec considers "deferred" and "merged" — terms used in the explicit ordered list? Are these states drawn from FR-028's three-layer status model? [Consistency, Spec §FR-028 / §FR-039]
- [ ] CHK011 - Is SC-004's "resolved list shown in the handoff preview and the list embedded in the submitted prompt match exactly" testable, and is "match exactly" defined (same order, same wording)? [Measurability, Spec §SC-004]

## Prompt Skeleton (FR-040)

- [ ] CHK012 - Does FR-040 specify the section ordering as a strict requirement (Assignment, Project Context, Workflow Instruction, Helper-Agent Policy, Success Criteria, Stopping and Escalation Rules) — and is the spec consistent everywhere that names this skeleton (FR-041, US3 §1, US3 §6)? [Consistency, Spec §FR-040 / §FR-041 / §US3]
- [ ] CHK013 - Are requirements present for what each section contains as a minimum body (e.g. Project Context must name repo + PRD + architecture + roadmap + selected feature spec paths per US3 §1)? [Completeness, Spec §FR-040 / §US3 §1]
- [ ] CHK014 - Are requirements present for how the prompt body changes when the mode changes (FR-040 says "regenerate ... while preserving operator notes") — is the regeneration deterministic given the same inputs? [Coverage, Spec §FR-040]
- [ ] CHK015 - Are requirements present for the prompt's encoding (markdown? plain text? structured headers) so the receiving master can parse it consistently? [Clarity, Gap, Spec §FR-040]

## Operator Notes (FR-041)

- [ ] CHK016 - Does FR-041 specify where in the prompt the operator notes are inserted (a dedicated section, appended after Stopping and Escalation Rules, woven into Workflow Instruction)? [Clarity, Spec §FR-041]
- [ ] CHK017 - Are requirements present for character / length limits on operator notes? [Coverage, Gap, Spec §FR-041]
- [ ] CHK018 - Are requirements present for the system rejecting skeleton edits (FR-041) — what UI surface, what copy? [Clarity, Spec §FR-041]

## Mode Switching (FR-040, US3 §3)

- [ ] CHK019 - Does FR-040's "preserving operator notes already entered" rule generalize to also preserve helper-policy override and priority/deadline when mode changes? [Coverage, Gap, Spec §FR-040 / §FR-037]
- [ ] CHK020 - Are requirements present for what happens to the resolved work-item list when mode changes (some modes might exclude already-merged features differently)? [Coverage, Gap, Spec §FR-039 / §FR-040]

## Submission (FR-042, FR-043)

- [ ] CHK021 - Does FR-042 enumerate every persisted field exhaustively, and does the order match the Key Entities Handoff definition? [Consistency, Spec §FR-042 / Key Entities]
- [ ] CHK022 - Is FR-043's delivery via the safe prompt queue (FEAT-009) defined to fail soft (handoff is persisted even if queue delivery fails per FR-072 (b))? [Consistency, Spec §FR-043 / §FR-072]
- [ ] CHK023 - Are requirements present for the daemon's ack of submission — is the handoff id daemon-issued or client-issued, and how is the operator told once the daemon confirms? [Clarity, Spec §FR-042 / §FR-043]

## Assignment State Lifecycle (FR-044)

- [ ] CHK024 - Does FR-044 define allowed transitions for every state (e.g. can `accepted` go back to `submitted`, can `blocked` go to `cancelled`)? [Completeness, Gap, Spec §FR-044]
- [ ] CHK025 - Are requirements present for who drives state transitions (operator action via the app? daemon-side automated? both)? [Clarity, Gap, Spec §FR-044]
- [ ] CHK026 - Are requirements present for whether `completed` and `cancelled` and `superseded` are terminal (no further transitions allowed)? [Coverage, Spec §FR-044]
- [ ] CHK027 - Is the FR-072 "held `submitted` until reconnection" state distinguishable from a normally-stalled `submitted` state (so the operator can tell the offline-master case from a slow-acceptance case)? [Clarity, Spec §FR-072]

## Querying & Filtering (FR-045)

- [ ] CHK028 - Does FR-045's filter set (project, master, feature/change, assignment state, date range) include a default that lands on "relevant to me right now" (e.g. last 30 days + non-terminal states)? [Coverage, Gap, Spec §FR-045]
- [ ] CHK029 - Are requirements present for whether the filter set is combinable (AND across filters, OR within a multi-select) and whether saved filters are part of FR-078 per-view persistence? [Coverage, Gap, Spec §FR-045 / §FR-078]

## Supersede Semantics (FR-081)

- [ ] CHK030 - Does FR-081 make the no-auto-cancel rule visible to the operator at supersede time (per error-handling.md CHK018) — is the warning surface specified? [Coverage, Spec §FR-081]
- [ ] CHK031 - Is the `superseded_by_handoff_id` field bidirectional — does the new handoff also record `supersedes_handoff_id`? If not, is the back-reference derivable? [Coverage, Gap, Spec §FR-042 / §FR-081]
- [ ] CHK032 - Are requirements present for surfacing supersede chains in the UI (handoff A → superseded by B → superseded by C)? [Coverage, Gap, Spec §FR-081]

## Driving-Master Indicator (FR-029)

- [ ] CHK033 - Does FR-029's "agent X is driving FEAT-N under handoff H" specify where it appears (feature card, Current Work view, spec view) — and what happens when no master is currently driving? [Completeness, Spec §FR-029]
- [ ] CHK034 - Are requirements present for what the indicator shows when multiple non-superseded handoffs target the same feature with different masters (the double-driving Edge Case + FR-081)? [Consistency, Spec §FR-029 / §FR-081 / Edge Cases]

## Helper-Agent Policy (FR-037, FR-038, FR-042)

- [ ] CHK035 - Does the spec name the helper-agent policy contract (what fields, what defaults) referenced by FR-038 ("allowed helper-agent defaults") and FR-042 ("helper policy id, helper policy snapshot")? [Completeness, Gap, Spec §FR-037 / §FR-038 / §FR-042 / Out of Scope]
- [ ] CHK036 - Is the assumption that helper-agent capability mapping "ships as defaults baked into this release" (Out of Scope) reconciled with FR-037's "helper-agent policy override" — what does the operator override? [Consistency, Spec §FR-037 / Out of Scope]

## Failure Modes (FR-072)

- [ ] CHK037 - Are FR-072 (a), (b), (c) reflected in acceptance scenarios for US3, or is US3 only covering the happy path? [Coverage, Gap, Spec §US3 / §FR-072]
- [ ] CHK038 - Are requirements present for a maximum retry count on FR-072 (b) "Retry delivery" — or is retry unbounded? [Coverage, Gap, Spec §FR-072]
- [ ] CHK039 - Are requirements present for how FR-072 (c) "offline master" state interacts with FR-058 OS-native notifications — does the operator get notified when the master comes back online and the handoff transitions to `accepted`? [Coverage, Spec §FR-058 / §FR-072]

## Scenario Class Coverage (Handoff Flow)

- [ ] CHK040 - Are Primary-flow handoff requirements complete (US3 §1, §4 cover happy path)? [Coverage, Spec §US3]
- [ ] CHK041 - Are Alternate-flow handoff requirements present (operator drafts, walks away, returns later — does the draft persist? per FR-072 (a) it does if submission failed; what about pure draft state)? [Coverage, Gap, Spec §FR-072]
- [ ] CHK042 - Are Exception-flow handoff requirements present (operator selects master that becomes non-master between selection and submit; project resolves at draft time but not at submit time)? [Coverage, Gap]
- [ ] CHK043 - Are Recovery-flow handoff requirements present (operator's retry after FR-072 (b) delivery failure, operator's manual cancel of a stuck `submitted` handoff)? [Coverage, Spec §FR-072]
- [ ] CHK044 - Are Non-Functional handoff requirements present (SC-003 generation budget, prompt-rendering performance for long feature ranges)? [Coverage, Spec §SC-003 / §FR-062]

## Measurability

- [ ] CHK045 - Can FR-040's six-section skeleton be validated against a known-good fixture (snapshot test)? [Measurability, Spec §FR-040]
- [ ] CHK046 - Can FR-041's skeleton-edit rejection be validated by an automated UI test that attempts to mutate each section? [Measurability, Spec §FR-041]
- [ ] CHK047 - Can FR-072's three failure tiers be triggered independently and the handoff's state transition asserted? [Measurability, Spec §FR-072]
- [ ] CHK048 - Can SC-003's 30-second handoff budget be measured for a single-feature, fully-autofilled flow? [Measurability, Spec §SC-003]

## Ambiguities & Conflicts

- [ ] CHK049 - Is there an ambiguity about whether `assignment_state = drafted` is persisted to the daemon at all, or held only in app-side memory (which would conflict with FR-069's "MUST NOT persist domain data" if drafts are domain data)? [Ambiguity, Spec §FR-042 / §FR-044 / §FR-069 / §FR-072]
- [ ] CHK050 - Is there an ambiguity about how a `drift_repair` mode handoff launched from Drift (FR-035) sets its "primary work item" — is it the drift signal id, or one of the affected feature ids? [Ambiguity, Spec §FR-035 / §FR-042]

## Round 2 — Post-plan re-verification (2026-05-23)

Re-checks that `contracts/helper-policy.md`, `research.md` R-19, `data-model.md` §1.6-§1.8, and FR-038a / FR-072 / FR-081 close the Round-1 handoff-flow gaps.

- [ ] CHK051 - Does helper-policy.md §2 close CHK035 (helper-agent policy contract fields) — the 4 required fields are now enumerated? [Closure-check, Round-1 CHK035]
- [ ] CHK052 - Does helper-policy.md §4 close CHK036 (helper override semantics) — per-handoff scope only? [Closure-check, Round-1 CHK036]
- [ ] CHK053 - Does spec FR-072 + data-model.md §1.6 (Handoff.deliveryStatus, .failureContext) close CHK037 (FR-072 acceptance scenarios) — note: the Codex pass added scenarios; verify they exist in the spec? [Closure-check, Round-1 CHK037]
- [ ] CHK054 - Does data-model.md §1.6 (draftId field) close CHK041 (pure-draft persistence behavior)? [Closure-check, Round-1 CHK041]
- [ ] CHK055 - Does helper-policy.md §6 close CHK008 (handoff on `definition` stage feature) — Note: still ambiguous; not closed? [Closure-check, Round-1 CHK008]
- [ ] CHK056 - Does data-model.md §1.6 (supersededByHandoffId + supersedesHandoffId) close CHK031 (bidirectional supersede link)? [Closure-check, Round-1 CHK031]
- [ ] CHK057 - Does data-model.md §1.7 ResolvedWorkItem + ResolvedExclusion close CHK010 ("deferred" not in FR-028) — Note: F7-a now adds it to FR-028? [Closure-check, Round-1 CHK010]
- [ ] CHK058 - Does spec FR-039 (with F8 syntax + F7-c annotation) close CHK009 (feature-range syntax) AND CHK020 (resolved-list changes with mode)? [Closure-check, Round-1 CHK009/020]
- [ ] CHK059 - Does spec FR-038a + helper-policy.md §5 close CHK023 (handoff id origin) by stating daemon-issued at submission? [Closure-check, Round-1 CHK023]
- [ ] CHK060 - Are Round-1 gaps NOT closed by the plan: filter defaults (CHK028), filter combinability (CHK029), supersede warning copy (CHK030), supersede chain surfacing (CHK032), multi-driver display (CHK034), retry count limit (CHK038), master-becomes-non-master (CHK042), drift_repair primary item (CHK050)? [Gap-tracking, Round-1 multi-CHK]
- [ ] CHK061 - Does the plan-side artifacts introduce ANY new handoff-flow concern (e.g. handoff list view's offline-master indicator from F-area finding F48)? [Coverage]
