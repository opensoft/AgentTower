# Contract: Persisted UX State (`ux-state.json`)

**Purpose**: Document the on-disk JSON schema for the single app-persisted file that holds Workspace Selection state per FR-069, FR-070, FR-076, FR-077, FR-078, FR-061a. This is the **only** file the app writes; daemon-owned domain data is never persisted (per FR-005, FR-069).

**File location** (per R-06 + FR-061a):

| OS | Path |
|---|---|
| Linux | `$XDG_DATA_HOME/agenttower-control-panel/ux-state.json` (typically `~/.local/share/agenttower-control-panel/ux-state.json`) |
| macOS | `~/Library/Application Support/agenttower-control-panel/ux-state.json` |
| Windows | `%LOCALAPPDATA%\agenttower-control-panel\ux-state.json` |

**Write discipline** (per R-05 + R-21):
- Atomic: write to `ux-state.json.tmp`, fsync, rename to `ux-state.json`.
- Debounced 250 ms after any UX-state change.
- Immediate flush on FR-082 window close (with a 500 ms cap before close proceeds anyway).
- Forward-only schema migrations applied on read (per R-21).
- File permissions: inherited from the OS-user app-data directory (FR-061a).

## Top-level shape

```json
{
  "$schema": "https://opensoft.one/agenttower/control-panel/ux-state.schema.json",
  "schema_version": 1,
  "last_written_by": {
    "app_major": 1,
    "contract_major": 1
  },
  "ux_state": { /* see §1 */ }
}
```

- `schema_version` (int, required) — currently `1`. Forward-only migrations apply per R-21.
- `last_written_by.app_major` (int, required) — the app's major version when the file was last written.
- `last_written_by.contract_major` (int, required) — the `app_contract_version` major when the file was last written. Used by FR-070's compatible-launch check.

## §1 `ux_state` object

```json
{
  "window_geometry": {
    "x": 100.0, "y": 100.0,
    "width": 1280.0, "height": 800.0,
    "maximized": false
  },
  "theme_mode": "system",
  "density_mode": "comfortable",
  "notifications_grouping_enabled": true,
  "os_native_notifications_enabled": false,
  "last_active_workspace": "agent_ops",
  "last_active_sub_view_per_workspace": {
    "agent_ops": "dashboard",
    "project_specs": "projects",
    "testing_demo": "available_validation"
  },
  "last_active_project_id": "proj_01H8Z3K4ABCDEF",
  "list_sort_filter_global": {
    "agent_ops/agents": {
      "sort_field": "last_activity_at",
      "sort_direction": "desc",
      "filters": { "state": ["active"] }
    },
    "agent_ops/queue": {
      "sort_field": "created_at",
      "sort_direction": "desc",
      "filters": { "state": ["blocked", "queued"] }
    }
  },
  "list_sort_filter_per_project": {
    "proj_01H8Z3K4ABCDEF": {
      "project_specs/drift": {
        "sort_field": "severity",
        "sort_direction": "desc",
        "filters": { "status": ["new", "review_needed", "confirmed"] }
      },
      "testing_demo/runs": {
        "sort_field": "started_at",
        "sort_direction": "desc",
        "filters": { "state": ["completed"], "result": ["fail", "error"] }
      }
    }
  },
  "settings": {
    "daemon_socket_path": "/run/user/1000/agenttower/agenttowerd.sock",
    "theme": "system",
    "density": "comfortable",
    "notifications_grouping": true,
    "os_native_notifications": false
  },
  "onboarding_milestone_completion": {
    "daemon_reachable": true,
    "bench_container_check": true,
    "pane_discovery_check": true,
    "first_pane_adoption": true,
    "first_agent_registration": true,
    "first_log_attachment": false,
    "first_direct_send": false,
    "first_route_creation": false
  }
}
```

### Field-by-field reference

