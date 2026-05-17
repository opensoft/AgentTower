# Observability Checklist: Event-Driven Routing and Multi-Master Arbitration

**Purpose**: Validate requirements quality for FEAT-010 observability surfaces — `agenttower status` routing section, per-route runtime view, degraded-state signal, and heartbeat liveness.
**Created**: 2026-05-16
**Feature**: [spec.md](../spec.md)
**Depth**: Deep

## status `routing` Section Schema

- [X] CHK001 Is the `routing` object's field set fully enumerated (`routes_total`, `routes_enabled`, `routes_disabled`, `last_routing_cycle_at`, `events_consumed_total`, `skips_by_reason`, `most_stalled_route`)? [Completeness, Spec §FR-038]
- [X] CHK002 Are field types specified for each routing-status field (counts as integers, timestamp as ISO-8601, etc.)? [Gap]
- [X] CHK003 Are counter scopes specified as daemon-process-scoped (reset on restart) vs persisted? [Clarity, Spec §FR-038, Gap]
- [X] CHK004 Are zero-valued `skips_by_reason` entries specified as present-with-0 vs omitted from the object? [Ambiguity, Spec §FR-038]
- [X] CHK005 Is `skips_by_reason` constrained to the closed FR-037 reason set (no free-form keys)? [Consistency, Spec §FR-037, FR-038]

## most_stalled_route Computation

- [X] CHK006 Is "lag" defined precisely (count of matching events with event_id > cursor)? [Clarity, Spec §FR-038]
- [X] CHK007 Is the tie-break rule specified when multiple routes share the same maximum lag? [Gap]
- [X] CHK008 Is the lag-computation cost bounded so it doesn't degrade `status` latency at 1000-route scale? [Spec §SC-006, Gap]
- [X] CHK009 Is the "no route lagging" null-vs-empty-object representation specified? [Clarity, Spec §FR-038]
- [X] CHK010 Is the lag-computation behavior under disabled routes specified (excluded? included?)? [Spec §FR-009, Gap]

## Per-Route runtime View

- [X] CHK011 Are the `runtime` sub-object fields for `route show --json` enumerated (`last_routing_cycle_at`, `events_consumed`, `last_skip_reason`, `last_skip_at`)? [Completeness, Spec §FR-047]
- [X] CHK012 Is `events_consumed` scoped (lifetime vs daemon-start vs since-enable)? [Ambiguity, Spec §FR-047]
- [X] CHK013 Is the persistence model for `runtime` fields specified (replayable from JSONL? cached?)? [Gap]
- [X] CHK014 Is `last_skip_reason` constrained to the closed FR-037 set with null for "never skipped"? [Consistency, Spec §FR-037, FR-047]

## Degraded State

- [X] CHK015 Are the entry conditions for `routing_worker_degraded` enumerated (audit-append failure? SQLite-lock streak? internal error?)? [Spec §FR-051, Gap]
- [X] CHK016 Are the exit conditions (how degraded clears) specified? [Gap]
- [X] CHK017 Is the operator-visible representation in `status` shape-identical to FEAT-008's classifier-degraded? [Consistency, Spec §FR-051]
- [X] CHK018 Is the degraded-state's effect on routing semantics (continue? pause?) specified? [Gap]
- [X] CHK019 Is the heartbeat's `degraded` field documented as the canonical JSONL-side mirror of the status field? [Spec §FR-039a]

## Liveness via Heartbeat

- [X] CHK020 Is the heartbeat positioned as a supplementary liveness signal (status is primary) consistently in the spec? [Spec §FR-039a, Clarifications]
- [X] CHK021 Is the heartbeat-interval bounds rationale documented (`[10, 3600]` reflects monitoring polling intervals)? [Gap]
- [X] CHK022 Is the operator workflow "is routing alive?" specified for both status-based and JSONL-based monitoring? [Coverage, Spec §Story 7]
- [X] CHK023 Is the "no per-cycle audit" decision documented in observability rationale, not buried in audit-section only? [Spec §FR-035, Gap]

## Backward Compatibility & Versioning

- [X] CHK024 Is the `routing` section additive to FEAT-009's status JSON shape (no field renames/removals)? [Gap]
- [X] CHK025 Is status JSON schema versioning specified or explicitly omitted with stability guarantee? [Gap]
- [X] CHK026 Are operator-visible field renames between dev cycles policy-documented? [Gap]

## Operator-Facing Coverage

- [X] CHK027 Does the spec define how an operator identifies "this route is silently failing" vs "no matching events"? [Spec §Story 7, FR-038]
- [X] CHK028 Is there an operator pathway to see fan-out distribution (which routes consumed which events)? [Spec §FR-015, Gap]
- [X] CHK029 Are routing observability surfaces accessible from inside a bench container (read-only) or host-only? [Gap, Spec §Assumptions]
- [X] CHK030 Is the `status --json` exit-code behavior on degraded routing specified (still 0? non-zero?)? [Gap]
