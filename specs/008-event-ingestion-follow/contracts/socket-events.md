# Socket Method Contract: `events.*`

**Branch**: `008-event-ingestion-follow` | **Date**: 2026-05-10
**Plan**: [../plan.md](../plan.md) | **Spec**: [../spec.md](../spec.md)

This contract documents the four new socket methods FEAT-008 adds to
the FEAT-002 daemon socket protocol. Method names follow the
`<package>.<verb>` convention used by FEAT-007 (`logs.*`) and
FEAT-006 (`agents.*`).

All requests use the FEAT-002 envelope:

```json
{ "method": "events.list", "params": { ... } }
```

All responses use:

```json
{ "result": { ... } }     // success
{ "error":  { "code": "<closed-set>", "message": "<string>" } }  // failure
```

Errors use the FEAT-002 `socket_api.errors.py` closed-set codes plus
the five new ones documented in `data-model.md` §8.

---

## C-EVT-001 — `events.list`

### Request

```json
{
  "method": "events.list",
  "params": {
    "target": "agt_a1b2c3d4e5f6",        // optional
    "types":  ["error", "test_failed"],  // optional, repeatable; subset of 10 closed-set values
    "since":  "2026-05-10T12:00:00Z",    // optional, ISO-8601
    "until":  "2026-05-10T13:00:00Z",    // optional, ISO-8601
    "limit":  50,                        // optional, default 50, max 50
    "cursor": "eyJlIjoxNDIsInIiOmZhbHNlfQ", // optional, opaque
    "reverse": false                     // optional, default false
  }
}
```

### Success response

```json
{
  "result": {
    "events": [
      {
        "event_id": 142,
        "event_type": "error",
        "agent_id": "agt_a1b2c3d4e5f6",
        "attachment_id": "atc_aabbccddeeff",
        "log_path": "/home/.../agent.log",
        "byte_range_start": 1024,
        "byte_range_end":   1078,
        "line_offset_start": 32,
        "line_offset_end":   33,
        "observed_at": "2026-05-10T12:34:56.789000+00:00",
        "record_at":   null,
        "excerpt":     "Error: foo",
        "classifier_rule_id": "error.line.v1",
        "debounce": {
          "window_id": null,
          "collapsed_count": 1,
          "window_started_at": null,
          "window_ended_at":   null
        },
        "schema_version": 1
      }
      // ... up to `limit` events ...
    ],
    "next_cursor": "eyJlIjoxOTIsInIiOmZhbHNlfQ"  // null when no more
  }
}
```

### Error responses

| Code | When |
|---|---|
| `agent_not_found` | `target` set AND not in FEAT-006 registry |
| `events_invalid_cursor` | `cursor` decodes to invalid shape |
| `events_filter_invalid` | unknown `type`, `since` > `until`, `limit` out of range |

### Ordering

The default order is `(observed_at ASC, byte_range_start ASC, event_id
ASC)`. `reverse: true` flips all three. Cursor encodes the last
returned `event_id`; the next page starts strictly after (forward) or
strictly before (reverse) it.

### Idempotence

Pure read. No state change. Safe to retry.

---

## C-EVT-002 — `events.follow_open`

### Request

```json
{
  "method": "events.follow_open",
  "params": {
    "target": "agt_a1b2c3d4e5f6",   // optional
    "types":  ["error"],            // optional
    "since":  "2026-05-10T12:00:00Z" // optional, prints bounded backlog before live
  }
}
```

### Success response

```json
{
  "result": {
    "session_id": "fs_b2c3d4e5f6a1",
    "backlog_events": [               // present iff `since` was set
      { /* same shape as events.list events */ }
    ],
    "live_starting_event_id": 192    // exclusive lower bound for the live tail
  }
}
```

### Error responses

| Code | When |
|---|---|
| `agent_not_found` | `target` set AND not in FEAT-006 registry |
| `events_filter_invalid` | unknown `type` |

### Notes

- `session_id` shape is `fs_<12-hex>` (mirrors FEAT-007 `atc_` and
  FEAT-006 `agt_` prefix conventions).
- The `backlog_events` are bounded by the same `default_page_size`
  cap (50). Operators wanting more history use `events.list` with
  `--since`.
- The session is registered server-side with an idle timeout
  (`follow_session_idle_timeout_seconds`, default 300 s).

