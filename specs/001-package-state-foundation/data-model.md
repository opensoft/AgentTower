# Phase 1 Data Model: Package, Config, and State Foundation

**Branch**: `001-package-state-foundation` | **Date**: 2026-05-05

This feature touches only one persistent table and four on-disk artifacts.
The "data model" is therefore primarily a filesystem + single-table
specification rather than a relational schema. Later features (FEAT-002+)
will extend the SQLite schema; nothing in FEAT-001 may add tables beyond
the one defined here.

---

## 1. Filesystem entities (the Resolved Path Set)

The `Paths` resolver returns one frozen, immutable struct of six members.
Every member is a `pathlib.Path`. Paths shown below assume XDG defaults
(when XDG variables are unset). When `XDG_CONFIG_HOME`, `XDG_STATE_HOME`,
or `XDG_CACHE_HOME` is set, the corresponding base is replaced and the
`opensoft/agenttower` sub-namespace is preserved beneath it (per FR-007).

| Key (FR-004) | Field on `Paths` | Default location | Kind | Created by `config init` | Mode (FR-015) |
|---|---|---|---|---|---|
| `CONFIG_FILE` | `config_file` | `~/.config/opensoft/agenttower/config.toml` | regular file | yes (only if absent) | `0600` |
| `STATE_DB` | `state_db` | `~/.local/state/opensoft/agenttower/agenttower.sqlite3` | SQLite file | yes (idempotent) | `0600` |
| `EVENTS_FILE` | `events_file` | `~/.local/state/opensoft/agenttower/events.jsonl` | append-only file | **no** — created lazily by event-writer | `0600` (when writer creates it) |
| `LOGS_DIR` | `logs_dir` | `~/.local/state/opensoft/agenttower/logs/` | directory | yes (only if absent) | `0700` |
| `SOCKET` | `socket` | `~/.local/state/opensoft/agenttower/agenttowerd.sock` | UNIX socket file | **no** — owned by FEAT-002 daemon | n/a (FEAT-002) |
| `CACHE_DIR` | `cache_dir` | `~/.cache/opensoft/agenttower/` | directory | yes (only if absent) | `0700` |

Implied parent directories also created by `config init` with mode
`0700`:

- `~/.config/opensoft/`, `~/.config/opensoft/agenttower/`
- `~/.local/state/opensoft/`, `~/.local/state/opensoft/agenttower/`
- `~/.cache/opensoft/`, `~/.cache/opensoft/agenttower/`

Mode policy for pre-existing artifacts:

- FEAT-001 never chmods a pre-existing artifact to "fix" it.
- "AgentTower-owned" means any path under the resolved
  `opensoft/agenttower` namespace for this feature.
- If a required AgentTower-owned artifact that FEAT-001 must use already
  exists with a broader mode than required (`0700` for directories,
  `0600` for files), the command or writer refuses and names the path,
  leaving bytes and mode unchanged.
- Pre-existing artifacts FEAT-001 does not touch, such as a stale socket
  file or prior log file, are left alone regardless of mode.
- Newly-created files and directories are chmod'd/fchmod'd after creation
  as needed so process `umask` cannot make the final mode broader than
  the table above.

### Invariants

- The set has exactly six members. Adding a seventh requires a spec
  amendment in a later feature.
- All members live under the same `opensoft/agenttower` sub-namespace
  beneath their respective XDG bases (default `~/.config`,
  `~/.local/state`, `~/.cache`).
- The `CONFIG_FILE` path's `parent` is the configuration directory.
- The `STATE_DB`, `EVENTS_FILE`, `LOGS_DIR`, and `SOCKET` paths share a
  common parent: the state directory.
- The `CACHE_DIR` is itself the cache directory; AgentTower writes no
  cache data in FEAT-001.

---

## 2. Default configuration file

| Field | Type | Required | Default | Source |
|---|---|---|---|---|
| `containers.name_contains` | array of strings | yes | `["bench"]` | architecture.md §6 |
| `containers.scan_interval_seconds` | integer (seconds) | yes | `5` | architecture.md §6 |

Validation rules (enforced by readers in FEAT-002+, **not** by FEAT-001
which only writes the default):

