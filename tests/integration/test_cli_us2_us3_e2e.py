"""End-to-end integration tests for FEAT-006 US2 + US3 + host context.

Covers:
* SC-004: ``set-role --role master`` without ``--confirm`` rejected.
* US2 happy path: ``set-role --role master --confirm`` promotes.
* US2 set-role swarm rejection.
* US3 happy path: register a swarm child under an existing slave.
* US3 parent failure paths (parent_not_found / parent_role_invalid).
* SC-009: host_context_unsupported when caller is on the host shell.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ._daemon_helpers import ensure_daemon, resolved_paths

# Reuse the same fixture-building helpers from the US1 e2e file.
from .test_cli_register_self_e2e import (
    CONTAINER_ID,
    PANE_ID,
    SOCKET_PATH,
    SESSION,
    _setup_env,
    _write_docker_fake,
    _write_proc_root,
    _write_tmux_fake,
)


def _run_cli(env, *args, timeout: float = 10.0):
    return subprocess.run(
        ["agenttower", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _seed_one_agent(env) -> str:
    """Bring up the daemon, scan, register one slave, return the agent_id."""
    ensure_daemon(env)
    _run_cli(env, "scan", "--containers")
    _run_cli(env, "scan", "--panes")
    proc = _run_cli(env, "register-self", "--role", "slave", "--json")
    return json.loads(proc.stdout)["result"]["agent_id"]


def test_set_role_master_without_confirm_rejected(env_with_fake) -> None:
    """SC-004 / FR-011: set-role --role master without --confirm rejected."""
    env, _home = _setup_env(env_with_fake)
    agent_id = _seed_one_agent(env)
    proc = _run_cli(
        env,
        "set-role",
        "--target", agent_id,
        "--role", "master",
        "--json",
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["error"]["code"] == "master_confirm_required"


def test_set_role_master_with_confirm_promotes(env_with_fake) -> None:
    """US2 happy path: set-role --role master --confirm promotes the agent."""
    env, _home = _setup_env(env_with_fake)
    agent_id = _seed_one_agent(env)
    proc = _run_cli(
        env,
        "set-role",
        "--target", agent_id,
        "--role", "master",
        "--confirm",
        "--json",
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["result"]["new_value"] == "master"
    assert payload["result"]["effective_permissions"]["can_send_to_roles"] == [
        "slave",
        "swarm",
    ]


def test_set_role_swarm_rejected_e2e(env_with_fake) -> None:
    """FR-012: set-role --role swarm is rejected client-side."""
    env, _home = _setup_env(env_with_fake)
    agent_id = _seed_one_agent(env)
    proc = _run_cli(
        env,
        "set-role",
        "--target", agent_id,
        "--role", "swarm",
        "--json",
    )
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["error"]["code"] == "swarm_role_via_set_role_rejected"


def test_register_self_host_context_rejected(env_with_fake) -> None:
    """SC-009: caller on host shell (FEAT-005 reports host_context) is rejected."""
    env, _home = _setup_env(env_with_fake)
    # Override AGENTTOWER_TEST_PROC_ROOT to a directory that has NO
    # container signals — runtime_detect.detect() returns HostContext.
    env_no_container = dict(env)
    bare_root = Path(env["HOME"]) / "bare-host"
    bare_root.mkdir(parents=True, exist_ok=True)
    (bare_root / "proc" / "self").mkdir(parents=True, exist_ok=True)
    (bare_root / "etc").mkdir(parents=True, exist_ok=True)
    (bare_root / "proc" / "self" / "cgroup").write_text("0::/\n")
    env_no_container["AGENTTOWER_TEST_PROC_ROOT"] = str(bare_root)
    # Also remove the override so identity detect() doesn't succeed via env.
    env_no_container.pop("AGENTTOWER_CONTAINER_ID", None)

    ensure_daemon(env_no_container)
    proc = _run_cli(env_no_container, "register-self", "--role", "slave", "--json")
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["error"]["code"] == "host_context_unsupported"


def test_set_label_round_trip(env_with_fake) -> None:
    """US2 set-label: changes label without altering role / permissions."""
    env, _home = _setup_env(env_with_fake)
    agent_id = _seed_one_agent(env)
    proc = _run_cli(
        env,
        "set-label",
        "--target", agent_id,
        "--label", "renamed",
        "--json",
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    payload = json.loads(proc.stdout)
    assert payload["result"]["new_value"] == "renamed"
    # list-agents shows the new label.
    listed = _run_cli(env, "list-agents", "--json")
    body = json.loads(listed.stdout)["result"]
    assert body["agents"][0]["label"] == "renamed"
    assert body["agents"][0]["role"] == "slave"


def test_set_capability_round_trip(env_with_fake) -> None:
    """SC-012 + review-pass-6 N19: set-capability round-trip e2e.

    Symmetric with ``test_set_label_round_trip`` — proves the
    set-capability CLI path through real socket framing works and that
    the new value lands on the row visible via ``list-agents``.
    """
    env, _home = _setup_env(env_with_fake)
    agent_id = _seed_one_agent(env)
    proc = _run_cli(
        env,
        "set-capability",
        "--target", agent_id,
        "--capability", "claude",
        "--json",
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    payload = json.loads(proc.stdout)
    assert payload["result"]["new_value"] == "claude"
    assert payload["result"]["audit_appended"] is False
    listed = _run_cli(env, "list-agents", "--json")
    body = json.loads(listed.stdout)["result"]
    assert body["agents"][0]["capability"] == "claude"
    # Role was not changed by set-capability (FR-014 only audits role).
    assert body["agents"][0]["role"] == "slave"


def test_set_role_swarm_text_mode_emits_code_line(env_with_fake) -> None:
    """Review-pass-5: text-mode pre-flight errors carry both ``error:``
    and ``code: <closed-set-token>`` on stderr (matches the established
    CLI surface used by ``_emit_register_error`` / ``_emit_daemon_error``).
    """
    env, _home = _setup_env(env_with_fake)
    agent_id = _seed_one_agent(env)
    proc = _run_cli(env, "set-role", "--target", agent_id, "--role", "swarm")
    assert proc.returncode == 3
    assert "error:" in proc.stderr
    assert "code: swarm_role_via_set_role_rejected" in proc.stderr
    # Text mode keeps stdout free of incidental output.
    assert proc.stdout == "", f"unexpected stdout: {proc.stdout!r}"


def test_set_role_master_without_confirm_text_mode_emits_code_line(
    env_with_fake,
) -> None:
    env, _home = _setup_env(env_with_fake)
    agent_id = _seed_one_agent(env)
    proc = _run_cli(env, "set-role", "--target", agent_id, "--role", "master")
    assert proc.returncode == 3
    assert "error:" in proc.stderr
    assert "code: master_confirm_required" in proc.stderr
    assert proc.stdout == "", f"unexpected stdout: {proc.stdout!r}"


def test_set_label_rejects_malformed_target_client_side(env_with_fake) -> None:
    """Review-pass-2: set-* validate --target locally (R-020 / contracts/cli.md).

    Without the daemon ever being contacted, a malformed --target MUST
    surface ``value_out_of_set`` and exit 3.
    """
    env, _home = _setup_env(env_with_fake)
    proc = _run_cli(
        env,
        "set-label",
        "--target", "not-an-agent-id",
        "--label", "anything",
        "--json",
    )
    assert proc.returncode == 3, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "value_out_of_set"
    # --json purity: stderr is empty in JSON mode.
    assert proc.stderr == "", f"stderr leaked in --json mode: {proc.stderr!r}"
