# Quickstart Quality Checklist: FEAT-012 `quickstart.md`

**Purpose**: Validate the Phase 1 quickstart document for US1 coverage, acceptance-check rigor, prerequisite realism, and failure-mode honesty. Tests the quickstart as a document, not the runtime behavior.
**Created**: 2026-05-23 (Round 2, post-plan)
**Feature**: [quickstart.md](../quickstart.md)
**Scope**: Prerequisites, Step 1-7, acceptance checks, failure-mode table, next steps.

## US1 acceptance-scenario coverage

- [ ] CHK001 - Does Step 1 (Launch + bootstrap) cover US1 §1 acceptance scenario (Dashboard shows daemon Healthy + ≥1 container + ≥1 pane in unmanaged state + Adopt a pane next-action)? [Completeness, Quickstart §Step-1 / Spec §US1 §1]
- [ ] CHK002 - Does Step 2 (Adopt a pane) cover US1 §2 (label + role + capability + project_path + attach_log → pane→registered, agent created, log active, view confirms)? [Completeness, Quickstart §Step-2 / Spec §US1 §2]
- [ ] CHK003 - Does Step 3 (Watch events) cover US1 §3 (classifiable output → events in observed-at order + activity stamp updates in budget)? [Completeness, Quickstart §Step-3 / Spec §US1 §3]
- [ ] CHK004 - Does Step 4 (Direct send) cover US1 §4 (non-empty payload + inline daemon response + send in recent activity + linked event)? [Completeness, Quickstart §Step-4 / Spec §US1 §4]
- [ ] CHK005 - Does Step 5 (Route management) cover US1 §5 (source+event_class+target+master_rule → route enabled, healthy + matching event creates queue row)? [Completeness, Quickstart §Step-5 / Spec §US1 §5]
- [ ] CHK006 - Does Step 6 (Outage handling) cover US1 §6 (daemon down → runtime-unreachable in 2s + per-surface placeholder + retry → live in 5s + no stale data)? [Completeness, Quickstart §Step-6 / Spec §US1 §6]

## Acceptance-check table rigor

- [ ] CHK007 - Does every Step's acceptance-check table tie each row to a specific spec FR or SC (not just prose)? [Traceability, Quickstart §Step-* tables]
- [ ] CHK008 - Does every acceptance-check table include a Pass criterion that is objectively testable (stopwatch, grep, count, etc.) rather than subjective? [Measurability, Quickstart §Step-* tables]
- [ ] CHK009 - Does Step 1's table cite the FR-062 2-second Dashboard budget? [Traceability, Quickstart §Step-1 / Spec §FR-062]
- [ ] CHK010 - Does Step 2's table cite the FR-065 5-second adopt budget? [Traceability, Quickstart §Step-2 / Spec §FR-065]
- [ ] CHK011 - Does Step 3's table cite the FR-064 2-second live-update budget? [Traceability, Quickstart §Step-3 / Spec §FR-064]
- [ ] CHK012 - Does Step 6's table cite the SC-010 2-second / 5-second outage and recovery budgets? [Traceability, Quickstart §Step-6 / Spec §SC-010]
- [ ] CHK013 - Does Step 7's table cite FR-009 (doctor 6 checks) AND FR-074 (diagnostics bundle contents)? [Traceability, Quickstart §Step-7 / Spec §FR-009 + FR-074]
- [ ] CHK014 - Does Step 7's table include the no-telemetry SC-009 / FR-074 network-trace check? [Completeness, Quickstart §Step-7 / Spec §SC-009 + FR-074]

## Prerequisite realism

