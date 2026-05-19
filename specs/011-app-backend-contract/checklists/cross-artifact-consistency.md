# Cross-Artifact Consistency Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Detect drift between `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, and `quickstart.md`. Every item asks: "does artifact X say the same thing as artifact Y?"
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md), [plan.md](../plan.md), [data-model.md](../data-model.md), [contracts/](../contracts/), [quickstart.md](../quickstart.md), [research.md](../research.md)

## Spec ↔ Plan Consistency

- [X] CHK001 Does plan.md's **Summary "7 layers"** reflect every FR cluster in spec.md (contract surface, identity/sessions, bootstrap/readiness, aggregate dashboard, read surfaces, adopt, operator mutations, errors, versioning, security, observability)? [Consistency, Plan §Summary, Spec §Requirements]
- [X] CHK002 Does plan.md's **Constraints section** mention every quantified limit from spec.md (pagination 200, recent_limit 50, scan wait 30s, request 1 MiB, response 8 MiB, idempotency scope)? [Consistency, Plan §Constraints, Spec §FR-003a, §FR-017, §FR-020a, §FR-030b, §FR-031a]
- [X] CHK003 Does plan.md's **Performance Goals** match the SC-002 and SC-004 measurable outcomes exactly? [Consistency, Plan §Performance Goals, Spec §SC-002, §SC-004]
- [X] CHK004 Does plan.md's **Constitution Check** evidence reference the same FRs/SCs the spec relies on (FR-002, FR-003, FR-009, FR-031, FR-040, FR-042, FR-044, SC-006, SC-008)? [Traceability, Plan §Constitution Check, Spec §Requirements]
- [X] CHK005 Does plan.md's **`app_contract_version = "1.0"`** match the value in every other artifact? [Consistency, Plan §Summary, Spec §Clarifications, Contracts §all]

## Spec ↔ Data Model Consistency

- [X] CHK006 Does data-model.md's **App Session schema** include `client_app_contract_major` matching FR-036's check requirement? [Consistency, DataModel §App Session, Spec §FR-036]
- [X] CHK007 Does data-model.md's **Scan Record state enum** match FR-030c's v1.0 set `{running, completed, failed}` (no `expired`)? [Consistency, DataModel §Scan Record, Spec §FR-030c]
- [X] CHK008 Does data-model.md's **Idempotency Entry scope** `(app_session_id, idempotency_key)` match FR-031a exactly? [Consistency, DataModel §Idempotency Entry, Spec §FR-031a]
- [X] CHK009 Does data-model.md's **PaneViewModel** include the FR-022 derived fields (`registered`, `agent_id`)? [Consistency, DataModel §PaneViewModel, Spec §FR-022]
- [X] CHK010 Does data-model.md's **AgentViewModel** include the FR-023 derived fields (`log_attached`, `pane_active`)? [Consistency, DataModel §AgentViewModel, Spec §FR-023]
- [X] CHK011 Does data-model.md's **state_priority / role_priority mapping** match FR-021a integer-for-integer? [Consistency, DataModel §Closed Sets, Spec §FR-021a]

## Spec ↔ Contracts Consistency

- [X] CHK012 Does `app-methods.md`'s **method enumeration (30 methods)** cover every method referenced in FR-029 plus the bootstrap and read methods? [Consistency, Contracts §app-methods, Spec §FR-029]
- [X] CHK013 Does `error-codes.md`'s **26-code closed set** match FR-034's enumeration entry-for-entry (no missing codes, no extra codes)? [Consistency, Contracts §error-codes, Spec §FR-034]
- [X] CHK014 Does `error-codes.md`'s **per-code `details` registry** match FR-034a entry-for-entry? [Consistency, Contracts §error-codes, Spec §FR-034a]
- [X] CHK015 Does `closed-sets.md`'s **`role_priority` and `state_priority` tables** match FR-021a integer-for-integer? [Consistency, Contracts §closed-sets, Spec §FR-021a]
- [X] CHK016 Does `closed-sets.md`'s **hint codes set** match FR-014a's v1.0 registry? [Consistency, Contracts §closed-sets, Spec §FR-014a]
- [X] CHK017 Does `closed-sets.md`'s **scan state set** match FR-030c's v1.0 set (no `expired`)? [Consistency, Contracts §closed-sets, Spec §FR-030c]
- [X] CHK018 Does `closed-sets.md`'s **payload caps section** match FR-003a's byte counts exactly (1,048,576 / 8,388,608)? [Consistency, Contracts §closed-sets, Spec §FR-003a]
- [X] CHK019 Does `app-methods.md`'s **`app.agent.update` semantics** match FR-029a entry-for-entry? [Consistency, Contracts §app-methods, Spec §FR-029a]
- [X] CHK020 Does `app-methods.md`'s **`app.log.detach` idempotency** match FR-029b? [Consistency, Contracts §app-methods, Spec §FR-029b]

