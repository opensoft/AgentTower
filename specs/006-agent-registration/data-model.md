# Phase 1 Data Model: Agent Registration and Role Metadata

**Branch**: `006-agent-registration` | **Date**: 2026-05-07

This document is the canonical reference for FEAT-006 entities and
data flow. Anything here overrides the informal entity descriptions
in `spec.md`. FEAT-006 introduces exactly **one** new SQLite table
(`agents`), **three** new SQLite indexes, **zero** new files on
disk, and **one** new JSONL event-type appended to the existing
FEAT-001 `events.jsonl`.

---

## 1. Filesystem footprint

FEAT-006 adds **no new files**. One existing FEAT-001 file gains a
new event-type; the existing FEAT-001 `state.db` gains one table and
three indexes via migration v4.

| Path                                              | Read by FEAT-006 | Written by FEAT-006 |
| ------------------------------------------------- | ---------------- | ------------------- |
| `<state_dir>/state.db`                            | yes              | yes (new `agents` table; existing FEAT-003 / FEAT-004 tables read-only) |
| `<state_dir>/state.db-journal` / `-wal` / `-shm`  | yes (companions) | yes (companions; mode `0600`) |
| `<state_dir>/events.jsonl`                        | no               | yes (one new event-type `agent_role_change`; mode `0600`) |
| `<RESOLVED_SOCKET>` (env / mounted-default / host-default) | yes (`AF_UNIX` connect for the five new socket methods) | no (the daemon writes to its own socket; FEAT-006 CLIs are read/write clients) |

No SQLite reads or writes happen client-side. The daemon side is
the single writer.

---

## 2. SQLite schema

`CURRENT_SCHEMA_VERSION` advances from `3` (FEAT-004) to `4`
(FEAT-006). The migration is idempotent and runs under one
`BEGIN IMMEDIATE` transaction inside
`schema._apply_pending_migrations` (FR-036). FEAT-001 / FEAT-002 /
FEAT-003 / FEAT-004 tables are untouched (FR-037).

### 2.1 New table `agents`

```sql
CREATE TABLE IF NOT EXISTS agents (
    agent_id                 TEXT NOT NULL PRIMARY KEY,
    -- Pane composite key (denormalized; mirrors panes PK; FR-002, FR-037)
    container_id             TEXT NOT NULL,
    tmux_socket_path         TEXT NOT NULL,
    tmux_session_name        TEXT NOT NULL,
    tmux_window_index        INTEGER NOT NULL,
    tmux_pane_index          INTEGER NOT NULL,
    tmux_pane_id             TEXT NOT NULL,
    -- Mutable metadata
    role                     TEXT NOT NULL CHECK(role IN ('master','slave','swarm','test-runner','shell','unknown')),
    capability               TEXT NOT NULL CHECK(capability IN ('claude','codex','gemini','opencode','shell','test-runner','unknown')),
    label                    TEXT NOT NULL DEFAULT '',
    project_path             TEXT NOT NULL DEFAULT '',
    -- Optional immutable parent linkage for swarm agents
    parent_agent_id          TEXT,
    -- Derived JSON column (recomputed on every role write)
    effective_permissions    TEXT NOT NULL,
    -- Lifecycle timestamps and active flag
    created_at               TEXT NOT NULL,
    last_registered_at       TEXT NOT NULL,
    last_seen_at             TEXT,
    active                   INTEGER NOT NULL CHECK(active IN (0, 1)),
    -- Pane composite key uniqueness (FR-006)
    UNIQUE (
        container_id,
        tmux_socket_path,
        tmux_session_name,
        tmux_window_index,
        tmux_pane_index,
        tmux_pane_id
    )
);
```

**Notes on column choices**:

- `agent_id TEXT PRIMARY KEY` — matches FR-001's
  `agt_<12-character-lowercase-hex>` shape; opaque string
  identifier.
- The pane composite key is denormalized rather than enforced by a
  foreign key on `panes` because (a) FEAT-004 panes transition
  active/inactive across scans and reuse pane ids; (b) FR-037
  forbids a foreign-key constraint here. Application-layer
  reconciliation (see §5) handles the relationship.
