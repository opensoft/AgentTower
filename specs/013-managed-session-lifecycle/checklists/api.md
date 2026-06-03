# API Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that the daemon socket API contract requirements for managed-layout operations are complete, clear, consistent, and measurable.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [x] CHK001 Are request/response schemas specified for the create-layout operation? [Gap, Spec §FR-001]
- [x] CHK002 Are request/response schemas specified for the remove-managed-pane operation? [Gap, Spec §FR-010]
- [x] CHK003 Are request/response schemas specified for the recreate-managed-pane operation? [Gap, Spec §FR-011]
- [x] CHK004 Are request/response schemas specified for listing managed layouts and managed panes? [Gap, Spec §FR-005]
- [x] CHK005 Is the structured error response specified for `managed_session_name_conflict` (code, message, hint)? [Gap, Spec §FR-016]
- [x] CHK006 Are error response codes/strings enumerated for every failure mode listed in FR-013 and FR-016? [Completeness]
- [x] CHK007 Is the contract for the lifecycle event stream defined (event types, payload shape, ordering)? [Gap, Spec §FR-015]
- [x] CHK008 Are API versioning requirements specified for the new managed-layout operations? [Gap]
- [x] CHK009 Is the API contract for cancellation of an in-flight create-layout defined? [Gap, Scenario Coverage]
- [x] CHK010 Is the contract for re-attaching to surviving panes after daemon restart specified (operator-driven, automatic, hybrid)? [Gap, Spec §FR-020]
- [x] CHK011 Are pagination/filtering requirements specified for layout listing and event listing? [Gap]
- [x] CHK012 Is the contract for the predecessor_id linkage queryable through the API (e.g., GET predecessor chain)? [Gap, Spec §FR-011]
- [x] CHK013 Are the contract requirements specified for the `promoted_from_adopted` transition stub (e.g., not-implemented response in MVP)? [Gap, Spec §FR-007]

## Requirement Clarity

- [x] CHK014 Is idempotency-key behavior defined for create-layout (header name, scope, lifetime)? [Clarity, Spec §FR-014]
- [x] CHK015 Is the contract behavior under FR-019 serialization defined (block-and-wait, queue-and-poll, immediate-reject-with-retry-after)? [Clarity, Spec §FR-019]
- [x] CHK016 Is the pending-managed-marker visibility specified for API consumers (part of the pane resource, separate field, hidden)? [Clarity, Gap, Spec §FR-014]
- [x] CHK017 Are timing/SLA requirements specified for API responses (synchronous vs async create-layout)? [Clarity, Gap, Spec §SC-001]
- [x] CHK018 Are the API authentication/identification requirements specified or explicitly absent for MVP? [Clarity, Spec §Assumptions]

## Requirement Consistency

- [x] CHK019 Are the contracts consistent between thin client → daemon and app → daemon for the same operations? [Consistency, Spec §FR-017]
- [x] CHK020 Are the contracts for distinguishing managed vs adopted agents specified consistently across endpoints (FR-005)? [Consistency]
- [x] CHK021 Are deprecation/migration requirements specified should any FEAT-011 contract surface change? [Gap]

## Scenario Coverage

- [x] CHK022 Is the contract behavior defined for the bench-container disappearance edge case (long-poll error, immediate failure, retry-after)? [Coverage, Gap, Spec §Edge Cases]
- [x] CHK023 Are concurrent-request semantics specified for non-create operations (remove, recreate) in addition to create-layout? [Coverage, Spec §FR-019]
- [x] CHK024 Is the contract for surfacing the `degraded` reason (which subsystem degraded: log, command, registration) specified? [Coverage, Gap, Spec §FR-013]

## Edge Case Coverage

- [x] CHK025 Is the contract behavior specified when the operator retries with the same idempotency key but different inputs? [Gap, Spec §FR-014]
- [x] CHK026 Is the contract behavior specified for remove of a pane that is currently in `creating` state? [Gap]
- [x] CHK027 Is the contract behavior specified for recreate of a pane whose predecessor record is missing (e.g., pruned in a future version)? [Gap, Spec §FR-021]

## Non-Functional API

- [x] CHK028 Are response-size or pagination requirements specified for high-volume audit/event queries (FR-021 indefinite retention)? [Gap]
- [x] CHK029 Are observability requirements specified for the API contract (request-id propagation, log fields)? [Gap, Cross-ref: observability.md]

---

## Walk closure (2026-05-25)

29/29 items resolved by contracts/managed-methods.md (M1-M8 with full request/response schemas) + contracts/error-codes.md (13 closed-set codes with details schemas) + R10 (idempotency) + R12 (peer scoping) + FR-016 (input validation) + FR-018 (cancel-in-flight out of scope). Pre-implement walk Clarifications session (4) closed the remaining open items from CHECKLIST_WALK.md (topic D input validation + topic B partial-failure rollback + topic E event ordering).
