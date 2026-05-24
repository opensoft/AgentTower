# Contract: Closed-Set Error Codes (FEAT-013 additions)

**Feature**: 013-managed-session-lifecycle
**Authority**: spec.md §FR-013/016/018; research.md.

This file lists the **new** closed-set error codes added by FEAT-013, extending the FEAT-011 27-entry registry. Each entry follows the FEAT-011 `(code, message-shape, details schema)` convention.

The full closed set for an `app.managed_*` or legacy `managed.*` response continues to include the prior FEAT-011 codes (`validation_failed`, `host_only`, `not_implemented`, `internal_error`, `malformed_request`, etc.) — those are reused unchanged.

---

## New codes

### `managed_template_not_found`

- **When**: `managed.layout.create` is called with a `template_name` that does not resolve via the built-in registry or the operator YAML override directory.
- **Details schema**:
  ```json
  {"template_name": "string", "known_templates": ["string", "..."]}
  ```
- **Operator action**: Verify the template name or define it in `~/.config/opensoft/agenttower/managed_templates/`.
- **Resolution order** (per FR-024): operator override file with the same `name` wins over the built-in default; if neither resolves, this error fires.

### `managed_launch_command_not_found`

- **When**: A `launch_command_overrides` entry or a template's `default_launch_command_ref` references a profile that does not exist in `~/.config/opensoft/agenttower/launch_commands/`.
- **Details schema**:
  ```json
  {"profile_name": "string", "known_profiles": ["string", "..."]}
  ```
- **Resolution order** (per FR-024): operator-supplied profile with the same `name` overrides any built-in default before this error is raised.

### `managed_session_name_conflict` (FR-016, Q6)

- **When**: `managed.layout.create` requests a `tmux_session_name` that already exists in the target container.
- **Details schema**:
  ```json
  {"container_id": "string", "tmux_session_name": "string"}
  ```
- **Operator action**: Choose a different `tmux_session_name` or kill the existing tmux session first.
- **Note**: This is a hard rejection — no silent suffixing or session reuse (per Q6 decision).

### `managed_layout_not_found`

- **When**: A layout-scoped method (`managed.layout.detail`, `managed.pane.list?layout_id=`, etc.) references an unknown `layout_id`.
- **Details schema**:
  ```json
  {"layout_id": "string"}
  ```

### `managed_pane_not_found`

- **When**: A pane-scoped method references an unknown `pane_id` or `predecessor_pane_id`.
- **Details schema**:
  ```json
  {"pane_id": "string"}
  ```

### `managed_pane_protected_adopted` (FR-012)

- **When**: A destructive `managed.pane.*` action targets a pane id that exists in the FEAT-006 agent registry but **not** in `managed_pane` — i.e., it was adopted, not created by AgentTower.
- **Details schema**:
  ```json
  {"agent_id": "string", "is_adopted": true}
  ```
- **Operator action**: Use the FEAT-006 adopt/unadopt path; or wait for the later promote-from-adopted feature.

### `managed_pane_illegal_transition`

- **When**: A request would trigger a transition not in the state-machine graph (e.g., `remove` while `creating`).
- **Details schema**:
  ```json
  {"pane_id": "string", "current_state": "string", "requested_action": "string"}
  ```

### `managed_pane_illegal_recreate_source`

- **When**: `managed.pane.recreate` references a `predecessor_pane_id` whose state is not `removed` or `failed`.
- **Details schema**:
  ```json
  {"predecessor_pane_id": "string", "current_state": "string"}
  ```

### `managed_pane_recreate_chain_too_deep` (R4)

- **When**: Predecessor's `chain_depth >= 15` (a new record would be at depth 16, which is the configured bound).
- **Details schema**:
  ```json
  {"predecessor_pane_id": "string", "predecessor_chain_depth": 15, "limit": 16}
  ```
- **Operator action**: Start a fresh layout rather than continuing the recreate chain.

---

## Reused codes (no change)

These FEAT-011 codes are also returned by FEAT-013 paths and retain their existing shapes:

- `validation_failed` — field-shape violations; details include `field`, `reason`.
- `host_only` — bench-container peer targeted a host-only method or a foreign container.
- `not_implemented` — used by the `promote_from_adopted` stub; details include `reserved_since: "FEAT-013"`.
- `internal_error` — unhandled exception; details are the redacted exception class name.
- `malformed_request` — NDJSON framing or UTF-8 violation before dispatch.
- `container_not_found` — FEAT-003 code; returned when `container_id` is unknown.
- `payload_too_large` — FEAT-011 code; bounds inherit from FEAT-011 FR-003a.

---

## Code count

FEAT-011 baseline: 27 codes.
FEAT-013 additions: **9** new codes (listed above).
FEAT-013 total in registry: **36** codes.

This is an additive evolution within `app_contract_version = "1.0"`; clients that don't recognize the new codes still see the generic `code`/`message`/`details` envelope and can surface them to the operator without protocol changes.
