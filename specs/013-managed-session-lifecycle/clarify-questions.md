# Clarify Questions — FEAT-013 Alignment Cleanup (Round 3)

**Session:** 2026-05-24 (alignment cleanup)
**Spec:** [spec.md](./spec.md)
**Trigger:** `alignment-check.md` "Worth investigating" items (CHK032, CHK033, CHK034, CHK037, CHK038)
**Reply format:** Answer with the option letter (e.g., `1: A`), `recommended` to take the recommended option, or a short free-form answer (≤5 words). Multi-answer form OK: `1: A, 2: recommended, ...`.

---

## Q1. Plan back-reference to post-plan Clarifications sub-session (CHK032)

Should `plan.md` cite the spec.md "Session 2026-05-24 (post-plan review)" sub-session as the documented origin of FR-022 / FR-023 / FR-024 / SC-009?

**Recommended:** Option A — explicit back-references give a future reader a one-hop audit trail from plan to spec without searching FR IDs.

| Option | Description |
|--------|-------------|
| A | Add a one-line back-reference in plan.md (Summary or Technical Context) pointing to spec §Clarifications "post-plan review" as the FR-022/023/024 + SC-009 origin. |
| B | No — the FR IDs already provide traceability; readers can find the sub-session in spec.md without help. |
| C | Cross-reference only from research.md (where R5/R4/R8/R9 already exist), not plan.md. |

---

## Q2. User-story traceability for FR-022 / FR-023 / FR-024 / SC-009 (CHK033)

These four new requirements are arguably system-level (TTL sweep, depth bound, override capability, restart visibility). How should they be traced?

**Recommended:** Option B — each maps cleanly to an existing User Story; that preserves the "every FR/SC traces to a US" property without inventing a new US.

| Option | Description |
|--------|-------------|
| A | Mark all four as "Cross-cutting / System-level" in their FR/SC text and document that they intentionally have no User Story home. |
| B | Map each to an existing US in the FR/SC text: FR-022 / SC-009 → US3 (lifecycle / recovery); FR-023 → US3 (recreate); FR-024 → US1 (layout creation). |
| C | Add a new "User Story 4 — Operational Recovery and Operator Overrides" covering these four explicitly. |

---

## Q3. plan-review.md CHK036–041 resolution disposition (CHK034)

Are CHK036–041 closed by the spec edits alone, or do FR-022 (TTL sweep) / FR-020 + SC-009 (detail-surface) imply specific implementation footprints that need separate task capture?

**Recommended:** Option B — the spec edits do close the requirements gaps, but FR-022 and FR-020/SC-009 imply real code (sweep loop, detail-surface fields). Acknowledging that now keeps the audit trail honest.

| Option | Description |
|--------|-------------|
| A | Resolved by spec edits alone — tick CHK036–041 in plan-review.md and move on. |
| B | Spec is updated AND FR-022 / FR-020 / SC-009 imply specific implementation work to capture as tasks; tick CHK036–041 and queue the implementation tasks when `/speckit.tasks` runs. |
| C | Defer the resolution decision to `/speckit.analyze`. |

---

## Q4. Error code for FR-022 TTL-driven failures (CHK037)

FR-022's TTL sweep transitions a pending pane to `failed` with `failed_stage = pane_create` or `registration`. Should this surface a dedicated error code, or stay observable via the pane state + `failed_stage` alone?

**Recommended:** Option A — `failed_stage` is the canonical operator signal; the sweep is daemon-internal and should not invent a new closed-set code.

| Option | Description |
|--------|-------------|
| A | No new error code. TTL sweep is internal; the operator sees the resulting `failed` state + `failed_stage` (`pane_create` or `registration`) — exactly the FR-013 closed set, no new vocabulary. |
| B | Add a new `managed_pane_pending_marker_expired` error code, surfaced when an operator queries during the sweep race. |
| C | Extend `managed_pane_recreate_chain_too_deep` details schema to also cover TTL failures (as CHK037's literal phrasing suggests). |

---

## Q5. SC-006 wording vs FR-013 enum (CHK038)

FR-013 now declares the closed `failed_stage` enum. SC-006 still says "with a specific failed stage and recovery action visible to the operator" abstractly.

**Recommended:** Option A — point SC-006 at FR-013; single-source the enum and keep the SC short.

| Option | Description |
|--------|-------------|
| A | Update SC-006 to reference FR-013 by ID: "...with `failed_stage` from the FR-013 closed set and a recovery action visible to the operator." |
| B | Inline the six enum values in SC-006. |
| C | Leave SC-006 abstract; FR-013 carries the canonical enum and SC-006 stays at the success-criterion level. |

---

## How to reply

- `1: A, 2: recommended, 3: B, ...`
- `all recommended` to accept every recommendation
- `recommended except 3: A` to accept recommendations with overrides
- For any question, supply a short free-form answer (≤5 words) instead of an option letter.

## Answers

1: A

2: B

3: B

4: A

5: A

Notes:

- Add the plan back-reference to the post-plan clarifications session so FR-022, FR-023, FR-024, and SC-009 have a one-hop audit trail.
- Trace the new system-level items to existing stories: FR-022 and SC-009 to US3, FR-023 to US3, and FR-024 to US1.
- Treat CHK036-CHK041 as requirement gaps closed by spec edits, while preserving the implementation work for task generation.
- Do not add a new TTL-specific error code; the operator-facing signal is the failed pane state plus FR-013 `failed_stage`.
- Update SC-006 to reference the FR-013 closed `failed_stage` set rather than duplicating the enum.

After your replies I will:
1. Apply the answers to spec.md (FR/SC wording adjustments), plan.md (back-reference, if Q1=A), error-codes.md (if Q4≠A), and plan-review.md (if Q3 → tick boxes + amendment note).
2. Re-run a quick consistency pass on FR/SC numbering and traceability.
3. Identify any items that need to be captured as forward-pointing tasks for `/speckit.tasks` (if Q3=B).
