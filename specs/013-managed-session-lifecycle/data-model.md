# Phase 1 Data Model: Managed Session Creation and Lifecycle

**Feature**: 013-managed-session-lifecycle
**Date**: 2026-05-24
**Sources**: spec.md §Key Entities + §Clarifications; research.md R3/R4/R7/R13.

---

## Entity overview

```text
ManagedTemplate (in-process; not stored in SQLite)
       │
       │ name
       ▼
ManagedLayout ────────────────────┐
   id, container_id, template_name, intended_pane_count,
   state, failed_stage?, idempotency_key?, created_at, updated_at
       │
       │ layout_id (1:N)
       ▼
ManagedPane ──────────► Agent (FEAT-006; nullable until registered)
   id, layout_id, agent_id?, role, capability, label,
   launch_command_ref?, tmux_session_name, tmux_pane_index,
   pending_marker_token?, state, failed_stage?,
   predecessor_id? (self-FK), chain_depth, created_at, updated_at

LaunchCommandProfile (YAML on disk; not stored in SQLite)
   name, command (argv), env?, working_dir?

LifecycleEvent (FEAT-008 JSONL; not stored in SQLite)
   event_id, timestamp, layout_id?, pane_id?, event_type, payload, actor
```

---

## SQLite DDL (additive migration `00NN_managed_sessions.sql`)

```sql
CREATE TABLE IF NOT EXISTS managed_layout (
    id                    TEXT PRIMARY KEY,             -- uuid4
    container_id          TEXT NOT NULL,
    template_name         TEXT NOT NULL,
    intended_pane_count   INTEGER NOT NULL,
    state                 TEXT NOT NULL CHECK (state IN
                              ('creating','ready','degraded','failed','removed')),
    failed_stage          TEXT,                          -- enum, see CHECK below
    idempotency_key       TEXT,
    created_at            TEXT NOT NULL,                 -- RFC3339 UTC
    updated_at            TEXT NOT NULL,
    CHECK (failed_stage IS NULL OR failed_stage IN
        ('pane_create','launch_command','registration','log_attach',
         'tmux_kill','recovery_reattach'))
);

CREATE INDEX IF NOT EXISTS ix_managed_layout_container_state
    ON managed_layout(container_id, state);

CREATE UNIQUE INDEX IF NOT EXISTS ux_managed_layout_idempotency_key
    ON managed_layout(container_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS managed_pane (
    id                    TEXT PRIMARY KEY,             -- uuid4
    layout_id             TEXT NOT NULL REFERENCES managed_layout(id),
    container_id          TEXT NOT NULL,                 -- denormalized from managed_layout.container_id at insert (FR-003 / Q4 label-uniqueness scope; SQLite does not allow subqueries in index expressions, so this column must be stored directly)
    agent_id              TEXT REFERENCES agents(agent_id),  -- FEAT-006 agent registry; null until registered
    role                  TEXT NOT NULL,                -- e.g., master / slave
    capability            TEXT NOT NULL,
    label                 TEXT NOT NULL,
    launch_command_ref    TEXT,                         -- name of LaunchCommandProfile
    tmux_session_name     TEXT NOT NULL,
    tmux_pane_index       INTEGER NOT NULL,
    pending_marker_token  TEXT,                         -- null in ready/degraded/failed/removed (FR-014 / FR-022 TTL sweep target)
    state                 TEXT NOT NULL CHECK (state IN
                              ('creating','ready','degraded','failed','removed')),
    failed_stage          TEXT,                          -- FR-013 closed set
    predecessor_id        TEXT REFERENCES managed_pane(id),
    chain_depth           INTEGER NOT NULL DEFAULT 0 CHECK (chain_depth >= 0 AND chain_depth <= 16),  -- FR-023 bound
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    CHECK (failed_stage IS NULL OR failed_stage IN
        ('pane_create','launch_command','registration','log_attach',
         'tmux_kill','recovery_reattach')),
    CHECK (
        pending_marker_token IS NULL OR state = 'creating'
    )
);

-- Label uniqueness scope: per bench container, across all managed layouts in that container (FR-003 / Q4).
-- managed_pane.container_id is denormalized from managed_layout.container_id at insert time and kept in sync by application code (the per-container serializer holds the only writer); SQLite does not support subqueries in CREATE INDEX expressions.
CREATE UNIQUE INDEX IF NOT EXISTS ux_managed_pane_container_label
    ON managed_pane(container_id, label)
    WHERE state IN ('creating','ready','degraded');
    -- terminal-state rows (failed/removed) do NOT participate in label uniqueness so recreate can reuse labels.

CREATE INDEX IF NOT EXISTS ix_managed_pane_layout_state
    ON managed_pane(layout_id, state);

CREATE INDEX IF NOT EXISTS ix_managed_pane_pending_marker
    ON managed_pane(pending_marker_token)
    WHERE pending_marker_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_managed_pane_predecessor
    ON managed_pane(predecessor_id)
    WHERE predecessor_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_managed_pane_tmux_target
    ON managed_pane(tmux_session_name, tmux_pane_index)
    WHERE state IN ('creating','ready','degraded');
    -- tmux pane target uniqueness; terminal-state rows are archived.
```

