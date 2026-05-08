# Quickstart: Agent Registration and Role Metadata

**Branch**: `006-agent-registration` | **Date**: 2026-05-07

This walkthrough exercises the FEAT-006 surface end-to-end against
a host daemon and a single bench container. It complements
`spec.md` (US1, US2, US3 acceptance scenarios) and
`contracts/cli.md`. Every command shown here is a real
`agenttower` console-script invocation; no real Docker daemon or
real tmux server is required for the test-harness equivalent (see
§6).

---

## 0. Prerequisites

- The host daemon is running (`agenttower ensure-daemon` already
  succeeded; see FEAT-002 quickstart).
- At least one bench container has been discovered by FEAT-003
  (`agenttower scan --containers`; `agenttower list-containers`
  shows it).
- At least one tmux pane has been discovered inside that container
  by FEAT-004 (`agenttower scan --panes`; `agenttower list-panes`
  shows it).
- The user is shelled into the bench container and into the
  desired tmux pane. FEAT-005's identity detection will resolve
  the container id and pane composite key automatically.

You can verify the prerequisites with:

```bash
agenttower config doctor
```

All checks (`socket_resolved`, `socket_reachable`, `daemon_status`,
`container_identity`, `tmux_present`, `tmux_pane_match`) MUST be
`pass` before `register-self` is meaningful.

---

## 1. Register the current pane (US1 — happy path)

From inside the bench container, in the target tmux pane:

```bash
agenttower register-self \
    --role slave \
    --capability codex \
    --label codex-01 \
    --project /workspace/acme
```

Expected output (one `key=value` line per field on stdout, exit
`0`):

```text
agent_id=agt_abc123def456
role=slave
capability=codex
label=codex-01
project_path=/workspace/acme
parent_agent_id=-
created_or_reactivated=created
```

`parent_agent_id` renders as the literal `-` when null. The
`--json` form wraps the same fields under `{"ok": true, "result":
{...}}` (see `contracts/cli.md` for the full envelope).

A new row in the `agents` table now binds this pane composite key
to `agent_id=agt_abc123def456`. A JSONL audit row has been
appended to the daemon's `events.jsonl` with `prior_role: null`
and `new_role: slave` (Clarifications Q4).

---

## 2. List agents

```bash
agenttower list-agents
```

Default output (TSV with required header row, locked column
schema; Clarifications Q5):

```text
AGENT_ID	LABEL	ROLE	CAPABILITY	CONTAINER	PANE	PROJECT	PARENT	ACTIVE
agt_abc123def456	codex-01	slave	codex	abc123def456	main:0.0	/workspace/acme	-	true
```

JSON form:

```bash
agenttower list-agents --json
```

Returns the standard FEAT-006 envelope `{"ok": true, "result":
{...}}`, with `filter` and the `agents` array nested under
`result` and every field from `data-model.md` §4.1 / §6.4. See
`contracts/cli.md` C-CLI-602 for the full shape.

Filter examples:

```bash
agenttower list-agents --role slave
agenttower list-agents --container abc123def456 --active-only
agenttower list-agents --parent agt_abc123def456    # swarm children of this slave
```

---

## 3. Idempotent re-registration (US1 AS2 / AS3)

Re-running the same command from the same pane returns the same
`agent_id` and updates `last_registered_at`:

```bash
agenttower register-self --role slave --capability codex --label codex-01 --project /workspace/acme
```

Output (the same field block as the first registration, but
`created_or_reactivated=updated`):

```text
agent_id=agt_abc123def456
role=slave
capability=codex
label=codex-01
project_path=/workspace/acme
parent_agent_id=-
created_or_reactivated=updated
```

The agent count stays at 1; no new audit row is appended (the
role did not change).

Updating a single mutable field by passing only that flag (per
Clarifications Q1, omitted flags leave stored values
unchanged):

```bash
agenttower register-self --label codex-main
```

Output:

```text
agent_id=agt_abc123def456
role=slave
capability=codex
label=codex-main
project_path=/workspace/acme
parent_agent_id=-
created_or_reactivated=updated
```

