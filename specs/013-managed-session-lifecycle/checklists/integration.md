# Integration Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that integration and external-dependency requirements (FEAT-011/012, sibling features, tmux, thin client) are complete, clear, consistent, and measurable.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Dependency Enumeration

- [ ] CHK001 Are the specific FEAT-011 surfaces this feature depends on enumerated (panes, agents, events, routes, queues, health, mutations)? [Completeness, Spec §Assumptions]
- [ ] CHK002 Are the specific FEAT-012 surfaces this feature depends on enumerated (which control-panel views, which mutations)? [Completeness, Spec §Assumptions]
- [ ] CHK003 Are the dependencies on FEAT-003 (bench-container discovery) and FEAT-004 (tmux pane discovery) enumerated? [Gap]
- [ ] CHK004 Are the dependencies on FEAT-006 (agent registration) enumerated (managed-created agents go through the same registration path)? [Gap, Spec §FR-004]
- [ ] CHK005 Are the dependencies on FEAT-007 (log attachment) enumerated (FR-006 reuses this path)? [Gap, Spec §FR-006]
- [ ] CHK006 Are the dependencies on FEAT-009 (safe-prompt-queue) and FEAT-010 (event routes / arbitration) enumerated (FR-008 reuses these)? [Gap, Spec §FR-008]
- [ ] CHK007 Are the tmux contract surfaces specified (which tmux commands are required: new-window, split-window, kill-pane, send-keys, list-panes)? [Gap]

## Contract & Versioning

- [ ] CHK008 Are version compatibility requirements specified for FEAT-011 contracts (semver, schema version)? [Gap]
- [ ] CHK009 Are deprecation/migration requirements specified for any FEAT-011 contract surface that this feature extends? [Gap]
- [ ] CHK010 Are integration requirements specified for the durable storage location (file path, format, owner) used by FR-020? [Gap, Spec §FR-020]
- [ ] CHK011 Are integration boundary requirements specified for the "no remote network listener" constraint (FR-017) — what is the canonical local socket path? [Clarity, Spec §FR-017]

## Failure Surfaces

- [ ] CHK012 Are the failure modes of each dependency's surface enumerated (what does this spec assume the upstream feature handles)? [Coverage, Gap]
- [ ] CHK013 Are integration requirements specified for handling tmux server crashes during layout creation? [Gap, Edge Case]
- [ ] CHK014 Are integration requirements specified for the case where FEAT-006 registration returns success but FEAT-007 log attachment fails (cross-feature partial failure)? [Gap, Coverage]

## Coexistence

- [ ] CHK015 Are integration requirements specified for the "managed and adopted coexist" assertion (FR-009) — what guarantees does FEAT-013 require from FEAT-006 to keep adopted-pane identity stable? [Coverage, Spec §FR-009]
- [ ] CHK016 Are integration requirements specified for the pending-managed marker interaction with FEAT-004 scan? [Coverage, Spec §FR-014]
- [ ] CHK017 Are the integration boundaries with the thin client specified (which managed-layout operations are exposed to in-container clients)? [Gap, Spec §FR-017]

## Consistency

- [ ] CHK018 Are integration requirements consistent across the host daemon and thin client paths (FR-017)? [Consistency]
- [ ] CHK019 Are integration requirements specified for the audit/event store and any external sink (none in MVP, but is this stated explicitly)? [Gap, Spec §FR-017]

## Testability

- [ ] CHK020 Are integration test requirements specified for the FEAT-011/012/006/007 interactions in this feature's scope? [Gap, Cross-ref: testing-strategy.md]
- [ ] CHK021 Are integration test fixtures specified for the bench-container dependency (real container, mock, hybrid)? [Gap]