| Field | Type | Default on fresh install | FR ref |
|---|---|---|---|
| `window_geometry.x` / `.y` | `number` (logical px) | OS-default-centered | FR-069 |
| `window_geometry.width` / `.height` | `number` (logical px) | 1280 × 800 | FR-069 |
| `window_geometry.maximized` | `boolean` | `false` | FR-069 |
| `theme_mode` | enum `"light"` \| `"dark"` \| `"system"` | `"system"` (per R-15) | FR-009 |
| `density_mode` | enum `"comfortable"` \| `"compact"` | `"comfortable"` | FR-009 |
| `notifications_grouping_enabled` | `boolean` | `true` (per FR-057) | FR-057 |
| `os_native_notifications_enabled` | `boolean` | `false` (per FR-058 opt-in) | FR-058 |
| `last_active_workspace` | enum `"agent_ops"` \| `"project_specs"` \| `"testing_demo"` \| `"settings"` | `"agent_ops"` | FR-006, FR-069 |
| `last_active_sub_view_per_workspace` | object: workspace → sub-view id string | `{ "agent_ops": "dashboard" }` | FR-011, FR-023, FR-046, FR-069 |
| `last_active_project_id` | string \| `null` | `null` (first-launch: onboarding) | FR-076 |
| `list_sort_filter_global` | object: viewId → `ListSortFilterState` | `{}` | FR-078 |
| `list_sort_filter_per_project` | object: projectId → viewId → `ListSortFilterState` | `{}` | FR-078 |
| `settings.daemon_socket_path` | string | OS-default discovery result | FR-001, FR-009 |
| `settings.theme` | mirrors `theme_mode` | mirrors default | FR-009 |
| `settings.density` | mirrors `density_mode` | mirrors default | FR-009 |
| `settings.notifications_grouping` | mirrors `notifications_grouping_enabled` | mirrors default | FR-009, FR-057 |
| `settings.os_native_notifications` | mirrors `os_native_notifications_enabled` | mirrors default | FR-009, FR-058 |
| `onboarding_milestone_completion` | object: milestone → `boolean` | all `false` | FR-010 |

### `ListSortFilterState` shape

```json
{
  "sort_field": "<view-specific column id>",
  "sort_direction": "asc" | "desc",
  "filters": { /* view-specific, typed-dynamic, deserialized via view registry */ }
}
```

The per-view filter schema lives in the view registry at `apps/control_panel/lib/features/<workspace>/<view>/sort_filter_schema.dart`. The persistence layer treats `filters` as opaque `Map<String, dynamic>` and lets each view validate on deserialize. A view that rejects a persisted filter (e.g. because an enum value was removed in a daemon update) silently resets that view's filter to default and logs a single entry per FR-074.

## §2 Compatibility & migrations

### Compatible app launch (FR-070)

On read:

1. Parse `last_written_by`.
2. If `last_written_by.app_major != currentAppMajor` OR `last_written_by.contract_major != currentContractMajor`: **drop the persisted state**, write fresh defaults, and skip restoration. The operator lands on onboarding (if not previously completed) or the Dashboard per FR-070.
3. Otherwise, restore as documented in FR-069 / FR-076.

### Schema migration (R-21)

If `schema_version < currentSchemaVersion`:

1. Apply registered `Migration { fromVersion, toVersion, transform }` functions in order.
2. After all applicable migrations, `schema_version` equals `currentSchemaVersion` and the in-memory state is normalized.
3. If `schema_version > currentSchemaVersion`: treat as incompatible (same as the compatible-launch failure path).

### Corruption recovery (state-persistence.md CHK032, F19 → R-21)

If the file exists but parses as invalid JSON or fails schema validation:

1. Move the file aside to `ux-state.json.corrupt-<timestamp>` (quarantine, not delete).
2. Write fresh defaults.
3. Log a single ERROR entry per FR-074 naming the quarantine path.
4. Operator continues to onboarding / Dashboard as if fresh-install.

### Cross-user isolation (FR-061a)

Each OS user's app-data directory is independent. The app NEVER reads from another OS user's directory and the diagnostics bundle (FR-074) NEVER includes files outside the current OS user's app-data path.

## §3 What MUST NOT appear in `ux-state.json`

The following MUST NEVER be written to this file (FR-003, FR-005, FR-069):

- **Daemon session token** — held in process memory only; lost on app exit.
- **Any daemon-owned entity** — Project, Adopted Agent, Master Summary, Pane, Feature/Change Status, Handoff, Helper Policy / Snapshot, Drift Signal, Validation Entrypoint, Validation Run, Demo Readiness, Attention Item, Notification, Operator History Entry, Container, Queue Row, Route, Event.
- **Handoff drafts that are pre-`submitted`** — these live in app memory only; a draft lost on app close is intentionally non-recoverable per FR-072(a). Once submitted, the handoff is daemon-owned and follows the normal daemon-persisted lifecycle.
- **Operator-typed prompt content** or other ephemeral keystroke buffers — not persisted.

## §4 Settings doctor & test surface

The Settings doctor (FR-009) includes a check that:

- `ux-state.json` is readable and parseable.
- `ux-state.json.tmp` is NOT present (a stale `.tmp` indicates a crashed write attempt; doctor reports a warning).
- `schema_version` matches the app's current version.

The doctor output is included verbatim in the FR-074 diagnostics bundle.

Unit tests for the persistence layer live at `apps/control_panel/test/unit/persistence_test.dart` and exercise:

- Fresh-install defaults.
- Schema migration `v1 → vN` paths (one per shipped migration).
- Compatible-launch happy path.
- Major-mismatch drop-and-reset.
- Atomic write + crash-mid-write recovery (using an in-memory file backend).
- Corruption quarantine.
- Per-view filter validation rejecting unknown enum values.
