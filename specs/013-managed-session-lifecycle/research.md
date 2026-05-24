# Phase 0 Research: Managed Session Creation and Lifecycle

**Feature**: 013-managed-session-lifecycle
**Date**: 2026-05-24
**Status**: Complete — all NEEDS CLARIFICATION items resolved.
**Spec back-reference**: Origin of FR-022 / FR-023 / FR-024 / SC-009 is spec §Clarifications "Session 2026-05-24 (post-plan review)"; user-story traceability + SC-006 rewording are recorded in spec §Clarifications "Session 2026-05-24 (alignment cleanup)".

This file resolves the load-bearing open questions surfaced by the spec, the clarifications session, and the deep-and-wide checklists. Each entry is **Decision / Rationale / Alternatives**.

---

## R1. Pending-managed marker representation

**Decision**: Mirror the marker in two places:

1. SQLite — `managed_pane.pending_marker_token TEXT NULL` (set on row insert before tmux spawn; cleared on transition to `ready`).
2. Tmux pane title — set to `@MANAGED:<token>:<label>` via `tmux select-pane -T '@MANAGED:<token>:<label>'` **immediately before** the spawning `new-session` / `split-window` call. The title is observable to the FEAT-004 scan through the existing `list-panes -F '#{pane_title}'` formatter.

The FEAT-004 scan checks for the `@MANAGED:` prefix and skips registration; FEAT-013 service clears the title (sets it back to the operator-visible `<label>` only) after registration completes.

**Rationale**: Visible to the existing scan path without modifying the scan; survives daemon restart because the SQLite column persists and the tmux title persists for as long as the pane exists; integrity-checked by comparing the column to the parsed title prefix during recovery.

**Alternatives considered**:
- Tmux per-pane user options (`tmux set-option -p -t <pane> @managed-token "<token>"`) — requires changing the scan's `list-panes` formatter to include `#{@managed-token}`; modifies FEAT-004's surface and is harder to verify on legacy tmux versions.
- Environment variables on the pane process — invisible to scan; depends on the operator's process reading them; lost across pane respawn.
- Lock-file or sidecar SQLite-only marker — invisible to tmux, so a scan that races SQLite reads can still see an unregistered pane.

---

## R2. Per-container serialization primitive (FR-019)

**Decision**: Maintain a dict `dict[container_id, asyncio.Lock]` inside the service module. Each `create-layout` acquires the lock for its container_id before starting; cross-container calls run in parallel. FIFO ordering of waiters is guaranteed by `asyncio.Lock` semantics on Python 3.11+ (the underlying `_FifoMutex`). No timeout: a stuck create surfaces via its `managed_layout.state = 'creating'` row, observable to the operator; cancellation of an in-flight create is **out of scope for MVP** per spec §FR-018 (may be revisited in a later feature).

**Rationale**: Matches the FEAT-011 mutation style. Per-container scope is the minimum lock granularity that prevents tmux-level conflicts (same container, same tmux server). No timeout keeps semantics simple and matches Q3's "the second request waits until the first finishes."

**Alternatives considered**:
- Process-wide global lock — over-restrictive; would serialize unrelated containers.
- SQLite SERIALIZABLE transactions — adds contention with non-managed writes; locks SQLite for the duration of tmux I/O, which is multi-second.
- Lock-free with optimistic re-check on tmux state — risks pane double-create on concurrent calls; loses FIFO observability.

---

## R3. SQLite schema shape

**Decision**: Two new tables `managed_layout` and `managed_pane`, with a self-FK on `managed_pane.predecessor_id` and a nullable FK on `managed_pane.agent_id` into the existing FEAT-006 `agent` table. No existing table is altered.

**Rationale**: Preserves FR-008's "same registry / queue / route / event surfaces" claim — managed agents become rows in the existing `agent` table once registered. The managed_layout / managed_pane tables are pure metadata layered above the registry; they own only the lifecycle, predecessor linkage, and tmux placement of each pane.

**Alternatives considered**:
- Storing managed metadata as JSON on `agent` — couples schemas and breaks aggregate queries (e.g., "list all panes still in `creating`").
- Single flat `managed_session` table — forces nullable layout-level fields per pane; harder to enforce 1:N cardinality and per-container label uniqueness.

---

## R4. Recreate-chain depth bound

**Decision**: Bound at **16**. `managed_pane.chain_depth INTEGER NOT NULL DEFAULT 0`; on recreate, the new row gets `chain_depth = predecessor.chain_depth + 1`. The service rejects a recreate when `predecessor.chain_depth >= 15` with `managed_pane_recreate_chain_too_deep`.

**Rationale**: Prevents pathological infinite-recreate loops while leaving generous headroom for legitimate iterative-debug workflows. Observable per FR-013 via a specific closed-set error code.

**Alternatives considered**:
- Unbounded — risks chain traversal cost growing; complicates indefinite audit (FR-021).
- Bound at 4 — too small; would surprise operators who iteratively fix a flaky launch command.

---

