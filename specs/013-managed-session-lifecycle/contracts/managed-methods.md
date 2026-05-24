# Contract: Managed-Session API Methods

**Feature**: 013-managed-session-lifecycle
**Authority**: spec.md §FR-001/002/004/005/008/010/011/012/015/016/017/018/019/020/021; research.md.

This contract defines the wire shapes for the FEAT-013 method set in **two parallel namespaces**:

- **Legacy CLI namespace** — `managed.*` methods on the existing FEAT-002 socket dispatcher; reachable from host CLI and bench-container thin clients. Thin-client callers may only target their own container (peer-detected; cross-container returns `host_only`).
- **App contract namespace** — `app.managed_*` methods on the FEAT-011 host-only dispatcher; same JSON envelope as the rest of `app.*`.

Both namespaces dispatch into the same `managed_sessions.service` entry points. The shapes below are identical between namespaces; method **names** differ as noted at the top of each method block.

All examples use NDJSON over the local Unix socket. Field types follow FEAT-011 conventions: `state_priority`, `role_priority`, pagination defaults, and the standard envelope.

---

## Envelope

Inherits FEAT-011 verbatim:

- Success: `{"ok": true, "app_contract_version": "1.0", "result": {...}}`
- Failure: `{"ok": true, "app_contract_version": "1.0", "error": {"code": "<closed-set>", "message": "...", "details": {...}}}`

