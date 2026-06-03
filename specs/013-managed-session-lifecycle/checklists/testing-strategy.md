# Testing Strategy Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that the requirements themselves are testable — i.e., that every FR/SC/edge case can be exercised by a test without requiring implementation-level inspection.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Traceability

- [x] CHK001 Is every FR (FR-001..FR-021) testable by at least one acceptance scenario or success criterion? [Traceability]
- [x] CHK002 Is every clarification (Session 2026-05-24 Q1–Q15) covered by at least one acceptance scenario, FR, or SC such that a test can verify the chosen option was applied? [Traceability]

## Observability for Tests

- [x] CHK003 Are the testability requirements specified for the FR-019 per-container serialization (how does a test observe that the second request waited)? [Measurability, Spec §FR-019]
- [x] CHK004 Are the testability requirements specified for the pending-managed marker (how does a test observe it being set and cleared)? [Measurability, Spec §FR-014]
- [x] CHK005 Are the testability requirements specified for the recreate predecessor_id linkage (how does a test verify the chain)? [Measurability, Spec §FR-011]
- [x] CHK006 Are the testability requirements specified for the daemon-restart recovery (FR-020/SC-008) without orchestrating a full process restart in every test? [Measurability, Spec §SC-008]

## SC Measurability

- [x] CHK007 Are the testability requirements specified for SC-001's <2min target in CI (with mocks or real bench containers)? [Measurability, Spec §SC-001]
- [x] CHK008 Are the testability requirements specified for SC-003's 10s log-attach-failure visibility? [Measurability, Spec §SC-003]
- [x] CHK009 Are the testability requirements specified for SC-008's reattach-without-operator-intervention? [Measurability, Spec §SC-008]
- [x] CHK010 Are the testability requirements specified for the "label uniqueness within bench container" (FR-003)? [Measurability]

## Negative & Concurrency Tests

- [x] CHK011 Are negative-test requirements specified (operator cannot remove adopted pane, FR-012)? [Coverage, Spec §FR-012]
- [x] CHK012 Are concurrency-test requirements specified (two simultaneous create-layout requests against the same container, FR-019)? [Coverage]
- [x] CHK013 Are race-condition test requirements specified for the scan/creation interaction (FR-014)? [Coverage]

## Failure Injection

- [x] CHK014 Are failure-injection test requirements specified for each Edge Case bullet (tmux kill mid-create, log-path unreadable, daemon restart mid-create, container disappearance)? [Gap, Coverage]
- [x] CHK015 Are test fixtures specified for the bench-container dependency (real container, mock, hybrid)? [Gap]

## Scope & Boundary

- [x] CHK016 Are integration-test requirements specified for the FEAT-011/012/006/007 interaction touch points? [Coverage, Cross-ref: integration.md]
- [x] CHK017 Are non-regression test requirements specified for the "managed and adopted coexist" guarantee (FR-009)? [Coverage, Spec §FR-009]
- [x] CHK018 Are the test ownership boundaries specified for what FEAT-013 owns vs what FEAT-011/012 own? [Clarity]
- [x] CHK019 Is indefinite audit retention (FR-021) testable without long-running tests (e.g., simulated time, or a test-only sub-policy)? [Measurability, Spec §FR-021]

---

## Walk closure (2026-05-25)

19/19 items resolved by plan.md §Project Structure (tests/contract/ + tests/integration/ + tests/fixtures/ listings) + tasks.md (56 tasks; T015 fixtures, T016-T021 US1 contract+integration tests with TDD ordering, T026-T028 US2, T035-T041 US3, T051 edge cases, T054-T056 perf SLAs) + R5 (5-min TTL testable via managed_clock.py frozen-clock fixture without long-running tests) + R11 (events testable via JSONL inspection; no real time required for SC-007 idempotency replay) + research §R2's threading.Lock + barrier-parallel test pattern (commit ab72150 implementation).
