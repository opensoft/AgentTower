# Failure Surface & Observability Requirements Checklist: Event Ingestion, Classification, and Follow CLI

**Purpose**: Validate that per-attachment failure isolation, daemon `status` surfacing, and FEAT-007 lifecycle separation requirements are complete, clear, consistent, and measurable. This checklist tests the **requirements writing**, not the implementation.
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)
**Depth**: Formal release gate

## Requirement Completeness

- [ ] CHK001 Are all per-attachment failure classes enumerated (EACCES, ENOENT outside FEAT-007 path, missing offset row, degraded SQLite, degraded JSONL, other I/O)? [Completeness, Spec §FR-038, FR-039]
- [ ] CHK002 Is the `agenttower status` failure-surface schema specified (object shape, field types, required vs optional)? [Completeness, Spec §FR-037, Gap]
- [ ] CHK003 Are requirements defined for which failure classes must ALSO surface as FEAT-007 lifecycle events vs status-only? [Completeness, Spec §FR-037]
- [ ] CHK004 Are requirements defined for clearing a failure indicator after recovery (auto-clear vs operator action)? [Completeness, Spec §FR-040, Gap]
- [ ] CHK005 Is the "degraded condition" object/structure defined consistently for both SQLite (FR-040) and JSONL (FR-029) paths? [Completeness, Spec §FR-029, FR-040]
- [ ] CHK006 Are operator-observable conditions defined for "missing offset row for active attachment" (what does the operator see, where)? [Completeness, Spec §FR-039]
- [ ] CHK007 Are requirements specified for failure-counter, last-seen-at, and first-seen-at metadata in the `status` failure surface? [Completeness, Gap]
- [ ] CHK008 Is the failure-record retention policy defined (does a transient failure remain visible after auto-clear)? [Completeness, Gap]

## Requirement Clarity

- [ ] CHK009 Is "MUST NOT cause loss of the attachment row" measurable as a row-existence assertion across all failure classes? [Clarity, Spec §FR-038]
- [ ] CHK010 Is "the reader skips that attachment for the cycle and surfaces the inconsistency" precisely defined as a test assertion (no offset advance, status visibility within N cycles)? [Clarity, Spec §FR-039]
- [ ] CHK011 Is "visible failure that points to the underlying degraded condition" (US6 AS2) measurable beyond "operator can see something"? [Clarity, Spec §US6 AS2, FR-040]
- [ ] CHK012 Is "diagnostic surface FEAT-007 already uses" (US6 AS1) enumerated to a specific surface, or is the prose abstract? [Ambiguity, Spec §US6 AS1]
- [ ] CHK013 Is "(or an equivalent inspect path)" in FR-037 precise enough to constrain the implementation, or is it a punt to plan-time? [Ambiguity, Spec §FR-037]

## Requirement Consistency

- [ ] CHK014 Are failure-surface requirements consistent across FR-037 (status surface), FR-026 (FEAT-007 lifecycle separation), FR-029, and FR-040 (degraded conditions)? [Consistency, Spec §FR-026, FR-029, FR-037, FR-040]
- [ ] CHK015 Do FR-038 (attachment-row preservation) and FR-039 (skip cycle on missing offset row) align on what constitutes a "lost" vs "skipped" attachment? [Consistency, Spec §FR-038, FR-039]
- [ ] CHK016 Is the FR-026 lifecycle/event separation consistent with FR-044's optional consolidated assertion? [Consistency, Spec §FR-026, FR-044]
- [ ] CHK017 Is FR-040's clarified "buffer + retry + visible status" pattern consistent with US6 AS2's older "(a) retry OR (b) surface failure" wording (post-clarification, both paths apply)? [Consistency, Spec §US6 AS2, FR-040, Clarifications]

## Acceptance Criteria Quality

