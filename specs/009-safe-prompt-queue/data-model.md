# Data Model: Safe Prompt Queue and Input Delivery

**Branch**: `009-safe-prompt-queue` | **Date**: 2026-05-11
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)

## 1. Overview

FEAT-009 introduces two new SQLite tables in migration v6 → v7:

- **`message_queue`** — one row per `send-input` invocation, holding
  envelope identity, body bytes, lifecycle state, closed-set reason
  fields, transition timestamps, and operator metadata.
- **`daemon_state`** — one-row-per-key/value table carrying the
  routing kill switch flag (the only key for MVP).

No existing FEAT-001..008 table is touched. JSONL audit lands in the
existing FEAT-008 `events.jsonl` stream using seven new
`queue_message_*` `event_type` values (R-008 disjointness test).

`CURRENT_SCHEMA_VERSION` advances from `6` (FEAT-008) to `7`
(FEAT-009). The migration is idempotent on re-open via `IF NOT
EXISTS`, runs under a single `BEGIN IMMEDIATE` transaction inside
`state.schema._apply_pending_migrations`, and refuses to serve the
daemon if rollback is required (mirrors FEAT-007 / FEAT-008).

## 2. SQLite schema (migration v6 → v7)

```sql
-- ────────────────────────────────────────────────────────────────────────────
-- message_queue: durable record of one send-input lifecycle.
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS message_queue (
    message_id                   TEXT PRIMARY KEY,              -- UUIDv4 string, FR-001
    state                        TEXT NOT NULL CHECK (state IN (
        'queued', 'blocked', 'delivered', 'canceled', 'failed'
    )),                                                          -- FR-013
    block_reason                 TEXT CHECK (
        block_reason IS NULL OR block_reason IN (
            'sender_role_not_permitted',
            'target_role_not_permitted',
            'target_not_active',
            'target_pane_missing',
            'target_container_inactive',
            'kill_switch_off',
            'operator_delayed'
        )
    ),                                                           -- FR-017
    failure_reason               TEXT CHECK (
        failure_reason IS NULL OR failure_reason IN (
            'attempt_interrupted',
            'tmux_paste_failed',
            'docker_exec_failed',
            'tmux_send_keys_failed',
            'pane_disappeared_mid_attempt'
        )
    ),                                                           -- FR-018

    -- Sender identity captured at enqueue and frozen for the row's lifetime.
    sender_agent_id              TEXT NOT NULL,
    sender_label                 TEXT NOT NULL,
    sender_role                  TEXT NOT NULL,
    sender_capability            TEXT,

    -- Target identity captured at enqueue; the target_* fields below are the
    -- audit/listing source of truth even if the agent is later deregistered.
    target_agent_id              TEXT NOT NULL,
    target_label                 TEXT NOT NULL,
    target_role                  TEXT NOT NULL,
    target_capability            TEXT,
    target_container_id          TEXT NOT NULL,
    target_pane_id               TEXT NOT NULL,                  -- pane composite key, FEAT-004

    -- Body and integrity.
    envelope_body                BLOB NOT NULL,                  -- raw bytes, FR-012a / R-002
    envelope_body_sha256         TEXT NOT NULL,                  -- hex over raw bytes
    envelope_size_bytes          INTEGER NOT NULL,               -- serialized envelope incl. headers, FR-004

    -- Lifecycle timestamps (canonical ISO-8601 ms UTC, FR-012b / Q5).
    enqueued_at                  TEXT NOT NULL,
    delivery_attempt_started_at  TEXT,
    delivered_at                 TEXT,
    failed_at                    TEXT,
    canceled_at                  TEXT,
    last_updated_at              TEXT NOT NULL,

    -- Operator override metadata.
    operator_action              TEXT CHECK (operator_action IS NULL OR operator_action IN (
        'approved', 'delayed', 'canceled'
    )),                                                          -- FR-012
    operator_action_at           TEXT,
    operator_action_by           TEXT,                           -- agent_id or 'host-operator' sentinel

    -- Reason-state coherence invariants (FR-017, FR-018 nullness).
    CHECK (block_reason IS NULL OR state = 'blocked'),
    CHECK (failure_reason IS NULL OR state = 'failed'),

    -- Operator-metadata coherence (FR-012 nullness).
    CHECK (
        (operator_action IS NULL AND operator_action_at IS NULL AND operator_action_by IS NULL)
        OR
        (operator_action IS NOT NULL AND operator_action_at IS NOT NULL AND operator_action_by IS NOT NULL)
    ),

    -- Per-state stamp invariants (terminal stamp matches state).
    CHECK (state != 'delivered' OR delivered_at IS NOT NULL),
    CHECK (state != 'failed'    OR failed_at    IS NOT NULL),
    CHECK (state != 'canceled'  OR canceled_at  IS NOT NULL)
);

-- Indexes. The names follow the FEAT-008 naming convention
-- (`idx_<table>_<columns>`).

-- Hot path: queue listing ordered by enqueued_at, filtered by state.
CREATE INDEX IF NOT EXISTS idx_message_queue_state_enqueued
    ON message_queue (state, enqueued_at, message_id);

-- Filter: --target listings, plus per-target FIFO scan.
CREATE INDEX IF NOT EXISTS idx_message_queue_target_enqueued
    ON message_queue (target_agent_id, enqueued_at, message_id);

-- Filter: --sender listings.
CREATE INDEX IF NOT EXISTS idx_message_queue_sender_enqueued
    ON message_queue (sender_agent_id, enqueued_at, message_id);

-- Recovery path (FR-040): partial index over rows that may be in-flight.
CREATE INDEX IF NOT EXISTS idx_message_queue_in_flight
    ON message_queue (target_agent_id)
    WHERE delivery_attempt_started_at IS NOT NULL
      AND delivered_at IS NULL
      AND failed_at   IS NULL
      AND canceled_at IS NULL;

-- ────────────────────────────────────────────────────────────────────────────
-- daemon_state: one-row-per-key/value table (R-003).
-- ────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daemon_state (
    key             TEXT PRIMARY KEY CHECK (key IN ('routing_enabled')),
    value           TEXT NOT NULL,                               -- 'enabled' | 'disabled' for routing
    last_updated_at TEXT NOT NULL,                               -- ISO-8601 ms UTC
    last_updated_by TEXT NOT NULL,                               -- agent_id or 'host-operator' sentinel
    CHECK (
        (key = 'routing_enabled' AND value IN ('enabled', 'disabled'))
    )
);

-- Seed row: routing enabled by default on a fresh state directory (FR-026).
-- Insertion happens during the migration via an explicit INSERT OR IGNORE
-- once the migration confirms there is no existing row (re-running the
-- migration on a v7 DB is a no-op because the seed already exists).
-- `last_updated_by` uses the literal sentinel `'(daemon-init)'` to record
-- that this is the migration-created default state, not an operator-driven
-- toggle. The sentinel cannot collide with any registered agent_id
-- (regex `^agt_[0-9a-f]{12}$`) and is distinct from `'host-operator'`
-- which is reserved for actual host-side operator actions.

-- ────────────────────────────────────────────────────────────────────────────
-- FEAT-008 `events` table rebuild (part 2 of the v6 → v7 migration).
-- ────────────────────────────────────────────────────────────────────────────
-- FR-046 requires queue audit rows to be inserted into the FEAT-008 `events`
-- table alongside classifier events (dual-write). To accept the FEAT-009 row
-- shape, the existing `events` table must (a) widen its `event_type` CHECK
-- constraint to include the eight FEAT-009 audit types and (b) make the
-- FEAT-008-specific NOT NULL columns NULLABLE so queue rows can omit them.
-- SQLite cannot ALTER CHECK or column NULL-ability in place, so the
-- standard rebuild pattern is used. The rebuild runs inside the same
-- BEGIN IMMEDIATE transaction as the additive tables above; if any step
-- fails the entire v6 → v7 migration rolls back.

CREATE TABLE events_new (
    event_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type         TEXT NOT NULL CHECK (event_type IN (
        -- FEAT-008 durable classifier types (10)
        'activity', 'waiting_for_input', 'completed', 'error',
        'test_failed', 'test_passed', 'manual_review_needed',
        'long_running', 'pane_exited', 'swarm_member_reported',
        -- FEAT-009 audit types (8)
        'queue_message_enqueued', 'queue_message_delivered',
        'queue_message_blocked', 'queue_message_failed',
        'queue_message_canceled', 'queue_message_approved',
        'queue_message_delayed', 'routing_toggled'
    )),
    agent_id           TEXT NOT NULL,
    attachment_id      TEXT,                                     -- was NOT NULL; nullable for FEAT-009 rows
    log_path           TEXT,                                     -- was NOT NULL; nullable for FEAT-009 rows
    byte_range_start   INTEGER,                                  -- was NOT NULL; nullable for FEAT-009 rows
    byte_range_end     INTEGER,                                  -- was NOT NULL; nullable for FEAT-009 rows
    line_offset_start  INTEGER,                                  -- was NOT NULL; nullable for FEAT-009 rows
    line_offset_end    INTEGER,                                  -- was NOT NULL; nullable for FEAT-009 rows
    observed_at        TEXT NOT NULL,
    record_at          TEXT CHECK (record_at IS NULL),           -- FEAT-008 invariant preserved
    excerpt            TEXT NOT NULL,
    classifier_rule_id TEXT,                                     -- was NOT NULL; nullable for FEAT-009 rows
    debounce_window_id          TEXT,
    debounce_collapsed_count    INTEGER NOT NULL DEFAULT 1,
    debounce_window_started_at  TEXT,
    debounce_window_ended_at    TEXT,
    schema_version     INTEGER NOT NULL DEFAULT 1,
    jsonl_appended_at  TEXT                                       -- watermark; set after JSONL append succeeds for either FEAT-008 or FEAT-009 rows
);

INSERT INTO events_new SELECT * FROM events;
DROP TABLE events;
ALTER TABLE events_new RENAME TO events;

-- Recreate the four FEAT-008 indexes (DROP TABLE drops them).
CREATE INDEX idx_events_agent_eventid
    ON events (agent_id, event_id);
CREATE INDEX idx_events_type_eventid
    ON events (event_type, event_id);
CREATE INDEX idx_events_observedat_eventid
    ON events (observed_at, event_id);
CREATE INDEX idx_events_jsonl_pending
    ON events (event_id) WHERE jsonl_appended_at IS NULL;
```

