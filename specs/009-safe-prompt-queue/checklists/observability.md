# Observability Requirements Quality Checklist: Safe Prompt Queue and Input Delivery

**Purpose**: Deep validation of audit, JSONL stream, queue listing display contract, `agenttower status` integration, and reconstructability requirements. Tests whether the observability surface is fully specified and consumer-ready (for operators, FEAT-008, and a future FEAT-010) — NOT whether logs are emitted at runtime.
**Rigor**: Deep (formal release-gate)
**Created**: 2026-05-11
**Walked**: 2026-05-12
**Feature**: [spec.md](../spec.md)

## Audit Entry Completeness

- [X] CHK001 Required fields enumerated for both event-type families (FR-046 + contracts/queue-audit-schema.md).
- [X] CHK002 Strict 1:1 mapping per state transition (FR-046 "MUST append one audit entry per state transition").
- [X] CHK003 Operator-identity capture on operator-driven transitions (FR-046 + data-model.md §5).
- [X] CHK004 Identity snapshot persists after deregistration (Edge Cases "Queue row references a hard-deleted agent" + data-model.md §5).
- [X] CHK005 Audit format declared additive-only (data-model.md §7 "Fields are stable across MVP minor revisions; new fields may be added (additive-only), existing fields may not change shape"; contracts/queue-audit-schema.md disjointness note).

## Event-Type Vocabulary

- [X] CHK006 Eight-element closed set declared (FR-046 + Clarifications 2026-05-12 Q1/Q3).
- [X] CHK007 Disjoint from FEAT-007 lifecycle + FEAT-008 classifier types (research §R-008 + T086 disjointness test).
- [X] CHK008 One event type per directed transition for `queue_message_*` (FR-046 mapping); `routing_toggled` is one type per toggle event.

## Excerpt & Redaction in Audit

- [X] CHK009 Body-meaningful transitions enumerated (FR-047 "`enqueued`, `delivered`, `blocked` at enqueue").
- [X] CHK010 Raw body excluded from audit as absolute MUST NOT (FR-047 + FR-047a).
- [X] CHK011 240-char cap + `…` truncation marker consistent across queue listings, audit, `--json` (FR-011, FR-047, FR-047b, queue-row-schema.md, queue-audit-schema.md).
- [X] CHK012 Multi-line body excerpt rendering = redact → collapse whitespace → truncate → append `…` (FR-047b, Clarifications Q3 of 2026-05-11).

## Queue Listing Display Contract

- [X] CHK013 Listing columns declared as a fixed contract (US3 #1 + FR-031 + contracts/cli-queue.md "Default columns").
- [X] CHK014 Column ordering specified for human mode in contracts/cli-queue.md; `--json` array shape per queue-row-schema.md is the stable machine surface.
- [X] CHK015 Redaction applied uniformly to both `--json` and human listings (FR-047a).
- [X] CHK016 Empty-state rendering specified — human prints `(no rows match)`, `--json` returns `[]`, exit `0` (contracts/cli-queue.md).
- [ ] CHK017 **Open**: human-mode default time format choice (relative vs absolute) is not stated. contracts/cli-queue.md shows absolute ISO-8601, but doesn't declare whether a relative form (e.g., "3m ago") is available or considered.
- [X] CHK018 Degraded signals surface through `agenttower status` (FR-048 + T054).
- [ ] CHK019 **Open**: specific queue-health fields surfaced through `agenttower status` (in-flight count, buffered audit count, last-recovery timestamp) are not enumerated. T054 names `routing` and `degraded_queue_audit_persistence` only.
- [X] CHK020 Kill switch state visible in `agenttower status` (T054).
- [ ] CHK021 **Open**: per-target `queued` row count visibility is not declared. Operators can run `agenttower queue --state queued --target <agent>` and count rows, but a summary in `agenttower status` (e.g., "in-flight=N, queued-per-target={…}") is not specified.

## Reconstructability & Retention

- [X] CHK022 SC-006 quantified at ≥ 1,000 transitions per agent pair (spec.md §SC-006).
- [X] CHK023 No-rotation MVP policy inherited from FEAT-008 (spec.md §Assumptions "No retention policy in MVP").
- [X] CHK024 Manual operator pruning permitted with no safety constraints (Assumptions "Manual operator pruning is allowed" — absence of constraints = no constraints).
- [X] CHK025 SQLite-vs-JSONL precedence: SQLite authoritative, JSONL best-effort (FR-048 + data-model.md §7.2 table).
- [X] CHK026 JSONL failure MUST NOT block SQLite state advancement (FR-048 + data-model.md §7.2; T034 dual-write order enforces).

## Downstream Consumers

- [X] CHK027 FEAT-010 forward-compatibility — sender/target identity + full transition timeline captured in JSONL audit per FR-046; additive-only audit format means no breaking change required later.
- [X] CHK028 Single-row history reconstructible via `agenttower events --target <agent>` then `jq 'select(.message_id == ...)'` — exercises the FR-046 dual-write surface; no new `--filter` flag needed in MVP.

## Plan-Grounded Additions (2026-05-12 pass)

- [X] CHK029 `routing_toggled` has its own schema in contracts/queue-audit-schema.md "Routing toggle audit entry".
- [X] CHK030 R-008 disjointness covers `routing_toggled` (T086 imports `_ROUTING_AUDIT_EVENT_TYPES`).
- [X] CHK031 `reason` nullability per event type declared in contracts/queue-audit-schema.md "Reason-field discipline".
- [X] CHK032 `degraded_queue_audit_persistence` distinct from FEAT-008's `degraded_events_persistence` (T054 + plan §"JSONL audit append + degraded path").
- [X] CHK033 `degraded_audit_buffer_max_rows = 1024` is a hard cap with drop-oldest policy (plan §"Defaults locked" + research §R-009 + T034).
- [X] CHK034 SQLite-first / JSONL-best-effort stated in FR-048, data-model.md §7.2, plan §"JSONL audit append + degraded path", and T034.
- [X] CHK035 JSON Schema `$id` URLs use the placeholder `agenttower.local` (not a registered domain) — MVP convention, no external tooling depends on resolution.
- [X] CHK036 `excerpt` `maxLength: 241` consistent between queue-row-schema.md and queue-audit-schema.md.
- [X] CHK037 Audit `sender`/`target` are enqueue-time snapshots (data-model.md §5 + §7 audit schema).
- [X] CHK038 `events.jsonl` backcompat (no rename, no removal of existing event types) declared in plan §"Backwards compatibility".

## Notes

- 35/38 items resolved by spec/plan/research/contracts through the 2026-05-12 remediation; 3 remain open.
- **Outstanding decisions for the user**: CHK017 (human-mode time format — relative vs absolute), CHK019 (`agenttower status` queue-health field set), CHK021 (per-target queue depth visibility through `agenttower status`).
