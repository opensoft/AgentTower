# CLI Contract — `agenttower routing`

**Branch**: `009-safe-prompt-queue`
**Surface**: `agenttower routing enable | disable | status`

## Subcommands

```text
agenttower routing enable    [ --json ] [ --help ]
agenttower routing disable   [ --json ] [ --help ]
agenttower routing status    [ --json ] [ --help ]
```

## `agenttower routing enable`

Set the global routing kill switch to `enabled`.

### Caller context

Host-only (Clarifications Q2 / FR-027). Bench-container thin
clients receive `routing_toggle_host_only`.

### Stdout / stderr

#### Human mode (default)

- On no-op (`changed=false`): `routing already enabled` to stdout. Exit `0`.
- On change (`changed=true`): `routing enabled (was disabled)` to stdout. Exit `0`.
- On error: one line on stderr — `routing enable failed: <code> — <message>`.

#### `--json` mode

```jsonc
{
  "previous_value":  "disabled",
  "current_value":   "enabled",
  "changed":         true,
  "last_updated_at": "2026-05-11T15:32:04.123Z",
  "last_updated_by": "host-operator"
}
```

### Exit codes

| Integer | String code                  | Meaning                                            |
|---------|------------------------------|----------------------------------------------------|
| `0`     | (success)                    | Flag now `enabled` (changed or already).           |
| `19`    | `routing_toggle_host_only`   | Bench-container caller refused.                    |
| `12`    | `daemon_unavailable` / `daemon_shutting_down` | Daemon unreachable / shutting down. |

## `agenttower routing disable`

Set the global routing kill switch to `disabled`. Symmetric to
`enable`.

### Stdout / stderr

#### Human mode

- On no-op: `routing already disabled` to stdout. Exit `0`.
- On change: `routing disabled (was enabled)` to stdout. Exit `0`.
- On error: same pattern as `enable`.

#### `--json` mode

Same shape as `routing enable`, `current_value="disabled"`.

### Exit codes

Same as `routing enable`.

## `agenttower routing status`

Read the current flag and its last-toggle metadata.

### Caller context

Any caller (host or bench container). Useful for masters to check
before issuing `send-input`.

### Stdout / stderr

#### Human mode

- One line on stdout — `routing: enabled (set 2026-05-11T15:32:04.123Z by host-operator)`. Exit `0`.

#### `--json` mode

```jsonc
{
  "value":           "enabled",
  "last_updated_at": "2026-05-11T15:32:04.123Z",
  "last_updated_by": "host-operator"
}
```

### Exit codes

| Integer | String code            | Meaning                                       |
|---------|------------------------|-----------------------------------------------|
| `0`     | (success)              | Value returned.                               |
| `12`    | `daemon_unavailable` / `daemon_shutting_down` | Daemon unreachable / shutting down. |

## Examples

```bash
# From a bench container, master toggling fails.
$ agenttower routing disable
routing disable failed: routing_toggle_host_only — routing toggle requires host CLI
$ echo $?
19

# From the host.
$ agenttower routing disable
routing disabled (was enabled)
$ echo $?
0

# Status from anywhere.
$ agenttower routing status --json
{"value":"disabled","last_updated_at":"2026-05-11T15:32:04.123Z","last_updated_by":"host-operator"}
```