## 3. State machine

The five valid `state` values and their allowed transitions
(FR-013 – FR-015). Every other transition MUST be refused with
`terminal_state_cannot_change` or the matching closed-set code.

```text
                 ┌──────────────────────────────────────────────┐
                 │                                              │
                 │   enqueue                          delivery  │
  send-input ────┼──▶ queued ────────────────────────▶ delivered (terminal)
                 │      │                                       │
                 │      │ delivery-time re-check fails          │
                 │      │  OR operator delay                    │
                 │      ▼                                       │
                 │   blocked ──────operator approve──▶ queued   │
                 │      │                                       │
                 │      ├─────────operator cancel───▶ canceled (terminal)
                 │      │                                       │
                 │      └─delivery worker tmux/docker error─┐   │
                 │                                          ▼   │
                 │                                       failed (terminal)
                 │                                              │
                 └──────────────────────────────────────────────┘

                 enqueue-time blocked (FR-020) lands directly in `blocked`
                 with the FR-019 precedence's first failing reason.
```

### 3.1 Allowed transitions

| From      | To         | Trigger                                             | Stamp(s) advanced                    |
|-----------|-----------|----------------------------------------------------|--------------------------------------|
| (insert)  | queued    | `send-input`, all FR-019 checks pass at enqueue     | `enqueued_at`, `last_updated_at`     |
| (insert)  | blocked   | `send-input`, any FR-019 check fails at enqueue     | `enqueued_at`, `last_updated_at`     |
| queued    | delivered | Delivery worker after successful tmux paste+submit  | `delivery_attempt_started_at`, `delivered_at`, `last_updated_at` |
| queued    | failed    | Delivery worker after tmux/docker error             | `delivery_attempt_started_at`, `failed_at`, `last_updated_at` |
| queued    | blocked   | Delivery worker pre-paste re-check fails (FR-025)   | `last_updated_at`                    |
| queued    | blocked   | Operator `queue delay`                              | `last_updated_at`, operator_*        |
| queued    | canceled  | Operator `queue cancel`                             | `canceled_at`, `last_updated_at`, operator_* |
| blocked   | queued    | Operator `queue approve` (block_reason resolvable)  | `last_updated_at`, operator_*        |
| blocked   | canceled  | Operator `queue cancel`                             | `canceled_at`, `last_updated_at`, operator_* |
| (in-flight) | failed | Crash recovery (FR-040) — `delivery_attempt_started_at` set, terminal stamps unset, at daemon startup | `failed_at`, `last_updated_at` |