---

## C-EVT-003 — `events.follow_next`

### Request

```json
{
  "method": "events.follow_next",
  "params": {
    "session_id": "fs_b2c3d4e5f6a1",
    "max_wait_seconds": 30.0   // optional, default 30, capped at server-side max
  }
}
```

### Success response

```json
{
  "result": {
    "events": [
      { /* same shape as events.list events */ }
    ],
    "session_open": true     // false if session expired or closed during wait
  }
}
```

The `events` array is empty if the wait budget elapsed without a
new event matching the session filter; the CLI re-issues the call.

### Error responses

| Code | When |
|---|---|
| `events_session_unknown` | `session_id` not in the registry |
| `events_session_expired` | `session_id` exists but past idle timeout |

### Concurrency

The reader thread, after each successful SQLite commit, calls
`registry.notify_filtered(event)`. `events.follow_next` blocks on a
`threading.Condition` keyed by the session's filter; on notification,
it queries the events table for `event_id > last_emitted_event_id`
matching the filter, returns the result, and updates
`last_emitted_event_id`.

---

## C-EVT-004 — `events.follow_close`

### Request

```json
{
  "method": "events.follow_close",
  "params": { "session_id": "fs_b2c3d4e5f6a1" }
}
```

### Success response

```json
{ "result": {} }
```

### Error responses

| Code | When |
|---|---|
| `events_session_unknown` | `session_id` not in the registry (idempotence: also returned for an already-closed session — clients should ignore this error) |

---

## C-EVT-005 — `events.classifier_rules` (debug-only)

### Request

```json
{ "method": "events.classifier_rules", "params": {} }
```

### Success response

```json
{
  "result": {
    "rules": [
      { "rule_id": "swarm_member.v1",        "event_type": "swarm_member_reported", "priority": 10 },
      { "rule_id": "manual_review.v1",       "event_type": "manual_review_needed",  "priority": 20 },
      { "rule_id": "error.traceback.v1",     "event_type": "error",                 "priority": 30 },
      { "rule_id": "error.line.v1",          "event_type": "error",                 "priority": 31 },
      { "rule_id": "test_failed.pytest.v1",  "event_type": "test_failed",           "priority": 40 },
      { "rule_id": "test_failed.generic.v1", "event_type": "test_failed",           "priority": 41 },
      { "rule_id": "test_passed.pytest.v1",  "event_type": "test_passed",           "priority": 50 },
      { "rule_id": "test_passed.generic.v1", "event_type": "test_passed",           "priority": 51 },
      { "rule_id": "completed.v1",           "event_type": "completed",             "priority": 60 },
      { "rule_id": "waiting_for_input.v1",   "event_type": "waiting_for_input",     "priority": 70 },
      { "rule_id": "activity.fallback.v1",   "event_type": "activity",              "priority": 999 }
    ],
    "synthetic_rule_ids": [
      "pane_exited.synth.v1",
      "long_running.synth.v1"
    ]
  }
}
```

### Notes

- This method is for diagnostic CLI use (`agenttower events
  --classifier-rules`, hidden from `--help`) and tests. It exposes
  only metadata; matchers themselves are not serialized.
- Returning the catalogue verbatim makes FR-008's "rule priority is
  documented and testable" empirically self-evident.

---

## Error envelope additions (closed-set)

| Code | HTTP-equivalent | CLI exit code |
|---|---|---|
| `agent_not_found` | 404 | 4 |
| `events_session_unknown` | 404 | 5 |
| `events_session_expired` | 410 | 5 |
| `events_invalid_cursor` | 400 | 6 |
| `events_filter_invalid` | 400 | 7 |

These are added to `socket_api/errors.py`'s closed-set tuple.

## Authentication / authorization

Same as every other FEAT-002 socket method: peer-uid match against
the daemon's running uid (FEAT-002 SC-006). On mismatch the existing
`socket_peer_uid_mismatch` lifecycle event fires.

## Concurrency invariants

1. The reader thread is the SOLE writer to the `events` table and
   `log_offsets` (FR-004 / FR-006).
2. `events.list` and `events.follow_*` are read-only against
   `events`; SQLite WAL gives them a consistent snapshot per call.
3. The follow registry is guarded by a `threading.Lock`; reader and
   followers contend only on session lookup, not on event reads.
