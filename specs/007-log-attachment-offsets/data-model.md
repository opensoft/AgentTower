# Data Model: Pane Log Attachment and Offset Tracking

**Branch**: `007-log-attachment-offsets` | **Date**: 2026-05-08

This document defines the SQLite schema, JSONL audit shape, lifecycle
event shapes, validation rules, and test-seam JSON shape introduced
by FEAT-007. It supplements `spec.md` § Key Entities, FR-014–FR-017,
FR-038, FR-039, FR-044–FR-046.

---

## 1. SQLite migration: `v4 → v5`

`CURRENT_SCHEMA_VERSION` advances from `4` (FEAT-006) to `5`
(FEAT-007). The migration creates two new tables and four indexes;
no existing table is touched.

### 1.1 Table `log_attachments`

```sql
CREATE TABLE IF NOT EXISTS log_attachments (
    attachment_id              TEXT PRIMARY KEY,
    agent_id                   TEXT NOT NULL,
    container_id               TEXT NOT NULL,
    tmux_socket_path           TEXT NOT NULL,
    tmux_session_name          TEXT NOT NULL,
    tmux_window_index          INTEGER NOT NULL,
    tmux_pane_index            INTEGER NOT NULL,
    tmux_pane_id               TEXT NOT NULL,
    log_path                   TEXT NOT NULL,
    status                     TEXT NOT NULL CHECK(status IN ('active','superseded','stale','detached')),
    source                     TEXT NOT NULL CHECK(source IN ('explicit','register_self')),
    pipe_pane_command          TEXT NOT NULL,
    attached_at                TEXT NOT NULL,
    last_status_at             TEXT NOT NULL,
    superseded_at              TEXT,
    superseded_by              TEXT,
    created_at                 TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE RESTRICT,
    FOREIGN KEY (superseded_by) REFERENCES log_attachments(attachment_id) ON DELETE RESTRICT
);
```

**Indexes**:

```sql
CREATE INDEX IF NOT EXISTS log_attachments_agent_status
    ON log_attachments(agent_id, status, last_status_at DESC);

CREATE INDEX IF NOT EXISTS log_attachments_pane_status
    ON log_attachments(container_id, tmux_socket_path, tmux_session_name,
                       tmux_window_index, tmux_pane_index, tmux_pane_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS log_attachments_active_log_path
    ON log_attachments(log_path) WHERE status = 'active';
```

**Field rules**:
- `attachment_id`: `lat_<12-lowercase-hex>` (Research R-001).
- `agent_id`: FK to `agents.agent_id` (FEAT-006); RESTRICT delete
  preserves the audit trail (FEAT-006 never hard-deletes agents,
  same boundary inherited).
- Pane composite key (six denormalized columns): mirrors FEAT-006
  `agents` denormalization; allows FR-042 fast lookup by pane key
  without JOIN.
- `log_path`: absolute, ≤ 4096 chars, validated per FR-006. The
  partial unique index enforces "at most one `active` row per
  `log_path`" (the FR-009 / FR-041 collision guard).
- `status`: closed-set CHECK constraint; the daemon validates at
  the application layer too for the actionable `value_out_of_set`
  rejection.
- `source`: closed-set; daemon-internal-only (FR-039 wire rejects
  client-supplied values).
- `pipe_pane_command`: the literal `docker exec` shell that was
  issued, sanitized (NUL strip, ≤ 4096 chars). Stored for forensic
  audit; never re-executed.
- Timestamps: ISO-8601 microsecond UTC, e.g.
  `2026-05-08T14:23:45.123456+00:00`. Matches FEAT-006 timestamp
  shape exactly.
- `superseded_at` / `superseded_by`: nullable; both set when
  `status='superseded'`; both null otherwise. Application layer
  enforces this invariant (no SQL CHECK because the DDL would be
  fragile across edge transitions).

### 1.2 Table `log_offsets`

```sql
CREATE TABLE IF NOT EXISTS log_offsets (
    agent_id                   TEXT NOT NULL,
    log_path                   TEXT NOT NULL,
    byte_offset                INTEGER NOT NULL DEFAULT 0,
    line_offset                INTEGER NOT NULL DEFAULT 0,
    last_event_offset          INTEGER NOT NULL DEFAULT 0,
    last_output_at             TEXT,
    file_inode                 TEXT,
    file_size_seen             INTEGER NOT NULL DEFAULT 0,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL,
    PRIMARY KEY (agent_id, log_path),
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE RESTRICT
);
```

**Indexes**:

