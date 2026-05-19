# Dashboard Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for `app.dashboard` — aggregate counts, recent-activity payloads, atomicity tradeoff, hints contract.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [X] CHK001 Are all dashboard count buckets enumerated for every surface (containers, panes, agents, log_attachments, queue, routes, events)? [Completeness, Spec §FR-016]
- [X] CHK002 Are all recent-activity row fields specified per surface (id, timestamp, type, key labels, summary)? [Completeness, Spec §FR-017]
- [X] CHK003 Is the `degraded_scan` semantics for container counts defined (when is a container counted as `degraded_scan`)? [Gap, Spec §FR-016]
- [X] CHK004 Is the `log_attachments` count bucket set defined (active/degraded/none appears in Story 1, but not enumerated in FR-016)? [Gap, Spec §US1 step 4, §FR-016]
- [X] CHK005 Is the `events` count bucket set defined (no buckets enumerated in FR-016 for events)? [Gap, Spec §FR-016]
- [X] CHK006 Is the `hints[]` array (Story 4 acceptance #4) defined in any FR, or only in an acceptance scenario? [Gap, Spec §US4]
- [X] CHK007 Are the closed-set hint codes for `hints[]` enumerated (e.g., `start_bench_container`, `check_container_filter`)? [Gap, Spec §US4]

## Requirement Clarity

- [X] CHK008 Is "most recent" defined operationally for events/queue/routes (by `event_id` DESC, `created_at` DESC, or mutation timestamp)? [Clarity, Spec §FR-017, §FR-021]
- [X] CHK009 Is `recent_limit` clearly tied to a closed bounds `[1, 50]` and a defined error code when out of bounds? [Clarity, Spec §FR-017]
- [X] CHK010 Is "compact rows" (FR-017) defined as a specific subset of fields, or left to implementer judgement? [Clarity, Spec §FR-017]

## Requirement Consistency

- [X] CHK011 Are FR-017's `recent_limit` bounds `[1, 50]` distinct from and reconciled with FR-020a's pagination bounds `[1, 200]`? [Consistency, Spec §FR-017, §FR-020a]
- [X] CHK012 Do FR-016's queue count buckets `{pending, in_flight, delivered, cancelled, expired}` match the FEAT-009 closed set referenced elsewhere? [Consistency, Spec §FR-016]
- [X] CHK013 Are FR-016's agent role buckets `{master, slave, swarm, test-runner, shell, unknown}` consistent with FEAT-006's role closed set? [Consistency, Spec §FR-016]
- [X] CHK014 Is the `degraded_scan` container-count bucket consistent with the FEAT-003 container discovery state vocabulary? [Consistency, Spec §FR-016]

## Scenario Coverage

- [X] CHK015 Are requirements defined for when one surface's counts are unavailable (e.g., events JSONL missing) — does dashboard return partial counts or a hard error? [Gap, Spec §FR-018]
- [X] CHK016 Are requirements defined for the relationship between dashboard counts and degraded readiness (e.g., docker unavailable → container counts zero, not unknown)? [Coverage, Spec §US4 acceptance 4]
- [X] CHK017 Is the behavior defined for an empty system (zero of everything)? [Coverage]
- [X] CHK018 Is the behavior defined when `recent_limit` exceeds the number of available rows for a surface (truncate silently? return all available)? [Gap, Spec §FR-017]

## Measurability

- [X] CHK019 Is "slight inter-surface inconsistency" (FR-018) bounded with a tolerable staleness window, or left undefined? [Ambiguity, Spec §FR-018]
- [X] CHK020 Can "MUST NOT take any global lock" be verified by a concurrency stress test? [Measurability, Spec §FR-018]
- [X] CHK021 Is the SC-002 ≤500ms budget for `app.dashboard` reproducible given a defined fixture (≥1 container, ≥1 agent, no cache)? [Measurability, Spec §SC-002]
- [X] CHK022 Is "best-effort consistent" (FR-018) measurable, or is it intentionally a documentation-only caveat? [Ambiguity, Spec §FR-018]

## Ambiguities, Conflicts, Gaps

- [X] CHK023 Is there a requirement that `app.dashboard` returns the same `app_contract_version` as `app.hello` for the same session? [Consistency, Spec §FR-033]
- [X] CHK024 Are dashboard count fields required to be non-negative integers, or could `-1` mean "unknown"? [Gap]
- [X] CHK025 Is the dashboard envelope's top-level structure (counts vs recents vs hints) explicitly specified, or left to implementer judgement? [Gap, Spec §FR-015..§FR-017]
- [X] CHK026 Is there a defined behavior when `app.dashboard` is called with `recent_limit = 0` (suppress recents entirely, or return empty arrays)? [Gap, Spec §FR-017]