- The `UNIQUE` constraint on the pane composite key tuple enforces
  FR-006 at the storage layer: at most one agent per pane.
- `parent_agent_id` is nullable. No `FOREIGN KEY` reference is
  declared because the spec explicitly allows the parent record to
  later be demoted, deleted, or marked inactive without
  invalidating the swarm child's stored `parent_agent_id` (FR-018).
  Application-layer validation at `register_agent` time (FR-017)
  enforces parent existence / activeness / role at the moment of
  swarm creation.
- `effective_permissions TEXT NOT NULL` stores the JSON object
  per FR-021. The pure derivation function lives in
  `agents/permissions.py` (research R-008).
- `last_seen_at TEXT` is nullable on creation (no FEAT-004 scan
  has yet observed the pane after registration); the FEAT-004
  reconciliation transaction populates it on the next scan
  (FR-009a; research R-003).
- `active INTEGER` mirrors the FEAT-003 / FEAT-004 boolean encoding
  conventions (`0`/`1`).
- `created_at`, `last_registered_at`, `last_seen_at` are ISO-8601
  microsecond UTC strings, consistent with
  `containers.first_seen_at` and `panes.first_seen_at`.

### 2.2 Indexes

```sql
-- FR-025 deterministic ordering for list_agents (R-009)
CREATE INDEX IF NOT EXISTS agents_active_order
    ON agents(active DESC, container_id ASC, parent_agent_id ASC,
              label ASC, agent_id ASC);

-- FR-026 filter by parent_agent_id (swarm children of a slave)
CREATE INDEX IF NOT EXISTS agents_parent_lookup
    ON agents(parent_agent_id);

-- FEAT-004 pane reconciliation last_seen_at UPDATE predicate (R-003)
CREATE INDEX IF NOT EXISTS agents_pane_lookup
    ON agents(container_id, tmux_socket_path, tmux_session_name,
              tmux_window_index, tmux_pane_index, tmux_pane_id);
```

The `UNIQUE` constraint on the pane composite key tuple already
implies an index covering exact-match lookups; the explicit
`agents_pane_lookup` index is kept for clarity and to match the
FEAT-004 pattern (`panes_active_order`, `panes_container_socket`).

### 2.3 No other table changes

`containers`, `container_scans`, `panes`, `pane_scans`,
`schema_version` — unchanged byte-for-byte from FEAT-004.

---

## 3. Migration `v3 → v4` (FR-036)

```python
def _apply_migration_v4(conn: sqlite3.Connection) -> None:
    """Create FEAT-006 tables. Idempotent because of IF NOT EXISTS guards."""
    conn.execute(
        # ... agents CREATE TABLE from §2.1 ...
    )
    conn.execute(
        # ... agents_active_order CREATE INDEX from §2.2 ...
    )
    conn.execute(
        # ... agents_parent_lookup CREATE INDEX from §2.2 ...
    )
    conn.execute(
        # ... agents_pane_lookup CREATE INDEX from §2.2 ...
    )
```

Registered in `_MIGRATIONS[4] = _apply_migration_v4`.
`CURRENT_SCHEMA_VERSION` becomes `4`.

The migration is invoked in two scenarios per the existing
`_ensure_current_schema` flow:

1. v3 DB → upgraded to v4 in one
   `_apply_pending_migrations(conn, 3)` call (single transaction).
2. v4 DB → defensive re-call of `_apply_migration_v4` from the
   "already at current version" branch (idempotent via
   `IF NOT EXISTS`).

---

## 4. In-memory entities (request / response shapes)

### 4.1 `AgentRecord`

The Python dataclass returned by `state/agents.py` reads:

```python
@dataclass(frozen=True)
class AgentRecord:
    agent_id: str
    container_id: str
    tmux_socket_path: str
    tmux_session_name: str
    tmux_window_index: int
    tmux_pane_index: int
    tmux_pane_id: str
    role: str
    capability: str
    label: str
    project_path: str
    parent_agent_id: str | None
    effective_permissions: dict[str, Any]   # parsed from JSON column
    created_at: str
    last_registered_at: str
    last_seen_at: str | None
    active: bool
```