```sql
CREATE INDEX IF NOT EXISTS log_offsets_agent
    ON log_offsets(agent_id);
```

**Field rules**:
- Composite PK `(agent_id, log_path)`: one offset row per
  attached `(agent, path)` pair. When supersede creates a new
  attachment row at a new path, a new `log_offsets` row at
  `(agent_id, new_path)` is inserted at `(0, 0, 0)`. The OLD
  `log_offsets` row at `(agent_id, old_path)` is RETAINED (not
  deleted) so a future operator can inspect the historical offset
  if they re-attach to the old path; cleanup is a future-feature
  concern.
- `byte_offset`, `line_offset`, `last_event_offset`: INTEGER ≥ 0;
  initial values per FR-015.
- `file_inode`: TEXT shaped `"<dev>:<ino>"` (Research R-010);
  NULL until first reader cycle observes the file.
- `file_size_seen`: INTEGER ≥ 0; bytes observed at most recent
  reader cycle.
- `last_output_at`: nullable ISO-8601 microsecond UTC; the file's
  most recent observed `mtime`.
- Timestamps follow FEAT-006 shape.

### 1.3 Foreign-key cascade behavior

Both tables use `ON DELETE RESTRICT`. Combined with FEAT-006's
soft-delete-only invariant for agents, this means:
- Agents are never hard-deleted in MVP; the FK never trips.
- `log_attachments` rows in non-`active` statuses persist for the
  forensic audit trail.
- Cleanup is explicitly out of scope for FEAT-007; future features
  may introduce a `prune-attachments` admin command.

---

## 2. JSONL audit row: `log_attachment_change`

Every `log_attachments.status` transition appends exactly one row
to the existing FEAT-001 `events.jsonl` file (FR-044). The on-disk
shape:

```json
{
  "ts": "2026-05-08T14:23:45.123456+00:00",
  "type": "log_attachment_change",
  "payload": {
    "attachment_id": "lat_a1b2c3d4e5f6",
    "agent_id": "agt_abc123def456",
    "prior_status": "active",
    "new_status": "stale",
    "prior_path": "/host/path/to/log/A.log",
    "new_path": "/host/path/to/log/A.log",
    "prior_pipe_target": null,
    "source": "explicit",
    "socket_peer_uid": 1000
  }
}
```

**Field rules**:
- `ts`: daemon-clock ISO-8601 microsecond UTC. Matches FEAT-006
  `agent_role_change` `ts` shape byte-for-byte.
- `type`: literal string `"log_attachment_change"`.
- `payload.attachment_id`: the row's id.
- `payload.agent_id`: the bound agent.
- `payload.prior_status`: closed-set `{active, superseded, stale,
  detached}` OR `null` for first-creation transitions (e.g. a
  brand-new `attach-log` that creates the row from scratch); the
  daemon emits `null` ONLY on the very first creation, never on
  recovery transitions.
- `payload.new_status`: closed-set `{active, superseded, stale,
  detached}`.
- `payload.prior_path`: nullable string. Equal to `new_path` for
  same-path transitions (recovery, supersede-to-self never
  happens). Different from `new_path` only on FR-019 path-change
  supersede.
- `payload.new_path`: the row's current `log_path`.
- `payload.prior_pipe_target`: nullable string; populated only
  when FR-011 detected a foreign pre-existing pipe and the daemon
  toggled it off. Sanitized per FEAT-006 rules (NUL strip,
  ≤ 2048 chars, no control bytes).
- `payload.source`: closed-set `{explicit, register_self}`.
- `payload.socket_peer_uid`: integer; the SO_PEERCRED-derived uid
  of the calling client.

**Append rules**:
- One audit row per actual transition (FR-044, FR-045).
- No-op writes (FR-018 idempotent re-attach with no status change)
  append zero rows.
- Failed attaches append zero rows.
- Failed detaches append zero rows.
- The append uses the FEAT-001 `events.writer.append_event`
  helper unchanged; failures of that helper surface as
  FEAT-006-style `audit_append_failed` lifecycle events and the
  daemon stays alive.

---

## 3. Lifecycle event shapes

These events go through the daemon's existing lifecycle logger
(NOT events.jsonl). They are observability signals about external
state. (FR-046)

### 3.1 `log_rotation_detected`

Fired by FR-024 (file truncation: `current_file_size <
file_size_seen`) and FR-025 (file recreation: `file_inode` differs).

