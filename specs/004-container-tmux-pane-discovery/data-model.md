# Phase 1 Data Model: Container tmux Pane Discovery

**Branch**: `004-container-tmux-pane-discovery` | **Date**: 2026-05-06

This document is the canonical reference for FEAT-004 entities,
SQLite schema, and state transitions. Anything here overrides the
informal entity descriptions in spec.md. FEAT-004 inherits FEAT-003's
filesystem layout, audit channel, lifecycle log, and matching shape;
this document only records what is *added* by FEAT-004.

---

## 1. Filesystem footprint

FEAT-004 adds **no new files, sockets, or directories**. Three
existing paths gain new behavior:

| Path                                                | Read by FEAT-004 | Written by FEAT-004 |
| --------------------------------------------------- | ---------------- | ------------------- |
| `<STATE_DIR>/agenttower.sqlite3`                    | yes (`containers` for active set + `container_user`; `panes`, `pane_scans`, `schema_version`) | yes (migration v2→v3; per-scan inserts/updates on `panes` + `pane_scans`) |
| `<STATE_DIR>/events.jsonl`                          | no               | yes (one line per *degraded* pane scan; nothing on healthy scans) |
| `<LOGS_DIR>/agenttowerd.log`                        | no               | yes (two new event tokens: `pane_scan_started`, `pane_scan_completed`) |
| `<CONFIG_DIR>/config.toml`                          | no               | no (no `[panes]` block in MVP — R-005) |
| `<STATE_DIR>/agenttowerd.sock`                      | served on        | no                  |
| `<STATE_DIR>/agenttowerd.{pid,lock}`                | no               | no                  |

The FEAT-003 `containers` and `container_scans` tables are read-only
from FEAT-004's perspective (FR-030). Mode bits inherited from
FEAT-001: parent dirs `0700`, files `0600`.

---

## 2. SQLite schema (v3)

FEAT-004 bumps `CURRENT_SCHEMA_VERSION` from `2` to `3`. The migration
adds two tables and touches no existing table (FR-029, FR-030). The
migration runner already exists from FEAT-003 (R-012); FEAT-004 adds
one new step `_apply_migration_v3`. The migration runs idempotently
(every `CREATE TABLE` / `CREATE INDEX` carries `IF NOT EXISTS`).

### 2.1 Table `panes`

```sql
CREATE TABLE IF NOT EXISTS panes (
    container_id            TEXT NOT NULL,
    tmux_socket_path        TEXT NOT NULL,
    tmux_session_name       TEXT NOT NULL,
    tmux_window_index       INTEGER NOT NULL,
    tmux_pane_index         INTEGER NOT NULL,
    tmux_pane_id            TEXT NOT NULL,
    container_name          TEXT NOT NULL,
    container_user          TEXT NOT NULL,
    pane_pid                INTEGER NOT NULL,
    pane_tty                TEXT NOT NULL,
    pane_current_command    TEXT NOT NULL,
    pane_current_path       TEXT NOT NULL,
    pane_title              TEXT NOT NULL,
    pane_active             INTEGER NOT NULL CHECK(pane_active IN (0, 1)),
    active                  INTEGER NOT NULL CHECK(active IN (0, 1)),
    first_seen_at           TEXT NOT NULL,
    last_scanned_at         TEXT NOT NULL,
    PRIMARY KEY (
        container_id,
        tmux_socket_path,
        tmux_session_name,
        tmux_window_index,
        tmux_pane_index,
        tmux_pane_id
    )
);

CREATE INDEX IF NOT EXISTS panes_active_order
    ON panes(active DESC, container_id ASC, tmux_socket_path ASC,
             tmux_session_name ASC, tmux_window_index ASC,
             tmux_pane_index ASC);

CREATE INDEX IF NOT EXISTS panes_container_socket
    ON panes(container_id, tmux_socket_path);
```

