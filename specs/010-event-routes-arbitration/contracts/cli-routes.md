# CLI Contract: `agenttower route ...`

**Branch**: `010-event-routes-arbitration` | **Date**: 2026-05-16

Six subcommands under `agenttower route`. Each accepts `--json`
and exits non-zero on any error with a closed-set string code
(per FR-049 revised + R13). All `--json` output goes to stdout;
human-format errors and warnings go to stderr.

The integer-to-string exit-code mapping is shared with the
existing FEAT-009 registry (`socket_api/errors.py`); tooling MUST
branch on the JSON `code` field, not on integer exit values
(FR-050).

## 1. `agenttower route add`

Create a new route. Cursor initializes to
`MAX(events.event_id) OR 0` (FR-002).

### Flags

| Flag | Required | Type | Notes |
|---|---|---|---|
| `--event-type <type>` | yes | string | One of the 10 FEAT-008 event types (FR-005). |
| `--source-scope <kind>` | no, default `any` | enum | `any`, `agent_id`, `role`. |
| `--source-scope-value <val>` | conditional | string | Required when `--source-scope != any`. `agt_<12-hex>` for `agent_id`; `role:<role>[,capability:<cap>]` for `role` (Clarifications Q1). |
| `--target-rule <rule>` | yes | enum | `explicit`, `source`, `role` (FR-006). |
| `--target <val>` | conditional | string | Required when `--target-rule != source`. `agt_<12-hex>` or label for `explicit`; `role:<role>[,capability:<cap>]` for `role`. |
| `--master-rule <rule>` | no, default `auto` | enum | `auto`, `explicit` (FR-007). |
| `--master <val>` | conditional | string | Required when `--master-rule = explicit`. `agt_<12-hex>`. |
| `--template <str>` | yes | string | UTF-8 ≤ 4 KiB; placeholders restricted to FR-008 whitelist. |
| `--json` | no | flag | If present, stdout = one JSON object; else human format. |

### Success response (`--json`)

Exit 0; stdout = exactly one JSON object:

```json
{
  "route_id": "11111111-2222-4333-8444-555555555555",
  "event_type": "waiting_for_input",
  "source_scope": {"kind": "any", "value": null},
  "target_rule": "explicit",
  "target_value": "agt_a1b2c3d4e5f6",
  "master_rule": "auto",
  "master_value": null,
  "template": "respond to {source_label}: {event_excerpt}",
  "enabled": true,
  "last_consumed_event_id": 4217,
  "created_at": "2026-05-16T21:30:00.123Z",
  "updated_at": "2026-05-16T21:30:00.123Z",
  "created_by_agent_id": "host-operator"
}
```

### Error responses

Exit non-zero with one JSON object `{"code": "<closed-set-code>",
"message": "<human msg>"}`:

| Code | When |
|---|---|
| `route_event_type_invalid` | `--event-type` not in FEAT-008 vocabulary (FR-005) |
| `route_master_rule_invalid` | `--master-rule` not in `{auto, explicit}` (FR-007) |
| `route_target_rule_invalid` | `--target-rule` not in `{explicit, source, role}` (FR-006) |
| `route_source_scope_invalid` | `--source-scope` not in `{any, agent_id, role}` OR value malformed (Clarifications Q1) |
| `route_template_invalid` | `--template` references field outside FR-008 whitelist |
| `route_creation_failed` | SQLite write failure |

Validation runs in order (FR-005 → FR-007 → FR-006 → source-scope →
target-value → FR-008 template), first failure wins (R15).

## 2. `agenttower route list`

List all routes ordered by `(created_at ASC, route_id ASC)`.

### Flags

| Flag | Required | Notes |
|---|---|---|
| `--enabled-only` | no | If present, only enabled routes. |
| `--json` | no | If present, stdout = JSON array. |

### Success response (`--json`)

Exit 0; stdout = JSON array of route objects (same shape as
`route add` success, no `runtime` sub-object):

```json
[
  {"route_id": "...", "event_type": "...", ...},
  ...
]
```

### Error responses

| Code | When |
|---|---|
| (none) | `route list` does not produce per-route errors; empty array on no rows. |

## 3. `agenttower route show <route-id>`

Show one route plus runtime stats.

### Flags

| Flag | Required | Notes |
|---|---|---|
| `<route-id>` | yes (positional) | UUIDv4 string. |
| `--json` | no | If present, stdout = JSON object. |

### Success response (`--json`)

Exit 0; stdout = one JSON object — same shape as `route add` plus
a `runtime` sub-object (FR-047):

```json
{
  "route_id": "...",
  ...,
  "runtime": {
    "last_routing_cycle_at": "2026-05-16T21:31:00.001Z",
    "events_consumed": 42,
    "last_skip_reason": "no_eligible_master",
    "last_skip_at": "2026-05-16T21:30:55.001Z"
  }
}
```

### Error responses

| Code | When |
|---|---|
| `route_id_not_found` | No row with the given `route_id` |

## 4. `agenttower route remove <route-id>`

