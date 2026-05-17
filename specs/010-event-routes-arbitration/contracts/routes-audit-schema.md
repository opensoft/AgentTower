# JSONL Audit Schema: Six FEAT-010 Audit Event Types

**Branch**: `010-event-routes-arbitration` | **Date**: 2026-05-16

FEAT-010 appends six new JSONL event types to the existing
FEAT-008 `events.jsonl` stream. All entries are appended via the
FEAT-001 `events.writer.append_event` helper. SQLite state
transitions (cursor advance, queue row insert) commit BEFORE the
JSONL append; durability failures buffer in memory and retry on
the next worker cycle (FR-039).

The five per-(route, event) and per-route-lifecycle types are
disjoint from the FEAT-008 classifier types, the FEAT-007
lifecycle types, and the FEAT-009 `queue_message_*` types. The
sixth (heartbeat) is emitted by the heartbeat thread (FR-039a).

## Common envelope fields

Every audit entry includes the FEAT-008 base envelope fields plus
the `emitted_at` ISO-8601-ms-UTC timestamp:

```json
{
  "event_type": "<one of the six>",
  "emitted_at": "2026-05-16T21:30:01.234Z",
  …type-specific fields…
}
```

Timestamps are produced by `routing.timestamps.now_iso_ms_utc()`.

## 1. `route_matched`

Emitted when a route's evaluation of an event reaches a terminal
"enqueue path was taken" decision (FR-035). The queue row was
inserted (possibly into `blocked` state if the kill switch is off
per Story 5 #1 — kill-switched inserts still produce
`route_matched`, not `route_skipped`).

```json
{
  "event_type": "route_matched",
  "emitted_at": "2026-05-16T21:30:01.234Z",
  "event_id": 4218,
  "route_id": "11111111-2222-4333-8444-555555555555",
  "winner_master_agent_id": "agt_aaa000111222",
  "target_agent_id": "agt_a1b2c3d4e5f6",
  "target_label": "slave-1",
  "reason": null,
  "event_excerpt": "Press y to continue"
}
```

| Field | Type | Notes |
|---|---|---|
| `event_id` | int | The FEAT-008 event being evaluated. |
| `route_id` | string | UUIDv4. |
| `winner_master_agent_id` | string | `agt_<12-hex>`. Always non-null for `route_matched`. |
| `target_agent_id` | string | `agt_<12-hex>` resolved per FR-021..023. Always non-null for `route_matched`. |
| `target_label` | string | Resolved at evaluation time from the agent registry. Always non-null for `route_matched`. |
| `reason` | null | Always `null` for `route_matched` (kept for shape uniformity with `route_skipped`). |
| `event_excerpt` | string | Redacted excerpt of the source event, ≤ 240 chars (FR-036). |

