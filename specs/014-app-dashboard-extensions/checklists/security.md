# Security Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for authorization, data exposure, and resource-exhaustion concerns introduced by v1.1.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Authorization Surface

- [x] CHK001 - Is the requirement that `app.dashboard` access control is inherited unchanged from FEAT-011 (no new auth requirement for v1.1 fields) stated explicitly? [Gap, Spec §FR-014] [EDIT-applied: spec.md §FR-023 — auth inherited unchanged from FEAT-011]
- [x] CHK002 - Is the requirement defined for whether `recommended_next_action.target` can leak identifiers that a less-privileged client should not see? [Gap, Spec §FR-011] [NEEDS-CLARIFY-R1, R1-resolved: spec.md §FR-011 — target.id opaque]

## Data Exposure

- [x] CHK003 - Is the requirement defined that `title` and `detail` strings must not contain operator-only secrets, internal paths, or credentials? [Gap, Spec §FR-011] [NEEDS-CLARIFY-R1, R1-resolved: spec.md §FR-011 + closed-sets-v1_1.md §Per-code Templates — template discipline IS scrubbing]
- [x] CHK004 - Is the requirement defined that `target.id` values are opaque identifiers and not, e.g., container labels containing sensitive metadata? [Gap, Spec §FR-011] [NEEDS-CLARIFY-R1, R1-resolved: spec.md §FR-011 — target.id opaque]
- [x] CHK005 - Are the rules for "ignore unknown future recommendation codes" stated such that an injected unknown code cannot trigger unsafe client behavior? [Gap, Spec §FR-012] [EDIT-applied: spec.md §FR-012 — clients silently ignore unknown values, never display verbatim]

## Resource Exhaustion

- [ ] CHK006 - Is the in-memory ring buffer for FEAT-010 skips bounded by a stated maximum size, so a hostile or malfunctioning FEAT-010 worker cannot exhaust daemon memory? [Gap, Spec §FR-008]
- [ ] CHK007 - Is the cost of recompute-per-call bounded so a client cannot DoS the daemon by polling at maximum rate? [Gap, Spec §Clarifications Q8]
- [ ] CHK008 - Are size caps on `title`/`detail` stated as security boundaries (preventing oversized response payloads), not just contract preferences? [Clarity, Spec §FR-011]

## Failure-Mode Safety

- [ ] CHK009 - Is the requirement defined that compute failure MUST NOT leak internal error detail into the dashboard response (FR-021 emits `null`, not the error)? [Clarity, Spec §FR-021]
- [x] CHK010 - Is the requirement defined that v1.1-additive failure paths never expose v1.0 fields that should have been suppressed for the calling client? [Gap, Spec §FR-014, §FR-021] [NEEDS-CLARIFY-R1, R1-resolved: spec.md §FR-023 — no per-caller suppression]

## Compliance & Audit Surface

- [ ] CHK011 - Is the requirement that recently-skipped routes is NOT durable audit history (and so MUST NOT be relied on for compliance) stated explicitly? [Clarity, Spec §Clarifications, §Assumptions]
- [x] CHK012 - Is the requirement that no PII or user-identifying data is introduced by v1.1 fields stated explicitly? [Gap] [EDIT-applied: spec.md §FR-024 — no PII in v1.1 fields]

## Plan & Design Alignment (re-verify 2026-05-24)

- [ ] CHK013 - Does Research §RB's 10 000-entry hard cap (with drop-oldest) address the resource-exhaustion concern from CHK006 in a way a unit test can assert? [Resolution, Research §RB]
- [ ] CHK014 - Does Research §FE's null-fallback prevent leaking internal exception detail into the dashboard response, closing CHK009? [Resolution, Research §FE]
- [ ] CHK015 - Is the WARN log content for compute failure documented as scrubbed of secrets — i.e., no recommendation-input state dumped into the log line? [Gap, Research §FE]
- [ ] CHK016 - Is FEAT-011's inherited host-only constraint (bench-container peers rejected) explicitly carried forward in plan.md §Constraints? [Consistency, Plan §Constraints]
