# Socket-API Contracts: Agent Registration and Role Metadata

**Branch**: `006-agent-registration` | **Date**: 2026-05-07

This document is the authoritative contract for the five new
daemon socket methods FEAT-006 introduces. It supplements
`spec.md` FR-023, FR-024, FR-025, FR-026, FR-027, FR-035,
FR-038, FR-039, FR-040, and Clarifications 2026-05-07 Q1, Q3,
Q4.

The new methods reuse the FEAT-002 newline-delimited JSON
request/response framing and host-user authorization (`0600`,
host user only) verbatim (FR-023, FR-043). No new framing, no
new authorization tier, no new envelope shape.

---

## 1. Method dispatch table

The FEAT-002 dispatch table grows from seven entries (FEAT-002:
ping/status/shutdown; FEAT-003: scan_containers/list_containers;
FEAT-004: scan_panes/list_panes) to twelve. Insertion order is
preserved per the FEAT-002 stability rule; new entries are
appended:

```python
DISPATCH: dict[str, Handler] = {
    "ping":              _ping,                 # FEAT-002
    "status":            _status,               # FEAT-002
    "shutdown":          _shutdown,             # FEAT-002
    "scan_containers":   _scan_containers,      # FEAT-003
    "list_containers":   _list_containers,      # FEAT-003
    "scan_panes":        _scan_panes,           # FEAT-004
    "list_panes":        _list_panes,           # FEAT-004
    "register_agent":    _register_agent,       # FEAT-006
    "list_agents":       _list_agents,          # FEAT-006
    "set_role":          _set_role,             # FEAT-006
    "set_label":         _set_label,            # FEAT-006
    "set_capability":    _set_capability,       # FEAT-006
}
```

Unknown method names continue to return `unknown_method` per
FEAT-002.

---

## 2. Request / response envelopes

**Case-sensitivity contract** (Clarifications session 2026-05-07-continued Q2): every closed-set token (`role`, `capability`) and every lowercase-hex identifier (`agent_id`, `parent_agent_id`, `container_id`) in any request envelope is matched case-sensitively. Mixed-case inputs (`Slave`, `MASTER`, `agt_ABC...`, `ABC123def456`) MUST be rejected with `value_out_of_set`; the daemon MUST NOT normalize, lowercase, or case-fold any value before validation, lookup, or filter matching.

All envelopes use the FEAT-002 newline-delimited JSON shape:

```text
{"method":"<name>","params":{...}}\n        # request
{"ok":true,"result":{...}}\n                 # success response
{"ok":false,"error":{"code":"<code>","message":"..."}}\n  # error response
```

Request size limit: inherits FEAT-002 `request_too_large`. Field
sanitization: inherits FEAT-004 `output_malformed` for daemon-side
free-text bounds; per-field bounds defined in
`data-model.md` §8.

### 2.1 `register_agent`

**Request**

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
    "role": "slave",                  // OPTIONAL — see Q1 wire encoding
    "capability": "codex",            // OPTIONAL
    "label": "codex-01",              // OPTIONAL
    "project_path": "/workspace/acme",// OPTIONAL
    "parent_agent_id": "agt_aaa..."   // OPTIONAL — must equal stored value if present (FR-018a)
  }
}
```

**Required keys**: `container_id`, `pane_composite_key`. The
six pane composite-key sub-keys are all required when
`pane_composite_key` is present.

**Optional keys**: `role`, `capability`, `label`, `project_path`,
`parent_agent_id`. Per Clarifications Q1, the *absence* of a key
means "leave the stored value unchanged" on idempotent
re-registration. On first registration of a new pane, the daemon
applies the same default values the CLI applies (`role="unknown"`,
`capability="unknown"`, `label=""`, `project_path=""`,
`parent_agent_id=null`) so the wire contract is symmetric.

**Forbidden keys**: any key other than the eight listed above is
rejected with `bad_request`.

**Validation order** (data-model.md §7.3):

1. Closed-set field shape on present optional keys (FR-004,
   FR-005, FR-001 for parent_agent_id).
2. Free-text bounds + sanitization on `label` (FR-033) and
   `project_path` (FR-034).
3. Master-safety static check: `role == "master"` →
   `master_via_register_self_rejected` (FR-010).
4. Swarm parent shape: `role == "swarm"` AND
   `parent_agent_id` absent → `swarm_parent_required` (FR-015);
   `parent_agent_id` present AND `role` is anything other than
   `swarm` → `parent_role_mismatch` (FR-016).
5. Acquire (container_id, pane_composite_key) advisory mutex
   (FR-038).
6. SELECT existing agent for the pane composite key.
7. If existing row and `parent_agent_id` is supplied and
   differs from the stored value → `parent_immutable`
   (FR-018a).
8. If no existing row and `role == "swarm"`:
   resolve parent (FR-017) — `parent_not_found` /
   `parent_inactive` / `parent_role_invalid`.
9. Compose post-write state (only-supplied-fields-overwrite
   per Q1).
10. Recompute `effective_permissions` from final role.
11. BEGIN IMMEDIATE; INSERT or UPDATE agents row; COMMIT.
12. If creation OR if role changed: append JSONL audit row
    (Q4: `prior_role: null` on creation).
13. Release mutex; return success envelope.

**Success response**

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
    "created_at": "2026-05-07T...",
    "last_registered_at": "2026-05-07T...",
    "last_seen_at": null,
    "active": true,
    "created_or_reactivated": "created"
  }
}
```

