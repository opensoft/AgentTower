# Schema Migration Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of the SQLite migration v6 → v7 requirements — table creation, idempotence, forward-version refusal, daemon_state seeding, downgrade story, and FEAT-001..008 backwards-compatibility invariants. Tests whether the migration is specified completely and unambiguously — NOT whether the migration runs.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-12
**Walked**: 2026-05-12 (post-remediation)
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [data-model.md](../data-model.md)

## Migration Scope

- [X] CHK001 Migration scope is declared. **Note:** the original "exactly two new tables, no modifications to FEAT-001..008" framing is superseded by the Clarifications Q1 (2026-05-12) decision; the actual three-part scope (add `message_queue` + `daemon_state` + four indexes; rebuild FEAT-008 `events`; recreate four FEAT-008 indexes) is fully declared in plan.md §"Storage" and data-model.md §2.
- [X] CHK002 `CURRENT_SCHEMA_VERSION` advances `6 → 7` as the sole version bump (data-model.md §1; plan.md §"Storage").
- [X] CHK003 Migration runs under a single `BEGIN IMMEDIATE` transaction (plan.md §"Storage"; data-model.md §1).
- [X] CHK004 Idempotent re-open via `IF NOT EXISTS` on every additive `CREATE TABLE` / `CREATE INDEX`; rebuild guard is current-version-equals-6 (data-model.md §2; T012).

## Forward Compatibility

- [X] CHK005 Forward-version refusal surfaces `schema_version_newer` (plan.md §"Backwards compatibility"; T013(c) asserts).
- [X] CHK006 Rollback behavior: daemon refuses to serve (plan.md §"Storage").
- [X] CHK007 FEAT-001..008 byte-identical preservation declared (plan.md §"Backwards compatibility"; T013(d) asserts pre-existing FEAT-008 rows survive the rebuild byte-for-byte; T087 backcompat test asserts CLI output byte-identical).

## Seed Data

- [X] CHK008 `daemon_state` seed row declared (data-model.md §2 "Seed row" comment; T012 step 1).
- [X] CHK009 Seed `last_updated_by` is the literal `'(daemon-init)'` sentinel — distinct from `host-operator` to record that the value is migration-created (data-model.md §2 comment block; resolved by L2 of 2026-05-12 remediation).
- [X] CHK010 Seed `last_updated_at` is `now_iso_ms_utc()` evaluated at migration time (data-model.md §2 / T012).
- [X] CHK011 `INSERT OR IGNORE` used for the seed (data-model.md §2 / T012).

## Index Specification

- [X] CHK012 Four indexes declared with primary query path (data-model.md §2 inline comments).
- [X] CHK013 `idx_message_queue_in_flight` partial index `WHERE` clause matches the FR-040 recovery `UPDATE` predicate exactly (data-model.md §2; plan.md §"Recovery + worker startup ordering"; Research §R-012).
- [X] CHK014 Index names follow FEAT-008 `idx_<table>_<columns>` convention (data-model.md §2; plan.md §"Storage").

## CHECK Constraints

- [X] CHK015 Schema-level CHECK constraints on `state` / `block_reason` / `failure_reason` / `operator_action` enumerate every closed-set value (data-model.md §2).
- [X] CHK016 Reason-state coherence CHECK declared (data-model.md §2 lines 93-95).
- [X] CHK017 Operator-metadata coherence CHECK (all three null XOR all three non-null) declared (data-model.md §2 lines 97-102).
- [X] CHK018 Per-state stamp invariant CHECKs declared (data-model.md §2 lines 104-107).

## Downgrade & Operator Recovery

- [ ] CHK019 **Open**: operator's path to downgrade v7 → v6 is NOT declared. Plan §"Backwards compatibility" says forward-version refusal raises `schema_version_newer` but doesn't tell the operator what to do next.
- [ ] CHK020 **Open**: migration behavior under FEAT-001..008 schema corruption (e.g., missing v6 marker) is NOT specified. Would the daemon refuse, re-init, or attempt repair?

## Testing

- [X] CHK021 `test_schema_migration_v7.py` covers v6-upgrade, v7-already-current re-open, and forward-version refusal (T013 a/b/c), plus rebuild-preservation, CHECK widening, NULL acceptance, and index existence (T013 d/e/f/g).
- [X] CHK022 `test_feat009_backcompat.py` declared as the byte-identical CLI gate across FEAT-001..008 commands (T087).
- [ ] CHK023 **Open**: the test fixture set for migration testing is NOT explicitly declared — which v6 DB snapshots are used, where they live in the repo.

## Notes

- Items test whether the migration is fully specified, not whether the SQL runs.
- 20/23 items resolved by spec/plan/data-model/tasks edits through the 2026-05-12 remediation; 3 remain open.
- **Outstanding decisions for the user**: CHK019 (downgrade path), CHK020 (schema-corruption handling), CHK023 (test-fixture location).
