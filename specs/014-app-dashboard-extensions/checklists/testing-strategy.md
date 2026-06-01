# Testing Strategy Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for the test-coverage requirements stated in the spec — i.e., is the spec itself prescriptive enough about what must be tested?
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Test Surface Enumeration

- [X] CHK001 - Does FR-017 enumerate every test category needed, or could a reader read it and miss a test type? [Completeness, Spec §FR-017]
- [X] CHK002 - Are per-state aggregation tests specified in terms of input fixture and expected bucket counts? [Measurability, Spec §FR-017, §SC-001]
- [X] CHK003 - Are recently-skipped-route tests specified for both in-window and out-of-window events (and the boundary)? [Coverage, Spec §FR-017, §SC-002]
- [X] CHK004 - Are recommendation-precedence tests specified for all seven codes (per SC-003, broadened in the prior turn to cover an adjacent-pair first-match)? [Completeness, Spec §SC-003]
- [X] CHK005 - Is the v1.0 compatibility regression test set specified (entire v1.0 contract test suite passes unchanged against a v1.1 daemon)? [Completeness, Spec §SC-004]
- [X] CHK006 - Is the v1.1 contract single-envelope shape test specified (one call, all new fields present and correctly typed)? [Completeness, Spec §SC-005]
- [X] CHK007 - Is the dashboard latency budget test specified with a measurement methodology and fixture size? [Measurability, Spec §SC-006]

## Test Quality Properties

- [X] CHK008 - Is each FR traceable to at least one SC that would observably fail if the FR were not implemented? [Traceability, Spec §FR-*, §SC-*]
- [X] CHK009 - Are fixture states for each recommendation code described in sufficient detail that two independent implementers would build the same fixture? [Clarity, Spec §SC-003, §US3 Independent Test]
- [X] CHK010 - Is "loading fixture states for each recommendation code" specified for all seven codes, not just `subsystem_degraded` and `all_clear`? [Coverage, Spec §US3 Independent Test]

## Cross-Cutting Test Requirements

- [X] CHK011 - Are tests required for the panes cross-check equalities (FR-019) as separate cases from the per-bucket aggregation tests? [Gap, Spec §FR-019]
- [X] CHK012 - Are tests required for the agent partition rule (`active` + `inactive` + `partially_configured` == total)? [Gap, Spec §FR-020]
- [X] CHK013 - Are tests required for the orthogonality of `log-attached`/`log-detached` (sum may exceed total)? [Coverage, Spec §FR-006]
- [X] CHK014 - Are tests required for compute-failure null fallback (FR-021), including the assertion that other v1.1 fields are unaffected? [Gap, Spec §FR-021]

## Test Determinism

- [X] CHK015 - Are tests required to fix the daemon clock or otherwise make `recently_skipped_window_ms` boundary tests deterministic? [Gap, Spec §FR-008]
- [X] CHK016 - Are tests required to ensure recommendation recomputation is deterministic for a fixed input state (no flakes from concurrent recomputes returning different first-matches)? [Gap, Spec §Clarifications Q8]

## Scenario Class Coverage

- [X] CHK017 - Primary scenarios (US1/US2/US3 happy paths) — are tests required? [Coverage, Spec §US1-§US3]
- [X] CHK018 - Alternate scenarios (mixed/empty fixtures) — are tests required? [Coverage, Spec §US1 acceptance #3, §US2 acceptance #2]
- [X] CHK019 - Exception scenarios (compute failure, degraded subsystem) — are tests required? [Coverage, Spec §SC-003, §FR-021]
- [X] CHK020 - Recovery scenarios (daemon restart resets skip count) — are tests required? [Coverage, Spec §US2 acceptance #3]
- [X] CHK021 - Non-functional scenarios (latency budget) — are tests required? [Coverage, Spec §SC-006]

## Plan & Design Alignment (re-verify 2026-05-24)

- [X] CHK022 - Does plan.md's tests/ layout name a test file for every FR-001..FR-021, directly or as part of a named omnibus test? [Traceability, Plan §Source Code tests/]
- [X] CHK023 - Are the two new unit test files (`test_recommendations.py`, `test_skip_counter.py`) described in plan.md with specific assertion targets that map to FRs/SCs? [Completeness, Plan §Source Code tests/unit]
- [X] CHK024 - Is the SC-003 (b) adjacent-pair coverage explicitly called out in plan.md's `test_recommendations.py` description? [Traceability, Plan §Source Code tests/unit, Spec §SC-003]
- [X] CHK025 - Does the extended `test_app_dashboard.py` description name the FR-019 cross-check, FR-020 partition, and FR-021 null-fallback as separate assertion targets, not bundled? [Measurability, Plan §Source Code tests/unit]
- [X] CHK026 - Is the SC-006 latency assertion in `test_story1_dashboard_bootstrap.py` consistent with FEAT-011's existing latency assertion (same fixture, same measurement methodology)? [Consistency, Plan §Source Code tests/integration]
- [X] CHK027 - Are all four scenario classes (Primary, Alternate, Exception, Recovery) named in plan.md's test descriptions, or only the Primary path? [Coverage, Plan §Source Code tests/*]
- [X] CHK028 - Is the determinism property for concurrent dashboard calls (Research §CC) named in any test file in plan.md? [Gap, Research §CC, Plan §Source Code tests/]
- [X] CHK029 - Are tests required for the `app_dashboard_recommendation_compute_failed` log event name (Research §FE), or is log-line content explicitly out of scope? [Gap, Research §FE]
