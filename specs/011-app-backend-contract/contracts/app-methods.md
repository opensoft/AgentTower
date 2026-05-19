# Contract: `app.*` Method Surface

**Feature**: FEAT-011 — Local App Backend Contract
**App contract version at FEAT-011 ship**: `1.0`

Every `app.*` method exchanges newline-delimited JSON over the existing Unix socket (FR-001). Request lines are `{method, params, app_session_token?}`; response lines are one of the two envelopes defined by [FR-033 / FR-034 / FR-034a](./error-codes.md).

Every response carries `app_contract_version` (FR-033). Every response is either:

```json
{"ok": true,  "app_contract_version": "1.0", "result": { ... }}
```

or

```json
{"ok": false, "app_contract_version": "1.0", "error": {"code": "<closed_set>", "message": "<prose>", "details": { ... }}}
```

Where `details` is always an object (possibly empty `{}`).

**Host-only gate** (FR-042): every `app.*` call from a bench-container peer is rejected at the dispatcher with `error.code == "host_only"`. This applies to `app.preflight` and `app.hello` too.

**Session gate** (FR-007): every method except `app.preflight` and `app.hello` requires a valid `app_session_token`. Missing → `app_session_required`. Stale/invalid → `app_session_expired`.

**Payload size gate** (FR-003a): every `app.*` request is bounded at **1 MiB per NDJSON line**. Overflow is rejected with `payload_too_large` (`details = {size_limit_bytes: 1048576, actual_size_bytes}`) before any handler executes — it is therefore a possible failure code for every method below (including `app.preflight` and `app.hello`), even though the per-method failure-code lists omit it for brevity. Responses are similarly bounded at **8 MiB per NDJSON line** as a daemon-side invariant guarded by the FR-020a pagination cap.

**Unknown-method gate** (FR-034b): any method name in the `app.*` namespace that the daemon does not implement at its current minor returns `unknown_method` with `details == {}`, regardless of cause (typo, future-minor method, nonexistent name). The daemon MUST NOT mutate state on this path. Clients differentiate future-minor methods by reading `capability_flags` from `app.hello` (FR-039) before invoking optional methods. Method names outside the `app.*` namespace are handled by the legacy FEAT-002 dispatcher and are not subject to this rule.

**Cursor opacity** (FR-020b): `cursor_next` is opaque to clients, ≤ 512 characters, daemon-chosen encoding. Clients pass it back verbatim. Malformed, oversized, or order/filter-mismatched cursors → `validation_failed.details.field == "cursor_next"`.

The method list below is the **complete v1.0 surface** (30 methods). All methods are required at v1.0; `capability_flags = {}`.

---

## Bootstrap

### `app.preflight`

Lightweight diagnostic. Does **not** require a session token. Safe to call before `app.hello`.

**Request params**: none required; ignored if present.

**Success result**:
```json
{
  "socket_reachable": true,
  "daemon_reachable": true,
  "code": "ok"
}
```

**Failure codes**: `host_only`, `socket_permission_denied`, `daemon_unavailable`, `socket_missing` (the last two are returned as success-envelope `code` rather than failure because the daemon needs to be reachable to respond; an actual connect failure surfaces as an OS-level error in the client). The success-envelope `code` field is one of `{ok, daemon_unavailable, socket_missing, socket_permission_denied}` per FR-011.

### `app.hello`

Handshake; issues a session.

**Request params**:
```json
{
  "client_id": "<optional string, ≤128 chars>",
  "client_version": "<optional string, ≤64 chars>",
  "client_app_contract_major": <int, default 1>
}
```

**Success result**:
```json
{
  "app_session_token": "<uuid v4 hex, 36 chars>",
  "app_session_id": <int ≥ 1>,
  "daemon_version": "<str>",
  "schema_version": <int>,
  "app_contract_version": "1.0",
  "supported_minor_range": {"min": "1.0", "max": "1.0"},
  "host_user_id": "<numeric UID as str>",
  "capability_flags": {},
  "state": "ok"
}
```

**Failure codes**: `host_only`, `app_contract_major_unsupported`, `internal_error`. On `app_contract_major_unsupported`, `details = {daemon_app_contract_version, client_app_contract_major}` and no session is issued (FR-036).

---

## Readiness & Dashboard

### `app.readiness`

Subsystem-level health check. Side-effect-free (FR-045).

**Request params**: none required.

