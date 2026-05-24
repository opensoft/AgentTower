# Versioning & Compatibility Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for the additive-minor evolution model and v1.0/v1.1 coexistence rules.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Version Advertisement

- [ ] CHK001 - Is the v1.0→v1.1 bump described both as "new advertised minor" and "supported minor range maximum includes v1.1"? [Clarity, Spec §FR-013]
- [ ] CHK002 - Is the absence of a major-version bump stated explicitly as a requirement (this is a minor; majors are reserved for breaking change)? [Completeness, Spec §FR-013, §FR-014]
- [ ] CHK003 - Is the requirement defined for how a v1.1 daemon should respond to a client advertising a major version > 1 (FR-014 says "existing major-version rejection behavior remains unchanged" — is "unchanged" defined elsewhere with enough detail to test)? [Traceability, Spec §FR-014, §US4 acceptance #2]

## Additive-Minor Discipline

- [ ] CHK004 - Is "additive" defined in terms of what specifically may be added (new fields, new closed-set values) and what may not (removing fields, changing types, narrowing closed sets)? [Completeness, Spec §FR-014, §Assumptions]
- [ ] CHK005 - Is the requirement that v1.0 fields' types and values remain identical in a v1.1 response stated as MUST? [Completeness, Spec §FR-014]
- [ ] CHK006 - Is the requirement that v1.0 error codes are not redefined or extended by v1.1 stated as MUST? [Completeness, Spec §FR-014]

## Forward Compatibility (Future Codes & Fields)

- [ ] CHK007 - Is the rule "clients ignore unknown future recommendation codes" stated as a client-side contract obligation, not just a daemon-side hope? [Clarity, Spec §FR-012, §Edge Cases]
- [x] CHK008 - Is the analogous rule "clients ignore unknown future closed-set values for PaneState/AgentState/target.kind" stated? [Gap, Spec §FR-012] [EDIT-applied: spec.md §FR-012 generalized to PaneState + AgentState + target.kind + recommendation code]
- [ ] CHK009 - Is there a requirement for the v1.1 daemon to ALSO ignore unknown future client-side fields (symmetric forward compat), or is that explicitly out of scope? [Gap] [NEEDS-CLARIFY-R2]

## Capability Flag Discipline

- [ ] CHK010 - Is the absence of new capability flags stated as a deliberate requirement (FR-015) and not a documentation gap? [Completeness, Spec §FR-015]
- [ ] CHK011 - Is the criterion for when a future v1.x field WOULD require a capability flag stated, or is that deferred to a later minor? [Gap] [NEEDS-CLARIFY-R2]

## Emission Gating

- [ ] CHK012 - Is the rule "always emit v1.1 fields once daemon advertises v1.1, regardless of `client_app_contract_major`" stated as a MUST in an FR, not only in the Clarifications section? [Traceability, Spec §Clarifications Q10, §FR-013]
- [ ] CHK013 - Is the alternative ("suppress v1.1 fields when client major == 1") explicitly rejected so the spec reader cannot accidentally implement it? [Clarity, Spec §Clarifications Q10]

## Test Coverage of Compatibility

- [ ] CHK014 - Is the requirement defined that the entire v1.0 contract test suite runs unchanged against a v1.1 daemon (SC-004 covers this)? [Coverage, Spec §SC-004]
- [ ] CHK015 - Is the requirement defined for a test that confirms a v1.0 client receives v1.1 fields and ignores them without error? [Gap, Spec §US4]

## Scope Boundary

- [ ] CHK016 - Is the boundary "FEAT-014 introduces v1.1 only, not v1.2 or v2.0 plans" stated, to prevent scope creep into adjacent minors? [Gap, Spec §FR-018]

## Plan & Design Alignment (re-verify 2026-05-24)

- [ ] CHK017 - Does plan.md name the exact module (`versioning.py`) where the `"1.0" → "1.1"` advertisement bump happens, so a reviewer can locate the one-line change? [Traceability, Plan §Source Code]
- [ ] CHK018 - Does data-model.md §AppContractVersion show the v1.0 and v1.1 values side-by-side, so a diff reviewer can spot a regression at a glance? [Clarity, Data Model §AppContractVersion]
- [ ] CHK019 - Is the supported-minor-range advertisement (range max widens to include 1.1) described in addition to the version-string change, so range-checking clients aren't surprised? [Completeness, Data Model §AppContractVersion]
- [ ] CHK020 - Does plan.md confirm `capability_flags` remains `{}` at v1.1 (FR-015) and that no v1.1 field gates on a capability flag? [Consistency, Plan §Constraints, Spec §FR-015]
- [ ] CHK021 - Does the quickstart §Step 1 assertion `daemon_app_contract_version == "1.1"` use exact-string equality and NOT a `startswith("1.")` substring match (which would mask a v1.2 advertisement during a v1.1 test)? [Clarity, Quickstart §Step 1]