| Column                | Type                | Notes |
| --------------------- | ------------------- | ----- |
| `container_id`        | TEXT (full id)      | Component of the composite PK. Foreign key in spirit to `containers.container_id`; no SQL FK enforced (FEAT-004 only reads `containers`, FR-030). |
| `tmux_socket_path`    | TEXT                | Absolute path inside the container, e.g. `/tmp/tmux-1000/default`. Component of the composite PK. |
| `tmux_session_name`   | TEXT                | From `#{session_name}`. Tabs/newlines stripped per R-009. Component of the composite PK. |
| `tmux_window_index`   | INTEGER             | From `#{window_index}`. Component of the composite PK. |
| `tmux_pane_index`     | INTEGER             | From `#{pane_index}`. Component of the composite PK. |
| `tmux_pane_id`        | TEXT (`%N` form)    | From `#{pane_id}`. Component of the composite PK; reused ids in a different session/window are treated as new panes (FR-007). |
| `container_name`      | TEXT                | Convenience copy from `containers.name`; refreshed on every successful pane upsert. Leading `/` already stripped by FEAT-003. |
| `container_user`      | TEXT                | The bench user passed to `docker exec -u`. Resolved at scan time per R-005 (`containers.config_user` else daemon `$USER`). Refreshed on every successful pane upsert. |
| `pane_pid`            | INTEGER             | From `#{pane_pid}`. |
| `pane_tty`            | TEXT                | From `#{pane_tty}`. |
| `pane_current_command`| TEXT                | From `#{pane_current_command}`. Sanitized + truncated to 2048 chars (R-009). |
| `pane_current_path`   | TEXT                | From `#{pane_current_path}`. Sanitized + truncated to 4096 chars (R-009). |
| `pane_title`          | TEXT                | From `#{pane_title}`. Sanitized + truncated to 2048 chars (R-009). |
| `pane_active`         | INTEGER (0/1)       | From `#{pane_active}`: `1` when this pane is the focused pane in its window, `0` otherwise. Distinct from the row-level `active` flag below. |
| `active`              | INTEGER (0/1)       | Row-level reconciliation flag: `1` when this pane was reported by the most recent successful per-`(container, socket)` scan; `0` when reconciled away. |
| `first_seen_at`       | TEXT (ISO-8601 UTC) | Set on insert; never updated. |
| `last_scanned_at`     | TEXT (ISO-8601 UTC) | Updated on every scan that observed this `(container, socket)` tuple — including the FR-010 preservation path, the FR-011 sibling-socket preservation path, and the FR-009 inactive-container cascade. |

Timestamps: ISO-8601 with offset, microsecond precision, UTC,
matching FEAT-002 / FEAT-003.

### 2.2 Table `pane_scans`

```sql
CREATE TABLE IF NOT EXISTS pane_scans (
    scan_id                      TEXT PRIMARY KEY,
    started_at                   TEXT NOT NULL,
    completed_at                 TEXT NOT NULL,
    status                       TEXT NOT NULL CHECK(status IN ('ok', 'degraded')),
    containers_scanned           INTEGER NOT NULL,
    sockets_scanned              INTEGER NOT NULL,
    panes_seen                   INTEGER NOT NULL,
    panes_newly_active           INTEGER NOT NULL,
    panes_reconciled_inactive    INTEGER NOT NULL,
    containers_skipped_inactive  INTEGER NOT NULL,
    containers_tmux_unavailable  INTEGER NOT NULL,
    error_code                   TEXT,
    error_message                TEXT,
    error_details_json           TEXT
);

CREATE INDEX IF NOT EXISTS pane_scans_started
    ON pane_scans(started_at DESC);
```