- [ ] CHK018 Is SC-009's "zero FEAT-007 lifecycle event classes appear in the JSONL events history" measurable against a documented set of FEAT-007 event-type names? [Measurability, Spec §SC-009, FR-026]
- [ ] CHK019 Is SC-010's "100% of test iterations" specified with a concrete iteration count and a documented strategy for inducing the failure? [Measurability, Spec §SC-010]
- [ ] CHK020 Are acceptance criteria defined for the `status` surface response shape (so a script can parse failure details deterministically)? [Acceptance Criteria, Gap]
- [ ] CHK021 Are acceptance criteria defined for failure-to-status-visibility latency (within N reader cycles)? [Acceptance Criteria, Gap]

## Scenario Coverage

- [ ] CHK022 Are requirements defined for one attachment in failure while many others are healthy? [Coverage, Spec §US6 AS1]
- [ ] CHK023 Are requirements defined for ALL attachments in failure simultaneously (e.g., disk full)? [Coverage, Gap]
- [ ] CHK024 Is the case "permission-restored after EACCES" required to clear the failure indicator within a bounded number of cycles? [Coverage, Gap]
- [ ] CHK025 Are requirements specified for failures that occur during the FR-040 buffered-retry path (failure on retry attempt)? [Coverage, Gap]
- [ ] CHK026 Are requirements specified for the case where `status` itself fails to render the failure surface (e.g., daemon-unreachable while degraded)? [Coverage, Gap]

## Edge Case Coverage

- [ ] CHK027 Is the case "offset row exists but `byte_offset` > current file size" addressed as an inconsistency, distinct from truncation? [Edge Case, Gap]
- [ ] CHK028 Is the case "attachment row exists but `log_offsets` row missing AND the file is also missing" handled by exactly one of the failure paths (no double-classification)? [Edge Case, Spec §FR-039]
- [ ] CHK029 Are repeated identical failures required to NOT spam the failure surface or lifecycle log (rate limiting / suppression)? [Edge Case, Gap]
- [ ] CHK030 Is "ENOENT outside the FEAT-007 missing/recreated path" precisely defined (which paths are FEAT-007's scope vs not)? [Edge Case, Spec §FR-038]
- [ ] CHK031 Are requirements defined for the case where the FEAT-007 lifecycle logger itself fails (where does that diagnostic land)? [Edge Case, Gap]

## Non-Functional Requirements

- [ ] CHK032 Are observability-latency requirements specified for failure-to-status-visibility (e.g., visible within K reader cycles, default K=2)? [NFR, Gap]
- [ ] CHK033 Are requirements for failure-message redaction specified (no secret leakage in error text shown via `status`)? [NFR, Spec §FR-012, Gap]
- [ ] CHK034 Are isolation requirements (one-attachment failure must not delay other attachments' cycles by more than X) quantified? [NFR, Spec §FR-036, Gap]

## Dependencies & Assumptions

- [ ] CHK035 Is the dependency on the FEAT-007 lifecycle logger surface version-pinned and stable? [Dependency, Spec §FR-037]
- [ ] CHK036 Is the assumption that `agenttower status` already exists (FEAT-002) documented as a hard precondition? [Assumption, Gap]
- [ ] CHK037 Is the dependency on FEAT-002's daemon-unreachable surface explicit and version-pinned? [Dependency, Spec §FR-034]

## Ambiguities & Conflicts

- [ ] CHK038 Could FR-040's clarified pattern (mandatory buffer + retry + visible status) be misread as the older FR-040 "OR" wording in US6 AS2 if a reader skips the Clarifications section? [Conflict, Spec §US6 AS2, FR-040, Clarifications]
- [ ] CHK039 Is "(or the same diagnostic surface FEAT-007 already uses)" in US6 AS1 a single concrete surface, or is the spec leaving the implementation a choice? [Ambiguity, Spec §US6 AS1]
- [ ] CHK040 Is the boundary between "per-attachment failure" (visible via status) and "daemon degraded condition" (visible globally) precisely defined? [Ambiguity, Spec §FR-037, FR-040]