**Notes**:
- All timestamps are RFC3339 UTC (consistent with FEAT-008 audit format).
- No alteration to existing tables. `managed_pane.agent_id` is a soft FK; FEAT-006 owns the agent row, FEAT-013 only links to it.
- Label uniqueness uses a partial unique index on `managed_pane.container_id` (denormalized from `managed_layout.container_id` at insert; the per-container serializer is the only writer, so the denormalized value cannot drift). Terminal-state rows are excluded so a recreated pane can reuse the predecessor's label pattern.
- `tmux_session_name + tmux_pane_index` is also unique among non-terminal rows so the daemon cannot accidentally double-back two managed_pane records onto the same tmux pane after a partial recovery.
- FR-022 TTL sweep: managed_pane rows that linger in `state = 'creating'` for more than 5 minutes are transitioned to `failed` by `pending_marker.sweep()` (boot-time + 60s periodic) with `failed_stage = 'pane_create'` if no tmux pane backs the row, else `failed_stage = 'registration'`.

---

## Entity field reference

### ManagedLayout

| Field | Type | Notes |
|---|---|---|
| `id` | uuid4 string | PK |
| `container_id` | string | Foreign reference to FEAT-003 container registry |
| `template_name` | string | Matches `ManagedTemplate.name` |
| `intended_pane_count` | int | Copied from template at create time (Q5 — template-defined) |
| `state` | enum | `creating` \| `ready` \| `degraded` \| `failed` \| `removed` |
| `failed_stage` | enum NULL | One of R7's six values |
| `idempotency_key` | string NULL | Per-container idempotency scope (R10) |
| `created_at`, `updated_at` | RFC3339 UTC | |

**Lifecycle**: A layout transitions to `ready` iff all its `managed_pane` rows are in `ready` or `degraded`. A layout is `degraded` iff at least one pane is `degraded` and no pane is `creating` or `failed`. A layout is `failed` iff at least one pane is `failed`. A layout is `creating` while any pane is `creating`. A layout is `removed` iff all its panes are in `removed` (or never advanced past `creating` and were swept).

### ManagedPane

| Field | Type | Notes |
|---|---|---|
| `id` | uuid4 string | PK |
| `layout_id` | uuid4 string | FK → `managed_layout.id` |
| `container_id` | string | NOT NULL; denormalized from `managed_layout.container_id` at insert; participates in the per-container label-uniqueness index (FR-003) |
| `agent_id` | string NULL | FK → FEAT-006 `agents.agent_id`; null until registration completes |
| `role` | string | Template-declared (e.g., `master`, `slave`) |
| `capability` | string | Template-declared (e.g., `orchestrator`, `worker`) |
| `label` | string | Resolved from `label_pattern` + ordinal; unique per container across non-terminal panes |
| `launch_command_ref` | string NULL | Name of LaunchCommandProfile (R9) |
| `tmux_session_name` | string | Created by the layout |
| `tmux_pane_index` | int | tmux pane index within the session |
| `pending_marker_token` | string NULL | Equal to `idempotency_key` when present, else `uuid4()` (R1, R10) |
| `state` | enum | Same enum as layout |
| `failed_stage` | enum NULL | Same enum as layout |
| `predecessor_id` | uuid4 NULL | Self-FK; set when this row was produced by recreate |
| `chain_depth` | int 0..16 | `predecessor.chain_depth + 1`; rejected at >16 (R4) |
| `created_at`, `updated_at` | RFC3339 UTC | |

