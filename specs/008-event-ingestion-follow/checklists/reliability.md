# Reliability & Durability Requirements Checklist: Event Ingestion, Classification, and Follow CLI

**Purpose**: Validate that reliability, durability, restart-resume, and degraded-mode requirements are complete, clear, consistent, and measurable. This checklist tests the **requirements writing**, not the implementation.
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)
**Depth**: Formal release gate

## Requirement Completeness

- [ ] CHK001 Are reader-cycle wall-clock cap requirements quantified for both the documented MVP default and any tighter implementation floor? [Completeness, Spec §FR-001]
- [ ] CHK002 Are atomic-commit boundaries explicitly specified for the SQLite event row + `log_offsets` advance pair? [Completeness, Spec §FR-006]
- [ ] CHK003 Is the JSONL append-after-SQLite ordering requirement documented as a hard sequencing rule, not a recommendation? [Completeness, Spec §FR-006, FR-029]
- [ ] CHK004 Are restart-resume requirements specified for every persisted state element the reader consumes (offsets, audit rows, lifecycle suppression keys)? [Completeness, Spec §FR-020]
- [ ] CHK005 Are duplicate-suppression requirements expressed in terms of byte ranges rather than event identity alone? [Completeness, Spec §FR-021]
- [ ] CHK006 Are bounds defined for the in-flight cycle buffer used by FR-040's degraded-mode retry path? [Completeness, Spec §FR-040]
- [ ] CHK007 Are degraded-mode "clear conditions" defined for both the SQLite path (FR-040) and the JSONL path (FR-029)? [Completeness, Spec §FR-029, FR-040]
- [ ] CHK008 Are requirements defined for what happens to the in-memory degraded-mode buffer if the daemon stops while degraded? [Completeness, Gap]
- [ ] CHK009 Is the watermark used for JSONL retry (FR-029) defined as a persisted artifact or only an in-memory hint? [Completeness, Spec §FR-029]

## Requirement Clarity

- [ ] CHK010 Is "exactly once per cycle BEFORE reading any bytes" measurable with a unit-level assertion (e.g., call-count check)? [Clarity, Spec §FR-002]
- [ ] CHK011 Is "single atomic commit per emitted event (or per cycle batch within a single transaction)" unambiguous about which path the implementer must choose? [Ambiguity, Spec §FR-006]
- [ ] CHK012 Is "monotonically-increasing event_id" defined unambiguously across daemon restarts (sequence preserved? gaps allowed?)? [Clarity, Spec §FR-028, Key Entities]
- [ ] CHK013 Is "byte range begins at or after the persisted byte_offset" precise enough to handle partial-line carry-over scenarios? [Clarity, Spec §FR-021]
- [ ] CHK014 Is FR-040's "buffer the in-flight cycle's classified events in memory" specific about whether the buffer survives a process restart? [Clarity, Spec §FR-040]
- [ ] CHK015 Is "next cycle once the degraded state clears" measurable as a deterministic test condition? [Clarity, Spec §FR-040]

## Requirement Consistency

- [ ] CHK016 Do FR-006 (atomic SQLite+offset commit) and FR-040 (in-memory buffer on degraded SQLite) reconcile when the SQLite write itself is the failure? [Consistency, Spec §FR-006, FR-040]
- [ ] CHK017 Is the restart-resume contract internally consistent across FR-020 (offsets authoritative), FR-022 (JSONL not load-bearing), and FR-023 (delegate to `reader_cycle_offset_recovery`)? [Consistency, Spec §FR-020, FR-022, FR-023]
- [ ] CHK018 Does FR-015 (debounce state does not span restarts) align with FR-021 (no event below persisted byte_offset) when an `activity` debounce window is interrupted by a restart? [Consistency, Spec §FR-014, FR-015, FR-021]
- [ ] CHK019 Does the FR-029 (JSONL degraded retry) pattern match the FR-040 (SQLite degraded retry) pattern in terms of operator-visible signal and clear-condition semantics? [Consistency, Spec §FR-029, FR-040]

