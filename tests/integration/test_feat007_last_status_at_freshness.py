"""Regression test for Drift 7 — ``last_status_at`` freshness in attach JSON.

Pre-fix: ``attach-log --json`` for a stale/detached → active transition
returned the pre-mutation ``last_status_at`` from the in-memory record
snapshot, even though the daemon had just updated the row to ``now``.
A subsequent ``--status --json`` would correctly return the new
timestamp, exposing the inconsistency.

Post-fix: the attach response carries the post-mutation timestamp so
``attach-log --json`` and ``attach-log --status --json`` return the
same ``last_status_at`` for the same instant in time.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon_if_alive,
)


def _seed(state_db: Path, *, container_id: str, agent_id: str, host_log_root: Path) -> None:
    pane_socket = "/tmp/tmux-1000/default"
    now = "2026-05-08T14:00:00.000000+00:00"
    mounts_json = json.dumps([
        {"Type": "bind", "Source": str(host_log_root),
         "Destination": str(host_log_root), "RW": True},
    ])
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, "
            "labels_json, mounts_json, inspect_json, config_user, working_dir, "
            "active, first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (container_id, "bench-acme", "bench:latest", "running",
             "{}", mounts_json, "{}", "brett", "/home/brett",
             1, now, now),
        )
        conn.execute(
            "INSERT INTO panes (container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, "
            "tmux_pane_id, container_name, container_user, pane_pid, "
            "pane_tty, pane_current_command, pane_current_path, pane_title, "
            "pane_active, active, first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (container_id, pane_socket, "main", 0, 0, "%17",
             "bench-acme", "brett", 12345, "/dev/pts/0", "bash",
             "/home/brett", "main", 1, 1, now, now),
        )
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, "
            "tmux_pane_id, role, capability, label, project_path, "
            "parent_agent_id, effective_permissions, created_at, "
            "last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id, container_id, pane_socket, "main", 0, 0, "%17",
             "slave", "codex", "codex-01", "", None, "{}",
             now, now, None, 1),
        )
    finally:
        conn.close()


@pytest.fixture
def env_with_fakes(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = isolated_env(home)
    fake = tmp_path / "fake.json"
    fake.write_text(json.dumps({
        "calls": [
            {"argv_match": ["tmux list-panes"], "returncode": 0, "stdout": "0 \n", "stderr": ""},
            {"argv_match": ["tmux pipe-pane -o"], "returncode": 0, "stdout": "", "stderr": ""},
        ]
    }))
    env["AGENTTOWER_TEST_PIPE_PANE_FAKE"] = str(fake)
    yield env, home
    stop_daemon_if_alive(env)


def test_attach_response_carries_post_mutation_last_status_at(env_with_fakes) -> None:
    """Re-attach after detach must return the NEW last_status_at, not the
    pre-mutation snapshot from the in-memory ``existing`` record."""
    env, home = env_with_fakes
    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    run_config_init(env)
    ensure_daemon(env)
    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed(paths["state_db"], container_id=container_id, agent_id=agent_id, host_log_root=host_log_root)

    # Initial attach.
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    initial = json.loads(proc.stdout)["result"]
    initial_last_status_at = initial["last_status_at"]

    # Detach.
    proc = subprocess.run(
        ["agenttower", "detach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    detach_last_status_at = json.loads(proc.stdout)["result"]["last_status_at"]
    assert detach_last_status_at != initial_last_status_at, (
        "detach must advance last_status_at"
    )

    # Re-attach: the JSON envelope must carry the freshly-set timestamp.
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    reattach = json.loads(proc.stdout)["result"]
    reattach_last_status_at = reattach["last_status_at"]
    assert reattach["status"] == "active"
    assert reattach["prior_status"] == "detached"

    # Drift 7 fix: the re-attach response must NOT echo the detach timestamp.
    assert reattach_last_status_at != detach_last_status_at, (
        "Drift 7 regression: attach-log JSON returned the pre-mutation "
        "last_status_at instead of the post-mutation value."
    )

    # And it must agree with --status (both reflect the same daemon state).
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--status", "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    status_payload = json.loads(proc.stdout)["result"]
    assert (
        status_payload["attachment"]["last_status_at"]
        == reattach_last_status_at
    ), (
        "attach-log JSON and --status JSON disagree on last_status_at "
        "after the same transition; Drift 7 is regressing."
    )