**Note**: The rendered template body is NOT included in
`route_matched` audit entries. The body lives only in the
`message_queue` row (`envelope_body` column from FEAT-009) and in
the downstream `queue_message_enqueued` / `queue_message_delivered`
JSONL entries (FEAT-009's excerpt convention). This avoids
duplicating the body across two audit streams.

## 2. `route_skipped`

Emitted when a route's evaluation of an event reaches a terminal
"no queue row" decision (FR-035). The cursor still advances per
FR-012.

```json
{
  "event_type": "route_skipped",
  "emitted_at": "2026-05-16T21:30:02.001Z",
  "event_id": 4220,
  "route_id": "11111111-2222-4333-8444-555555555555",
  "winner_master_agent_id": null,
  "target_agent_id": null,
  "target_label": null,
  "reason": "no_eligible_master",
  "sub_reason": null,
  "event_excerpt": "Some other prompt"
}
```

| Field | Type | Notes |
|---|---|---|
| `event_id`, `route_id`, `event_excerpt` | same as `route_matched` | |
| `winner_master_agent_id` | string OR `null` | Null for arbitration-failure skips (`no_eligible_master`, `master_inactive`, `master_not_found`); populated for target-failure skips and template-failure skips. |
| `target_agent_id` | string OR `null` | Null when target resolution never completed: skip reasons `no_eligible_master`, `no_eligible_target`. Populated when target resolution succeeded but enqueue failed (target_role_not_permitted, target_pane_missing, etc.) or when template-render failed (master + target both resolved). |
| `target_label` | string OR `null` | Same null-rule as `target_agent_id`. |
| `reason` | string | Closed set from FR-037: `no_eligible_master`, `master_inactive`, `master_not_found`, `target_not_found`, `target_role_not_permitted`, `target_not_active`, `target_pane_missing`, `target_container_inactive`, `no_eligible_target`, `template_render_error`. |
| `sub_reason` | string OR `null` | For `reason='template_render_error'`, one of: `missing_field`, `body_empty`, `body_invalid_chars`, `body_invalid_encoding`, `body_too_large`. Null for all other reasons. |

## 3. `route_created`

Emitted on successful `routes.add` (FR-035).

```json
{
  "event_type": "route_created",
  "emitted_at": "2026-05-16T21:30:00.123Z",
  "route_id": "11111111-2222-4333-8444-555555555555",
  "event_type_subscribed": "waiting_for_input",
  "source_scope_kind": "any",
  "source_scope_value": null,
  "target_rule": "explicit",
  "target_value": "agt_a1b2c3d4e5f6",
  "master_rule": "auto",
  "master_value": null,
  "template": "respond to {source_label}: {event_excerpt}",
  "created_by_agent_id": "host-operator",
  "cursor_at_creation": 4217
}
```

The field is named `event_type_subscribed` (rather than
`event_type`) to avoid name-collision with the envelope's
`event_type` field, which carries the audit-event-type discriminator.

## 4. `route_updated`

Emitted on successful enable/disable that actually flipped the
state (FR-009 idempotent: no audit on no-op).

```json
{
  "event_type": "route_updated",
  "emitted_at": "2026-05-16T21:36:00.001Z",
  "route_id": "11111111-2222-4333-8444-555555555555",
  "change": { "enabled": true },
  "updated_by_agent_id": "host-operator"
}
```

The `change` object enumerates exactly which field changed. In
MVP only `enabled` may change (FR-009a immutability); future
extensions could add more keys.

## 5. `route_deleted`

Emitted on successful `routes.remove` (FR-035).

```json
{
  "event_type": "route_deleted",
  "emitted_at": "2026-05-16T21:35:00.001Z",
  "route_id": "11111111-2222-4333-8444-555555555555",
  "deleted_by_agent_id": "host-operator"
}
```

The historical `route_matched`, `route_skipped`, and
`queue_message_*` entries for the deleted route remain intact —
their `route_id` becomes an orphan reference (FR-003).

## 6. `routing_worker_heartbeat`

Emitted by the heartbeat thread every `interval_seconds` (default
60s, bounds `[10, 3600]`), regardless of routing-cycle activity
(FR-039a + Clarifications Q3). The first heartbeat fires one full
interval after the worker thread enters its loop (no startup
beacon).

```json
{
  "event_type": "routing_worker_heartbeat",
  "emitted_at": "2026-05-16T21:31:00.123Z",
  "interval_seconds": 60,
  "cycles_since_last_heartbeat": 60,
  "events_consumed_since_last_heartbeat": 3,
  "skips_since_last_heartbeat": 1,
  "degraded": false
}
```

| Field | Type | Notes |
|---|---|---|
| `interval_seconds` | int | Configured interval at the moment of emission. |
| `cycles_since_last_heartbeat` | int ≥ 0 | Number of routing cycles that ran in the window. |
| `events_consumed_since_last_heartbeat` | int ≥ 0 | Sum across all routes of cursor advances in the window. |
| `skips_since_last_heartbeat` | int ≥ 0 | Sum across all routes of skips in the window. |
| `degraded` | bool | Mirrors `routing_worker_degraded` from `agenttower status` at the moment of emission. |

Counters reset to zero immediately after the heartbeat snapshot
(under the shared lock).

## Ordering & duplicates

- Within a single routing cycle, per-(route, event) audit entries
  are appended in the order events were processed (route order
  per FR-042; event order per FR-011).
- The `route_*` lifecycle entries are appended at the moment the
  SQLite transaction commits.
- Heartbeats are appended at their own cadence, interleaved
  with everything else as wall-clock time dictates.
- The JSONL stream may contain DUPLICATE entries during
  degraded-state retry (the buffer's drain may re-append an entry
  whose first attempt actually succeeded but the success was not
  recorded). Audit consumers MUST tolerate this — SQLite state
  is the source of truth (FR-039).

## AST-test invariant

A test (`tests/unit/test_no_per_cycle_audit_calls.py`) walks the
`worker.py` AST and asserts the only `append_event` calls in the
worker's hot path are for the five per-(route, event) and
lifecycle types. `routing_cycle_started` /
`routing_cycle_completed` MUST NOT appear (per Clarifications Q3
/ FR-035).
