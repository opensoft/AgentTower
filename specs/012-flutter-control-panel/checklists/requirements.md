# Specification Quality Checklist: Flutter Desktop Control Panel for Local Operator Workspaces

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

### Content Quality

- "Flutter" appears in the title and Summary because it is part of the FEAT-012 product decision recorded in `docs/mvp-feature-sequence.md` and `docs/product-sections-and-control-panel.md`. It identifies the product, not an implementation strategy; the spec does not prescribe Flutter libraries, frameworks, state-management approach, or rendering details. Treat the framework name as a fixed product attribute, similar to "desktop app for Windows, macOS, and Linux".
- "Unix socket" and `SO_PEERCRED` appear in FR-060/FR-061 and Assumptions because the trust model is a product-visible commitment (local-only, same-host) inherited from FEAT-011. They describe the security posture the operator must understand, not the implementation of the socket client.
- "Safe prompt queue" naming in FR-043 and Assumptions refers to the operator-facing FEAT-009 capability surfaced in the app, not the internal queue implementation.

### Requirement Completeness

- Zero `[NEEDS CLARIFICATION]` markers in spec.md (verified by search).
- All functional requirements use MUST/MUST NOT and name testable conditions (states, fields, navigation outcomes, time budgets).
- Success criteria include both quantitative budgets (SC-001 10 minutes onboarding, SC-002 5 seconds per project, SC-003 30 seconds for handoff, SC-005 60 seconds drift surfacing, SC-006/SC-007 sub-5-second update budgets, SC-010 2/5 second outage transitions) and qualitative outcomes (SC-011 90% step completion rate, SC-012 90% identification success).
- Acceptance scenarios are present for each of the six user stories and use Given/When/Then form.
- Edge cases cover daemon outages, contract-version skew, empty/degraded discovery states, pane loss under an adopted agent, feature-range gaps, concurrent driving conflicts, missing docs, slow runs, notification volume, and attention-queue interaction stability.

### Feature Readiness