| Column                         | Type                | Notes |
| ------------------------------ | ------------------- | ----- |
| `scan_id`                      | TEXT (UUID4)        | Generated by the daemon at scan start. Returned to the caller. Distinct namespace from `container_scans.scan_id`. |
| `started_at`                   | TEXT (ISO-8601 UTC) | Wall-clock time the scan acquired the pane mutex. |
| `completed_at`                 | TEXT (ISO-8601 UTC) | Wall-clock time of the SQLite commit. |
| `status`                       | TEXT                | `'ok'` only when no per-container or per-socket error fired, every active container produced at least one parsed `tmux list-panes` row OR an empty result from a reachable tmux server, and no row required truncation; `'degraded'` otherwise (FR-027). |
| `containers_scanned`           | INTEGER             | Count of active containers reached by `docker exec` in this scan (excludes those skipped via the FR-009 cascade). |
| `sockets_scanned`              | INTEGER             | Count of `(container, socket)` tuples for which a `tmux list-panes` call was attempted. |
| `panes_seen`                   | INTEGER             | Count of well-formed pane rows parsed across every successful socket scan. Equals the number of `upserts` in the reconcile write set. |
| `panes_newly_active`           | INTEGER             | Count of `panes` rows that were absent or `active=0` before this scan and became `active=1`. |
| `panes_reconciled_inactive`    | INTEGER             | Count of `panes` rows that were `active=1` before this scan and became `active=0`. Matches the size of the reconcile `inactivate` set. |
| `containers_skipped_inactive`  | INTEGER             | Count of containers that were `containers.active = 0` at scan start and triggered the FR-009 cascade. |
| `containers_tmux_unavailable`  | INTEGER             | Count of active containers for which the entire pane scope ended up unknown (no `id -u`, no socket dir, every socket failed). Their prior pane rows are preserved per FR-010. **Disjoint from `containers_skipped_inactive`**: a container that triggered the FR-009 cascade is NOT counted here even if its tmux scope is also unknown — formally, `containers_tmux_unavailable = len(tmux_unavailable_containers − inactive_cascade_containers)`. The two counters never double-count the same container. |
| `error_code`                   | TEXT (nullable)     | Closed-set token (R-011). NULL on healthy scans. The representative code for partial failures is the first per-container or per-socket failure in scan order. |
| `error_message`                | TEXT (nullable)     | Sanitized + truncated to 2048 chars (R-009). |
| `error_details_json`           | TEXT (nullable JSON)| One element per affected `(container, socket?)` tuple: `{container_id, tmux_socket_path?, error_code, error_message, pane_truncations?}`. `tmux_socket_path` is omitted for per-container failures (no `id -u`, socket dir missing). `pane_truncations` is omitted unless at least one pane field on a successful socket scan was truncated. NULL on healthy scans. |

### 2.3 Schema version row

`schema_version` already exists from FEAT-001 and was bumped to `2`
by FEAT-003. After the v3 migration, its single row reads
`version = 3`. The daemon caches this value at startup (FEAT-002
contract); `agenttower status` will report `schema_version: 3` after
this feature lands.

---

## 3. Domain entities

All entities below are in-memory dataclasses; persistence is
exclusively via the SQLite schema in §2.

### 3.1 `ParsedPane` (parsed `tmux list-panes` row)

Result of one well-formed row from `tmux -S <socket> list-panes -a -F
<format>` after splitting on `\t` and validating field count = 10
(R-002). Pre-sanitization shape; the reconciler runs each field
through `sanitize_text(...)` before producing a `PaneUpsert`.

```python
@dataclass(frozen=True)
class ParsedPane:
    tmux_session_name:    str
    tmux_window_index:    int
    tmux_pane_index:      int
    tmux_pane_id:         str    # e.g. "%0"
    pane_pid:             int
    pane_tty:             str
    pane_current_command: str
    pane_current_path:    str
    pane_title:           str
    pane_active:          bool   # parsed from "1" / "0"
```

### 3.2 `SocketListing` (parsed socket-dir output)

Result of one `ls -1 -- /tmp/tmux-<uid>` invocation. Empty lines and
non-basename rows are dropped per R-007.

```python
@dataclass(frozen=True)
class SocketListing:
    container_id: str
    uid:          str            # raw stdout of `id -u`, digits only
    sockets:      tuple[str, ...]  # basenames; "default" surfaces here when present
```

### 3.3 `SocketScanOutcome`

Per-`(container, socket)` result fed into the reconciler.

```python
SocketScanOutcome = OkSocketScan | FailedSocketScan

@dataclass(frozen=True)
class OkSocketScan:
    panes: tuple[ParsedPane, ...]   # may be empty (reachable server, zero panes)

@dataclass(frozen=True)
class FailedSocketScan:
    error_code:    str    # one of the closed-set per-socket codes (R-011)
    error_message: str    # sanitized + bounded; not raw stderr
```

### 3.4 `TmuxError`

```python
@dataclass(frozen=True)
class TmuxError(Exception):
    code:             str           # closed-set token (R-011)
    message:          str           # sanitized + bounded
    container_id:     str | None = None   # populated for per-container failures
    tmux_socket_path: str | None = None   # populated for per-socket failures
```

### 3.5 `PaneScanResult`

The return value of `PaneDiscoveryService.scan()` and the payload of
the `scan_panes` socket method's `result`.

