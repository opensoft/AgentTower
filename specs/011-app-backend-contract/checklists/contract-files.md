# Contract Files Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality of `contracts/app-methods.md`, `contracts/error-codes.md`, `contracts/closed-sets.md` — per-method shape clarity, closed-set membership, registry consistency.
**Created**: 2026-05-19
**Feature**: [contracts/](../contracts/), [spec.md](../spec.md)

## `contracts/app-methods.md` Completeness

- [X] CHK001 Are **all 30 v1.0 methods** declared in `app-methods.md` (2 bootstrap, 2 dashboard, 14 read = 7×{list,detail}, 1 adopt, 11 mutations)? [Completeness, Contracts §app-methods]
- [X] CHK002 Does each method declare both **request params** and **success result** shapes? [Completeness, Contracts §app-methods]
- [X] CHK003 Does each method declare its **failure codes** (not just "see error-codes.md")? [Completeness, Contracts §app-methods]
- [X] CHK004 Is **`app.preflight`'s success-envelope code field** distinguished from a failure envelope (it's a success carrying a diagnostic `code`)? [Clarity, Contracts §app-methods, Spec §FR-011, §FR-033]
- [X] CHK005 Is the **host-only gate** stated as a top-level rule applicable to every method, including `app.preflight` and `app.hello`? [Completeness, Contracts §app-methods, Spec §FR-042]
- [X] CHK006 Is the **session gate** stated with exemption list (`app.preflight`, `app.hello`)? [Completeness, Contracts §app-methods, Spec §FR-007]
- [X] CHK007 Is the **payload size gate** (1 MiB / 8 MiB) stated as a top-level rule applicable to every method? [Completeness, Contracts §app-methods, Spec §FR-003a]
- [X] CHK008 Is `app.scan.status`'s **request input** specified (just `scan_id`)? [Completeness, Contracts §app-methods, Spec §FR-030c]
- [X] CHK009 Does `app.send_input` document the **dedupe response shape** (`deduplicated: true` marker)? [Completeness, Contracts §app-methods, Spec §FR-031a]
- [X] CHK010 Does `app.agent.update` enumerate **all four clearable / non-clearable cases** (absent, empty-string-clearable fields, empty-string-non-clearable fields, invalid value)? [Completeness, Contracts §app-methods, Spec §FR-029a]
- [X] CHK011 Does `app.log.detach` explicitly state **success-idempotent behavior** with the post-state shape? [Completeness, Contracts §app-methods, Spec §FR-029b]
- [X] CHK012 Are **time-range filter params** (`since`/`until`) documented as unix-ms integers, distinct from filter exact-match fields? [Clarity, Contracts §app-methods]

## `contracts/error-codes.md` Completeness & Consistency

- [X] CHK013 Are **all 27 v1.0 codes** listed in error-codes.md with consistent spelling and ordering? [Completeness, Contracts §error-codes]
- [X] CHK014 Are **typical triggers** documented per code (not just the name)? [Clarity, Contracts §error-codes]
- [X] CHK015 Is the **per-code `details` registry** complete for every code with structured details (12 entries)? [Completeness, Contracts §error-codes, Spec §FR-034a]
- [X] CHK016 Is the **`details == {}` set** (14 codes) explicitly enumerated so a contract test can assert membership? [Completeness, Contracts §error-codes]
- [X] CHK017 Are **evolution rules** stated (adding code = additive minor; adding required key = major bump)? [Completeness, Contracts §error-codes, Spec §FR-034a]
- [X] CHK018 Is the **`error.code` regex `^[a-z][a-z0-9_]*$`** stated as an enforceable rule? [Measurability, Contracts §error-codes]
- [X] CHK019 Is **`stale_object` scope** documented as queue-lifecycle-only, never for entity updates (FR-030a)? [Consistency, Contracts §error-codes, Spec §FR-030a]
- [X] CHK020 Are codes that **never appear in `app.preflight`** clearly distinguished from codes that may appear? [Clarity, Contracts §error-codes]

## `contracts/closed-sets.md` Completeness

- [X] CHK021 Are **all closed enumerations referenced by FRs** present in closed-sets.md (versions, states, severities, hint codes, priorities, order_by per-surface sets, pagination, recent_limit, payload caps, direction syntax, filter operators)? [Completeness, Contracts §closed-sets]
- [X] CHK022 Are the **state_priority and role_priority integer mappings** stated byte-for-byte matching FR-021a? [Consistency, Contracts §closed-sets, Spec §FR-021a]
- [X] CHK023 Is the **scan state set** trimmed to `{running, completed, failed}` (no `expired`)? [Consistency, Contracts §closed-sets, Spec §FR-030c]
- [X] CHK024 Is the **mutation origin set** documented as `{cli, app, route, system}` (FEAT-008 reused)? [Consistency, Contracts §closed-sets, Spec §FR-044]
- [X] CHK025 Are **per-surface order_by closed sets** enumerated for every entity (containers, panes, agents, log_attachments, events, queue, routes)? [Completeness, Contracts §closed-sets, Spec §FR-021]
- [X] CHK026 Are the **payload caps section** and **direction syntax section** present with concrete byte counts and regex? [Completeness, Contracts §closed-sets, Spec §FR-003a, §FR-021b]
- [X] CHK027 Is the **state-aggregation rule** for readiness (any unavailable → unavailable, etc.) documented explicitly per FR-012? [Completeness, Contracts §closed-sets]

## Cross-Contract Consistency

- [X] CHK028 Are the **error codes referenced in app-methods.md per-method failure lists** all present in error-codes.md? [Consistency, Contracts §app-methods, §error-codes]
- [X] CHK029 Are the **per-method `details` shapes referenced in app-methods.md** consistent with the error-codes.md per-code `details` registry? [Consistency, Contracts §app-methods, §error-codes]
- [X] CHK030 Are the **closed-set values used in app-methods.md** (scan states, severities, role values) consistent with closed-sets.md? [Consistency, Contracts §app-methods, §closed-sets]
- [X] CHK031 Is the **`app_contract_version = "1.0"` constant** stated identically in all three contract files? [Consistency, Contracts §all]

## Measurability & Test Surface

- [X] CHK032 Does error-codes.md state the **6 contract test assertions** explicitly (regex, registry, per-code required keys, types, object shape, version field present)? [Measurability, Contracts §error-codes]
- [X] CHK033 Can the **per-method failure code lists** be enforced via a registry-driven contract test (method → set of allowed codes)? [Measurability, Contracts §app-methods]
- [X] CHK034 Can the **per-surface filter closed set** be enforced via a parameter-validation test (any filter field not in the set → `validation_failed`)? [Measurability, Contracts §app-methods, §closed-sets]

## Ambiguities & Gaps

- [X] CHK035 Is the **`payload_too_large` code's applicability** stated per-method, or only in the top-level "Payload size gate" note? [Clarity, Contracts §app-methods, §error-codes]
- [X] CHK036 Is the **`unknown_method` behavior** specified — does the daemon emit it for both unrecognized `app.*` methods and recognized methods at a future minor not implemented? [Gap, Contracts §error-codes]
- [X] CHK037 Are **per-method request payload validation orderings** documented (e.g., does session-gate run before payload-size-gate, before host-only gate)? [Gap, Contracts §app-methods]
- [X] CHK038 Is the **cursor_next encoding format** specified (opaque str, daemon-chosen) with a maximum length? [Gap, Contracts §app-methods]
- [X] CHK039 Is the **`order_by` field-name validation** specified as occurring before direction-suffix validation? [Clarity, Contracts §closed-sets]
