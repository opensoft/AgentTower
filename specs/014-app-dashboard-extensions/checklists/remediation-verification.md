# Post-Analyze-Remediation Verification Checklist: App Dashboard Extensions v1.1

**Purpose**: Targeted delta audit of the 9 surgical edits applied during the post-`/speckit-analyze` remediation pass — does each fix actually close its finding without introducing drift between the touched file and its peers?
**Created**: 2026-05-24
**Mode**: focused delta verification (NOT a full max-coverage re-sweep)
**Scope**: only the artifact areas modified by the analyze-remediation. The 282-item suite from the prior two `/speckit-checklist` runs remains the release-gate audit.
**Source artifacts**: [spec.md](../spec.md), [plan.md](../plan.md), [research.md](../research.md), [data-model.md](../data-model.md), [contracts/dashboard-v1_1.md](../contracts/dashboard-v1_1.md), [contracts/closed-sets-v1_1.md](../contracts/closed-sets-v1_1.md), [quickstart.md](../quickstart.md), [tasks.md](../tasks.md). Commit `457d5c2` is the canonical post-remediation state on `origin/014-app-dashboard-extensions`.

Each item below verifies one of the 9 edits and asks whether the fix is congruent with the rest of the artifact set.

## I1 — Entity Name Normalization

- [X] CHK001 - Is `RecentlySkippedRoutesWindow` (no space) the only spelling used across spec.md §Key Entities, data-model.md §Entity, plan.md, and research.md? [Consistency, Spec §Key Entities, Data Model §Entity, Plan, Research]
- [X] CHK002 - Does any committed file still contain the legacy `RecentlySkippedRoutes Window` (with space) form? [Consistency, Resolution]

## A2 — FR-002 Bucket-Priority Pointer

- [X] CHK003 - Does the priority chain stated in FR-002 (`discovery-degraded` > `inactive-or-stale` > `discovered-and-registered` > `discovered-and-unmanaged`) match the priority order in `data-model.md` §PaneState verbatim? [Consistency, Spec §FR-002, Data Model §PaneState]
- [X] CHK004 - Does the FR-002 pointer to "data-model.md §PaneState" still resolve correctly after the I1 entity rename — i.e., is the section heading reachable by that name? [Traceability, Spec §FR-002, Data Model §PaneState]
- [X] CHK005 - Does Research §PB's bucket-priority statement match FR-002's (now-explicit) chain? [Consistency, Spec §FR-002, Research §PB]

## I2 — Test File Naming Note

- [X] CHK006 - Is the "Test file naming note" paragraph in plan.md placed where a reader following the source-code tree will see it before reaching the Structure Decision (i.e., immediately after the tests/integration block)? [Clarity, Plan §Source Code]
- [X] CHK007 - Does the naming note explicitly acknowledge that `test_story1_*` in FEAT-014 houses scenarios for US1/US2/US3 (not just US1), so a future maintainer doesn't mistake the file for US1-only? [Completeness, Plan §Test file naming note]

## U1 — T023 Pinned to pytest Fixture

- [X] CHK008 - Does T023's new test file name `tests/unit/test_v1_0_compat.py` conflict with any existing or planned FEAT-011 test file under `tests/unit/`? [Boundary, Tasks T023, Plan §Source Code]
- [X] CHK009 - Does T023's marker-filtered replay (`pytest tests/unit/test_app_*.py -m 'not v1_1'`) correctly identify the FEAT-011 v1.0 contract test set, or could it accidentally include FEAT-014's own test extensions (`test_app_dashboard.py` post-T005/T011/T017) and create a circular re-run? [Risk, Tasks T023, Plan §Source Code tests/unit]

## C1 — T021 Per-Assertion FR Mapping

- [X] CHK010 - Does T021's per-assertion mapping (FR-013, FR-013, FR-015, FR-014) correctly match what each sub-assertion actually tests, or has the wrong FR been assigned to a sub-assertion? [Traceability, Tasks T021, Spec §FR-013, §FR-014, §FR-015]
- [X] CHK011 - Does the bundled-but-mapped pattern in T021 set a precedent — does any OTHER task in tasks.md have multiple unrelated assertions sharing one task ID without per-assertion FR mapping? [Consistency, Tasks T021 vs Tasks *]

## U2 — T024 Citing SC-002 ≤ 500 ms Inline

- [X] CHK012 - Does the "≤ 500 ms" number cited inline in T024 match FEAT-011's actual SC-002 budget as documented in `specs/011-app-backend-contract/spec.md`? [Traceability, Tasks T024, FEAT-011 §SC-002]
- [X] CHK013 - Is the fixture-scale envelope cited in T024 ("≤ 10 containers, ≤ 200 agents, ≤ 100 routes") identical to the FEAT-011 fixture scale used by FEAT-011's existing latency test, so the methodologies are actually comparable? [Consistency, Tasks T024, FEAT-011 Scale/Scope]
- [X] CHK014 - Was the parallel reference to T001 ("no separate record step is required") propagated — i.e., does T001 still claim it is doing the recording, or has that wording been removed from T001 too? [Consistency, Tasks T001, Tasks T024]

## C2 — T026 Cross-Reference Strategy

- [X] CHK015 - Does T026's prescription to edit `specs/011-app-backend-contract/contracts/app-methods.md` (a file in FEAT-011's spec dir) create a cross-feature-spec ownership issue — i.e., should FEAT-014's PR really be editing FEAT-011's specs dir, or should the docs change go in a separate FEAT-011-side follow-up PR? [Boundary, Tasks T026, Spec Kit Convention]
- [X] CHK016 - Does the "App Contract Evolution — v1.1 (FEAT-014)" subsection name proposed by T026 follow a pattern that future minor evolutions (v1.2, v1.3, …) can reuse without renaming? [Forward-Compat, Tasks T026]

## A1 — JSON Block Rewrite in dashboard-v1_1.md

- [X] CHK017 - Does the rewritten JSON block in `contracts/dashboard-v1_1.md` still align field-for-field with the §Field-by-Field Specification section immediately below it (no field added in one but missing in the other)? [Consistency, Contracts dashboard-v1_1.md §Response, §Field-by-Field]
- [X] CHK018 - Does the "How to read this sketch" annotation correctly state the wire types (e.g., explicitly clarify that `"<int>"` is a JSON integer on the wire, not a string)? [Clarity, Contracts dashboard-v1_1.md]
- [X] CHK019 - Is the merged-JSON form (single `counts` object containing both v1.0 and v1.1 keys) consistent with how FEAT-011's existing `app.dashboard` response is structured, so a v1.0 client wouldn't see a second `counts` key on the wire? [Risk, Contracts dashboard-v1_1.md, FEAT-011 app-methods.md]

## Cross-Cutting Drift Check

- [X] CHK020 - Did any of the 9 remediation edits inadvertently invalidate an existing item in the 282-item suite that was previously passing? [Resolution, Checklists *]
- [X] CHK021 - Does the post-remediation commit (`457d5c2`) contain only the intended 23-file diff, with zero accidental source-code changes that should have been deferred per the user's "implementation paused" decision? [Boundary, Commit 457d5c2]
- [X] CHK022 - Are the 4 LOW findings deliberately left as-is (U3, D1, D2, F1) documented somewhere durable (e.g., in the analyze report or a remediation summary) so a future reviewer doesn't re-flag them? [Resolution, Analyze Report]