### 4.2 `RegisterAgentRequest` (in-process; not on the wire)

```python
@dataclass
class RegisterAgentRequest:
    container_id: str                       # full FEAT-005 resolved id
    pane_composite_key: PaneCompositeKey    # six-tuple from FEAT-004 lookup
    role: str | _UNSET                      # _UNSET means "leave unchanged"
    capability: str | _UNSET
    label: str | _UNSET
    project_path: str | _UNSET
    parent_agent_id: str | None | _UNSET    # _UNSET ≠ None; None means "no parent"
    socket_peer_uid: int                    # captured by FEAT-002 SO_PEERCRED
```

`_UNSET` is the in-process marker for "field absent in the JSON
request envelope" per Clarifications Q1. The wire protocol
encodes it as "key not present in the params object".

### 4.3 `EffectivePermissions`

```python
EffectivePermissions = TypedDict(
    "EffectivePermissions",
    {
        "can_send": bool,
        "can_receive": bool,
        "can_send_to_roles": list[str],
    },
)
```

Closed-set values per FR-021:

| Role          | can_send | can_receive | can_send_to_roles |
| ------------- | -------- | ----------- | ----------------- |
| `master`      | `true`   | `false`     | `["slave", "swarm"]` |
| `slave`       | `false`  | `true`      | `[]` |
| `swarm`       | `false`  | `true`      | `[]` |
| `test-runner` | `false`  | `false`     | `[]` |
| `shell`       | `false`  | `false`     | `[]` |
| `unknown`     | `false`  | `false`     | `[]` |

### 4.4 `AuditRecord` (JSONL row shape)

FEAT-006 reuses the FEAT-001 `events.writer.append_event` helper
unchanged, so its on-disk shape is the standard nested envelope —
`ts` is added by the writer and the FEAT-006 fields live under
`payload`:

```json
{
  "ts": "2026-05-07T14:30:00.123456+00:00",
  "type": "agent_role_change",
  "payload": {
    "agent_id": "agt_abc123def456",
    "prior_role": null,
    "new_role": "slave",
    "confirm_provided": false,
    "socket_peer_uid": 1000
  }
}
```

Field rules:

- `ts` — daemon clock, prepended by `events.writer.append_event`;
  ISO-8601 with microseconds and explicit `+00:00` UTC offset.
- `type` — fixed literal `"agent_role_change"` for FEAT-006.
- `payload.prior_role` — JSON `null` on first registration of an
  agent (creation transition); the previous string role on every
  other transition (Clarifications Q4).
- `payload.new_role` — closed-set string from FR-004.
- `payload.confirm_provided` — the **literal** boolean the
  operator passed in the `confirm` request parameter, never
  rewritten based on whether `--confirm` was *required* by the
  transition (Clarifications session 2026-05-07-continued Q5).
  `true` when the CLI passed `--confirm`; `false` when it did
  not. Demotion with redundant `--confirm` logs `true`;
  `set-role` to a non-master role with redundant `--confirm` also
  logs `true`; `register-self` creation always logs `false`.
  Consumers that need "was confirm required" derive it from
  `prior_role` + `new_role`.
- `payload.socket_peer_uid` — host uid of the calling process, from
  FEAT-002 `SO_PEERCRED`. The daemon extracts this from the
  accepted AF_UNIX connection out-of-band and a request body cannot
  spoof it; `-1` indicates the kernel did not surface a peer
  credential (e.g. tests calling the dispatcher directly without a
  real socket).

No-op writes (set-* with the same value the agent already has;
register-self with an unchanged role) MUST NOT append a row
(FR-027). Failed writes MUST NOT append a row (FR-014).

---

## 5. Cross-table relationships and transactions

### 5.1 `agents` ↔ `panes` (FR-009 / FR-009a)

The `agents` row stores the FEAT-004 pane composite key
denormalized (no FK constraint per FR-037). The relationship is
maintained at the application layer:

- **Pane reconciliation** (`discovery/pane_reconcile.py`):
  - For every pane observed as `active=true` in a FEAT-004 scan,
    `UPDATE agents SET last_seen_at = :scan_time WHERE
    (container_id, tmux_socket_path, ...) = :pane_key` runs in
    the same `BEGIN IMMEDIATE` transaction as the pane row
    upsert. The `agents_pane_lookup` index covers this predicate.
  - For every pane that transitions active→inactive
    (`panes.active 1 → 0`), `UPDATE agents SET active = 0 WHERE
    (container_id, ...) = :pane_key` runs in the same
    transaction (FR-009).
  - Inactive→active pane transitions do NOT auto-flip
    `agents.active` (FR-009); explicit `register-self` is
    required.

- **Re-activation** (`agents/service.py` `register_agent`):
  - When a `register-self` call comes from a composite key whose
    existing agent row is `active=0`, the handler runs `UPDATE
    agents SET active = 1, last_registered_at = :now,
    role = :resolved_role, capability = :resolved_capability,
    label = :resolved_label, project_path = :resolved_project,
    effective_permissions = :recomputed WHERE agent_id = ?` in a
    single transaction (FR-008). `created_at` and
    `parent_agent_id` are NOT modified.

### 5.2 `agents` parent linkage (FR-017)

- At `register_agent --role swarm --parent <id>` time, the
  handler runs `SELECT role, active FROM agents WHERE agent_id = ?`
  to validate (a) parent exists; (b) `active = 1`; (c)
  `role = 'slave'`. Failure short-circuits before any agent row
  write (FR-017).
- After creation, no continuing constraint is enforced — the
  parent agent may later be demoted, deleted, or marked
  inactive (FR-018, FR-019).

### 5.3 Audit row append site

- The daemon-side `service.py` calls `agents/audit.py`'s
  `append_role_change(prior_role, new_role, ...)` *after* the
  SQLite COMMIT and only when `prior_role != new_role`. Failed
  COMMITs (rolled back) MUST NOT append a row (FR-014, FR-035).

### 5.4 Concurrency boundary (R-005)

- Per-(container_id, pane_composite_key) advisory mutex
  (`agents/service.py::register_locks`) serializes
  `register_agent` calls addressing the same pane (FR-038).
- Per-`agent_id` advisory mutex
  (`agents/service.py::agent_locks`) serializes `set_role`,
  `set_label`, `set_capability` calls addressing the same
  agent (FR-039).
- Concurrent calls addressing distinct keys / agent_ids
  proceed in parallel.

---

## 6. Wire format summary

The five new socket methods (full details in
`contracts/socket-api.md`):

### 6.1 `register_agent` request

```json
{
  "method": "register_agent",
  "params": {
    "container_id": "<full-id>",
    "pane_composite_key": {
      "container_id": "<full-id>",
      "tmux_socket_path": "/tmp/...",
      "tmux_session_name": "main",
      "tmux_window_index": 0,
      "tmux_pane_index": 0,
      "tmux_pane_id": "%17"
    },
    "role": "slave",                 // OPTIONAL (Clarifications Q1)
    "capability": "codex",            // OPTIONAL
    "label": "codex-01",              // OPTIONAL
    "project_path": "/workspace/acme",// OPTIONAL
    "parent_agent_id": "agt_aaa..."   // OPTIONAL
  }
}
```

### 6.2 `register_agent` response (success)

```json
{
  "ok": true,
  "result": {
    "agent_id": "agt_abc123def456",
    "role": "slave",
    "capability": "codex",
    "label": "codex-01",
    "project_path": "/workspace/acme",
    "parent_agent_id": null,
    "container_id": "<full-id>",
    "container_name": "...",
    "container_user": "...",
    "tmux_socket_path": "/tmp/...",
    "tmux_session_name": "main",
    "tmux_window_index": 0,
    "tmux_pane_index": 0,
    "tmux_pane_id": "%17",
    "pane_pid": 12345,
    "cwd": "/workspace/acme",
    "effective_permissions": {
      "can_send": false,
      "can_receive": true,
      "can_send_to_roles": []
    },
    "created_at": "2026-05-07T14:30:00.123456+00:00",
    "last_registered_at": "2026-05-07T14:30:00.123456+00:00",
    "last_seen_at": null,
    "active": true,
    "created_or_reactivated": "created"   // "created" | "reactivated" | "updated"
  }
}
```

