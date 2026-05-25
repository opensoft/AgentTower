# Deployment & Rollback Requirements Quality Checklist: Managed Session Creation and Lifecycle

**Purpose**: Validate that deployment, upgrade, rollback, and first-run requirements are complete, clear, consistent, and measurable for this feature.
**Created**: 2026-05-24
**Feature**: [spec.md](../spec.md)

## Migration & Schema

- [x] CHK001 Are deployment requirements specified for the schema migration that adds `predecessor_id`, pending-managed marker, and any new tables/fields? [Gap, Cross-ref: data-model.md]
- [x] CHK002 Are rollback requirements specified for the schema migration (down-migration safety)? [Gap]
- [x] CHK003 Are backwards-compatibility requirements specified with existing FEAT-011 contracts during a phased rollout? [Gap]

## First-Run & Install

- [x] CHK004 Are deployment requirements specified for the durable storage initialization (empty state, first-run behavior, schema seeding)? [Gap, Spec §FR-020]
- [x] CHK005 Are deployment requirements specified for the local-socket path / permissions during install? [Gap, Spec §FR-017]
- [x] CHK006 Are deployment requirements specified for configuration file installation (templates, launch profiles, defaults)? [Gap, Cross-ref: configuration.md]

## Daemon Upgrade / Restart

- [x] CHK007 Are deployment requirements specified for the daemon restart sequence (graceful shutdown, in-flight create-layout handling)? [Gap, Spec §FR-020]
- [x] CHK008 Are deployment requirements specified for surviving daemon upgrades while in-flight layouts exist? [Gap, Recovery Flow]
- [x] CHK009 Are rollback requirements specified if a daemon upgrade introduces breaking changes to the managed-layout contract? [Gap]
- [x] CHK010 Are post-deployment audit requirements specified to verify reattach completeness (FR-020)? [Gap]

## Validation

- [x] CHK011 Are deployment-time validation requirements specified (smoke test, configuration sanity check, durable-store integrity check)? [Gap]
- [x] CHK012 Are requirements specified for cleaning up stale tmux panes / pending-managed markers left over from a prior failed deployment? [Gap]

## Observability of Deploys

- [x] CHK013 Are observability requirements specified for the deploy/restart path itself (events emitted on reattach, FR-020)? [Gap, Cross-ref: observability.md]

---

## Walk closure (2026-05-25)

13/13 items resolved by FEAT-001's in-Python migration registry pattern (idempotent CREATE TABLE IF NOT EXISTS, single forward migration v9 — see T002/T007) + FR-020 + recovery.py (boot reconcile before socket accepts requests) + FR-022 + R5 (boot-time pending-marker GC) + FR-024 (no auto-create under override directories from pre-implement walk topic H). Down-migration and cross-version compatibility are constitution-level invariants documented in data-model.md §Migration & rollout (no down-migration in MVP).
