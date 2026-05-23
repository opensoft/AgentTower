# Cross-Artifact Alignment Checklist: FEAT-012

**Purpose**: Validate that the five planning-side artifacts (`plan.md`, `research.md`, `data-model.md`, `contracts/*.md`, `quickstart.md`) are mutually consistent with `spec.md` and with each other. Tests the requirements / decisions themselves for alignment, not the future implementation.
**Created**: 2026-05-23 (Round 2, post-plan)
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [research.md](../research.md) | [data-model.md](../data-model.md) | [contracts/](../contracts/) | [quickstart.md](../quickstart.md)
**Scope**: spec ↔ plan ↔ research ↔ data-model ↔ contracts ↔ quickstart consistency. Specifically: every FR has a planning home; every Key Entity has a data-model home; every clarification is reflected; every research decision traces to a spec requirement or recorded gap; every contract documents what it consumes from the daemon.

## Section 1 — Spec ↔ Plan alignment

- [ ] CHK001 - Does the plan's Technical Context name every NEEDS CLARIFICATION resolved by `/speckit-clarify` round 1 and round 2 (Q14 interaction-stability, F4 helper-policy, F7 deferred stage)? [Consistency, Spec §Clarifications / Plan §Technical Context]
- [ ] CHK002 - Does the plan's Constitution Check evidence cite specific FRs (not just principle names) for each ✅ / ⚠️ entry? [Traceability, Plan §Constitution Check]
- [ ] CHK003 - Does the plan's Project Structure name the destination for every architectural concept in the spec (workspaces, sub-views, doctor, command palette, notification grouping, helper-policy snapshot, etc.)? [Completeness, Plan §Project Structure]
- [ ] CHK004 - Does the plan's Complexity Tracking explicitly justify EVERY divergence from the constitution's Technical Constraints (primary-language and CLI-only-UI), or are there unrecorded deviations? [Completeness, Plan §Complexity Tracking / Constitution §Technical Constraints]
- [ ] CHK005 - Does the plan's Performance Goals section cite every FR-062..FR-065 budget AND every measurable SC (SC-001..SC-013, SC-008a)? [Completeness, Plan §Technical Context / Spec §Success Criteria]
- [ ] CHK006 - Does the plan's Constraints section cite the FEAT-011 wire-framing caps (1 MiB request / 8 MiB response), session cap (8), and pagination cap (200)? [Completeness, Plan §Technical Context / FEAT-011 contract]
- [ ] CHK007 - Does the plan name a concrete library or built-in mechanism for every cross-cutting concern the spec introduces (i18n, kbd nav, OS notifications, theme/density, window persistence, markdown rendering, logging, doctor)? [Completeness, Plan §Primary Dependencies]

## Section 2 — Spec ↔ Research alignment

- [ ] CHK008 - Does research.md record a decision for every plan-deferred placeholder the spec carried (interaction-stability window value FR-053, latency threshold FR-074, severity color palette, helper-policy sourcing)? [Completeness, Research §R-* / Spec §Clarifications]
- [ ] CHK009 - Does every research decision (R-01..R-21) name (a) the choice, (b) the rationale, (c) at least one alternative considered, AND (d) the spec FR(s) the decision satisfies or affects? [Traceability, Research §All]
- [ ] CHK010 - Is every "Alternative considered" in research.md a real candidate (not strawman) with a credible reason for rejection — i.e. would a reviewer reading the rejection learn something? [Clarity, Research §All]
- [ ] CHK011 - Does research.md explicitly declare "no NEEDS CLARIFICATION remaining" — and is that true on inspection? [Completeness, Research §Open items]
- [ ] CHK012 - Does R-19 (helper-policy sourcing) align with `contracts/helper-policy.md` §1 and with the Q1 clarification — daemon-side via `app.*`, not file reads? [Consistency, Research R-19 / Helper-Policy §1 / Spec §Clarifications round 2 Q1]

## Section 3 — Spec ↔ Data-model alignment

- [ ] CHK013 - Does data-model.md include a freezed entity for every Key Entity in spec.md (Project, Master Summary, Sub-agent, Pane, Adopted Agent, Feature/Change Status, Handoff, Drift Signal, Validation Entrypoint, Validation Run, Validation Target, Demo Readiness Summary, Attention Item, Notification, Operator History Entry, Workspace Selection)? [Completeness, Data-model §1-2 / Spec §Key Entities]
- [ ] CHK014 - Does each daemon-owned entity in data-model.md cite the FEAT-011 `app.*` method that populates it (per contracts/app-methods-consumed.md)? [Traceability, Data-model §1]
- [ ] CHK015 - Does data-model.md encode the four F3 lifecycle transition matrices (Pane FR-014, Drift FR-034, Handoff FR-044, Validation Run FR-048) as named invariants, AND the F7-b `deferred` non-terminal rule? [Completeness, Data-model §1.4/§1.9/§1.6/§1.11 / Spec §FR-014/§FR-034/§FR-044/§FR-048/§FR-028]
- [ ] CHK016 - Does data-model.md encode the FR-071 master-qualification gate (role=master AND master-class capability) as an in-app invariant, not just a comment? [Completeness, Data-model §1.3 / Spec §FR-071]
- [ ] CHK017 - Does data-model.md state explicitly that Workspace Selection is the only persisted entity AND enumerate every daemon-owned entity that MUST NOT be persisted (FR-005, FR-069)? [Completeness, Data-model §2.1 §3]
- [ ] CHK018 - Does data-model.md carry an `asOf` field on every daemon-owned model so reconnect staleness (FR-003) is reasoning-friendly? [Consistency, Data-model §3]
- [ ] CHK019 - Does data-model.md's HelperPolicySnapshot (§1.8) match the contracts/helper-policy.md §5 snapshot shape field-for-field? [Consistency, Data-model §1.8 / Helper-Policy §5]

