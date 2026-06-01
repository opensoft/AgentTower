# Plan & Design Alignment Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit cross-artifact requirements quality — is the spec / plan / research / data-model / contracts / quickstart surface internally coherent, fully traceable, and free of drift?
**Created**: 2026-05-24
**Mode**: max-coverage re-verify with explicit plan-alignment emphasis (`/speckit-checklist` invoked as `reverify aligned with plan and full and deepest coverage`)
**Source artifacts**: [spec.md](../spec.md), [plan.md](../plan.md), [research.md](../research.md), [data-model.md](../data-model.md), [contracts/dashboard-v1_1.md](../contracts/dashboard-v1_1.md), [contracts/closed-sets-v1_1.md](../contracts/closed-sets-v1_1.md), [quickstart.md](../quickstart.md)

This file complements the per-domain checklists in this folder by examining alignment *between* artifacts. Each per-domain file also gained a "Plan & Design Alignment (re-verify 2026-05-24)" section in the same pass for items that naturally fit a domain.

## Spec → Plan Traceability

- [X] CHK001 - Does plan.md identify every FR (FR-001..FR-028) with the module that owns it, or explicitly mark it out-of-scope per FR-018? [Traceability, Plan §Source Code]
- [X] CHK002 - Does plan.md identify every SC (SC-001..SC-007) with the test file that asserts it? [Traceability, Plan §Source Code tests/, Spec §SC-*]
- [X] CHK003 - Are all four User Stories (US1–US4) mapped to named integration tests in plan.md? [Traceability, Plan §Source Code tests/integration]
- [X] CHK004 - Does every Clarifications Q-A pair have a corresponding plan/research decision pointer (i.e., is each clarification honored in the design surface)? [Consistency, Spec §Clarifications, Plan + Research §*]

## Plan → Constitution Gate Evidence

- [X] CHK005 - For each Constitution principle in plan.md §Constitution Check, is the "Evidence" cell specific enough to verify (cites concrete FRs or named modules, not generic phrases)? [Measurability, Plan §Constitution Check]
- [X] CHK006 - Is the principle II "Container-First MVP" note ("FEAT-014 is post-MVP") consistent with the spec's Assumption that FEAT-012 is the primary consumer (also post-MVP)? [Consistency, Plan §Constitution Check, Spec §Assumptions]
- [X] CHK007 - Is the principle V "Conservative Automation" claim (recommendation is advisory, not auto-executed) testable via an FR or SC, not just stated as evidence? [Acceptance Criteria, Plan §Constitution Check, Spec §FR-010]

## Research → Spec Resolution

- [X] CHK008 - Does each Research §-section close at least one `[Gap]` / `[Ambiguity]` item from the spec-only checklist suite, or is it a new decision worth a back-reference? [Traceability, Research §*]
- [X] CHK009 - Does Research §TS (timestamp format) match the wire-shape `<ISO-8601 UTC ms string>` in dashboard-v1_1.md? [Consistency, Research §TS, Contracts dashboard-v1_1.md]
- [X] CHK010 - Does Research §SS subsystem enumeration match the FEAT-011 readiness-probe list named in closed-sets-v1_1.md §TargetKind? [Consistency, Research §SS, Contracts closed-sets-v1_1.md]
- [X] CHK011 - Does Research §PB pane-bucket priority match data-model.md §PaneState bucket-assignment priority verbatim? [Consistency, Research §PB, Data Model §PaneState]
- [X] CHK012 - Does Research §PR (`partially_configured` does NOT exclude a pane from `discovered-and-registered`) preserve the FR-019 cross-check arithmetic? [Consistency, Research §PR, Spec §FR-019]
- [X] CHK013 - Does Research §FE (WARN log event for compute failure) stay strictly daemon-internal — i.e., it MUST NOT appear in the response envelope? [Boundary, Research §FE, Spec §FR-021]

## Data-Model ↔ Contracts ↔ Spec Triangulation

- [X] CHK014 - Do the four PaneState keys spell identically and appear in the same canonical order in data-model.md §PaneState, contracts/closed-sets-v1_1.md §PaneState, and contracts/dashboard-v1_1.md §counts.panes.by_state? [Consistency]
- [X] CHK015 - Do the five AgentState keys appear identically in data-model.md §AgentState, contracts/closed-sets-v1_1.md §AgentState, and dashboard-v1_1.md §counts.agents.by_state? [Consistency]
- [X] CHK016 - Do the seven recommendation codes appear identically (same spelling, same precedence order) in spec.md §FR-010, spec.md §Clarifications precedence note, data-model.md §RecommendedNextAction, and contracts/closed-sets-v1_1.md §RecommendationCode? [Consistency]
- [X] CHK017 - Do the `target.kind` closed-set values (v1.0 set + `subsystem`) match between dashboard-v1_1.md, closed-sets-v1_1.md §TargetKind, and Research §SS? [Consistency]

## Contracts ↔ Quickstart Coverage

- [X] CHK018 - Does quickstart.md exercise every required v1.1 field defined in dashboard-v1_1.md on the positive path? [Coverage, Quickstart, Contracts dashboard-v1_1.md]
- [X] CHK019 - Does quickstart.md cover the FR-021 negative path (recommendation compute failure → both fields null, rest of payload intact)? [Coverage, Quickstart §Step 6, Spec §FR-021]
- [X] CHK020 - Does quickstart.md include a v1.0-client-against-v1.1-daemon assertion (US4)? [Coverage, Quickstart §Step 7, Spec §US4]
- [X] CHK021 - Does quickstart.md cover the recommendation precedence rule with at least one adjacent-pair check, satisfying SC-003 (b)? [Coverage, Quickstart §Step 5, Spec §SC-003]

## Constitution & Scope Boundaries

- [X] CHK022 - Does plan.md's Structure Decision rationalize why `skip_counter.py` lives under `routing/` rather than `app_contract/` (avoiding inversion)? [Clarity, Plan §Structure Decision]
- [X] CHK023 - Does plan.md explicitly state that no new SQLite table, no JSONL schema change, no new error code, and no new capability flag are introduced? [Boundary, Plan §Storage, §Constraints]
- [X] CHK024 - Are all out-of-scope items from spec.md §FR-018 (FEAT-012 UI work, push updates, customizable rules, persisted history) absent from plan.md's design? [Consistency, Plan §*, Spec §FR-018]
- [X] CHK025 - Does plan.md preserve FEAT-011's host-only and local-only constraints as *inherited* (referenced) rather than *re-stated* (duplicated)? [Boundary, Plan §Constraints]
