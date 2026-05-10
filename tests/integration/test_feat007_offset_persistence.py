"""US2 / SC-003 — log_offsets persist byte-for-byte across daemon restart.

Attach a log, advance the offset via the test seam, kill the daemon, restart
it, and assert the offset reads back identically.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from agenttower.state import log_offsets

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
        [{"Type": "bind", "Source": str(host_log_root), "Destination": str(host_log_root), "RW": True}]
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
            {"argv_match": ["tmux pipe-pane"], "returncode": 0, "stdout": "", "stderr": ""},
        ]
    }))


@pytest.fixture
def primed(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = isolated_env(home)
    fake = tmp_path / "fake.json"
    _write_fake(fake)
    env["AGENTTOWER_TEST_PIPE_PANE_FAKE"] = str(fake)
    yield env, home
    stop_daemon_if_alive(env)


def _read_offsets(state_db: Path, agent_id: str) -> tuple:
    conn = sqlite3.connect(str(state_db))
    try:
        row = conn.execute(
            "SELECT byte_offset, line_offset, last_event_offset, file_inode, "
            "file_size_seen FROM log_offsets WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
    finally:
        conn.close()
    return row


def test_offsets_persist_across_sigterm_restart(primed) -> None:
    env, home = primed
    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    # 1. Bring up daemon, seed, attach.
    run_config_init(env)
    ensure_daemon(env)
    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed(paths["state_db"], container_id=container_id, agent_id=agent_id, host_log_root=host_log_root)
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10, check=True,
    )
    log_path = json.loads(proc.stdout)["result"]["log_path"]

    # 2. Write a real log file matching the size we'll seed AND grab
    # its actual inode. The FEAT-008 events reader runs on every active
    # attachment per cycle and would observe a TRUNCATED state if the
    # stored size/inode didn't match the on-disk file — resetting the
    # offsets we just stored. Keeping them aligned makes the recovery
    # see UNCHANGED so the durability invariant we're testing here
    # (persistent offset rows survive a daemon restart) holds.
    Path(log_path).write_bytes(b"x" * 8192)
    real_stat = os.stat(log_path)
    real_inode = f"{real_stat.st_dev}:{real_stat.st_ino}"

    # 3. Advance offset via the test seam.
    conn = sqlite3.connect(str(paths["state_db"]), isolation_level=None)
    try:
        log_offsets.advance_offset_for_test(
            conn,
            agent_id=agent_id,
            log_path=log_path,
            byte_offset=4096,
            line_offset=137,
            last_event_offset=3200,
            file_inode=real_inode,
            file_size_seen=8192,
            last_output_at="2026-05-08T14:23:00.000000+00:00",
            timestamp="2026-05-08T14:23:00.000000+00:00",
        )
    finally:
        conn.close()

    # 4. Stop the daemon (SIGTERM via stop_daemon_if_alive) and re-launch.
    pre_restart = _read_offsets(paths["state_db"], agent_id)
    assert pre_restart == (4096, 137, 3200, real_inode, 8192)
    stop_daemon_if_alive(env)
    ensure_daemon(env)

    # 5. Verify offsets unchanged byte-for-byte.
    post_restart = _read_offsets(paths["state_db"], agent_id)
    assert post_restart == pre_restart, (
        f"offsets did not survive restart: pre={pre_restart!r} post={post_restart!r}"
    )


def test_offsets_persist_across_sigkill_restart(primed) -> None:
    env, home = primed
    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    run_config_init(env)
    ensure_daemon(env)
    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed(paths["state_db"], container_id=container_id, agent_id=agent_id, host_log_root=host_log_root)
    subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id],
        env=env, capture_output=True, text=True, timeout=10, check=True,
    )

    # Read attached path.
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        log_path = conn.execute(
            "SELECT log_path FROM log_attachments WHERE agent_id = ?", (agent_id,)
        ).fetchone()[0]
    finally:
        conn.close()

    # Match the on-disk file to the seeded offsets so the FEAT-008
    # reader sees UNCHANGED at restart (see SIGTERM-restart test for
    # rationale).
    Path(log_path).write_bytes(b"x" * 20000)
    real_stat = os.stat(log_path)
    real_inode = f"{real_stat.st_dev}:{real_stat.st_ino}"

    conn = sqlite3.connect(str(paths["state_db"]), isolation_level=None)
    try:
        log_offsets.advance_offset_for_test(
            conn,
            agent_id=agent_id,
            log_path=log_path,
            byte_offset=12345,
            line_offset=50,
            last_event_offset=10000,
            file_inode=real_inode,
            file_size_seen=20000,
            last_output_at="2026-05-08T14:23:00.000000+00:00",
            timestamp="2026-05-08T14:23:00.000000+00:00",
        )
    finally:
        conn.close()

    pre = _read_offsets(paths["state_db"], agent_id)

    # SIGKILL the daemon to exercise WAL durability.
    pid = int(paths["pid_file"].read_text().strip())
    os.kill(pid, signal.SIGKILL)
    # Wait for the process to actually exit so our restart isn't blocked
    # by the lock file that wasn't yet released.
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)

    ensure_daemon(env)
    post = _read_offsets(paths["state_db"], agent_id)
    assert post == pre, f"SIGKILL durability lost: pre={pre!r} post={post!r}"
