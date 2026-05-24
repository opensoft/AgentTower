# Performance Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that performance, scalability, and timing requirements are complete, clear, consistent, and measurable.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Latency & Timing

- [ ] CHK001 Is SC-001's "under 2 minutes" decomposed by stage (pane create, command launch, registration, log attach)? [Completeness, Spec §SC-001]
- [ ] CHK002 Is SC-003's "within 10 seconds of layout creation completion" defined precisely (10s wall-clock from completion event, or 10s from log-attach attempt)? [Clarity, Spec §SC-003]
- [ ] CHK003 Are performance requirements specified for the FR-019 serialization wait time upper bound (max time a second request may wait)? [Gap, Spec §FR-019]
- [ ] CHK004 Are performance requirements specified for daemon-restart recovery time (FR-020/SC-008)? [Gap, Spec §FR-020, SC-008]
- [ ] CHK005 Are timing requirements specified for the pending-managed marker lifetime (max in-flight duration before it is considered stale)? [Gap, Spec §FR-014]
- [ ] CHK006 Are performance requirements specified for the operator-facing diagnostic surface latency (FR-013)? [Gap]
- [ ] CHK007 Are first-feedback-time requirements specified inside the SC-001 budget (operator sees something within X seconds)? [Gap, Spec §SC-001]

## Throughput & Scalability

- [ ] CHK008 Are scalability requirements specified for max concurrent managed layouts per daemon? [Gap]
- [ ] CHK009 Are scalability requirements specified for max managed panes per host / per bench container? [Gap]
- [ ] CHK010 Are throughput requirements specified for the lifecycle event stream (events/sec sustainable)? [Gap, Spec §FR-015]
- [ ] CHK011 Is the performance impact of the indefinite event retention's growth on query performance bounded by an SLA? [Gap, Spec §FR-021]
- [ ] CHK012 Is the performance impact of repeated recreations on the predecessor chain quantified (chain length × query cost)? [Gap, Spec §FR-011]

## Degradation & Load

- [ ] CHK013 Are degradation requirements specified for high-load scenarios (operator creating many layouts back-to-back)? [Gap, Edge Case]
- [ ] CHK014 Are performance requirements specified for the scan + creation flow interaction (does the scan polling interval impact create-layout p95)? [Gap, Spec §FR-014]
- [ ] CHK015 Are performance requirements specified consistently between FR-008's shared surfaces and existing FEAT-011 contracts (no new SLAs that contradict prior contracts)? [Consistency]

## Measurability

- [ ] CHK016 Are performance requirements measurable in CI or local-dev without a multi-host setup? [Measurability]
- [ ] CHK017 Are the metrics required to measure SC-001/SC-003/SC-008 enumerated (which timers, where they are emitted)? [Measurability, Cross-ref: observability.md]
