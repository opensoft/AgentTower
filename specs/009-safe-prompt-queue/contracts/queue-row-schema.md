# JSON Schema — Queue Row

**Branch**: `009-safe-prompt-queue`
**Surface**: Stable schema returned by `queue.send_input`, `queue.list`, `queue.approve`, `queue.delay`, `queue.cancel` (in the FEAT-002 `result` envelope) and by the four `agenttower` CLI subcommands under `--json` (FR-011).

## JSON Schema (Draft 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://agenttower.local/schemas/queue-row.v1.json",
  "title": "QueueRow",
  "type": "object",
  "required": [
    "message_id",
    "state",
    "block_reason",
    "failure_reason",
    "sender",
    "target",
    "envelope_size_bytes",
    "envelope_body_sha256",
    "enqueued_at",
    "delivery_attempt_started_at",
    "delivered_at",
    "failed_at",
    "canceled_at",
    "last_updated_at",
    "operator_action",
    "operator_action_at",
    "operator_action_by",
    "excerpt"
  ],
  "additionalProperties": false,
  "properties": {
    "message_id": {
      "type": "string",
      "description": "UUIDv4 string (FR-001).",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    },
    "state": {
      "type": "string",
      "enum": ["queued", "blocked", "delivered", "canceled", "failed"]
    },
    "block_reason": {
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
            "operator_delayed"
          ]
        }
      ]
    },
    "failure_reason": {
      "anyOf": [
        { "type": "null" },
        {
          "type": "string",
          "enum": [
            "attempt_interrupted",
            "tmux_paste_failed",
            "docker_exec_failed",
            "tmux_send_keys_failed",
            "pane_disappeared_mid_attempt"
          ]
        }
      ]
    },
    "sender": { "$ref": "#/$defs/AgentIdentity" },
    "target": { "$ref": "#/$defs/AgentIdentity" },
    "envelope_size_bytes": { "type": "integer", "minimum": 1 },
    "envelope_body_sha256": {
      "type": "string",
      "pattern": "^[0-9a-f]{64}$"
    },
    "enqueued_at":                  { "$ref": "#/$defs/Timestamp" },
    "delivery_attempt_started_at":  { "anyOf": [ { "type": "null" }, { "$ref": "#/$defs/Timestamp" } ] },
    "delivered_at":                 { "anyOf": [ { "type": "null" }, { "$ref": "#/$defs/Timestamp" } ] },
    "failed_at":                    { "anyOf": [ { "type": "null" }, { "$ref": "#/$defs/Timestamp" } ] },
    "canceled_at":                  { "anyOf": [ { "type": "null" }, { "$ref": "#/$defs/Timestamp" } ] },
    "last_updated_at":              { "$ref": "#/$defs/Timestamp" },
    "operator_action": {
      "anyOf": [
        { "type": "null" },
        {
          "type": "string",
          "enum": ["approved", "delayed", "canceled"]
        }
      ]
    },
    "operator_action_at": {
      "anyOf": [ { "type": "null" }, { "$ref": "#/$defs/Timestamp" } ]
    },
    "operator_action_by": {
      "anyOf": [
        { "type": "null" },
        { "type": "string", "pattern": "^(agt_[0-9a-f]{12}|host-operator)$" }
      ]
    },
    "excerpt": {
      "type": "string",
      "maxLength": 241,
      "description": "Redacted, whitespace-collapsed body excerpt; ≤ 240 chars + optional U+2026 truncation marker (FR-047b). Always single-line."
    }
  },
  "allOf": [
    {
      "if":   { "properties": { "state": { "const": "blocked" } }, "required": ["state"] },
      "then": { "required": ["block_reason"], "properties": { "block_reason": { "type": "string" } } }
    },
    {
      "if":   { "properties": { "state": { "const": "failed" } }, "required": ["state"] },
      "then": { "required": ["failure_reason"], "properties": { "failure_reason": { "type": "string" } } }
    },
    {
      "if":   { "properties": { "state": { "const": "delivered" } }, "required": ["state"] },
      "then": { "required": ["delivered_at"], "properties": { "delivered_at": { "$ref": "#/$defs/Timestamp" } } }
    },
    {
      "if":   { "properties": { "state": { "const": "canceled" } }, "required": ["state"] },
      "then": { "required": ["canceled_at"], "properties": { "canceled_at": { "$ref": "#/$defs/Timestamp" } } }
    }
  ],
  "$defs": {
    "AgentIdentity": {
      "type": "object",
      "required": ["agent_id", "label", "role"],
      "additionalProperties": false,
      "properties": {
        "agent_id": { "type": "string", "pattern": "^agt_[0-9a-f]{12}$" },
        "label":    { "type": "string", "minLength": 1 },
        "role":     { "type": "string", "enum": ["master", "slave", "swarm", "test-runner", "shell", "unknown"] },
        "capability": { "anyOf": [ { "type": "null" }, { "type": "string" } ] }
      }
    },
    "Timestamp": {
      "type": "string",
      "description": "ISO-8601 ms UTC with literal Z suffix (FR-012b).",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$"
    }
  }
}
```

## Notes

- All `--json` outputs (single object for `send-input` / `approve` / `delay` / `cancel`; array of objects for `queue` list) carry rows matching this schema verbatim.
- Single-object envelopes from `queue.send_input` and the operator-action methods are guaranteed to be exactly one line of JSON on stdout (NDJSON-compatible — Session 2 Q5 / UX-CHK023 implication).
- The `additionalProperties: false` clause means any future field requires a `schema_version` bump in the row contract (current implicit version `1` — recorded as `schema_version` only in the JSONL audit shape).
- Tests load this schema as `tests/fixtures/queue_row_schema.json` and validate every fixture under unit + integration tests.
