# Audit Stream Checklist: Event-Driven Routing and Multi-Master Arbitration

**Purpose**: Validate requirements quality for FEAT-010 JSONL audit entries — vocabulary completeness, schema clarity, redaction enforcement, and self-containment per SC-008.
**Created**: 2026-05-16
**Feature**: [spec.md](../spec.md)
**Depth**: Deep

## Audit Event Vocabulary

- [X] CHK001 Are all six FEAT-010 audit event types enumerated (`route_matched`, `route_skipped`, `route_created`, `route_updated`, `route_deleted`, `routing_worker_heartbeat`)? [Completeness, Spec §FR-035]
- [X] CHK002 Is the explicit exclusion of per-cycle `routing_cycle_started/completed` events documented with rationale? [Clarity, Spec §FR-035, Clarifications]
- [X] CHK003 Is the closed-set `route_skipped(reason=…)` vocabulary complete and stable? [Completeness, Spec §FR-037]
- [X] CHK004 Are FEAT-010 audit event types distinguishable from FEAT-008 / FEAT-009 entries (e.g., prefix, namespace, schema field)? [Gap]

## route_matched / route_skipped Schema

- [X] CHK005 Is the field set for `route_matched` / `route_skipped` enumerated with type, nullability, and rationale per field? [Completeness, Spec §FR-036]
- [X] CHK006 Are `target_agent_id` and `target_label` documented as present in every entry with explicit null semantics? [Spec §FR-036, Clarifications]
- [X] CHK007 Is `winner_master_agent_id` null semantics tied to specific skip reasons (`no_eligible_master`)? [Clarity, Spec §FR-036]
- [X] CHK008 Is the relationship between `target_label` and the agent-registry source-of-truth at evaluation time specified? [Spec §FR-036, Gap]
- [X] CHK009 Is the 240-char excerpt cap consistent with FEAT-009's audit excerpt convention? [Consistency, Spec §FR-036]
- [X] CHK010 Is the rendered template body excluded from `route_matched` audit (kept only in the queue row) explicitly stated to avoid duplication? [Gap]

## Catalog Lifecycle Audit Entries

- [X] CHK011 Are the field sets for `route_created`, `route_updated`, `route_deleted` enumerated? [Gap]
- [X] CHK012 Is `route_updated` distinguishable for enable-vs-disable transitions (e.g., dedicated `change` field)? [Spec §FR-009, FR-035, Gap]
- [X] CHK013 Is the idempotent no-op (re-disable an already-disabled route) explicitly specified as NOT emitting `route_updated`? [Consistency, Spec §FR-009]
- [X] CHK014 Is the audit entry for a failed `route add` (validation rejection) specified or explicitly omitted? [Gap, Spec §FR-005..008]

## Heartbeat Entry Schema

- [X] CHK015 Are heartbeat fields (`emitted_at`, `interval_seconds`, `cycles_since_last_heartbeat`, `events_consumed_since_last_heartbeat`, `skips_since_last_heartbeat`, `degraded`) enumerated with type? [Spec §FR-039a]
- [X] CHK016 Is counter-reset-at-emission semantics specified? [Spec §FR-039a]
- [X] CHK017 Is the first-heartbeat-after-startup timing (one full interval after worker begins, no startup beacon) specified? [Spec §FR-039a]
- [X] CHK018 Is heartbeat behavior during `routing_worker_degraded` specified (emit with `degraded=true`, still on cadence)? [Spec §FR-039a, FR-051]
- [X] CHK019 Is the heartbeat distinguishable from any FEAT-008 classifier heartbeat (event_type uniqueness)? [Gap]
- [X] CHK020 Are heartbeat interval bounds `[10, 3600]` justified against observability needs? [Spec §FR-039a]

## Redaction & Sensitive Data

- [X] CHK021 Is FEAT-007 redaction applied to the excerpt in EVERY FEAT-010 audit entry that carries one? [Completeness, Spec §FR-026, FR-036]
- [X] CHK022 Are `source_label`, `source_agent_id`, `winner_master_agent_id`, `target_label`, `target_agent_id` explicitly designated raw-passthrough (operator-controlled identifiers) rather than redacted? [Gap]
- [X] CHK023 Are template fields rendered into queue body (not audit) distinguished from those echoed to audit, to prevent leaking unredacted data via audit? [Gap, Spec §FR-026]

## Ordering & Durability

- [X] CHK024 Is audit-entry ordering specified per-route (event_id ascending) and within a cycle (route processing order per FR-042)? [Spec §FR-011, FR-042]
- [X] CHK025 Is wall-clock timestamp format specified (ISO-8601, UTC, precision) consistently across all entry types? [Gap]
- [X] CHK026 Is the audit-append-failure recovery flow (buffer + retry, surface degraded state) bounded (max buffer? max retry count?)? [Spec §FR-039, Gap]
- [X] CHK027 Is the SQLite-state-as-source-of-truth invariant explicit when audit JSONL diverges? [Spec §FR-039]

## Self-Containment & Traceability

- [X] CHK028 Does the spec affirm SC-008's "one line is enough" property for every `route_skipped` reason individually? [Measurability, Spec §SC-008, FR-036]
- [X] CHK029 Are `event_id` and `route_id` confirmed present in every per-(route,event) audit entry to enable joins without timing dependencies? [Consistency, Spec §FR-036]
- [X] CHK030 Is the operator workflow to reconstruct a full delivery chain from JSONL (event → route_matched → queue_message_enqueued → queue_message_delivered) explicitly traceable? [Spec §Story 1 #3]

## Coverage-Gap Remediation (added 2026-05-16 per coverage.md audit)

- [X] CHK031 Is the `no_eligible_master` skip semantic (exactly one `route_skipped` JSONL entry per matching event AND cursor advances AND zero queue rows created) fully measurable from JSONL output alone? [Measurability, Spec §FR-018, SC-003]
- [X] CHK032 Is SC-003's 100%-skip-and-cursor-advance threshold over N=10 events with zero eligible masters specified with explicit pass/fail criteria (audit-entry count = N, cursor advance count = N, queue-row count = 0)? [Measurability, Spec §SC-003]
