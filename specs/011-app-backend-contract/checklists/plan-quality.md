# Plan Document Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality of `plan.md` itself — Technical Context completeness, Constitution Check rigor, Project Structure precision, Complexity Tracking.
**Created**: 2026-05-19
**Feature**: [plan.md](../plan.md), [spec.md](../spec.md)

## Technical Context Completeness

- [ ] CHK001 Is the **Python version** specified as a concrete value (e.g., 3.11+) rather than a range or "as needed"? [Completeness, Plan §Technical Context]
- [ ] CHK002 Are **all upstream feature dependencies** enumerated (FEAT-002 dispatcher, FEAT-003 container discovery, FEAT-004 pane discovery, FEAT-006 agent service, FEAT-007 log attachment, FEAT-008 event pipeline, FEAT-009 queue, FEAT-010 routes)? [Completeness, Plan §Primary Dependencies]
- [ ] CHK003 Is the **no new third-party Python dependency** claim documented as a non-goal? [Completeness, Plan §Primary Dependencies]
- [ ] CHK004 Are the **three in-memory stores** (sessions, scan results cap 100, idempotency dedupe cap 256/session) enumerated in Storage? [Completeness, Plan §Storage]
- [ ] CHK005 Are **all performance budgets** specified with both target and fixture (SC-002 ≤500ms cold-start with ≥1 container ≥1 agent; SC-004 ≤2s adopt; bootstrap < 50ms; readiness < 100ms; list/detail < 100ms)? [Completeness, Plan §Performance Goals]
- [ ] CHK006 Are **all constraint thresholds** quantified (pagination cap 200, recent_limit cap 50, scan wait cap 30s, request 1 MiB, response 8 MiB, idempotency dedupe scope)? [Completeness, Plan §Constraints]
- [ ] CHK007 Is the **scale envelope** quantified rather than left vague (≤10 containers, ≤200 agents, ≤1k events/day, ≤100 routes, ≤3 concurrent app sessions)? [Completeness, Plan §Scale/Scope]
- [ ] CHK008 Are **target platforms** enumerated (Linux primary, macOS, Windows host)? [Completeness, Plan §Target Platform]

## Constitution Check Rigor

- [ ] CHK009 Does each of the 5 constitution principles have **specific evidence** cited from FRs/SCs, not just a "PASS"? [Measurability, Plan §Constitution Check]
- [ ] CHK010 Is **Principle II (Container-First MVP)** justified given FEAT-011 is post-MVP — does the plan explain why post-MVP work still satisfies the container-first principle? [Clarity, Plan §Constitution Check Principle II]
- [ ] CHK011 Is **Principle III (Safe Terminal Input)** evidence linked to `app.send_input` riding FEAT-009 queue with permission gate (FR-031)? [Traceability, Plan §Constitution Check Principle III]
- [ ] CHK012 Is **Principle IV (Observable and Scriptable)** evidence linked to both legacy CLI preservation (FR-002) AND `origin = "app"` audit attribution (FR-009, FR-044, SC-008)? [Completeness, Plan §Constitution Check Principle IV]
- [ ] CHK013 Is the **post-design re-check** documented as a separate gate result (not just the pre-design gates)? [Completeness, Plan §Constitution Check]
- [ ] CHK014 Does the plan state **explicitly** that no Complexity Tracking entries are required, with rationale? [Completeness, Plan §Complexity Tracking]

## Project Structure Precision

- [ ] CHK015 Is the **new sub-package path** `src/agenttower/app_contract/` specified with all 17 module names enumerated? [Completeness, Plan §Project Structure]
- [ ] CHK016 Does each enumerated module have a **one-line purpose** documented (not just a filename)? [Clarity, Plan §Project Structure]
- [ ] CHK017 Are the **test files** enumerated by purpose (17 contract test files, 5 integration test files, 3 fixture files)? [Completeness, Plan §Project Structure]
- [ ] CHK018 Is the **"zero changes to existing modules"** claim qualified with the single exception (FEAT-002 dispatcher registration via `register()`)? [Clarity, Plan §Structure Decision]
- [ ] CHK019 Does the Structure Decision **explicitly cross-reference** the FRs that the structure satisfies (FR-002 legacy preserved, FR-004 same service layer, SC-006 no new I/O surface)? [Traceability, Plan §Structure Decision]
- [ ] CHK020 Is the **service-layer dispatch** documented operationally — which specific existing files `app_contract/mutations.py` calls into (e.g., `agents/service.py`, `routing/service.py`, `queue/service.py`)? [Clarity, Plan §Structure Decision]

## Summary Completeness

- [ ] CHK021 Does the Summary enumerate the **7 layers** of the implementation (app-session, host-only gate, bootstrap, readiness+dashboard, reads, mutations, envelope+errors)? [Completeness, Plan §Summary]
- [ ] CHK022 Is the **`app_contract_version = "1.0"`** value stated in the Summary, not buried in contracts? [Clarity, Plan §Summary]
- [ ] CHK023 Is **CLI namespace preservation** (FR-002) called out in the Summary so a reader can confirm "additive, not replacement" at a glance? [Clarity, Plan §Summary]

## Ambiguities & Gaps

- [ ] CHK024 Is the plan explicit about what happens when an upstream FEAT changes (e.g., FEAT-006 adds a role) — does FEAT-011's view models need to update, and is that an additive minor? [Gap]
- [ ] CHK025 Is there a documented **rollback / disable mechanism** for the `app.*` surface if a critical bug ships (feature flag, config disable)? [Gap]
- [ ] CHK026 Is the plan explicit about **deployment / release artifact** boundaries — is FEAT-011 a separate pip release, or bundled with the next daemon release? [Gap]
- [ ] CHK027 Is the relationship between **plan-level decisions made via research.md** and the spec FRs explicit — does the plan annotate which constraints come from research vs spec? [Traceability]

## Measurability of Plan Claims

- [ ] CHK028 Can the **"zero changes to existing modules"** claim be verified by a `git diff --stat` test in CI? [Measurability, Plan §Structure Decision]
- [ ] CHK029 Can the **"no new third-party dependency"** claim be verified by a `pyproject.toml` diff test? [Measurability, Plan §Primary Dependencies]
- [ ] CHK030 Can the **"all `app.*` methods dispatch into shared service layer"** claim be verified by a static-analysis test (e.g., import inspection)? [Measurability, Plan §Structure Decision, Spec §FR-004]
