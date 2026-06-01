# Error Handling Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for failure-mode definitions, fallback behaviors, and degraded-state semantics.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Failure Mode Enumeration

- [x] CHK001 - Are all failure modes that can affect a v1.1 dashboard response enumerated (compute failure, scanner degraded, container inactive, no containers, no panes, no routes, blocked queue, daemon restart)? [Completeness, Spec §FR-010, §FR-021] [NEEDS-CLARIFY-R1, R1-resolved: Clarifications §Session 2026-05-24-r1 Q5 — reuse FEAT-011 readiness semantics]
- [x] CHK002 - Is the difference between "field not yet populated" (e.g., post-restart zero count) and "field cannot be computed" (compute failure) clearly distinguished in the contract? [Clarity, Spec §FR-008, §FR-021] [NEEDS-CLARIFY-R1, R1-resolved: spec.md §FR-025]
- [X] CHK003 - Are upstream-dependency failures (FEAT-010 worker stalled, container scanner returns no data) specified to bucket into `discovery-degraded` / `subsystem_degraded` rather than crash the dashboard? [Coverage, Spec §FR-002, §FR-010]

## Compute-Failure Fallback

- [X] CHK004 - Is FR-021 stated such that both `recommended_next_action` AND `recommended_next_action_refreshed_at` are nulled together, never one without the other? [Clarity, Spec §FR-021]
- [X] CHK005 - Is the requirement explicit that compute failure MUST NOT degrade the rest of the v1.1 payload (`counts.panes.by_state`, `counts.agents.by_state`, route counts)? [Coverage, Spec §FR-021]
- [X] CHK006 - Is the requirement defined for what observability the daemon emits when a recommendation compute failure occurs (log line, metric, none)? [Gap]

## Degraded-State Semantics

- [X] CHK007 - Is "degraded subsystem must win by precedence" expressed both as an Edge Case bullet and as a testable FR/SC pair? [Consistency, Spec §Edge Cases, §FR-010, §SC-003]
- [x] CHK008 - Is the requirement defined for whether a degraded subsystem suppresses *other* v1.1 fields (e.g., are `panes.by_state` counts still trustworthy when `subsystem_degraded`)? [Gap, Spec §FR-010, §FR-002] [NEEDS-CLARIFY-R1, R1-resolved: spec.md §FR-026]
- [X] CHK009 - Is "`subsystem_degraded` always has `target: null`" stated in the spec? (Clarifications Q9 Option B's wording mentioned it but Option A was chosen — confirm the constraint is captured somewhere durable.) [Gap, Spec §Clarifications Q9, §FR-011]

## Recovery Requirements

- [X] CHK010 - Are the post-daemon-restart requirements specified for every transient state (`recently_skipped_count` → 0, recommendation cache → none-by-design, all other dashboard fields → recomputed from current daemon state)? [Coverage, Spec §FR-008, §Clarifications Q7]
- [x] CHK011 - Is the requirement defined for whether a partially-restarted daemon (some subsystems up, others down) must coherently report `subsystem_degraded`, or whether it may emit inconsistent partials? [Gap, Spec §FR-010] [NEEDS-CLARIFY-R1, R1-resolved: spec.md §FR-026 partial-restart coherence]

## Edge Cases

- [X] CHK012 - Are zero-row edge cases (no panes, no agents, no routes, no recent skips, no recommendation) all enumerated with required output values? [Completeness, Spec §Edge Cases, §FR-003]
- [X] CHK013 - Are boundary-time edge cases (skip event exactly at the window edge, recommendation recomputed at exactly the same timestamp) specified? [Coverage, Spec §Edge Cases]
- [X] CHK014 - Is the edge case "future recommendation code emitted to older client" covered by an existing FR (FR-012)? [Coverage, Spec §FR-012, §Edge Cases]
- [x] CHK015 - Is the edge case "reserved state bucket exists before populated" specified — it's named in Edge Cases but is the FR/SC consequence stated? [Coverage, Spec §Edge Cases] [EDIT-applied: spec.md §FR-003 now covers reserved future buckets emitting 0]

## Error Propagation Boundaries

- [X] CHK016 - Is the requirement defined that v1.1-additive-field errors MUST NOT change v1.0 method-level error codes? [Completeness, Spec §FR-014]
- [X] CHK017 - Is the requirement defined that no new error code is introduced to the wire contract for v1.1? [Gap, Spec §FR-014]

## Coverage of Scenario Classes

- [X] CHK018 - Primary error path (recommendation compute failure) covered? [Coverage, Spec §FR-021]
- [X] CHK019 - Alternate error path (degraded subsystem coexisting with lower-priority conditions) covered? [Coverage, Spec §SC-003, §US3]
- [X] CHK020 - Recovery path (daemon restart wipes skip ring buffer) covered? [Coverage, Spec §FR-008, §US2 acceptance #3]
- [X] CHK021 - Non-functional error path (latency budget under load during a degraded state) covered? [Gap, Spec §SC-006]

## Plan & Design Alignment (re-verify 2026-05-24)

- [X] CHK022 - Does Research §FE specify both the response-side behavior (paired nulls) AND the daemon-internal observability (WARN log + stable event name)? [Completeness, Research §FE]
- [X] CHK023 - Is the stable event name `app_dashboard_recommendation_compute_failed` documented only in research.md, and *absent* from dashboard-v1_1.md (correctly daemon-internal, not wire)? [Boundary, Research §FE, Contracts dashboard-v1_1.md]
- [X] CHK024 - Does the try/except boundary in plan.md (`dashboard.py` wraps `compute_recommendation`) prevent the recommendation from raising into the dispatcher, which would otherwise surface as an error envelope? [Coverage, Plan §Source Code, Spec §FR-021]
- [X] CHK025 - Is "the rest of the v1.1 payload is unaffected" (FR-021) reflected as code-level isolation (try/except boundary) in plan.md, not just a documentation aspiration? [Measurability, Plan §Source Code, Spec §FR-021]
- [X] CHK026 - Does the log level chosen for compute failure (WARN, not ERROR) match the stated rationale that the dashboard remained operational? [Consistency, Research §FE]