Hard-delete a route. Audit `route_deleted`. Historical queue rows
referencing the route_id remain (orphan reference per FR-003).

### Success response (`--json`)

Exit 0; stdout = one JSON object:

```json
{
  "route_id": "11111111-2222-4333-8444-555555555555",
  "operation": "removed",
  "at": "2026-05-16T21:35:00.001Z"
}
```

### Error responses

| Code | When |
|---|---|
| `route_id_not_found` | No row with the given `route_id` |

## 5. `agenttower route enable <route-id>`

Set `enabled=1`. Idempotent: re-enabling an already-enabled route
succeeds without emitting a duplicate `route_updated` (FR-009).

### Success response (`--json`)

Exit 0; stdout = one JSON object:

```json
{
  "route_id": "11111111-2222-4333-8444-555555555555",
  "operation": "enabled",
  "at": "2026-05-16T21:36:00.001Z"
}
```

When already enabled (no-op), `operation` is still `enabled` and
exit is still 0; no audit entry emitted.

### Error responses

| Code | When |
|---|---|
| `route_id_not_found` | No row with the given `route_id` |

## 6. `agenttower route disable <route-id>`

Set `enabled=0`. Idempotent (FR-009).

### Success response (`--json`)

Exit 0; stdout = one JSON object:

```json
{
  "route_id": "11111111-2222-4333-8444-555555555555",
  "operation": "disabled",
  "at": "2026-05-16T21:37:00.001Z"
}
```

### Error responses

| Code | When |
|---|---|
| `route_id_not_found` | No row with the given `route_id` |

## 7. CLI absent on purpose

There is **no** `agenttower route update` command. Structural
edits (event_type, source_scope, target, master, template) require
`route remove` + `route add` (FR-009a per Clarifications Q5). The
help text for `agenttower route` SHOULD explicitly state this so
operators know the absence is intentional, not a TODO.

## 8. Human-format output (no `--json`)

Each subcommand produces a one-line summary on success:

```text
created route 11111111-2222-4333-8444-555555555555 (event_type=waiting_for_input enabled=true cursor=4217)
listed 3 routes (3 enabled, 0 disabled)
showed route 11111111-2222-4333-8444-555555555555 (events_consumed=42 last_skip_reason=no_eligible_master)
removed route 11111111-2222-4333-8444-555555555555
enabled route 11111111-2222-4333-8444-555555555555
disabled route 11111111-2222-4333-8444-555555555555
```

Errors print as `error: <code>: <message>` to stderr, then exit
non-zero.

## 9. CLI polish details (flag aliases, conventions, scale, help text)

These items close cli.md checklist gaps without altering the core
contract above.

- **Short-form flag aliases**: FEAT-010 does NOT define short-form
  aliases (e.g., no `-e` for `--event-type`) in MVP. Operators
  use long-form flags only. This matches FEAT-009's convention.
- **Mutually-exclusive flag combinations**: When `--target-rule=source`,
  `--target` MUST be omitted (the source agent supplies the
  target). When `--master-rule=auto`, `--master` MUST be omitted.
  Violating either combo yields `route_target_rule_invalid` or
  `route_master_rule_invalid` respectively, with the message text
  naming the conflict.
- **`--source-scope` value escape rules**: The
  `role:<role>[,capability:<cap>]` grammar treats `:` and `,` as
  reserved separators. Role and capability tokens MUST match
  `[A-Za-z0-9_-]+`; tokens containing reserved characters are
  rejected at parse time with `route_source_scope_invalid`. The
  same rule applies to `--target` under `--target-rule=role`.
- **Color / no-color output**: Human-format output respects the
  `NO_COLOR` environment variable convention (no FEAT-010-specific
  flag). When `NO_COLOR` is set OR stdout is not a TTY, no ANSI
  color escapes are emitted. This matches FEAT-009's convention.
- **Pagination for `route list`**: No pagination in MVP. SC-006
  validates 1000 routes in a single sub-500 ms response.
  Operators with > 10K routes can pipe through `jq` or `--enabled-only`
  for filtering.
- **Output filters for `route list`**: `--enabled-only` is the
  only filter in MVP. Filtering by `--event-type`, `--target`, or
  `--source-scope` is forward-compatible additive (out of MVP
  scope; operators can use `jq` on the JSON output).
- **Exit codes for transient failures**: SQLite-locked /
  daemon-unreachable / socket-timeout conditions return integer
  exit code `2` with string code `transient_unavailable` (inherits
  FEAT-002's transient-error vocabulary; distinct from FEAT-010's
  validation codes which are integers ≥ 10). Tooling MUST retry
  on `transient_unavailable` and surface as a hard failure
  otherwise.
- **CLI help text content requirements**: Each `agenttower route`
  subcommand MUST have a 1–2 line description, an example
  invocation, and a list of every flag with its purpose. The
  `route` group's main help text MUST cite the immutability rule
  (FR-009a) and direct operators to `route remove` + `route add`
  for structural changes. Implementation may use argparse's
  `description=` / `epilog=` for these blocks.