```python
@dataclass(frozen=True)
class PaneScanResult:
    scan_id:                       str
    started_at:                    str    # ISO-8601 UTC
    completed_at:                  str
    status:                        Literal["ok", "degraded"]
    containers_scanned:            int
    sockets_scanned:               int
    panes_seen:                    int
    panes_newly_active:            int
    panes_reconciled_inactive:     int
    containers_skipped_inactive:   int
    containers_tmux_unavailable:   int
    error_code:                    str | None
    error_message:                 str | None
    error_details:                 list[PerScopeError]    # may be empty even when degraded

@dataclass(frozen=True)
class PerScopeError:
    container_id:     str
    tmux_socket_path: str | None       # None for per-container failures
    error_code:       str
    error_message:    str
    pane_truncations: list[PaneTruncationNote]   # default empty

@dataclass(frozen=True)
class PaneTruncationNote:
    tmux_pane_id: str          # the pane whose field was truncated
    field:        str          # one of: pane_title, pane_current_command, pane_current_path, ...
    original_len: int          # pre-truncation length in characters
```

### 3.6 `PaneUpsert` (sanitized full-row write)

Produced by the reconciler from a `ParsedPane` + container metadata.
Consumed by the SQLite writer.

```python
@dataclass(frozen=True)
class PaneUpsert:
    container_id:         str
    tmux_socket_path:     str
    tmux_session_name:    str
    tmux_window_index:    int
    tmux_pane_index:      int
    tmux_pane_id:         str
    container_name:       str
    container_user:       str
    pane_pid:             int
    pane_tty:             str
    pane_current_command: str    # post-sanitize, post-truncate
    pane_current_path:    str    # post-sanitize, post-truncate
    pane_title:           str    # post-sanitize, post-truncate
    pane_active:          bool
    last_scanned_at:      str    # always the scan's started_at
    # first_seen_at handled by the SQL writer:
    # INSERT ... ON CONFLICT(...) DO UPDATE preserves the existing
    # first_seen_at and writes the new last_scanned_at.
```

### 3.7 `PaneCompositeKey`

Tuple alias for the composite primary key. Used by the reconciler
for `touch_only` and `inactivate` sets.

```python
PaneCompositeKey = tuple[str, str, str, int, int, str]
# (container_id, tmux_socket_path, tmux_session_name,
#  tmux_window_index, tmux_pane_index, tmux_pane_id)
```

---

## 4. State transitions

### 4.1 `panes.active` flag

Five distinct transitions cover every case spec FR-008 / FR-009 /
FR-010 / FR-011 demands. The transition is determined per row by the
reconciler from the per-`(container, socket)` outcome, NOT by the
container-level outcome.

```text
                                      (parsed in this scan,
                                       socket scan = OkSocketScan)
   ┌─────────┐   ──────────────────────────────────────────────►   ┌──────────┐
   │  none   │                                                     │ active=1 │
   └─────────┘                                                     └────┬─────┘
                                                                        │
                          ┌─────────────────────────────────────────────┤
                          │                                             │
                          │                                             │
                          ▼ (a) per-(c,s) OkSocketScan,                 │ (b) per-(c,s) OkSocketScan,
                                pane absent from parsed set:               pane present in parsed set:
                                active 1→0, last_scanned_at = scan.started_at      active stays 1, full row refreshed
                                                                                (incl. pane_active, pane_pid, ...)
                          ┌──────────┐
                          │ active=0 │  ◄── (a)
                          └────┬─────┘
                               │
                               │ (b) parsed in a later scan
                               │     → active 0→1, full row refreshed
                               ▼
                          ┌──────────┐
                          │ active=1 │
                          └──────────┘
```

Plus the three preservation paths (FR-009, FR-010, FR-011), which all
emit a `touch_only` write — the row is left otherwise unchanged and
only `last_scanned_at` is updated:

| Transition | Trigger | Effect on `active` | Effect on other columns |
| ---------- | ------- | ------------------ | ----------------------- |
| (c) FR-009 inactive-container cascade | `containers.active = 0` at scan start AND row's `container_id` matches | `1 → 0` | `last_scanned_at` updated; no `docker exec` invoked for that container |
| (d) FR-010 tmux-unavailable preservation | container has no `id -u` / no socket dir / every socket failed | UNCHANGED | `last_scanned_at` updated |
| (e) FR-011 sibling-socket preservation | a `(container, socket)` tuple's scan failed but at least one *other* socket on the same container succeeded | UNCHANGED for rows belonging to the failed socket | `last_scanned_at` updated |