`role`, `capability`, and `project_path` are preserved exactly
because `--role`, `--capability`, and `--project` were not
passed. This is the property that prevents a routine re-run from
silently demoting a master.

---

## 4. Promote to master (US2 — master safety boundary)

### 4.1 Reject promotion via `register-self` (FR-010)

`register-self` does not accept `--confirm` (the master safety
boundary is not unlocked at this surface in any way), so calling
it with `--role master` is refused unconditionally:

```bash
agenttower register-self --role master
```

Exit code `3` (FEAT-002 daemon-error convention); stderr:

```text
error: register-self cannot assign role=master; register first, then run `agenttower set-role --role master --confirm`
code: master_via_register_self_rejected
```

No agent row created; no audit row appended.

### 4.2 Reject `set-role --role master` without `--confirm` (FR-011)

```bash
agenttower set-role --target agt_abc123def456 --role master
```

Exit code `3`; stderr:

```text
error: master role assignment requires --confirm
code: master_confirm_required
```

Role unchanged.

### 4.3 Promote with `--confirm` (US2 AS1)

```bash
agenttower set-role --target agt_abc123def456 --role master --confirm
```

Exit code `0`; stdout (one `key=value` line per field):

```text
agent_id=agt_abc123def456
field=role
prior_value=slave
new_value=master
audit_appended=true
```

`agenttower list-agents` now shows `role=master`. The agent's
`effective_permissions.can_send_to_roles` is `["slave", "swarm"]`
(FR-021). One JSONL audit row was appended with
`confirm_provided: true`.

### 4.4 Demote from master (FR-013)

Demotion does NOT require `--confirm`:

```bash
agenttower set-role --target agt_abc123def456 --role slave
```

Exit code `0`; one audit row appended with `confirm_provided: false`.

---

## 5. Register a swarm child (US3)

A swarm child is a separate agent in a different tmux pane, bound
to a parent slave. The parent must exist, be active, and have
`role=slave` (FR-017).

In the swarm child's pane (a different pane, possibly in the same
container):

```bash
agenttower register-self \
    --role swarm \
    --parent agt_abc123def456 \
    --capability claude \
    --label claude-swarm-01
```

Output:

```text
agent_id=agt_def456abc789
role=swarm
capability=claude
label=claude-swarm-01
project_path=
parent_agent_id=agt_abc123def456
created_or_reactivated=created
```

`agenttower list-agents` now shows two rows; the swarm row has
`PARENT=agt_abc123def456`.

### 5.1 Swarm parent failure paths (US3 AS2..AS6)

| Command | Closed-set error code |
| ------- | --------------------- |
| `register-self --role swarm --parent agt_unknown123456 --capability claude` | `parent_not_found` |
| `register-self --role swarm --parent <slave-id> --capability claude` (where the parent is `active=false`) | `parent_inactive` |
| `register-self --role swarm --parent <master-id> --capability claude` | `parent_role_invalid` |
| `register-self --role swarm --capability claude` (no `--parent`) | `swarm_parent_required` |
| `register-self --role slave --parent <id>` | `parent_role_mismatch` |

### 5.2 Parent immutability (Clarifications Q3)

Re-running `register-self` with a *different* `--parent` value is
rejected:

```bash
agenttower register-self --role swarm --parent agt_otherSlave1234 --capability claude
```

Exit code `3`; stderr:

```text
error: parent_agent_id is immutable for life; stored value is agt_abc123def456
code: parent_immutable
```

No mutable field is updated by this call (Q3 atomicity).

Re-running with the *same* `--parent` is a no-op success:

```bash
agenttower register-self --role swarm --parent agt_abc123def456 --capability claude
```

Returns the same `agent_id`; updates `last_registered_at`; no
audit row.

---

## 6. Test-harness equivalent

Every command above can be exercised in the FEAT-002 daemon
harness without a real Docker daemon, real container, or real
tmux server (FR-044, SC-012). Set up:

```python
# tests/integration/test_cli_register_self.py (illustrative)
from . import _daemon_helpers as h

def test_register_self_happy_path(tmp_path, monkeypatch):
    with h.spawn_daemon(home=tmp_path) as daemon:
        h.seed_container(daemon, container_id="abc123def456...", name="bench-1", active=True)
        h.seed_pane(daemon, container_id="abc123def456...",
                    tmux_socket_path="/tmp/tmux-1000/default",
                    tmux_session_name="main",
                    tmux_window_index=0, tmux_pane_index=0,
                    tmux_pane_id="%17", active=True)
        # Simulate "running inside that container in that pane" via FEAT-005
        # test seam: AGENTTOWER_TEST_PROC_ROOT points at a fixture rooting
        # /proc/self/cgroup at the container id and seeding /etc/hostname.
        monkeypatch.setenv("AGENTTOWER_TEST_PROC_ROOT", str(h.proc_fixture_for(...)))
        monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,12345,$0")
        monkeypatch.setenv("TMUX_PANE", "%17")

        result = h.run_cli(["register-self", "--role", "slave",
                            "--capability", "codex",
                            "--label", "codex-01",
                            "--project", "/workspace/acme",
                            "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["agent_id"].startswith("agt_")
        assert payload["role"] == "slave"
        assert payload["created_or_reactivated"] == "created"
```

The same three test seams from FEAT-003 / FEAT-004 / FEAT-005
(`AGENTTOWER_TEST_DOCKER_FAKE`, `AGENTTOWER_TEST_TMUX_FAKE`,
`AGENTTOWER_TEST_PROC_ROOT`) cover every external surface
FEAT-006 exercises. No new test seam is introduced (R-013).

---

## 7. Cleanup

FEAT-006 introduces no `unregister` / `delete-agent` command —
that capability is deferred (FR-043). Agent rows persist with
`active=false` after the bound pane disappears (FR-009).
Re-running `register-self` from the same pane composite key
re-activates the existing row (FR-008).

To inspect the audit log:

```bash
tail -n 20 ~/.local/state/opensoft/agenttower/events.jsonl
```

Each successful role transition appears as one JSON line emitted
by the FEAT-001 `events.writer.append_event` helper. The on-disk
record shape is `{"ts": "<utc-iso>", "type": "agent_role_change",
"payload": {...}}` (FR-014; data-model.md §4.4).

---

## 8. Failure mode quick reference

The Symptom column already names the closed-set code, so a separate
column would be redundant. Codes inherit the FEAT-002 socket-API
contract — see `contracts/socket-api.md` §3 for the daemon-side
closed set; `daemon_unavailable` is the FEAT-002 CLI-side
classification (the daemon never received the call).

| Symptom | Likely cause |
| ------- | ------------ |
| `register-self` exits `2` (`daemon_unavailable`, FEAT-002 inheritance) | Daemon not running |
| `register-self` exits `1` with `host_context_unsupported` | Running on the host shell, not inside a bench container |
| `register-self` exits `3` with `not_in_tmux` | `$TMUX` unset |
| `register-self` exits `3` with `tmux_pane_malformed` | `$TMUX_PANE` malformed |
| `register-self` exits `3` with `container_unresolved` | FEAT-005 identity detection got `multi_match` / `no_match` / `no_candidate` |
| `register-self` exits `3` with `pane_unknown_to_daemon` | Pane composite key not in FEAT-004 registry; focused rescan did not find it; run `agenttower scan --panes` from the host |
| `set-role --role master` exits `3` with `master_confirm_required` | Forgot `--confirm` |
| `set-role --role swarm` exits `3` with `swarm_role_via_set_role_rejected` | Swarm role assignment requires `register-self --role swarm --parent <id>` |
| `register-self --role swarm` exits `3` with `swarm_parent_required` | Forgot `--parent <agent-id>` |
| `register-self --parent <id>` exits `3` with `parent_role_mismatch` | `--parent` requires `--role swarm` |
| Any CLI exits `3` with `schema_version_newer` | Daemon is newer than this CLI build; upgrade the CLI | |