## R5. Pending-managed marker TTL

**Decision**: 5 minutes. Markers older than the TTL are GC'd at:

- Daemon boot (FR-020 reconciliation runs before the socket starts accepting requests).
- A periodic 60-second sweep (`pending_marker.sweep()` task) that drops markers whose `managed_pane.created_at` is more than 5 minutes ago and whose `managed_pane.state` is still `creating`; the affected pane is transitioned to `failed` with `failed_stage = 'pane_create'` if no tmux pane backs it, or `failed_stage = 'registration'` if a pane exists but never registered.

**Rationale**: Well above SC-001's 2-minute layout-create p95, with headroom for retries. Small enough that crashed-daemon residue clears quickly. Mirrors FEAT-011's scan-result eviction cadence.

**Alternatives considered**:
- Indefinite TTL — label-uniqueness collisions accumulate; never-cleared markers block recreate.
- 60-second TTL — too aggressive given SC-001's 2-minute headroom; healthy long creates would be killed.

---

## R6. Tmux command surface

**Decision**: Use the following tmux invocations through the existing FEAT-004 `docker exec -u "$USER" <container> tmux ...` channel:

- `tmux new-session -d -s <session_name> -n <window_name> -- <launch_argv...>` — creates a detached session with the first pane.
- `tmux split-window -t <session_name>:<window>.<pane_index> -h|-v -- <launch_argv...>` — adds further panes per template.
- `tmux select-pane -t ... -T '@MANAGED:<token>:<label>'` — sets the pending-managed marker pane title.
- `tmux select-pane -t ... -T '<label>'` — clears the marker after registration.
- `tmux kill-pane -t ...` — `remove` action (FR-010).

Launch argv is passed as separate argv items after `--`; **no shell `-c` is used**. When operator-supplied `env` or `working_dir` is present, it is applied via tmux's `-e KEY=VALUE` flag (env) or the `cd <dir> &&` prefix using `shlex.quote` (working_dir — only path where any escaping happens, and the path is the only escaped token).

**Rationale**: Argv-first matches Principle III ("shell command construction must never interpolate raw prompt text"). `new-session -d` puts the session in detached state so the daemon can complete registration before the operator focuses the window. Splitting after `new-session` is the safe order: no race against tmux's first-pane initialization.

**Alternatives considered**:
- `tmux send-keys` for the first-line command — shell-interpolates the operator string; Principle III hazard.
- `tmux respawn-pane` — rebases an existing pane; semantically wrong for create.

---

## R7. Failure-stage taxonomy

**Decision**: Closed enum `failed_stage ∈ {pane_create, launch_command, registration, log_attach, tmux_kill, recovery_reattach}`.

- `pane_create` — `tmux new-session` / `split-window` failed.
- `launch_command` — pane exists but the launch process exited within 1 second (R8 timing).
- `registration` — FEAT-006 register-self path errored.
- `log_attach` — FEAT-007 log attachment failed (results in `degraded`, not `failed`, per FR-006).
- `tmux_kill` — `tmux kill-pane` failed during `remove`.
- `recovery_reattach` — daemon-boot reconcile could not match a stored managed_pane to a live tmux pane.

**Rationale**: Aligns to the four-stage create pipeline + the two restart-path stages. Testable (FR-013 contract tests assert the exact enum value).

---

## R8. Template schema and storage

**Decision**: Two built-in templates ship as Python data in `src/agenttower/managed_sessions/templates.py`:

```python
TEMPLATE_1M_2S = ManagedTemplate(
    name="1m+2s",
    panes=[
        TemplatePane(role="master", capability="orchestrator", label_pattern="m{ordinal}",
                     default_launch_command_ref=None),
        TemplatePane(role="slave",  capability="worker",        label_pattern="s{ordinal}",
                     default_launch_command_ref=None),
        TemplatePane(role="slave",  capability="worker",        label_pattern="s{ordinal}",
                     default_launch_command_ref=None),
    ],
)
TEMPLATE_2M_2S = ManagedTemplate(... 4 panes ...)
```

Operator overrides live in `~/.config/opensoft/agenttower/managed_templates/*.yaml` with the same schema:

```yaml
name: my-custom
panes:
  - role: master
    capability: orchestrator
    label_pattern: m{ordinal}
    default_launch_command_ref: my-master-cmd
  - ...
```

Loader merges built-ins with user files; **user file with same `name` wins**. Loader rejects files whose schema fails validation with a startup warning (does not abort daemon).

**Rationale**: Matches the constitution's `~/.config/opensoft/agenttower/` path. Built-in MVP templates remain immutable code defaults; YAML overrides keep configuration scriptable.

**Alternatives considered**:
- SQLite-resident templates — over-engineered; templates change rarely.
- CLI-only template registration — operator cannot version-control their own templates.

---

## R9. Launch command profile storage

**Decision**: YAML files in `~/.config/opensoft/agenttower/launch_commands/*.yaml` with schema:

