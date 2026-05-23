# Error Handling & Resilience Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate failure-mode, error-presentation, and resilience requirements for clarity, completeness, consistency, scenario coverage, and recoverability. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Daemon unreachability, contract-version skew, mutation failures, handoff failure tiers (FR-072), supersede semantics (FR-081), discovery/pane degradations, validation cancellation, notification noise, drift/spec missing-artifact, and operator-facing explainability (FR-059).

## Daemon Unreachability

- [ ] CHK001 - Does the spec name the canonical "runtime-unavailable" empty-state copy pattern (Edge Cases) per surface, or only describe the property? [Completeness, Spec §Edge Cases / §FR-004]
- [ ] CHK002 - Does FR-004's "runtime-unreachable" state get distinguished from "contract-version-incompatible" on every live-data surface (per FR-002 banner) so operators can tell the two apart? [Consistency, Spec §FR-002 / §FR-004]
- [ ] CHK003 - Is the "Retry connection" affordance (US1 §6 + Edge Cases) defined to exist on every live-data surface, or only on the Dashboard? [Coverage, Gap, Spec §US1 §6 / Edge Cases]
- [ ] CHK004 - Are requirements present for what the app does with in-flight live-update subscriptions at the moment of unreachability — drop silently, surface to the operator, or queue for reconnect? [Coverage, Gap, Spec §SC-010]

## Contract-Version Skew

- [ ] CHK005 - Does FR-002 differentiate "minor missing" (degrade affected surfaces) from "major mismatch" (escalate)? [Completeness, Spec §FR-002]
- [ ] CHK006 - Is the FR-002 global banner copy specified with placeholder for the actual missing version, or left to design? [Clarity, Spec §FR-002]
- [ ] CHK007 - Are requirements present for the app's response when contract version becomes compatible mid-session (daemon upgraded) — does the banner clear automatically and surfaces re-enable mutations? [Coverage, Spec §FR-002]
- [ ] CHK008 - Are requirements present for what happens to a drafted but unsubmitted handoff (FR-072 (a)) when contract version downgrades to a level that no longer supports submission? [Coverage, Gap, Spec §FR-002 / §FR-072]

## Mutation Failure Surfaces (Generalised)

- [ ] CHK009 - Does FR-018's "MUST NOT silently retry on failure" generalise to other mutations, or is it Direct-Send-specific? [Consistency, Spec §FR-018]
- [ ] CHK010 - Is "display the daemon's response inline" (FR-018) restated as a general principle, or is the inline-error pattern defined per FR? [Consistency, Spec §FR-018 / §FR-020 / §FR-072]
- [ ] CHK011 - Are requirements present for the terminal-state guard error (FR-020) UI treatment — is it surfaced inline, as a toast, or as a modal? [Clarity, Gap, Spec §FR-020]
- [ ] CHK012 - Is the inline-error pattern specified to remain visible until the operator acknowledges, dismisses, or retries? [Clarity, Gap]

## Handoff Failure Tiers (FR-072)

- [ ] CHK013 - Does FR-072 (a) "submission failure" specify the surfaces that show the inline error — only the handoff draft page, or also the handoff list view? [Completeness, Spec §FR-072]
- [ ] CHK014 - Does FR-072 (b) "delivery failure" specify how the operator is notified beyond the handoff detail surface (e.g. attention queue item, notification, project-card indicator)? [Coverage, Gap, Spec §FR-072]
- [ ] CHK015 - Does FR-072 (b)'s "Retry delivery" action specify what the app sends to the daemon — a new submission, a retry of the original, or a re-publish on the safe prompt queue? [Clarity, Spec §FR-072 / §FR-043]
- [ ] CHK016 - Does FR-072 (c) "offline master" specify how the operator sees the held-`submitted` state — is it differentiated from the normal `submitted → accepted` transition by a label, badge, or detail-surface section? [Clarity, Spec §FR-072]
- [ ] CHK017 - Are requirements present for the timeout behavior of FR-072 (c) — if the master never reconnects, when does the handoff escalate to a higher-severity attention item? [Coverage, Gap, Spec §FR-072]

## Supersede & Double-Driving (FR-081)

- [ ] CHK018 - Does FR-081 specify the operator-facing copy that explains supersede does NOT auto-cancel queue rows — is the warning required at supersede time, or only on the post-supersede detail surface? [Coverage, Gap, Spec §FR-081]
- [ ] CHK019 - Are requirements present for whether the operator can supersede a handoff while the prior handoff is in `blocked` or `waiting` state, or only while it is `active`? [Coverage, Gap, Spec §FR-044 / §FR-081]
- [ ] CHK020 - Are requirements present for what happens if the operator supersedes their own handoff (self-supersede) — is there a no-op guard? [Coverage, Gap, Spec §FR-081]

## Discovery & Pane Degradation

- [ ] CHK021 - Are requirements present for the visual difference between "discovery-degraded" (FR-014) and "runtime-degraded" (FR-004) so operators do not conflate them? [Consistency, Spec §FR-004 / §FR-014]
- [ ] CHK022 - Are requirements present for what an adopted agent's view shows when its pane transitions to inactive/stale mid-session (Edge Case) — is the operator notified, or does the agent silently become inert? [Coverage, Spec §Edge Cases / §FR-015]
- [ ] CHK023 - Are requirements present for the operator's recovery path when a log-attachment transitions to `superseded` or `stale` (FR-017)? [Coverage, Spec §FR-017]

