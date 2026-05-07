# CLI Contracts: Agent Registration and Role Metadata

**Branch**: `006-agent-registration` | **Date**: 2026-05-07

This document is the authoritative contract for the five additive
CLI surfaces FEAT-006 introduces. It supplements `spec.md`
FR-028, FR-029, FR-030, FR-031, FR-032, FR-040, and Clarifications
2026-05-07 Q1, Q3, Q4, Q5. Anything here overrides informal CLI
descriptions in spec.md.

FEAT-001 / FEAT-002 / FEAT-003 / FEAT-004 / FEAT-005 CLI surfaces
are unchanged byte-for-byte (SC-010).

---

## C-CLI-601 — `agenttower register-self`

### Synopsis

```text
agenttower register-self [--role <r>] [--capability <c>] [--label <l>]
                         [--project <path>] [--parent <agent-id>]
                         [--json]
```

### Behavior

Resolves the caller's container id (FEAT-005) and tmux pane
composite key (FEAT-005 + FEAT-004 lookup; FR-041 focused rescan
on miss), then registers (or idempotently re-registers /
re-activates) the bound agent via the daemon's `register_agent`
socket method.

### Flags

| Flag | Argparse default | Wire behavior on absence | Notes |
| ---- | ---------------- | ------------------------ | ----- |
| `--role <r>` | `argparse.SUPPRESS` | absent in JSON params | First registration applies CLI default `unknown` server-side; idempotent re-registration leaves stored role unchanged (Clarifications Q1). `r` ∈ `{master, slave, swarm, test-runner, shell, unknown}`. `--role master` is rejected unconditionally per FR-010. |
| `--capability <c>` | `argparse.SUPPRESS` | absent in JSON params | Same semantics. `c` ∈ `{claude, codex, gemini, opencode, shell, test-runner, unknown}`. |
| `--label <l>` | `argparse.SUPPRESS` | absent in JSON params | Sanitized + bounded to 64 chars (FR-033). Empty string is allowed when explicitly passed. |
| `--project <path>` | `argparse.SUPPRESS` | absent in JSON params | Validated as absolute, NUL-free, no `..` segment, ≤ 4096 chars (FR-034). |
| `--parent <agent-id>` | `argparse.SUPPRESS` | absent in JSON params | Only valid with `--role swarm` (FR-016). Re-registration with a *different* `--parent` rejected `parent_immutable` (Clarifications Q3). |
| `--json` | flag | — | Emit one JSON object on stdout; suppress human-readable output. |

### Exit codes (FR-032 + FR-040)

The FEAT-006 CLI handlers follow the FEAT-002 / FEAT-005
exit-code surface (daemon errors → `3`) rather than the
spec-prose `1`-for-error sketch. The `1` slot is reserved for
client-side context errors (today only `host_context_unsupported`).

| Pattern | Exit code |
| ------- | --------- |
| Successful registration / idempotent re-registration / re-activation | `0` |
| `host_context_unsupported` (running on the host shell, not in a bench container) | `1` |
| `daemon_unavailable` (daemon down)                                   | `2` (FEAT-002 inheritance) |
| Any other closed-set error code (e.g., `container_unresolved`, `not_in_tmux`, `tmux_pane_malformed`, `pane_unknown_to_daemon`, `master_via_register_self_rejected`, `swarm_parent_required`, `parent_role_mismatch`, `parent_not_found`, `parent_inactive`, `parent_role_invalid`, `parent_immutable`, `value_out_of_set`, `field_too_long`, `project_path_invalid`, `schema_version_newer`) | `3` |
| Internal CLI error                                                   | `4` (reserved per FEAT-002) |

### Default output

One `key=value` line per field on stdout (matching the
established multi-line key=value style FEAT-002 / FEAT-005 use for
single-record success output):

```text
agent_id=<agt_xxx>
role=<role>
capability=<cap>
label=<label>
project_path=<path>
parent_agent_id=<agt_xxx-or-dash>
created_or_reactivated=<created|reactivated|updated>
```

`parent_agent_id` renders as the literal `-` when null.

### `--json` output

