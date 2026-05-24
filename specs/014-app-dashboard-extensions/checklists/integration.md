# Integration Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for cross-feature contract assumptions and consumer expectations.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Upstream Dependencies (What FEAT-014 Consumes)

- [ ] CHK001 - Is the contract this feature consumes from FEAT-003/004 (container state vocabulary, pane discovery semantics) named with a specific reference? [Dependency, Gap]
- [ ] CHK002 - Is the contract this feature consumes from FEAT-007 (`log-attached` / `log-detached` semantics, what counts as "ever succeeded") named with a specific reference? [Dependency, Gap, Spec §FR-006]
- [ ] CHK003 - Is the contract this feature consumes from FEAT-010 (route-skip event shape, timing source, emission triggers) named with a specific reference? [Dependency, Spec §FR-008, §Clarifications Q7]
- [ ] CHK004 - Is the contract this feature extends from FEAT-011 (v1.0 dashboard fields, minor-evolution rules, handshake) named with a specific reference? [Dependency, Spec §Assumptions, §FR-013]
- [ ] CHK005 - Is the FEAT-006 agent-registration contract (when an agent counts as "registered") referenced rather than reinvented? [Dependency, Gap, Spec §FR-020]

## Downstream Consumers (What FEAT-014 Provides)

- [ ] CHK006 - Is FEAT-012 named as the primary consumer and the contract surface FEAT-012 will read enumerated? [Completeness, Spec §Assumptions]
- [ ] CHK007 - Are requirements stated for *other* potential consumers (CLI, monitoring scripts, future apps) using the same fields, or is FEAT-012 declared the sole v1.1 consumer? [Gap]

## Contract Versioning Touchpoints

- [ ] CHK008 - Is the v1.0→v1.1 advertisement mechanism (`app.hello` minor range) the same surface FEAT-011 already specifies, or is a new field implied? [Consistency, Spec §FR-013, §Clarifications Q10]
- [ ] CHK009 - Is the requirement that `client_app_contract_major == 1` clients still see v1.1 fields stated as a daemon-side MUST (not just a client-side ignore-unknown)? [Clarity, Spec §Clarifications Q10]

## Failure Mode Propagation

- [ ] CHK010 - Is the requirement defined for how an upstream failure (e.g., container scanner unavailable) translates into v1.1 field values (`discovery-degraded`, `subsystem_degraded` recommendation)? [Coverage, Spec §FR-002, §FR-010]
- [ ] CHK011 - Is the requirement defined for how an upstream FEAT-010 ring buffer reset (daemon restart) is observable to clients (just a `0` count) versus needing a separate "buffer reset" indicator? [Clarity, Spec §FR-008]

## External Format Stability

- [ ] CHK012 - Are field-name spellings (hyphens vs underscores) stated as part of the wire contract, not merely internal naming preferences? [Clarity, Spec §Clarifications Q12]

## Scenario Coverage

- [ ] CHK013 - Is the integration scenario "v1.1 daemon + v1.0 client" covered by a dedicated requirement and acceptance scenario? [Coverage, Spec §US4, §FR-014]
- [ ] CHK014 - Is the integration scenario "v1.0 daemon + v1.1-aware client" specified, or explicitly declared out of scope? [Gap]
- [ ] CHK015 - Is the integration scenario "FEAT-010 emitting unknown skip event shape" handled by the ring buffer model, or does it require a contract guarantee at the FEAT-010 boundary? [Gap, Spec §FR-008]

## Plan & Design Alignment (re-verify 2026-05-24)

- [ ] CHK016 - Does plan.md's placement of `skip_counter.py` under `src/agenttower/routing/` (not under `app_contract/`) include a stated rationale, so the placement decision survives later refactors? [Clarity, Plan §Structure Decision]
- [ ] CHK017 - Does plan.md confirm that the FEAT-010 routing worker is the sole writer of the ring buffer (no other module calls `record_skip`)? [Coverage, Plan §Source Code]
- [ ] CHK018 - Does plan.md confirm that `app_contract/dashboard.py` is the sole reader of the ring buffer (no other module calls `count_in_window`)? [Coverage, Plan §Source Code]
- [ ] CHK019 - Is the integration between the v1.1 version bump and FEAT-011's `app.hello` advertisement described in plan.md, so an implementer knows where the supported-minor-range advertisement widens? [Traceability, Plan §Source Code]
- [ ] CHK020 - Are downstream consumers other than FEAT-012 still declared out of scope, or did plan.md silently introduce a new consumer? [Boundary, Plan §*]

## Post-Remediation Audit (commit 457d5c2)

- [ ] CHK021 - Does T026's prescription to add an "App Contract Evolution — v1.1 (FEAT-014)" subsection to `specs/011-app-backend-contract/contracts/app-methods.md` cross a feature-spec boundary that may require a coordinated PR (FEAT-014 PR editing FEAT-011's specs dir vs. a separate FEAT-011-side follow-up PR)? [Boundary, Tasks T026, Spec Kit Convention]
- [ ] CHK022 - Does T023's new file `tests/contract/test_v1_0_compat.py` collide with any FEAT-011 test file naming convention, and does its "parametrized over `test_app_*.py` modules" selector correctly exclude the FEAT-014 extensions to those same files (avoiding circular re-run)? [Risk, Tasks T023, FEAT-011 Source Code]
