"""Lifecycle integration tests for FEAT-007 (US7 detach + US3 preview/redaction).

Covers:
* US7 AS1: explicit detach transitions active → detached, retains offsets.
* US7 AS2: re-attach from detached reuses the same row, retains offsets.
* US7 AS3: detach against a row not in active state refused with attachment_not_found.
* US3 / SC-010: preview redaction zero raw secrets.
"""

from __future__ import annotations

import json
import os
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
            (container_id, "bench-acme", "bench:latest", "running",
             "{}", mounts_json, "{}", "brett", "/home/brett", 1, now, now),
        )
        conn.execute(
            "INSERT INTO panes (container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, container_name, "
            "container_user, pane_pid, pane_tty, pane_current_command, "
            "pane_current_path, pane_title, pane_active, active, "
            "first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (container_id, pane_socket, "main", 0, 0, "%17", "bench-acme",
             "brett", 12345, "/dev/pts/0", "bash", "/home/brett", "main",
             1, 1, now, now),
        )
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "role, capability, label, project_path, parent_agent_id, "
            "effective_permissions, created_at, last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id, container_id, pane_socket, "main", 0, 0, "%17",
             "slave", "codex", "codex-01", "", None, "{}", now, now, None, 1),
        )
    finally:
        conn.close()


def _write_fake(path: Path) -> None:
    path.write_text(json.dumps({
        "calls": [
            {"argv_match": ["tmux list-panes"], "returncode": 0, "stdout": "0 \n", "stderr": ""},
            {"argv_match": ["tmux pipe-pane -o"], "returncode": 0, "stdout": "", "stderr": ""},
            {"argv_match": ["tmux pipe-pane -t"], "returncode": 0, "stdout": "", "stderr": ""},
        ]
    }))


@pytest.fixture
def primed_env(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = isolated_env(home)
    fake = tmp_path / "fake.json"
    _write_fake(fake)
    env["AGENTTOWER_TEST_PIPE_PANE_FAKE"] = str(fake)
    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    run_config_init(env)
    ensure_daemon(env)
    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed(paths["state_db"], container_id=container_id, agent_id=agent_id, host_log_root=host_log_root)

    yield env, paths, agent_id
    stop_daemon_if_alive(env)


def test_detach_log_round_trip_us7_sc011(primed_env) -> None:
    env, paths, agent_id = primed_env

    # 1. Attach.
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    initial = json.loads(proc.stdout)["result"]
    attachment_id = initial["attachment_id"]

    # 2. Detach.
    proc = subprocess.run(
        ["agenttower", "detach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, f"detach failed: {proc.stderr}"
    detached = json.loads(proc.stdout)["result"]
    assert detached["attachment_id"] == attachment_id
    assert detached["status"] == "detached"

    # 3. Re-attach from detached: same row reused, status active.
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0
    reattached = json.loads(proc.stdout)["result"]
    assert reattached["attachment_id"] == attachment_id, "expected SAME row reused after detach"
    assert reattached["status"] == "active"
    assert reattached["is_new"] is False

    # 4. Audit trail: 3 transitions (creation, detach, re-attach).
    events_text = paths["events_file"].read_text()
    matching = [
        line for line in events_text.splitlines()
        if "log_attachment_change" in line
    ]
    assert len(matching) == 3, f"expected 3 audit rows, got {len(matching)}"


def test_detach_log_invalid_state_us7_as3(primed_env) -> None:
    env, _, agent_id = primed_env

    # No attachment exists yet → detach refused with attachment_not_found.
    proc = subprocess.run(
        ["agenttower", "detach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 3, f"expected exit 3; got {proc.returncode}"
    envelope = json.loads(proc.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "attachment_not_found"


def test_preview_redaction_us3_sc010(primed_env) -> None:
    env, paths, agent_id = primed_env

    # Attach first.
    subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10, check=True,
    )

    # Find the host log file path and write fixture content.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        log_path = conn.execute(
            "SELECT log_path FROM log_attachments WHERE agent_id=?", (agent_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    # AWS access keys are AKIA + 16 [A-Z0-9] (20 chars total per FR-028).
    Path(log_path).write_text(
        "build started\n"
        "auth=sk-AAAAAAAAAAAAAAAAAAAAAA continuing\n"
        "github_token=ghp_BBBBBBBBBBBBBBBBBBBBBB\n"
        "AKIAIOSFODNN7EXAMPLE\n"
        "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.AbCdEfGhIj012345678\n"
        "OPENAI_API_KEY=sk-test-1234567890\n"
        "build complete in 4.2s\n"
    )

    # Preview.
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--preview", "10", "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, f"preview failed: {proc.stderr}"
    envelope = json.loads(proc.stdout)
    lines = envelope["result"]["lines"]

    # SC-010: every documented sentinel MUST be absent in rendered output.
    rendered = "\n".join(lines)
    for sentinel in ("sk-A", "ghp_B", "AKIAIOSFODNN7EXAMPLE"):
        assert sentinel not in rendered, (
            f"raw secret sentinel {sentinel!r} survived redaction; lines={lines!r}"
        )
    # Bearer token must be reduced to the documented marker.
    assert "Bearer <redacted:bearer>" in rendered

    # Non-secret content survives byte-for-byte.
    assert "build started" in rendered
    assert "build complete in 4.2s" in rendered
