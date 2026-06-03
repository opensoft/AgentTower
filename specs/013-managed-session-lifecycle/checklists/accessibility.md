# Accessibility Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that accessibility requirements for the operator-facing surfaces touched by this feature are present, complete, and measurable — or explicitly scoped to a sibling feature.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Coverage

- [x] CHK001 Are accessibility requirements explicitly excluded or deferred to FEAT-012 in this spec? [Clarity, Gap]
- [x] CHK002 Are keyboard-navigation requirements specified for the layout-creation flow? [Gap]
- [x] CHK003 Are screen-reader requirements specified for the managed/adopted distinction (FR-005)? [Gap, Spec §FR-005]
- [x] CHK004 Are accessibility requirements specified for the lifecycle-state indicators (`creating`, `ready`, `degraded`, `failed`, `removed`) such that they are perceivable without color alone? [Gap, Spec §FR-007]
- [x] CHK005 Are accessibility requirements specified for the diagnostic surface (FR-013) such that "failed stage" is announced clearly to assistive tech? [Gap, Spec §FR-013]
- [x] CHK006 Are focus-management requirements specified for the confirmation dialogs of remove/recreate (FR-010/FR-011)? [Gap]
- [x] CHK007 Are accessibility requirements specified for the live progress feedback during the up-to-2-min layout creation (live region, polite vs assertive)? [Gap, Spec §SC-001]
- [x] CHK008 Are accessibility requirements specified for surfacing the `predecessor_id` chain or the recreate history? [Gap, Spec §FR-011]
- [x] CHK009 Are accessibility requirements specified for error messages (`managed_session_name_conflict`, daemon unhealthy)? [Gap, Spec §FR-016]
- [x] CHK010 Are accessibility requirements specified for any audit/history view (FR-021 indefinite retention)? [Gap]

## Clarity / Consistency

- [x] CHK011 Are color-contrast requirements specified for `degraded` vs `failed` state indicators so they are distinguishable to users with color-vision deficiency? [Gap, Spec §FR-007]
- [x] CHK012 Are accessibility requirements consistent across managed-pane surfaces and existing adopted-pane surfaces (FR-008)? [Consistency, Spec §FR-008]

## Measurability

- [x] CHK013 Are accessibility requirements stated in objectively-testable form (specific WCAG criteria, role/name/value expectations)? [Measurability]

---

## Walk closure (2026-05-25)

All 13 items deferred to FEAT-012/014 per CHECKLIST_WALK.md (UX/a11y is the control-panel domain; FEAT-013 is server-side only — spec §FR-018 keeps UI out of scope). Spec §Clarifications keep 'operator-facing' wording so when FEAT-012/014 ships, the closed-set lifecycle states (FR-007) and failed_stage enum (FR-013) become the natural anchors for WCAG-aligned visual treatments.
