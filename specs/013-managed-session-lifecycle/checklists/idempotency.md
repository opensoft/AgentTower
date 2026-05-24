# Idempotency Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that idempotency requirements (retry safety, dedup keys, pending markers, replay semantics) are complete, clear, consistent, and measurable.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Idempotency Boundary

- [ ] CHK001 Is the idempotency boundary specified for create-layout (request idempotency-key, layout pending-state, both)? [Clarity, Spec §FR-014]
- [ ] CHK002 Are deduplication semantics specified for "the same pending layout" — what determines sameness (idempotency key, layout id, hash of inputs)? [Clarity, Spec §FR-014]
- [ ] CHK003 Are idempotency semantics specified for remove-managed-pane (multiple removes of the same pane)? [Gap, Spec §FR-010]
- [ ] CHK004 Are idempotency semantics specified for recreate-managed-pane (multiple recreates from the same predecessor)? [Gap, Spec §FR-011]
- [ ] CHK005 Are idempotency semantics specified for layout removal (cascade of pane removals)? [Gap]

## Pending Marker Lifecycle

- [ ] CHK006 Is the pending-managed marker's lifetime / TTL specified (how long does it remain active before considered stale)? [Gap, Spec §FR-014]
- [ ] CHK007 Are the conditions specified under which a partial layout is "resumed" vs "restarted"? [Clarity, Spec §FR-014]
- [ ] CHK008 Are requirements specified for cleanup of stale pending-managed markers across daemon restart (FR-020)? [Gap]
- [ ] CHK009 Is the pending-managed-marker representation specified to be observable by the periodic scan without scan changes (or with explicit scan changes)? [Coverage, Cross-ref: integration.md]

## Replay & Retry

- [ ] CHK010 Are requirements specified for what happens if the operator retries with different inputs (same idempotency key, different launch command)? [Gap]
- [ ] CHK011 Are concurrent-retry semantics specified (two retries of the same idempotency key in flight at once)? [Gap, Spec §FR-019]
- [ ] CHK012 Is the maximum number of retries before a layout is considered permanently failed specified? [Gap]
- [ ] CHK013 Are idempotency semantics specified for the lifecycle event stream (FR-015) — can duplicate events occur on retry, or are events themselves idempotent? [Gap]

## Response Semantics

- [ ] CHK014 Are requirements specified for distinguishing "no-op because already done" from "operation succeeded" responses? [Clarity]
- [ ] CHK015 Is the response shape specified for a retry that finds a previously-failed layout (does it return the prior failure, or attempt resumption)? [Gap, Spec §FR-013]

## Crash Recovery

- [ ] CHK016 Are the requirements specified for the case where the daemon crashes after creating panes but before registering them — does the next retry deduplicate via the pending-managed marker? [Coverage, Spec §FR-020]
- [ ] CHK017 Are requirements specified for crash recovery during recreate (predecessor archived, new record half-created)? [Gap, Spec §FR-011]
