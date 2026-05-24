# Observability Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that observability requirements (events, metrics, logs, traces) are complete, clear, consistent, and measurable for this feature.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Event Catalog

- [ ] CHK001 Are lifecycle event types fully enumerated (FR-015 lists 8 categories — is each a distinct event type or family of types)? [Completeness, Spec §FR-015]
- [ ] CHK002 Are event payload schemas specified for each event type? [Gap]
- [ ] CHK003 Are required event fields enumerated (event_id, timestamp, layout_id, pane_id, type, payload, actor)? [Gap, Spec §FR-015]
- [ ] CHK004 Are requirements specified for emitting an event on every state transition (versus only on entry to terminal states)? [Clarity, Spec §FR-015]
- [ ] CHK005 Is the relationship between Lifecycle Event records and the FR-008 shared event surfaces specified (are these the same events or two channels)? [Clarity, Spec §FR-008]

## Metrics & SLIs

- [ ] CHK006 Are metrics requirements specified (gauges, counters, histograms) for layout-creation duration and pane-state transitions? [Gap]
- [ ] CHK007 Are SLIs specified that correspond to SC-001 (layout-create p95 under 2 minutes) and SC-003 (log-attach-failure surface latency)? [Gap, Measurability, Spec §SC-001, SC-003]
- [ ] CHK008 Are observability requirements specified for the daemon-internal serialization queue (FR-019) so operators can see waits (queue depth, wait time)? [Gap, Spec §FR-019]
- [ ] CHK009 Are observability requirements specified for the pending-managed marker (count of in-flight markers, age distribution)? [Gap, Spec §FR-014]

## Tracing & Correlation

- [ ] CHK010 Are trace/correlation-id requirements specified across the create-layout pipeline (operator request → layout → panes → events)? [Gap]
- [ ] CHK011 Are requirements specified for the predecessor_id chain visibility in observability (query "show me the chain for pane X")? [Gap, Spec §FR-011]

## Coverage

- [ ] CHK012 Are requirements specified for the operator's ability to filter events by managed/adopted origin? [Gap, Spec §FR-005]
- [ ] CHK013 Are requirements specified for distinguishing events from automated transitions vs operator-initiated transitions? [Gap]
- [ ] CHK014 Are observability requirements specified for daemon-restart recovery (which events are emitted on reattach, FR-020)? [Gap, Spec §FR-020]
- [ ] CHK015 Are observability requirements specified for the failed-stage diagnostic (FR-013) so log queries can find it? [Coverage, Spec §FR-013]
- [ ] CHK016 Are observability requirements specified for the layout-level aggregate state (vs only pane-level events)? [Gap]

## Volume & Cost

- [ ] CHK017 Are requirements specified for the volume of events emitted per layout creation (does it scale O(panes), O(stages × panes))? [Gap]
- [ ] CHK018 Are retention/sizing requirements specified for the durable event store given indefinite retention (FR-021)? [Gap, Cross-ref: data-model.md, performance.md]

## Confidentiality

- [ ] CHK019 Are requirements specified for redacting any sensitive fields in events (launch command env vars, secrets)? [Gap, Cross-ref: security.md]

## Consistency

- [ ] CHK020 Are observability requirements consistent between this feature and FEAT-008 (event ingestion)? [Consistency, Dependency]
- [ ] CHK021 Are observability requirements aligned with the existing operator surfaces used for adopted panes (FR-008)? [Consistency, Spec §FR-008]
