# Data Model Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that data-model and lifecycle-state-machine requirements (entities, attributes, transitions, constraints, durability) are complete, clear, consistent, and measurable.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Entity Attribute Completeness

- [ ] CHK001 Are all attributes of `Managed Layout` enumerated (id, template_id, container_id, state, created_at, updated_at, owner, …)? [Completeness, Spec §Key Entities]
- [ ] CHK002 Are all attributes of `Managed Pane` enumerated (id, layout_id, role, capability, label, launch_command_ref, state, predecessor_id, pending_marker, tmux_pane_ref, created_at, …)? [Completeness, Spec §Key Entities]
- [ ] CHK003 Are all attributes of `Launch Command Profile` enumerated (id, name, command, env, working_dir, …)? [Completeness, Spec §Key Entities]
- [ ] CHK004 Are all attributes of `Lifecycle Event` enumerated (id, layout_id, pane_id, event_type, timestamp, payload, actor)? [Completeness, Spec §Key Entities]
- [ ] CHK005 Are required-vs-optional field markers specified for every entity attribute? [Completeness]
- [ ] CHK006 Are `Adopted Agent` attributes within FEAT-013's scope clarified (delegated to FEAT-006, partially overridden, fully owned here)? [Clarity, Dependency, Spec §Key Entities]

## State Machine Coverage

- [ ] CHK007 Is the lifecycle state transition graph fully enumerated (every valid transition from every state)? [Coverage, Gap, Spec §FR-007]
- [ ] CHK008 Are illegal lifecycle state transitions enumerated (e.g., `removed → ready` without a recreate; `failed → ready` without a recreate)? [Coverage, Gap]
- [ ] CHK009 Is the state of the predecessor record at the moment of recreation defined (must be `removed` or `failed`; not `ready` or `creating`)? [Clarity, Spec §FR-011]
- [ ] CHK010 Are the relationships between layout-level state and pane-level state defined (e.g., a layout is `ready` iff all panes are `ready` or `degraded`)? [Gap]
- [ ] CHK011 Is the boundary between `creating` and `ready` defined precisely (at pane spawn, at first prompt, at registration)? [Clarity, Spec §FR-007]
- [ ] CHK012 Is the data-model representation of the `promoted_from_adopted` reserved transition specified (extra optional field, sentinel value, separate table)? [Gap, Spec §FR-007]

## Constraints & Identity

- [ ] CHK013 Is the field type for `predecessor_id` defined (UUID, opaque string, integer)? [Gap]
- [ ] CHK014 Is the label uniqueness constraint scope storage specified (database constraint, application-level check, both)? [Clarity, Spec §FR-003]
- [ ] CHK015 Are unique constraints enumerated (layout_id PK, pane_id PK, label uniqueness per container, tmux session-name uniqueness)? [Completeness]
- [ ] CHK016 Is the cardinality between Managed Layout and Managed Pane specified (1:N enforced)? [Completeness]
- [ ] CHK017 Is the cardinality between Managed Pane and Lifecycle Event specified (1:N append-only)? [Completeness]
- [ ] CHK018 Is the relationship between Managed Pane and the underlying tmux pane identifier specified (tmux pane_id stored, recomputed, both)? [Clarity, Spec §FR-007]

## Durability & Persistence

- [ ] CHK019 Is the data-at-rest requirement specified (sqlite, json file, in-memory only)? [Gap, Spec §FR-020]
- [ ] CHK020 Is the durability boundary specified for FR-020 (which records must be durable, which may be in-memory)? [Clarity, Spec §FR-020]
- [ ] CHK021 Is the retention model for `Lifecycle Event` storage specified (indefinite per FR-021, but is the storage shape and growth profile specified)? [Clarity, Spec §FR-021]
- [ ] CHK022 Are timestamp requirements specified (UTC, monotonic, system-clock-only, RFC3339)? [Gap]
- [ ] CHK023 Is the data model robust against partial writes during the failure of a layout-creation transaction (write-ahead, idempotent commit)? [Gap, Spec §FR-014]

## Schema Evolution

- [ ] CHK024 Are schema migration requirements specified for adding `predecessor_id`, pending-marker, etc.? [Gap]
- [ ] CHK025 Are forward/backward compatibility requirements specified for the durable store across daemon upgrades? [Gap, Cross-ref: deployment.md]

## Consistency

- [ ] CHK026 Is the data model consistent with the FEAT-011 agent registry (same id space, FK constraints)? [Consistency, Dependency]
- [ ] CHK027 Are there any data-model conflicts with the `Adopted Agent` storage owned by FEAT-006? [Conflict, Dependency]
- [ ] CHK028 Does the data model align with FR-008's "same registry/queue/route/event/health/direct-send surfaces" claim (no parallel managed-only tables)? [Consistency, Spec §FR-008]

## Edge Cases

- [ ] CHK029 Is the recreate-chain depth (predecessor → predecessor → …) bounded or explicitly unbounded? [Gap, Spec §FR-011]
- [ ] CHK030 Is the data shape for "failed stage" (FR-013) defined as an enum or free-text? [Clarity, Spec §FR-013]
- [ ] CHK031 Is the pending-managed marker's representation specified (field on Managed Pane, separate record, tmux pane title prefix)? [Gap, Spec §FR-014]

## Non-Functional

- [ ] CHK032 Are concurrency-safety requirements specified at the data model level (row-level locks, optimistic concurrency, transaction isolation)? [Gap, Spec §FR-019]
- [ ] CHK033 Are integrity-check / fsck-style requirements specified for the durable store on daemon boot (FR-020)? [Gap, Spec §FR-020]