The combined behavior:
- (a) and the `inactivate` half of (c) flip rows to `active = 0`.
- (b) flips rows to `active = 1` (or holds them at 1) AND refreshes
  every non-key column from the new parse.
- (d) and (e) are pure `touch_only` updates: only `last_scanned_at`
  changes, regardless of what the prior `active` value was.
- Pane rows are NEVER deleted (FR-008).

`first_seen_at` is set on the insert path of transition (a→active=1
from `none`) and is otherwise immutable. A pane that goes inactive
and later reappears keeps its original `first_seen_at`; an upsert
on its composite key updates `last_scanned_at` and refreshes the
non-key columns but never overwrites `first_seen_at`.

### 4.2 `pane_scans.status`

```text
   start ──► ok            (every active container reached a tmux server,
                            every per-socket scan returned OkSocketScan,
                            no pane row required truncation, no row was
                            counted as malformed)
         └─► degraded      (any of:
                              - any per-container error (id -u failed,
                                socket_dir_missing, socket_unreadable,
                                tmux_unavailable, tmux_no_server,
                                docker_exec_failed, docker_exec_timeout)
                              - any per-socket error (tmux_no_server on
                                one socket, output_malformed,
                                docker_exec_failed, docker_exec_timeout)
                              - any pane field required truncation
                              - any tmux list-panes row failed parse
                                with output_malformed)
```

`ok` and `degraded` are terminal; `pane_scans` rows are never updated
after insertion. Whole-scan failures (e.g., `docker_unavailable` from
`shutil.which("docker")` returning nothing) still persist a row with
`status='degraded'`, even when the socket envelope is `ok:false`
(R-011, mirroring FEAT-003 R-014).

### 4.3 `containers` table interaction

FEAT-004 only **reads** the FEAT-003 `containers` table:

| Read | Used for |
| ---- | -------- |
| `SELECT container_id, name, config_user FROM containers WHERE active = 1` | Active set scanned by `docker exec` (FR-002). Returns the set of `container_id` values plus the bench user resolution input per R-005. |
| `SELECT container_id FROM containers WHERE active = 0` (intersected with `panes.container_id`) | FR-009 cascade set: prior panes whose container has gone inactive between FEAT-003 and FEAT-004 scans. |

No FEAT-004 statement modifies `containers` or `container_scans`
(FR-030).

---

## 5. Reconciliation algorithm

Pure function in `discovery/pane_reconcile.py` (R-008) so it can be
unit tested without touching SQLite:

```python
def reconcile(
    *,
    prior_panes:                  dict[PaneCompositeKey, PriorPaneRow],
    socket_results:               dict[tuple[str, str], SocketScanOutcome],
    tmux_unavailable_containers:  set[str],
    inactive_cascade_containers:  set[str],
    container_metadata:           dict[str, ContainerMeta],
    now_iso:                      str,
) -> PaneReconcileWriteSet:
    ...

@dataclass(frozen=True)
class PriorPaneRow:
    active:        bool
    first_seen_at: str   # preserved on upsert

@dataclass(frozen=True)
class ContainerMeta:
    container_name: str
    container_user: str

@dataclass(frozen=True)
class PaneReconcileWriteSet:
    upserts:                      list[PaneUpsert]                # transition (a)→1 / (b)
    touch_only:                   list[PaneCompositeKey]          # transitions (d), (e)
    inactivate:                   list[PaneCompositeKey]          # transition (a)→0 + transition (c)
    pane_truncations:             list[PaneTruncationNote]        # one per truncated field across all upserts
    panes_seen:                   int                             # len(upserts)
    panes_newly_active:           int                             # upserts whose prior row was absent or active=0
    panes_reconciled_inactive:    int                             # len(inactivate)
    containers_skipped_inactive:  int                             # len(inactive_cascade_containers ∩ {c | any prior_panes row has c})
    containers_tmux_unavailable:  int                             # len(tmux_unavailable_containers ∩ active container set)
```

Inputs in plain English:

- `prior_panes`: every existing `panes` row indexed by composite key.
  Loaded once at scan start with `SELECT * FROM panes`.
- `socket_results`: one entry per `(container_id, socket_path)` tuple
  for which a `tmux list-panes` call was attempted. Successful socket
  scans yield `OkSocketScan(panes=...)` (possibly empty); failed
  socket scans yield `FailedSocketScan(error_code, error_message)`.