## Acceptance Criteria Quality

- [ ] CHK020 Are SC-003's "10 consecutive daemon restarts with no intervening log writes" reproducibility conditions documented (clock injection, deterministic offsets)? [Measurability, Spec §SC-003]
- [ ] CHK021 Are SC-004 and SC-005 distinguishable by test assertion alone (truncation vs recreation)? [Measurability, Spec §SC-004, SC-005]
- [ ] CHK022 Is SC-006's "100% of test iterations across 100 runs" achievable without an explicit randomness/clock-control strategy in the requirements? [Measurability, Spec §SC-006]
- [ ] CHK023 Are observable success criteria defined for FR-040 buffered-retry behavior (e.g., events appear after recovery within N cycles)? [Acceptance Criteria, Gap]

## Scenario Coverage

- [ ] CHK024 Are requirements specified for daemon-stop after byte read but before SQLite commit? [Coverage, Spec §US3 AS2]
- [ ] CHK025 Are requirements specified for daemon-stop mid-batch (some events committed, others not, single transaction model)? [Coverage, Spec §FR-006]
- [ ] CHK026 Are requirements defined for daemon-stop while events are sitting in the FR-040 in-memory degraded buffer? [Coverage, Gap]
- [ ] CHK027 Are requirements specified for the case where SQLite recovers but JSONL is still failing (both degraded paths active simultaneously)? [Coverage, Spec §FR-029, FR-040]

## Edge Case Coverage

- [ ] CHK028 Is the empty-log post-restart case (no bytes appended while down) explicitly required to produce zero events? [Edge Case, Spec §US3 AS1]
- [ ] CHK029 Is the "bytes appended while daemon is down" case explicitly required to NOT replay any pre-restart events? [Edge Case, Spec §US3 AS3]
- [ ] CHK030 Are requirements defined for SQLite WAL recovery on restart (e.g., trust the WAL, no manual replay logic)? [Edge Case, Gap]
- [ ] CHK031 Are requirements specified for JSONL truncation, corruption, or partial last-line between restarts? [Edge Case, Gap]
- [ ] CHK032 Is the "same byte sequence in distinct cycles" deduplication scenario covered as a normative requirement, not just an edge-case note? [Edge Case, Spec §Edge Cases, US3 AS2]
- [ ] CHK033 Are requirements documented for clock skew across restart (e.g., system time moves backwards; `observed_at` ordering implications)? [Edge Case, Gap]

## Non-Functional Requirements

- [ ] CHK034 Is the per-cycle wall-clock cap (≤ 1 second) bounded under high-throughput load (≤ 50 agents at upper-bound write rates)? [NFR, Spec §FR-001]
- [ ] CHK035 Is the in-memory FR-040 buffer's worst-case memory footprint bounded by an observable cap (e.g., per-cycle byte cap × N agents)? [NFR, Spec §FR-040]
- [ ] CHK036 Are concurrency requirements specified for `events` SQLite reads while a writer cycle is mid-commit (snapshot isolation expectations)? [NFR, Spec §Edge Cases]

## Dependencies & Assumptions

- [ ] CHK037 Is the assumption of SQLite read-after-write consistency within a single transaction documented? [Assumption, Gap]
- [ ] CHK038 Is the assumption that the daemon process clock is monotonic enough for `observed_at` ordering documented? [Assumption, Spec §Assumptions]
- [ ] CHK039 Are dependencies on FEAT-007's `reader_cycle_offset_recovery` semantics version-pinned to a specific helper API surface? [Dependency, Spec §FR-002, FR-041]

## Ambiguities & Conflicts

- [ ] CHK040 Is "next cycle" in FR-040 unambiguous when a degraded mode persists across many cycles (does the buffer accumulate or stop reading)? [Ambiguity, Spec §FR-040]
