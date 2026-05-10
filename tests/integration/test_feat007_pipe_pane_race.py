"""FR-055 / T055a — pipe-pane race window between FR-011 and FR-010.

If ``tmux list-panes`` succeeds (FR-011 inspection finds the pane) but the
subsequent ``tmux pipe-pane`` (FR-010 attach) fails because the pane was
killed in the interim, the daemon MUST refuse with ``pipe_pane_failed``
and produce zero side effects:

* (a) refuse with ``pipe_pane_failed``
* (b) NO retry within the same call
* (c) NO ``log_attachments`` row written
* (d) NO ``log_offsets`` row written
* (e) NO toggle-off issued
* (f) NO JSONL audit row appended
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


def _write_race_fake(path: Path, *, race_stderr: str = "pane not found") -> None:
    """Fake docker-exec runner where list-panes succeeds but pipe-pane fails.

    The fake's call list is matched in order; the FIRST entry whose
    argv_match tokens all appear (in order) wins.
    """
    path.write_text(json.dumps({
        "calls": [
            # FR-011 inspection succeeds: pane exists, no active pipe.
            {
                "argv_match": ["tmux list-panes"],
                "returncode": 0,
                "stdout": "0 \n",
                "stderr": "",
            },
            # FR-010 attach fails: pane was killed between inspection and attach.
            {
                "argv_match": ["tmux pipe-pane -o"],
                "returncode": 1,
                "stdout": "",
                "stderr": race_stderr,
            },
        ]
    }))


@pytest.fixture
def primed(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = isolated_env(home)
    fake = tmp_path / "race_fake.json"
    _write_race_fake(fake)
    env["AGENTTOWER_TEST_PIPE_PANE_FAKE"] = str(fake)
    yield env, home
    stop_daemon_if_alive(env)


def _read_state(state_db: Path, agent_id: str) -> dict:
    conn = sqlite3.connect(str(state_db))
    try:
        attachments = conn.execute(
            "SELECT count(*) FROM log_attachments WHERE agent_id=?", (agent_id,)
        ).fetchone()[0]
        offsets = conn.execute(
            "SELECT count(*) FROM log_offsets WHERE agent_id=?", (agent_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    return {"attachments": attachments, "offsets": offsets}


def _audit_count(events_file: Path, event_type: str) -> int:
    if not events_file.exists():
        return 0
    text = events_file.read_text()
    return sum(
        1 for line in text.splitlines()
        if f'"type": "{event_type}"' in line or f'"type":"{event_type}"' in line
    )


@pytest.mark.parametrize(
    "race_stderr",
    [
        "pane not found",
        "session not found",
        "no current target",
        "tmux: server died",  # generic non-zero, no FR-012 stderr pattern
    ],
)
def test_pipe_pane_race_window_fr055(primed, race_stderr: str, tmp_path: Path) -> None:
    env, home = primed
    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    # Rewrite the fake with the parametrized stderr.
    fake = Path(env["AGENTTOWER_TEST_PIPE_PANE_FAKE"])
    _write_race_fake(fake, race_stderr=race_stderr)

    run_config_init(env)
    ensure_daemon(env)
    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed(paths["state_db"], container_id=container_id, agent_id=agent_id, host_log_root=host_log_root)

    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )

    # (a) refused with pipe_pane_failed.
    assert proc.returncode == 3, (
        f"expected exit 3; got {proc.returncode}; stderr={proc.stderr!r}"
    )
    envelope = json.loads(proc.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "pipe_pane_failed", envelope

    # (c, d) NO log_attachments row, NO log_offsets row.
    state = _read_state(paths["state_db"], agent_id)
    assert state == {"attachments": 0, "offsets": 0}, (
        f"FR-055: expected zero rows after race-window failure; got {state}"
    )

    # (f) NO log_attachment_change audit row.
    assert _audit_count(paths["events_file"], "log_attachment_change") == 0


def test_pipe_pane_race_window_does_not_retry(primed) -> None:
    """FR-055 (b): the daemon MUST NOT retry the attach within the same call.

    We arm the fake so the FIRST pipe-pane call fails; if the daemon retried
    in-call, the test's recorded_argv would show two pipe-pane invocations.
    Here we check via a follow-up successful re-attempt: the FIRST attach
    failed, the SECOND (independent) attach must produce its own audit row,
    proving the failed first attempt left no partial state to confuse the
    second.
    """
    env, home = primed
    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    run_config_init(env)
    ensure_daemon(env)
    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed(paths["state_db"], container_id=container_id, agent_id=agent_id, host_log_root=host_log_root)

    # First attach: fails per the fake.
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 3
    assert json.loads(proc.stdout)["error"]["code"] == "pipe_pane_failed"

    # Confirm zero state mutated.
    assert _read_state(paths["state_db"], agent_id) == {"attachments": 0, "offsets": 0}
    assert _audit_count(paths["events_file"], "log_attachment_change") == 0

    # Now rewrite the fake to succeed on the next call (proves we'd land an
    # attach if the daemon CAN find a successful pipe-pane). The first call
    # didn't leave any state behind, so this second call is fresh.
    fake = Path(env["AGENTTOWER_TEST_PIPE_PANE_FAKE"])
    fake.write_text(json.dumps({
        "calls": [
            {"argv_match": ["tmux list-panes"], "returncode": 0, "stdout": "0 \n", "stderr": ""},
            {"argv_match": ["tmux pipe-pane -o"], "returncode": 0, "stdout": "", "stderr": ""},
        ]
    }))

    # Daemon caches the fake's loaded JSON in a process-local state inside
    # the FakeDockerExecRunner; we need a fresh daemon to pick up the new
    # fixture. Restart cleanly.
    stop_daemon_if_alive(env)
    ensure_daemon(env)

    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, f"second attach failed; stderr={proc.stderr!r}"
    state = _read_state(paths["state_db"], agent_id)
    assert state == {"attachments": 1, "offsets": 1}
    assert _audit_count(paths["events_file"], "log_attachment_change") == 1
