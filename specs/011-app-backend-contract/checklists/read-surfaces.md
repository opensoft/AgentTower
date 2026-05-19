# Read Surfaces Requirements Quality Checklist: Local App Backend Contract (FEAT-011)

**Purpose**: Validate requirements quality for per-entity `app.<entity>.list` / `.detail` surfaces — pagination, ordering, filtering, derived fields.
**Created**: 2026-05-19
**Feature**: [spec.md](../spec.md)

## Requirement Completeness

- [ ] CHK001 Is the full enumerable list of `app.<entity>.list` / `.detail` methods specified (FR-019 lists 7 entities; is each name canonicalized)? [Completeness, Spec §FR-019]
- [ ] CHK002 Are the response fields specified per entity, or only for `pane` (FR-022) and `agent` (FR-023)? [Completeness, Spec §FR-022, §FR-023]
- [ ] CHK003 Is the `not_found` semantics on `app.<entity>.detail` defined consistently across all 7 entities? [Coverage, Spec §FR-034]
- [ ] CHK004 Are filter parameter sets enumerated per supported entity (events/queue/route — FR-024)? [Completeness, Spec §FR-024]
- [ ] CHK005 Is `since`/`until` time-range parameter format (ISO-8601 string, unix epoch int, both) defined? [Gap, Spec §FR-024]
- [ ] CHK006 Are derived fields beyond `registered`/`agent_id`/`log_attached`/`pane_active` enumerated where applicable (e.g., `log_attachment` derived `stale: bool`, `bytes_written`, `last_output_at`)? [Gap]
- [ ] CHK007 Is the `total_estimate` semantics defined (when is it used vs `total`, and how stale may the estimate be)? [Gap, Spec §FR-020]

## Requirement Clarity

- [ ] CHK008 Is `cursor_next` shape defined — opaque string, structured object, bounded length, base64-encoded? [Clarity, Spec §FR-020]
- [ ] CHK009 Is the `total` vs `total_estimate` selection rule clear (when does the daemon return one vs. the other)? [Clarity, Spec §FR-020]
- [ ] CHK010 Is `order_by`'s "closed set defined per surface" (FR-021) actually enumerated for any surface? [Gap, Spec §FR-021]
- [ ] CHK011 Is "default ordering" overridable in both directions (ASC and DESC) per surface? [Gap, Spec §FR-021]
- [ ] CHK012 Is the meaning of `state_priority` (used in queue ordering) defined as a specific ordering of `{pending, in_flight, delivered, cancelled, expired}`? [Gap, Spec §FR-021]
- [ ] CHK013 Is the meaning of `role_priority` (used in agent ordering) defined as a specific ordering across the FEAT-006 role set? [Gap, Spec §FR-021]

## Requirement Consistency

- [ ] CHK014 Are the entity names in FR-019 (`container`, `pane`, `agent`, `log_attachment`, `event`, `queue`, `route`) singular/plural-consistent across all FRs, user stories, and acceptance scenarios? [Consistency, Spec §FR-019]
- [ ] CHK015 Do FR-021's default orderings cover every entity in FR-019? [Consistency, Coverage]
- [ ] CHK016 Are pagination defaults (FR-020a: limit=50/cap=200) applied identically to all 7 list methods (e.g., `app.event.list` may be much larger than `app.route.list`)? [Consistency, Spec §FR-020a]
- [ ] CHK017 Are FR-022's `pane` derived fields consistent with the underlying FEAT-004 `panes` row vocabulary? [Consistency, Spec §FR-022]

## Scenario Coverage

- [ ] CHK018 Are requirements defined for invalid filter combinations (e.g., `since > until`)? [Gap, Spec §FR-024]
- [ ] CHK019 Are requirements defined for filtering by closed-set fields with values outside the closed set (`event_type=foo` where `foo` is not a valid event_type)? [Coverage, Spec §FR-024]
- [ ] CHK020 Are requirements defined for the page-size lower bound (e.g., `limit=0`, `limit=-1`)? [Coverage, Spec §FR-020a]
- [ ] CHK021 Is the behavior defined for an invalid or expired `cursor_next`? [Gap, Spec §FR-020]
- [ ] CHK022 Is the behavior defined when `cursor_next` is passed alongside a different `order_by` or filter than the prior page used? [Gap, Spec §FR-020]
- [ ] CHK023 Is the behavior defined for `app.<entity>.detail` with a malformed id (wrong type, wrong format)? [Gap]

## Measurability

- [ ] CHK024 Can FR-022 (`registered: bool` + nullable `agent_id`) be verified by a fixture comparison test for both registered and unregistered panes? [Measurability]
- [ ] CHK025 Can FR-021's default orderings be deterministically asserted in contract tests? [Measurability]
- [ ] CHK026 Is "consistent with FEAT-008/FEAT-009/FEAT-010 closed-set fields" (FR-024) testable via cross-reference, or only by inspection? [Measurability, Spec §FR-024]

## Ambiguities, Conflicts, Gaps

- [ ] CHK027 Is `registered_at` guaranteed to exist on every agent row (referenced by FR-021's agent ordering)? [Gap]
- [ ] CHK028 Is `last_output_at` guaranteed to exist on every `log_attachments` row (referenced by FR-021's ordering)? [Gap]
- [ ] CHK029 Is `event_id` monotonicity within the daemon guaranteed (referenced by FR-021's event ordering)? [Gap]
- [ ] CHK030 Is the rule defined for whether `app.<entity>.list` MAY return rows that no longer exist as of response time (snapshot vs. live read)? [Gap, Spec §FR-018]
- [ ] CHK031 Is the `agent_id` field's nullability on `app.pane.list` rows (FR-022) reflected in `app.agent.detail`'s response shape (must `null` map to a defined absent-agent state)? [Coverage]