The success envelope wraps the daemon's `register_agent` result
under `{"ok": true, "result": {...}}` so the same outer shape
applies to every FEAT-006 CLI command (mirroring how `set-*`
emit). The `result` object carries the fields below:

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
    "pane_composite_key": {
      "container_id": "<full-id>",
      "tmux_socket_path": "/tmp/...",
      "tmux_session_name": "main",
      "tmux_window_index": 0,
      "tmux_pane_index": 0,
      "tmux_pane_id": "%17"
    },
    "effective_permissions": {
      "can_send": false,
      "can_receive": true,
      "can_send_to_roles": []
    },
    "created_or_reactivated": "created"
  }
}
```

On error:

```json
{
  "ok": false,
  "error": {
    "code": "<closed_set_code>",
    "message": "<actionable message>"
  }
}
```

---

## C-CLI-602 — `agenttower list-agents`

### Synopsis

```text
agenttower list-agents [--role <r>...] [--container <id-or-short>]
                       [--active-only] [--parent <agent-id>] [--json]
```

### Behavior

Calls the daemon's `list_agents` socket method with the requested
filter envelope. Read-only, no SQLite writes, no JSONL appends,
no `last_seen_at` mutation (R-003).

### Flags

| Flag | Behavior |
| ---- | -------- |
| `--role <r>` | Repeatable. Each value must belong to the FR-004 closed set. AND-composes with other filters per FR-026 (within `--role` repeats: OR). |
| `--container <id-or-short>` | Full container id or 12-char short id; classified server-side per FR-026. |
| `--active-only` | Boolean flag; when present, daemon returns only `active=true` agents. |
| `--parent <agent-id>` | Filter to swarm children of the named slave (FR-026). |
| `--json` | Emit JSON array; suppress TSV. |

### Exit codes

`0` on success (incl. empty result set per edge case "filter matches
no rows" line 83 of spec); `2` on `daemon_unavailable`; `3` on any
other closed-set code (e.g., `unknown_filter`, `value_out_of_set`,
`schema_version_newer`).

### Default output (Clarifications Q5)

Tab-separated values with a required header row, locked
nine-column schema in this exact order:

```text
AGENT_ID\tLABEL\tROLE\tCAPABILITY\tCONTAINER\tPANE\tPROJECT\tPARENT\tACTIVE
agt_abc123def456\tcodex-01\tslave\tcodex\t<12-char-short>\tmain:0.1\t/workspace/acme\t-\ttrue
agt_def456abc789\tclaude-swarm-01\tswarm\tclaude\t<12-char-short>\tmain:0.2\t/workspace/acme\tagt_abc123def456\ttrue
...
```

Rendering rules:

- Header row is the first line of output.
- `CONTAINER` renders as the 12-character short container id.
- `PARENT` renders as the full `agt_<12-hex>` form when
  `parent_agent_id` is non-null, or the literal `-` (single ASCII
  hyphen) when null.
- `PANE` renders as `<session>:<window>.<pane>` (FEAT-004 short
  form).
- `ACTIVE` renders as the literal `true` or `false`.
- Empty `LABEL` and `PROJECT` render as empty strings between the
  tabs.
- All free-text fields are sanitized of NUL / C0 control bytes
  (per FR-033 / R-022); embedded `\t` and `\n` MUST be replaced
  with single spaces so the TSV row stays one logical line.

Future fields MUST NOT be added to the default form; they go to
`--json` or a separately-introduced `--wide` flag.

### `--json` output

```json
{
  "ok": true,
  "filter": {
    "role": null,
    "container_id": null,
    "active_only": false,
    "parent_agent_id": null
  },
  "agents": [
    {
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
      "effective_permissions": { ... },
      "created_at": "2026-05-07T...",
      "last_registered_at": "2026-05-07T...",
      "last_seen_at": "2026-05-07T..." ,
      "active": true
    },
    ...
  ]
}
```

---

## C-CLI-603 — `agenttower set-role`

### Synopsis

```text
agenttower set-role --target <agent-id> --role <r> [--confirm] [--json]
```

### Behavior

Calls the daemon's `set_role` socket method. Master promotion
(`--role master`) requires `--confirm` AND the target agent
`active=true` AND the target's bench container `active=true`
(FR-011). Demotion from master MUST NOT require `--confirm`
(FR-013). `--role swarm` MUST be rejected with
`swarm_role_via_set_role_rejected` and the actionable message
`swarm role assignment requires register-self --role swarm --parent <id>`
(FR-012).

### Flags

| Flag | Required | Behavior |
| ---- | -------- | -------- |
| `--target <agent-id>` | yes | Validated client-side against `^agt_[0-9a-f]{12}$` (R-020). |
| `--role <r>` | yes | `r` ∈ FR-004 closed set. `swarm` rejected per FR-012. `master` requires `--confirm` per FR-011. |
| `--confirm` | conditional | Required for `--role master`. Calls without `--confirm` for master rejected `master_confirm_required`. |
| `--json` | optional | Emit JSON; suppress text output. |

### Exit codes

`0` on success (including no-op when new role equals stored role);
`2` on `daemon_unavailable`; `3` on any other closed-set code
(`agent_not_found`, `agent_inactive`, `master_confirm_required`,
`swarm_role_via_set_role_rejected`, `value_out_of_set`,
`schema_version_newer`).

### Default output

One `key=value` line per field on stdout:

```text
agent_id=<agt_xxx>
field=role
prior_value=<role>
new_value=<role>
audit_appended=<true|false>
```

### `--json` output

The success envelope is `{"ok": true, "result": {...}}` (same
outer shape as `register-self`):

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

`audit_appended` is `false` on no-op writes (FR-027).

---

## C-CLI-604 — `agenttower set-label`

### Synopsis

```text
agenttower set-label --target <agent-id> --label <l> [--json]
```

### Behavior

Calls `set_label`. `--label` is sanitized + bounded to 64 chars
(FR-033). Setting the same value the agent already has is a
successful no-op that appends no audit row (FR-027 — `set_label`
does not append audit rows in any path because only role
transitions are audited).

### Exit codes

`0` on success; `2` on `daemon_unavailable`; `3` on any other
closed-set code (`agent_not_found`, `agent_inactive`,
`field_too_long`, `value_out_of_set`, `schema_version_newer`).

### Default output

One `key=value` line per field on stdout:

```text
agent_id=<agt_xxx>
field=label
prior_value=<label>
new_value=<label>
audit_appended=false
```

### `--json` output

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

---

## C-CLI-605 — `agenttower set-capability`

### Synopsis

```text
agenttower set-capability --target <agent-id> --capability <c> [--json]
```

### Behavior

Calls `set_capability`. `--capability` MUST belong to the FR-005
closed set. Setting the same value is a successful no-op.

### Exit codes

`0` on success; `2` on `daemon_unavailable`; `3` on any other
closed-set code (`agent_not_found`, `agent_inactive`,
`value_out_of_set`, `schema_version_newer`).

### Default output / `--json` output

Mirrors `set-label` with `field=capability`.

---

## Cross-cutting CLI rules

### Socket resolution (FR-032)

Every CLI in this feature inherits the FEAT-005 socket-resolution
priority chain `AGENTTOWER_SOCKET → in-container default → host
default` and the FEAT-005 / FEAT-002 daemon-unreachable
exit-code-`2` behavior. None of these commands MUST start the
daemon implicitly; the operator runs `agenttower ensure-daemon`
separately.

### Sanitization (FR-033, R-022)

All free-text inputs and outputs are sanitized of NUL bytes and
C0 control bytes via the existing
`agenttower.tmux.parsers.sanitize_text` helper. Per-field bounds
are enforced (label ≤ 64; project_path ≤ 4096); over-bound values
are rejected with `field_too_long` rather than silently
truncated.

### Case-sensitivity (Clarifications session 2026-05-07-continued Q2)

Every closed-set token (`role`, `capability`) and every
lowercase-hex identifier (`agent_id`, `parent_agent_id`,
`container_id`) is matched case-sensitively. Mixed-case inputs
(`Slave`, `MASTER`, `agt_ABC...`, `ABC123def456`) MUST be
rejected with `value_out_of_set` and MUST NOT be normalized.
This applies uniformly to CLI argument validation, daemon-side
validation, and filter matching for `list-agents`. Closed-set
error messages list canonical lowercase tokens only.

### Closed-set error codes (FR-040)

Every failure path surfaces a closed-set error code that appears
verbatim in `--json` output and in the human-readable stderr
message. The complete set is in `contracts/socket-api.md` §3.

### `--json` purity

When `--json` is set, stdout MUST contain exactly one JSON object
per invocation. No incidental human-readable lines on stderr
(except the standard FEAT-002 daemon-unavailable message on
`daemon_unavailable` which the CLI inherits verbatim).

### Forward-compat (R-018)

When the daemon's `schema_version` (returned by the FEAT-002
`status` round-trip) is greater than the CLI's local
`CURRENT_SCHEMA_VERSION`, every CLI in this feature surfaces
`schema_version_newer` and refuses the call without making any
state-changing socket call.
