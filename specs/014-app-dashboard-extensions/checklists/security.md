# Security Requirements Quality Checklist: App Dashboard Extensions v1.1

**Purpose**: Audit requirements quality for authorization, data exposure, and resource-exhaustion concerns introduced by v1.1.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Authorization Surface

- [ ] CHK001 - Is the requirement that `app.dashboard` access control is inherited unchanged from FEAT-011 (no new auth requirement for v1.1 fields) stated explicitly? [Gap, Spec §FR-014]
- [ ] CHK002 - Is the requirement defined for whether `recommended_next_action.target` can leak identifiers that a less-privileged client should not see? [Gap, Spec §FR-011]

## Data Exposure

- [ ] CHK003 - Is the requirement defined that `title` and `detail` strings must not contain operator-only secrets, internal paths, or credentials? [Gap, Spec §FR-011]
- [ ] CHK004 - Is the requirement defined that `target.id` values are opaque identifiers and not, e.g., container labels containing sensitive metadata? [Gap, Spec §FR-011]
- [ ] CHK005 - Are the rules for "ignore unknown future recommendation codes" stated such that an injected unknown code cannot trigger unsafe client behavior? [Gap, Spec §FR-012]

## Resource Exhaustion

- [ ] CHK006 - Is the in-memory ring buffer for FEAT-010 skips bounded by a stated maximum size, so a hostile or malfunctioning FEAT-010 worker cannot exhaust daemon memory? [Gap, Spec §FR-008]
- [ ] CHK007 - Is the cost of recompute-per-call bounded so a client cannot DoS the daemon by polling at maximum rate? [Gap, Spec §Clarifications Q8]
- [ ] CHK008 - Are size caps on `title`/`detail` stated as security boundaries (preventing oversized response payloads), not just contract preferences? [Clarity, Spec §FR-011]

## Failure-Mode Safety

- [ ] CHK009 - Is the requirement defined that compute failure MUST NOT leak internal error detail into the dashboard response (FR-021 emits `null`, not the error)? [Clarity, Spec §FR-021]
- [ ] CHK010 - Is the requirement defined that v1.1-additive failure paths never expose v1.0 fields that should have been suppressed for the calling client? [Gap, Spec §FR-014, §FR-021]

## Compliance & Audit Surface

- [ ] CHK011 - Is the requirement that recently-skipped routes is NOT durable audit history (and so MUST NOT be relied on for compliance) stated explicitly? [Clarity, Spec §Clarifications, §Assumptions]
- [ ] CHK012 - Is the requirement that no PII or user-identifying data is introduced by v1.1 fields stated explicitly? [Gap]

## Plan & Design Alignment (re-verify 2026-05-24)

- [ ] CHK013 - Does Research §RB's 10 000-entry hard cap (with drop-oldest) address the resource-exhaustion concern from CHK006 in a way a unit test can assert? [Resolution, Research §RB]
- [ ] CHK014 - Does Research §FE's null-fallback prevent leaking internal exception detail into the dashboard response, closing CHK009? [Resolution, Research §FE]
- [ ] CHK015 - Is the WARN log content for compute failure documented as scrubbed of secrets — i.e., no recommendation-input state dumped into the log line? [Gap, Research §FE]
- [ ] CHK016 - Is FEAT-011's inherited host-only constraint (bench-container peers rejected) explicitly carried forward in plan.md §Constraints? [Consistency, Plan §Constraints]
