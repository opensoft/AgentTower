# Socket API Contract — Routing Methods

**Branch**: `009-safe-prompt-queue`
**Surface**: Daemon Unix socket (FEAT-002 envelope)

Three new methods controlling the global routing kill switch.

## routing.enable

Set `daemon_state.routing_enabled = "enabled"`.

### Request

```jsonc
{
  "method": "routing.enable",
  "params": {}
}
```

### Caller-context requirement (Clarifications Q2 / FR-027)

The dispatch layer enforces:

- `caller_pane is None` (else `routing_toggle_host_only`).
- `peer_uid == os.getuid()` (else `routing_toggle_host_only`).

### Success response

```jsonc
{
  "ok": true,
  "result": {
    "previous_value":  "disabled",                    // or "enabled" if already on
    "current_value":   "enabled",
    "changed":         true,
    "last_updated_at": "2026-05-11T15:32:04.123Z",
    "last_updated_by": "host-operator"
  }
}
```

`changed=false` if the flag was already `enabled` (no-op). The
audit row is appended only when `changed=true` (no duplicate
audit on idempotent calls).

### Error responses

| Code                       | Trigger                                                  |
|----------------------------|----------------------------------------------------------|
| `routing_toggle_host_only` | Caller is bench-container thin client (pane present).    |
| `daemon_shutting_down`     | Daemon is in shutdown.                                   |

## routing.disable

Set `daemon_state.routing_enabled = "disabled"`. Symmetric to
`routing.enable` in every respect: same caller-context check, same
response shape, same idempotent behavior. In-flight rows are NOT
preempted (Session 2 Q1 / FR-028).

### Request

```jsonc
{
  "method": "routing.disable",
  "params": {}
}
```

### Success response

Same shape as `routing.enable`; `current_value="disabled"`.

### Error responses

| Code                       | Trigger                                              |
|----------------------------|------------------------------------------------------|
| `routing_toggle_host_only` | Bench-container caller.                              |
| `daemon_shutting_down`     | Daemon is in shutdown.                               |

## routing.status

Read the current flag and its last-toggle metadata. Accepted from
any origin (host or bench container).

### Request

```jsonc
{
  "method": "routing.status",
  "params": {}
}
```

### Success response

```jsonc
{
  "ok": true,
  "result": {
    "value":            "enabled",                      // 'enabled' | 'disabled'
    "last_updated_at":  "2026-05-11T15:32:04.123Z",
    "last_updated_by":  "host-operator"                 // or "agt_<12-hex>" agent_id
  }
}
```

### Error responses

| Code                   | Trigger                          |
|------------------------|----------------------------------|
| `daemon_shutting_down` | Daemon is in shutdown.           |

## JSONL audit on toggle

Every successful toggle (`changed=true`) emits one
`queue_message_*`-namespace audit row of a new sub-type:

```jsonc
{
  "schema_version": 1,
  "event_type":     "routing_toggled",            // disjoint from queue_message_* (R-008)
  "previous_value": "enabled",
  "current_value":  "disabled",
  "observed_at":    "2026-05-11T15:32:04.123Z",
  "operator":       "host-operator"
}
```

Idempotent toggles (`changed=false`) do NOT emit an audit row.

The `routing_toggled` event type is added to the R-008 disjointness
test (FEAT-009 namespace now contains seven `queue_message_*` types
plus this one routing event).
