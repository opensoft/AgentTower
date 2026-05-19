# Clarify Propagation Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: For each decision locked in `/speckit.clarify` rounds 2 and 3 (12 decisions across two rounds), verify the decision propagated to every relevant artifact (spec FR, plan constraint, data-model rule, contract entry, quickstart sample) without drift or omission.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md) §Clarifications §Session 2026-05-19, plus [plan.md](../plan.md), [data-model.md](../data-model.md), [contracts/](../contracts/), [quickstart.md](../quickstart.md)

## Round-1 Clarify Decisions (already integrated pre-plan)

These were locked before plan generation; this section is a sanity audit.

- [ ] CHK001 **List pagination — default 50 / cap 200**: integrated in FR-020a, propagated to `closed-sets.md` "Pagination" section, mentioned in plan Constraints, no drift across artifacts. [Consistency, Spec §FR-020a]
- [ ] CHK002 **Last-write-wins on entity updates**: integrated in FR-030a, propagated to `app-methods.md` `app.agent.update` failure-code list (never `stale_object`), data-model.md Validation Rules section. [Consistency, Spec §FR-030a]
- [ ] CHK003 **`idempotency_key` on `app.send_input` only**: integrated in FR-031a, propagated to `app-methods.md` request shape, data-model.md Idempotency Entry, research.md R-006 with cap/eviction details. [Consistency, Spec §FR-031a]
- [ ] CHK004 **`capability_flags = {}` at v1.0**: integrated in FR-039, propagated to `closed-sets.md`, `app-methods.md` `app.hello` sample, quickstart.md Step 2. [Consistency, Spec §FR-039]
- [ ] CHK005 **`app.scan.*` 30s timeout cap + server-side continue + `scan_timeout`**: integrated in FR-030b, propagated to `app-methods.md`, `error-codes.md` (with `scan_id` in details), `closed-sets.md`. [Consistency, Spec §FR-030b]

## Round-2 Clarify Decisions

- [ ] CHK006 **`app.scan.status(scan_id)` method declaration**: is the method present in `app-methods.md` with the response schema `{state, scan_kind, started_at, completed_at, result}` (state set now trimmed to 3 values after round 3)? [Consistency, Spec §FR-030c, Contracts §app-methods, §closed-sets]
- [ ] CHK007 **`scan_not_found` closed-set code**: present in FR-034 closed set, in `error-codes.md` registry, with `details = {scan_id: string}` in FR-034a registry? [Consistency, Spec §FR-034, §FR-034a, Contracts §error-codes]
- [ ] CHK008 **`hints[]` array on `app.dashboard` AND `app.readiness`**: present in FR-014a, in `app-methods.md` for both methods, in quickstart.md Step 3 sample (empty `[]`) and Step 4 sample (with hint entry)? [Consistency, Spec §FR-014a, Contracts §app-methods, Quickstart §Step 3, §Step 4]
- [ ] CHK009 **Hint code v1.0 closed set (6 codes)**: present in FR-014a, in `closed-sets.md` Hint Codes section, in data-model.md Closed Sets section, in quickstart.md (`docker_unavailable_hint` referenced in degraded sample)? [Consistency, Spec §FR-014a, Contracts §closed-sets, DataModel, Quickstart]
- [ ] CHK010 **Hint severity closed set `{info, warning, action_required}`**: present in FR-014a, in `closed-sets.md`, in data-model.md? [Consistency, Spec §FR-014a, Contracts §closed-sets, DataModel]
- [ ] CHK011 **`error.details` per-code registry (12 entries with structured details)**: present in FR-034a, in `error-codes.md` per-code registry, in data-model.md Validation Rules cross-reference? [Consistency, Spec §FR-034a, Contracts §error-codes, DataModel]
- [ ] CHK012 **`error.details` always-an-object rule**: present in FR-033, in data-model.md Validation Rules, in `error-codes.md` ("Codes with `details == {}`" enumeration)? [Consistency, Spec §FR-033, Contracts §error-codes, DataModel]
- [ ] CHK013 **`state_priority` integer mapping** (`pending=1..delivered=6`): present in FR-021a, in `closed-sets.md`, in data-model.md, in QueueViewModel definition? [Consistency, Spec §FR-021a, Contracts §closed-sets, DataModel]
- [ ] CHK014 **`role_priority` integer mapping** (`master=1..unknown=6`): present in FR-021a, in `closed-sets.md`, in data-model.md? [Consistency, Spec §FR-021a, Contracts §closed-sets, DataModel]
- [ ] CHK015 **`app.*` host-only policy**: FR-042 rewritten, `host_only` in FR-034 closed set, `error-codes.md` has the code, `app-methods.md` top-level host-only gate documented? [Consistency, Spec §FR-042, Contracts §app-methods, §error-codes]
- [ ] CHK016 **Legacy namespace unchanged for container callers**: FR-040 updated to be explicit about legacy-vs-app surfaces, Assumptions updated to be normative? [Consistency, Spec §FR-040, §Assumptions]
- [ ] CHK017 **`host_only` closed-set code in FR-034**: present in error-codes.md with `details == {}`? [Consistency, Spec §FR-034, Contracts §error-codes]