```python
{
    "event": "log_rotation_detected",
    "agent_id": "agt_abc123def456",
    "log_path": "/host/path/to/log/A.log",
    "prior_inode": "234:1234567",
    "new_inode": "234:7654321",   # equal to prior_inode for truncation
    "prior_size": 8192,
    "new_size": 0,
    "ts": "2026-05-08T14:23:45.123456+00:00"
}
```

### 3.2 `log_file_missing`

Fired by FR-026 when a reader cycle observes the host file has
disappeared.

```python
{
    "event": "log_file_missing",
    "agent_id": "agt_abc123def456",
    "log_path": "/host/path/to/log/A.log",
    "last_known_inode": "234:1234567",
    "last_known_size": 8192,
    "ts": "2026-05-08T14:23:45.123456+00:00"
}
```

### 3.3 `log_file_returned`

Fired by FR-026 when a reader cycle observes the host file has
reappeared at a `log_path` whose row is in `status=stale`. Suppress
repeat firings on same `(agent_id, log_path, file_inode)` triple.

```python
{
    "event": "log_file_returned",
    "agent_id": "agt_abc123def456",
    "log_path": "/host/path/to/log/A.log",
    "prior_inode": "234:1234567",   # nullable if never recorded
    "new_inode": "234:8888888",
    "new_size": 16,
    "ts": "2026-05-08T14:23:45.123456+00:00"
}
```

### 3.4a `mounts_json_oversized`

Fired by FR-063 when `containers.mounts_json` exceeds 256 mount
entries.

```python
{
    "event": "mounts_json_oversized",
    "container_id": "<full-64-char-id>",
    "observed_count": 312,
    "max_count": 256,
    "ts": "2026-05-08T14:23:45.123456+00:00"
}
```

### 3.4b `socket_peer_uid_mismatch`

Fired by FR-058 when a connecting client's SO_PEERCRED uid does
not match the daemon's effective uid.

```python
{
    "event": "socket_peer_uid_mismatch",
    "observed_uid": 1001,
    "expected_uid": 1000,
    "ts": "2026-05-08T14:23:45.123456+00:00"
}
```

(Connection is closed immediately; no agent_id / log_path context
is available because the FEAT-007 method dispatch never runs.)

### 3.5 `log_attachment_orphan_detected`

Fired by FR-043 daemon-startup pass when a pane is observed with
`pane_pipe=1` whose target matches the AgentTower canonical-log-
prefix but has no corresponding `log_attachments` row.

```python
{
    "event": "log_attachment_orphan_detected",
    "container_id": "<full-64-char-id>",
    "pane_composite_key": {
        "container_id": "<full-id>",
        "tmux_socket_path": "/tmp/tmux-1000/default",
        "tmux_session_name": "main",
        "tmux_window_index": 0,
        "tmux_pane_index": 0,
        "tmux_pane_id": "%17"
    },
    "observed_pipe_target": "/host/.../<unknown>",
    "ts": "2026-05-08T14:23:45.123456+00:00"
}
```

### 3.6 Suppression registry durability (FR-061 / FR-046)

The per-`(agent_id, log_path)` and per-`(agent_id, log_path, file_inode)`
and per-`(container_id, pane_composite_key, observed_pipe_target)`
suppression state described in FR-061 lives **in process memory only**.
The daemon does NOT persist this state to SQLite or to events.jsonl.

**Implications**:
- After a daemon restart (graceful or hard), every suppression counter
  resets to zero. A previously-suppressed `log_file_returned` event MAY
  re-fire once for the same triple; a previously-suppressed
  `log_file_missing` MAY re-fire once after the row's next stale-state
  entry; a previously-suppressed `log_attachment_orphan_detected` MAY
  re-fire once per orphan in the next startup pass.
- This is acceptable because lifecycle events are observability signals
  (FR-046), not audit rows. The audit log (FEAT-001 events.jsonl)
  carries the durable record; lifecycle events are diagnostic.
- Operators who want strict at-most-once semantics across restarts must
  consume lifecycle events into an external system (FEAT-008 event
  classification or downstream observability tooling), not the daemon
  itself.

**Where the state lives**: `logs/lifecycle.py` (T030) holds the maps
as module-level dictionaries protected by a single guard lock. No
persistence; no recovery hook. Tests asserting this invariant: T174
(restart durability assertion) and T182 (suppression-state implementation).

---

## 4. Validation rules

### 4.1 `--log <path>` shape (FR-006 + hardening)

