# UX Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that operator-facing UX requirements are complete, clear, consistent, and measurable for the surfaces this feature touches in the control panel.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [ ] CHK001 Are control-panel UI requirements specified for the layout-creation entry point (modal, wizard, inline action)? [Gap]
- [ ] CHK002 Are visual requirements specified for distinguishing managed vs adopted agents in agent lists? [Completeness, Spec §FR-005]
- [ ] CHK003 Are progress-feedback requirements specified for the up-to-2-minute layout creation duration? [Gap, Spec §SC-001]
- [ ] CHK004 Are visual representations defined for each managed-pane lifecycle state (`creating`, `ready`, `degraded`, `failed`, `removed`)? [Completeness, Spec §FR-007]
- [ ] CHK005 Is the visual treatment for "managed/adopted origin" (SC-002) specified (badge, icon, label, color)? [Clarity, Spec §SC-002]
- [ ] CHK006 Are operator-facing diagnostic UI requirements specified for FR-013's "failed pane, failed stage, suggested recovery action"? [Completeness, Spec §FR-013]
- [ ] CHK007 Is the UI for the predecessor → recreated linkage defined (how the operator sees the chain)? [Gap, Spec §FR-011]
- [ ] CHK008 Are confirmation/affirmation UI requirements specified for destructive lifecycle actions (remove, recreate)? [Gap, Spec §FR-010]
- [ ] CHK009 Are visual cues defined for `managed_session_name_conflict` and other error conditions surfaced to the operator? [Gap, Spec §FR-016]
- [ ] CHK010 Is the surface for the audit/history view (FR-021 indefinite retention) defined or scoped out? [Gap, Spec §FR-021]
- [ ] CHK011 Is the input shape for "provide or select configured launch commands" (FR-002) defined (free-text, dropdown, hybrid)? [Clarity, Spec §FR-002]

## Requirement Clarity

- [ ] CHK012 Are the visual treatments for `degraded` and `failed` distinct enough to be unambiguous at a glance? [Clarity, Spec §FR-007]
- [ ] CHK013 Are visual hierarchy requirements specified for the relative importance of layouts vs panes vs agents in the same view? [Gap]
- [ ] CHK014 Are operator-facing copy/wording requirements specified to keep the canonical term "operator" across all UI strings? [Consistency, Spec §Clarifications]
- [ ] CHK015 Is the UI behavior defined during the "second request waits" path of FR-019 serialization (spinner, queue position, estimated wait)? [Gap, Spec §FR-019]

## Requirement Consistency

- [ ] CHK016 Are UI requirements for managed-vs-adopted distinction consistent across agent lists, routes, queues, and events views (FR-008)? [Consistency, Spec §FR-008]
- [ ] CHK017 Are confirmation-prompt UI requirements consistent between remove and recreate flows (FR-010, FR-011)? [Consistency]

## Scenario Coverage

- [ ] CHK018 Are loading/empty-state UI requirements specified for the layout list when no managed layouts exist? [Coverage, Gap]
- [ ] CHK019 Are UI requirements specified for the Recovery Flow when an operator returns to a partially-failed layout? [Coverage, Gap, Spec §FR-013]
- [ ] CHK020 Are UI requirements specified for the daemon-restart recovery scenario (operator notification, transparent reattach, or both)? [Coverage, Gap, Spec §SC-008]
- [ ] CHK021 Are UI requirements specified for the Exception Flow when the bench container disappears mid-creation? [Coverage, Gap, Spec §Edge Cases]

## Edge Case Coverage

- [ ] CHK022 Are UI requirements specified for surfacing a pending-managed pane to the operator before registration completes? [Gap, Spec §FR-014]
- [ ] CHK023 Are UI requirements specified for the case where an operator attempts a destructive action on an adopted pane (FR-012)? [Gap, Spec §FR-012]

## Non-Functional UX

- [ ] CHK024 Are responsive/breakpoint requirements defined for the control panel surfaces this feature affects? [Gap]
- [ ] CHK025 Are perceived-performance requirements specified for stages within the SC-001 2-minute budget (e.g., first feedback within X seconds)? [Gap, Spec §SC-001]
