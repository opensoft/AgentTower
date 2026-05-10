# Phase 1 Data Model: Event Ingestion, Classification, and Follow CLI

**Branch**: `008-event-ingestion-follow` | **Date**: 2026-05-10
**Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)

## 1. Overview

FEAT-008 adds exactly one durable SQLite table (`events`), reuses the
existing FEAT-001 JSONL events history file, introduces three in-
memory state models (reader-cycle state, debounce window, follow
session), and updates `agenttower status` to surface two new degraded-
mode fields. No existing FEAT-001 — FEAT-007 table is altered.

Schema version: `5` → `6`.

## 2. SQLite — `events` table

### 2.1 DDL

```sql
CREATE TABLE events (
    event_id           INTEGER PRIMARY KEY AUTOINCREMENT,

    event_type         TEXT NOT NULL CHECK (event_type IN (
        'activity', 'waiting_for_input', 'completed', 'error',
        'test_failed', 'test_passed', 'manual_review_needed',
        'long_running', 'pane_exited', 'swarm_member_reported'
    )),

    agent_id           TEXT NOT NULL,
    attachment_id      TEXT NOT NULL,
    log_path           TEXT NOT NULL,

    byte_range_start   INTEGER NOT NULL CHECK (byte_range_start >= 0),
    byte_range_end     INTEGER NOT NULL CHECK (byte_range_end >= byte_range_start),
    line_offset_start  INTEGER NOT NULL CHECK (line_offset_start >= 0),
    line_offset_end    INTEGER NOT NULL CHECK (line_offset_end >= line_offset_start),

    observed_at        TEXT NOT NULL,
    record_at          TEXT,

    excerpt            TEXT NOT NULL,
    classifier_rule_id TEXT NOT NULL,

    debounce_window_id          TEXT,
    debounce_collapsed_count    INTEGER NOT NULL DEFAULT 1
                                CHECK (debounce_collapsed_count >= 1),
    debounce_window_started_at  TEXT,
    debounce_window_ended_at    TEXT,

    schema_version     INTEGER NOT NULL DEFAULT 1
                       CHECK (schema_version >= 1),

    jsonl_appended_at  TEXT
);

CREATE INDEX idx_events_agent_eventid
    ON events (agent_id, event_id);

CREATE INDEX idx_events_type_eventid
    ON events (event_type, event_id);

CREATE INDEX idx_events_observedat_eventid
    ON events (observed_at, event_id);

CREATE INDEX idx_events_jsonl_pending
    ON events (event_id) WHERE jsonl_appended_at IS NULL;
```

### 2.2 Column reference

| Column | Type | Nullable | Description |
|---|---|---|---|
| `event_id` | INTEGER PK AUTOINCREMENT | no | Monotonic per daemon process. The CLI cursor encodes this. Locked by Clarifications Q2. |
| `event_type` | TEXT | no | Closed-set of 10 values (FR-008). CHECK enforced. |
| `agent_id` | TEXT | no | FK shape only (no `REFERENCES`); FEAT-006 owns the `agents` table. Indexed via `idx_events_agent_eventid` for `--target` queries. |
| `attachment_id` | TEXT | no | FK shape only; FEAT-007 owns `log_attachments`. Records which attachment generation produced the event. |
| `log_path` | TEXT | no | Denormalized from `log_attachments` for read-side stability across re-attaches. |
| `byte_range_start` | INTEGER | no | Inclusive byte offset of the source record's first byte in the source log file. Drives FR-021 duplicate suppression. |
| `byte_range_end` | INTEGER | no | Exclusive byte offset (i.e., the offset AFTER the trailing `\n`). |
| `line_offset_start` | INTEGER | no | Inclusive line index (0-based) at cycle entry. |
| `line_offset_end` | INTEGER | no | Exclusive line index after this record was consumed. |
| `observed_at` | TEXT | no | ISO-8601 microsecond UTC. Reader clock at classification. Always populated (Clarifications Q3). |
| `record_at` | TEXT | yes | Best-effort source time. Always NULL in MVP (Clarifications Q3). Column exists to keep schema stable for future extension. |
| `excerpt` | TEXT | no | Redacted, capped at `per_event_excerpt_cap_bytes` (default 1024) including the truncation marker. Empty string allowed for synthesized `pane_exited` / `long_running`. |
| `classifier_rule_id` | TEXT | no | Stable rule identifier from `events/classifier_rules.py` (e.g., `error.traceback.v1`) or one of the synthetic ids (`pane_exited.synth.v1`, `long_running.synth.v1`). |
| `debounce_window_id` | TEXT | yes | 12-hex opaque id. NULL for non-collapsible classes. |
| `debounce_collapsed_count` | INTEGER | no | `>= 1`. Always `1` for non-collapsible classes; `>= 1` for `activity`. |
| `debounce_window_started_at` | TEXT | yes | NULL for non-collapsible classes. ISO-8601 microsecond UTC. |
| `debounce_window_ended_at` | TEXT | yes | NULL for non-collapsible classes. Equals `observed_at` for the emitted `activity` event closing its window. |
| `schema_version` | INTEGER | no | Initial value `1`. Bumped only on non-breaking JSONL/SQLite shape additions. |
| `jsonl_appended_at` | TEXT | yes | NULL until the JSONL append succeeds for this row. Internal-only; never surfaced through CLI/JSON output. |