- `tmux_unavailable_containers`: container ids whose tmux scope is
  unknown for this scan (no `id -u` result, socket dir missing,
  socket dir unreadable, OR every attempted socket scan failed). FR-010
  applies: prior pane rows for these containers go through `touch_only`,
  not through reconciliation.
- `inactive_cascade_containers`: container ids whose
  `containers.active = 0` at scan start. FR-009 applies: every prior
  pane row whose `container_id` is in this set has its `active` flag
  flipped to `0` regardless of whether `docker exec` was attempted
  (it MUST NOT be).
- `container_metadata`: `container_name` and `container_user` per
  container_id, used to refresh the convenience copies on upsert.
- `now_iso`: scan start timestamp. Every `last_scanned_at` and (for
  inserts) `first_seen_at` is set from this single value.

Reconciliation is per-`(container, socket)` (FR-011):

1. For each `(c, s) → OkSocketScan(panes)`:
   - Sanitize+truncate every `ParsedPane`; record any
     `PaneTruncationNote`.
   - Emit one `PaneUpsert` per parsed pane.
   - Compute prior_socket_keys = composite keys in `prior_panes`
     that share `(container_id=c, tmux_socket_path=s)`.
   - Emit `inactivate` for every key in `prior_socket_keys` whose
     prior row was `active=1` AND that is NOT in the parsed set.
2. For each `(c, s) → FailedSocketScan(...)` where `c` is NOT in
   `tmux_unavailable_containers` and NOT in
   `inactive_cascade_containers`:
   - Emit `touch_only` for every prior pane row whose composite key
     shares `(c, s)`. (FR-011 sibling-socket preservation.)
3. For each `c` in `tmux_unavailable_containers` AND `c` is NOT in
   `inactive_cascade_containers`:
   - Emit `touch_only` for every prior pane row whose
     `container_id == c`, regardless of socket. (FR-010
     tmux-unavailable preservation.)
4. For each `c` in `inactive_cascade_containers`:
   - Emit `inactivate` for every prior pane row whose
     `container_id == c` AND prior `active=1`. Prior rows with
     `active=0` get `touch_only` (their `last_scanned_at` still
     advances). (FR-009 inactive-container cascade.)
5. For each `c` that was scanned (i.e., `c` appears as the first
   element of at least one `socket_results` key) AND `c` is NOT in
   `tmux_unavailable_containers` AND `c` is NOT in
   `inactive_cascade_containers`:
   - Compute `sockets_observed = {s | (c, s) ∈ socket_results}`.
   - For every prior pane row whose `container_id == c` AND whose
     `tmux_socket_path NOT IN sockets_observed`: emit `inactivate`
     when prior `active=1`, else `touch_only`. This is the
     **disappeared-socket** case — the socket file was no longer
     enumerated by `ls -1 -- /tmp/tmux-<uid>/` between scans (e.g.,
     the operator ran `tmux -L work kill-server`), so neither an
     `OkSocketScan` nor a `FailedSocketScan` exists for that
     `(c, s)` tuple. The pane state is *known-empty* for that
     socket (the socket no longer exists), distinct from the
     FR-010 *unknown-empty* case.

`upserts` and `inactivate` are mutually exclusive within one scan
because (a) and (b) are computed from the same OkSocketScan parsed
set; `touch_only` is mutually exclusive with both.

The returned `PaneReconcileWriteSet` is consumed by the SQLite
writer in one `BEGIN IMMEDIATE / COMMIT` transaction (FR-024). The
pane_truncations are NOT persisted into `panes` rows — they surface
only in the `pane_scans.error_details_json` payload and the socket
response. If the SQLite transaction fails, the transaction rolls
back, no JSONL degraded event is appended, the pane-scan mutex is
released, and the caller receives `internal_error` (R-015).

---

## 6. JSON serialization at the socket boundary

The two new socket methods serialize the dataclasses above into the
shapes documented in `contracts/socket-api.md`. Notes that matter
for clients:

1. `panes.pane_active` (the focused-pane flag from tmux) and the
   row-level `active` flag are distinct fields in every JSON
   payload. The CLI default view shows the row-level `active` as
   "active/inactive"; `pane_active` surfaces as a focused-pane
   marker. They are NEVER collapsed into a single field at the
   protocol boundary.
