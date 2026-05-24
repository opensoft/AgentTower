# API Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for the dashboard contract surface — response shape, fields, semantics, evolution rules, idempotency, and determinism.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Contract Surface Completeness

- [ ] CHK001 - Are all v1.1 additive fields enumerated by name at one canonical location in the spec? [Completeness, Spec §FR-001..§FR-009]
- [ ] CHK002 - Is the response envelope structure (top-level keys around `counts`, `recommended_next_action`, `recommended_next_action_refreshed_at`) specified as either a referenced contract doc or an inline schema sketch? [Completeness, Gap]
- [ ] CHK003 - Are required vs optional vs nullable distinctions made for every v1.1 field? [Completeness, Spec §FR-003, §FR-011, §FR-021]
- [ ] CHK004 - Is the type of every numeric count (`integer`, signed/unsigned, bounds) specified? [Completeness, Spec §FR-003, §FR-007]
- [ ] CHK005 - Are unit conventions for all duration fields stated (e.g., `_ms` suffix → milliseconds)? [Clarity, Spec §FR-007]

## Response Field Clarity

- [ ] CHK006 - Are the closed-set values for `recommended_next_action.code` listed exhaustively in FR-010 and matched in the Clarifications precedence note? [Completeness, Spec §FR-010, §Clarifications]
- [ ] CHK007 - Is the closed set for `target.kind` listed exhaustively, including the v1.1 addition `subsystem`? [Completeness, Spec §FR-011]
- [ ] CHK008 - Is the meaning of `target.id` per `target.kind` documented (e.g., for `target.kind == subsystem` what string forms are valid)? [Ambiguity, Spec §FR-011]
- [x] CHK009 - Are `title` and `detail` distinguishable in purpose so two different writers would generate the same prose for the same condition? [Clarity, Spec §FR-011] [EDIT-applied: contracts/closed-sets-v1_1.md §Per-code title/detail Templates]

## Idempotency & Determinism

- [ ] CHK010 - Is `app.dashboard` declared as a read-side, side-effect-free request? [Completeness, Gap]
- [ ] CHK011 - Is "recomputed on every call" reconciled with a same-input-same-output determinism guarantee, so two concurrent callers see the same code when underlying state is unchanged? [Clarity, Spec §Clarifications Q8]
- [ ] CHK012 - Is the precedence list specified as a strict total order so first-match resolution is unambiguous even for novel combinations of matching conditions? [Clarity, Spec §FR-010]
- [ ] CHK013 - Is the case where multiple `target` candidates exist for a single code (e.g., multiple unadopted panes, multiple degraded subsystems) resolved by a documented selection rule? [Gap, Spec §FR-010, §FR-011]

## Compatibility & Evolution

- [ ] CHK014 - Is the additive-minor rule explicitly stated as a requirement on both the daemon side (always-emit) and the client side (ignore-unknown)? [Completeness, Spec §FR-012, §FR-014, §Clarifications Q10]
- [ ] CHK015 - Is the v1.0→v1.1 contract version bump described in terms of an advertised supported minor range, not only a new value? [Clarity, Spec §FR-013]
- [ ] CHK016 - Are removal/renaming prohibitions on v1.0 fields, methods, and error codes stated as MUST NOT, not soft preferences? [Completeness, Spec §FR-014]
- [ ] CHK017 - Is the absence of a new capability flag stated as a deliberate requirement, not an oversight? [Completeness, Spec §FR-015]

## Error Envelope & Exception Flow

- [ ] CHK018 - Are dashboard read errors (e.g., method-level failure) specified separately from "recommendation compute failed" (which is success with nulls)? [Clarity, Spec §FR-021]
- [x] CHK019 - Is the response shape when the daemon advertises only v1.0 but is asked for v1.1 fields specified, or is it impossible by handshake construction? [Gap, Spec §FR-013] [EDIT-applied: contracts/dashboard-v1_1.md §Versioning Behavior now covers v1.0-daemon + v1.1-aware client]

## Scenario Coverage

- [ ] CHK020 - Are primary-path requirements (healthy daemon, mixed state) covered by US1/US2/US3? [Coverage, Spec §US1, §US2, §US3]
- [ ] CHK021 - Are alternate-path requirements (v1.0 client against v1.1 daemon) covered by US4? [Coverage, Spec §US4]
- [ ] CHK022 - Are exception/error requirements (compute failure, degraded subsystem, no containers) explicitly covered in FRs and acceptance scenarios? [Coverage, Spec §FR-021, §US3]
- [ ] CHK023 - Are recovery requirements (post-restart skip counter, post-restart recommendation state) covered? [Coverage, Spec §FR-008, §Clarifications Q8]
- [ ] CHK024 - Are non-functional requirements (latency budget) defined for the new fields specifically, not just inherited generally from v1.0? [Coverage, Spec §SC-006]

## Documentation Quality

- [ ] CHK025 - Is FR-016 specific enough to verify (which docs file, which sections, which closed-set value definitions must be added)? [Measurability, Spec §FR-016]

## Plan & Design Alignment (re-verify 2026-05-24)

- [ ] CHK026 - Does dashboard-v1_1.md document every v1.1 field with type, nullability, range/format, and a cross-reference to the FR or Clarifications source? [Completeness, Contracts dashboard-v1_1.md]
- [ ] CHK027 - Is the per-code `target` rule table in data-model.md §RecommendedNextAction reflected in dashboard-v1_1.md §Field-by-Field, giving a wire-test author one source of truth instead of two? [Consistency, Data Model, Contracts dashboard-v1_1.md]
- [ ] CHK028 - Does dashboard-v1_1.md's "no new error codes" statement match plan.md's "no new error code" constraint? [Consistency, Contracts dashboard-v1_1.md §Error Behavior, Plan §Constraints]
- [ ] CHK029 - Are the v1.0 fields shown in dashboard-v1_1.md (for context only) consistent with FEAT-011's actual `app.dashboard` v1.0 contract, so future drift wouldn't mislead an implementer? [Risk, Contracts dashboard-v1_1.md]
- [ ] CHK030 - Does closed-sets-v1_1.md mark v1.1 additions (specifically `subsystem` in TargetKind) so a future v1.2 reader can see what was added and when? [Clarity, Contracts closed-sets-v1_1.md §TargetKind]
- [ ] CHK031 - Is the precedence-order table in closed-sets-v1_1.md §RecommendationCode in the same numeric order (1..7) as FR-010 and the Clarifications precedence note? [Consistency, Contracts closed-sets-v1_1.md]
- [ ] CHK032 - Is the determinism guarantee from Research §CC reflected in the contract docs (so two implementers cannot disagree about whether concurrent calls may diverge)? [Coverage, Research §CC, Contracts dashboard-v1_1.md]