### 6.3 `list_agents` request

```json
{
  "method": "list_agents",
  "params": {
    "role": "slave",                  // OPTIONAL — string or list of strings
    "container_id": "abc123def456",   // OPTIONAL — full or 12-char short
    "active_only": true,              // OPTIONAL — default false
    "parent_agent_id": "agt_aaa..."   // OPTIONAL
  }
}
```

### 6.4 `list_agents` response

```json
{
  "ok": true,
  "result": {
    "filter": {
      "role": null,
      "container_id": null,
      "active_only": false,
      "parent_agent_id": null
    },
    "agents": [
      { /* full AgentRecord JSON; see §4.1 + 6.2 result */ },
      ...
    ]
  }
}
```

Order is `active DESC, container_id ASC, parent_agent_id ASC NULLS FIRST, label ASC, agent_id ASC`
per FR-025 / R-009.

### 6.5 `set_role` / `set_label` / `set_capability` request

```json
{
  "method": "set_role",
  "params": {
    "agent_id": "agt_abc123def456",
    "role": "master",
    "confirm": true                   // OPTIONAL — required for role=master
  }
}
```

### 6.6 `set_*` response

```json
{
  "ok": true,
  "result": {
    "agent_id": "agt_abc123def456",
    "field": "role",
    "prior_value": "slave",
    "new_value": "master",
    "effective_permissions": { ... },  // recomputed
    "audit_appended": true             // false on no-op
  }
}
```

### 6.7 Error envelope

```json
{
  "ok": false,
  "error": {
    "code": "<closed_set_code>",
    "message": "<actionable message>"
  }
}
```

Closed-set codes are listed in `contracts/socket-api.md` and in
research R-010.

---

## 7. State transition diagrams

### 7.1 Agent lifecycle

```text
                        register-self (first time, valid pane)
                                       │
                                       ▼
            ┌────────────── (active, role=<assigned>) ───────┐
            │                                                │
register-self (different mutable fields)            FEAT-004 scan: pane absent
            │                                                │
            ▼                                                ▼
            └────► (active, role=<merged>) ───────► (inactive, role=<unchanged>)
                                                                │
                                                                │ register-self again
                                                                ▼
                                                  (active, role=<resolved>)
                                                  agent_id, created_at, parent_agent_id
                                                  preserved (FR-008)

set-role --role master --confirm  (when active+container active)
            │
            ▼
            (active, role=master, effective_permissions updated, audit row appended)

set-role --role slave / shell / test-runner / unknown
            │
            ▼
            (active, role=<new>, effective_permissions updated, audit row appended)

set-label / set-capability
            │
            ▼
            (active, role=unchanged, label/capability updated, NO audit row)
```

### 7.2 Audit append predicate

```text
  prior_role  →  new_role   |  audit row appended?
  ─────────────────────────  ─────────────────────
  null        →  X (any)    |  YES  (creation; Clarifications Q4)
  X           →  X          |  NO   (no-op; FR-027)
  X           →  Y (X≠Y)    |  YES  (transition; FR-014)
```

### 7.3a Validation order for `set_role`

```text
  client-side                               daemon-side
  ───────────                               ───────────
  1. Validate --target shape (case-sensitive)
  2. Validate --role in closed set (case-sensitive)
  3. Reject --role swarm client-side (swarm_role_via_set_role_rejected)
  4. Reject --role master without --confirm (master_confirm_required)
  5. Send set_role over the socket
                                            6. closed-set field shape (case-sensitive)
                                            7. static reject role=swarm (swarm_role_via_set_role_rejected)
                                            8. static reject role=master without confirm
                                            9. acquire per-agent_id mutex (FR-039)
                                            10. SELECT existing agent (existence pre-check)
                                            11. if no row: agent_not_found, release mutex
                                            12. BEGIN IMMEDIATE
                                            13. ATOMIC RE-CHECK: re-SELECT agents.active AND
                                                containers.active for the bound container_id;
                                                if either == 0 → ROLLBACK + agent_inactive
                                                (FR-011 / Clarifications session 2026-05-07-
                                                continued Q3). SQLite BEGIN IMMEDIATE serializes
                                                against concurrent FEAT-004 reconciliation.
                                            14. if new role == stored role: COMMIT no-op,
                                                no audit row (FR-027), release mutex
                                            15. recompute effective_permissions
                                            16. UPDATE agents SET role, effective_permissions
                                            17. COMMIT
                                            18. append audit row (literal confirm_provided
                                                per Clarifications Q5)
                                            19. release mutex
                                            20. respond
```