- `name_contains` MUST be a non-empty array of non-empty strings.
- `scan_interval_seconds` MUST be a positive integer.

`config init` writes the file verbatim from `R-005` of `research.md` and
never touches an existing file.

---

## 3. Registry database (SQLite)

File: at `STATE_DB`.

Pragmas applied on open (idempotent):

- `journal_mode = WAL`
- `foreign_keys = ON`

### 3.1 Table `schema_version`

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
```

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `version` | `INTEGER` | `NOT NULL` | Schema generation; monotonically increasing across durable schema migrations. |

Row-level invariants (enforced by application code in `state.schema`):

- The table contains **exactly one** row at all times after initialization.
- The single row's `version` value MUST match the package's compile-time
  constant `CURRENT_SCHEMA_VERSION` after `config init` runs against a
  fresh database. For the FEAT-001 release, `CURRENT_SCHEMA_VERSION = 1`.
- `CURRENT_SCHEMA_VERSION` is owned by the AgentTower codebase, is
  independent of the package release version, and is incremented by later
  migration features only when they add or change durable schema.
- `config init` MUST NOT change `version` if a row already exists. (Schema
  migrations are owned by later features; FEAT-001 only seeds the row.)

### 3.2 Reserved schema future

No other tables, indexes, triggers, or views may be created by FEAT-001.
The empty `src/agenttower/state/` package is reserved for FEAT-002+ to
add tables (`containers`, `panes`, `agents`, etc., per
`docs/architecture.md` §18).

---

## 4. Event history file (JSONL)

File: at `EVENTS_FILE`.

Format: one JSON object per line, UTF-8, terminated by `\n`. The file is
strictly append-only at the application layer (no truncation, no
in-place edits).

### 4.1 Record shape (FEAT-001 contract)

Every record produced by the event-writer utility is a JSON object with
**at least** the following key:

| Key | Type | Required | Notes |
|---|---|---|---|
| `ts` | string (ISO-8601 with offset, microsecond precision) | yes | Generated by the writer using `datetime.now(UTC)`. Caller-supplied `ts` is overwritten. |

All other keys are caller-supplied. FEAT-001 itself **does not** call
the writer outside of tests; therefore no event-type taxonomy is
defined at this layer. FEAT-008 will define the canonical event-type
schema and is free to add required keys (`event_id`, `event_type`,
`agent_id`, etc.) without breaking the FEAT-001 writer contract.

### 4.2 Concurrency invariants

- Each `append_event(...)` call produces exactly one line.
- Concurrent in-process callers cannot interleave bytes within a record
  (enforced by a module-level `threading.Lock`, see research R-007).
- Cross-process append safety is **not** guaranteed in FEAT-001 (no
  daemon yet). FEAT-002 may revisit by adding `fcntl.flock`.

---

## 5. Relationships and lifecycle

```text
Paths (resolver, in-memory)
   ├── CONFIG_FILE  ── written by `config init`               (FR-005)
   ├── STATE_DB     ── opened/created by `config init`        (FR-005, FR-009)
   │      └── table schema_version  (one row)                 (FR-009)
   ├── EVENTS_FILE  ── created lazily by event-writer         (FR-012)
   ├── LOGS_DIR     ── ensured by `config init`               (FR-005)
   ├── SOCKET       ── NOT touched in FEAT-001                (FR-016, FEAT-002)
   └── CACHE_DIR    ── ensured by `config init`               (FR-005)
```

State transitions:

- **Uninitialized → Initialized**: `config init` on a fresh host
  creates `CONFIG_FILE`, `STATE_DB` (with one `schema_version` row),
  and the directories. `EVENTS_FILE` and `SOCKET` remain absent.
- **Initialized → Initialized** (re-run): `config init` is a no-op
  (FR-010). Files unchanged, directories unchanged, `schema_version`
  row unchanged.
- **Initialized → Has-events**: any FEAT-002+ caller invokes
  `append_event(...)`, which lazily creates `EVENTS_FILE` with mode
  `0600` and appends a record.

Schema migrations are out of scope for FEAT-001; the lifecycle does
**not** include an "upgrade" transition yet.