**Success result**:
```json
{
  "state": "ready | degraded | unavailable",
  "subsystems": [
    {"name": "docker",                  "status": "ok|degraded|unavailable", "reason": "", "hint": null},
    {"name": "tmux_discovery",          "status": "...", "reason": "", "hint": null},
    {"name": "sqlite",                  "status": "...", "reason": "", "hint": null},
    {"name": "jsonl",                   "status": "...", "reason": "", "hint": null},
    {"name": "routing_worker",          "status": "...", "reason": "", "hint": null},
    {"name": "log_attachment_workers",  "status": "...", "reason": "", "hint": null}
  ],
  "hints": [
    {"code": "<from hint code closed set>", "severity": "info|warning|action_required", "message": "<short prose>", "target": {"kind": "container|pane|agent|route|...", "id": "..."}}
  ]
}
```

`hints` is always present, possibly `[]` (FR-014a).

**Failure codes**: `app_session_required`, `app_session_expired`, `host_only`, `internal_error`.

### `app.dashboard`

Aggregate counts + recents + hints. Side-effect-free (FR-045). Best-effort consistent, no global lock (FR-018).

**Request params**:
```json
{"recent_limit": <int, 1..50, default 10>}
```

**Success result**:
```json
{
  "counts": {
    "containers":      {"active": <int>, "inactive": <int>, "degraded_scan": <int>},
    "panes":           {"total": <int>, "registered": <int>, "unregistered": <int>},
    "agents":          {"total": <int>, "by_role": {"master": <int>, "slave": <int>, "swarm": <int>, "test-runner": <int>, "shell": <int>, "unknown": <int>}},
    "log_attachments": {"active": <int>, "degraded": <int>, "none": <int>},
    "events":          {"total": <int>},
    "queue":           {"pending": <int>, "in_flight": <int>, "blocked": <int>, "expired": <int>, "cancelled": <int>, "delivered": <int>},
    "routes":          {"enabled": <int>, "disabled": <int>}
  },
  "recent": {
    "events":  [ <EventViewModel-compact>, ... ],
    "queue":   [ <QueueViewModel-compact>, ... ],
    "routes":  [ <RouteViewModel-compact>, ... ]
  },
  "hints": [ <Hint>, ... ]
}
```

Compact rows include `id`, `timestamp`, `type`, key labels, and `summary` (FR-017). Default `recent_limit = 10`, capped `[1, 50]`. Out of bounds → `validation_failed.details = {field: "recent_limit", reason: "out of bounds [1,50]"}`.

**Failure codes**: `app_session_required`, `app_session_expired`, `host_only`, `validation_failed`, `internal_error`.

---

## Read Surfaces

The seven entities `container`, `pane`, `agent`, `log_attachment`, `event`, `queue`, `route` each have a `.list` and a `.detail` method. Listing is paginated (FR-020, FR-020a); detail is by `id`.

### `app.<entity>.list`

**Request params**:
```json
{
  "limit": <int, 1..200, default 50>,
  "cursor_next": "<opaque str from prior page>",
  "order_by": "<closed-set field name per surface>",
  "filters": { ... per-entity ... }
}
```

Pagination contract (FR-020, FR-020a):
- `limit` is bounded `[1, 200]`. Out of bounds → `validation_failed.details = {field: "limit", reason}`.
- `cursor_next` is opaque. Reusing it with a different `order_by` or `filters` → `validation_failed.details = {field: "cursor_next", reason}`.
- Each response includes the next `cursor_next` (string) or omits it when no more pages remain.

**Success result**:
```json
{
  "rows": [ <EntityViewModel>, ... ],
  "total":          <int> | null,
  "total_estimate": <int> | null,
  "cursor_next":    "<str>" | null,
  "ordering":       "<applied order_by name>"
}
```

Exactly one of `total` / `total_estimate` is non-null per response.

**Per-entity defaults and filters**:

| Entity | Default order | Filter fields (FR-024) |
|---|---|---|
| `container` | `name ASC` | `state ∈ {active, inactive, degraded_scan}` |
| `pane` | `(container_name, session_name, window_index, pane_index) ASC` | `container_id`, `registered: bool` |
| `agent` | `(role_priority, registered_at) ASC` | `role`, `capability`, `container_id`, `log_attached: bool` |
| `log_attachment` | `last_output_at DESC` | `agent_id`, `status` |
| `event` | `event_id DESC` | `event_type`, `origin`, `agent_id`, `since`, `until` |
| `queue` | `(state_priority, created_at) ASC` | `state`, `origin`, `route_id`, `target_agent_id`, `since`, `until` |
| `route` | `(created_at, route_id) ASC` | `enabled: bool` |