```yaml
name: claude-master
command: ["claude", "--model", "opus", "--system-prompt-file", "master.md"]
env:
  ANTHROPIC_LOG: warn
working_dir: /workspace
```

`command` is argv (list of strings); never a single string. Profiles referenced by `name` from templates and from operator overrides at create time.

**Rationale**: Argv shape forces Principle III safety. Matches constitution paths.

---

## R10. Idempotency-key behavior for create-layout

**Decision**: Optional `idempotency_key: str` field on the `managed.layout.create` / `app.managed_layout_create` request. When present, scope is `(container_id, idempotency_key)`. Behavior:

- **In-flight match** — return the current state of the existing layout (don't restart).
- **Completed match** — return the prior success or failure record verbatim.
- **Absent** — two calls produce two separate layouts; the FR-019 per-container serializer still prevents tmux-level conflicts.

The pending-managed marker token (R1) equals `idempotency_key` when present, else `uuid4()`.

**Rationale**: Mirrors the FEAT-011 `app.send_input` idempotency model. Collapses dedupe storage into the pending-marker storage.

---

## R11. Audit / lifecycle event retention (FR-021)

**Decision**: Reuse FEAT-008's JSONL audit pipeline. New event types:

- `managed_layout_created`, `managed_layout_state_changed`
- `managed_pane_created`, `managed_pane_state_changed`, `managed_pane_recreated`, `managed_pane_removed`
- `managed_pane_pending_marker_set`, `managed_pane_pending_marker_cleared`
- `managed_pane_launch_command_exited` (degraded), `managed_pane_log_attach_failed` (degraded)
- `managed_layout_recovery_reattached`, `managed_layout_recovery_failed`

No separate file. **No retention pruning in MVP** — pruning is a later feature; growth is operationally bounded as described in plan.md "Scale/Scope".

**Rationale**: Single observability surface; matches Principle IV.

---

## R12. Operator authorization (MVP)

**Decision**:

- `app.managed_*` — host-only via FEAT-011's bench-container peer gate. Returns `host_only` to bench-container callers.
- Legacy `managed.*` CLI namespace — reachable from bench-container thin clients, **but** the dispatcher validates that `request.container_id` matches the peer's own container (resolved via FEAT-009 peer detection). Cross-container calls from a thin client return `host_only`.
- No UID-match or per-container ACL in MVP. Captured in spec Assumptions.

**Rationale**: Matches FR-017 + spec Assumptions. Preserves the principle that a bench container can manage its own panes but cannot affect other containers.

---

## R13. State machine transition rules (formal)

**Decision**: see [contracts/state-machine.md](./contracts/state-machine.md). Summary:

| From | To | Trigger |
|---|---|---|
| `creating` | `ready` | Pane spawned + agent registered + log attach attempted (success or recoverable failure) |
| `creating` | `degraded` | Log attach failed (recoverable) OR launch command exited immediately (recoverable) |
| `creating` | `failed` | Pane create failed OR registration failed (non-recoverable for this record) |
| `ready` | `degraded` | Subsequent transient failure (log path lost, agent exited) |
| `ready` | `removed` | Operator `remove` |
| `degraded` | `removed` | Operator `remove` |
| `degraded` | `failed` | Subsequent non-recoverable failure |
| `failed` | `removed` | Operator `remove` (cleans up the record) |
| `removed` | — | Terminal — record is archived, recreate produces a new record |

Illegal transitions are rejected with `managed_pane_illegal_transition`. `promoted_from_adopted` is reserved and rejected with `not_implemented` in MVP.

**Rationale**: Maps directly onto the Q1/Q8/Q9 clarifications. Recovery from `degraded` to `ready` is **not** permitted in MVP — recovery is via `recreate`, which produces a fresh record linked by `predecessor_id`. This keeps the state graph acyclic and the audit story clean.

---

## Coverage summary

| Question / Gap source | Resolved in |
|---|---|
| Q1 distinct states | R13 |
| Q2 predecessor_id | R3, data-model.md |
| Q3 serialization | R2 |
| Q4 label uniqueness scope | R3, data-model.md |
| Q5 template pane count | R8 |
| Q6 SESSION_NAME_CONFLICT | contracts/error-codes.md |
| Q7 pending-managed marker | R1 |
| Q8 launch immediate-exit → degraded | R7, R13 |
| Q9 log attach failure → degraded | R7, R13 |
| Q10 daemon restart recovery | recovery.py + R5 sweep |
| Q11 tmux kill-pane on remove | R6 |
| Q12 indefinite audit retention | R11 |
| Q13 promote-from-adopted reserved | R13 + errors.py |
| Q14 socket-access authz | R12 |
| Q15 canonical "operator" term | spec.md (applied) |
| Checklist gap: failure-stage taxonomy | R7 |
| Checklist gap: chain-depth bound | R4 |
| Checklist gap: template schema | R8 |
| Checklist gap: launch profile schema | R9 |
| Checklist gap: idempotency key | R10 |
| Checklist gap: tmux command surface | R6 |
| Checklist gap: pending-marker TTL | R5 |