## Spec ↔ Quickstart Consistency

- [X] CHK021 Does quickstart.md's **Step 2 sample `app.hello` response** include every FR-010 required field? [Consistency, Quickstart §Step 2, Spec §FR-010]
- [X] CHK022 Does quickstart.md's **Step 3 sample `app.readiness` response** include all 6 subsystems from FR-013 in the order from data-model.md? [Consistency, Quickstart §Step 3, Spec §FR-013]
- [X] CHK023 Does quickstart.md's **Step 4 sample `app.dashboard` response** include all 7 count surfaces from FR-016? [Consistency, Quickstart §Step 4, Spec §FR-016]
- [X] CHK024 Does quickstart.md's **5 user stories forward-pointer** match the 5 User Stories in spec.md 1:1? [Consistency, Quickstart §Beyond Story 1, Spec §User Scenarios]

## Plan ↔ Data Model Consistency

- [X] CHK025 Does plan.md's **three in-memory stores** match data-model.md's three entities (App Session, Scan Record, Idempotency Entry)? [Consistency, Plan §Storage, DataModel §entities]
- [X] CHK026 Does plan.md's **scan retention cap (100)** match FR-030c and data-model.md? [Consistency, Plan §Constraints, DataModel §Scan Record, Spec §FR-030c]
- [X] CHK027 Does plan.md's **idempotency dedupe scope** match data-model.md's `(app_session_id, idempotency_key)` and research.md's R-006 cap of 256? [Consistency, Plan §Constraints, DataModel §Idempotency Entry, Research §R-006]

## Plan ↔ Contracts Consistency

- [X] CHK028 Does plan.md's **module structure** map to the contract surfaces (e.g., `bootstrap.py` → `app.preflight`+`app.hello`; `reads.py` → 7 entity list/detail methods)? [Consistency, Plan §Project Structure, Contracts §app-methods]
- [X] CHK029 Does plan.md's **test file list** cover every contract domain (error-codes, closed-sets, app-methods)? [Consistency, Plan §Project Structure §tests/contract, Contracts §all]

## Plan ↔ Research Consistency

- [X] CHK030 Does plan.md's **R-001 host-vs-container detection mechanism** reuse the FEAT-009 mechanism research.md commits to? [Consistency, Plan §Constraints, Research §R-001]
- [X] CHK031 Does plan.md's **threading model** (per-connection threads) match research.md's R-003? [Consistency, Plan §Project Type, Research §R-003]
- [X] CHK032 Does plan.md's **synthetic client design** for tests match research.md's R-010 "bare-metal socket client" decision? [Consistency, Plan §Project Structure §tests/fixtures, Research §R-010]

## Contracts ↔ Quickstart Consistency

- [X] CHK033 Does quickstart.md's **request-line format** match `contracts/app-methods.md`'s top-level NDJSON framing? [Consistency, Quickstart §global, Contracts §app-methods]
- [X] CHK034 Does quickstart.md's **error-envelope sample** match `contracts/error-codes.md`'s success/failure envelope shape? [Consistency, Quickstart §Step 2, Contracts §error-codes]
- [X] CHK035 Does quickstart.md's **degraded-readiness sample** use a hint code from `contracts/closed-sets.md`'s registry (`docker_unavailable_hint`)? [Consistency, Quickstart §Step 3, Contracts §closed-sets]

## Within-Spec Consistency (Round-2/3 Locks vs Prior FRs)

- [X] CHK036 Does the **FR-042 host-only rule** (round-2) co-exist consistently with FR-040 (round-1) — does FR-040 still permit container callers for legacy methods only? [Consistency, Spec §FR-040, §FR-042]
- [X] CHK037 Does the **`expired` scan state removal** (round-3) leave no stale references to `expired` in FR-030c, FR-030b, FR-034, FR-034a, or any user-story acceptance? [Consistency, Spec §FR-030b, §FR-030c, §FR-034]
- [X] CHK038 Do **all references to `stale_object`** consistently scope it to queue terminal-state guards only (FR-030a is the binding rule)? [Consistency, Spec §FR-030a, §FR-034, §FR-034a]
- [X] CHK039 Does the **`hints[]` array on both dashboard AND readiness** (round-2) have consistent schema documentation in FR-014a and across data-model.md / closed-sets.md / app-methods.md? [Consistency, Spec §FR-014a, DataModel, Contracts]
- [X] CHK040 Does the **`details` always-an-object rule** (FR-033 + FR-034a) have consistent enforcement language across spec.md, data-model.md, error-codes.md? [Consistency, Spec §FR-033, §FR-034a]
- [X] CHK041 Are all references to the **error-code closed set** counting **27 entries** at v1.0 (after `host_only` round-2 + `payload_too_large` round-3 + `scan_not_found` round-2 + `malformed_request` round-4 additions)? [Consistency, Spec §FR-034, Contracts §error-codes]
