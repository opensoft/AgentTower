# Managed Session Creation and Lifecycle (FEAT-013)

Operator-facing reference for AgentTower's **managed-session** surface:
how to create a multi-agent tmux layout inside a bench container, how
the lifecycle states behave, where the operator YAML configuration
lives, and which CLI / app-contract methods are available.

This is a companion to:

- [`specs/013-managed-session-lifecycle/spec.md`](../specs/013-managed-session-lifecycle/spec.md) — feature requirements.
- [`specs/013-managed-session-lifecycle/quickstart.md`](../specs/013-managed-session-lifecycle/quickstart.md) — synthetic-client walkthrough (US1/US2/US3 end-to-end).
- [`specs/013-managed-session-lifecycle/contracts/managed-methods.md`](../specs/013-managed-session-lifecycle/contracts/managed-methods.md) — wire-shape contracts for M1–M8.
- [`docs/app-contract-client-guide.md`](app-contract-client-guide.md) — the client-facing index for all `app.*` methods (including the new `app.managed_*` set added by this feature).

---

## Overview

FEAT-013 adds operator-driven creation of standard multi-agent tmux
layouts. Instead of adopting existing panes one-by-one through
`app.agent.register_from_pane`, the operator picks a **template** (e.g.
"1 master + 2 slaves") and AgentTower:

1. Creates the tmux panes via `tmux new-session` / `split-window` (no
   `send-keys` for the first-line command — Principle III safety).
2. Registers each created pane as a FEAT-006 agent so the existing
   route / queue / event / log surfaces work uniformly across managed
   and adopted agents.
3. Tracks each pane through a 5-state lifecycle (`creating` → `ready` /
   `degraded` / `failed` → `removed`) with audit-grade events on every
   transition.
4. Survives daemon restarts: managed layouts are recovered from durable
   SQLite storage and reattached to surviving tmux panes within 5
   seconds of the socket opening (SC-008 + SC-009).

---

## Templates

Two built-in templates ship in code; operator-overridable YAML files
extend the set without re-compiling the daemon.

### Built-ins

| Name | Panes | Roles |
|---|---|---|
| `1m+2s` | 3 | 1 master + 2 slaves |
| `2m+2s` | 4 | 2 masters + 2 slaves |

### Override directory

```text
~/.config/opensoft/agenttower/managed_templates/*.yaml
```

