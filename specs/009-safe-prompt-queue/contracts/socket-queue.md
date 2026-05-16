# Socket API Contract — Queue Methods

**Branch**: `009-safe-prompt-queue`
**Surface**: Daemon Unix socket (FEAT-002 envelope)

Five new methods, all dispatched through the existing FEAT-002
`SocketServer` and routed by `socket_api.methods`. Every method
accepts the standard FEAT-002 request envelope and returns the
standard `{ok: true, result: ...}` or `{ok: false, error: ...}`
envelope.

## queue.send_input

Create a new `message_queue` row from a master agent.

### Request

```jsonc
{
  "method": "queue.send_input",
  "params": {
    "target":      "agt_aaa111bbb222",          // required; agent_id or label (R-001)
    "body_bytes":  "<base64-standard-no-newlines>",  // required; raw body bytes (BLOB), pre-FR-003 check
    "wait":        true,                         // optional; default true (FR-009)
    "wait_timeout_seconds": 10.0                 // optional; bounded [0.0, 300.0]
  }
}
```

- `body_bytes` is the raw envelope body as base64 — the *transport*
  encoding only; the daemon decodes and stores the resulting `bytes`
  in `envelope_body` (R-002).
- `wait=true` blocks the response until the row reaches a terminal
  state OR the wait budget elapses (FR-009). `wait=false` returns
  immediately after enqueue.

### Caller-context requirement (FR-006)

The dispatch layer enforces:

- `caller_pane is not None` (else `sender_not_in_pane`).
- The pane resolves to a registered, active `master` agent (else
  `sender_role_not_permitted`).

### Success response

```jsonc
{
  "ok": true,
  "result": {
    "message_id":  "<uuidv4>",
    "state":       "delivered",        // terminal at return when wait=true
    "block_reason": null,
    "failure_reason": null,
    "sender":  { "agent_id": "...", "label": "...", "role": "master",   "capability": "..." },
    "target":  { "agent_id": "...", "label": "...", "role": "slave",    "capability": "..." },
    "enqueued_at":                   "2026-05-11T15:32:04.123Z",
    "delivery_attempt_started_at":   "2026-05-11T15:32:04.500Z",
    "delivered_at":                  "2026-05-11T15:32:05.012Z",
    "failed_at":                     null,
    "canceled_at":                   null,
    "excerpt":                       "do thing"
  }
}
```

If `wait=true` and the wait budget elapses with the row still
non-terminal, the daemon returns success with the row's current
state (most commonly `queued` or `blocked`) — the CLI maps this to
exit code `delivery_wait_timeout`.

### Error responses (closed set)

| Code                          | Trigger                                                                |
|-------------------------------|------------------------------------------------------------------------|
| `sender_not_in_pane`          | Host-origin caller; pane context absent.                               |
| `sender_role_not_permitted`   | Sender pane resolves to non-master OR inactive sender (FR-021/023).    |
| `agent_not_found`             | `--target` resolution fails (no agent_id, no label).                   |
| `target_label_ambiguous`      | Multiple active labels match (R-001).                                  |
| `body_empty`                  | Body length 0 after base64 decode (FR-003).                            |
| `body_invalid_encoding`       | Body is not valid UTF-8 (FR-003).                                       |
| `body_invalid_chars`          | NUL or disallowed ASCII control (FR-003).                              |
| `body_too_large`              | Serialized envelope exceeds cap (FR-004).                              |
| `daemon_shutting_down`        | Daemon is in shutdown.                                                  |
| `kill_switch_off`             | Row created in `blocked` state with this reason — the CLI surfaces it.  |

Note `kill_switch_off` is delivered as a *success* envelope with
`state="blocked"` and `block_reason="kill_switch_off"`; the CLI
maps it to the `routing_disabled` exit code (cli-send-input.md).

## queue.list

List `message_queue` rows with filters.

### Request

```jsonc
{
  "method": "queue.list",
  "params": {
    "state":   "queued",                       // optional; closed set §4.1 of data-model
    "target":  "agt_aaa111bbb222",             // optional; agent_id or label
    "sender":  "agt_abc123def456",             // optional; agent_id or label
    "since":   "2026-05-11T00:00:00.000Z",     // optional; ms or seconds form (FR-012b)
    "limit":   100,                            // optional; 1..1000, default 100
    "cursor":  "<opaque-cursor>"               // optional; reserved for future pagination
  }
}
```