`since` / `until` are unix-ms ints. `since > until` → `validation_failed.details = {field: "since", reason: "after until"}`.

**Failure codes**: `app_session_required`, `app_session_expired`, `host_only`, `validation_failed`, `internal_error`.

### `app.<entity>.detail`

**Request params**:
```json
{"<entity>_id": "<str>"}
```

(e.g., `container_id`, `pane_id`, `agent_id`, `message_id` for queue, `route_id`, `event_id` for event.)

**Success result**: the full `<Entity>ViewModel` for the row, wrapped in `result`.

**Failure codes**: `app_session_required`, `app_session_expired`, `host_only`, `not_found` (entity-specific: `pane_not_found`, `agent_not_found`, `route_not_found`, `queue_message_not_found` — see error-codes.md), `validation_failed`, `internal_error`.

---

## Adopt Mutation

### `app.agent.register_from_pane`

The only path the app uses to promote a discovered tmux pane to a registered agent (FR-025..FR-028). Reuses FEAT-006 `register-self` validation and persistence.

**Request params**:
```json
{
  "container_id":     "<str>",
  "tmux_socket":      "<str>",
  "session_name":     "<str>",
  "window_index":     <int>,
  "pane_index":       <int>,
  "pane_id":          "<str>",
  "role":             "<from agent role closed set>",
  "capability":       "<str, ≤128 chars>",
  "label":            "<str, ≤128 chars>",
  "project_path":     "<optional str>",
  "parent_agent_id":  "<optional str>",
  "attach_log":       <optional bool, default false>
}
```

**Success result**: full `AgentViewModel` for the new agent.

**Failure codes**: `app_session_required`, `app_session_expired`, `host_only`, `validation_failed` (with `details.field`, e.g., `role`, `label`, `capability`), `pane_not_found` (with `details.pane_id`), `pane_already_registered` (with `details.agent_id` = the existing agent), `internal_error`.

Audit: emits an `agent_registered` JSONL row with `origin == "app"` and `app_session_id` set (FR-044).

---

## Operator Mutations

All mutation responses contain the full post-mutation state of the affected entity (FR-030). Last-write-wins on entity updates; no `expected_version` / `etag` (FR-030a).

### `app.agent.update`

**Request params**:
```json
{
  "agent_id":      "<str>",
  "role":          "<optional, from role closed set>",
  "capability":    "<optional non-empty str>",
  "label":         "<optional str — empty string clears>",
  "project_path":  "<optional str — empty string clears>"
}
```

Field semantics (FR-029a):
- **Absent field** → no change.
- **Empty string on `project_path` or `label`** → clears the field (sets to `null` / `""` per existing FEAT-006 semantics).
- **Empty string on `role`** → `validation_failed` with `details = {field: "role", reason: "field is not clearable; provide a valid value from the role closed set"}`.
- **Empty string on `capability`** → `validation_failed` with `details = {field: "capability", reason: "field is not clearable; provide a non-empty value"}`.
- **`role` not in the closed set** → `validation_failed` with `details.field == "role"`.

**Success result**: full post-update `AgentViewModel`.

**Failure codes**: `app_session_required`, `app_session_expired`, `host_only`, `validation_failed`, `agent_not_found`, `payload_too_large`, `internal_error`. Notably **never** `stale_object` (FR-030a).

### `app.log.attach` / `app.log.detach`

**Request params**: `{"agent_id": "<str>"}`

**Success result**: full post-mutation `AgentViewModel` (with `log_attached` reflecting the new state).

**Failure codes**:
- `app.log.attach`: `app_session_required`, `app_session_expired`, `host_only`, `agent_not_found`, `container_inactive` (with `details.container_id`), `log_attach_blocked` (with `details.agent_id` and `details.reason`), `internal_error`.
- `app.log.detach` (FR-029b): `app_session_required`, `app_session_expired`, `host_only`, `agent_not_found`, `internal_error`. `app.log.detach` is **success-idempotent**: detaching a never-attached log returns a success envelope carrying the agent's `AgentViewModel` with `log_attached: false`. No closed-set error code is emitted for "already detached" — the response is structurally identical to a successful detach of a previously-attached log.