## Section 4 — Spec ↔ Contracts alignment

- [ ] CHK020 - Does contracts/app-methods-consumed.md map every workspace sub-view (FR-011, FR-023, FR-046) to a specific FEAT-011 method? [Completeness, App-Methods-Consumed §1-9]
- [ ] CHK021 - Does contracts/app-methods-consumed.md explicitly flag which methods are "anticipated in a FEAT-011 v1.x bump" (i.e. not yet on v1.0) so an implementer knows the dependency risk? [Clarity, App-Methods-Consumed §3 / §5]
- [ ] CHK022 - Does contracts/ux-state.md carry an example JSON for the persisted file AND a field-by-field reference matching FR-069's persisted set exactly? [Completeness, UX-State §1]
- [ ] CHK023 - Does contracts/ux-state.md state explicitly what MUST NOT appear in the file (session token, daemon-owned entities, pre-submission handoff drafts)? [Completeness, UX-State §3]
- [ ] CHK024 - Does contracts/helper-policy.md document all four resolved clarifications (Q1 sourcing, Q2 field set, Q3 override scope, Q4 repo-level override)? [Completeness, Helper-Policy §1-4]
- [ ] CHK025 - Does contracts/helper-policy.md state the FEAT-011 v1.0 absence fallback (R-19) — what happens to the handoff flow if `app.helper_policies.*` is not yet exposed? [Coverage, Helper-Policy §6]
- [ ] CHK026 - Does contracts/ux-state.md's compatibility / migration / corruption rules align with research.md R-21 forward-only migration policy? [Consistency, UX-State §2 / Research R-21]

## Section 5 — Spec ↔ Quickstart alignment

- [ ] CHK027 - Does quickstart.md map every US1 acceptance scenario (US1 §1-§6) to a numbered step? [Completeness, Quickstart §Step-1 through §Step-6]
- [ ] CHK028 - Does quickstart.md include a per-step Acceptance Check table tying each step to specific FRs and SCs? [Traceability, Quickstart §Step-* tables]
- [ ] CHK029 - Does quickstart.md cover the doctor / preflight surface (FR-009) consistent with research.md R-20 doctor implementation? [Consistency, Quickstart §Step-7 / Research R-20 / Spec §FR-009]
- [ ] CHK030 - Does quickstart.md's "Common failure modes & first-aid" table cover failure surfaces named in the spec edge-cases section without inventing new ones? [Consistency, Quickstart §Common-failure-modes / Spec §Edge Cases]
- [ ] CHK031 - Does quickstart.md mention how to run the integration-test mock-daemon harness (per research R-17) so a future engineer can validate US2..US6 against the same fixtures? [Coverage, Quickstart §Next-steps / Research R-17]

## Section 6 — Internal artifact consistency (research ↔ data-model ↔ contracts)

- [ ] CHK032 - Does research R-06 (per-OS app data paths) match contracts/ux-state.md "File location" and data-model.md's Workspace Selection persistence path discipline? [Consistency, Research R-06 / UX-State §file-location / Data-model §2.1 §write-rules]
- [ ] CHK033 - Does research R-21 (forward-only schema migrations) match contracts/ux-state.md §2 migration rules and data-model.md §2.1 schema_version handling? [Consistency, Research R-21 / UX-State §2 / Data-model §2.1]
- [ ] CHK034 - Does research R-14 (200 ms p95 latency threshold) match observability.md CHK003 expectation (per the Round-1 observability checklist) and FR-074's "documented threshold"? [Consistency, Research R-14 / Observability CHK003 / Spec §FR-074]
- [ ] CHK035 - Does research R-15 (severity color palette) name colors with WCAG AA contrast — and does it match the FR-052 / FR-025 / FR-066 chain? [Consistency, Research R-15 / Spec §FR-052/§FR-025/§FR-066]
- [ ] CHK036 - Does research R-04 (Unix socket via `dart:io`) name the supported OS matrix consistent with plan.md Target Platform (Windows 10 1803+, macOS 13+, Linux Ubuntu 22.04+)? [Consistency, Research R-04 / Plan §Target Platform]
- [ ] CHK037 - Does research R-12 (release feed) reconcile with security.md CHK029 / api-contract.md CHK039 (FR-001 + SC-009 vs FR-068 outbound HTTPS)? [Consistency, Research R-12 / Spec §FR-001/§FR-068/§SC-009]

## Section 7 — Spec ↔ Plan-artifact terminology