Inherited verbatim from FEAT-006 `project_path` validation:
- Absolute path (starts with `/`).
- ≤ 4096 chars.
- No NUL byte.
- No `..` segment after normalization.
- No C0 control bytes after stripping.
- A path that is a directory, NOT a regular file: rejected via
  `log_path_invalid` (FR-006 edge case).

Plus the FEAT-007 hardening rules (anchor each rule to the FR):
- No newline (`\n`), carriage return (`\r`), tab (`\t`), or DEL
  (`0x7F`) bytes — FR-051.
- No path equal to or under any daemon-owned root
  (`agenttower.sqlite3`, `events.jsonl`, `agenttowerd.sock`,
  `agenttowerd.lock`, `agenttowerd.pid`, `~/.config/opensoft/`,
  `~/.cache/opensoft/`); the canonical log subdirectory is the
  only allowed exception — FR-052.
- No path whose realpath resolves under `/proc/`, `/sys/`,
  `/dev/`, or `/run/` — FR-053.
- Symlink-escape (path lies under bind mount but realpath escapes
  the resolved mount Source root) — rejected at host-visibility-
  proof time per FR-050.

All rejections produce `log_path_invalid` (or
`log_path_not_host_visible` for FR-050) with zero side effects
(SC-012).

### 4.2 Closed-set field validation

| Field          | Closed set                                            |
|----------------|-------------------------------------------------------|
| `status`       | `{active, superseded, stale, detached}`               |
| `source`       | `{explicit, register_self}` (daemon-internal-only)    |

Out-of-set values surface as `value_out_of_set` with a message
listing the valid values (mirrors FEAT-006 pattern).

### 4.3 `--preview <N>` bounds (FR-033)

`1 ≤ N ≤ 200`. Out-of-range surfaces as `value_out_of_set` with
the message `"lines must be between 1 and 200"`.

### 4.4 Wire envelope allowed-keys (FR-039)

| Method               | Allowed keys                                                        |
|----------------------|---------------------------------------------------------------------|
| `attach_log`         | `{schema_version, agent_id, log_path, source}` (source rejected on wire — clients cannot supply) |
| `detach_log`         | `{schema_version, agent_id}`                                        |
| `attach_log_status`  | `{schema_version, agent_id}`                                        |
| `attach_log_preview` | `{schema_version, agent_id, lines}`                                 |

Unknown keys surface as `bad_request` listing the offending keys.

---

## 5. State transitions

```text
                              ┌──────────────────────────────┐
                              │                              │
                              v                              │
       ┌──────────┐ attach   ┌────────┐ pane drift ┌─────┐  │
none ──┤ create   ├─────────>│ active │───────────>│stale│  │
       └──────────┘          └────┬───┘            └─┬───┘  │
                                  │                   │      │
                  detach (operator)│                   │ same-path attach
                                  v                   │ (operator)
                             ┌────────┐               │
                             │detached│<──────────────┘
                             └────┬───┘
                                  │
                                  │ same-path attach (operator)
                                  └───────────────────────────┐
                                                              │
                                                              v
                                                          ┌───────┐
                       path change (operator) ───────────>│  new  │
                                                          │active │
                                                          └───────┘
                                                              ↑
                                                              │
                       prior row → superseded (any status)────┘
```

**Allowed transitions** (every transition appends one
`log_attachment_change` audit row):

| From          | Via                                   | To           | Audit row?  |
|---------------|---------------------------------------|--------------|-------------|
| none          | `attach-log` (first time)             | `active`     | yes (prior_status=null) |
| `active`      | `attach-log` same path                | `active`     | NO (FR-018 no-op) |
| `active`      | `attach-log` different path           | `superseded` | yes (FR-019) |
| `active`      | `detach-log`                          | `detached`   | yes (FR-021c) |
| `active`      | FEAT-004 reconcile (pane → inactive)  | `stale`      | yes (FR-042, source=explicit) |
| `active`      | FEAT-008 reader (file vanished)       | `stale`      | yes (FR-026) |
| `stale`       | `attach-log` same path                | `active`     | yes (FR-021); offsets retained or reset per file consistency |
| `stale`       | `attach-log` different path           | `superseded` | yes (FR-019) |
| `stale`       | file reappears (no operator action)   | `stale` (unchanged) | NO; emits `log_file_returned` lifecycle event only |
| `detached`    | `attach-log` same path                | `active`     | yes (FR-021d); offsets retained |
| `detached`    | `attach-log` different path           | `superseded` | yes (FR-019) |
| `superseded`  | (terminal)                            | (no transitions) | n/a |

