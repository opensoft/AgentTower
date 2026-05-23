# Plan Quality Checklist: FEAT-012 `plan.md`

**Purpose**: Validate the implementation plan document itself for quality (clarity, completeness, traceability, gate-evidence rigor). Tests the requirements / decisions written in plan.md, not the future code.
**Created**: 2026-05-23 (Round 2, post-plan)
**Feature**: [plan.md](../plan.md)
**Scope**: Summary, Technical Context, Constitution Check, Project Structure, Complexity Tracking. Sister checklist for cross-artifact alignment lives in `alignment.md`.

## Summary

- [ ] CHK001 - Is the Summary's "primary requirement" sentence specific enough that a reader who hasn't read spec.md can name what FEAT-012 delivers? [Clarity, Plan §Summary]
- [ ] CHK002 - Does the Summary identify the "technical approach" as decisions, not options (e.g. "Flutter 3.27 + Riverpod 2.x" vs "consider Flutter or Compose")? [Clarity, Plan §Summary]
- [ ] CHK003 - Does the Summary's first paragraph explicitly call out the local-only / FEAT-011-client posture so a casual reader cannot mistake this for a hosted product? [Completeness, Plan §Summary]

## Technical Context — completeness

- [ ] CHK004 - Is Language/Version pinned with a specific lower-bound (not "latest")? [Clarity, Plan §Technical Context]
- [ ] CHK005 - Does Primary Dependencies enumerate every third-party package with its version constraint (lower-bound) and its purpose, so an implementer can resolve "do I need this dependency?" without guessing? [Completeness, Plan §Primary Dependencies]
- [ ] CHK006 - Does the Storage section say "no SQLite, no embedded DB, no domain cache" loudly so an implementer is not tempted to add one? [Clarity, Plan §Storage]
- [ ] CHK007 - Does the Testing section name a concrete test stack AND a concrete mock-daemon strategy (not "test it somehow")? [Completeness, Plan §Testing]
- [ ] CHK008 - Are Target Platform versions specified as a supported floor (e.g. "Windows 10 1809+") not as a range (e.g. "modern Windows")? [Clarity, Plan §Target Platform]
- [ ] CHK009 - Does Project Type name a single canonical type (e.g. "Desktop application") so downstream tooling can derive layouts? [Clarity, Plan §Project Type]
- [ ] CHK010 - Are Performance Goals each tied to a specific spec FR or SC, not generic "should be fast"? [Traceability, Plan §Performance Goals]
- [ ] CHK011 - Does Constraints enumerate every non-functional invariant the plan inherits from spec or FEAT-011 (local-only, wire-framing caps, session caps, pagination caps, no telemetry, accessibility baseline)? [Completeness, Plan §Constraints]
- [ ] CHK012 - Does Scale/Scope cite numeric expectations consistent with the FEAT-011 scale profile (~5 projects, ~10 containers, etc.)? [Consistency, Plan §Scale/Scope]
- [ ] CHK013 - Are there any "NEEDS CLARIFICATION" markers remaining in Technical Context? [Completeness, Plan §Technical Context]

## Constitution Check — evidence rigor

- [ ] CHK014 - Does each principle row cite at least one specific FR (not just a principle name) as evidence? [Traceability, Plan §Constitution Check]
- [ ] CHK015 - Is every ⚠️ or "with note" entry accompanied by a Complexity Tracking row OR a Post-design re-check entry explaining why the deviation stands? [Completeness, Plan §Constitution Check / §Complexity Tracking]
- [ ] CHK016 - Is the Post-design re-check note present and dated relative to the Phase 1 artifacts? [Completeness, Plan §Constitution Check post-design re-check]
- [ ] CHK017 - Is the "MVP UI is CLI-only" tension reconciled with the "GUI is purely additive" claim by citing specific FEAT-002..010 CLI methods that remain unchanged, OR by reference to FEAT-011 `app.*` scriptability? [Clarity, Plan §Constitution Check IV]
- [ ] CHK018 - Does the plan cite both architecture.md and the constitution by file path when invoking their constraints? [Traceability, Plan §Constitution Check]