- [ ] CHK015 - Are host-environment prerequisites listed with concrete commands the operator can run to verify (`agenttower preflight`, `docker ps`, `docker exec ... tmux list-panes`)? [Completeness, Quickstart §Prerequisites]
- [ ] CHK016 - Does the desktop-app prerequisite specify how to identify "first-launch onboarding has NOT been completed" so the reader can choose the right path? [Clarity, Quickstart §Prerequisites]
- [ ] CHK017 - Are the verification commands platform-aware (Linux/macOS vs Windows) where relevant? [Coverage, Quickstart §Prerequisites]
- [ ] CHK018 - Does the prerequisite list cover FEAT-011 contract version compatibility (the app's expected major matching daemon's `app_contract_version` major)? [Completeness, Quickstart §Prerequisites / Spec §FR-002]

## Failure modes

- [ ] CHK019 - Does the "Common failure modes" table cover daemon-unreachable, contract-version mismatch, adopt validation failures, classifier degradation, log-permission issues, and persisted-geometry issues — at minimum? [Completeness, Quickstart §Common-failure-modes / Spec §Edge Cases]
- [ ] CHK020 - Does each failure-mode row name a likely cause AND a concrete fix? [Clarity, Quickstart §Common-failure-modes]
- [ ] CHK021 - Are the failure modes drawn from spec.md Edge Cases AND from the planning artifacts (e.g. UX-state corruption from R-21 + UX-State §2)? [Coverage, Quickstart §Common-failure-modes]

## Scenario class coverage in the quickstart

- [ ] CHK022 - Does the quickstart cover Primary flow (Steps 1-5)? [Coverage, Quickstart §Step-1 to §Step-5]
- [ ] CHK023 - Does the quickstart cover Exception/Error flow (Step 6 outage + Step 2 validation_failed)? [Coverage, Quickstart §Step-2 / §Step-6]
- [ ] CHK024 - Does the quickstart cover Recovery flow (Step 6 retry + reconnect)? [Coverage, Quickstart §Step-6]
- [ ] CHK025 - Does the quickstart cover Non-Functional verification (Step 7 doctor + diagnostics bundle + no-telemetry)? [Coverage, Quickstart §Step-7]
- [ ] CHK026 - Does the quickstart cover Alternate flows (e.g. second launch with persisted state vs first launch with onboarding)? [Coverage, Quickstart §Step-1 §expected-subsequent-launch-behavior]

## Next-steps and integration test hooks

- [ ] CHK027 - Does the "Next steps after this quickstart passes" section name the mock-daemon harness location (per research R-17)? [Traceability, Quickstart §Next-steps / Research R-17]
- [ ] CHK028 - Does the section name the per-US integration test files (mirroring plan.md §Project Structure integration_test/)? [Consistency, Quickstart §Next-steps / Plan §Project Structure]
- [ ] CHK029 - Does the section explicitly recommend `/speckit-tasks` as the next Spec Kit command? [Clarity, Quickstart §Next-steps]

## Cross-step consistency

- [ ] CHK030 - Are state names referenced in the quickstart consistent with spec.md enums (`discovered_and_unmanaged` not "unmanaged", `queued` not "pending", etc.)? [Consistency, Quickstart / Spec §FR-014 + §FR-020]
- [ ] CHK031 - Are FEAT-011 method names referenced consistently with contracts/app-methods-consumed.md (e.g. `app.agent.register_from_pane` not `app.agent.create`)? [Consistency, Quickstart / App-Methods-Consumed §4]
- [ ] CHK032 - Are timestamps + budgets cited consistently (FR-064 said "2 seconds" everywhere it appears in the quickstart)? [Consistency, Quickstart §All]

## Audience appropriateness

- [ ] CHK033 - Is the quickstart's tone appropriate for "implementation engineers and integration testers" (the stated audience) — neither dumbing down nor assuming undocumented context? [Clarity, Quickstart §Audience]
- [ ] CHK034 - Does the quickstart avoid implementation-specific code (Dart snippets, Riverpod providers, etc.) and stay at the operator-action level? [Boundary, Quickstart §All]
- [ ] CHK035 - Does the quickstart include enough context that a new engineer can run it from scratch without reading spec.md cover-to-cover? [Coverage, Quickstart §Prerequisites + §Steps]