`created_or_reactivated` ∈ `{"created", "reactivated", "updated"}`:

- `"created"` — first registration of this pane composite key.
- `"reactivated"` — pane composite key existed with `active=0`
  and was re-activated (FR-008).
- `"updated"` — pane composite key existed with `active=1`;
  this is an idempotent re-registration.

**Error responses**

Closed-set error codes for `register_agent`:

| Code | Trigger |
| ---- | ------- |
| `bad_request` | Malformed JSON / missing required key / unknown key |
| `value_out_of_set` | `role` / `capability` / `parent_agent_id` shape |
| `field_too_long` | `label` > 64 chars or `project_path` > 4096 chars |
| `project_path_invalid` | `project_path` not absolute / contains `..` / contains NUL |
| `master_via_register_self_rejected` | `role == "master"` |
| `swarm_parent_required` | `role == "swarm"` AND no `parent_agent_id` |
| `parent_role_mismatch` | `parent_agent_id` AND `role != "swarm"` |
| `parent_not_found` | swarm parent does not exist |
| `parent_inactive` | swarm parent has `active = 0` |
| `parent_role_invalid` | swarm parent has `role != "slave"` |
| `parent_immutable` | re-registration with different `parent_agent_id` (Q3) |
| `internal_error` | SQLite error / transaction rollback / agent_id collision retry exhausted |
| `schema_version_newer` | client newer than daemon (defensive; CLI usually catches this first) |

### 2.2 `list_agents`

**Request**

```json
{
  "method": "list_agents",
  "params": {
    "role": "slave",                  // OPTIONAL — string OR list of strings
    "container_id": "abc123def456",   // OPTIONAL — full or 12-char short
    "active_only": true,              // OPTIONAL — default false
    "parent_agent_id": "agt_aaa..."   // OPTIONAL
  }
}
```

**Filter rules** (FR-026):

- Filters compose with AND across keys.
- `role` accepts a string or a list of strings; multiple values
  OR within the field.
- `container_id` accepts the full container id OR a 12-char
  short id; classified server-side.
- `active_only` is a boolean; missing key defaults to `false`.
- `parent_agent_id` filters to swarm children of the named
  slave.
- Unknown filter keys → `unknown_filter`.

**Read-only contract** (FR-025):

- MUST NOT call Docker or tmux.
- MUST NOT acquire any registration mutex.
- MUST NOT update `last_seen_at`.
- Returns the latest committed SQLite state in deterministic
  order: `active DESC, container_id ASC, parent_agent_id ASC NULLS FIRST, label ASC, agent_id ASC`.

**Success response**

```json
{
  "ok": true,
  "result": {
    "filter": {
      "role": ["slave"],
      "container_id": null,
      "active_only": true,
      "parent_agent_id": null
    },
    "agents": [
      { /* full AgentRecord JSON */ },
      ...
    ]
  }
}
```

The `filter` echo in the response normalizes `role` to a list
even when the request supplied a string, and fills in nulls for
absent filters so consumers can rely on the shape.

**Error responses**

| Code | Trigger |
| ---- | ------- |
| `bad_request` | Malformed JSON |
| `unknown_filter` | Unknown key in `params` |
| `value_out_of_set` | `role` value not in FR-004 closed set |
| `internal_error` | SQLite error |
| `schema_version_newer` | client newer than daemon |

