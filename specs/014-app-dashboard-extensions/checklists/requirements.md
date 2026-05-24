# Specification Quality Checklist: App Dashboard Extensions

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

- Initial validation passed for `/speckit.clarify` and `/speckit.plan`.

---

# Cross-Cutting Requirements Quality Audit

**Purpose**: Release-gate quality audit of the spec's requirement *statements themselves* — does the English read like well-written code?
**Appended**: 2026-05-24
**Mode**: max-coverage re-verify (`/speckit-checklist` no-arg default, invoked as `reverify we are full coverage and max depth`)
**Feature**: [spec.md](../spec.md)

This section uses the "unit tests for English" framing: every item asks whether a requirement statement in `spec.md` is complete, unambiguous, consistent, measurable, traceable, or properly bounded. It does NOT test implementation behavior.

## Completeness

- [ ] CHK001 - Are requirements present for every v1.1 field listed in the Clarifications section's RecommendedNextAction shape? [Completeness, Spec §FR-011, §Clarifications]
- [ ] CHK002 - Is every closed-set value the spec relies on (`PaneState`, `AgentState`, recommendation `code`, `target.kind`, container `state`) enumerated in the spec or in a referenced contract document? [Completeness, Spec §FR-002, §FR-005, §FR-010, §FR-011]
- [ ] CHK003 - Are requirements present for the daemon-side default value of every tunable-looking field (e.g., `recently_skipped_window_ms`, recommendation cache TTL)? [Completeness, Spec §FR-008]
- [ ] CHK004 - Are requirements present for the *absence* of behavior that v1.0 had but v1.1 must NOT change (fields, methods, error codes, capability flags)? [Completeness, Spec §FR-014, §FR-015]
- [x] CHK005 - Are requirements present for the failure mode of every newly added field, not only the happy path? [Completeness, Spec §FR-021, §Clarifications] [NEEDS-CLARIFY-R1, R1-resolved: spec.md §FR-025]

## Clarity

- [ ] CHK006 - Is every adjective in the spec ("active", "stale", "degraded", "recent", "partial", "additive") explicitly defined or traced to a closed-set definition? [Clarity, Spec §FR-002, §FR-005]
- [ ] CHK007 - Is "the most recent successful scan" defined unambiguously (what counts as "successful" and which timestamp the comparison uses)? [Ambiguity, Spec §Clarifications Q1]
- [ ] CHK008 - Are size/length caps for string-typed contract fields stated as exact integers, not relative phrases? [Clarity, Spec §FR-011]
- [ ] CHK009 - Is the daemon's clock source for `recently_skipped_window_ms` and `recommended_next_action_refreshed_at` named (monotonic vs wall clock, UTC vs local, precision)? [Ambiguity, Gap]
- [ ] CHK010 - Is "the rest of the dashboard payload still returns success" defined in terms of which fields specifically remain present and well-typed when recommendation computation fails? [Clarity, Spec §FR-021]

## Consistency

- [ ] CHK011 - Do the Clarifications session bullets and the FR text agree on the same canonical phrasing for every closed-set value (hyphens preserved, no synonyms)? [Consistency, Spec §Clarifications Q12, §FR-002, §FR-005]
- [ ] CHK012 - Is the agent-state partition (`active` + `inactive` + `partially_configured`) consistent between Clarifications Q5, FR-020, and Edge Cases? [Consistency, Spec §FR-020, §Clarifications Q5]
- [ ] CHK013 - Are the seven recommendation codes named identically in FR-010, SC-003, the Clarifications precedence note, and US3 acceptance scenarios (same spelling, same order)? [Consistency, Spec §FR-010, §SC-003, §Clarifications, §US3]
- [ ] CHK014 - Is the orthogonality rule for `log-attached`/`log-detached` stated identically in FR-006, FR-020, and Edge Cases? [Consistency, Spec §FR-006, §FR-020]

## Measurability & Acceptance Criteria

- [ ] CHK015 - Can every FR be paired with at least one SC or acceptance scenario that would observably fail if the FR were not implemented? [Acceptance Criteria, Spec §FR-001..§FR-021, §SC-001..§SC-007]
- [ ] CHK016 - Are FR-008's window bounds (`300_000` ms) testable with a single fixture, including the boundary conditions (exactly at the window edge)? [Measurability, Spec §FR-008]
- [ ] CHK017 - Is "Dashboard response latency remains within the existing FEAT-011 dashboard budget" backed by a numeric budget visible in the spec or a clearly referenced document? [Measurability, Spec §SC-006]
- [ ] CHK018 - Are the new FR-019 panes cross-check equalities stated in a form a unit test can assert directly? [Measurability, Spec §FR-019]

## Dependencies & Assumptions

- [ ] CHK019 - Is every cross-feature dependency (FEAT-004, FEAT-006, FEAT-007, FEAT-010, FEAT-011, FEAT-012) named with the specific contract surface this feature consumes from it? [Dependency, Spec §Assumptions, §US-*]
- [ ] CHK020 - Are the assumptions about container state vocabulary (`active`, `inactive`, `degraded_scan`) traceable to an authoritative FEAT-003/004 closed set, not assumed inline? [Assumption, Spec §Clarifications Q1, Q3]
- [ ] CHK021 - Is the assumption that v1.0 clients ignore unknown fields stated as a *consumer-contract* requirement, not just daemon-side intent? [Assumption, Spec §Clarifications Q10, §FR-012, §FR-014]

## Ambiguities & Conflicts

- [x] CHK022 - Are there any FRs that say "as appropriate" or "or no target as appropriate" without enumerating the cases? [Ambiguity, Spec §FR-011] [EDIT-applied: spec.md §FR-011 now incorporates the per-code target rule by reference]
- [x] CHK023 - Does the spec resolve whether `partially_configured` agents are still counted as `registered` for the pane's `discovered-and-registered` bucket (the agent row exists, but configuration is incomplete)? [Conflict, Spec §FR-020, §FR-002] [EDIT-applied: spec.md §FR-019 now states the partially_configured pane carve-out]
- [ ] CHK024 - Is "recomputed on every `app.dashboard` call" reconciled with "fixed-order, deterministic" by an explicit same-input-same-output guarantee, so two concurrent dashboard calls observe identical recommendation output when underlying state is unchanged? [Ambiguity, Spec §Clarifications Q8, §FR-010]

## Plan & Design Alignment (re-verify 2026-05-24)

- [ ] CHK025 - Are FR-019, FR-020, and FR-021 (added during the prior `/speckit-clarify` round) each owned by a specific module in plan.md §Source Code? [Traceability, Plan §Source Code, Spec §FR-019..§FR-021]
- [ ] CHK026 - Is every Clarifications Q-A pair traceable to a research §-section, a plan-stated decision, or a contract-doc clause — with no answer "lost" between artifacts? [Traceability, Spec §Clarifications, Plan + Research]
- [ ] CHK027 - Is Research §FE (WARN log on compute failure) congruent with Constitution Principle IV ("failures should produce actionable output rather than silent degradation")? [Consistency, Research §FE, Constitution Principle IV]
- [ ] CHK028 - Are gaps surfaced by the spec-only checklist suite either resolved by research/plan/data-model/contracts, or explicitly carried forward as named known limitations? [Resolution, Checklists *]
- [ ] CHK029 - Does any plan artifact contradict the spec (introduce a closed-set value not in the spec, change a count cap, redefine a window)? [Consistency, Plan + Research vs Spec]
- [ ] CHK030 - Is the design surface bounded — i.e., plan.md does not silently expand scope beyond what the spec FRs/SCs require? [Boundary, Plan §Source Code, Spec §FR-*]