- [ ] CHK038 - Does every artifact use the same name for each Key Entity (e.g. "Adopted Agent" vs "Agent" vs "AdoptedAgent" — case + space variations)? [Consistency, All artifacts]
- [ ] CHK039 - Does every artifact use the same state-value strings as the spec's enums (e.g. `discovered_and_unmanaged` vs `discovered-and-unmanaged`)? [Consistency, All artifacts]
- [ ] CHK040 - Does every artifact use the same FR id format (e.g. `FR-038a` not `FR-038A` or `FR038a`)? [Consistency, All artifacts]
- [ ] CHK041 - Does every artifact use the same workspace name strings (`agent_ops`, `project_specs`, `testing_demo` per ux-state.md vs the prose names in spec FR-006)? [Consistency, UX-State §1 / Spec §FR-006]
- [ ] CHK042 - Does every artifact spell `app_contract_version` identically (per FEAT-011 wire field)? [Consistency, All artifacts]

## Section 8 — Tier-1 findings re-verification (post Codex / OpenSpec run)

These verify that the 12 spec-quality-pass Tier-1 findings actually landed in spec.md and are reflected in the plan artifacts.

- [ ] CHK043 - F1: Are the 5 new acceptance scenarios (US1 §contract-version, US2 §first-launch-project, US3 §submission-failure, US3 §supersede, US6 §grouping-rule) referenced in quickstart.md and/or integration-test plan? [Traceability, Quickstart / Plan §Project-Structure integration_test/]
- [ ] CHK044 - F2: Are entity identity rules (7 entities) reflected in data-model.md's Identity lines per §1.1..§1.16? [Consistency, Data-model §1 / Spec §Key Entities]
- [ ] CHK045 - F3: Are the 4 lifecycle transition matrices encoded as `LifecycleValidator` invariants per data-model.md §3? [Consistency, Data-model §3 / Spec §FR-014/§FR-034/§FR-044/§FR-048]
- [ ] CHK046 - F4: Is FR-038a's contract reflected in contracts/helper-policy.md AND in data-model.md §1.8 HelperPolicy/HelperPolicySnapshot? [Consistency, Helper-Policy / Data-model §1.8]
- [ ] CHK047 - F5: Is the master/agent state relationship from FR-030 reflected in data-model.md §1.3 (Master Summary as a view over Adopted Agent)? [Consistency, Data-model §1.3 / Spec §FR-030/§FR-071]
- [ ] CHK048 - F6: Is "runtime-unreachable" used consistently across all planning artifacts (no recurrence of "runtime unavailable")? [Consistency, All artifacts]
- [ ] CHK049 - F7: Is `deferred` a stage in data-model.md §1.5 FeatureChangeStatus AND treated per F7-b (non-terminal, un-defer back to definition/spec_ready) AND per F7-c (FR-039 annotation rendering reflected in ResolvedWorkItem §1.7)? [Consistency, Data-model §1.5/§1.7 / Spec §FR-028/§FR-039]
- [ ] CHK050 - F8: Is the canonical range syntax `FEAT-N..FEAT-M` referenced in the data-model.md range-resolution discussion AND in quickstart.md or integration-test fixtures? [Traceability, Data-model §1.7 / Quickstart]
- [ ] CHK051 - F9: Is FR-079 cross-referenced from data-model.md (e.g. document-rendering rule for the in-app markdown viewer)? [Consistency, Spec §FR-079 / Plan §Primary Dependencies (flutter_markdown) / Research R-09]
- [ ] CHK052 - F10: Is the expanded Workspace Selection entity reflected in contracts/ux-state.md §1 field-by-field reference? [Consistency, Spec §Key Entities / UX-State §1 / Data-model §2.1]
- [ ] CHK053 - F11: Are the 8 onboarding milestone completion criteria from FR-010 reflected in data-model.md OnboardingMilestone enum and contracts/ux-state.md onboarding_milestone_completion field? [Consistency, Data-model §2.1 / UX-State §1 / Spec §FR-010]
- [ ] CHK054 - F12: Are the 6 doctor checks from FR-009 reflected in research R-20 (doctor implementation) AND in quickstart.md §Step-7 acceptance check? [Consistency, Research R-20 / Quickstart §Step-7 / Spec §FR-009]

## Section 9 — Missing artifact items (gaps the alignment audit should surface)

- [ ] CHK055 - Are there functional requirements in spec.md that have no corresponding entry in plan.md, research.md, data-model.md, contracts/, OR quickstart.md? [Gap]
- [ ] CHK056 - Are there research decisions (R-*) that do not trace back to any spec FR or recorded gap finding? [Coverage]
- [ ] CHK057 - Are there contracts entries that describe behavior not specified in spec.md? [Coverage]
- [ ] CHK058 - Are there entities in data-model.md that have no corresponding mention in spec.md Key Entities? [Coverage]
- [ ] CHK059 - Are there quickstart steps that exercise behavior not specified in spec.md or US1 scenarios? [Coverage]
- [ ] CHK060 - Are there Spec assumptions or Out-of-Scope items that have no acknowledgment in plan.md or research.md? [Traceability]