### 7.3 Validation order for `register_agent`

```text
  client-side                               daemon-side
  ───────────                               ───────────
  1. AGENTTOWER_SOCKET resolution (FEAT-005)
  2. CLI presence in tmux (NOT_IN_TMUX, TMUX_PANE_MALFORMED)
  3. FEAT-005 identity (HOST_CONTEXT_UNSUPPORTED, CONTAINER_UNRESOLVED)
  4. list_panes lookup; if absent, scan_panes(container=...) once
  5. If pane still absent after rescan: PANE_UNKNOWN_TO_DAEMON
  6. Compose RegisterAgentRequest (only supplied fields per Q1)
  7. Send register_agent over the socket
                                            8. forward-compat schema check
                                            9. closed-set field shape
                                            10. label/project bounds + sanitize
                                            11. master-safety static rejection
                                            12. acquire (container, pane_key) mutex
                                            13. SELECT existing agent for pane
                                            14. resolve mutable fields per Q1
                                            15. parent immutability check (FR-018a)
                                            16. compose post-write state
                                            17. recompute effective_permissions
                                            18. BEGIN IMMEDIATE
                                            19. INSERT or UPDATE agents
                                            20. COMMIT
                                            21. if role changed: append audit row
                                            22. release mutex
                                            23. respond (ok or error)
```

---

## 8. Validation rules summary

**Case-sensitivity rule** (Clarifications session 2026-05-07-continued Q2): every closed-set token below is lowercase and case-sensitive; every lowercase-hex identifier is case-sensitive. Mixed-case inputs are rejected with `value_out_of_set` and MUST NOT be normalized. This rule applies uniformly to every validator, filter, lookup, and comparison site.

| Field            | Validation                                                                       | On failure                       |
| ---------------- | -------------------------------------------------------------------------------- | -------------------------------- |
| `role`           | one of `{master, slave, swarm, test-runner, shell, unknown}` (FR-004); case-sensitive            | `value_out_of_set`               |
| `capability`     | one of `{claude, codex, gemini, opencode, shell, test-runner, unknown}` (FR-005); case-sensitive | `value_out_of_set`               |
| `agent_id`       | matches `^agt_[0-9a-f]{12}$` (FR-001); case-sensitive (no uppercase hex)         | `value_out_of_set`               |
| `parent_agent_id`| matches `^agt_[0-9a-f]{12}$` AND parent exists, active, role=slave (FR-017); case-sensitive      | `parent_not_found` / `parent_inactive` / `parent_role_invalid` |
| `container_id`   | full id or 12-char short prefix; lowercase hex; case-sensitive (FR-026)          | `value_out_of_set`               |
| `label`          | NUL-stripped, C0-stripped, ≤ 64 chars (FR-033)                                   | `field_too_long` if oversized    |
| `project_path`   | NUL-free, absolute, no `..` segment, ≤ 4096 chars (FR-034)                       | `project_path_invalid` / `field_too_long` |
| filter keys      | one of `{role, container_id, active_only, parent_agent_id}` (FR-026)             | `unknown_filter`                 |

---

## 9. Out-of-scope reaffirmation

FEAT-006 does **not** introduce:

- a network listener;
- an in-container daemon or relay;
- prompt delivery, queue inspection, route configuration;
- log attachment, log offset tracking, event ingestion;
- automatic swarm inference;
- multi-master arbitration;
- TUI or web UI;
- a new audit log file (uses existing `events.jsonl`);
- a foreign-key constraint between `agents` and `panes` (FR-037);
- any new test seam (reuses existing FEAT-003 / FEAT-004 /
  FEAT-005 seams);
- any new in-container subprocess shape (FR-042).