### 3.2 Terminal states

`delivered`, `failed`, `canceled` are terminal (FR-014). Any
transition originating from a terminal state MUST exit non-zero
with closed-set `terminal_state_cannot_change` and MUST NOT mutate
any column.

### 3.3 Operator-resolvable block reasons (FR-033)

| `block_reason`               | Operator `approve` allowed? |
|------------------------------|------------------------------|
| `operator_delayed`            | Yes                          |
| `kill_switch_off`             | Yes if switch is *currently* enabled; otherwise `approval_not_applicable` |
| `target_not_active`           | Yes                          |
| `target_pane_missing`         | Yes                          |
| `target_container_inactive`   | Yes                          |
| `sender_role_not_permitted`   | No → `approval_not_applicable` |
| `target_role_not_permitted`   | No → `approval_not_applicable` |

A successful `approve` flips the row back to `queued`; the delivery
worker re-evaluates at attempt time and may re-block with a fresh
reason (operator sees this in the next listing).

### 3.4 FR-019 enqueue-time precedence

Order of evaluation (first failure determines `block_reason`):

1. Routing flag is `enabled` → otherwise `kill_switch_off`.
2. Sender has a permitted role (`master`) AND is currently active
   → otherwise `sender_role_not_permitted`.
3. Target is registered AND active → otherwise `target_not_active`
   (or `agent_not_found` *outside* the queue row — the row is
   never created in that case; the CLI surfaces the closed-set
   code and exits non-zero).
