# API Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that the daemon socket API contract requirements for managed-layout operations are complete, clear, consistent, and measurable.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [ ] CHK001 Are request/response schemas specified for the create-layout operation? [Gap, Spec §FR-001]
- [ ] CHK002 Are request/response schemas specified for the remove-managed-pane operation? [Gap, Spec §FR-010]
- [ ] CHK003 Are request/response schemas specified for the recreate-managed-pane operation? [Gap, Spec §FR-011]
- [ ] CHK004 Are request/response schemas specified for listing managed layouts and managed panes? [Gap, Spec §FR-005]
- [ ] CHK005 Is the structured error response specified for `SESSION_NAME_CONFLICT` (code, message, hint)? [Gap, Spec §FR-016]
- [ ] CHK006 Are error response codes/strings enumerated for every failure mode listed in FR-013 and FR-016? [Completeness]
- [ ] CHK007 Is the contract for the lifecycle event stream defined (event types, payload shape, ordering)? [Gap, Spec §FR-015]
- [ ] CHK008 Are API versioning requirements specified for the new managed-layout operations? [Gap]
- [ ] CHK009 Is the API contract for cancellation of an in-flight create-layout defined? [Gap, Scenario Coverage]
- [ ] CHK010 Is the contract for re-attaching to surviving panes after daemon restart specified (operator-driven, automatic, hybrid)? [Gap, Spec §FR-020]
- [ ] CHK011 Are pagination/filtering requirements specified for layout listing and event listing? [Gap]
- [ ] CHK012 Is the contract for the predecessor_id linkage queryable through the API (e.g., GET predecessor chain)? [Gap, Spec §FR-011]
- [ ] CHK013 Are the contract requirements specified for the `promoted_from_adopted` transition stub (e.g., not-implemented response in MVP)? [Gap, Spec §FR-007]

## Requirement Clarity

- [ ] CHK014 Is idempotency-key behavior defined for create-layout (header name, scope, lifetime)? [Clarity, Spec §FR-014]
- [ ] CHK015 Is the contract behavior under FR-019 serialization defined (block-and-wait, queue-and-poll, immediate-reject-with-retry-after)? [Clarity, Spec §FR-019]
- [ ] CHK016 Is the pending-managed-marker visibility specified for API consumers (part of the pane resource, separate field, hidden)? [Clarity, Gap, Spec §FR-014]
- [ ] CHK017 Are timing/SLA requirements specified for API responses (synchronous vs async create-layout)? [Clarity, Gap, Spec §SC-001]
- [ ] CHK018 Are the API authentication/identification requirements specified or explicitly absent for MVP? [Clarity, Spec §Assumptions]

## Requirement Consistency

- [ ] CHK019 Are the contracts consistent between thin client → daemon and app → daemon for the same operations? [Consistency, Spec §FR-017]
- [ ] CHK020 Are the contracts for distinguishing managed vs adopted agents specified consistently across endpoints (FR-005)? [Consistency]
- [ ] CHK021 Are deprecation/migration requirements specified should any FEAT-011 contract surface change? [Gap]

## Scenario Coverage

- [ ] CHK022 Is the contract behavior defined for the bench-container disappearance edge case (long-poll error, immediate failure, retry-after)? [Coverage, Gap, Spec §Edge Cases]
- [ ] CHK023 Are concurrent-request semantics specified for non-create operations (remove, recreate) in addition to create-layout? [Coverage, Spec §FR-019]
- [ ] CHK024 Is the contract for surfacing the `degraded` reason (which subsystem degraded: log, command, registration) specified? [Coverage, Gap, Spec §FR-013]

## Edge Case Coverage

- [ ] CHK025 Is the contract behavior specified when the operator retries with the same idempotency key but different inputs? [Gap, Spec §FR-014]
- [ ] CHK026 Is the contract behavior specified for remove of a pane that is currently in `creating` state? [Gap]
- [ ] CHK027 Is the contract behavior specified for recreate of a pane whose predecessor record is missing (e.g., pruned in a future version)? [Gap, Spec §FR-021]

## Non-Functional API

- [ ] CHK028 Are response-size or pagination requirements specified for high-volume audit/event queries (FR-021 indefinite retention)? [Gap]
- [ ] CHK029 Are observability requirements specified for the API contract (request-id propagation, log fields)? [Gap, Cross-ref: observability.md]
