# Data Model Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality of `data-model.md` — in-memory entity shapes, view model derivation, closed-set inventory, cross-FR validation rules.
**Created**: 2026-05-19
**Feature**: [data-model.md](../data-model.md), [spec.md](../spec.md)

## In-Memory Entity Completeness

- [X] CHK001 Is **App Session** fully defined (all 8 fields with type, source, description)? [Completeness, DataModel §App Session]
- [X] CHK002 Is App Session's **lifecycle** stated as a closed transition graph (`created → invalidated` terminal)? [Clarity, DataModel §App Session]
- [X] CHK003 Is **Scan Record** state enum aligned with FR-030c (now `{running, completed, failed}`, no `expired`)? [Consistency, DataModel §Scan Record, Spec §FR-030c]
- [X] CHK004 Is **Idempotency Entry** cap (256) and policy (LRU) documented and traced to research R-006? [Traceability, DataModel §Idempotency Entry, Research §R-006]
- [X] CHK005 Is the **token vs id distinction** stated for App Session (token is opaque secret-like, id is audit-friendly int)? [Clarity, DataModel §App Session]
- [X] CHK006 Are all **maximum field lengths** quantified where they matter (client_id ≤128, client_version ≤64, idempotency_key ≤256)? [Completeness, DataModel §entities]

## View Model Completeness

- [X] CHK007 Are **all 7 view models** defined (Container, Pane, Agent, LogAttachment, Event, Queue, Route)? [Completeness, DataModel §view models]
- [X] CHK008 Is each derived field marked `Derived? yes/no` consistently so an implementer knows which fields require joins? [Clarity, DataModel §view models]
- [X] CHK009 Does **PaneViewModel** derive both `registered: bool` AND `agent_id: nullable` (FR-022)? [Completeness, DataModel §PaneViewModel, Spec §FR-022]
- [X] CHK010 Does **AgentViewModel** derive both `log_attached: bool` AND `pane_active: bool` (FR-023)? [Completeness, DataModel §AgentViewModel, Spec §FR-023]
- [X] CHK011 Does **QueueViewModel** include `state_priority: int 1..6` consistent with FR-021a? [Consistency, DataModel §QueueViewModel, Spec §FR-021a]
- [X] CHK012 Does **EventViewModel** include a `summary` field for "Recent activity" rendering (FR-017)? [Completeness, DataModel §EventViewModel, Spec §FR-017]
- [X] CHK013 Does **RouteViewModel** include `last_consumed_event_id` and `updated_at` for activity displays (Round-6: `updated_at`, not `last_used_at`)? [Completeness, DataModel §RouteViewModel]
- [X] CHK014 Are **summary field length caps** specified (e.g., EventViewModel.summary ≤ 256 chars)? [Clarity, DataModel §EventViewModel]

## Closed-Set Inventory

- [X] CHK015 Are **all FR-defined closed sets** mirrored in data-model.md (app_contract_version format, readiness state, subsystem status, subsystem names, hint severity, hint codes, agent roles + role_priority, queue state + state_priority, scan state, scan kind, mutation origin)? [Completeness, DataModel §Closed Sets]
- [X] CHK016 Is **mutation origin** documented as `{cli, app, route, system}` and consistent with FR-044's "origin == 'app'" requirement? [Consistency, DataModel §Closed Sets, Spec §FR-044]
- [X] CHK017 Is **capability_flags = {}** stated for v1.0 with a forward note about additive evolution? [Consistency, DataModel §Closed Sets, Spec §FR-039]
- [X] CHK018 Is the **error-codes registry** cross-referenced to `contracts/error-codes.md` rather than duplicated (single source of truth)? [Consistency, DataModel §Closed Sets]
- [X] CHK019 Are the **state_priority** and **role_priority** integer mappings stated normatively (per FR-021a)? [Completeness, DataModel §Closed Sets, Spec §FR-021a]

## Cross-FR Validation Rules

- [X] CHK020 Is **"session lifetime = connection lifetime"** stated as a normative rule? [Completeness, DataModel §Validation Rules, Spec §FR-008]
- [X] CHK021 Is **"token never persisted, never logged"** stated normatively with reference to SC-008? [Traceability, DataModel §Validation Rules, Spec §SC-008]
- [X] CHK022 Is **"adopt parity (byte-for-byte modulo origin)"** stated and traced to SC-004 + SC-010? [Traceability, DataModel §Validation Rules]
- [X] CHK023 Are **payload size caps** stated (1 MiB request, 8 MiB response) per FR-003a? [Completeness, DataModel §Validation Rules, Spec §FR-003a]
- [X] CHK024 Are **`agent.update` field semantics** stated (absent = no change; empty-string clears project_path/label only) per FR-029a? [Completeness, DataModel §Validation Rules, Spec §FR-029a]
- [X] CHK025 Is **`log.detach` idempotency** stated (success with `log_attached: false` even when never attached) per FR-029b? [Completeness, DataModel §Validation Rules, Spec §FR-029b]
- [X] CHK026 Is **`order_by` direction syntax** stated (field, field:asc, field:desc) per FR-021b? [Completeness, DataModel §Validation Rules, Spec §FR-021b]
- [X] CHK027 Is **filter exact-match-only at v1.0** stated per FR-024a? [Completeness, DataModel §Validation Rules, Spec §FR-024a]
- [X] CHK028 Is **`error.code` regex `^[a-z][a-z0-9_]*$`** stated as an enforceable rule (SC-003)? [Measurability, DataModel §Validation Rules, Spec §SC-003]

## Ambiguities & Gaps

- [X] CHK029 Is the **`host_user_id` format** specified concretely (numeric UID as string, per data-model and FR-010)? [Clarity, DataModel §App Session, Spec §FR-010]
- [X] CHK030 Is the **`event_id` monotonicity assumption** stated (referenced by FR-021 events default order)? [Gap]
- [X] CHK031 Is the **`registered_at` field's presence on every agent row** guaranteed (referenced by FR-021 agent ordering)? [Gap]
- [X] CHK032 Is the **derived `pane_active` definition** specified operationally (e.g., "seen on the most recent successful pane scan")? [Clarity, DataModel §AgentViewModel]
- [X] CHK033 Is the **`degraded_scan` semantics for container counts** specified — when is a container counted as `degraded_scan` (FR-016)? [Gap]
- [X] CHK034 Is the **interaction between view-model composition and SQLite isolation** documented (no global lock per FR-018, but what isolation level do individual reads use)? [Clarity, DataModel §Validation Rules]