### LaunchCommandProfile (YAML on disk)

```yaml
name: claude-master
command: ["claude", "--model", "opus", "--system-prompt-file", "master.md"]
env:
  ANTHROPIC_LOG: warn
working_dir: /workspace
```

- `name`: string, unique across all profiles.
- `command`: list[str], argv-shape (R9); not interpolated by a shell at any point.
- `env`: optional map[str, str].
- `working_dir`: optional string; passed via `cd <shlex-quoted> &&` only when needed.

### ManagedTemplate (in-process Python data + YAML overrides)

```python
@dataclass
class ManagedTemplate:
    name: str
    panes: list[TemplatePane]

@dataclass
class TemplatePane:
    role: str
    capability: str
    label_pattern: str               # supports {ordinal} substitution
    default_launch_command_ref: str | None
```

- Two built-ins ship in code: `1m+2s` (3 panes), `2m+2s` (4 panes).
- Operator overrides live in `~/.config/opensoft/agenttower/managed_templates/*.yaml`; same schema; user file with same `name` wins.

### LifecycleEvent (FEAT-008 JSONL)

| Field | Type | Notes |
|---|---|---|
| `event_id` | uuid4 | |
| `timestamp` | RFC3339 UTC | |
| `event_type` | enum | From R11's event catalog |
| `layout_id` | uuid4 NULL | Present for layout-scoped events |
| `pane_id` | uuid4 NULL | Present for pane-scoped events |
| `actor` | enum | `operator` \| `daemon` (operator for explicit requests; daemon for sweep / recovery / scan reactions) |
| `payload` | object | Event-type-specific (see contracts) |

---

## State transitions

Authoritative graph: see [contracts/state-machine.md](./contracts/state-machine.md). One-line summary here:

```text
creating ─► ready ─► degraded ─► removed
   │           │         │
   │           ▼         ▼
   ▼        removed    failed ─► removed
degraded ────┐
   │         │
   ▼         ▼
failed ──► removed   (terminal)
```

- `degraded → ready` is **disallowed** in MVP; recovery from `degraded` is via `recreate` (new record with `predecessor_id`).
- `removed` is terminal.
- `promoted_from_adopted` is reserved; the state machine refuses it with `not_implemented`.

---

## Validation rules

- `label` MUST be non-empty and match the template's `label_pattern` (after `{ordinal}` substitution).
- `pending_marker_token` MUST be `NULL` whenever `state ≠ 'creating'`.
- `predecessor_id`, if non-NULL, MUST reference a `managed_pane` in state `removed` or `failed` (validated at insert).
- `chain_depth` MUST equal `predecessor.chain_depth + 1` when `predecessor_id` is non-NULL, else `0`.
- `tmux_session_name + tmux_pane_index` MUST be unique among non-terminal rows (enforced by partial unique index).
- `intended_pane_count` MUST equal the template's `len(panes)` at create time.
- Layout-level state MUST satisfy the aggregation rules in the ManagedLayout lifecycle note above; computed and persisted on each pane state transition.

---

## Concurrency

- The per-container `threading.Lock` (research §R2; matches the FEAT-009 `agents/mutex.py` lock-map pattern — AgentTower's daemon is threaded, not asyncio) serializes all SQLite writes for a given `container_id`'s managed_layout / managed_pane rows.
- Cross-container writes proceed in parallel; SQLite WAL mode (already enabled by FEAT-001) handles cross-container interleaving.
- Reads (list / detail) do **not** take the lock; they run inside a read transaction.
- The recovery path (boot reconcile) holds **all** per-container locks for the duration of reconcile; it runs before the socket starts accepting requests so this is exclusive.

---

## Migration & rollout

- Single forward migration: `00NN_managed_sessions.sql` (DDL above).
- No down-migration in MVP — the constitution and prior FEATs do not provide one. Rolling back the feature means leaving the empty tables in place (they have no FKs *out* of existing tables, so they do not block other operations).
- Schema version bump in the existing `schema_version` table.
