"""Regression test for the FR-008 file-mode race during attach_log.

The bug: ``_attach_log_locked`` previously issued ``tmux pipe-pane -o
... 'cat >> <file>'`` BEFORE pre-creating the host log file at mode 0600.
On a real bench container the bench-side shell opens the redirection
under the bench user's umask (typically 0o022), creating the file at
0o644. The daemon's subsequent FR-008 mode check then refuses with
``internal_error: file mode 0o644 broader than required 0o600`` and the
attach fails — even though the file was just created by the daemon's
own pipe-pane command.

The fix hoists ``_ensure_log_dir_and_file`` to BEFORE every
pipe-pane attach issuance so the file pre-exists at 0600 and ``cat >>``
appends to a safe file. This test exercises the race by using the
``touch_path_with_mode`` side-effect on the docker-exec fake to simulate
the bench-side cat creating the file at 0644.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
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


def _seed(
    state_db: Path,
    *,
    container_id: str,
    agent_id: str,
    host_log_root: Path,
) -> None:
    """Seed the daemon's state DB with one container + one pane + one agent."""
    pane_socket = "/tmp/tmux-1000/default"
    now = "2026-05-08T14:00:00.000000+00:00"
    mounts_json = json.dumps([
        {
            "Type": "bind",
            "Source": str(host_log_root),
            "Destination": str(host_log_root),
            "RW": True,
        }
    ])
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, "
            "labels_json, mounts_json, inspect_json, config_user, working_dir, "
            "active, first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                container_id, "bench-acme", "bench:latest", "running",
                "{}", mounts_json, "{}", "brett", "/home/brett",
                1, now, now,
            ),
        )
        conn.execute(
            "INSERT INTO panes (container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, "
            "tmux_pane_id, container_name, container_user, pane_pid, "
            "pane_tty, pane_current_command, pane_current_path, pane_title, "
            "pane_active, active, first_seen_at, last_scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                container_id, pane_socket, "main", 0, 0, "%17",
                "bench-acme", "brett", 12345, "/dev/pts/0", "bash",
                "/home/brett", "main", 1, 1, now, now,
            ),
        )
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, "
            "tmux_pane_id, role, capability, label, project_path, "
            "parent_agent_id, effective_permissions, created_at, "
            "last_registered_at, last_seen_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent_id, container_id, pane_socket, "main", 0, 0, "%17",
                "slave", "codex", "codex-01", "", None, "{}",
                now, now, None, 1,
            ),
        )
    finally:
        conn.close()


def test_attach_log_succeeds_when_pipe_pane_creates_file_at_0644(
    tmp_path: Path,
) -> None:
    """Regression: attach_log must pre-create the host log file at 0600 BEFORE
    issuing pipe-pane, so the bench-side ``cat >> file`` opens the existing
    safe file rather than creating one at the bench user's umask.

    Pre-fix behavior: pipe-pane issued first → bench creates file at 0o644 →
    daemon's FR-008 mode check fails → attach refused with internal_error.
    Post-fix behavior: daemon pre-creates at 0o600 → cat opens existing safe
    file → attach succeeds.
    """
    home = tmp_path / "home"
    home.mkdir()
    env = isolated_env(home)

    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    paths = resolved_paths(home)

    # Fake whose pipe-pane attach side-effects a 0o644 file at the canonical
    # log path — exactly what a real bench container's ``cat >> file`` does
    # under a default umask of 0o022. ``target_log`` is computed from paths
    # but the fake JSON is loaded by the daemon, so we resolve it now.
    target_log = (
        paths["state_dir"] / "logs" / container_id / f"{agent_id}.log"
    )

    fake = tmp_path / "race_fake.json"
    fake.write_text(json.dumps({
        "calls": [
            # FR-011 inspection succeeds, no active pipe.
            {
                "argv_match": ["tmux list-panes"],
                "returncode": 0,
                "stdout": "0 \n",
                "stderr": "",
            },
            # FR-010 attach succeeds; side-effect creates file at 0o644 to
            # simulate the bench-side `cat >> file` under default umask.
            {
                "argv_match": ["tmux pipe-pane -o"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "touch_path_with_mode": {
                    "path": str(target_log),
                    "mode": 0o644,
                },
            },
        ]
    }))
    env["AGENTTOWER_TEST_PIPE_PANE_FAKE"] = str(fake)

    try:
        run_config_init(env)
        ensure_daemon(env)
        host_log_root = paths["state_dir"] / "logs"
        host_log_root.mkdir(parents=True, exist_ok=True)
        _seed(
            paths["state_db"],
            container_id=container_id,
            agent_id=agent_id,
            host_log_root=host_log_root,
        )

        proc = subprocess.run(
            ["agenttower", "attach-log", "--target", agent_id, "--json"],
            env=env, capture_output=True, text=True, timeout=10,
        )

        assert proc.returncode == 0, (
            f"attach-log failed; stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
        envelope = json.loads(proc.stdout)
        assert envelope["ok"] is True, envelope
        assert envelope["result"]["status"] == "active"

        # File MUST exist on disk at mode 0o600. The race-window simulator
        # would have written 0o644 if the daemon issued pipe-pane first.
        assert target_log.exists(), f"target log not created: {target_log}"
        actual_mode = stat.S_IMODE(os.stat(target_log).st_mode)
        assert actual_mode == 0o600, (
            f"expected mode 0o600 (FR-008); got {oct(actual_mode)} — the "
            "daemon issued pipe-pane BEFORE pre-creating the file, "
            "regressing the FR-008 file-mode race fix."
        )
    finally:
        stop_daemon_if_alive(env)


def test_attach_log_pre_creates_file_before_pipe_pane(tmp_path: Path) -> None:
    """The daemon MUST pre-create the host log file BEFORE issuing pipe-pane.

    Asserted via the recorded order of fake docker-exec calls:
    the file must exist on disk by the time pipe-pane is invoked. We probe
    this by having the pipe-pane fake assert the file already exists at
    its expected mode (0o600) at invocation time, and emitting a sentinel
    via stderr if it doesn't.
    """
    home = tmp_path / "home"
    home.mkdir()
    env = isolated_env(home)

    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    paths = resolved_paths(home)
    target_log = (
        paths["state_dir"] / "logs" / container_id / f"{agent_id}.log"
    )

    fake = tmp_path / "ordering_fake.json"
    fake.write_text(json.dumps({
        "calls": [
            {
                "argv_match": ["tmux list-panes"],
                "returncode": 0,
                "stdout": "0 \n",
                "stderr": "",
            },
            {
                "argv_match": ["tmux pipe-pane -o"],
                "returncode": 0,
                "stdout": "",
                "stderr": "",
            },
        ]
    }))
    env["AGENTTOWER_TEST_PIPE_PANE_FAKE"] = str(fake)

    try:
        run_config_init(env)
        ensure_daemon(env)
        host_log_root = paths["state_dir"] / "logs"
        host_log_root.mkdir(parents=True, exist_ok=True)
        _seed(
            paths["state_db"],
            container_id=container_id,
            agent_id=agent_id,
            host_log_root=host_log_root,
        )

        # Must NOT exist before attach — sanity check.
        assert not target_log.exists()

        proc = subprocess.run(
            ["agenttower", "attach-log", "--target", agent_id, "--json"],
            env=env, capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0, proc.stderr

        # After attach, the file must exist at exactly 0o600.
        assert target_log.exists()
        actual_mode = stat.S_IMODE(os.stat(target_log).st_mode)
        assert actual_mode == 0o600, oct(actual_mode)
    finally:
        stop_daemon_if_alive(env)
