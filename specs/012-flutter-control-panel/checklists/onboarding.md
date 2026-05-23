# Onboarding Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate first-launch onboarding requirements (FR-010, FR-066/FR-075/FR-076 interplay, SC-001, SC-011, Q24 clarification) for clarity, completeness, consistency, scenario coverage, and measurability. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: Eight-step onboarding flow, skip behavior, Dashboard nudges, milestone persistence, time budget (SC-001), completion-rate measurement (SC-011), re-entry from Settings.

## Milestone Definition (FR-010)

- [ ] CHK001 - Are the eight onboarding milestones (daemon reachable, bench container check, pane discovery check, first pane adoption, first agent registration, first log attachment, first direct send, first route creation) each defined with an automatically-detectable completion criterion the app can observe? [Completeness, Spec §FR-010]
- [ ] CHK002 - Are the milestones' acceptable completion paths defined when the operator completes the action outside onboarding (e.g. adopts a pane from the Panes view before onboarding's adoption step)? [Coverage, Gap, Spec §FR-010]
- [ ] CHK003 - Are requirements present for a milestone being marked complete via "explicit operator confirmation" vs "system-detected event" (e.g. is the "bench container check" complete when the daemon reports ≥1 container, or when the operator clicks "Continue")? [Clarity, Spec §FR-010]
- [ ] CHK004 - Are the milestones ordered as a strict prerequisite chain (can a later milestone be reached without the prior), or as a recommended sequence? [Clarity, Spec §FR-010]

## Skip Behavior (Q24 Clarification — Option C)

- [ ] CHK005 - Does FR-010 specify the placement and copy of the "Skip onboarding" affordance — on every step or only on the first? [Clarity, Spec §FR-010]
- [ ] CHK006 - Are requirements present for what data is captured on skip (which step was skipped, did the operator complete partial input)? [Coverage, Gap, Spec §FR-010]
- [ ] CHK007 - Are requirements present for the Dashboard nudge surfaces — one nudge per incomplete milestone, or a single rolled-up "complete setup" nudge? [Clarity, Spec §FR-010]
- [ ] CHK008 - Are requirements present for nudge dismissibility — can the operator dismiss a nudge without completing the underlying milestone? Does dismissal persist? [Coverage, Gap, Spec §FR-010]
- [ ] CHK009 - Are requirements present for nudge visual prominence relative to the FR-012 recommended-next-action tile (per ux.md CHK044)? [Consistency, Spec §FR-010 / §FR-012]

## Resume from Settings

- [ ] CHK010 - Is the re-entry path documented (per Q24 Recommended discussed alternative B) — does Settings expose a "Show onboarding again" affordance regardless of which option was chosen? [Coverage, Gap, Spec §FR-010]
- [ ] CHK011 - Are requirements present for what happens on re-entry when some milestones are already complete (do they show as checked? skip to first incomplete? offer "redo")? [Coverage, Gap, Spec §FR-010]

## Milestone Persistence (FR-010, FR-069)

- [ ] CHK012 - Is "per-milestone completion state MUST be persisted" (FR-010) reconciled with the FR-069 persistence enumeration — is onboarding state explicitly in the persisted set? [Consistency, Spec §FR-010 / §FR-069]
- [ ] CHK013 - Are requirements present for whether onboarding state persists across "compatible app launches" (FR-070) the same way other UX state does, or is it always retained even after major-version upgrade? [Coverage, Gap, Spec §FR-070 / §FR-010]

## Empty / Degraded States During Onboarding

- [ ] CHK014 - Are requirements present for onboarding behavior when the daemon is unreachable at the "daemon reachable check" step (does it block, retry, or surface diagnostics)? [Coverage, Spec §FR-010 / Edge Cases]
- [ ] CHK015 - Are requirements present for onboarding behavior when no bench container exists (the "bench container check" step) — does it surface a helpful explanation or block? [Coverage, Gap, Spec §FR-010 / Edge Cases]
- [ ] CHK016 - Are requirements present for onboarding behavior when no pane is discovered (the "pane discovery check" step)? [Coverage, Gap, Spec §FR-010 / Edge Cases]
- [ ] CHK017 - Are requirements present for onboarding behavior on contract-version mismatch (FR-002) at any step? [Coverage, Gap, Spec §FR-002 / §FR-010]