Empty result sets (e.g., `--container <id>` with no matching
rows) are NOT errors per spec edge case line 83 — the response
is `ok: true` with `agents: []`.

### 2.3 `set_role`

**Request**

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

**Validation order**:

1. Closed-set shape: `agent_id` matches `^agt_[0-9a-f]{12}$`
   (case-sensitive); `role` ∈ FR-004 closed set (case-sensitive).
2. Static rejection: `role == "swarm"` →
   `swarm_role_via_set_role_rejected` (FR-012).
3. Master-safety static rejection: `role == "master"` AND
   `confirm != true` → `master_confirm_required` (FR-011).
4. Acquire per-`agent_id` advisory mutex (FR-039).
5. SELECT existing agent (read-only, outside the write
   transaction; used only for the existence pre-check at step 6).
6. Existence: if no row → `agent_not_found` (release mutex; no
   transaction opened).
7. `BEGIN IMMEDIATE` — open the write transaction.
8. **Atomic re-check inside the transaction** (FR-011 / Clarifications
   session 2026-05-07-continued Q3): re-SELECT `agents.active`
   for the target AND `containers.active` for the agent's bound
   `container_id`. If either is `0`, `ROLLBACK` and return
   `agent_inactive`; no role mutation, no `effective_permissions`
   recomputation, no JSONL audit row. SQLite's `BEGIN IMMEDIATE`
   serializes this re-check against any concurrent FEAT-004
   reconciliation transaction so the validate-then-write window
   is closed at the SQLite level.
9. If new role equals stored role: `COMMIT` no-op; no audit
   row (FR-027); release mutex; return success envelope.
10. Recompute `effective_permissions` from the new role.
11. `UPDATE agents SET role = ?, effective_permissions = ? WHERE agent_id = ?`.
12. `COMMIT`.
13. Append JSONL audit row with `prior_role`, `new_role`,
    `confirm_provided` (the **literal** boolean the operator
    passed — `true` if `--confirm` was passed, `false` otherwise;
    NOT rewritten based on whether `--confirm` was required;
    Clarifications session 2026-05-07-continued Q5),
    `socket_peer_uid` (FR-014, Q4).
14. Release mutex; return success envelope.

**Success response**

```json
{
  "ok": true,
  "result": {
    "agent_id": "agt_abc123def456",
    "field": "role",
    "prior_value": "slave",
    "new_value": "master",
    "effective_permissions": {
      "can_send": true,
      "can_receive": false,
      "can_send_to_roles": ["slave", "swarm"]
    },
    "audit_appended": true
  }
}
```

**Error responses**

| Code | Trigger |
| ---- | ------- |
| `bad_request` | Malformed JSON / missing required key / unknown key |
| `value_out_of_set` | `agent_id` shape / `role` not in closed set |
| `swarm_role_via_set_role_rejected` | `role == "swarm"` |
| `master_confirm_required` | `role == "master"` AND `confirm != true` |
| `agent_not_found` | `agent_id` does not exist |
| `agent_inactive` | target `active = 0` OR (master promotion AND container `active = 0`) |
| `internal_error` | SQLite error / transaction rollback |
| `schema_version_newer` | client newer than daemon |

### 2.4 `set_label`

**Request**

```json
{
  "method": "set_label",
  "params": {
    "agent_id": "agt_abc123def456",
    "label": "codex-main"
  }
}
```

**Validation order**:

1. Closed-set shape: `agent_id` matches regex.
2. Free-text: `label` sanitized + bounded ≤ 64 chars (FR-033).
3. Acquire per-`agent_id` advisory mutex (FR-039).
4. SELECT existing agent.
5. Existence + active checks (`agent_not_found` / `agent_inactive`).
6. If new label equals stored label: no-op success.
7. BEGIN IMMEDIATE; UPDATE agents SET label; COMMIT.
8. NO audit row (FR-014 only audits role transitions).
9. Release mutex; return success envelope.

**Success response**

```json
{
  "ok": true,
  "result": {
    "agent_id": "agt_abc123def456",
    "field": "label",
    "prior_value": "codex-01",
    "new_value": "codex-main",
    "audit_appended": false
  }
}
```

`audit_appended` is always `false` for `set_label`.

**Error responses**