4. Target has a permitted role (`slave` or `swarm`) → otherwise
   `target_role_not_permitted`.
5. Target's container is in the daemon's active container set →
   otherwise `target_container_inactive`.
6. Target's pane is resolvable via FEAT-004 → otherwise
   `target_pane_missing`.

## 4. Closed-set vocabularies

### 4.1 `state`

```text
queued | blocked | delivered | canceled | failed
```

### 4.2 `block_reason` (FR-017)

```text
sender_role_not_permitted
target_role_not_permitted
target_not_active
target_pane_missing
target_container_inactive
kill_switch_off
operator_delayed
```

### 4.3 `failure_reason` (FR-018)

```text
attempt_interrupted
tmux_paste_failed
docker_exec_failed
tmux_send_keys_failed
pane_disappeared_mid_attempt
sqlite_lock_conflict
```

### 4.4 `operator_action` (FR-012)

```text
approved | delayed | canceled
```

### 4.5 `event_type` (JSONL audit, FR-046)

```text
queue_message_enqueued
queue_message_delivered
queue_message_blocked
queue_message_failed
queue_message_canceled
queue_message_approved
queue_message_delayed
```

The R-008 disjointness test asserts zero overlap with the FEAT-007
lifecycle event types and the FEAT-008 ten durable types.

## 5. Identity capture