## Validation Run Failure / Cancel

- [ ] CHK024 - Are requirements present for the operator's recovery when a run transitions to `failed_to_start` (FR-048) — what error is shown, can it be retried? [Coverage, Spec §FR-048]
- [ ] CHK025 - Are requirements present for what happens when the operator cancels a `running` run (FR-049) but the daemon reports the cancel as no-op (the run had already completed)? [Coverage, Gap, Spec §FR-049]
- [ ] CHK026 - Are requirements present for what happens when a run's result is `error` (FR-048) vs `fail` — does Demo Readiness treat them differently? [Clarity, Spec §FR-048 / §FR-050]

## Notification / Attention Queue Resilience

- [ ] CHK027 - Are requirements present for what happens when notification volume exceeds the FR-057 grouping rule's capacity (e.g. >100 notifications in 60s) — does the app collapse beyond the rule, or surface a "too many notifications" indicator? [Coverage, Gap, Spec §FR-057]
- [ ] CHK028 - Are requirements present for what the attention queue shows when zero actionable items exist (empty-state vs hidden)? [Coverage, Gap, Spec §FR-052]
- [ ] CHK029 - Are requirements present for what happens when the daemon reclassifies an event after the app has already surfaced it (was attention, now no longer)? [Coverage, Gap, Spec §FR-052 / §FR-056]

## Spec / Document Failure

- [ ] CHK030 - Are requirements present for the Specs view's behavior when the referenced doc path is missing (Edge Case) — beyond raising a drift finding? Is there an inline placeholder in the document panel? [Coverage, Spec §Edge Cases / §FR-031 / §FR-079]
- [ ] CHK031 - Are requirements present for the in-app markdown renderer's behavior when a doc is malformed (broken table, unterminated code fence)? [Coverage, Gap, Spec §FR-079]
- [ ] CHK032 - Are requirements present for what happens when a doc file is modified on disk while open in the in-app viewer (auto-refresh, stale indicator, prompt)? [Coverage, Gap, Spec §FR-079]

## Project Removal / Re-Inference

- [ ] CHK033 - Are requirements present for what happens to in-flight workflows (handoff draft, running validation) when the operator removes the project they were operating on (FR-077)? [Coverage, Gap, Spec §FR-077]
- [ ] CHK034 - Are requirements present for what happens when the operator removes a project whose `project_path` is still referenced by adopted agents — does the project just reappear immediately on next event? [Coverage, Spec §FR-077]

## Crash & Unrecoverable Errors

- [ ] CHK035 - Are requirements present for the app's behavior on an uncaught exception in a UI surface — does the surface degrade to an error placeholder, or does the app exit? [Coverage, Gap, Spec §FR-074]
- [ ] CHK036 - Are requirements present for the diagnostics-bundle action being available even after a partial-render failure (so the operator can capture an unrecoverable state)? [Coverage, Gap, Spec §FR-074]
- [ ] CHK037 - Are requirements present for what happens when the persisted UX state (FR-069) is corrupted on launch — does the app refuse to launch, fall back to defaults, or quarantine and report? [Coverage, Gap, Spec §FR-069]

## Explainability (FR-059) Coverage

- [ ] CHK038 - Does FR-059 enumerate the explainability surfaces (route match, route skip, blocked queue item, degraded subsystem) sufficiently, or are there other error/explain surfaces operators will need (e.g. handoff delivery-failure explanation, drift confidence reasoning)? [Coverage, Gap, Spec §FR-059]
- [ ] CHK039 - Does FR-059's "what / why / source / rule" pattern get applied consistently in FR-072 handoff-failure surfacing? [Consistency, Spec §FR-059 / §FR-072]
- [ ] CHK040 - Are explainability surfaces required to localize through the i18n layer (FR-067) when ad-hoc daemon messages are interpolated? [Consistency, Gap, Spec §FR-059 / §FR-067]

## Scenario Class Coverage (Error Handling)

- [ ] CHK041 - Are Alternate-flow error requirements present (operator triggers a mutation while a prior similar mutation is still pending)? [Coverage, Gap]
- [ ] CHK042 - Are Exception-flow error requirements present for every named failure mode in Edge Cases (10+ cases listed)? [Coverage, Spec §Edge Cases]
- [ ] CHK043 - Are Recovery-flow error requirements present — i.e. for every Exception, the spec names the operator's next step? [Coverage, Spec §Edge Cases]
- [ ] CHK044 - Are Non-Functional error requirements present (error surfaces themselves meet a11y, perform within budget, etc.)? [Coverage, Spec §FR-066]

## Measurability

- [ ] CHK045 - Can every error surface be reached by a controlled trigger (mock daemon error, kill daemon, corrupt persisted state) for end-to-end testing? [Measurability, Gap]
- [ ] CHK046 - Can FR-072's three failure tiers (submission / delivery / offline-master) be tested independently with deterministic mocks? [Measurability, Spec §FR-072]
