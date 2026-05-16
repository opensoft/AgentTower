# Data Model & State Vocabulary Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the `message_queue` schema, identity capture, timestamp completeness, closed-set vocabularies (state, block_reason, failure_reason), transition graph, operator metadata, and routing-flag entity. Tests whether the data model itself is fully specified, closed, and integrity-checkable — NOT whether the SQLite implementation is correct.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Walked**: 2026-05-12
**Feature**: [spec.md](../spec.md)

## `message_queue` Schema Completeness

- [X] CHK001 All columns enumerated with roles (FR-012 + data-model.md §2 DDL).
- [X] CHK002 PK is UUIDv4 (122 bits of entropy); FR-001 explicitly chose UUIDv4 over `agt_<hex>` for `message_id` because it's an internal queue identifier with no FEAT-006 collision domain.
- [X] CHK003 `envelope_body` is always raw bytes (FR-012, FR-012a, Clarifications Q1 of 2026-05-11).
- [X] CHK004 `envelope_body_sha256` defined as hex over the raw body for integrity (data-model.md §2 + Clarifications Q1 follow-on note).
- [X] CHK005 `envelope_size_bytes` applies to the serialized envelope (data-model.md §2 inline comment + FR-004).
- [X] CHK006 NULLABLE vs NOT NULL distinguished per column in data-model.md §2 DDL.

## Identity Capture

- [X] CHK007 Sender identity fields frozen at enqueue (data-model.md §5 "Identity capture" table).
- [X] CHK008 Target identity fields frozen at enqueue (data-model.md §5).
- [X] CHK009 Hard-deleted agent handling specified (spec.md Edge Cases "Queue row references a sender or target that has been hard-deleted").
- [X] CHK010 Precedence: stored identity wins for audit/listing; live registry wins for re-check eligibility (data-model.md §5 + FR-025).

## Timestamp Completeness

- [X] CHK011 Per-transition stamp updates declared in data-model.md §3.1 transition table ("Stamp(s) advanced" column).
- [X] CHK012 `last_updated_at` is monotonic per transition (advanced by every transition in §3.1; backed by `now_iso_ms_utc()` system clock).
- [X] CHK013 Timestamp resolution = millisecond (FR-012b).
- [X] CHK014 UTC + ISO 8601 + `Z` suffix declared for every timestamp surface (FR-012b).
- [X] CHK015 `delivery_attempt_started_at < {delivered_at, failed_at}` ordering invariant declared (FR-041 + FR-042 + per-state stamp CHECK constraints).

## State & Reason Closed Sets

- [X] CHK016 `state` closed set enumerated, no synonyms (data-model.md §2 CHECK + FR-013).
- [X] CHK017 `block_reason` closed set with each value mapped to a precedence step (FR-017 + FR-020 per-step mapping + data-model.md §3.4).
- [X] CHK018 `failure_reason` closed set with each value mapped to a delivery-worker failure mode (FR-018 + FR-043 + plan §"Delivery worker loop").
- [X] CHK019 `block_reason` and `failure_reason` are mutually exclusive on a single row by construction — data-model.md §2 CHECK forces `block_reason IS NULL OR state='blocked'` and `failure_reason IS NULL OR state='failed'`; the two states are disjoint.
- [X] CHK020 `block_reason` NULL outside `state='blocked'` (data-model.md §2 CHECK).
- [X] CHK021 `failure_reason` NULL outside `state='failed'` (data-model.md §2 CHECK).

## Allowed Transitions

- [X] CHK022 Transition graph closed (data-model.md §3.1 enumerates every valid transition; FR-015).
- [X] CHK023 Operator vs worker triggers distinguished in §3.1 "Trigger" column.
- [X] CHK024 `queued → blocked` via delivery-time re-check vs operator `delay` distinguished (different `block_reason` values; FR-025 + data-model.md §3.1).
- [X] CHK025 Terminal-state-backward invariant declared (FR-014 + data-model.md §3.2 "no further transitions allowed").

## Operator Metadata

- [X] CHK026 `operator_action` closed set declared (data-model.md §2 CHECK + FR-012 + §4.4).
- [X] CHK027 `operator_action_by` column captures operator identity (data-model.md §2 + §5).
- [X] CHK028 Operator metadata is "latest wins" on the queue row; full action history lives in the JSONL audit per data-model.md §5.

## Routing Flag Entity

- [X] CHK029 Routing flag fields enumerated (data-model.md §2 daemon_state schema + Key Entities entry).
- [X] CHK030 `last_updated_by` uses `host-operator` for host-side toggles and `(daemon-init)` for the migration-time seed (Clarifications session 2 Q4 + data-model.md §2 seed comment).
- [X] CHK031 Routing flag default = `enabled` on fresh state (FR-026 + data-model.md §2 seed row).

## Plan-Grounded Additions (2026-05-12 pass)

- [X] CHK032 BLOB rationale declared in research §R-002, tying to FR-012a byte-exact replay.
- [X] CHK033 Four indexes with primary query path commented (data-model.md §2 inline comments).
- [X] CHK034 Recovery partial index `WHERE` clause matches the FR-040 `UPDATE` predicate exactly (data-model.md §2).
- [X] CHK035 `envelope_body_sha256` covers the raw body (Clarifications Q1).
- [X] CHK036 CHECK constraints enumerate every closed-set value, matching spec one-for-one (data-model.md §2 vs FR-017/018).
- [X] CHK037 Operator-metadata coherence CHECK declared (data-model.md §2).
- [X] CHK038 Per-state stamp invariant CHECKs declared (data-model.md §2).
- [X] CHK039 Seed row in migration transaction (T012 + data-model.md §2).
- [X] CHK040 `daemon_state` CHECK constraints declared (data-model.md §2).
- [X] CHK041 `operator_action_by` accepts `agt_<12-hex>` or `host-operator` with explicit regex pattern (contracts/queue-row-schema.md `$defs`).
- [X] CHK042 `ResolvedTarget` dataclass declared in plan §"Target resolver" (acceptably as a plan-level type, not a data-model entity, since it's not persisted).
- [X] CHK043 Timestamp resolution = millisecond consistent across data-model.md §2 (`TEXT` ISO-8601 ms UTC) and plan §"Timestamp encoding" (`now_iso_ms_utc()` Python helper).

## Notes

- 43/43 items resolved. Zero outstanding.