### Caller-context requirement

No origin restriction (FR-029 — queue read works under kill switch).

### Success response

```jsonc
{
  "ok": true,
  "result": {
    "rows": [
      { /* one row object matching the FR-011 shape */ },
      ...
    ],
    "next_cursor": null   // reserved for future use
  }
}
```

Ordering: `enqueued_at ASC, message_id ASC` (FR-031).

### Error responses

| Code                    | Trigger                                              |
|-------------------------|------------------------------------------------------|
| `agent_not_found`       | `--target` resolution fails.                         |
| `target_label_ambiguous`| Multiple labels match.                               |
| `since_invalid_format`  | `--since` does not parse as ms or seconds UTC form.  |

## queue.approve

Operator-driven `blocked → queued` transition (FR-032 – FR-033).

### Request

```jsonc
{
  "method": "queue.approve",
  "params": { "message_id": "<uuidv4>" }
}
```

### Caller-context requirement

No origin restriction in MVP (host or bench-container masters may
approve). Operator identity recorded:

- Bench-container caller → `caller_pane`'s agent_id.
- Host caller → `HOST_OPERATOR_SENTINEL` (`"host-operator"`).

### Success response

Same shape as `queue.send_input` success, reflecting the row's new
state (now `queued`).

### Error responses

| Code                            | Trigger                                                                  |
|---------------------------------|--------------------------------------------------------------------------|
| `message_id_not_found`          | `message_id` does not exist in `message_queue`.                          |
| `operator_pane_inactive`        | Caller pane resolves to an inactive or deregistered agent (bench-container callers only; host callers use `host-operator` sentinel). |
| `terminal_state_cannot_change`  | Row is in `delivered`/`failed`/`canceled`.                               |
| `delivery_in_progress`          | Row has `delivery_attempt_started_at` set and terminal stamps unset.     |
| `approval_not_applicable`       | Row's `block_reason` is intrinsic (`sender_role_not_permitted` / `target_role_not_permitted`) OR `kill_switch_off` while the switch is disabled. |

Note: `message_id` lookup failures use a distinct closed-set code
`message_id_not_found` (introduced for FEAT-009 to keep agent-lookup
failures aligned with FEAT-008's `agent_not_found`). The operator's
remediation differs slightly: `agent_not_found` means "verify the
agent identifier"; `message_id_not_found` means "verify the row id
from a prior `queue` listing".

## queue.delay

Operator-driven `queued → blocked` transition (FR-034).

### Request

```jsonc
{
  "method": "queue.delay",
  "params": { "message_id": "<uuidv4>" }
}
```

### Success response

Same shape as `queue.send_input` success; new `state="blocked"`,
`block_reason="operator_delayed"`.

### Error responses

| Code                            | Trigger                                                |
|---------------------------------|--------------------------------------------------------|
| `message_id_not_found`          | `message_id` unknown.                                  |
| `operator_pane_inactive`        | Caller pane resolves to inactive/deregistered agent.   |
| `terminal_state_cannot_change`  | Row is terminal.                                       |
| `delay_not_applicable`          | Row is already `blocked`.                              |
| `delivery_in_progress`          | Row is in flight.                                      |

## queue.cancel

Operator-driven transition to terminal `canceled` (FR-035).

### Request

```jsonc
{
  "method": "queue.cancel",
  "params": { "message_id": "<uuidv4>" }
}
```

### Success response

Same shape as `queue.send_input` success; new `state="canceled"`,
`canceled_at` populated.

### Error responses

| Code                            | Trigger                                  |
|---------------------------------|------------------------------------------|
| `message_id_not_found`          | `message_id` unknown.                    |
| `operator_pane_inactive`        | Caller pane inactive/deregistered.       |
| `terminal_state_cannot_change`  | Row is already terminal.                 |
| `delivery_in_progress`          | Row is in flight.                        |

## Envelope serialization

Every response field encoding follows `queue-row-schema.md`. Every
timestamp is the canonical ISO-8601 ms UTC form (FR-012b). Every
error envelope follows FEAT-002:

```jsonc
{
  "ok": false,
  "error": { "code": "<closed-set>", "message": "<human readable>" }
}
```
