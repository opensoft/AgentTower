# Accessibility Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that accessibility requirements for the operator-facing surfaces touched by this feature are present, complete, and measurable — or explicitly scoped to a sibling feature.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Coverage

- [ ] CHK001 Are accessibility requirements explicitly excluded or deferred to FEAT-012 in this spec? [Clarity, Gap]
- [ ] CHK002 Are keyboard-navigation requirements specified for the layout-creation flow? [Gap]
- [ ] CHK003 Are screen-reader requirements specified for the managed/adopted distinction (FR-005)? [Gap, Spec §FR-005]
- [ ] CHK004 Are accessibility requirements specified for the lifecycle-state indicators (`creating`, `ready`, `degraded`, `failed`, `removed`) such that they are perceivable without color alone? [Gap, Spec §FR-007]
- [ ] CHK005 Are accessibility requirements specified for the diagnostic surface (FR-013) such that "failed stage" is announced clearly to assistive tech? [Gap, Spec §FR-013]
- [ ] CHK006 Are focus-management requirements specified for the confirmation dialogs of remove/recreate (FR-010/FR-011)? [Gap]
- [ ] CHK007 Are accessibility requirements specified for the live progress feedback during the up-to-2-min layout creation (live region, polite vs assertive)? [Gap, Spec §SC-001]
- [ ] CHK008 Are accessibility requirements specified for surfacing the `predecessor_id` chain or the recreate history? [Gap, Spec §FR-011]
- [ ] CHK009 Are accessibility requirements specified for error messages (SESSION_NAME_CONFLICT, daemon unhealthy)? [Gap, Spec §FR-016]
- [ ] CHK010 Are accessibility requirements specified for any audit/history view (FR-021 indefinite retention)? [Gap]

## Clarity / Consistency

- [ ] CHK011 Are color-contrast requirements specified for `degraded` vs `failed` state indicators so they are distinguishable to users with color-vision deficiency? [Gap, Spec §FR-007]
- [ ] CHK012 Are accessibility requirements consistent across managed-pane surfaces and existing adopted-pane surfaces (FR-008)? [Consistency, Spec §FR-008]

## Measurability

- [ ] CHK013 Are accessibility requirements stated in objectively-testable form (specific WCAG criteria, role/name/value expectations)? [Measurability]
