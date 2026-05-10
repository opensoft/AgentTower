# FEAT-007 Carry-Over Integration Requirements Checklist: Event Ingestion, Classification, and Follow CLI

**Purpose**: Validate that the FEAT-007 carry-over obligations (T175/T176/T177, file-change classification, no-replay invariant, lifecycle separation) are complete, clear, consistent, and measurable. This checklist tests the **requirements writing**, not the implementation.
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)
**Depth**: Formal release gate

## Requirement Completeness

- [ ] CHK001 Are integration test deliverables (T175 truncation, T176 recreation, T177 missing→recreated→re-attach) explicitly required as in-scope for FEAT-008? [Completeness, Spec §FR-043]
- [ ] CHK002 Is the "no-replay invariant" defined precisely enough to be the form of an assertion (e.g., "no event whose `byte_range_start` is below the post-reset offset")? [Completeness, Spec §FR-043]
- [ ] CHK003 Is the requirement to call `reader_cycle_offset_recovery` "exactly once per cycle BEFORE reading bytes" testable at the unit level (call-count assertion)? [Completeness, Spec §FR-002, FR-041]
- [ ] CHK004 Are FR-004's prohibitions on production use of `advance_offset_for_test` enforced by an existing AST gate that this feature must continue to pass? [Completeness, Spec §FR-004, SC-008]
- [ ] CHK005 Are requirements covering the file-change classifier obligation (`detect_file_change`) explicit about the prohibition on re-implementation? [Completeness, Spec §FR-042]
- [ ] CHK006 Is the dispatcher mapping (`unchanged | truncated | recreated | missing | reappeared`) referenced in the FEAT-008 reader requirements as the canonical taxonomy? [Completeness, Spec §FR-002, FR-041]
- [ ] CHK007 Is the optional consolidated lifecycle-surface assertion (FR-044) defined with a clear scope vs the dedicated per-class FEAT-007 tests it consolidates? [Completeness, Spec §FR-044]
- [ ] CHK008 Are requirements defined for the audit-row append (`log_attachment_change`) idempotence under retry? [Completeness, Gap]

## Requirement Clarity

- [ ] CHK009 Is "≤ 1 reader cycle (≤ 1 s wall-clock at MVP scale)" measurable with a deterministic injected test clock (no real-time sleeps in tests)? [Clarity, Spec §FR-043]
- [ ] CHK010 Is "no durable event whose excerpt comes from pre-reset bytes" precisely defined for the truncate-then-write-same-bytes case (excerpt-content vs source-byte-range distinction)? [Clarity, Spec §FR-043, US4 AS1]
- [ ] CHK011 Is "operator-explicit re-attach" distinguished from automatic recovery in the requirements (which path applies in which scenario)? [Clarity, Spec §US4 AS5]
- [ ] CHK012 Is "delegating to `reader_cycle_offset_recovery`" in FR-023 specific enough to prevent the reader from inlining or duplicating the helper's logic? [Ambiguity, Spec §FR-023]

## Requirement Consistency

- [ ] CHK013 Does FR-041's helper-ownership claim agree with FR-003's prohibition on direct `log_attachments` / `log_offsets` row mutation? [Consistency, Spec §FR-003, FR-041]
- [ ] CHK014 Are the row-status transitions referenced in US4 AS3/AS4 consistent with FEAT-007's documented `active → stale → active` state machine? [Consistency, Spec §US4]
- [ ] CHK015 Is the `log_rotation_detected` / `log_file_missing` / `log_file_returned` lifecycle separation in FR-026 consistent with US4's per-scenario "exactly one" emission counts? [Consistency, Spec §FR-026, US4]
- [ ] CHK016 Is the "(suppression-keyed by `(agent_id, log_path, file_inode)`)" rule in US4 AS4 consistent with FEAT-007's documented suppression key shape (FR-061 reference)? [Consistency, Spec §US4 AS4, FR-041]

## Acceptance Criteria Quality

