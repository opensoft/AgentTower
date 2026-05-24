# Observability Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for the dashboard-as-observability semantics (since `app.dashboard` IS the operator-facing observability surface).
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Telemetry Surface Completeness

- [ ] CHK001 - Are the v1.1 dashboard fields explicitly classified as telemetry (per-call snapshot) vs durable audit history? [Clarity, Spec §Clarifications, §Assumptions]
- [ ] CHK002 - Is the recently-skipped count specified as observable in the dashboard *only*, with no requirement to also emit metrics, logs, or events for the same data? [Clarity, Spec §FR-008]
- [ ] CHK003 - Are observable semantics for each `recommended_next_action.code` defined so an operator can act on the recommendation without reading source code? [Completeness, Spec §FR-010, §FR-011]

## Resolution & Freshness

- [ ] CHK004 - Is `recommended_next_action_refreshed_at` specified with timezone, precision (ms/µs), and clock source? [Ambiguity, Spec §Clarifications Q8]
- [ ] CHK005 - Is the dashboard explicitly poll-based with no push/subscribe requirements in v1.1? [Clarity, Spec §Assumptions, §FR-018]

## Degraded-State Observability

- [ ] CHK006 - Are the conditions that surface a `discovery-degraded` pane in the dashboard explicitly named, not just "container in `degraded_scan`"? [Clarity, Spec §Clarifications Q1]
- [ ] CHK007 - Are the conditions that surface a `subsystem_degraded` recommendation enumerated (which subsystems, what counts as degraded)? [Gap, Spec §FR-010]
- [ ] CHK008 - Is the requirement defined for the dashboard surfacing degraded states even if some sub-fields cannot be computed (recommendation compute failure)? [Coverage, Spec §FR-021]

## Operator-Action Mapping

- [ ] CHK009 - Is each recommendation code mapped to a documented operator next-step (so the dashboard's recommendation is actionable, not just a label)? [Completeness, Spec §FR-011, §FR-016]
- [ ] CHK010 - Is the relationship between `target` and operator actionability stated (e.g., `target.kind == container` implies "operator should inspect that container next")? [Clarity, Spec §FR-011]

## Data Retention vs Snapshot Semantics

- [ ] CHK011 - Is "process-local, resets on daemon restart" stated as both a feature AND a constraint operators should understand? [Clarity, Spec §FR-008, §Assumptions]
- [ ] CHK012 - Is the requirement defined that operators must not infer trend or history from `recently_skipped_count` alone? [Gap]

## Coverage of Scenario Classes

- [ ] CHK013 - Are observability requirements defined for the primary path (healthy daemon, populated dashboard)? [Coverage, Spec §US1, §US3]
- [ ] CHK014 - Are observability requirements defined for the alternate path (mixed populated/empty buckets, partial agents)? [Coverage, Spec §US1, §FR-020]
- [ ] CHK015 - Are observability requirements defined for the exception path (compute failure, degraded subsystem)? [Coverage, Spec §FR-021, §US3]
- [ ] CHK016 - Are observability requirements defined for the recovery path (daemon-restart resets, post-restart dashboard call before any new events)? [Coverage, Spec §FR-008, §US2 acceptance #3]

## Cross-Field Observability Invariants

- [ ] CHK017 - Is the observable invariant `discovered-and-registered == registered_v1.0` stated as a property an operator (or test) can verify directly? [Measurability, Spec §FR-019]
- [ ] CHK018 - Is the observable invariant `active + inactive + partially_configured == total_agents` stated similarly? [Measurability, Spec §FR-020]

## Plan & Design Alignment (re-verify 2026-05-24)

- [ ] CHK019 - Is the WARN log event name `app_dashboard_recommendation_compute_failed` (Research §FE) declared in a single canonical location so other consumers (alerts, dashboards) can grep for it? [Clarity, Research §FE]
- [ ] CHK020 - Is the timestamp format (Research §TS: ISO-8601 UTC ms) consistent with other FEAT-011 observability surfaces (cited in research.md)? [Consistency, Research §TS]
- [ ] CHK021 - Do research.md or data-model.md state that the WARN log is the ONLY operator-visible signal of recommendation compute failure (no metric, no JSONL event)? [Boundary, Research §FE]
- [ ] CHK022 - Is the determinism guarantee (Research §CC) observable — i.e., can an operator infer that the same dashboard state will yield the same recommendation without reading source code? [Clarity, Research §CC]
