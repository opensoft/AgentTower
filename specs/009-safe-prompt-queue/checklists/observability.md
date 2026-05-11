# Observability Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of audit, JSONL stream, queue listing display contract, `agenttower status` integration, and reconstructability requirements. Tests whether the observability surface is fully specified and consumer-ready (for operators, FEAT-008, and a future FEAT-010) — NOT whether logs are emitted at runtime.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Feature**: [spec.md](../spec.md)

## Audit Entry Completeness

- [ ] CHK001 Are the required fields in each `queue_message_*` audit entry enumerated exhaustively (`message_id`, `from_state`, `to_state`, `reason`, operator identity, transition timestamp)? [Completeness, Spec §FR-046]
- [ ] CHK002 Is the "one audit entry per state transition" rule stated as a strict 1:1 mapping with no batching or coalescing? [Clarity, Spec §FR-046]
- [ ] CHK003 Are requirements specified for capturing operator identity on operator-driven transitions distinctly from worker-driven transitions? [Completeness, Spec §FR-046]
- [ ] CHK004 Is the enqueue-time identity snapshot (sender_label, sender_role, sender_capability) required to persist in audit even after the agent is deregistered? [Completeness, Spec §Edge Cases, §FR-046]
- [ ] CHK005 Is the audit format declared as backward-compatible additive (new fields may be added; existing fields cannot change shape) so downstream consumers don't break? [Gap, Coverage]

## Event-Type Vocabulary

- [ ] CHK006 Is the `queue_message_*` event-type set enumerated as a closed list with one entry per transition kind? [Completeness, Spec §FR-046, §Clarifications]
- [ ] CHK007 Are these event types disjoint from existing FEAT-008 classifier event types so that consumers can switch on type without collision? [Consistency, Gap]
- [ ] CHK008 Is the relationship between event type and `(from_state, to_state)` pair declared (one type per directed transition, or one type per logical event)? [Clarity, Spec §FR-046]

## Excerpt & Redaction in Audit

- [ ] CHK009 Is the "body-meaningful" set of transitions enumerated, so the excerpt requirement applies deterministically? [Coverage, Spec §FR-047]
- [ ] CHK010 Is the raw body's exclusion from audit stated as an absolute prohibition (MUST NOT), not a default? [Clarity, Spec §FR-047, §FR-047a]
- [ ] CHK011 Is the excerpt cap (240 chars) and truncation marker (ellipsis) defined consistently across queue listings, audit entries, and `--json`? [Consistency, Spec §FR-011, §FR-047, §Assumptions]
- [ ] CHK012 Is the excerpt for multi-line bodies defined (truncate at first newline? collapse whitespace? preserve as-is up to cap)? [Gap, Clarity]

## Queue Listing Display Contract

- [ ] CHK013 Are the columns of `agenttower queue` listing enumerated as a fixed contract (`message_id`, sender identity, target identity, `state`, `enqueued_at`, last-transition timestamp, redacted `excerpt`)? [Completeness, Spec §US3 #1, §FR-031]
- [ ] CHK014 Is the column ordering and tabular format specified, or explicitly left to implementer rendering with a stable `--json` contract as the machine surface? [Gap, Clarity]
- [ ] CHK015 Is the redacted-excerpt requirement applied uniformly to both `--json` and human-readable listings? [Consistency, Spec §FR-047a]
- [ ] CHK016 Are requirements specified for empty-state rendering (no rows match filters): exit code, output shape under `--json`, human-readable message? [Gap, Coverage]
- [ ] CHK017 Is the listing's default time format (relative vs absolute) specified for human-readable mode? [Gap, Clarity]

## `agenttower status` Integration

- [ ] CHK018 Are the degraded-state signals from JSONL-buffer failures required to surface through `agenttower status` (so operators can detect a daemon delivering but not auditing)? [Completeness, Spec §FR-048]
- [ ] CHK019 Are specific queue-health fields surfaced by `agenttower status` defined (in-flight count, buffered audit count, last-recovery timestamp), or explicitly inherited from FEAT-008? [Gap, Coverage]
- [ ] CHK020 Is the kill switch's current state required to be visible in `agenttower status` independently of `agenttower routing status`? [Gap, Consistency]
- [ ] CHK021 Is the operator told (through `status` or otherwise) how many `queued` rows are waiting per target so they can detect FIFO stalls? [Gap, Coverage]

## Reconstructability & Retention

- [ ] CHK022 Is the audit-reconstructability success criterion (full transition history derivable from JSONL alone) quantified with a numeric floor (≥ 1,000 transitions per agent pair)? [Measurability, Spec §SC-006]
- [ ] CHK023 Is the no-rotation MVP policy stated as inherited from FEAT-008 rather than re-specified inconsistently? [Consistency, Spec §Assumptions]
- [ ] CHK024 Are requirements defined for manual operator pruning of queue rows or audit entries (allowed? disallowed? safety constraints)? [Gap, Spec §Assumptions]
- [ ] CHK025 Is the SQLite-vs-JSONL source-of-truth precedence stated unambiguously (SQLite authoritative for state; JSONL is replay-only and best-effort)? [Clarity, Spec §FR-048]
- [ ] CHK026 Is the rule that `events.jsonl` write failure MUST NOT block SQLite state advancement stated as a hard MUST? [Clarity, Spec §FR-048]

## Downstream Consumers

- [ ] CHK027 Are the audit-entry fields required by a future FEAT-010 arbitration consumer (sender/target identity, full transition timeline) identified, so FEAT-009 doesn't need a breaking change later? [Gap, Coverage]
- [ ] CHK028 Is `agenttower events --filter message_id=<id>` (or equivalent) required so an operator can reconstruct a single row's history without a full scan? [Gap, Spec §SC-006]

## Notes

- Items test whether the spec defines the observability surface, not whether logs are correct at runtime.
- Resolution path: fill named gaps as FRs or explicit Assumptions; ensure each visible field has a contract.
- Check items off as completed: `[x]`.