## Time Budget (SC-001)

- [ ] CHK018 - Does SC-001 ("under 10 minutes from launch to fully adopted-and-operating agent") specify the included scope (does it include the doctor / preflight, OR only the eight milestones)? [Clarity, Spec §SC-001]
- [ ] CHK019 - Is SC-001 reconciled with FR-062's 2-second Dashboard budget — is the 10 minutes wall-clock or active-time? [Consistency, Spec §FR-062 / §SC-001]

## Completion-Rate Measurement (SC-011)

- [ ] CHK020 - Does SC-011 ("≥90% step completion rate") specify the denominator — operators who started onboarding, operators who launched the app at least once, or a defined cohort? [Clarity, Spec §SC-011 / Assumptions]
- [ ] CHK021 - Is SC-011 reconciled with Q24's skip behavior — are skipped steps counted as not-completed, completed-via-nudge-eventually, or excluded? [Consistency, Spec §SC-011 / §Clarifications Q24]
- [ ] CHK022 - Are requirements present for the data-collection method for SC-011 (telemetry would violate FR-074; is it a manual survey instead)? [Coverage, Gap, Spec §SC-011 / §FR-074]

## Survey-Based Success Criteria (SC-012)

- [ ] CHK023 - Does SC-012 ("≥90% can identify which agent is driving which feature from card-level info alone") tie to the same cohort definition as SC-011, and is the survey instrument named? [Consistency, Spec §SC-011 / §SC-012 / Assumptions]

## Internationalization & Accessibility of Onboarding

- [ ] CHK024 - Are requirements present for routing onboarding strings through the FR-067 i18n layer? [Consistency, Spec §FR-010 / §FR-067]
- [ ] CHK025 - Are requirements present for onboarding's keyboard-only completability (FR-075)? [Consistency, Spec §FR-010 / §FR-075]
- [ ] CHK026 - Are requirements present for onboarding meeting FR-066 a11y baseline at each step (focus order, contrast)? [Consistency, Spec §FR-010 / §FR-066]

## Trust-Model First-Launch Statement (FR-061)

- [ ] CHK027 - Is the FR-061 trust-model first-launch statement placed within onboarding (as a step) or shown separately as a one-time modal? [Clarity, Spec §FR-010 / §FR-061]
- [ ] CHK028 - Are requirements present for whether the operator must acknowledge the trust-model statement before proceeding past the first step? [Coverage, Gap, Spec §FR-061]

## Scenario Class Coverage (Onboarding)

- [ ] CHK029 - Are Primary-flow onboarding requirements complete enough to ship the SC-001 measurable outcome? [Coverage, Spec §FR-010 / §SC-001]
- [ ] CHK030 - Are Alternate-flow onboarding requirements present (operator completes some steps out of order, operator opens app a second time mid-onboarding)? [Coverage, Gap, Spec §FR-010]
- [ ] CHK031 - Are Exception-flow onboarding requirements present (daemon goes unreachable mid-onboarding, contract version mismatch during onboarding)? [Coverage, Gap, Spec §FR-010 / Edge Cases]
- [ ] CHK032 - Are Recovery-flow onboarding requirements present (operator skipped, came back, continued from a Dashboard nudge)? [Coverage, Spec §FR-010]

## Measurability

- [ ] CHK033 - Can each milestone's completion criterion be objectively verified by an automated test? [Measurability, Spec §FR-010]
- [ ] CHK034 - Can SC-001's 10-minute budget be measured deterministically in an internal scripted run? [Measurability, Spec §SC-001]
- [ ] CHK035 - Can SC-011's ≥90% completion rate be measured without telemetry (e.g. via post-onboarding self-report)? [Measurability, Spec §SC-011 / §FR-074]

## Ambiguities

- [ ] CHK036 - Is there an ambiguity about whether onboarding's "first route creation" milestone requires the route to also have produced a successful match, or only existence of the route? [Ambiguity, Gap, Spec §FR-010]
- [ ] CHK037 - Is there an ambiguity about whether dismissed-but-incomplete nudges (CHK008) still count as "skipped" for SC-011's denominator? [Ambiguity, Spec §FR-010 / §SC-011]