## Project Structure — concrete vs placeholder

- [ ] CHK019 - Does the Project Structure tree show CONCRETE paths (e.g. `apps/control_panel/lib/core/daemon/socket_client.dart`) rather than template placeholders (`src/`, `tests/`)? [Clarity, Plan §Project Structure]
- [ ] CHK020 - Does the Source Code tree call out which directories are NEW (`apps/control_panel/`) versus existing (`src/agenttower/`)? [Clarity, Plan §Project Structure]
- [ ] CHK021 - Does every workspace sub-view named in spec.md (FR-011 Dashboard/Containers/Panes/Agents/Events/Queue/Routes/Health; FR-023 Projects/Current Work/Specs/Changes/Drift; FR-046 Available Validation/Runs/Demo Readiness) have a Project Structure home? [Completeness, Plan §Project Structure features/]
- [ ] CHK022 - Does the test layout show concrete file names per integration-test scenario (one file per US, plus contract-version-skew, runtime-states, persistence)? [Completeness, Plan §Project Structure integration_test/]
- [ ] CHK023 - Is the Structure Decision sentence explicit that this is a multi-language monorepo and that Python sources are untouched? [Clarity, Plan §Structure Decision]
- [ ] CHK024 - Are per-OS packaging scripts named under `tools/` (not "to be decided in tasks.md")? [Completeness, Plan §Project Structure tools/]

## Complexity Tracking — honesty

- [ ] CHK025 - Does each Complexity Tracking row carry (a) a concrete violation, (b) a "Why Needed" reason rooted in a spec or product-decision artifact, and (c) at least one rejected simpler alternative? [Completeness, Plan §Complexity Tracking]
- [ ] CHK026 - Are the Complexity Tracking entries dated to or traceable to specific docs (e.g. `docs/product-sections-and-control-panel.md`)? [Traceability, Plan §Complexity Tracking]
- [ ] CHK027 - Is the "Dart/Flutter as second language" entry's rejected alternatives credible (Python GUI, web UI), not strawman? [Clarity, Plan §Complexity Tracking]
- [ ] CHK028 - Is the "first post-MVP GUI" entry framed as a known architectural evolution rather than as a violation that needs apology? [Clarity, Plan §Complexity Tracking]

## Scenario Coverage in the plan

- [ ] CHK029 - Does the plan address Primary flow (the happy path from launch to operate)? [Coverage, Plan §Summary / §Performance Goals]
- [ ] CHK030 - Does the plan address Alternate flows (multi-OS-user, reconnect, contract-version-skew degradation)? [Coverage, Plan §Constraints / §Target Platform]
- [ ] CHK031 - Does the plan address Exception flows (daemon-unreachable, contract-version-incompatible)? [Coverage, Plan §Constraints]
- [ ] CHK032 - Does the plan address Recovery flows (re-bootstrap, atomic UX-state writes, schema migration)? [Coverage, Plan §Storage / §Constraints]
- [ ] CHK033 - Does the plan address Non-Functional (a11y, i18n, telemetry posture, performance budgets)? [Coverage, Plan §Constraints / §Performance Goals]

## Ambiguities & gaps

- [ ] CHK034 - Are there architectural decisions in research.md that should have surfaced in the plan but did not (e.g. plan should mention crash-recovery strategy, mock-daemon harness location)? [Gap]
- [ ] CHK035 - Is the integration-test mock-daemon strategy reflected in the plan's Project Structure under `test_harness/`? [Completeness, Plan §Project Structure / Research R-17]
- [ ] CHK036 - Does the plan acknowledge anticipated FEAT-011 v1.x additions (helper-policy methods, project/handoff/drift methods) explicitly, or does it assume v1.0 covers everything? [Clarity, Plan §Storage / Contracts/]