(Note: legacy `managed.*` methods use FEAT-002's existing envelope, which is the same shape minus `app_contract_version`.)

---

## Methods

### M1. `managed.layout.create` / `app.managed_layout_create`

Create a managed layout in a bench container.

**Request**:
```json
{
  "method": "managed.layout.create",
  "container_id": "bench-abc",
  "template_name": "1m+2s",
  "tmux_session_name": "session-alpha",
  "launch_command_overrides": {
      "master:m1": "claude-master",
      "slave:s1":  "claude-worker",
      "slave:s2":  "claude-worker"
  },
  "idempotency_key": "operator-clicked-create-12345"
}
```

- `container_id` (string, required) — FEAT-003 container id.
- `template_name` (string, required) — must resolve via the template registry (built-in or YAML override).
- `tmux_session_name` (string, required) — must not exist in the target container; otherwise `managed_session_name_conflict` (FR-016).
- `launch_command_overrides` (object, optional) — keyed by `"<role>:<label>"`; values reference `LaunchCommandProfile.name`. Missing entries fall back to the template's `default_launch_command_ref`. Unresolved profile names return `managed_launch_command_not_found`.
- `idempotency_key` (string, optional) — see R10. Scope is `(container_id, idempotency_key)`.

**Response (success)**:
```json
{
  "ok": true,
  "result": {
    "layout_id": "01HZ...",
    "state": "creating",
    "intended_pane_count": 3,
    "panes": [
        {"pane_id": "01HZ-p1", "role": "master", "label": "m1", "state": "creating"},
        {"pane_id": "01HZ-p2", "role": "slave",  "label": "s1", "state": "creating"},
        {"pane_id": "01HZ-p3", "role": "slave",  "label": "s2", "state": "creating"}
    ]
  }
}
```

**Behavior**:

- Acquires per-container serializer (FR-019). FIFO ordering; no timeout.
- Returns **after** the layout row + all pane rows are inserted in SQLite and the pending-managed markers are set. The actual tmux spawn + registration runs in a background task; the operator polls via `managed.layout.detail` or subscribes to lifecycle events.
- Idempotency replay: a repeated request with the same `(container_id, idempotency_key)` returns the current row state without restarting the pipeline.

**Errors**:
- `managed_template_not_found`
- `managed_launch_command_not_found`
- `managed_session_name_conflict` (FR-016)
- `container_not_found` (existing FEAT-003 code)
- `host_only` (thin-client peer targeting a foreign container)
- `validation_failed` (any field shape violation)

### M2. `managed.layout.list` / `app.managed_layout_list`

Paginated list of managed layouts.

**Request**:
```json
{"method": "managed.layout.list", "container_id": "bench-abc", "limit": 50, "after": null}
```

`container_id` optional — when absent, all containers. `limit` defaults to 50, capped at 200 (FR-020a inherited from FEAT-011).

**Response**:
```json
{"ok": true, "result": {"items": [{"layout_id": "...", "container_id": "...", "template_name": "...", "state": "ready", "intended_pane_count": 3, "ready_pane_count": 3, "created_at": "..."}], "next": null}}
```

Ordering: `(state_priority ASC, created_at DESC)` — same convention as the FEAT-011 list endpoints.

### M3. `managed.layout.detail` / `app.managed_layout_detail`

Full layout view including all (non-terminal + terminal) panes.

**Request**:
```json
{"method": "managed.layout.detail", "layout_id": "01HZ...", "include_terminal_panes": false}
```

**Response**:
```json
{"ok": true, "result": {
    "layout_id": "...",
    "container_id": "...",
    "template_name": "1m+2s",
    "state": "degraded",
    "failed_stage": null,
    "panes": [
        {"pane_id": "...", "role": "master", "label": "m1", "state": "ready",
         "agent_id": "...", "tmux_session_name": "session-alpha", "tmux_pane_index": 0,
         "predecessor_id": null, "chain_depth": 0, "log_attached": true},
        {"pane_id": "...", "role": "slave", "label": "s1", "state": "degraded",
         "failed_stage": "log_attach", "agent_id": "...", "tmux_pane_index": 1,
         "predecessor_id": null, "chain_depth": 0, "log_attached": false},
        {"pane_id": "...", "role": "slave", "label": "s2", "state": "ready",
         "agent_id": "...", "tmux_pane_index": 2, "predecessor_id": null, "chain_depth": 0}
    ],
    "created_at": "...", "updated_at": "..."
}}
```

**Sample variant — recovery_reattach failure (FR-020 / SC-009)**: After a daemon restart in which one pane's tmux backing was killed externally, the detail response surfaces the recovery outcome directly — no log inspection required:

```json
{"ok": true, "result": {
    "layout_id": "...",
    "state": "failed",
    "failed_stage": "recovery_reattach",
    "panes": [
        {"pane_id": "...", "label": "m1", "state": "ready", "agent_id": "...",
         "tmux_session_name": "session-alpha", "tmux_pane_index": 0},
        {"pane_id": "...", "label": "s1", "state": "failed",
         "failed_stage": "recovery_reattach",
         "tmux_session_name": "session-alpha", "tmux_pane_index": 1,
         "agent_id": null}
    ]
}}
```

### M4. `managed.pane.list` / `app.managed_pane_list`

Same shape as M2, scoped to panes. Filters: `container_id?`, `layout_id?`, `state?` (single-value or array). Ordering: `(layout_id, tmux_pane_index)`.

### M5. `managed.pane.detail` / `app.managed_pane_detail`

Single-pane detail including the full `predecessor_id` chain (recursive, bounded at `chain_depth`).

**Request**:
```json
{"method": "managed.pane.detail", "pane_id": "01HZ-p2", "include_predecessor_chain": true}
```

**Response (snippet)**:
```json
{"ok": true, "result": {
    "pane_id": "01HZ-p2", "state": "ready", "chain_depth": 2,
    "predecessor_id": "01HZ-prev",
    "predecessor_chain": [
        {"pane_id": "01HZ-prev",  "state": "removed", "chain_depth": 1, "predecessor_id": "01HZ-prev0"},
        {"pane_id": "01HZ-prev0", "state": "failed",  "chain_depth": 0, "predecessor_id": null}
    ]
}}
```

### M6. `managed.pane.remove` / `app.managed_pane_remove`

Remove a managed pane; kills the underlying tmux pane (R6, FR-010).

**Request**:
```json
{"method": "managed.pane.remove", "pane_id": "01HZ-p2"}
```

**Response (success)**:
```json
{"ok": true, "result": {"pane_id": "01HZ-p2", "state": "removed"}}
```

**Behavior**:
- Refuses if the pane's `managed_pane` record does not exist (it is therefore adopted, not managed) — returns `managed_pane_protected_adopted` (FR-012).
- Acquires per-container serializer (FR-019).
- Issues `tmux kill-pane`. If the pane is already gone, success is still returned (idempotent).
- Cleans up routes, log attachments via the existing FEAT-007/010 paths.
- Emits `managed_pane_removed` lifecycle event (FR-015).

**Errors**:
- `managed_pane_not_found`
- `managed_pane_protected_adopted`
- `host_only` (thin-client targeting a foreign container)
- `managed_pane_illegal_transition` if the pane is in `creating` — operator must wait or use the in-progress cancel (out of scope MVP).

### M7. `managed.pane.recreate` / `app.managed_pane_recreate`

Recreate a previously-removed-or-failed managed pane. Produces a new pane row linked via `predecessor_id` (FR-011 / Q2).

**Request**:
```json
{"method": "managed.pane.recreate", "predecessor_pane_id": "01HZ-prev", "launch_command_override": "claude-worker-v2", "idempotency_key": null}
```

- `predecessor_pane_id` (string, required) — must be in `removed` or `failed`.
- `launch_command_override` (string, optional) — overrides the template/profile.
- `idempotency_key` (string, optional) — same semantics as M1.

**Response**:
```json
{"ok": true, "result": {"pane_id": "01HZ-new", "predecessor_id": "01HZ-prev", "chain_depth": 1, "state": "creating"}}
```

**Errors**:
- `managed_pane_not_found`
- `managed_pane_recreate_chain_too_deep` (R4: predecessor's `chain_depth` ≥ 15)
- `managed_pane_illegal_recreate_source` (predecessor is `ready`, `degraded`, or `creating`)
- `managed_launch_command_not_found`

### M8. `managed.pane.promote_from_adopted` / `app.managed_pane_promote_from_adopted` (STUB, FR-018)

Reserved transition. MVP behavior: always responds with `not_implemented`.

**Request**:
```json
{"method": "managed.pane.promote_from_adopted", "agent_id": "..."}
```

**Response**:
```json
{"ok": true, "error": {"code": "not_implemented", "message": "promote_from_adopted is reserved for a later feature.", "details": {"reserved_since": "FEAT-013"}}}
```

This is implemented as a service entry point that returns the error envelope; the underlying state-machine module exposes the `PROMOTE_FROM_ADOPTED` constant for tests but the transition itself is gated off.

---

## Event subscription (FR-015)

All lifecycle events flow through the existing FEAT-008 event pipeline. FEAT-013 adds the following event types (research §R11 catalog):

| Event type | Layout-scoped | Pane-scoped | Payload notes |
|---|---|---|---|
| `managed_layout_created` | ✓ | — | template_name, container_id, intended_pane_count |
| `managed_layout_state_changed` | ✓ | — | prev_state, new_state |
| `managed_pane_created` | ✓ | ✓ | role, label, tmux_session_name, tmux_pane_index |
| `managed_pane_state_changed` | ✓ | ✓ | prev_state, new_state, failed_stage? |
| `managed_pane_recreated` | ✓ | ✓ | predecessor_id, chain_depth |
| `managed_pane_removed` | ✓ | ✓ | tmux_kill_succeeded: bool |
| `managed_pane_pending_marker_set` | — | ✓ | marker_token |
| `managed_pane_pending_marker_cleared` | — | ✓ | marker_token |
| `managed_pane_launch_command_exited` | ✓ | ✓ | exit_code, elapsed_ms |
| `managed_pane_log_attach_failed` | ✓ | ✓ | reason |
| `managed_layout_recovery_reattached` | ✓ | — | reattached_pane_ids |
| `managed_layout_recovery_failed` | ✓ | — | failed_pane_ids, failed_stage |

Consumers use the existing FEAT-011 `app.event.list` / `app.event.detail` methods to retrieve them. Ordering is per-pane FIFO and per-layout FIFO; cross-pane ordering is best-effort timestamp.

---

## Bench-container thin-client peer scoping

Per research §R12:

- Every legacy `managed.*` call from a bench-container peer is checked: `request.container_id == peer.container_id`. Mismatch returns `host_only`.
- `managed.layout.list` / `managed.pane.list` from a thin-client peer are silently filtered to the peer's own container (no error; results are scoped).
- All `app.managed_*` methods are host-only via FEAT-011's existing gate.

---

## Idempotency summary

| Method | Key | Replay semantics |
|---|---|---|
| `managed.layout.create` | `idempotency_key` (optional, scoped per container) | In-flight match → return current state; completed match → return prior record verbatim |
| `managed.pane.remove` | None — operation is idempotent at the data-layer (already-removed pane returns success) | |
| `managed.pane.recreate` | `idempotency_key` (optional, scoped per container) | Same as create |
| Other methods | None — read-only | — |

---

## Versioning

FEAT-013 is additive within FEAT-011's `app_contract_version = "1.0"`. No major bump; clients that ignore unknown methods (per FEAT-011's compat rule) treat FEAT-013 as a no-op until they update. The `app.managed_*` methods are **required FEAT-013 surfaces, not optional capabilities**. They are NOT advertised in the `app.hello` response's `capability_flags`, which remains `{}` at v1.0 per FEAT-011 (`capability_flags` is reserved for gating *optional* methods in a future minor bump; required methods of any FEAT shipped at the current `app_contract_version` are discovered via the version itself, not via the flag map). FEAT-013 makes no change to `app.hello` semantics.