The daemon does NOT auto-create this directory; the operator creates
it when adding the first override. Sample template YAMLs live in the
repo under `examples/managed_templates/` for discovery (NOT installed
by the daemon — per FR-024's no-auto-create rule).

### YAML schema

```yaml
name: my-custom            # unique; operator file with same name wins
                            # over a built-in default
panes:
  - role: master
    capability: orchestrator
    label_pattern: "m{ordinal}"        # {ordinal} → 1, 2, ...
    default_launch_command_ref: claude-master    # see Launch profiles
  - role: slave
    capability: worker
    label_pattern: "s{ordinal}"
    default_launch_command_ref: claude-worker
```

---

## Launch command profiles

Argv-shape command definitions used to start each agent. The argv form
is mandatory — single-string shell-parsed commands are rejected (the
shell-interpolation hazard is the reason FEAT-013 exists).

### Override directory

```text
~/.config/opensoft/agenttower/launch_commands/*.yaml
```

Sample profile YAMLs live under `examples/launch_commands/` for
discovery.

### YAML schema

```yaml
name: claude-master
command: ["claude", "--model", "opus", "--system-prompt-file", "master.md"]
env:
  ANTHROPIC_LOG: warn
working_dir: /workspace
```

- `command` — argv (list of strings); the tmux `new-session -d -s ... --
  <cmd...>` invocation passes these AS-IS, no shell parsing.
- `env` — optional; merged into the pane's environment via tmux's
  `-e KEY=VALUE` flag.
- `working_dir` — optional; the ONLY field where any shell escaping
  happens (via `shlex.quote`), because tmux's `-c` working-directory
  flag goes through the shell.

Operator-supplied env-var **values** matching the closed substring set
`*TOKEN*` / `*SECRET*` / `*KEY*` / `*PASSWORD*` (case-insensitive) are
redacted in lifecycle event payloads (FR-021). Argv and `working_dir`
are NOT redacted (operator-visible failure diagnostics rely on them).

---

## Lifecycle states

Both `managed_pane` and `managed_layout` rows track one of five states:

| State | Meaning |
|---|---|
| `creating` | Pane is being spawned, agent is being registered, logs are being attached. Pending-managed marker is set on the tmux pane title so the FEAT-004 scan skips it. |
| `ready` | Pane exists in tmux, agent is registered with FEAT-006, log attach attempted (success or recoverable failure). Marker cleared. |
| `degraded` | Pane exists but is partly unhealthy: launch command exited within 1s, log attach failed, or agent went unhealthy after `ready`. Recovery is via **recreate**. |
| `failed` | Pane is unusable until recreated. `failed_stage` is populated. Audit retained indefinitely; a fresh recreated row may take the same label. |
| `removed` | Operator-initiated removal; tmux pane was killed, routes/log attachments cleaned. Terminal. Audit retained indefinitely. |

`failed_stage` is one of six closed-set values when set:
`pane_create` / `launch_command` / `registration` / `log_attach` /
`tmux_kill` / `recovery_reattach`. The full state graph (transitions,
disallowed transitions, recovery rules) lives in
[`contracts/state-machine.md`](../specs/013-managed-session-lifecycle/contracts/state-machine.md).

---

## Method list

Eight methods total, available in **both** namespaces. The legacy
`managed.*` namespace is reachable from host CLI and bench-container
thin clients (with peer scoping); the `app.managed_*` namespace is
host-only via the FEAT-011 gate.

| Method (legacy) | Method (app) | What it does |
|---|---|---|
| `managed.layout.create` | `app.managed_layout_create` | Create a managed layout from a template. Returns immediately after row insertion; tmux spawn runs in a background task. (M1) |
| `managed.layout.list` | `app.managed_layout_list` | Paginated list of managed layouts. Ordered by `(state_priority ASC, created_at DESC)` — operational-state first. (M2) |
| `managed.layout.detail` | `app.managed_layout_detail` | Full layout view including all panes (optionally terminal). Surfaces `failed_stage` at both layout and per-pane levels. (M3) |
| `managed.pane.list` | `app.managed_pane_list` | Paginated list of managed panes. (M4) |
| `managed.pane.detail` | `app.managed_pane_detail` | Single-pane detail with optional `predecessor_chain` recursion. (M5) |
| `managed.pane.remove` | `app.managed_pane_remove` | Kill underlying tmux pane + clean up routes/logs + transition to `removed`. Preserves audit history. (M6) |
| `managed.pane.recreate` | `app.managed_pane_recreate` | Produce a new pane row linked via `predecessor_id` + `chain_depth+1`. Predecessor must be in `removed` or `failed`. (M7) |
| `managed.pane.promote_from_adopted` | `app.managed_pane_promote_from_adopted` | **STUB** — always returns `not_implemented` with `reserved_since="FEAT-013"`. Reserved for a later feature. (M8) |

Full request / response shapes for every method are in
[`contracts/managed-methods.md`](../specs/013-managed-session-lifecycle/contracts/managed-methods.md).

---

## Example: create a layout

```json
{
  "method": "app.managed_layout_create",
  "container_id": "bench-alpha",
  "template_name": "1m+2s",
  "tmux_session_name": "session-quickstart",
  "launch_command_overrides": {
      "master:m1": "claude-master",
      "slave:s1":  "claude-worker",
      "slave:s2":  "claude-worker"
  },
  "idempotency_key": "operator-clicked-create-12345"
}
```

Response (immediate, before tmux spawn completes):

```json
{
  "ok": true,
  "app_contract_version": "1.0",
  "result": {
    "layout_id": "01HZ...",
    "state": "creating",
    "intended_pane_count": 3,
    "panes": [
        {"pane_id": "01HZ-p1", "role": "master", "label": "m1", "state": "creating"},
        {"pane_id": "01HZ-p2", "role": "slave",  "label": "s1", "state": "creating"},
        {"pane_id": "01HZ-p3", "role": "slave",  "label": "s2", "state": "creating"}
    ],
    "replay": false
  }
}
```

Poll `app.managed_layout_detail` until `state == "ready"` (or subscribe
to lifecycle events via `app.event.list`).

---

## Closed-set error codes (FEAT-013 additions)

13 new error codes added on top of FEAT-011's 27-entry registry (40
total). Full details in
[`contracts/error-codes.md`](../specs/013-managed-session-lifecycle/contracts/error-codes.md).

