# Data Model Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that data-model and lifecycle-state-machine requirements (entities, attributes, transitions, constraints, durability) are complete, clear, consistent, and measurable.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Entity Attribute Completeness

- [x] CHK001 Are all attributes of `Managed Layout` enumerated (id, template_id, container_id, state, created_at, updated_at, owner, …)? [Completeness, Spec §Key Entities]
- [x] CHK002 Are all attributes of `Managed Pane` enumerated (id, layout_id, role, capability, label, launch_command_ref, state, predecessor_id, pending_marker, tmux_pane_ref, created_at, …)? [Completeness, Spec §Key Entities]
- [x] CHK003 Are all attributes of `Launch Command Profile` enumerated (id, name, command, env, working_dir, …)? [Completeness, Spec §Key Entities]
- [x] CHK004 Are all attributes of `Lifecycle Event` enumerated (id, layout_id, pane_id, event_type, timestamp, payload, actor)? [Completeness, Spec §Key Entities]
- [x] CHK005 Are required-vs-optional field markers specified for every entity attribute? [Completeness]
- [x] CHK006 Are `Adopted Agent` attributes within FEAT-013's scope clarified (delegated to FEAT-006, partially overridden, fully owned here)? [Clarity, Dependency, Spec §Key Entities]

## State Machine Coverage

- [x] CHK007 Is the lifecycle state transition graph fully enumerated (every valid transition from every state)? [Coverage, Gap, Spec §FR-007]
- [x] CHK008 Are illegal lifecycle state transitions enumerated (e.g., `removed → ready` without a recreate; `failed → ready` without a recreate)? [Coverage, Gap]
- [x] CHK009 Is the state of the predecessor record at the moment of recreation defined (must be `removed` or `failed`; not `ready` or `creating`)? [Clarity, Spec §FR-011]
- [x] CHK010 Are the relationships between layout-level state and pane-level state defined (e.g., a layout is `ready` iff all panes are `ready` or `degraded`)? [Gap]
- [x] CHK011 Is the boundary between `creating` and `ready` defined precisely (at pane spawn, at first prompt, at registration)? [Clarity, Spec §FR-007]
- [x] CHK012 Is the data-model representation of the `promoted_from_adopted` reserved transition specified (extra optional field, sentinel value, separate table)? [Gap, Spec §FR-007]

## Constraints & Identity

- [x] CHK013 Is the field type for `predecessor_id` defined (UUID, opaque string, integer)? [Gap]
- [x] CHK014 Is the label uniqueness constraint scope storage specified (database constraint, application-level check, both)? [Clarity, Spec §FR-003]
- [x] CHK015 Are unique constraints enumerated (layout_id PK, pane_id PK, label uniqueness per container, tmux session-name uniqueness)? [Completeness]
- [x] CHK016 Is the cardinality between Managed Layout and Managed Pane specified (1:N enforced)? [Completeness]
- [x] CHK017 Is the cardinality between Managed Pane and Lifecycle Event specified (1:N append-only)? [Completeness]
- [x] CHK018 Is the relationship between Managed Pane and the underlying tmux pane identifier specified (tmux pane_id stored, recomputed, both)? [Clarity, Spec §FR-007]

## Durability & Persistence

- [x] CHK019 Is the data-at-rest requirement specified (sqlite, json file, in-memory only)? [Gap, Spec §FR-020]
- [x] CHK020 Is the durability boundary specified for FR-020 (which records must be durable, which may be in-memory)? [Clarity, Spec §FR-020]
- [x] CHK021 Is the retention model for `Lifecycle Event` storage specified (indefinite per FR-021, but is the storage shape and growth profile specified)? [Clarity, Spec §FR-021]
- [x] CHK022 Are timestamp requirements specified (UTC, monotonic, system-clock-only, RFC3339)? [Gap]
- [x] CHK023 Is the data model robust against partial writes during the failure of a layout-creation transaction (write-ahead, idempotent commit)? [Gap, Spec §FR-014]

## Schema Evolution

- [x] CHK024 Are schema migration requirements specified for adding `predecessor_id`, pending-managed marker, etc.? [Gap]
- [x] CHK025 Are forward/backward compatibility requirements specified for the durable store across daemon upgrades? [Gap, Cross-ref: deployment.md]

## Consistency

- [x] CHK026 Is the data model consistent with the FEAT-011 agent registry (same id space, FK constraints)? [Consistency, Dependency]
- [x] CHK027 Are there any data-model conflicts with the `Adopted Agent` storage owned by FEAT-006? [Conflict, Dependency]
- [x] CHK028 Does the data model align with FR-008's "same registry/queue/route/event/health/direct-send surfaces" claim (no parallel managed-only tables)? [Consistency, Spec §FR-008]

## Edge Cases

- [x] CHK029 Is the recreate-chain depth (predecessor → predecessor → …) bounded or explicitly unbounded? [Gap, Spec §FR-011]
- [x] CHK030 Is the data shape for "failed stage" (FR-013) defined as an enum or free-text? [Clarity, Spec §FR-013]
- [x] CHK031 Is the pending-managed marker's representation specified (field on Managed Pane, separate record, tmux pane title prefix)? [Gap, Spec §FR-014]

## Non-Functional

- [x] CHK032 Are concurrency-safety requirements specified at the data model level (row-level locks, optimistic concurrency, transaction isolation)? [Gap, Spec §FR-019]
- [x] CHK033 Are integrity-check / fsck-style requirements specified for the durable store on daemon boot (FR-020)? [Gap, Spec §FR-020]

---

## Walk closure (2026-05-25)

33/33 items resolved by data-model.md DDL (all entity attributes + CHECK constraints + partial unique indexes + RFC3339 timestamps + WAL-mode concurrency from research §R2) + state-machine.md (full transition graph including illegal transitions + recreate semantics + recovery rules) + FR-023 + R4 (chain depth bounded at 16) + FR-022 + R5 (5-min TTL sweep) + FEAT-001's in-Python migration registry (single forward migration v9 with idempotent IF NOT EXISTS).