**Forbidden transitions**:
- Any transition INTO `detached` other than from `active` via
  operator-explicit `detach-log` (FR-021a).
- Any transition out of `superseded` (terminal).
- Any auto-transition between any non-`active`/non-stale states.

---

## 6. Test seam JSON shape: `AGENTTOWER_TEST_LOG_FS_FAKE`

A path to a JSON file consumed by `logs/host_fs.py`:

```json
{
  "/host/path/A.log": {
    "exists": true,
    "inode": "234:1234567",
    "size": 4096,
    "mtime_iso": "2026-05-08T14:23:45.123456+00:00",
    "contents": "line one\nline two\nsk-AAAAAAAAAAAAAAAAAAAA\n"
  },
  "/host/path/B.log": {
    "exists": false
  }
}
```

**Rules**:
- Production code (no env var) uses real `os.stat` etc.
- Test mode (env var set): every `host_fs` call resolves the path
  against this map. Unmapped paths behave as `{"exists": false}`.
- `contents` is optional; only `read_tail_lines` consumes it.
  Missing `contents` for an `exists: true` path causes
  `read_tail_lines` to return `b""`.
- The JSON is read once at module load; test fixtures must rewrite
  the file and reset the module's cached map between scenarios
  (the helper exposes `_reset_for_test()` for this).

---

## 7. Validation order (daemon-side `attach_log`)

0. SO_PEERCRED uid match (FR-058) — runs at connection-accept
   time, before any FEAT-007 method dispatch. Mismatched uid
   closes the connection, emits one `socket_peer_uid_mismatch`
   lifecycle event.
1. `_check_schema_version` (FR-038 forward-compat) — refuse with
   `schema_version_newer` if daemon's `schema_version` < client's
   advertised value.
2. `_check_unknown_keys` (FR-039) — refuse with `bad_request` for
   any key outside the `attach_log` closed allowed-keys set
   (including `source` rejected on wire).
3. Required-field presence (`agent_id`).
4. `agent_id` shape validation (`agt_<12-hex>` per FEAT-006).
5. `agent_id` resolution → row in `agents` table (FR-001 →
   `agent_not_found`).
6. `agents.active=1` check (FR-002 → `agent_inactive`).
7. Bound pane present in `panes` table with `active=1` (FR-003);
   trigger one focused FEAT-004 rescan if missing
   (`pane_unknown_to_daemon`).
8. Bound container's `containers.active=1` (FR-004 →
   `agent_inactive`).
9. `log_path` shape + hardening validation (FR-006, FR-051,
   FR-052, FR-053 → `log_path_invalid`) — only when `--log` is
   supplied; otherwise generated path is bypassed per FR-005.
10. Host-visibility proof with realpath / symlink-escape /
    chained-mount / mounts-bound checks (FR-007, FR-050, FR-056,
    FR-063 → `log_path_not_host_visible`).
11. `log_path_in_use` check (FR-009 → `log_path_in_use`).
12. `tmux_unavailable` check via cached `containers.tmux_present`
    (FR-013 → `tmux_unavailable`).
13. Acquire per-`agent_id` mutex FIRST, then per-`log_path` mutex
    SECOND only when `--log` is supplied (FR-040, FR-041, FR-059).
    Reverse-order acquisition is forbidden.
14. `BEGIN IMMEDIATE` SQLite transaction.
15. Re-check existing row state inside the transaction (FR-018 /
    FR-019 / FR-021 / FR-021d branch decision).
16. Verify directory mode 0700 + create file with `O_EXCL | O_CREAT
    | O_WRONLY` mode 0600 if absent — under the per-`agent_id`
    mutex, in this order (FR-008, FR-048, FR-057).
17. Issue `tmux list-panes` inspection (FR-011) via FEAT-004
    adapter; canonical-target match is STRICT EQUALITY (FR-054).
18. Issue `tmux pipe-pane` attach (or toggle-off + attach) with
    `shlex.quote` interpolation (FR-010, FR-019, FR-021c, FR-047)
    via FEAT-003 docker-exec adapter; mid-flight crash → no row
    persistence (FR-055, FR-012).
19. Update or insert `log_attachments` row.
20. Update or insert `log_offsets` row.
21. Append `log_attachment_change` audit row via FEAT-001 writer
    (FR-044), with bounded payload sizes (FR-062).
22. `COMMIT`.
23. Release locks (LIFO order of acquisition).

On failure at any stage post-step 14, ROLLBACK and append zero
audit rows (FR-045). On failure pre-step 14, return the closed-
set error code without touching SQLite or the audit log.
