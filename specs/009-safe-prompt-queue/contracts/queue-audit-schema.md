# JSON Schema — Queue Audit Entry (events.jsonl)

**Branch**: `009-safe-prompt-queue`
**Surface**: One JSONL record per state transition, appended to the existing FEAT-008 `events.jsonl` stream.

## JSON Schema (Draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://agenttower.local/schemas/queue-audit.v1.json",
  "title": "QueueAuditEntry",
  "type": "object",
  "required": [
    "schema_version",
    "event_type",
    "message_id",
    "from_state",
    "to_state",
    "reason",
    "operator",
    "observed_at",
    "sender",
    "target",
    "excerpt"
  ],
  "additionalProperties": false,
  "properties": {
    "schema_version": {
      "type": "integer",
      "const": 1
    },
    "event_type": {
      "type": "string",
      "enum": [
        "queue_message_enqueued",
        "queue_message_delivered",
        "queue_message_blocked",
        "queue_message_failed",
        "queue_message_canceled",
        "queue_message_approved",
        "queue_message_delayed"
      ]
    },
    "message_id": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    },
    "from_state": {
      "anyOf": [
        { "type": "null" },
        { "type": "string", "enum": ["queued", "blocked", "delivered", "canceled", "failed"] }
      ]
    },
    "to_state": {
      "type": "string",
      "enum": ["queued", "blocked", "delivered", "canceled", "failed"]
    },
    "reason": {
      "anyOf": [
        { "type": "null" },
        {
          "type": "string",
          "enum": [
            "sender_role_not_permitted",
            "target_role_not_permitted",
            "target_not_active",
            "target_pane_missing",
            "target_container_inactive",
            "kill_switch_off",
            "operator_delayed",
            "attempt_interrupted",
            "tmux_paste_failed",
            "docker_exec_failed",
            "tmux_send_keys_failed",
            "pane_disappeared_mid_attempt",
            "sqlite_lock_conflict"
          ]
        }
      ]
    },
    "operator": {
      "anyOf": [
        { "type": "null" },
        { "type": "string", "pattern": "^(agt_[0-9a-f]{12}|host-operator)$" }
      ],
      "description": "null for worker-driven transitions; agent_id or host-operator sentinel for operator-driven transitions."
    },
    "observed_at": {
      "type": "string",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"
    },
    "sender": { "$ref": "#/$defs/AgentIdentity" },
    "target": { "$ref": "#/$defs/AgentIdentity" },
    "excerpt": {
      "type": "string",
      "maxLength": 241,
      "description": "Redacted, whitespace-collapsed body excerpt (FR-047b). Always single-line."
    }
  },
  "$defs": {
    "AgentIdentity": {
      "type": "object",
      "required": ["agent_id", "label", "role"],
      "additionalProperties": false,
      "properties": {
        "agent_id":   { "type": "string", "pattern": "^agt_[0-9a-f]{12}$" },
        "label":      { "type": "string", "minLength": 1 },
        "role":       { "type": "string", "enum": ["master", "slave", "swarm", "test-runner", "shell", "unknown"] },
        "capability": { "anyOf": [ { "type": "null" }, { "type": "string" } ] }
      }
    }
  }
}
```

## Routing toggle audit entry (separate schema)

`routing_toggled` events use a sibling schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://agenttower.local/schemas/routing-audit.v1.json",
  "title": "RoutingAuditEntry",
  "type": "object",
  "required": ["schema_version", "event_type", "previous_value", "current_value", "observed_at", "operator"],
  "additionalProperties": false,
  "properties": {
    "schema_version": { "type": "integer", "const": 1 },
    "event_type":     { "type": "string", "const": "routing_toggled" },
    "previous_value": { "type": "string", "enum": ["enabled", "disabled"] },
    "current_value":  { "type": "string", "enum": ["enabled", "disabled"] },
    "observed_at":    { "type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$" },
    "operator":       { "type": "string", "pattern": "^(agt_[0-9a-f]{12}|host-operator)$" }
  }
}
```

## Reason-field discipline

- `reason` is `null` for `queue_message_delivered` and `queue_message_canceled` when the transition originates from the worker / operator-cancel path with no closed-set reason to record.
- `reason` carries the `block_reason` closed-set value for `queue_message_blocked` and `queue_message_approved` (the operator action that resolved which block reason).
- `reason` carries the `failure_reason` closed-set value for `queue_message_failed`.
- `reason` is `"operator_delayed"` for `queue_message_delayed`.
- `reason` is `null` for `queue_message_enqueued` when the row lands in `queued`; carries the `block_reason` when the row lands in `blocked` at enqueue.

## Disjointness

The seven `queue_message_*` types plus `routing_toggled` MUST be
disjoint from the FEAT-007 lifecycle event types and the FEAT-008
ten durable types (R-008). The disjointness test imports the closed
sets from each domain's `__init__.py` and asserts pairwise non-
intersection.

## Reconstructability

SC-006 demands that every queue row's full transition history is
reconstructible from JSONL alone. For each `message_id`, the audit
stream contains:

- Exactly one `queue_message_enqueued`.
- Zero or more `queue_message_blocked` / `queue_message_approved` /
  `queue_message_delayed` rows for blocked-state interactions.
- Exactly one terminal row (`queue_message_delivered`,
  `queue_message_failed`, or `queue_message_canceled`).

A consumer reading `events.jsonl` and filtering by `message_id` can
reconstruct the full state machine without consulting SQLite.
