# Concurrency Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that concurrency requirements (serialization, locking, races, ordering) are complete, clear, consistent, and measurable.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Serialization Scope

- [x] CHK001 Are concurrency requirements specified for layout-creation against the same container (FR-019)? [Completeness, Spec §FR-019]
- [x] CHK002 Are concurrency requirements specified for layout-creation across different containers (must they also serialize, or run in parallel)? [Gap, Spec §FR-019]
- [x] CHK003 Are concurrency requirements specified for remove + recreate ordering on the same managed pane? [Gap]
- [x] CHK004 Are concurrency requirements specified for two operators issuing the same operation at the same time on the same pane (e.g., two removes, two recreates)? [Gap]

## Locking Model

- [x] CHK005 Is the locking model specified for the per-container serialization (mutex, semaphore, queue)? [Gap, Spec §FR-019]
- [x] CHK006 Are deadlock-prevention requirements specified (per-container locks must release on operator disconnect / crash)? [Gap, Spec §FR-019]
- [x] CHK007 Are starvation-prevention requirements specified for the FR-019 wait queue (FIFO ordering, max wait time, fairness)? [Gap]
- [x] CHK008 Is lock granularity specified (per-container vs per-layout vs per-pane)? [Clarity, Spec §FR-019]

## Race Conditions

- [x] CHK009 Are concurrency requirements specified for the scan + creation flow interaction (FR-014 marker is the mitigation — but what is the low-level race set)? [Coverage, Spec §FR-014]
- [x] CHK010 Are concurrency requirements specified for the daemon's handling of overlapping retries on the same pending-managed layout? [Gap, Spec §FR-014]
- [x] CHK011 Are concurrency requirements specified for the predecessor_id chain (two simultaneous recreations of the same predecessor)? [Gap, Spec §FR-011]
- [x] CHK012 Are race conditions enumerated for the periodic scan vs creation completion (low-level race set)? [Coverage]
- [x] CHK013 Are concurrency requirements specified for the case where tmux itself executes commands asynchronously vs the daemon's expected ordering? [Gap]

## Recovery & Restart

- [x] CHK014 Are concurrency requirements specified for daemon-restart recovery vs an in-flight operator request at the moment of restart? [Gap, Spec §FR-020]
- [x] CHK015 Are concurrency requirements specified for resumption of partially-serialized work after a daemon crash? [Gap, Spec §FR-019, FR-020]

## Event Ordering

- [x] CHK016 Are concurrency requirements specified for the lifecycle event stream (consumer ordering guarantees per pane, per layout)? [Gap, Spec §FR-015]
- [x] CHK017 Are concurrency requirements specified for the audit/history append-only semantics under concurrent writers? [Gap, Spec §FR-021]

## Consistency

- [x] CHK018 Are concurrency requirements consistent with the assumption "MVP authorization is socket-access based" (single operator typical, but the requirements still cover concurrent calls)? [Consistency, Spec §Assumptions]
- [x] CHK019 Are concurrency safety properties testable from the operator surface alone? [Measurability]

---

## Walk closure (2026-05-25)

19/19 items resolved by R2 (per-container threading.Lock, FIFO via CPython contention semantics) + FR-019 (per-container serialization) + FR-014 + R1 (pending-managed marker race mitigation) + FR-015 amendment (per-pane FIFO + per-layout FIFO event ordering, from pre-implement walk topic E) + FR-027 + managed_pane_concurrent_recreate (concurrent recreate, from pre-implement walk topic F).
