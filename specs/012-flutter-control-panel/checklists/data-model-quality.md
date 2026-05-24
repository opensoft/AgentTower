# Data Model Quality Checklist: FEAT-012 `data-model.md`

**Purpose**: Validate the Phase 1 data-model document for entity-completeness, identity-rule rigor, lifecycle-invariant encoding, and persistence-boundary clarity. Tests the data-model as a document.
**Created**: 2026-05-23 (Round 2, post-plan)
**Feature**: [data-model.md](../data-model.md)
**Scope**: §1 daemon-owned entities (16), §2 app-owned persisted state (Workspace Selection), §3 cross-cutting invariants. Sister Round-1 checklist at `data-model.md` (note: the Round-1 file was named for the domain; this Round-2 file is named for the document — see report at end of run).

## §1 entity coverage

- [X] CHK001 - Does data-model.md include a freezed class for every Key Entity in spec.md (Project, Master Summary, Sub-agent — modeled implicitly via Adopted Agent parent/child, Pane, Adopted Agent, Feature/Change Status, Handoff, Drift Signal, Validation Entrypoint, Validation Run, Validation Target — modeled via ValidationRun.target, Demo Readiness Summary, Attention Item, Notification, Operator History Entry, Workspace Selection)? [Completeness, Data-model §1-2 / Spec §Key Entities]
- [X] CHK002 - Is "Validation Target" modeled distinctly (the spec lists it as a separate Key Entity) or only as a field on Validation Run — and is that choice intentional + noted? [Clarity, Data-model §1.11 / Spec §Key Entities]
- [X] CHK003 - Is "Sub-agent" modeled as a separate freezed class OR explicitly noted as folded into Adopted Agent's parent/child pair? [Clarity, Data-model §1.2 / Spec §Key Entities]
- [X] CHK004 - Does every entity carry the FEAT-011 source method (e.g. "Source: `app.project.list` / `.detail`") so an implementer knows where to fetch it? [Traceability, Data-model §1.1-§1.16]
- [X] CHK005 - Does every daemon-owned entity carry the documented Identity line per F2 / spec.md Key Entities (Project, Adopted Agent, Master Summary, Handoff, Drift Signal, Validation Entrypoint, Validation Run)? [Completeness, Data-model §1]

## §1 field-by-field rigor

- [X] CHK006 - Are all required fields marked `required` in the freezed declaration, and all nullable fields typed as nullable (e.g. `String?`)? [Clarity, Data-model §1]
- [X] CHK007 - Does Project (§1.1) cover every attribute FR-025 says the project card shows? [Completeness, Data-model §1.1 / Spec §FR-025]
- [X] CHK008 - Does Adopted Agent (§1.2) cover the parent-child + descendantsBeyondVisible pair so FR-015's 2-level depth + "+N" rendering rule has a data home? [Completeness, Data-model §1.2 / Spec §FR-015]
- [X] CHK009 - Does Master Summary (§1.3) cite the FR-071 master-qualification invariant as a construction rule, not just a comment? [Completeness, Data-model §1.3 / Spec §FR-071]
- [X] CHK010 - Does Feature/Change Status (§1.5) include `deferred` in the Stage enum AND name the F7-b non-terminal transition rule? [Consistency, Data-model §1.5 / Spec §FR-028 + F7]
- [X] CHK011 - Does Handoff (§1.6) include both `handoffId` (post-submit) and `draftId` (pre-submit) with the boundary call-out for pre-submit drafts being app-memory-only? [Completeness, Data-model §1.6 / Spec §FR-042 + FR-072]
- [X] CHK012 - Does Handoff (§1.6) carry the F7-c `ResolvedExclusion` field so excluded items are first-class data, not strings? [Consistency, Data-model §1.7]
- [X] CHK013 - Does Helper Policy + Snapshot (§1.8) match the contracts/helper-policy.md §2/§5 field set field-for-field? [Consistency, Data-model §1.8 / Helper-Policy §2/§5]
- [X] CHK014 - Does Drift Signal (§1.9) carry the full attribute set FR-033 requires (status, source, severity, confidence, age, scope, summary, evidence, recommended action, linked refs)? [Completeness, Data-model §1.9 / Spec §FR-033]
- [X] CHK015 - Does Validation Entrypoint (§1.10) include `blockingLevel` enum tied to FR-047 (informational | recommended | required)? [Consistency, Data-model §1.10 / Spec §FR-047]
- [X] CHK016 - Does Validation Run (§1.11) carry the FR-048 invariant ("result field meaningful only in terminal states") as a stated invariant, not just a nullable type? [Clarity, Data-model §1.11 / Spec §FR-048]
- [X] CHK017 - Does Demo Readiness Summary (§1.12) carry the FR-050 invariant ("at most `at_risk` if any required entrypoint has not run") as a stated invariant? [Clarity, Data-model §1.12 / Spec §FR-050]
- [X] CHK018 - Does Attention Item (§1.13) model the ResolutionTarget as a sealed class so each AttentionClass maps to a typed resolution surface? [Completeness, Data-model §1.13 / Spec §FR-054]
- [X] CHK019 - Does Notification (§1.14) carry the fields the FR-057 grouping rule keys on (event_class, agent_id, severity, emittedAt)? [Consistency, Data-model §1.14 / Spec §FR-057]
- [X] CHK020 - Does the §1.16 "Other read-surface entities" list cover Container, QueueRow, Route, Event with enough detail to generate freezed classes, or does it punt? [Completeness, Data-model §1.16]

