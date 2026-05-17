# CLI Contract: `agenttower queue --origin` (filter extension)

**Branch**: `010-event-routes-arbitration` | **Date**: 2026-05-16

FEAT-010 extends the existing FEAT-009 `agenttower queue` CLI
with one new flag: `--origin {direct|route}`. No other change to
the CLI shape.

## Flag

| Flag | Required | Type | Notes |
|---|---|---|---|
| `--origin <origin>` | no | enum | `direct` or `route`. Omit for no filter (default: both origins). |

## Behavior

- `agenttower queue --json` — returns all rows (both origins), per
  existing FEAT-009 contract.
- `agenttower queue --origin direct --json` — returns only rows
  with `origin='direct'` (FEAT-009 direct sends).
- `agenttower queue --origin route --json` — returns only rows
  with `origin='route'` (FEAT-010 route-generated).
- `agenttower queue --origin <other> --json` — exits non-zero with
  closed-set CLI error `queue_origin_invalid` (added to FEAT-009
  vocabulary). Acceptance values are exactly `{direct, route}`.

## JSON-shape extension (FR-033)

Every queue row in `--json` output gains three new fields,
populated unconditionally (NULL for direct rows; non-null for
route rows):

```json
{
  "message_id": "...",
  "origin": "direct" | "route",
  "route_id": null | "<uuid>",
  "event_id": null | <int>,
  …rest of FEAT-009 fields unchanged…
}
```

Existing FEAT-009 scripts that parsed `agenttower queue --json`
continue to work because the schema is additive — the three new
fields can be ignored by clients that don't care.

## Other queue operations

`agenttower queue approve <id>`, `queue delay <id>`,
`queue cancel <id>` are unchanged from FEAT-009. They work on
route-generated rows under the same rules as direct-send rows
(FR-034); the audit entry's `event_type` (e.g.,
`queue_message_canceled`) is identical in shape — only the
`origin`, `route_id`, `event_id` discriminators differ from the
direct-send case.

## Human-format output

`agenttower queue` (without `--json`) gains one column to its
human-format table:

```text
MESSAGE_ID  ORIGIN  TARGET     STATE     ENQUEUED_AT          ROUTE_ID  EVENT_ID
abc123…     direct  agt_a1b2…  delivered 2026-05-16T21:30Z   -         -
def456…     route   agt_a1b2…  blocked   2026-05-16T21:31Z   1111…     4218
```

When `--origin route` is set, the `ROUTE_ID` and `EVENT_ID`
columns always show values; when `--origin direct` is set, they
always show `-`; when no filter, mixed.

## Error vocabulary additions

| Code | When |
|---|---|
| `queue_origin_invalid` | `--origin` value not in `{direct, route}` |

(Added to the existing FEAT-009 CLI error vocabulary.)
