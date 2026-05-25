# Quickstart: FEAT-013 Managed Session Creation and Lifecycle

**Feature**: 013-managed-session-lifecycle
**Audience**: developers integrating the daemon's new managed-layout surface; reviewers verifying the spec is buildable.

This quickstart walks through US1 (create a standard layout) end-to-end against a real `agenttowerd` plus a real bench container, then exercises US2 (managed agents share adopted surfaces) and US3 (remove + recreate). It assumes FEAT-001..FEAT-012 are merged and the daemon is healthy.

---

## Preconditions

1. `agenttowerd` is running and the Unix socket is listening at `~/.local/state/opensoft/agenttower/agenttowerd.sock` (constitution path).
2. A bench container is running and discovered: `agenttower container list` shows it with a known `container_id` (we'll use `bench-alpha` below).
3. The FEAT-011 app contract is reachable: `agenttower app preflight` returns `ok=true`.
4. Two operator YAML config files exist:
   - `~/.config/opensoft/agenttower/launch_commands/claude-master.yaml`:
     ```yaml
     name: claude-master
     command: ["bash", "-lc", "echo 'master ready'; exec bash"]
     ```
   - `~/.config/opensoft/agenttower/launch_commands/claude-worker.yaml`:
     ```yaml
     name: claude-worker
     command: ["bash", "-lc", "echo 'worker ready'; exec bash"]
     ```
   (Production usage swaps `bash` for `claude` / actual agent binaries; the bash placeholders make the quickstart deterministic.)
5. No tmux session named `session-quickstart` exists in `bench-alpha`.

---

## US1 — Create a "1 master + 2 slaves" layout

### 1. Send the create request

Using the synthetic NDJSON client (or `agenttower app send` once the helper exists):

```json
{"method": "app.managed_layout_create",
 "container_id": "bench-alpha",
 "template_name": "1m+2s",
 "tmux_session_name": "session-quickstart",
 "launch_command_overrides": {
     "master:m1": "claude-master",
     "slave:s1":  "claude-worker",
     "slave:s2":  "claude-worker"
 },
 "idempotency_key": "quickstart-001"}
```

Expected response (within ~200ms of acceptance — the response returns after row insertion, before tmux spawn completes):

```json
{"ok": true, "app_contract_version": "1.0", "result": {
    "layout_id": "01HZ-LAYOUT",
    "state": "creating",
    "intended_pane_count": 3,
    "panes": [
        {"pane_id": "01HZ-P1", "role": "master", "label": "m1", "state": "creating"},
        {"pane_id": "01HZ-P2", "role": "slave",  "label": "s1", "state": "creating"},
        {"pane_id": "01HZ-P3", "role": "slave",  "label": "s2", "state": "creating"}
    ]
}}
```

### 2. Wait for `ready`

Poll the layout detail until `state == "ready"` (or subscribe to lifecycle events). SC-001 budget: ≤ 120s.

```json
{"method": "app.managed_layout_detail", "layout_id": "01HZ-LAYOUT"}
```

After completion you should see:

```json
{"ok": true, "result": {
    "layout_id": "01HZ-LAYOUT",
    "state": "ready",
    "panes": [
        {"pane_id": "01HZ-P1", "state": "ready", "agent_id": "...", "log_attached": true,
         "tmux_session_name": "session-quickstart", "tmux_pane_index": 0},
        {"pane_id": "01HZ-P2", "state": "ready", "agent_id": "...", "log_attached": true},
        {"pane_id": "01HZ-P3", "state": "ready", "agent_id": "...", "log_attached": true}
    ]
}}
```

### 3. Verify in tmux

From inside the bench container:

```bash
tmux list-sessions
# session-quickstart: 1 windows ...

tmux list-panes -t session-quickstart -F '#{pane_index} #{pane_title}'
# 0 m1
# 1 s1
# 2 s2
```

Pane titles are `m1`, `s1`, `s2` — the `@MANAGED:...` prefix is **only** present during `creating`; it is cleared before `ready`.

### 4. Verify in the agent surfaces (US2)

Each created pane is now an agent in the FEAT-006 registry:

```json
{"method": "app.agent.list", "container_id": "bench-alpha"}
```

Expected: three agent rows with `origin == "managed"` and the same `tmux_session_name` / `tmux_pane_index` as the managed_pane rows. Sending input via the existing FEAT-009 `app.send_input` works the same as for adopted panes:

```json
{"method": "app.send_input", "agent_id": "<P2 agent_id>", "input": "echo hello\n"}
```

This satisfies US2 acceptance scenarios 1–3.

---

## US3 — Remove and recreate a managed pane

### 1. Remove

```json
{"method": "app.managed_pane_remove", "pane_id": "01HZ-P2"}
```

Response:

```json
{"ok": true, "result": {"pane_id": "01HZ-P2", "state": "removed"}}
```

Side effects:
- `tmux kill-pane -t session-quickstart:0.1` is invoked.
- The FEAT-007 log attachment is detached; the FEAT-010 routes pointing at this agent are removed.
- `managed_pane_removed` lifecycle event fires.
- The audit JSONL retains the record indefinitely (FR-021).

### 2. Try to remove an adopted pane (FR-012 negative case)

Suppose `bench-alpha` also has an adopted pane with `agent_id == "01HZ-ADOPTED"`:

```json
{"method": "app.managed_pane_remove", "pane_id": "01HZ-ADOPTED"}
```

Response:

```json
{"ok": true, "error": {"code": "managed_pane_protected_adopted", "message": "...",
                       "details": {"agent_id": "01HZ-ADOPTED", "is_adopted": true}}}
```

The adopted pane is unaffected. This satisfies US3 acceptance scenario 3.

### 3. Recreate

```json
{"method": "app.managed_pane_recreate", "predecessor_pane_id": "01HZ-P2",
 "launch_command_override": "claude-worker"}
```

Response:

```json
{"ok": true, "result": {"pane_id": "01HZ-P2b", "predecessor_id": "01HZ-P2", "chain_depth": 1, "state": "creating"}}
```

Poll until `ready`. Verify the chain:

```json
{"method": "app.managed_pane_detail", "pane_id": "01HZ-P2b", "include_predecessor_chain": true}
```

The response includes the predecessor chain (one element: `01HZ-P2` in `state == "removed"`). This satisfies US3 acceptance scenario 2.

---

## US3 — Daemon restart (SC-008)

Verify that the layout survives a daemon restart with no operator intervention.

### 1. Stop the daemon

```bash
systemctl --user stop agenttowerd
# or: kill $(cat ~/.local/state/opensoft/agenttower/agenttowerd.pid)
```

### 2. Confirm tmux panes are still alive

```bash
docker exec -u "$USER" bench-alpha tmux list-panes -t session-quickstart
# 0 1 2 — still there
```

### 3. Start the daemon

```bash
systemctl --user start agenttowerd
```

Within ~5s of the socket becoming ready (SC-008 target):

```json
{"method": "app.managed_layout_detail", "layout_id": "01HZ-LAYOUT"}
```

The layout is `ready`, all panes are `ready`, and the audit log contains a `managed_layout_recovery_reattached` event with the reattached pane ids. **No operator action was required.** SC-009 mandates this readability within 5 seconds of the socket becoming ready — no log inspection required, the detail surface alone tells the whole recovery story.

**If reattach failed for a pane** (e.g., its tmux backing was killed externally during the restart window), the same detail call surfaces the outcome directly:

```json
{"ok": true, "result": {
    "layout_id": "01HZ-LAYOUT",
    "state": "failed",
    "failed_stage": "recovery_reattach",
    "panes": [
        {"pane_id": "01HZ-P1", "state": "ready", ...},
        {"pane_id": "01HZ-P2b", "state": "failed", "failed_stage": "recovery_reattach", ...},
        {"pane_id": "01HZ-P3", "state": "ready", ...}
    ]
}}
```

The operator can then `app.managed_pane_recreate` against the failed pane to bring the layout back to `ready`.

---

## Edge cases worth exercising

| Edge case | Expected behavior |
|---|---|
| Two creates in the same container at the same time (FR-019) | Second blocks; both eventually return success in submission order. |
| Tmux session name already exists (FR-016 / Q6) | First returns `managed_session_name_conflict` with `tmux_session_name` in `details`. |
| Launch command exits within 1s (Q8) | Affected pane lands in `degraded`; layout `state == "degraded"`; `failed_stage = "launch_command"` on the pane. |
| Log path not host-readable (Q9) | Affected pane lands in `degraded`; layout `state == "degraded"`; `failed_stage = "log_attach"`. |
| Discovery scan fires during create (Q7) | Scan sees `@MANAGED:<token>` title prefix and skips the pane until registration clears the prefix. |
| Recreate chain hits depth 16 (FR-023, R4) | `managed_pane_recreate_chain_too_deep` with predecessor's chain_depth in `details`. |
| Daemon already holds 40 concurrent managed layouts; 41st request (FR-025) | `managed_layout_capacity_exceeded` with `{"current_count": 40, "limit": 40}` in `details`; operator removes an unused layout before retrying. |
| One pane fails mid-create-layout (FR-026) | Sibling in-flight panes continue to natural completion; the layout's aggregate state derives from the worst child (`failed` if any pane is `failed`, else `degraded`, else `ready`); no cascade-kill. |
| Two `app.managed_pane_recreate` requests target the same predecessor in flight (FR-027) | First proceeds; second returns `managed_pane_concurrent_recreate` with the in-flight successor's `pane_id`; operator polls `app.managed_pane_detail` on that id. |

Each of these is covered by a contract or integration test in `tests/contract/` and `tests/integration/`.

---

## Cleanup

```json
{"method": "app.managed_pane_remove", "pane_id": "01HZ-P1"}
{"method": "app.managed_pane_remove", "pane_id": "01HZ-P2b"}
{"method": "app.managed_pane_remove", "pane_id": "01HZ-P3"}
```

After all panes are `removed`, the layout transitions to `removed`. Audit records persist indefinitely (FR-021).

---

## What this quickstart does NOT cover (out of scope)

- Adopted-to-managed promotion (FR-018 / `not_implemented` stub).
- Custom drag-and-drop topology design (later feature; spec Assumptions).
- The control-panel UI itself (FEAT-012 / FEAT-014).
- Per-user or per-container ACL (later hardening feature; spec Assumptions).
- Retention pruning (later feature; FR-021 keeps history indefinitely in MVP).