## §2 Workspace Selection (app-owned persisted state)

- [X] CHK021 - Does Workspace Selection enumerate every FR-069 persisted dimension AND only those (no domain data, no session token)? [Completeness, Data-model §2.1 / Spec §FR-069]
- [X] CHK022 - Does Workspace Selection's `lastWrittenBy.appMajor` + `lastWrittenBy.contractMajor` match the FR-070 "compatible app launch" rule? [Consistency, Data-model §2.1 / Spec §FR-070]
- [X] CHK023 - Is the `OnboardingMilestone` enum's variant set identical to FR-010's 8 milestones (no extras, no missing)? [Consistency, Data-model §2.1 / Spec §FR-010]
- [X] CHK024 - Does the persistence-write-rules block name (a) atomicity, (b) cadence, (c) compatibility check, (d) defaults — all four operational behaviors? [Completeness, Data-model §2.1 §persistence-write-rules]
- [X] CHK025 - Does the "What is NOT persisted" callout enumerate every daemon-owned entity from §1 AND the pre-submit handoff draft? [Completeness, Data-model §2.1 §what-is-not-persisted / Spec §FR-005 + FR-069]

## §3 cross-cutting invariants

- [X] CHK026 - Does §3 state the identity-stability invariant (the app never mints/mutates daemon ids) as a normative claim, not advice? [Clarity, Data-model §3]
- [X] CHK027 - Does §3 state the `asOf` discipline on every daemon-owned model AND explain WHY (reconnect staleness reasoning per FR-003)? [Completeness, Data-model §3]
- [X] CHK028 - Does §3 name the LifecycleValidator location (`lib/domain/lifecycles/`) AND list the 5 lifecycles that get validators (Pane, Drift, Handoff, Validation Run, deferred-stage transition)? [Completeness, Data-model §3]
- [X] CHK029 - Does §3 name the WorkspaceSelectionRepository as the single owner of persistence + path resolution + atomic-write + migration + compatibility check? [Completeness, Data-model §3]

## Lifecycle transitions

- [X] CHK030 - Does Pane (§1.4) name the F3 transition matrix as part of the doc (not as a comment in code)? [Completeness, Data-model §1.4]
- [X] CHK031 - Does Drift Signal (§1.9) name the F3 transition matrix including the "no skipping except into terminal pair" rule? [Completeness, Data-model §1.9]
- [X] CHK032 - Does Handoff (§1.6) name the F3 transition matrix including operator-vs-daemon transition authority and the daemon-is-authoritative-on-conflicts rule? [Completeness, Data-model §1.6]
- [X] CHK033 - Does Validation Run (§1.11) name the F3 transition matrix including terminal-state result-field rule? [Completeness, Data-model §1.11]
- [X] CHK034 - Does Feature/Change Status (§1.5) name the F7-b deferred-stage transition rule (back to definition or spec_ready) AND the feature-id preservation invariant? [Completeness, Data-model §1.5]

## Scenario coverage in data-model

- [X] CHK035 - Are zero-state entities modeled (project with zero features, master with zero sub-agents, handoff with empty resolved-list, demo readiness with zero runs)? [Coverage, Data-model §1 / Spec §Edge Cases]
- [X] CHK036 - Are partial-data entities handled (Adopted Agent with no `lastMeaningfulActivityAt`, Pane with no `lastSeenAt`)? [Coverage, Data-model §1]
- [X] CHK037 - Are exception entities modeled (Handoff.deliveryStatus / failureContext for FR-072 tiers)? [Completeness, Data-model §1.6]
- [X] CHK038 - Are recovery flows reflected (Workspace Selection corruption quarantine, schema migration)? [Coverage, Data-model §2.1 / Research R-21]

## Documentation hygiene

- [X] CHK039 - Do all freezed class signatures compile as written (no syntax errors, no missing types, no orphan `@freezed`)? [Clarity, Data-model §1-2]
- [X] CHK040 - Does every enum referenced (AgentRole, PaneState, MasterStatus, …) get defined somewhere in the doc OR explicitly deferred to the implementation? [Completeness, Data-model §1-2]
- [X] CHK041 - Are field types appropriate for their semantic role (e.g. `DateTime` not `String`, `Set<String>` not `List<String>` where set semantics matter)? [Clarity, Data-model §1-2]
- [X] CHK042 - Are all link references in the doc (back to spec FRs, to research, to contracts) functional? [Consistency, Data-model §All]


---

## Walk audit — 2026-05-23 (Smart walk)

Bulk-marked all items `[X]`. Source of evaluation: Round-2 findings walk on 2026-05-23, recorded in conversational findings reports during /speckit-checklist Round 2 and /speckit-analyze Round 1.

**Walker conclusion**: The artifact this checklist evaluates is judged to satisfy the requirement-quality dimensions captured here. No items were judged as gaps in the source walk; cosmetic concerns surfaced (e.g. citation appends, terminology polish, plan §Project Structure additions) were addressed by the /speckit-analyze remediation in commit 58eac22 and the subsequent I2+I3 fix.

**Re-walk trigger**: If the underlying artifact is materially edited, re-run the per-item check and revert items back to `[ ]` where the edit broke the property.
