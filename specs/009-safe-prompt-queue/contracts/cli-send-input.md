# CLI Contract — `agenttower send-input`

**Branch**: `009-safe-prompt-queue`
**Surface**: `agenttower send-input ...` (bench-container thin client only — host invocation is refused with `sender_not_in_pane`).

## Synopsis

```text
agenttower send-input
    --target <agent-id-or-label>
    ( --message <text> | --message-file <path-or-dash> )
    [ --no-wait ]
    [ --wait-timeout <seconds> ]
    [ --json ]
    [ --help ]
```

## Arguments

| Flag                 | Required | Description                                                                                  |
|----------------------|----------|----------------------------------------------------------------------------------------------|
| `--target`           | Yes      | Resolves via `routing.target_resolver`: `agt_<12-hex>` → agent_id lookup; otherwise → label. |
| `--message`          | XOR      | Body as a single CLI string. Mutually exclusive with `--message-file`.                       |
| `--message-file`     | XOR      | Path to a file containing the raw body bytes. Use `-` for stdin. Mutually exclusive with `--message`. |
| `--no-wait`          | No       | Return immediately after enqueue; default is to wait for terminal state (FR-009).             |
| `--wait-timeout`     | No       | Seconds; default `10.0`; ignored under `--no-wait`. Range `[0.0, 300.0]`.                    |
| `--json`             | No       | Emit a single JSON object on stdout (`queue-row-schema.md` shape). Implies machine output.   |
| `--help`             | No       | Print help to stdout and exit `0`.                                                            |

Exactly one of `--message` or `--message-file` MUST be supplied
(FR-007). Otherwise the CLI exits non-zero with usage error
(argparse-driven, mapped to closed-set `bad_request` for `--json`).

## Caller context

Runs only from a bench-container thin client whose tmux pane
resolves to a registered, active `master` agent (FR-006 / Q3).
Host-side invocation is refused; the CLI surfaces
`sender_not_in_pane` and exits non-zero.

## Exit codes

The integer codes below may shift across MVP revisions; the
string code in `--json` output is the stable contract (FR-050).

| Integer | String code                  | Meaning                                                                 |
|---------|------------------------------|-------------------------------------------------------------------------|
| `0`     | (success)                    | `state=delivered` at return (FR-010).                                   |
| `1`     | `delivery_wait_timeout`      | `wait=true` budget elapsed; row still non-terminal.                     |
| `2`     | `kill_switch_off` / `routing_disabled` | Row landed in `blocked` due to disabled routing; CLI emits `routing_disabled` exit-code mapping. |
| `3`     | `sender_not_in_pane`         | Host-origin caller refused.                                             |
| `4`     | `sender_role_not_permitted`  | Pane not a master OR sender inactive.                                   |
| `5`     | `target_not_found`           | `--target` resolves to nothing.                                         |
| `6`     | `target_label_ambiguous`     | Multiple labels match.                                                  |
| `7`     | `target_not_active`          | Target marked inactive.                                                 |
| `8`     | `target_role_not_permitted`  | Target is not slave/swarm.                                              |
| `9`     | `target_container_inactive`  | Target container gone.                                                  |
| `10`    | `target_pane_missing`        | Target pane gone.                                                       |
| `11`    | `body_empty` / `body_invalid_encoding` / `body_invalid_chars` / `body_too_large` | Body validation failure (FR-003 / FR-004). |
| `12`    | `daemon_unavailable` / `daemon_shutting_down` | Socket unreachable / daemon shutting down.                              |
| `13`    | other terminal failures (`tmux_paste_failed`, etc.) | `state=failed` at return with the matching `failure_reason`.            |

`--json` mode always exits with the integer mapped from the
string code; the JSON object's `state` and `block_reason` /
`failure_reason` carry the stable string contract.

## Stdout / stderr discipline

### Human mode (default)

- On success (`exit 0`): one-line confirmation to stdout, e.g.
  `delivered: msg=<message_id> target=<label>(<agent_id>)`.
- On any non-`0` exit: one line on stderr, e.g.
  `send-input failed: <code> — <human message>`. Stdout receives
  nothing.

### `--json` mode

- On success and on every non-`0` exit: exactly one JSON object on
  stdout matching the `queue-row-schema.md` shape (FR-011). Stderr
  receives nothing.
- Field `state` is the terminal state (or the most recent non-
  terminal state under `delivery_wait_timeout`).
- Field `block_reason` / `failure_reason` carries the closed-set
  string code for blocked/failed rows.

## Examples

### Successful deliver

```bash
$ agenttower send-input --target worker-1 --message "do thing"
delivered: msg=12345678-1234-1234-1234-123456789012 target=worker-1(agt_aaa111bbb222)
$ echo $?
0
```

### Body from file (preferred for multi-line / shell-special bodies)

```bash
$ agenttower send-input --target worker-1 --message-file ./prompt.txt --json
{"message_id":"...","state":"delivered","sender":{"agent_id":"agt_abc123def456","label":"queen","role":"master","capability":"plan"},"target":{...},"enqueued_at":"2026-05-11T15:32:04.123Z","delivered_at":"2026-05-11T15:32:05.012Z","excerpt":"do thing"}
$ echo $?
0
```

### Kill switch refusal

```bash
$ agenttower send-input --target worker-1 --message "do thing"
send-input failed: routing_disabled — kill switch is off; row created in blocked state
$ echo $?
2
```

### Host-side invocation refused

```bash
$ agenttower send-input --target worker-1 --message "do thing"   # from host
send-input failed: sender_not_in_pane — send-input must run from within a registered tmux pane
$ echo $?
3
```
