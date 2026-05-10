# Schema Migration Safety Requirements Checklist: Event Ingestion, Classification, and Follow CLI

**Purpose**: Validate that v5 → v6 migration, rollback, forward-version refusal, mixed-state recovery, and backwards-compatibility requirements are complete, clear, consistent, and measurable. This checklist tests the **requirements writing**, not the implementation.
**Created**: 2026-05-10
**Feature**: [spec.md](../spec.md)
**Depth**: Formal release gate

## Requirement Completeness

- [ ] CHK001 Is the schema-version bump (v5 → v6) explicitly required at the spec level, or is it only a plan-level decision? [Completeness, Plan §R1, Spec Gap]
- [ ] CHK002 Are migration idempotence requirements specified (running the migration on an already-v6 DB is a no-op)? [Completeness, Plan §R1]
- [ ] CHK003 Are migration atomicity requirements specified (single `BEGIN IMMEDIATE` or equivalent — partial failure leaves the DB at v5)? [Completeness, Plan §R1]
- [ ] CHK004 Are forward-version refusal requirements specified (v6 daemon refuses to open v7+ DB)? [Completeness, Plan §R1]
- [ ] CHK005 Are backwards-version refusal requirements specified (v6 daemon CAN read v5, applies migration; CANNOT read v4 or earlier without prior FEAT-006 / FEAT-007 migrations)? [Completeness, Gap]
- [ ] CHK006 Are requirements specified for the events table's initial state on first open after migration (empty)? [Completeness, Gap]
- [ ] CHK007 Are requirements specified for the indexes' creation order (PK first, then four indexes — `IF NOT EXISTS` semantics)? [Completeness, Plan §2.5]
- [ ] CHK008 Are requirements specified for handling a migration interrupted by daemon kill (PRAGMA `journal_mode=WAL` recovery on reopen)? [Completeness, Gap]
- [ ] CHK009 Are requirements specified for the backwards-compatibility test scope (every FEAT-001..007 CLI surface must produce byte-identical output)? [Completeness, Plan §R12]
- [ ] CHK010 Is the `schema_version` field on each event row required to start at `1` and bump only on non-breaking JSONL/SQLite shape additions? [Completeness, Spec §FR-027]

## Requirement Clarity

- [ ] CHK011 Is "single `BEGIN IMMEDIATE` transaction" precise enough (vs `BEGIN DEFERRED` with same effect)? [Clarity, Plan §R1]
- [ ] CHK012 Is "refuses to serve the daemon on rollback" precise about what the operator sees (exit code, stderr message)? [Clarity, Plan §R1]
- [ ] CHK013 Is "non-breaking schema-version bump" defined operationally (which kinds of change qualify; new optional field qualifies, renamed field does not)? [Clarity, Spec §FR-027]
- [ ] CHK014 Is the migration-test reproducibility scheme defined unambiguously (use a fixture v5 DB, not a freshly-created one)? [Clarity, Gap]

## Requirement Consistency

- [ ] CHK015 Is the migration shape consistent with the FEAT-007 v4 → v5 migration pattern (same `_apply_pending_migrations` pathway, same forward-refusal behavior)? [Consistency, Plan §R1]
- [ ] CHK016 Are the events-table CHECK constraints consistent with the documented JSONL schema enums (`event_type` closed-set in both)? [Consistency, Plan §2.1, Spec §FR-008, FR-027]
- [ ] CHK017 Is the `schema_version` column default value (1) consistent with the JSON schema's `schema_version` initial value? [Consistency, Plan §2.1, Contracts §event-schema]
- [ ] CHK018 Are migration failure semantics consistent between FEAT-008 and the prior FEAT-006 / FEAT-007 migrations (same lifecycle event, same exit-code, same rollback)? [Consistency, Gap]

## Acceptance Criteria Quality

- [ ] CHK019 Is there a test-for-test SC item explicitly requiring the migration to be reproducible against a v5-only DB fixture? [Measurability, Plan §"Testing"]
- [ ] CHK020 Is there an SC item explicitly requiring the v6-already-current re-open path to be a no-op? [Measurability, Plan §"Testing"]
- [ ] CHK021 Is there an SC item explicitly requiring the forward-version refusal path to surface a documented error? [Measurability, Plan §"Testing"]
- [ ] CHK022 Is the backwards-compatibility test's coverage scope auditable (an explicit list of FEAT-001..007 commands that must produce byte-identical output)? [Measurability, Plan §R12]

## Scenario Coverage

- [ ] CHK023 Are requirements defined for the FRESH-INSTALL scenario (no prior DB; create at v6 directly)? [Coverage, Gap]
- [ ] CHK024 Are requirements defined for the V5-UPGRADE scenario (existing v5 DB; apply v5 → v6 migration)? [Coverage, Plan §R1]
- [ ] CHK025 Are requirements defined for the V6-NOOP scenario (existing v6 DB; reopen as no-op)? [Coverage, Plan §R1]
- [ ] CHK026 Are requirements defined for the V7-FUTURE scenario (existing v7 DB on a v6 daemon; forward-refuse)? [Coverage, Plan §R1]
- [ ] CHK027 Are requirements defined for the V4-OR-EARLIER scenario (older DB on v6 daemon; chain through v5 first, or refuse)? [Coverage, Gap]
- [ ] CHK028 Are requirements defined for the INTERRUPTED-MIGRATION scenario (daemon killed mid-migration; SQLite WAL recovery on next open)? [Coverage, Gap]

## Edge Case Coverage

- [ ] CHK029 Is the case "v5 DB has FEAT-007 audit rows in `log_attachment_change` that reference now-stale `attachment_id` values" addressed (events table FK shape only — no enforced FK)? [Edge Case, Plan §2.2]
- [ ] CHK030 Is the case "FEAT-007 redaction utility was updated between FEAT-007 and FEAT-008 deploys" addressed (existing v5-era audit rows already redacted; no retroactive re-redaction)? [Edge Case, Gap]
- [ ] CHK031 Is the case "operator runs `agenttower events` against an unmigrated v5 DB before `agenttowerd` is upgraded" addressed (CLI surfaces a clear error)? [Edge Case, Gap]
- [ ] CHK032 Is the case "concurrent connections to the DB during migration" addressed (`BEGIN IMMEDIATE` lock semantics)? [Edge Case, Plan §R1]

## Non-Functional Requirements

- [ ] CHK033 Are migration runtime requirements specified (the migration is O(1) — empty table, no backfill)? [NFR, Plan §R1]
- [ ] CHK034 Are migration disk-space requirements specified (the indexes are empty post-migration; no rebuild)? [NFR, Gap]
- [ ] CHK035 Are migration logging requirements specified (single audit-log line on success/failure)? [NFR, Gap]

## Dependencies & Assumptions

- [ ] CHK036 Is the assumption that the FEAT-007 v4 → v5 migration is already applied at FEAT-008 deploy time documented? [Assumption, Plan §R1]
- [ ] CHK037 Is the dependency on SQLite's `IF NOT EXISTS` semantics for idempotence documented? [Dependency, Plan §R1]
- [ ] CHK038 Is the assumption that no manual SQL has been applied to the v5 DB between deploys documented (operator must not hand-edit the events SQLite file)? [Assumption, Gap]