Identity fields are captured at enqueue and frozen for the row's
lifetime (FR-012, Edge Cases "queue row references a hard-deleted
agent"). This is the audit/listing source of truth — the live
FEAT-006 registry is consulted only for re-check eligibility, not
for display.

| Column                  | Source                                                | Mutability                |
|-------------------------|-------------------------------------------------------|---------------------------|
| `sender_agent_id`       | FEAT-005 caller-pane → FEAT-006 agent record          | Frozen at enqueue         |
| `sender_label`          | FEAT-006 agent record                                 | Frozen at enqueue         |
| `sender_role`           | FEAT-006 agent record                                 | Frozen at enqueue         |
| `sender_capability`     | FEAT-006 agent record                                 | Frozen at enqueue         |
| `target_agent_id`       | `routing.target_resolver` (R-001)                     | Frozen at enqueue         |
| `target_label`          | FEAT-006 agent record at resolve time                 | Frozen at enqueue         |
| `target_role`           | FEAT-006 agent record at resolve time                 | Frozen at enqueue         |
| `target_capability`     | FEAT-006 agent record at resolve time                 | Frozen at enqueue         |
| `target_container_id`   | FEAT-006 agent record at resolve time                 | Frozen at enqueue         |
| `target_pane_id`        | FEAT-006 agent record at resolve time                 | Frozen at enqueue         |
| `operator_action_by`    | FEAT-005 caller-pane → agent_id, OR `HOST_OPERATOR_SENTINEL` | Set on each operator action; latest wins |

The `host-operator` sentinel (R-004) is used in:

- `operator_action_by` for host-side `queue approve|delay|cancel`.
- `daemon_state.last_updated_by` for host-side `routing enable|disable`.
- JSONL audit `operator` field for host-originated transitions.

## 6. Envelope rendering (FR-001, FR-002)

```text
Message-Id: 12345678-1234-1234-1234-123456789012
From: agt_abc123def456 "queen" master [capability=plan]
To: agt_aaa111bbb222 "worker-1" slave [capability=implement]
Type: prompt
Priority: normal
Requires-Reply: yes

do thing
```

- Header section is ASCII-safe (labels and capabilities are
  FEAT-006-validated as ASCII-printable).
- Separator is exactly `\n\n` (one blank line).
- Body is appended verbatim, including `\n` and `\t`.
- `Priority: normal` and `Requires-Reply: yes` are literals in MVP
  (FR-001); future per-row priority is out of scope.
- Capability is omitted from the header bracket if the agent's
  `capability` is `NULL` (renders as `From: <id> "<label>" <role>`).

### 6.1 Size cap

`envelope_size_bytes = len(rendered_envelope_utf8_bytes)`. The
FR-004 cap is enforced against this number BEFORE any SQLite write.
Default 65 536 bytes; configurable via `[routing]` in `config.toml`.

### 6.2 Excerpt pipeline (FR-047b, Q3)

```python
def render_excerpt(body_bytes: bytes, redactor) -> str:
    raw   = body_bytes.decode("utf-8")
    redacted = redactor.redact_one_line(raw)
    one_line = re.sub(r"\s+", " ", redacted)
    if len(one_line) <= 240:
        return one_line
    return one_line[:240] + "…"
```

- Step 1: redact via FEAT-007 `logs.redaction.redact_one_line`.
- Step 2: collapse every run of whitespace (`\s+` matches `\n`,
  `\t`, `\r`, space, plus other Unicode whitespace) to one ASCII
  space.
- Step 3: truncate to 240 chars (the configurable cap).
- Step 4: append U+2026 `…` only if truncation occurred.

Pipeline is pure — same input always produces the same output.

## 7. JSONL audit schema (FR-046)

One entry per state transition, appended to the existing FEAT-008
`events.jsonl` stream after the SQLite state-transition commit.

```jsonc
{
  "schema_version": 1,                                    // FEAT-009 audit schema
  "event_type": "queue_message_delivered",                // closed set §4.5
  "message_id": "12345678-1234-1234-1234-123456789012",
  "from_state": "queued",
  "to_state": "delivered",
  "reason": null,                                         // block_reason or failure_reason when relevant
  "operator": null,                                       // null for worker-driven; agent_id or HOST_OPERATOR_SENTINEL for operator-driven
  "observed_at": "2026-05-11T15:32:04.123Z",              // canonical ms UTC, FR-012b
  "sender": {
    "agent_id": "agt_abc123def456",
    "label": "queen",
    "role": "master",
    "capability": "plan"
  },
  "target": {
    "agent_id": "agt_aaa111bbb222",
    "label": "worker-1",
    "role": "slave",
    "capability": "implement"
  },
  "excerpt": "do thing"                                   // redacted, ≤ 240, single-line
}
```

Fields are stable across MVP minor revisions; new fields may be
added (additive-only), existing fields may not change shape
(FEAT-008 audit-format contract).

### 7.1 FEAT-008 `events` table column mapping for FEAT-009 audit rows

FR-046 requires every audit transition to ALSO insert one row into
the (rebuilt) FEAT-008 `events` SQLite table so `agenttower events`
surfaces queue activity in one chronology with classifier events
(per Clarifications Q1 of 2026-05-12). The mapping below is
authoritative; T034 implements it verbatim.

#### 7.1.1 `queue_message_*` events

| FEAT-008 column        | Value for FEAT-009 queue audit                                                    |
|------------------------|-----------------------------------------------------------------------------------|
| `event_id`             | `INTEGER PRIMARY KEY AUTOINCREMENT` — auto-assigned                               |
| `event_type`           | `queue_message_enqueued` / `_delivered` / `_blocked` / `_failed` / `_canceled` / `_approved` / `_delayed` |
| `agent_id`             | `target_agent_id` from the queue row (so `events --target <agent>` shows queue events delivered to that agent) |
| `attachment_id`        | `NULL`                                                                            |
| `log_path`             | `NULL`                                                                            |
| `byte_range_start`     | `NULL`                                                                            |
| `byte_range_end`       | `NULL`                                                                            |
| `line_offset_start`    | `NULL`                                                                            |
| `line_offset_end`      | `NULL`                                                                            |
| `observed_at`          | Transition timestamp (canonical ISO-8601 ms UTC per FR-012b)                      |
| `record_at`            | `NULL` (per FEAT-008 invariant)                                                   |
| `excerpt`              | The same redacted/collapsed/truncated excerpt as the JSONL `excerpt` field        |
| `classifier_rule_id`   | `NULL` (no classifier rule fired)                                                 |
| `debounce_window_id`   | `NULL`                                                                            |
| `debounce_collapsed_count` | `1` (default; queue events do not collapse)                                  |
| `debounce_window_started_at` | `NULL`                                                                      |
| `debounce_window_ended_at`   | `NULL`                                                                      |
| `schema_version`       | `1`                                                                               |
| `jsonl_appended_at`    | `NULL` initially; back-filled after the JSONL append step of the dual-write succeeds (mirrors FEAT-008 FR-029 watermark pattern) |

#### 7.1.2 `routing_toggled` events

| FEAT-008 column        | Value for FEAT-009 routing toggle audit                                           |
|------------------------|-----------------------------------------------------------------------------------|
| `event_id`             | `INTEGER PRIMARY KEY AUTOINCREMENT` — auto-assigned                               |
| `event_type`           | `routing_toggled`                                                                  |
| `agent_id`             | The operator identity (`host-operator` since routing toggles are host-only per FR-027) |
| `attachment_id`        | `NULL`                                                                            |
| `log_path`             | `NULL`                                                                            |
| `byte_range_*`, `line_offset_*` | `NULL`                                                                   |
| `observed_at`          | Toggle timestamp (canonical ISO-8601 ms UTC)                                      |
| `record_at`            | `NULL`                                                                            |
| `excerpt`              | Human-readable summary, e.g., `"routing disabled (was enabled)"` — single-line, ≤ 240 chars, satisfies FEAT-008's NOT NULL excerpt constraint without leaking sensitive data |
| `classifier_rule_id`   | `NULL`                                                                            |
| `debounce_*`           | `NULL` / `1` / `NULL` / `NULL`                                                    |
| `schema_version`       | `1`                                                                               |
| `jsonl_appended_at`    | `NULL` initially; back-filled after the JSONL append step succeeds                |

The `excerpt` choice for `routing_toggled` is the literal string
`"routing <new-value> (was <previous-value>)"` — short, human-
parseable, and contains no body content. This keeps FEAT-008's
NOT NULL `excerpt` invariant satisfied without inventing a new
schema branch.

### 7.2 Source-of-truth precedence (clarifies FR-048)

When the dual-write succeeds: both writes land. When the dual-
write partially fails:

| Failure mode                            | SQLite row | JSONL line | `agenttower status`                | Recovery                                       |
|-----------------------------------------|------------|------------|------------------------------------|------------------------------------------------|
| SQLite INSERT fails                     | absent     | not attempted | the state-transition exception bubbles up to the caller | The caller (delivery worker or queue service) rolls back the state transition; row stays in its prior state |
| SQLite succeeds, JSONL fails            | present    | absent     | `degraded_queue_audit_persistence=true`, error message captured | JSONL record buffered; drained on next worker cycle; `jsonl_appended_at` back-filled after drain succeeds |
| Both succeed                            | present    | present    | clean                              | n/a                                            |

SQLite is the authority. JSONL is a best-effort replica with a
watermark. This mirrors FEAT-008's existing FR-029 / FR-040
patterns.

## 8. Closed-set socket error codes (new)

Added to `src/agenttower/socket_api/errors.py` (FEAT-009 block,
alphabetical):

```text
approval_not_applicable
body_empty
body_invalid_chars
body_invalid_encoding
body_too_large
daemon_shutting_down
delay_not_applicable
delivery_in_progress
delivery_wait_timeout
kill_switch_off
routing_disabled
routing_toggle_host_only
message_id_not_found
operator_pane_inactive
sender_not_in_pane
sender_role_not_permitted
since_invalid_format
target_container_inactive
target_label_ambiguous
target_not_active
target_pane_missing
target_role_not_permitted
terminal_state_cannot_change
```

Each code is `Final[str]` and is also added to the existing
`CLOSED_CODE_SET` frozen-set. Eleven codes are first-introduced
by FEAT-009 (note: `message_id_not_found` replaces the earlier
draft's `target_not_found`); `agent_not_found` is reused
verbatim from FEAT-006/008 for `--target` lookup failures so the
"named agent does not exist" failure mode stays consistent across
features (per Clarifications 2026-05-12).

(The full count from FR-049 is 19 spec-side codes; the table above
includes `routing_toggle_host_only` and `since_invalid_format` —
the two codes added by the second Clarifications session — plus
`routing_disabled`, which the spec names as a separate code from
`kill_switch_off`. `routing_disabled` is the *CLI* error code; the
*row-state* reason is `kill_switch_off`. The plan keeps them
distinct.)

## 9. In-memory state (transient)

The daemon carries the following non-durable state (rebuilt at
boot from SQLite):

- **`RoutingFlagService`** — caches the current `routing_enabled`
  value with a write-through pattern (every toggle writes
  `daemon_state` first, then updates the cache). Reads avoid
  SQLite on the hot delivery path.
- **`DeliveryWorker._pending_audit`** — bounded deque of buffered
  JSONL audit records when the `events.jsonl` write is degraded
  (FR-048, mirrors FEAT-008's `_pending`). Capped at
  `degraded_audit_buffer_max_rows` (default 1024); oldest entries
  are dropped and `agenttower status` surfaces the alarm.
- **`QueueService._wait_observers`** — per-`message_id` `Condition`
  registry used by `send-input` (without `--no-wait`) to block
  until the row reaches a terminal state or the wait timeout
  elapses. Created on demand, removed on terminal transition.

None of the transient state persists across restart; the
`message_queue` SQLite table is the only source of truth for state
recovery (FR-016, Q1).

## 10. Backwards compatibility

- The migration is forward-only; opening a v7 DB with a v6 binary
  surfaces `schema_version_newer` (existing FEAT-006 closed-set
  code).
- All existing FEAT-001..008 SQLite tables are untouched.
- The `events.jsonl` schema gains the `queue_message_*` event types
  but no existing FEAT-007 / FEAT-008 type is renamed or removed.
- The `socket_api/errors.py` closed-code-set is additive; every
  pre-FEAT-009 code remains.
- The tmux adapter Protocol gains four new methods (additive).
  Existing FEAT-004 callers do not need to be updated.
- The CLI gains three new subcommand groups; no existing subcommand
  is renamed or modified.

The `test_feat009_backcompat.py` integration test asserts every
FEAT-001..008 CLI command produces byte-identical stdout, stderr,
exit codes, and `--json` shapes.