| Code | Trigger |
| ---- | ------- |
| `bad_request` | Malformed JSON / missing required key |
| `value_out_of_set` | `agent_id` shape |
| `field_too_long` | `label` > 64 chars |
| `agent_not_found` / `agent_inactive` | as for `set_role` |
| `internal_error` | SQLite error |
| `schema_version_newer` | client newer than daemon |

### 2.5 `set_capability`

**Request**

```json
{
  "method": "set_capability",
  "params": {
    "agent_id": "agt_abc123def456",
    "capability": "claude"
  }
}
```

**Validation order**:

1. Closed-set shape: `agent_id` matches regex; `capability` ∈
   FR-005 closed set.
2. Acquire per-`agent_id` advisory mutex.
3. SELECT existing agent.
4. Existence + active checks.
5. If new capability equals stored: no-op success.
6. BEGIN IMMEDIATE; UPDATE agents SET capability; COMMIT.
7. NO audit row (only role transitions audited).
8. Release mutex; return success envelope.

**Success response**

Same shape as `set_label` with `field=capability`.
`audit_appended` is always `false`.

**Error responses**

| Code | Trigger |
| ---- | ------- |
| `bad_request` | Malformed JSON / missing required key |
| `value_out_of_set` | `agent_id` shape OR `capability` not in closed set |
| `agent_not_found` / `agent_inactive` | as above |
| `internal_error` | SQLite error |
| `schema_version_newer` | client newer than daemon |

---

## 3. Closed-set error codes (FR-040)

The complete FEAT-006 closed-set error code addition (R-010):

| Constant | Wire token |
| -------- | ---------- |
| `HOST_CONTEXT_UNSUPPORTED` | `host_context_unsupported` |
| `CONTAINER_UNRESOLVED` | `container_unresolved` |
| `NOT_IN_TMUX` | `not_in_tmux` |
| `TMUX_PANE_MALFORMED` | `tmux_pane_malformed` |
| `PANE_UNKNOWN_TO_DAEMON` | `pane_unknown_to_daemon` |
| `AGENT_NOT_FOUND` | `agent_not_found` |
| `AGENT_INACTIVE` | `agent_inactive` |
| `PARENT_NOT_FOUND` | `parent_not_found` |
| `PARENT_INACTIVE` | `parent_inactive` |
| `PARENT_ROLE_INVALID` | `parent_role_invalid` |
| `PARENT_ROLE_MISMATCH` | `parent_role_mismatch` |
| `PARENT_IMMUTABLE` | `parent_immutable` |
| `SWARM_PARENT_REQUIRED` | `swarm_parent_required` |
| `SWARM_ROLE_VIA_SET_ROLE_REJECTED` | `swarm_role_via_set_role_rejected` |
| `MASTER_VIA_REGISTER_SELF_REJECTED` | `master_via_register_self_rejected` |
| `MASTER_CONFIRM_REQUIRED` | `master_confirm_required` |
| `VALUE_OUT_OF_SET` | `value_out_of_set` |
| `FIELD_TOO_LONG` | `field_too_long` |
| `PROJECT_PATH_INVALID` | `project_path_invalid` |
| `UNKNOWN_FILTER` | `unknown_filter` |
| `SCHEMA_VERSION_NEWER` | `schema_version_newer` |

These codes are added to `socket_api/errors.py` and to
`CLOSED_CODE_SET`. Existing FEAT-002/003/004 codes are unchanged
(SC-010). `daemon_unavailable` is a CLI-side classification (the
daemon never sees the call) and is NOT added to the daemon-side
closed set; it remains the FEAT-002 inheritance.

---

## 4. Backwards compatibility (SC-010)

- Existing dispatch entries (`ping`, `status`, `shutdown`,
  `scan_containers`, `list_containers`, `scan_panes`,
  `list_panes`) MUST be unchanged byte-for-byte: same handler
  function, same response shape, same closed-set codes, same
  error messages.
- `socket_api/errors.py`'s existing constants and existing
  `CLOSED_CODE_SET` membership MUST be unchanged; only new
  constants are added.
- The FEAT-002 newline-delimited JSON framing MUST be
  unchanged.
- The FEAT-002 `0600` host-user-only socket-file authorization
  MUST be unchanged.

A backwards-compat integration test
(`tests/integration/test_feat006_backcompat.py`) gates these
guarantees by re-running every FEAT-001..005 CLI command on the
host and asserting byte-identical stdout, stderr, exit codes,
and `--json` shapes.

