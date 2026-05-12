# CLI Contract — `agenttower queue`

**Branch**: `009-safe-prompt-queue`
**Surface**: `agenttower queue ...` (host or bench-container thin client; no origin restriction).

## Subcommands

```text
agenttower queue                                    # list
agenttower queue approve <message-id>
agenttower queue delay   <message-id>
agenttower queue cancel  <message-id>
```

## `agenttower queue` (list)

### Synopsis

```text
agenttower queue
    [ --state    <state>      ]
    [ --target   <agent-or-label> ]
    [ --sender   <agent-or-label> ]
    [ --since    <iso8601-utc> ]
    [ --limit    <n>          ]
    [ --json     ]
    [ --help     ]
```

### Arguments

| Flag        | Description                                                                                  |
|-------------|----------------------------------------------------------------------------------------------|
| `--state`   | One of `queued | blocked | delivered | canceled | failed`.                                   |
| `--target`  | agent_id or label (R-001).                                                                   |
| `--sender`  | agent_id or label (R-001).                                                                   |
| `--since`   | ISO-8601 UTC, ms or seconds form (FR-012b / Q5).                                             |
| `--limit`   | Integer `1..1000`; default `100`.                                                            |
| `--json`    | Emit a JSON array of row objects (each row matches `queue-row-schema.md`).                   |
| `--help`    | Print help to stdout; exit `0`.                                                              |

Multiple filters are AND-combined (US3 #2 / FR-031). Ordering is
`enqueued_at ASC, message_id ASC`.

### Caller context

Any caller with socket access. The kill switch does not affect this
subcommand (FR-029).

### Stdout / stderr

#### Human mode (default)

- Tabular listing with one row per matching `message_queue` row.
- Default columns: `MESSAGE_ID  STATE  SENDER  TARGET  ENQUEUED  LAST_UPDATED  EXCERPT`.
- Sender / target columns render as `<label>(<agent_id-prefix>)` where the agent_id prefix
  is the first 8 hex chars (e.g., `worker-1(agt_aaa1)`).
- Empty result: one line on stdout — `(no rows match)`. Exit `0`.

#### `--json` mode

- One JSON array on stdout. Each element is the full row object per
  `queue-row-schema.md`.
- Empty result: `[]`. Exit `0`.

### Exit codes

| Integer | String code              | Meaning                                                |
|---------|--------------------------|--------------------------------------------------------|
| `0`     | (success)                | Listing returned (possibly empty).                     |
| `5`     | `agent_not_found`        | `--target` resolves to nothing.                        |
| `6`     | `target_label_ambiguous` | `--target` matches multiple active labels.             |
| `14`    | `since_invalid_format`   | `--since` cannot be parsed as ISO-8601 UTC.            |
| `12`    | `daemon_unavailable` / `daemon_shutting_down` | Daemon unreachable / shutting down. |

## `agenttower queue approve <message-id>`

### Synopsis

```text
agenttower queue approve <message-id> [ --json ] [ --help ]
```

### Caller context

Any caller. Operator identity is captured as the caller's pane
agent_id (bench container) or `host-operator` sentinel (host).

### Stdout / stderr

#### Human mode

- On success: `approved: msg=<id> state=queued` on stdout. Exit `0`.
- On any non-`0` exit: one line on stderr — `approve failed: <code> — <human message>`.

#### `--json` mode

- On success and on every non-`0` exit: one JSON object matching
  `queue-row-schema.md` on stdout (FR-032 / US3 #7).

### Exit codes

| Integer | String code                       | Meaning                                                                |
|---------|-----------------------------------|------------------------------------------------------------------------|
| `0`     | (success)                         | Row transitioned `blocked → queued`.                                   |
| `20`    | `message_id_not_found`            | `message_id` unknown.                                                  |
| `21`    | `operator_pane_inactive`          | Caller pane resolves to inactive / deregistered agent.                  |
| `15`    | `terminal_state_cannot_change`    | Row is `delivered`/`failed`/`canceled`.                                |
| `16`    | `delivery_in_progress`            | Row is mid-flight.                                                     |
| `17`    | `approval_not_applicable`         | `block_reason` not operator-resolvable, or `kill_switch_off` and switch is currently disabled. |
| `12`    | `daemon_unavailable` / `daemon_shutting_down` | Daemon unreachable / shutting down.                                    |

## `agenttower queue delay <message-id>`

### Synopsis

```text
agenttower queue delay <message-id> [ --json ] [ --help ]
```

### Caller context, stdout, JSON shape

Same as `approve` (operator identity captured the same way).

### Exit codes

| Integer | String code                       | Meaning                                                |
|---------|-----------------------------------|--------------------------------------------------------|
| `0`     | (success)                         | Row transitioned `queued → blocked` with `block_reason=operator_delayed`. |
| `20`    | `message_id_not_found`            | `message_id` unknown.                                  |
| `21`    | `operator_pane_inactive`          | Caller pane inactive/deregistered.                     |
| `15`    | `terminal_state_cannot_change`    | Row is terminal.                                       |
| `16`    | `delivery_in_progress`            | Row is mid-flight.                                     |
| `18`    | `delay_not_applicable`            | Row is already `blocked`.                              |
| `12`    | `daemon_unavailable` / `daemon_shutting_down` | Daemon unreachable / shutting down.                    |

## `agenttower queue cancel <message-id>`

### Synopsis

```text
agenttower queue cancel <message-id> [ --json ] [ --help ]
```

### Caller context, stdout, JSON shape

Same as `approve`.

### Exit codes

| Integer | String code                       | Meaning                                                |
|---------|-----------------------------------|--------------------------------------------------------|
| `0`     | (success)                         | Row transitioned to `canceled`.                        |
| `20`    | `message_id_not_found`            | `message_id` unknown.                                  |
| `21`    | `operator_pane_inactive`          | Caller pane inactive/deregistered.                     |
| `15`    | `terminal_state_cannot_change`    | Row already terminal.                                  |
| `16`    | `delivery_in_progress`            | Row is mid-flight.                                     |
| `12`    | `daemon_unavailable` / `daemon_shutting_down` | Daemon unreachable / shutting down.                    |

## Examples

```bash
$ agenttower queue --state blocked --target worker-1
MESSAGE_ID                            STATE    SENDER             TARGET             ENQUEUED                  LAST_UPDATED              EXCERPT
12345678-1234-1234-1234-123456789012  blocked  queen(agt_abc1)    worker-1(agt_aaa1) 2026-05-11T15:31:00.123Z  2026-05-11T15:31:00.300Z  do thing

$ agenttower queue approve 12345678-1234-1234-1234-123456789012
approved: msg=12345678-1234-1234-1234-123456789012 state=queued
```
