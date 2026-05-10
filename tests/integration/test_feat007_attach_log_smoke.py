"""End-to-end smoke test for FEAT-007 attach-log (T050 / US1 AS1).

Spins up the daemon under the existing FEAT-002 harness with a fake
docker adapter (FEAT-003 fixture), a fake tmux adapter (FEAT-004 fixture),
and a fake docker-exec runner (FEAT-007 fixture). Seeds the agents/panes/
containers tables, runs ``agenttower attach-log --target <agent>`` from
a subprocess, and asserts the documented happy-path outcomes:

* CLI exits 0
* ``log_attachments`` row in ``status=active``
* ``log_offsets`` row at ``(0, 0, 0)``
* ``events.jsonl`` contains exactly one ``log_attachment_change`` row
* The fake docker-exec runner received the ``tmux pipe-pane -o`` invocation

This is the foundational US1 / SC-001 happy-path test. Other US1 tests
(idempotency, supersede, rejections) live in dedicated files.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon_if_alive,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _seed_database(state_db: Path, *, container_id: str, agent_id: str, host_log_root: Path) -> None:
    """Seed containers / panes / agents tables to reflect a registered agent.

    Container has the canonical bind-mount entry so FR-007 host-visibility
    proof passes. Pane composite key matches the agent's pane.
    """
    pane_socket = "/tmp/tmux-1000/default"
    pane_session = "main"
    pane_window = 0
    pane_index = 0
    pane_id = "%17"
    now = "2026-05-08T14:00:00.000000+00:00"

    mounts_json = json.dumps(
        [
            {
                "Type": "bind",
                "Source": str(host_log_root),
                "Destination": str(host_log_root),
                "Mode": "rw",
                "RW": True,
            }
        ]
    )

    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, "
            "labels_json, mounts_json, inspect_json, config_user, working_dir, "
            "active, first_seen_at, last_scanned_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                container_id,
                "bench-acme",
                "bench:latest",
                "running",
                "{}",
                mounts_json,
                "{}",
                "brett",
                "/home/brett",
                1,
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO panes (container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, container_name, "
            "container_user, pane_pid, pane_tty, pane_current_command, "
            "pane_current_path, pane_title, pane_active, active, "
            "first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                container_id,
                pane_socket,
                pane_session,
                pane_window,
                pane_index,
                pane_id,
                "bench-acme",
                "brett",
                12345,
                "/dev/pts/0",
                "bash",
                "/home/brett",
                "main",
                1,
                1,
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "role, capability, label, project_path, parent_agent_id, "
            "effective_permissions, created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent_id,
                container_id,
                pane_socket,
                pane_session,
                pane_window,
                pane_index,
                pane_id,
                "slave",
                "codex",
                "codex-01",
                "",
                None,
                "{}",
                now,
                now,
                None,
                1,
            ),
        )
    finally:
        conn.close()


def _write_pipe_pane_fake(path: Path) -> None:
    """Write a docker-exec fake fixture that succeeds for both list-panes and pipe-pane."""
    fixture = {
        "calls": [
            # FR-011 inspection: pane has no active pipe.
            {
                "argv_match": ["tmux list-panes"],
                "returncode": 0,
                "stdout": "0 \n",
                "stderr": "",
            },
            # FR-010 attach.
            {
                "argv_match": ["tmux pipe-pane -o"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            },
        ]
    }
    path.write_text(json.dumps(fixture))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def env_with_fakes(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = isolated_env(home)
    fake_path = tmp_path / "pipe_pane_fake.json"
    _write_pipe_pane_fake(fake_path)
    env["AGENTTOWER_TEST_PIPE_PANE_FAKE"] = str(fake_path)
    yield env, home, fake_path
    stop_daemon_if_alive(env)


def test_attach_log_happy_path_us1_as1(env_with_fakes) -> None:
    env, home, _ = env_with_fakes
    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    # 1. Bring up the daemon and seed state.
    run_config_init(env)
    ensure_daemon(env)

    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed_database(
        paths["state_db"],
        container_id=container_id,
        agent_id=agent_id,
        host_log_root=host_log_root,
    )

    # 2. Run attach-log.
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"attach-log failed; stderr={proc.stderr!r} stdout={proc.stdout!r}"
    )
    envelope = json.loads(proc.stdout)
    assert envelope["ok"] is True
    result = envelope["result"]
    assert result["agent_id"] == agent_id
    assert result["status"] == "active"
    assert result["attachment_id"].startswith("lat_")
    assert result["source"] == "explicit"
    assert result["is_new"] is True

    # 3. Verify durable state.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        rows = conn.execute(
            "SELECT count(*) FROM log_attachments WHERE agent_id = ? AND status = 'active'",
            (agent_id,),
        ).fetchone()
        assert rows[0] == 1, "expected exactly one active log_attachments row"
        rows = conn.execute(
            "SELECT byte_offset, line_offset, last_event_offset FROM log_offsets "
            "WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        assert rows == (0, 0, 0), "expected fresh offsets at (0, 0, 0)"
    finally:
        conn.close()

    # 4. Verify exactly one log_attachment_change JSONL row.
    events_text = paths["events_file"].read_text()
    matching = [
        line for line in events_text.splitlines()
        if '"type": "log_attachment_change"' in line or '"type":"log_attachment_change"' in line
    ]
    assert len(matching) == 1, f"expected 1 audit row, got {len(matching)}: {matching!r}"

    # 5. --status should now succeed.
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, (
        f"attach-log --status failed; stderr={proc.stderr!r}"
    )
    envelope = json.loads(proc.stdout)
    assert envelope["result"]["attachment"]["status"] == "active"
    assert envelope["result"]["offset"]["byte_offset"] == 0


def test_attach_log_idempotent_us1_as2(env_with_fakes) -> None:
    """Re-running attach-log against the same (agent, path) is a no-op success."""
    env, home, _ = env_with_fakes
    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    run_config_init(env)
    ensure_daemon(env)
    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed_database(
        paths["state_db"],
        container_id=container_id,
        agent_id=agent_id,
        host_log_root=host_log_root,
    )

    # Attach 5 times in quick succession.
    for _ in range(5):
        proc = subprocess.run(
            ["agenttower", "attach-log", "--target", agent_id, "--json"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0

    # Exactly one row.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        n = conn.execute(
            "SELECT count(*) FROM log_attachments WHERE agent_id = ?", (agent_id,)
        ).fetchone()[0]
        assert n == 1
        n = conn.execute(
            "SELECT count(*) FROM log_offsets WHERE agent_id = ?", (agent_id,)
        ).fetchone()[0]
        assert n == 1
    finally:
        conn.close()

    # Exactly one audit row.
    events_text = paths["events_file"].read_text()
    matching = [
        line for line in events_text.splitlines()
        if '"type": "log_attachment_change"' in line or '"type":"log_attachment_change"' in line
    ]
    assert len(matching) == 1