## Round-3 Clarify Decisions

- [ ] CHK018 **`order_by` direction syntax (`field:asc`/`field:desc`)**: present in FR-021b, in `closed-sets.md` Order-By Direction Syntax section, in `app-methods.md` (top-level or per-method)? [Consistency, Spec §FR-021b, Contracts §closed-sets, §app-methods]
- [ ] CHK019 **`agent.update` clearable fields (project_path, label only)**: present in FR-029a, in `app-methods.md` `app.agent.update` semantics, in data-model.md Validation Rules? [Consistency, Spec §FR-029a, Contracts §app-methods, DataModel]
- [ ] CHK020 **`log.detach` idempotent success**: present in FR-029b, in `app-methods.md` failure-code lists for log.detach (no `not_attached` code, no error path), in data-model.md? [Consistency, Spec §FR-029b, Contracts §app-methods, DataModel]
- [ ] CHK021 **Filter operators = exact match only at v1.0**: present in FR-024a, in `closed-sets.md` Filter Operator Vocabulary section, in `app-methods.md` per-entity filter table? [Consistency, Spec §FR-024a, Contracts §closed-sets, §app-methods]
- [ ] CHK022 **`scan_state.expired` removed from v1.0**: FR-030c enum trimmed, `closed-sets.md` Scan State trimmed, `app-methods.md` `app.scan.status` response trimmed, data-model.md Scan Record + Closed Sets trimmed? [Consistency, Spec §FR-030c, Contracts §closed-sets, §app-methods, DataModel]
- [ ] CHK023 **Payload caps (1 MiB request, 8 MiB response)**: present in FR-003a, in `closed-sets.md` Payload Size Caps section, in `app-methods.md` top-level payload gate, in plan.md Constraints? [Consistency, Spec §FR-003a, Contracts §closed-sets, §app-methods, Plan §Constraints]
- [ ] CHK024 **`payload_too_large` closed-set code**: present in FR-034 (26 codes total), in `error-codes.md` with `details = {size_limit_bytes: int, actual_size_bytes: int}`? [Consistency, Spec §FR-034, §FR-034a, Contracts §error-codes]
- [ ] CHK025 **`payload_too_large` is a possible failure for every method**: stated at top level of `app-methods.md` (not per-method, but globally)? [Consistency, Contracts §app-methods, Spec §FR-003a]

## Drift Detection (Negative)

- [ ] CHK026 Does ANY artifact still reference **`scan_state == "expired"`** as a v1.0 reachable state (vs. an "intentionally absent" forward-looking note)? [Negative, Consistency, Spec §FR-030c]
- [ ] CHK027 Does ANY artifact still reference **`stale_object`** in the context of `app.agent.update` or `app.route.update` (banned by FR-030a)? [Negative, Consistency, Spec §FR-030a]
- [ ] CHK028 Does ANY artifact still imply that **`hints[]` is only on dashboard** (it must also be on readiness per FR-014a)? [Negative, Consistency, Spec §FR-014a]
- [ ] CHK029 Does ANY artifact still imply that **container callers can call `app.*` methods** (forbidden by FR-042)? [Negative, Consistency, Spec §FR-042]
- [ ] CHK030 Does ANY artifact still imply that **`details` may be `null` or absent** (forbidden by FR-033)? [Negative, Consistency, Spec §FR-033]
- [ ] CHK031 Does ANY artifact's **error-code list** count differ from 26 entries at v1.0? [Negative, Consistency, Spec §FR-034]

## Round-2/3 SC Gap (Outstanding)

- [ ] CHK032 Are **success criteria added for FR-020a (pagination), FR-030b (scan timeout), FR-031a (idempotency), FR-039 (capability_flags), FR-014a (hints), FR-021a (state_priority/role_priority normative ordering), FR-021b (order_by direction), FR-024a (filter exact-match), FR-029a (update clearable fields), FR-029b (log.detach idempotent), FR-030c (scan.status method), FR-034a (details registry), FR-042 (app.* host-only), FR-003a (payload caps)**? [Gap, Spec §Success Criteria]
- [ ] CHK033 Is the **SC numbering plan** documented (e.g., SC-011..SC-025) so the additions don't collide with existing SC-001..SC-010? [Gap, Spec §Success Criteria]

## Process Audit

- [ ] CHK034 Is the **Session 2026-05-19 Q/A list** in `spec.md` ordered chronologically by round (round 1 first, round 2 next, round 3 last) for an audit trail reader? [Clarity, Spec §Clarifications]
- [ ] CHK035 Are **superseded earlier Q/A entries** (e.g., the round-2 entry that listed `expired` as a scan state, later removed by round 3) preserved as historical record with their later supersession traceable? [Traceability, Spec §Clarifications]
- [ ] CHK036 Is the **17-file checklist directory** (including this one and the 16 from the first run) free of cross-file duplication that would force the reader to read the same item twice? [Clarity, Quality]
