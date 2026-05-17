# Concurrency & Crash Safety Checklist: Event-Driven Routing and Multi-Master Arbitration

**Purpose**: Validate requirements quality for FEAT-010's concurrency, transaction, and crash-recovery semantics — single-writer model, atomic cursor advance, restart safety, and race-window handling.
**Created**: 2026-05-16
**Feature**: [spec.md](../spec.md)
**Depth**: Deep

## Worker Concurrency Model

- [X] CHK001 Is the single-threaded sequential worker model explicit (FR-014 + Clarifications) without residual ambiguity from older "concurrent cycles for same route" wording? [Spec §FR-014, Clarifications]
- [X] CHK002 Is the "no per-route parallelism" decision recorded as intentional MVP scope, not omission? [Spec §FR-014, Clarifications]
- [X] CHK003 Is the "one cycle in flight" invariant testable (no overlapping cycles observable in audit ordering)? [Measurability, Spec §FR-014]
- [X] CHK004 Is the interaction between the routing worker and other daemon workers (event ingest, queue delivery) specified (independent? coordinated?)? [Gap]

## Cursor-Advance Transaction Semantics

- [X] CHK005 Is the cursor-advance-with-enqueue atomicity requirement explicit (single SQLite transaction)? [Clarity, Spec §FR-012, Story 4 #1]
- [X] CHK006 Is the cursor-advance-on-skip transaction scope specified (cursor update only, no queue insert)? [Spec §FR-012]
- [X] CHK007 Is the transaction-rollback behavior on SQLite-write failure specified (no cursor advance, retry next cycle)? [Spec §FR-013]
- [X] CHK008 Are the "transient internal errors" that warrant no-cursor-advance enumerated as a closed set? [Spec §FR-013, FR-051]
- [X] CHK009 Is the audit JSONL append explicitly outside the cursor-advance transaction (best-effort retry per FEAT-008 inheritance)? [Consistency, Spec §FR-039]

## Crash Recovery

- [X] CHK010 Is cold-start cursor read from SQLite specified as the sole recovery primitive (no journaling, no replay log)? [Spec §FR-044]
- [X] CHK011 Is the "no recovery transition needed" claim (FR-044) justified by the cursor-advance-with-enqueue atomicity? [Consistency, Spec §FR-012, FR-044]
- [X] CHK012 Is mid-transaction crash behavior specified (next cycle re-evaluates the in-flight event)? [Spec §Story 4 #1]
- [X] CHK013 Is post-commit-mid-render crash behavior specified (route does not re-process; no duplicate)? [Spec §Story 4 #2]
- [X] CHK014 Are recovery tests fault-injection-driven (Story 4 IT) sufficient to cover both before-commit and after-commit windows? [Spec §Story 4 IT]

## Duplicate-Routing Defense

- [X] CHK015 Is the UNIQUE `(route_id, event_id)` constraint behavior on conflict specified (storage-layer rejection, hard internal error surfaced)? [Spec §FR-030, Story 4 #3]
- [X] CHK016 Is the relationship between cursor-advance-with-enqueue (primary guard) and UNIQUE constraint (defense-in-depth) explicit? [Consistency, Spec §FR-030, Edge Cases]
- [X] CHK017 Is the closed-set internal-error code raised on UNIQUE violation documented? [Gap, Spec §FR-051]

## Shutdown & Lifecycle

- [X] CHK018 Is shutdown behavior specified (worker exits at next cycle boundary, in-flight transaction commits or rolls back)? [Spec §FR-043]
- [X] CHK019 Is the daemon-shutdown signal handling specified for the routing worker? [Gap]
- [X] CHK020 Is the relationship between FEAT-009 worker shutdown and FEAT-010 worker shutdown ordered (which stops first)? [Gap]
- [X] CHK021 Is the heartbeat-emission shutdown behavior specified (emit final heartbeat? suppress?)? [Gap, Spec §FR-039a]

## CLI-vs-Daemon Race Windows

- [X] CHK022 Is concurrent CLI access (e.g., two `route disable` calls racing) safety-guaranteed? [Gap]
- [X] CHK023 Is the routing-cycle reaction to a mid-cycle `route disable` specified ("cycle completes events already loaded, subsequent cycles skip")? [Spec §Edge Cases]
- [X] CHK024 Is `route remove` while a route's queue row is mid-delivery handled per the orphan-reference rule? [Spec §Edge Cases]
- [X] CHK025 Is the master-deregistration-between-arbitration-and-queue-insert race documented with deterministic resolution? [Spec §Edge Cases]
- [X] CHK026 Is the target-deregistration-between-resolution-and-enqueue race specified? [Spec §Edge Cases]

## SQLite Locking & Multi-Process

- [X] CHK027 Are SQLite journaling mode requirements (WAL? rollback?) specified for safe concurrent reads during writes? [Gap]
- [X] CHK028 Is multi-process daemon detection (refuse to start a second daemon on the same DB) specified? [Gap]
- [X] CHK029 Is the host-daemon-vs-bench-container-CLI write contention bound (single daemon writer, multiple CLI readers)? [Gap, Spec §Assumptions]
- [X] CHK030 Is the cycle-interval-vs-batch-runtime overrun behavior specified (cycle N+1 deferred until cycle N finishes)? [Spec §FR-014, FR-040, FR-041, Gap]

## Coverage-Gap Remediation (added 2026-05-16 per coverage.md audit)

- [X] CHK031 Is SC-004's no-duplicate-routing threshold (over N=10 fault-injected mid-transaction crashes) specified with explicit count-equality criteria — every unique `(route_id, event_id)` pair appears in `queue_message_enqueued` audit entries exactly once, zero exceptions — so the test can pass/fail without subjective judgement? [Measurability, Spec §SC-004, FR-012, FR-030]