---

## 5. Concurrency contract (FR-038, FR-039)

- `register_agent` requests addressing the same
  (container_id, pane_composite_key) tuple are serialized via a
  per-key `threading.Lock` (R-005). Concurrent calls from
  different panes proceed in parallel.
- `set_role`, `set_label`, `set_capability` requests addressing
  the same `agent_id` are serialized via a per-`agent_id`
  `threading.Lock`. Concurrent calls on different agents
  proceed in parallel.
- All SQLite writes happen inside a `BEGIN IMMEDIATE`
  transaction so the read-modify-write of
  `effective_permissions` is atomic.
- Failed transactions are rolled back; the daemon stays alive
  (FR-035); no audit row is appended on rollback (FR-014).

### Cross-subsystem ordering with FEAT-004 (FR-038 / Clarifications session 2026-05-07-continued Q4)

- The FEAT-006 per-(container, pane-key) registration mutex
  covers `register_agent` against other `register_agent`
  requests addressing the same composite key, **and nothing
  else**.
- FEAT-004 pane reconciliation MUST NOT acquire the FEAT-006
  per-key registration mutex; the two subsystems remain
  decoupled.
- Cross-subsystem ordering between a `register_agent`
  transaction and a FEAT-004 reconciliation transaction
  touching the same `agents` row is provided **exclusively** by
  SQLite's `BEGIN IMMEDIATE` semantics.
- Both transactions remain atomic — neither observes a partial
  write from the other.
- The transaction that commits last wins for any overlapping
  mutable column (e.g., if `register_agent` sets `active=1` and
  a concurrent reconciliation sets `active=0` for the same row,
  whichever commits last is the post-state visible to
  subsequent reads).
- `SQLITE_BUSY` MUST surface as `internal_error` (FR-035)
  without daemon-side retry; the operator can re-invoke the
  CLI if needed.

---

## 6. JSONL audit-row contract (FR-014, Q4)

Appended to the existing FEAT-001 `events.jsonl`. One row per
successful role transition (creation OR change), 0 rows on no-op
or failure.

**Row shape**: FEAT-006 reuses the FEAT-001
`events.writer.append_event` helper, so the on-disk record is the
standard nested envelope — `ts` is added by the writer and
FEAT-006 fields live under `payload`:

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

`payload.prior_role` is `null` (JSON literal) on the initial
creation transition (Q4), regardless of which role was assigned
(including the default `unknown`). On every other transition
`prior_role` is the previous string role.

`payload.confirm_provided` is the **literal** boolean the
operator passed in the `confirm` request parameter, never
rewritten based on whether `--confirm` was *required*
(Clarifications session 2026-05-07-continued Q5). `true` when
`--confirm` was passed; `false` otherwise. Demotion from master
with redundant `--confirm` logs `true`; `set-role` to a
non-master role with redundant `--confirm` also logs `true`;
`register-self` creation always logs `false`. Consumers derive
"was confirm required" from `prior_role` + `new_role`.

`payload.socket_peer_uid` is the host uid of the calling process,
extracted by the daemon from the accepted AF_UNIX connection via
`SO_PEERCRED` and passed to the agent dispatcher out-of-band so a
request body cannot spoof it. The sentinel value `-1` indicates
the kernel did not surface a peer credential — in production this
would be an unexpected operational anomaly; in tests it is the
default when DISPATCH is invoked without a real socket.

`set_label` and `set_capability` MUST NOT append rows.

---

## 7. Forward-compat (R-018)

The daemon's `status` response includes `schema_version` per
FEAT-002. CLIs in this feature compare it to their local
`CURRENT_SCHEMA_VERSION` and surface `schema_version_newer` if
the daemon is ahead. The daemon also performs a defensive check
on every method handler — if it ever receives a request shape
it does not recognize, it returns `bad_request` rather than
silently misinterpreting the call.

---

## 8. No new transport / no new auth (FR-043)

FEAT-006 introduces no new transport. The five new methods reuse
the FEAT-002 `AF_UNIX` socket, the FEAT-002 newline-delimited
JSON framing, the FEAT-002 socket-file authorization (`0600`,
host user only), and the FEAT-002 `SO_PEERCRED`-derived
`socket_peer_uid`. No network listener, no in-container daemon,
no relay, no secondary auth tier (FR-043).
