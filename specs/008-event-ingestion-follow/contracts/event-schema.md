# JSON Schema Contract: Event JSONL / `events --json` Output

**Branch**: `008-event-ingestion-follow` | **Date**: 2026-05-10
**Plan**: [../plan.md](../plan.md) | **Spec**: [../spec.md](../spec.md)

This is the FR-027 / FR-032 stable JSON schema for one event. It
applies to:

- The body of one line in `~/.local/state/opensoft/agenttower/events.jsonl`
  (FEAT-008 durable events only — FEAT-007 lifecycle events use a
  different `event_type` enum and are out of scope here).
- One line of `agenttower events --json` stdout.
- One element of the `events` array in `events.list` /
  `events.follow_open` (`backlog_events`) / `events.follow_next`
  socket responses.

The schema is JSON-Schema 2020-12.

## Schema (full)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://opensoft.one/schemas/agenttower/feat-008/event.json",
  "title": "AgentTower Event (FEAT-008)",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "event_id",
    "event_type",
    "agent_id",
    "attachment_id",
    "log_path",
    "byte_range_start",
    "byte_range_end",
    "line_offset_start",
    "line_offset_end",
    "observed_at",
    "record_at",
    "excerpt",
    "classifier_rule_id",
    "debounce",
    "schema_version"
  ],
  "properties": {
    "ts": {
      "type": "string",
      "format": "date-time",
      "description": "JSONL writer timestamp (FEAT-001). Present only in JSONL output, NOT in events.list / events.follow_* responses."
    },
    "event_id": {
      "type": "integer",
      "minimum": 1,
      "description": "Monotonic per daemon process. SQLite INTEGER PRIMARY KEY AUTOINCREMENT."
    },
    "event_type": {
      "type": "string",
      "enum": [
        "activity",
        "waiting_for_input",
        "completed",
        "error",
        "test_failed",
        "test_passed",
        "manual_review_needed",
        "long_running",
        "pane_exited",
        "swarm_member_reported"
      ]
    },
    "agent_id": {
      "type": "string",
      "pattern": "^agt_[0-9a-f]{12}$"
    },
    "attachment_id": {
      "type": "string",
      "pattern": "^atc_[0-9a-f]{12}$"
    },
    "log_path": {
      "type": "string",
      "minLength": 1
    },
    "byte_range_start": {
      "type": "integer",
      "minimum": 0
    },
    "byte_range_end": {
      "type": "integer",
      "minimum": 0
    },
    "line_offset_start": {
      "type": "integer",
      "minimum": 0
    },
    "line_offset_end": {
      "type": "integer",
      "minimum": 0
    },
    "observed_at": {
      "type": "string",
      "format": "date-time",
      "description": "Reader wall-clock at classification, ISO-8601 microsecond UTC."
    },
    "record_at": {
      "type": ["string", "null"],
      "format": "date-time",
      "description": "Best-effort source time. ALWAYS null in MVP; reserved for future non-breaking schema bump."
    },
    "excerpt": {
      "type": "string",
      "description": "Redacted log excerpt; capped at per_event_excerpt_cap_bytes (default 1024). May be empty for synthesized event types."
    },
    "classifier_rule_id": {
      "type": "string",
      "pattern": "^[a-z][a-z0-9_]*(?:\\.[a-z0-9_]+)?\\.v[0-9]+$"
    },
    "debounce": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "window_id",
        "collapsed_count",
        "window_started_at",
        "window_ended_at"
      ],
      "properties": {
        "window_id":         { "type": ["string", "null"], "pattern": "^[0-9a-f]{12}$" },
        "collapsed_count":   { "type": "integer", "minimum": 1 },
        "window_started_at": { "type": ["string", "null"], "format": "date-time" },
        "window_ended_at":   { "type": ["string", "null"], "format": "date-time" }
      }
    },
    "schema_version": {
      "type": "integer",
      "minimum": 1
    }
  }
}
```

## Field stability rules

- The set of required fields is FIXED at `schema_version: 1`.
- Adding a new optional field is a non-breaking change behind a
  `schema_version` bump (FR-027); consumers reading older events
  see the field absent.
- Renaming, removing, or re-typing a field is BREAKING and requires
  a major-version bump beyond MVP.
- The `event_type` enum is closed in MVP. Adding a new event type
  is a feature-level decision (FR-007) and would bump
  `schema_version`.

## Examples

### `activity` with debounce

```json
{
  "ts": "2026-05-10T12:34:56.789012+00:00",
  "event_id": 142,
  "event_type": "activity",
  "agent_id": "agt_a1b2c3d4e5f6",
  "attachment_id": "atc_aabbccddeeff",
  "log_path": "/home/u/.local/state/opensoft/agenttower/logs/abc.../agt_a1b2c3d4e5f6.log",
  "byte_range_start": 8192,
  "byte_range_end": 8260,
  "line_offset_start": 128,
  "line_offset_end": 129,
  "observed_at": "2026-05-10T12:34:56.789000+00:00",
  "record_at": null,
  "excerpt": "running pytest tests/unit/test_foo.py …",
  "classifier_rule_id": "activity.fallback.v1",
  "debounce": {
    "window_id": "0a1b2c3d4e5f",
    "collapsed_count": 4,
    "window_started_at": "2026-05-10T12:34:53.000000+00:00",
    "window_ended_at":   "2026-05-10T12:34:56.789000+00:00"
  },
  "schema_version": 1
}
```

### `error` (one-to-one, no debounce window)

```json
{
  "event_id": 143,
  "event_type": "error",
  "agent_id": "agt_a1b2c3d4e5f6",
  "attachment_id": "atc_aabbccddeeff",
  "log_path": "/home/.../agt_a1b2c3d4e5f6.log",
  "byte_range_start": 8260,
  "byte_range_end": 8294,
  "line_offset_start": 129,
  "line_offset_end": 130,
  "observed_at": "2026-05-10T12:34:57.001000+00:00",
  "record_at": null,
  "excerpt": "Error: division by zero",
  "classifier_rule_id": "error.line.v1",
  "debounce": {
    "window_id": null,
    "collapsed_count": 1,
    "window_started_at": null,
    "window_ended_at": null
  },
  "schema_version": 1
}
```

### `swarm_member_reported`

```json
{
  "event_id": 144,
  "event_type": "swarm_member_reported",
  "agent_id": "agt_a1b2c3d4e5f6",
  "attachment_id": "atc_aabbccddeeff",
  "log_path": "/home/.../agt_a1b2c3d4e5f6.log",
  "byte_range_start": 8294,
  "byte_range_end": 8412,
  "line_offset_start": 130,
  "line_offset_end": 131,
  "observed_at": "2026-05-10T12:34:57.250000+00:00",
  "record_at": null,
  "excerpt": "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%17 label=worker-2 capability=test purpose=run-tests",
  "classifier_rule_id": "swarm_member.v1",
  "debounce": {
    "window_id": null,
    "collapsed_count": 1,
    "window_started_at": null,
    "window_ended_at": null
  },
  "schema_version": 1
}
```

### `pane_exited` (synthesized)

```json
{
  "event_id": 145,
  "event_type": "pane_exited",
  "agent_id": "agt_a1b2c3d4e5f6",
  "attachment_id": "atc_aabbccddeeff",
  "log_path": "/home/.../agt_a1b2c3d4e5f6.log",
  "byte_range_start": 9000,
  "byte_range_end": 9000,
  "line_offset_start": 200,
  "line_offset_end": 200,
  "observed_at": "2026-05-10T12:35:30.000000+00:00",
  "record_at": null,
  "excerpt": "",
  "classifier_rule_id": "pane_exited.synth.v1",
  "debounce": {
    "window_id": null,
    "collapsed_count": 1,
    "window_started_at": null,
    "window_ended_at": null
  },
  "schema_version": 1
}
```

## Negative validation tests

Cases that MUST FAIL schema validation (covered by
`tests/unit/test_event_schema_negative.py`):

- `event_type` not in the closed-set enum.
- `event_id` ≤ 0 or non-integer.
- `agent_id` not matching `agt_[0-9a-f]{12}`.
- `record_at` is a string but not ISO-8601 (in MVP this should
  always be null).
- `debounce` missing one of the four required keys.
- `debounce.collapsed_count` < 1.
- Top-level fields beyond the documented set.
- `classifier_rule_id` not matching the documented `^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)?\.v[0-9]+$` pattern (accepts both 2-segment forms like `swarm_member.v1` and 3-segment forms like `error.traceback.v1`; the catalogue uses both).

## Schema artifact path

The JSON Schema above is also committed (verbatim) at
`tests/integration/schemas/event-v1.schema.json` and consumed by
`tests/integration/test_events_us5_json.py` and
`test_lifecycle_separation.py` for SC-011 coverage.