### 2.3 Lifecycle

Inserts: only the reader (production). Tests exercise the DAO's
`insert_event` API directly (no debug CLI flag, no extra test seam).
Deletes: none in MVP (no retention; Clarifications Q4). Updates:
only `jsonl_appended_at` is mutable, and only via the post-JSONL-
success watermark write.

### 2.4 Migration `_migrate_v5_to_v6`

- Idempotent: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT
  EXISTS`.
- Single `BEGIN IMMEDIATE` transaction.
- No data backfill (the events table starts empty).
- Forward-version refusal mirrors FEAT-007: a `v6` daemon refuses to
  open a `v7+` DB.

### 2.5 Indexes — coverage

| Query pattern | Index used |
|---|---|
| `WHERE agent_id = ? ORDER BY event_id [DESC]` | `idx_events_agent_eventid` |
| `WHERE agent_id = ? AND event_type IN (...)` | `idx_events_agent_eventid` (filter at SQLite layer) |
| `WHERE event_type = ? ORDER BY event_id [DESC]` | `idx_events_type_eventid` |
| `WHERE observed_at >= ? AND observed_at < ?` | `idx_events_observedat_eventid` |
| `WHERE jsonl_appended_at IS NULL ORDER BY event_id ASC LIMIT N` | `idx_events_jsonl_pending` (partial) |
| `ORDER BY observed_at, byte_range_start, event_id` | `idx_events_observedat_eventid` (primary) + `byte_range_start` filter on tie |

The default ordering `(observed_at, byte_range_start, event_id)`
(FR-028) is stable: `observed_at` is monotonic per daemon (the
reader's clock advances), and `event_id` breaks any remaining tie.
For pagination, the cursor encodes `event_id` only; the reader
guarantees `event_id` is monotonic with `observed_at` per daemon
process, so cursoring by `event_id` is consistent with the documented
ordering.

## 3. JSONL stable schema

Path: `~/.local/state/opensoft/agenttower/events.jsonl` (existing
FEAT-001 file). One JSON object per line, terminated by `\n`. UTF-8
encoded. The schema is the FR-027 contract:

```json
{
  "ts": "2026-05-10T12:34:56.789012+00:00",
  "event_id": 42,
  "event_type": "activity",
  "agent_id": "agt_a1b2c3d4e5f6",
  "attachment_id": "atc_aabbccddeeff",
  "log_path": "/home/user/.local/state/opensoft/agenttower/logs/<container>/<agent>.log",
  "byte_range_start": 1024,
  "byte_range_end": 1078,
  "line_offset_start": 32,
  "line_offset_end": 33,
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

Notes:

- `ts` is the FEAT-001 `events.writer` timestamp (when the JSONL
  append happened) and is distinct from `observed_at` (when the
  classifier produced the event). They will typically be within
  milliseconds of each other but tests should not assume equality.
- `record_at` is always `null` in MVP (Clarifications Q3) but the
  field is always present to keep the schema stable.
- `debounce` is always present; for non-collapsible classes:
  `{"window_id": null, "collapsed_count": 1, "window_started_at":
  null, "window_ended_at": null}`. (This is a small wart vs.
  "omit when N/A" but keeps the schema rectangular for `jq`.)
- `jsonl_appended_at` is NEVER part of the JSONL output (internal
  watermark only).

The same schema is what `agenttower events --json` produces (FR-032).

### 3.1 Lifecycle separation (FR-026)

The same `events.jsonl` file ALSO carries FEAT-007 lifecycle events
and audit rows. They are distinguishable by `event_type`:

- FEAT-008 durable events: `event_type` ∈ {ten closed-set values}
- FEAT-007 lifecycle events: `event_type` ∈ {`log_rotation_detected`,
  `log_file_missing`, `log_file_returned`,
  `log_attachment_orphan_detected`, `mounts_json_oversized`,
  `socket_peer_uid_mismatch`}
- FEAT-007 audit rows: `event_type = "log_attachment_change"`

No overlap by spec construction. The optional consolidated test
(FR-044) asserts this empirically by reading the JSONL after a
contrived rotation+classify sequence and partitioning by
`event_type`.

## 4. In-memory state — Reader-Cycle State

Per-attachment cycle-local state, discarded at cycle end:

```python
@dataclass
class AttachmentCycleState:
    attachment_id: str
    agent_id: str
    log_path: Path
    pre_cycle_offsets: tuple[int, int, int]   # (byte, line, last_event)
    recovery_result: ReaderCycleResult         # from FEAT-007
    bytes_read_this_cycle: bytes
    classified_records: list[ClassifierOutcome]
    pending_events_to_emit: list[PendingEvent]
    last_output_at: ISOString                  # for long_running
```

`AttachmentCycleState` is constructed at cycle entry per attachment,
populated as the cycle progresses, and discarded after the per-
attachment commit. It is NOT persisted.

## 5. In-memory state — Debounce Window

See `research.md` §R5. One `dict[(attachment_id, event_class),
DebounceWindow]` on the reader's `DebounceManager`.

```python
@dataclass
class DebounceWindow:
    window_id: str           # 12-hex
    started_at: ISOString
    ended_at: ISOString | None
    collapsed_count: int     # >= 1
    latest_excerpt: str
    latest_byte_range: tuple[int, int]
    latest_line_range: tuple[int, int]
    latest_observed_at: ISOString
    latest_classifier_rule_id: str
```

NOT persisted (FR-015). On daemon restart, the dict is empty; the
first qualifying record opens a new window.

## 6. In-memory state — Follow Session

```python
@dataclass
class FollowSession:
    session_id: str          # 12-hex
    target_agent_id: str | None
    type_filter: frozenset[str]   # empty = no filter
    since_iso: ISOString | None
    last_emitted_event_id: int    # 0 = nothing emitted yet
    expires_at_monotonic: float   # time.monotonic() + idle timeout
    condition: threading.Condition
```

Stored in a `dict[session_id, FollowSession]` on the daemon's
`FollowSessionRegistry`. The registry is a singleton owned by
`DaemonContext` and lives for the daemon's lifetime. Sessions are
created by `events.follow_open`, refreshed by `events.follow_next`,
and removed by `events.follow_close` or the cycle-time janitor.

## 7. `agenttower status` extensions

The existing `status` socket method (FEAT-002) returns a JSON object.
FEAT-008 adds two top-level keys:

```json
{
  "...": "existing FEAT-001..007 fields",
  "events_reader": {
    "running": true,
    "last_cycle_started_at": "2026-05-10T12:34:56.789012+00:00",
    "last_cycle_duration_ms": 38,
    "active_attachments": 5,
    "attachments_in_failure": []
  },
  "events_persistence": {
    "degraded_sqlite": null,
    "degraded_jsonl": null
  }
}
```

When SQLite is degraded for one or more attachments:

```json
"events_persistence": {
  "degraded_sqlite": {
    "since": "2026-05-10T12:30:00.000000+00:00",
    "buffered_attachments": [
      {
        "attachment_id": "atc_aabbccddeeff",
        "agent_id": "agt_a1b2c3d4e5f6",
        "buffered_count": 7,
        "last_error_class": "OperationalError"
      }
    ]
  },
  "degraded_jsonl": null
}
```

When JSONL is degraded:

```json
"events_persistence": {
  "degraded_sqlite": null,
  "degraded_jsonl": {
    "since": "2026-05-10T12:30:00.000000+00:00",
    "pending_event_count": 142,
    "last_error_class": "OSError"
  }
}
```

These fields are also set on `attachments_in_failure` for per-
attachment EACCES / ENOENT diagnostic surfaces (FR-038), with shape
`{attachment_id, agent_id, error_class, since}`.

## 8. Closed-set error envelope additions

`socket_api/errors.py` gains five new error codes (added to the
existing closed-set):

| Code | Meaning |
|---|---|
| `agent_not_found` | `--target` agent not in FEAT-006 registry. (FR-035a, US1 AS5.) |
| `events_session_unknown` | `events.follow_next` / `events.follow_close` referenced an unknown `session_id`. |
| `events_session_expired` | `events.follow_next` referenced a session whose idle timeout elapsed. |
| `events_invalid_cursor` | `events.list` `cursor` failed validation. |
| `events_filter_invalid` | `events.list` filter combination is invalid (e.g., `--since` > `--until`, unknown `--type`). |

Each code maps to a CLI exit-code constant (4 for `agent_not_found`,
5 for `events_session_*`, 6 for `events_invalid_cursor`, 7 for
`events_filter_invalid`).

## 9. Configuration surface (`[events]` in `config.toml`)

```toml
[events]
reader_cycle_wallclock_cap_seconds   = 1.0
per_cycle_byte_cap_bytes             = 65536
per_event_excerpt_cap_bytes          = 1024
excerpt_truncation_marker            = "…[truncated]"
debounce_activity_window_seconds     = 5.0
pane_exited_grace_seconds            = 30.0
long_running_grace_seconds           = 30.0
default_page_size                    = 50
max_page_size                        = 50
follow_long_poll_max_seconds         = 30.0
follow_session_idle_timeout_seconds  = 300.0
```

`agenttower config paths` is extended to surface the resolved values
under an `events` heading (FR-045).

## 10. Validation rules summary

| Rule | Source |
|---|---|
| `event_type` ∈ closed-set of 10 | SQLite CHECK + FR-008 |
| `byte_range_start` ≥ 0, `byte_range_end` ≥ `byte_range_start` | SQLite CHECK + FR-005 |
| `excerpt` length ≤ `per_event_excerpt_cap_bytes` | App-layer (truncation) + Edge Cases |
| `excerpt` is redacted | App-layer + FR-012 |
| `debounce_collapsed_count` ≥ 1 | SQLite CHECK + FR-014 |
| Default ordering `(observed_at, byte_range_start, event_id)` | FR-028 |
| `--cursor` round-trips opaquely | App-layer (R8) |
| `--target <unknown>` errors with `agent_not_found` | App-layer + FR-035a |
| Schema version `6` after migration | App-layer + R1 |

## 11. State transitions

The events table is append-only by design; rows have only one
internal transition:

```text
NEW (jsonl_appended_at IS NULL)
  → JSONL append succeeds
COMMITTED (jsonl_appended_at IS NOT NULL)
```

No row ever returns to `NEW`. No row is ever deleted in MVP
(Clarifications Q4).

The reader's per-attachment SQLite-degraded state machine:

```text
HEALTHY  (no buffered events)
   |  on SQLite write error during commit
   v
DEGRADED (events buffered in memory; offsets NOT advanced;
          status surfaces degraded_sqlite)
   |  on next cycle, retry succeeds
   v
HEALTHY
```

The reader's per-cycle JSONL-degraded state machine:

```text
HEALTHY  (no rows with jsonl_appended_at IS NULL)
   |  on JSONL write error after a successful SQLite commit
   v
DEGRADED (rows with jsonl_appended_at IS NULL accumulate;
          status surfaces degraded_jsonl)
   |  on next cycle, retry succeeds
   v
HEALTHY
```

These two state machines are independent: SQLite can be degraded
while JSONL is healthy and vice versa.