- [ ] CHK017 Is SC-004's "T175 promoted to FEAT-008 integration coverage" tied to a specific test-file path or naming convention so it can be located? [Measurability, Spec §SC-004]
- [ ] CHK018 Is SC-006's "100 runs of the integration test" reproducibility assured by a documented seed, clock-injection, or fixed-fixture strategy? [Measurability, Spec §SC-006]
- [ ] CHK019 Are timing assertions for ≤ 1 reader cycle measurable without flakiness on slow CI runners (e.g., logical-clock model rather than wall-clock)? [Measurability, Gap]
- [ ] CHK020 Is the assertion "exactly one `log_rotation_detected` lifecycle event" in US4 AS1/AS2 measurable against a deterministic lifecycle-event sink? [Measurability, Spec §US4 AS1, AS2]

## Scenario Coverage

- [ ] CHK021 Is the "missing→reappear→re-attach" round-trip required to be covered as a single end-to-end test, not three independent tests? [Coverage, Spec §FR-043, US4 AS5]
- [ ] CHK022 Are requirements specified for a reader that observes RECREATED in the same cycle as a pending event from the previous (now-truncated) inode? [Coverage, Gap]
- [ ] CHK023 Are requirements specified for the case where re-attach succeeds but the file is missing again before the next cycle? [Coverage, Gap]
- [ ] CHK024 Is the deletion → permanent-missing case (no recreation) covered by separate requirements from deletion → recreation? [Coverage, Spec §US4 AS3, AS4]
- [ ] CHK025 Are requirements defined for the no-replay invariant under ALL four file-change kinds (truncated, recreated, missing, reappeared), not just truncated/recreated? [Coverage, Spec §FR-043]

## Edge Case Coverage

- [ ] CHK026 Is the case "inode reuse within a short window" (OS-level inode recycling) addressed by the file-change classifier requirements? [Edge Case, Gap]
- [ ] CHK027 Is the case "file size returns to identical pre-truncate value with new bytes" (size-only check would miss this) addressed? [Edge Case, Gap]
- [ ] CHK028 Is the case "MISSING followed by REAPPEARED in adjacent cycles before any operator action" required to emit no durable event? [Edge Case, Spec §Edge Cases]
- [ ] CHK029 Is `log_file_returned` suppression-keyed by `(agent_id, log_path, file_inode)` enforced for the duration of a single stale period (does the same key fire again across stale → active → stale cycles)? [Edge Case, Spec §US4 AS4]
- [ ] CHK030 Are requirements defined for the case where FEAT-007 and FEAT-008 disagree on the row's expected state at cycle entry (defensive read)? [Edge Case, Gap]

## Non-Functional Requirements

- [ ] CHK031 Is the test-runtime budget for the round-trip integration tests bounded (so SC-006's 100 runs is feasible on CI)? [NFR, Gap]
- [ ] CHK032 Are flake-rate budgets for SC-006's 100 runs documented (e.g., 0% flake target)? [NFR, Gap]

## Dependencies & Assumptions

- [ ] CHK033 Is the version-pin of FEAT-007's `reader_recovery` API surface documented (so a FEAT-007 patch cannot silently change FEAT-008 behavior)? [Dependency, Spec §FR-041]
- [ ] CHK034 Is the assumption that FEAT-007 lifecycle suppression (FR-061 reference) is in place documented as an explicit precondition? [Assumption, Spec §FR-041]
- [ ] CHK035 Is the dependency on FEAT-007's audit-row append idempotence documented? [Dependency, Gap]

## Ambiguities & Conflicts

- [ ] CHK036 Could FR-044's "MAY add a single integration test" leave the FR-026 lifecycle-separation requirement under-tested if the feature opts not to add the test? [Conflict, Spec §FR-026, FR-044]
- [ ] CHK037 Is "the same byte sequence appears twice in distinct cycles" (Edge Cases) the same scenario as US3 AS2, or a different scenario? [Ambiguity, Spec §Edge Cases, US3 AS2]
- [ ] CHK038 Is FR-018's "if the same pane id reappears later... it counts as a new lifecycle once the attachment is re-bound" precisely defined in terms of which event triggers the new lifecycle counter? [Ambiguity, Spec §FR-018]
- [ ] CHK039 Is "at most one reader cycle" (US4 AS1/AS2) consistent with the sometimes-stricter "one reader cycle" used elsewhere (US4 AS3, AS4)? [Ambiguity, Spec §US4]
- [ ] CHK040 Is the FR-043 "no-replay invariant" requirement scoped to the test suite alone, or also a normative reader-behavior requirement (would the bug be caught outside the named tests)? [Ambiguity, Spec §FR-043]
