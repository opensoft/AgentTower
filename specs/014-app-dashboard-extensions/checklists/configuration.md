# Configuration Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for tunable values, defaults, and naming conventions in the v1.1 dashboard contract.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Default Values

- [ ] CHK001 - Is every default value stated as an exact integer or string literal, not a descriptive phrase? [Clarity, Spec §FR-008]
- [ ] CHK002 - Is the default `recently_skipped_window_ms` (`300_000` ms) stated in milliseconds with the underscore-separator convention preserved consistently? [Clarity, Spec §FR-008, §Clarifications Q6]
- [ ] CHK003 - Is the default specified as daemon-side and not client-tunable in v1.1? [Completeness, Spec §FR-008, §Clarifications Q6]
- [x] CHK004 - Is the requirement defined for whether the default may be daemon-config-file tunable (Clarifications Q6 Option D was rejected — confirm the spec actively reflects that rejection)? [Consistency, Spec §FR-008, §Clarifications Q6] [NEEDS-CLARIFY-R2, R2-resolved: Clarifications §Session 2026-05-24-r2 Q1 + FR-022 — pure internal constant]

## Tunability Boundaries

- [ ] CHK005 - Is the absence of a per-request tuning parameter (e.g., a `window_ms` override on `app.dashboard`) stated explicitly, not by omission? [Clarity, Spec §Clarifications Q6]
- [ ] CHK006 - Is the absence of customizable recommendation rules in v1.1 stated explicitly (FR-018 mentions this as out of scope)? [Consistency, Spec §FR-018, §Clarifications]

## Naming Conventions

- [ ] CHK007 - Is the hyphenated naming convention for new closed-set values stated as a contract requirement, not a stylistic preference? [Clarity, Spec §Clarifications Q12]
- [ ] CHK008 - Is the mixing of snake_case (v1.0 closed sets, recommendation codes) with hyphens (v1.1 PaneState/AgentState/log-state) declared deliberate and rationalized? [Consistency, Spec §Clarifications Q12]
- [ ] CHK009 - Are the requirements for the `_ms` suffix on duration fields stated? [Clarity, Spec §FR-007]

## Implicit Constants

- [ ] CHK010 - Are the size caps `title ≤128` and `detail ≤512` declared "configuration" or "contract" (and is that distinction stated)? [Clarity, Spec §FR-011]
- [x] CHK011 - Is there a requirement on how these caps would be raised in a future minor (additive only, or never)? [Gap] [NEEDS-CLARIFY-R2, R2-resolved: spec.md §FR-014 extension — future v1.x MAY raise caps additively]

## Configuration Surface Discipline

- [x] CHK012 - Is the requirement defined that v1.1 introduces zero new configuration surface area to operators (no new env vars, no new config keys)? [Gap] [EDIT-applied: spec.md §FR-022 — no new operator-facing configuration in v1.1]

## Plan & Design Alignment (re-verify 2026-05-24)

- [ ] CHK013 - Does data-model.md §RecentlySkippedRoutesWindow name the constant `window_ms = 300_000` exactly, not just "5 minutes"? [Clarity, Data Model §RecentlySkippedRoutesWindow]
- [ ] CHK014 - Does data-model.md name the constant `maxlen = 10_000` for the ring buffer, sourced from Research §RB? [Clarity, Data Model §RecentlySkippedRoutesWindow, Research §RB]
- [ ] CHK015 - Are these two constants declared "internal daemon constants" (not configurable), rather than "defaults that could become tunable"? [Boundary, Data Model, Research §RB]
- [ ] CHK016 - Does plan.md confirm there is no test-only or debug-only configuration knob that bypasses the FR-021 compute-failure fallback in release builds? [Boundary, Quickstart §Step 6, Plan §Source Code]