### `app.send_input`

Routes a structured payload to a target agent via the FEAT-009 queue. Respects the FEAT-009 permission gate and global kill switch (FR-031).

**Request params**:
```json
{
  "target_agent_id":  "<str>",
  "payload":          { ... structured ... },
  "idempotency_key":  "<optional str, ≤256 chars>"
}
```

**Success result**:
```json
{
  "message_id":     "<str>",
  "state":          "<queue state>",
  "deduplicated":   <bool>
}
```

On a duplicate `idempotency_key` retry within the session, returns the original `message_id` and `deduplicated: true` (FR-031a). No second queue row; no duplicate audit row.

**Failure codes**: `app_session_required`, `app_session_expired`, `host_only`, `validation_failed`, `agent_not_found`, `routing_disabled`, `permission_denied`, `internal_error`.

### `app.queue.approve` / `app.queue.delay` / `app.queue.cancel`

**Request params**: `{"message_id": "<str>", ...action-specific...}`

- `approve`: `{message_id}` only.
- `delay`: `{message_id, delay_ms: <int>}` — delay relative to now.
- `cancel`: `{message_id, reason?: <str>}`.

**Success result**: full post-mutation `QueueViewModel`.

**Failure codes**: `app_session_required`, `app_session_expired`, `host_only`, `validation_failed`, `queue_message_not_found`, `stale_object` (terminal-state guard — FR-030a allows this code only on queue lifecycle), `routing_disabled`, `internal_error`.

### `app.route.add` / `app.route.remove` / `app.route.update`

**Request params**:

- `add`: full FEAT-010 route definition (`source_scope`, `template`, `target`).
- `remove`: `{route_id}`.
- `update`: `{route_id, enabled}` — enable/disable only (FR-029, FR-032). Other fields rejected with `validation_failed`.

**Success result**: full post-mutation `RouteViewModel`.

**Failure codes**: `app_session_required`, `app_session_expired`, `host_only`, `validation_failed`, `route_not_found`, `internal_error`.

Audit: each emits the matching FEAT-010 audit event (`route_created`/`route_updated`/`route_deleted`) with `origin == "app"`.

---

## Scans

### `app.scan.containers` / `app.scan.panes`

Trigger a FEAT-003 / FEAT-004 discovery scan.

**Request params**:
```json
{"wait": <bool, default true>}
```

**Success result when `wait == true` and scan completes within 30 s** (FR-030b):
```json
{
  "scan_id": "<str>",
  "state": "completed",
  "result": { ... post-scan summary ... }
}
```

**Success result when `wait == false`**:
```json
{
  "scan_id": "<str>",
  "state": "running"
}
```

**Failure on `wait == true` timeout** (FR-030b):
```json
{"ok": false, "app_contract_version": "1.0",
 "error": {"code": "scan_timeout", "message": "...", "details": {"scan_id": "<str>"}}}
```

The scan continues server-side; the same `scan_id` is reachable via `app.scan.status` once terminal.

**Failure codes**: `app_session_required`, `app_session_expired`, `host_only`, `docker_unavailable`, `tmux_unavailable`, `scan_timeout`, `internal_error`.

### `app.scan.status`

Poll a previously-issued scan (FR-030c).

**Request params**: `{"scan_id": "<str>"}`

**Success result**:
```json
{
  "state":         "running | completed | failed",
  "scan_kind":     "containers | panes",
  "started_at":    <int ms>,
  "completed_at":  <int ms> | null,
  "result":        { ... } | null
}
```

`completed_at` and `result` are non-null exactly when `state ∈ {completed, failed}`. The `expired` state is intentionally absent from the v1.0 closed set; a future minor may introduce it with a defined wall-clock trigger.

**Failure codes**: `app_session_required`, `app_session_expired`, `host_only`, `scan_not_found` (with `details.scan_id`), `internal_error`.

---

## Method Count

30 methods total at v1.0:
- 2 bootstrap (preflight, hello)
- 2 dashboard surfaces (readiness, dashboard)
- 14 read surfaces (7 entities × {list, detail})
- 1 adopt mutation
- 11 operator mutations (agent.update, log.attach, log.detach, send_input, queue × 3, route × 3, scan × 3)

All required at v1.0. `capability_flags = {}` reflects "every method is mandatory" (FR-039).
