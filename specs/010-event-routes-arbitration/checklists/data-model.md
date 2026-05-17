# Data Model Checklist: Event-Driven Routing and Multi-Master Arbitration

**Purpose**: Validate requirements quality for the FEAT-010 SQLite schema — column contracts, constraints, migration, referential integrity, and tagging of FEAT-009 queue rows.
**Created**: 2026-05-16
**Feature**: [spec.md](../spec.md)
**Depth**: Deep

## Routes Table Schema

- [X] CHK001 Are all columns of the `routes` table enumerated with type, nullability, and default? [Completeness, Spec §FR-001]
- [X] CHK002 Is the primary-key uniqueness contract for `route_id` (UUIDv4) explicit? [Clarity, Spec §FR-001]
- [X] CHK003 Is the `source_scope_value` type contract specified per `source_scope_kind` value (NULL for `any`, agent_id for `agent_id`, `role:<r>[,capability:<c>]` for `role`)? [Clarity, Spec §FR-001, Clarifications]
- [X] CHK004 Is the `target_value` type contract specified per `target_rule` value? [Clarity, Spec §FR-001, FR-006]
- [X] CHK005 Is the `master_value` type contract specified per `master_rule` value (NULL for `auto`, agent_id for `explicit`)? [Clarity, Spec §FR-001, FR-007]
- [X] CHK006 Are `created_at` / `updated_at` semantics specified (UTC, ISO-8601, monotonic on update)? [Gap]
- [X] CHK007 Is `created_by_agent_id` documented as nullable + sentinel-reserved (`host-operator` per FEAT-009 inheritance)? [Spec §FR-001]
- [X] CHK008 Is the closed set of `event_type` values pinned to the FEAT-008 vocabulary version-by-version? [Spec §FR-005, Gap]

## Cursor & Lifecycle Columns

- [X] CHK009 Is `last_consumed_event_id` initial value (MAX(events.event_id) or 0) specified with the empty-table edge case? [Completeness, Spec §FR-002]
- [X] CHK010 Are the cursor monotonicity invariants (never decreases except via `route reset-cursor`, which is out of scope) explicit? [Spec §FR-002, Story 4 #4]
- [X] CHK011 Is the cursor-freeze semantic during disable explicitly specified as a data-model invariant? [Spec §Story 2 #3]
- [X] CHK012 Is the relationship between `last_consumed_event_id` and `events.event_id` (no FK; soft reference) documented? [Gap, Spec §Edge Cases]

## message_queue Extension

- [X] CHK013 Are the three new `message_queue` columns (`origin`, `route_id`, `event_id`) specified with default values for backward compatibility? [Completeness, Spec §FR-029]
- [X] CHK014 Is the closed-set domain for `origin` (`direct` | `route`) documented? [Clarity, Spec §FR-029]
- [X] CHK015 Are NULL semantics for `route_id` / `event_id` when `origin=direct` specified? [Clarity, Spec §FR-029]
- [X] CHK016 Is the UNIQUE constraint on `(route_id, event_id)` scope specified (where both non-null)? [Clarity, Spec §FR-030]
- [X] CHK017 Is the orphan-route_id contract specified (deletes do not cascade; queue history preserved)? [Spec §FR-003, FR-031, Edge Cases]

## Migration & Schema Versioning

- [X] CHK018 Is the migration to schema version 8 specified as idempotent? [Gap, Spec §FR-031]
- [X] CHK019 Is migration rollback behavior (or its absence) explicitly stated? [Gap]
- [X] CHK020 Is the migration's behavior on partial completion (interrupted at column-add vs index-add) specified? [Gap]
- [X] CHK021 Is concurrent migration safety (single daemon vs CLI during upgrade) specified? [Gap]
- [X] CHK022 Are the existing FEAT-009 `message_queue` rows guaranteed migrated to default `origin='direct'` atomically? [Spec §FR-029, Gap]

## Indexes & Query Performance

- [X] CHK023 Are index requirements for the routing-cycle event-scan query (`events WHERE event_id > cursor AND event_type = ?`) specified? [Gap, Spec §FR-010, SC-006]
- [X] CHK024 Is the index supporting the UNIQUE `(route_id, event_id)` constraint explicit? [Spec §FR-030, Gap]
- [X] CHK025 Are query-plan assumptions for `agenttower queue --origin route` filter performance documented? [Gap, Spec §FR-033]

## Configuration & Daemon-State Tables

- [X] CHK026 Is the storage location of routing-worker config knobs (cycle interval per FR-040, batch size per FR-041, heartbeat interval per FR-039a) specified (table? file? CLI args)? [Gap]
- [X] CHK027 Is the persistence model for the FR-038 status counters (`events_consumed_total`, `skips_by_reason`) specified (in-memory vs SQLite)? [Gap]

## Cross-Feature Dependencies

- [X] CHK028 Are FEAT-008 `events` table schema dependencies (`event_id`, `event_type`, `source_role`, `source_capability`, `source_agent_id`) pinned with version assumptions? [Gap]
- [X] CHK029 Is the relationship between FEAT-009's `message_queue` schema version and FEAT-010's schema version 8 documented? [Spec §FR-031, Gap]
- [X] CHK030 Are storage growth bounds documented for `routes`, extended `message_queue`, and audit JSONL under MVP no-retention policy? [Spec §Assumptions, Gap]
