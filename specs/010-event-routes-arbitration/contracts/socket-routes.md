# Socket Contract: `routes.*` methods

**Branch**: `010-event-routes-arbitration` | **Date**: 2026-05-16

Six new socket methods over the existing FEAT-002 thin-client
envelope. Method names use a `routes.*` namespace (plural,
matching FEAT-009's `queue.*` and `routing.*` conventions).

All methods accept the standard FEAT-002 envelope (method, params,
caller_context) and return either a success JSON object or a
closed-set error code mapped from a `RouteError` exception via
`route_errors.py`.

## 1. `routes.add`

**Params**:
```json
{
  "event_type": "waiting_for_input",
  "source_scope_kind": "any",
  "source_scope_value": null,
  "target_rule": "explicit",
  "target_value": "agt_a1b2c3d4e5f6",
  "master_rule": "auto",
  "master_value": null,
  "template": "respond to {source_label}: {event_excerpt}"
}
```

**Caller context** (per FEAT-005): `created_by_agent_id` is
derived from the caller-identity headers. Host-CLI caller →
`'host-operator'` sentinel. Bench-container caller →
`agt_<12-hex>` of the registered caller agent.

**Success**:
```json
{
  "route_id": "...",
  "event_type": "...",
  …full route row…
}
```

**Error codes** (closed set):
- `route_event_type_invalid`
- `route_master_rule_invalid`
- `route_target_rule_invalid`
- `route_source_scope_invalid`
- `route_template_invalid`
- `route_creation_failed`

## 2. `routes.list`

**Params**:
```json
{ "enabled_only": false }
```

**Success**:
```json
{
  "routes": [
    {"route_id": "...", …},
    …
  ]
}
```

Ordered by `(created_at ASC, route_id ASC)`.

**Error codes**: none.

## 3. `routes.show`

**Params**:
```json
{ "route_id": "..." }
```

**Success**:
```json
{
  "route_id": "...",
  …full route row…,
  "runtime": {
    "last_routing_cycle_at": "...",
    "events_consumed": 42,
    "last_skip_reason": "no_eligible_master" | null,
    "last_skip_at": "..." | null
  }
}
```

**Error codes**:
- `route_id_not_found`

## 4. `routes.remove`

**Params**:
```json
{ "route_id": "..." }
```

**Success**:
```json
{
  "route_id": "...",
  "operation": "removed",
  "at": "..."
}
```

Audit: `route_deleted`.

**Error codes**:
- `route_id_not_found`

## 5. `routes.enable`

**Params**:
```json
{ "route_id": "..." }
```

**Success**:
```json
{
  "route_id": "...",
  "operation": "enabled",
  "at": "..."
}
```

Audit: `route_updated` (with `change: {enabled: true}`) IFF the
state actually flipped. Already-enabled → no audit, still 0 exit
(FR-009 idempotent).

**Error codes**:
- `route_id_not_found`

## 6. `routes.disable`

**Params**:
```json
{ "route_id": "..." }
```

**Success**:
```json
{
  "route_id": "...",
  "operation": "disabled",
  "at": "..."
}
```

Audit: `route_updated` (with `change: {enabled: false}`) IFF the
state actually flipped.

**Error codes**:
- `route_id_not_found`

## Authorization

FEAT-010 MVP does NOT enforce host-vs-container restrictions on
`routes.*` methods. Any caller with socket access can invoke any
method. This matches the FEAT-009 socket-boundary assumption
("host-user only at the socket boundary"); per-caller RBAC is a
follow-up feature (spec Assumptions).

The two FEAT-009 commands that DO enforce host-only —
`routing.enable` / `routing.disable` — remain host-only and
continue to use FEAT-002's `socket_peer_uid` check.

## Existing socket-method extensions

| Method | FEAT-010 change |
|---|---|
| `queue.list` (FEAT-009) | New optional param `origin_filter: 'direct'|'route'|null` (default null = no filter). |
| `queue.send_input` (FEAT-009) | NO public change. The internal handler gains `_origin`, `_route_id`, `_event_id` kw-only args but the socket dispatcher does NOT forward them (R7). |
| `status` (FEAT-009) | Response gains a `routing` sub-object per `cli-status-routing.md`. |

## Error envelope

All errors use the existing FEAT-002 envelope:

```json
{
  "ok": false,
  "error": {
    "code": "route_id_not_found",
    "message": "no route with route_id=11111111-..."
  }
}
```

Success envelope:

```json
{
  "ok": true,
  "result": { … method-specific … }
}
```
