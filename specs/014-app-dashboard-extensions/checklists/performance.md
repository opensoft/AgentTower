# Performance Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for latency, throughput, concurrency, and resource consumption introduced by v1.1.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Latency Specification

- [ ] CHK001 - Is the FEAT-011 dashboard latency budget cited by name or by numeric value in this spec? [Measurability, Spec §SC-006]
- [ ] CHK002 - Is the latency budget specified as a percentile (p50/p95/p99) or only a mean? [Clarity, Spec §SC-006]
- [ ] CHK003 - Is the latency budget specified for the new v1.1 fields specifically (additive cost ≤ X ms), or only for the overall response envelope? [Gap, Spec §SC-006]

## Throughput & Concurrency

- [ ] CHK004 - Are concurrent-caller requirements specified for `app.dashboard` (e.g., is recompute-per-call safe and bounded for N concurrent callers)? [Gap, Spec §Clarifications Q8]
- [ ] CHK005 - Is the cost model for recompute-per-call stated (i.e., is recomputation cheap enough that no cache is required, and how is "cheap enough" defined)? [Clarity, Spec §Clarifications Q8]

## Resource Consumption

- [ ] CHK006 - Is the worst-case in-memory size of the recently-skipped ring buffer bounded (300_000 ms × maximum-skips-per-second)? [Gap, Spec §FR-008]
- [ ] CHK007 - Are memory bounds specified for the recommendation engine (stateless, no caching, just a function over current daemon state)? [Gap, Spec §Clarifications Q8]

## Degradation Under Load

- [ ] CHK008 - Is the requirement defined for what the dashboard does when it cannot meet the latency budget (return stale, return partial, exceed budget gracefully)? [Gap, Spec §SC-006]
- [ ] CHK009 - Is the requirement defined for whether dashboard latency SLOs still apply during a degraded subsystem state? [Gap, Spec §FR-010]

## Measurability

- [ ] CHK010 - Can SC-006 be measured by a single automated test against a known fixture? [Measurability, Spec §SC-006]
- [ ] CHK011 - Is the test fixture for latency described (size of fixture: how many panes, agents, recent skips)? [Gap, Spec §SC-006]

## Boundary & Stress Scenarios

- [ ] CHK012 - Is the boundary case "very large pane/agent count" addressed by either a stated limit or a stated graceful behavior? [Gap]
- [ ] CHK013 - Is the boundary case "high skip rate filling the ring buffer faster than it ages out" addressed? [Gap, Spec §FR-008]
- [ ] CHK014 - Is the non-functional requirement for daemon CPU usage during dashboard calls under load specified, or is it implicitly bounded by the latency budget alone? [Gap]

## Plan & Design Alignment (re-verify 2026-05-24)

- [ ] CHK015 - Does Research §CO state the additive cost estimate (< 5 ms) with the explicit fixture-scale assumption (FEAT-011 fixture sizes), so the budget headroom claim is testable? [Measurability, Research §CO]
- [ ] CHK016 - Is the ring buffer's worst-case memory (~80 KB at 10 000 entries × ~8 bytes/entry) called out so reviewers can sanity-check the `maxlen` choice? [Clarity, Research §RB]
- [ ] CHK017 - Does plan.md's "no new background worker" claim reconcile with `skip_counter.record_skip` being called synchronously by the existing FEAT-010 routing worker? [Consistency, Plan §Constraints]
- [ ] CHK018 - Is the cost of recommendation evaluation stated as O(n) over a small named n (panes + agents + routes ≤ a stated bound), not just "fast"? [Clarity, Research §CO]
