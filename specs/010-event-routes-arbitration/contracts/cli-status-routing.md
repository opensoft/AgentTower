# CLI Contract: `agenttower status` (routing section)

**Branch**: `010-event-routes-arbitration` | **Date**: 2026-05-16

FEAT-010 extends the existing `agenttower status` (and its
`--json` form) with a new top-level `routing` object exposing
routing-worker health. Read-only; no operator actions live here.

## JSON-shape extension (FR-038)

`agenttower status --json` now includes:

```json
{
  …existing top-level fields unchanged…,
  "routing": {
    "routes_total": 12,
    "routes_enabled": 11,
    "routes_disabled": 1,
    "last_routing_cycle_at": "2026-05-16T21:31:00.001Z",
    "events_consumed_total": 42,
    "skips_by_reason": {
      "no_eligible_master": 3,
      "target_not_found": 1
    },
    "most_stalled_route": {
      "route_id": "11111111-2222-4333-8444-555555555555",
      "lag": 27
    },
    "routing_worker_degraded": false,
    "degraded_routing_audit_persistence": false
  }
}
```

### Field semantics

| Field | Type | Semantics |
|---|---|---|
| `routes_total` | int ≥ 0 | Count of rows in `routes`. |
| `routes_enabled` | int ≥ 0 | Count where `enabled=1`. |
| `routes_disabled` | int ≥ 0 | Count where `enabled=0`. |
| `last_routing_cycle_at` | ISO-8601 ms UTC string OR `null` | Wall-clock timestamp of the most recent worker cycle completion. `null` if no cycle has run yet (daemon just started). |
| `events_consumed_total` | int ≥ 0 | Sum across all routes of cursor-advance count since daemon start. Resets to 0 on daemon restart. |
| `skips_by_reason` | object | Keys are closed-set FR-037 reasons; values are counts since daemon start. Reasons with zero skips MAY be omitted (sparse map). |
| `most_stalled_route` | object OR `null` | The single enabled route with the largest count of unconsumed matching events (lag). `null` when no enabled route has lag > 0. Ties broken by `(created_at, route_id)`. |
| `routing_worker_degraded` | bool | `true` iff the worker is currently in a degraded state (transient internal errors, audit-append failures). |
| `degraded_routing_audit_persistence` | bool | `true` iff the audit buffer has pending unflushed entries. Mirrors FEAT-008's `degraded_events_persistence` pattern. |

### `most_stalled_route.lag` computation

For each enabled route, lag is the number of events in `events`
where `event_id > route.last_consumed_event_id` AND
`event_type = route.event_type` AND the source matches the
route's `source_scope`. The most-stalled route is the one with
the largest lag; `null` if all enabled routes have lag 0.

The query SHOULD use the existing FEAT-008 events index on
`(event_type, event_id)` for an indexed scan per route. At 1000
routes × 1000 events, this is bounded by SC-006's 500ms target
for the `route list` operation (the `status --json` call is
allowed up to 1s under MVP — explicitly documented to operators
in the human help text).

## Human-format output

`agenttower status` (no `--json`) appends a section after the
existing FEAT-009 routing kill-switch status:

```text
Routing:
  Routes: 12 total (11 enabled, 1 disabled)
  Last cycle: 2026-05-16T21:31:00.001Z
  Events consumed (since start): 42
  Skips by reason:
    no_eligible_master: 3
    target_not_found: 1
  Most stalled: 11111111-... (lag=27)
  Worker degraded: false
  Audit buffer degraded: false
```

## Exit-code behavior

`agenttower status` always exits 0 (read-only), even when
`routing_worker_degraded=true` — operators detect degradation by
parsing the field, not by exit code. This matches FEAT-008's
status contract.

## Backward compatibility

The `routing` object is a new top-level field. Existing scripts
that parsed `status --json` continue to work; clients that don't
care about FEAT-010 can ignore the new field.

The pre-existing FEAT-009 `routing` field on `status --json` (the
kill-switch state, `routing.enabled`, etc.) is preserved at the
exact same path. FEAT-010 adds its fields **inside the same
`routing` object**, not at a sibling path, so the merge is:

```json
{
  "routing": {
    "enabled": true,                   // FEAT-009 kill switch state
    "last_toggled_at": "...",           // FEAT-009
    "last_toggled_by_agent_id": "...",  // FEAT-009
    "routes_total": 12,                 // FEAT-010 (new)
    "routes_enabled": 11,               // FEAT-010 (new)
    …rest of FEAT-010 fields…
  }
}
```

This is intentional: operators conceptualize "routing" as one
subsystem; merging the kill-switch state and the worker state
under one object matches that mental model.

## Fan-out visibility

`agenttower status --json` does NOT expose per-route fan-out
distribution (how many queue rows each route has produced). That
information is available via `agenttower queue --origin route
--json | jq 'group_by(.route_id) | map({route_id: .[0].route_id,
count: length})'`. A dedicated `routing.fan_out` status field is
forward-compatible additive (out of MVP scope).

## Access from inside bench containers

`agenttower status` is read-only and accessible from both the host
CLI and bench-container CLI; FEAT-010 adds no caller-origin
restriction on the status surface. Bench-container operators see
the same `routing` object as host-CLI operators.