2. `scan_panes` returns the same `PaneScanResult` shape for healthy
   scans and partial degraded scans; `status="degraded"` is the
   signal, not a different envelope. Whole-scan failures
   (`docker_unavailable`) return an `ok:false` envelope while still
   persisting a `pane_scans` row for audit.
3. `pane_scans.error_details_json`, socket
   `result.error_details`, JSONL degraded event details, and CLI
   `--json` details share one canonical per-scope shape:
   `{container_id, tmux_socket_path?, error_code, error_message,
   pane_truncations?}`. `tmux_socket_path` is omitted for
   per-container failures (no `id -u`, no socket dir).
   `pane_truncations` is omitted unless at least one pane field
   was truncated on a successful socket scan.
4. `list_panes` is read-only, MUST NOT acquire the pane-scan
   mutex, and MUST return rows in the deterministic order
   `active DESC, container_id ASC, tmux_socket_path ASC,
   tmux_session_name ASC, tmux_window_index ASC,
   tmux_pane_index ASC` (FR-016). The `--container <id-or-name>`
   CLI filter resolves on the daemon side: a single `WHERE
   container_id = ?` if the argument is a 64-char hex, else a
   single `WHERE container_id IN (SELECT container_id FROM
   containers WHERE name = ?)`. Empty result is exit code `0`.
5. **Counter-name alias at the JSON boundary.** The
   `pane_scans` SQLite column, the `PaneScanResult` Python
   dataclass field, and the CLI default `key=value` rendering
   all use the short name `panes_reconciled_inactive`. The JSON
   wire form (socket envelope `result.panes_reconciled_to_inactive`,
   CLI `--json` payload, JSONL `pane_scan_degraded.payload`,
   and `pane_scans.error_details_json` aggregate views) uses
   the long name `panes_reconciled_to_inactive`. The two names
   refer to the same counter (the size of the reconcile
   `inactivate` set per data-model §5). The serialization layer
   in `socket_api/methods.py` MUST perform this alias rename in
   exactly one direction (dataclass → JSON) on the `scan_panes`
   response path; deserialization on the CLI side reads the
   long name from the JSON envelope and maps it back to the
   short name for the human-readable rendering. No other
   `PaneScanResult` field is renamed at the JSON boundary.

---

## 7. Migration & backward compatibility

| FEAT | Concern | Resolution |
| ---- | ------- | ---------- |
| FEAT-001 | `agenttower config init` byte-for-byte stable | FEAT-004 adds no new config block; the loader has no `[panes]` section in MVP (R-005). |
| FEAT-001 | `events.jsonl` schema | Degraded pane scans append using the existing `events.writer.append_event(...)` API. Event type token: `pane_scan_degraded` (parallel to FEAT-003's `container_scan_degraded`). No existing record shape changes. |
| FEAT-002 | `agenttower status` schema | `schema_version` field now reports `3` (was `2`). FEAT-002 already documents `schema_version` as forward-compatible (clients tolerate unknown values). |
| FEAT-002 | `ping` / `status` / `shutdown` envelopes | Unchanged. New methods (`scan_panes`, `list_panes`) added to the dispatch table; unknown-method responses for any other token are unchanged. |
| FEAT-003 | `containers` / `container_scans` schema | UNCHANGED (FR-030). FEAT-004 only reads from these tables. The single new read pattern — `SELECT container_id, name, config_user FROM containers WHERE active = 1` — fits the existing `containers_active_lastscan` index. |
| FEAT-003 | `scan_containers` / `list_containers` socket methods | UNCHANGED. The new `scan_panes` mutex is independent of the FEAT-003 scan mutex (FR-017). |
| FEAT-003 | `scan_started` / `scan_completed` lifecycle tokens | UNCHANGED. FEAT-004 adds two distinct tokens (`pane_scan_started`, `pane_scan_completed`) so operators can grep them apart. |

A daemon running the FEAT-004 build against a v2 SQLite database
applies the v3 migration exactly once at startup. A daemon running
the FEAT-003 build against a v3 SQLite database refuses to start
(schema-version mismatch); downgrade is not supported (FR-029).

The v2 → v3 migration runs in a single transaction. If any statement
fails, the transaction rolls back and the daemon refuses to serve
requests rather than operating with a partial schema. Future database
versions greater than this build supports also cause startup refusal.
An otherwise-empty v2 database still receives both new tables and
then bumps `schema_version` to 3.