- Each user story has an "Independent Test" clause naming a minimum viable shippable slice.
- Functional requirements map to acceptance scenarios (e.g. FR-016 Adopt-flow → US1 #2; FR-040/FR-041 Prompt skeleton → US3 #3/#6; FR-053 stability window → US6 #1 / SC-008a; FR-050 demo readiness → US5 #4).
- Out-of-scope section explicitly excludes FEAT-013 managed creation, hosted backends, mobile, antigravity, raw-log inspector, in-app spec editing, and multi-daemon.

### Outstanding items deferred to later Speckit phases (not blockers for /speckit-plan)

- Concrete number for the attention-queue interaction-stability window (FR-053 / SC-008a) — picked in plan.
- Concrete pagination page sizes for list-view 1-second budgets (FR-063) — derived from FEAT-011 page-size defaults in plan.
- Settings surface taxonomy (which settings live where) — fleshed out in plan/UX design.

### Items marked incomplete

- None. All checklist items pass. The spec is ready for `/speckit-clarify` (optional) or `/speckit-plan`.

---

## Cross-Cutting Requirement-Quality Checks (appended 2026-05-23, max-coverage run)

The items above are pre-flight content-quality marks. The items below are "unit tests for English" applied to the cross-cutting dimensions: Completeness, Clarity, Consistency, Acceptance Criteria Quality, Dependencies & Assumptions, Ambiguities & Conflicts. They evaluate the requirements themselves, not the future implementation. See per-domain checklists (`ux.md`, `api-contract.md`, etc.) for domain-deep coverage.

### Completeness

- [ ] CHK001 - Is every functional requirement that introduces an enumerated state vocabulary (pane states, agent states, queue states, route enabled/skip, validation run states, validation results, demo readiness `overall_state`, drift status/severity/confidence/source, handoff assignment states, feature/change stage + execution status + subphase, daemon subsystems) named with its full set of allowed values in the spec? [Completeness, Spec §FR-014/FR-015/FR-020/FR-021/FR-028/FR-030/FR-033/FR-034/FR-044/FR-047/FR-048/FR-050]
- [ ] CHK002 - Are project-card display attributes (FR-025) defined consistently with the attributes named on Project, Master Summary, and Drift Signal entities (e.g. "validation badge + last run age", "drift badge + source + age", "current driving master") such that the entity definitions are sufficient to specify the card view? [Completeness, Spec §FR-025 / Key Entities]
- [ ] CHK003 - Are requirements present for what is shown on the project card and Current Work view when a project has zero active features/changes, zero assigned masters, or zero drift findings? [Completeness, Gap]
- [ ] CHK004 - Are requirements present for what is shown when an active feature/change references a master that has been deleted or unadopted? [Completeness, Gap]
- [ ] CHK005 - Are requirements present for the operator history surface's filterability, retention, and sort order beyond "default-rolled-up by agent"? [Completeness, Spec §FR-055]
- [ ] CHK006 - Are the eight onboarding milestones (FR-010) each defined with an explicit completion criterion the app can detect (not just "the operator did X")? [Completeness, Spec §FR-010]
- [ ] CHK007 - Are requirements present for what the "blocking findings" and "recommended next runs" lists on the Demo Readiness summary actually contain (just entrypoint refs? include rationale?)? [Completeness, Spec §FR-050]
- [ ] CHK008 - Are requirements present for the "doctor / preflight check action" (FR-009) — what it checks, what output format it produces, how failure is presented? [Completeness, Spec §FR-009]
- [ ] CHK009 - Are requirements present for what counts as a "primary action" (FR-075 kbd/palette coverage) — is there an explicit enumeration, or is it derivable from the FRs that already exist? [Completeness, Spec §FR-075]
- [ ] CHK010 - Is the daemon's "configured release feed" (FR-068) defined — origin, format, polling cadence beyond "at most once per app launch", and behavior when the feed is unreachable? [Completeness, Spec §FR-068]

### Clarity

- [ ] CHK011 - Is the term "operationally readable" (SC-001, FR-062) defined with concrete observable criteria (counts visible, no spinner, health pill rendered) or left to interpretation? [Clarity, Spec §FR-062 / SC-001]
- [ ] CHK012 - Is "last meaningful activity" (multiple FRs) defined — what event classes count as meaningful vs noise? [Clarity, Gap, Spec §FR-030 / Key Entities]
- [ ] CHK013 - Is "non-blocking banner" (FR-076) defined consistently across the spec, and distinguished from the "global banner" used in FR-002 for contract-version mismatch? [Clarity, Spec §FR-002 / §FR-076]
- [ ] CHK014 - Is the difference between an "attention summary" and a "notification count" (FR-025) defined precisely enough that the project card can render them without overlap or double-counting? [Clarity, Spec §FR-025]
- [ ] CHK015 - Is "documented threshold" for operator-action latency logging (FR-074) given as a value or as a placeholder to be set in the plan? [Clarity, Spec §FR-074]
- [ ] CHK016 - Is "master-class capability" (FR-071) defined as an enumerated set or as a daemon-side-registered identifier the app reads — and is the source of truth named? [Clarity, Spec §FR-071]
- [ ] CHK017 - Is "compatible app launch" (FR-070) clearly distinguished from "compatible contract version" (FR-002) so that the persistence policy and the read-only-mode policy do not collide on a borderline version mismatch? [Clarity, Spec §FR-002 / §FR-070]
- [ ] CHK018 - Is the term "event_class" (FR-057 grouping rule) defined with reference to the daemon's classifier output, or left as an undefined string? [Clarity, Spec §FR-057]
- [ ] CHK019 - Is "in a single navigation step" (FR-007) measurable — does it permit a modal step, a search-first then select step, or only one click? [Clarity, Spec §FR-007 / US2 §4]
- [ ] CHK020 - Is "compact master strip (up to two masters with overflow summarized)" (FR-025) defined consistently with the Master Summary entity such that a card carrying two of the same status renders unambiguously? [Clarity, Spec §FR-025]

### Consistency

- [ ] CHK021 - Are the four runtime states in FR-004 (runtime-unreachable, contract-version-incompatible, runtime-healthy-empty, runtime-healthy-populated, runtime-degraded) used consistently in every later FR that references "runtime unavailable", "discovery-degraded", or "degraded but usable", or are there parallel vocabularies in tension? [Consistency, Spec §FR-004 / §FR-013 / §FR-014 / §FR-022 / §FR-036 / Edge Cases]
- [ ] CHK022 - Are the four pane states in FR-014 (discovered-and-unmanaged, discovered-and-registered, inactive/stale, discovery-degraded) used identically in the Pane entity definition and the Edge Cases section (pane disappears under adopted agent)? [Consistency, Spec §FR-014 / Edge Cases / Key Entities]
- [ ] CHK023 - Is the agent state vocabulary (FR-015: active, inactive, partially configured, log-attached, log-detached) consistent with the master current-status vocabulary (FR-030: active, waiting_for_input, blocked, reviewing, idle, offline, degraded), and is the relationship between the two explained? [Consistency, Spec §FR-015 / §FR-030]
- [ ] CHK024 - Are the handoff assignment-state lifecycle (FR-044) and the feature/change three-layer status model (FR-028) shown as independent state machines anywhere a surface displays both — and is the rule that they are independent stated normatively, not just descriptively? [Consistency, Spec §FR-028 / §FR-044]
- [ ] CHK025 - Are project-scoped persistence rules (FR-078) consistent with the project removal rule (FR-077) — i.e. does "clears that project's UI-side persistence" cover every persistence dimension FR-078 introduces? [Consistency, Spec §FR-077 / §FR-078]
- [ ] CHK026 - Is the document-rendering rule (FR-079) consistent across FR-027 (Current Work), FR-031 (Specs), FR-032 (Changes), and US2 §3 (Specs view document links) — and does it cover OpenSpec change document paths in addition to PRD/architecture/roadmap/feature spec? [Consistency, Spec §FR-027 / §FR-031 / §FR-032 / §FR-079]
- [ ] CHK027 - Is the notification grouping rule (FR-057) consistent with the high-severity OS-native notification behavior (FR-058 + US6 §5) — i.e. high notifications are never grouped AND always trigger an OS notification when opt-in is enabled? [Consistency, Spec §FR-057 / §FR-058]
- [ ] CHK028 - Is the trust-model statement (FR-061) consistent with the per-OS-user isolation rule (FR-061a) — do both reference the same socket-path discovery and UID-match enforcement? [Consistency, Spec §FR-061 / §FR-061a]
- [ ] CHK029 - Is the keyboard-shortcut for the project switcher in FR-007 (`Ctrl+P` / `Cmd+P`) consistent with the command-palette shortcut in FR-075 (`Ctrl+K` / `Cmd+K`) such that they cannot collide on any documented OS? [Consistency, Spec §FR-007 / §FR-075]
- [ ] CHK030 - Are the FR numbering and topical grouping consistent — specifically, is the out-of-order placement of FR-071 (within Project and Specs but after FR-030) intentional and harmless to downstream tooling that reads the spec? [Consistency, Spec §Requirements]

### Acceptance Criteria Quality

- [ ] CHK031 - Does every Success Criterion (SC-001 … SC-013, including SC-008a) carry a measurement method explicit enough to be repeated by a different team in a different environment? [Acceptance Criteria, Spec §Success Criteria]
- [ ] CHK032 - Is SC-008a's "100 simulated live-update bursts" defined operationally (what counts as a burst, what arrival pattern, what hover pattern) sufficiently for an automated test to be written against it? [Acceptance Criteria, Spec §SC-008a]
- [ ] CHK033 - Are SC-011 and SC-012's survey methodology, cohort size, and "pass" thresholds (≥90%) tied to a specific cohort defined in Assumptions — and does the spec name where that cohort definition lives? [Acceptance Criteria, Spec §SC-011 / §SC-012 / Assumptions]
- [ ] CHK034 - Is SC-005 ("within 60 seconds of the daemon emitting") tied to a definable origin timestamp on the daemon side (i.e. is "emitted" defined the same way the daemon and the app agree)? [Acceptance Criteria, Spec §SC-005]
- [ ] CHK035 - Are the performance budgets (FR-062 to FR-065) tied to environmental preconditions (machine class, daemon load, network conditions if any) so they remain reproducible? [Acceptance Criteria, Spec §FR-062 / §FR-063 / §FR-064 / §FR-065]
- [ ] CHK036 - Does every user-story Independent Test name a shippable slice with a verification path that does not depend on other US shipping first (where the priority allows)? [Acceptance Criteria, Spec §User Scenarios]
- [ ] CHK037 - Is there at least one acceptance scenario or success criterion covering each clarification answer (especially Q9 handoff failures, Q15 first-launch project resolution, Q19 notification grouping rule, Q21 contract-version-incompatible behavior, Q23 supersede semantics)? [Acceptance Criteria, Spec §Clarifications]

### Dependencies & Assumptions

- [ ] CHK038 - Are all FEAT-011 `app.*` method dependencies the app relies on (bootstrap, discovery, pane adoption, log attach, direct send, route management, queue actions, handoff submission, validation run trigger/cancel, drift transitions, demo readiness query) called out in the Dependencies section beyond the umbrella "Hard dependency" sentence? [Dependencies, Gap, Spec §Dependencies]
- [ ] CHK039 - Are the FEAT-001..FEAT-010 indirect dependencies enumerated by capability (containers, panes, agents, log attachment, events, queue, routes, arbitration) sufficient for an implementer to know which FEAT covers which `app.*` method they will call? [Dependencies, Spec §Dependencies]
- [ ] CHK040 - Is the assumption "Helper-agent capability mapping and prompt policy ship as defaults baked into this release" tied to a concrete artifact in the repo or in the daemon, or is it a verbal commitment? [Assumption, Spec §Out of Scope]
- [ ] CHK041 - Is the assumption "Project = repository (one-to-one)" reconciled with the Edge Case "Spec or OpenSpec doc paths recorded on a feature have moved or been deleted" (which implies the app must tolerate repo-internal path movement)? [Assumption, Spec §Assumptions / Edge Cases]
- [ ] CHK042 - Is the assumption that document discovery follows conventional paths (`docs/product-requirements.md`, `docs/architecture.md`, `docs/mvp-feature-sequence.md`) reflected in a functional requirement, or only in Assumptions? [Assumption, Gap, Spec §Assumptions / §FR-038]
- [ ] CHK043 - Is the dependency on the daemon's "safe prompt queue" (FEAT-009) restated in functional requirements (FR-043), or only in Assumptions, so an implementer knows it is normative? [Dependencies, Spec §FR-043 / Assumptions]

### Ambiguities & Conflicts

- [ ] CHK044 - Does FR-024 ("suitable for a small concurrent project count (~5 or fewer)") create an ambiguity with FR-076 / FR-077 (project removal + first-launch fallback) — what does the app do once an operator has added or inferred more than ~5 projects? Is "~5 or fewer" a guidance or a hard ceiling? [Ambiguity, Spec §FR-024 / §FR-076 / §FR-077]
- [ ] CHK045 - Does FR-008 (notifications come from daemon-side events classified as notifications) leave the classification rule itself ambiguous — is it a daemon-side responsibility entirely, an app-side overlay, or both? [Ambiguity, Spec §FR-008 / §FR-057]
- [ ] CHK046 - Does the spec resolve the apparent tension between FR-027 ("recent activity on that feature/change") and FR-080 ("event-style streams MUST always surface 'Jump to most recent'") — i.e. is "recent activity" itself a virtualized list or a summary card? [Ambiguity, Spec §FR-027 / §FR-080]
- [ ] CHK047 - Does FR-058 ("OS-native notification integration MUST be opt-in") conflict with US6 §5 ("with the setting disabled, only the in-app surface is used") on first-launch default — is the toggle's default state explicitly off in Settings? [Ambiguity, Spec §FR-058 / US6 §5]
- [ ] CHK048 - Does FR-072(c) "submission allowed, held submitted until reconnection" leave the operator with any visible indicator besides the offline-master state — e.g. a banner on the handoff list view, or only on the handoff detail surface? [Ambiguity, Spec §FR-072]
- [ ] CHK049 - Does FR-081 (supersede does not auto-cancel) name any specific user-facing affordance to surface "the prior master still has running rows" so an operator does not assume supersede stopped the prior work? [Ambiguity, Gap, Spec §FR-081]
- [ ] CHK050 - Is there a single canonical glossary anywhere in the spec for terms used cross-section (master, driving, runtime, surface, attention, notification, handoff, drift, validation entrypoint, master-class capability), or does each section reintroduce the term in its own words? [Ambiguity, Gap, Spec §Key Entities]