| Code | Method(s) | When |
|---|---|---|
| `managed_template_not_found` | M1 | `template_name` doesn't resolve via built-ins or operator overrides. |
| `managed_launch_command_not_found` | M1 / M7 | `launch_command_overrides` references an unknown profile. |
| `managed_session_name_conflict` | M1 | `tmux_session_name` already exists in the target container. No silent suffixing. |
| `managed_pane_label_conflict` | M1 | Two non-terminal panes collide on `(container_id, label)`. |
| `managed_layout_capacity_exceeded` | M1 | Daemon at 40-layout cap (FR-025). |
| `managed_layout_not_found` | M3 | Unknown `layout_id`. |
| `managed_pane_not_found` | M4 / M5 / M6 / M7 | Unknown `pane_id` (or `predecessor_pane_id`). |
| `managed_pane_protected_adopted` | M6 / M7 | Target pane exists in `agents` (adopted) but NOT in `managed_pane` (FR-012). |
| `managed_pane_illegal_transition` | M6 | E.g., trying to remove a pane in `creating` state. |
| `managed_pane_illegal_recreate_source` | M7 | Predecessor is `ready` / `degraded` / `creating` (must be `removed` / `failed`). |
| `managed_pane_recreate_chain_too_deep` | M7 | `predecessor.chain_depth >= 15` (limit is 16; FR-023). |
| `managed_pane_concurrent_recreate` | M7 | Another recreate of the same predecessor is in flight (FR-027). |
| `container_not_found` | M1 / M6 / M7 | `container_id` is unknown to the FEAT-003 registry. |

---

## Scope notes (MVP)

**Out of scope** (FR-018): non-tmux backends, semantic task planning,
cross-host orchestration, adopted-to-managed pane promotion, and
cancellation of in-flight layout creation.

**Indefinite retention** (FR-021): managed-layout and managed-pane
audit records are preserved indefinitely in MVP. Pruning is deferred to
a later feature.

**Authorization** (spec §Assumptions): MVP is socket-access-based —
any caller with access to the host daemon's local socket can create
managed layouts. Per-user or per-container ACL is a later hardening
feature. `app.managed_*` is host-only via FEAT-011's gate; legacy
`managed.*` is peer-scoped (a bench-container thin client may only act
on its own container).

---

## See also

- Spec: [`specs/013-managed-session-lifecycle/spec.md`](../specs/013-managed-session-lifecycle/spec.md)
- Quickstart: [`specs/013-managed-session-lifecycle/quickstart.md`](../specs/013-managed-session-lifecycle/quickstart.md)
- Contracts: [`specs/013-managed-session-lifecycle/contracts/`](../specs/013-managed-session-lifecycle/contracts/)
- Research decisions: [`specs/013-managed-session-lifecycle/research.md`](../specs/013-managed-session-lifecycle/research.md)
- Data model: [`specs/013-managed-session-lifecycle/data-model.md`](../specs/013-managed-session-lifecycle/data-model.md)
