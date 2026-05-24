# Success Criteria coverage map

**Closes analyze findings C6 + C11** (post-Phase-3 analyze, recorded
in tasks.md T158).

Every SC-### from `specs/012-flutter-control-panel/spec.md`
§Success Criteria is one of:

- **Build-coverable** — an automated test asserts the budget.
  Listed under "Automated coverage" below with the task that owns it.
- **Operator-cohort** — a survey / user-study measure that cannot
  be asserted by code. Listed under "Operator-cohort deferred" below
  with the spec Assumption it references.

## Automated coverage

| SC | Budget | Task owning the assertion | Status |
|---|---|---|---|
| **SC-001** | Onboarding walk completes ≤ 10 min | T054 (extended via T161) | T054 lands, T161 follow-up pending |
| **SC-003** | Single-feature handoff ≤ 30 s open→submit | T097 (extended via T168) | T097 lands, T168 follow-up pending |
| **SC-004** | Preview resolved-list ≡ submitted prompt resolved-list (byte-for-byte) | T097 (extended via T169) | T097 lands, T169 follow-up pending |
| **SC-005** | Drift visible on project card ≤ 60 s | T112 (extended via T170) | T112 lands, T170 follow-up pending |
| **SC-006** | Validation run reaches `running` ≤ 2 s | T125 / T154 | T125 + T154 |
| **SC-007** | Demo Readiness updates ≤ 5 s after run resolves | T128 / T154 | T128 + T154 |
| **SC-008a** | Attention queue stable ≥ 2 s under pointer | T130 (interaction stability synthetic-clock) | T130 ✅ |
| **SC-009** | No network listener; no remote services at MVP | T155 | T155 pending |
| **SC-010** | Daemon-outage transition ≤ 2 s; revert ≤ 5 s | T055 (extended via T162) | T055 lands, T162 follow-up pending |

## Operator-cohort deferred (NOT build-coverable)

These SCs are measured against the internal Opensoft operator cohort
per spec.md §Assumptions ("Onboarding cohort and survey metrics
(SC-011, SC-012)"). Code cannot assert them; they require a survey
+ structured observation pass after a real cohort uses the app.

| SC | Measure | Assumption reference |
|---|---|---|
| **SC-002** | Operator identifies driving master + phase from card alone ≤ 5 s per project | spec.md §Assumptions "Onboarding cohort" |
| **SC-008** | Across ≥ 5 attention-item classes, operator correctly classifies + navigates in ≤ 10 s | spec.md §Assumptions "Onboarding cohort" |
| **SC-011** | Onboarding step-completion rate ≥ 90 % across 8 FR-010 milestones | spec.md §Assumptions "Onboarding cohort" |
| **SC-012** | ≥ 90 % of new operators identify driver-per-feature from card alone (post-onboarding survey) | spec.md §Assumptions "Onboarding cohort" |
| **SC-013** | After ≥ 1 prior session, returning operator names driver + phase + spec path ≤ 30 s | spec.md §Assumptions "Onboarding cohort" |

The MVP ship gate is the Automated section. The Operator-cohort
section gates the post-launch retrospective; surfacing these here
prevents the analyze pass from re-flagging them as uncovered.

## How to update this doc

When a new SC is added to `spec.md`, append a row to one of the
two tables above. If a new automated test owns an existing SC
(e.g. T170 lands and now measures SC-005's wall-clock), update
the "Task owning the assertion" column and the "Status" column.
