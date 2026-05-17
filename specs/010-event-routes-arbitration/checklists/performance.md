# Performance Checklist: Event-Driven Routing and Multi-Master Arbitration

**Purpose**: Validate requirements quality for FEAT-010's performance SLOs — latency targets, throughput bounds, scalability limits, and load-assumption clarity.
**Created**: 2026-05-16
**Feature**: [spec.md](../spec.md)
**Depth**: Deep

## End-to-End Latency SLOs

- [X] CHK001 Is the 5-second event-to-delivery latency SLO defined under quantified load assumptions (event rate, route count)? [Clarity, Spec §SC-001]
- [X] CHK002 Is "typical local conditions" quantified (host CPU class, disk type, concurrent workload)? [Ambiguity, Spec §SC-001]
- [X] CHK003 Is the 5-second budget decomposed across pipeline stages (FEAT-008 ingest → routing cycle → FEAT-009 enqueue → tmux paste)? [Gap]
- [X] CHK004 Is the latency target's relationship to the FR-040 default cycle interval (1s) consistent (worst-case cycle wait fits within budget)? [Consistency, Spec §SC-001, FR-040]

## CLI Latency SLOs

- [X] CHK005 Is the 500ms `route list` target at 1000 routes specified with the hardware/storage class? [Clarity, Spec §SC-006]
- [X] CHK006 Is the 100ms `route add` validation target specified for cold-start vs warm cache? [Ambiguity, Spec §SC-007]
- [X] CHK007 Are the `route show`, `route enable`, `route disable`, `route remove` latency targets specified or explicitly omitted? [Gap]
- [X] CHK008 Is `agenttower status` latency at 1000 routes bounded (FR-038's `most_stalled_route` lag computation)? [Gap, Spec §FR-038]

## Throughput & Scale Bounds

- [X] CHK009 Is the maximum supported event-ingest rate documented vs routing-cycle throughput? [Gap, Spec §FR-010]
- [X] CHK010 Is the maximum supported route count beyond 1000 documented as supported / unsupported / degraded? [Gap, Spec §SC-006]
- [X] CHK011 Is the fan-out performance (N routes × M events) bounded with a worst-case formula? [Gap, Spec §FR-015]
- [X] CHK012 Is the per-route batch cap (FR-041 default 100, bounds `[1, 10000]`) justified against worst-case backlog drain scenarios? [Clarity, Spec §FR-041]
- [X] CHK013 Is the catch-up rate for a long-disabled route quantified per SC-009's `ceil(backlog_size / batch_size)` cycles formula? [Spec §SC-009]

## Cycle Performance

- [X] CHK014 Is per-cycle elapsed time explicitly out-of-scope for MVP, with operator-impact rationale? [Spec §Assumptions]
- [X] CHK015 Is the cycle-interval bounds `[0.1, 60]` justified against latency SLO at the low end and idle-cost at the high end? [Spec §FR-040]
- [X] CHK016 Is the cycle-overrun behavior specified when one cycle exceeds the next-cycle interval? [Gap, Spec §FR-014]
- [X] CHK017 Is the heartbeat-emission cost (FR-039a) bounded vs cycle latency? [Gap]
- [X] CHK018 Are the observability-counter update costs (`events_consumed_total`, `skips_by_reason`) bounded per cycle? [Gap, Spec §FR-038]

## SQLite Query Performance

- [X] CHK019 Is the routing-cycle event-scan query performance documented (indexed on `event_id` + `event_type`)? [Gap, Spec §FR-010]
- [X] CHK020 Are query-plan assumptions documented for `agenttower queue --origin route` filter at scale? [Gap, Spec §FR-033]
- [X] CHK021 Is the UNIQUE `(route_id, event_id)` index performance impact on insert bounded? [Spec §FR-030, Gap]
- [X] CHK022 Is the `most_stalled_route` computation cost bounded with explicit algorithmic complexity? [Gap, Spec §FR-038]

## Rendering & Redaction Costs

- [X] CHK023 Is template-rendering latency per-(route,event) bounded? [Gap, Spec §FR-025]
- [X] CHK024 Is FEAT-007 redaction-latency assumption documented for excerpts at the 240-char cap? [Gap, Spec §FR-026]
- [X] CHK025 Is the arbitration-before-render ordering (FR-019) measurable as a CPU-savings invariant? [Spec §FR-019]

## Degraded-State Performance

- [X] CHK026 Is worst-case latency under audit-retry buffering (FR-039) bounded? [Gap, Spec §FR-039]
- [X] CHK027 Is the routing throughput impact of `routing_worker_degraded` specified (slowed? halted?)? [Gap, Spec §FR-051]
- [X] CHK028 Is the audit-buffer growth rate during degraded state bounded? [Gap]

## Measurability

- [X] CHK029 Are all performance SLOs (SC-001, SC-006, SC-007, SC-009) measurable from CLI output without external profiling? [Measurability, Spec §SC-001, SC-006, SC-007, SC-009]
- [X] CHK030 Are scale-test scenarios (hardware, dataset size, event rate) documented as part of the performance acceptance gate? [Gap]
