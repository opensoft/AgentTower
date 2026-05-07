"""End-to-end integration tests for FEAT-006 ``register-self`` (T037 / SC-001).

Exercises the full CLI → daemon → SQLite path with a real host daemon
under the FEAT-002 harness, FEAT-003 / FEAT-004 / FEAT-005 fakes, and
``$TMUX`` / ``$TMUX_PANE`` env injection. These tests cover the
critical happy path that proves all of Phase 3 wiring works end-to-end.

This is the SC-001 / SC-002 / SC-007 baseline integration test. It
intentionally combines several spec-listed integration tests into one
file (test_cli_register_self.py + test_cli_register_idempotent.py +
test_cli_list_agents.py) for compactness; the per-test functions still
map 1:1 to the spec's acceptance scenarios.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from ._daemon_helpers import ensure_daemon, resolved_paths


CONTAINER_ID = "abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
SHORT_ID = CONTAINER_ID[:12]
SOCKET_PATH = "/tmp/tmux-1000/default"  # NOSONAR - test fixture inside fake /proc tree
SESSION = "main"
PANE_ID = "%17"


def _write_docker_fake(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "list_running": {
                    "action": "ok",
                    "containers": [
                        {
                            "container_id": CONTAINER_ID,
                            "name": "bench-acme",
                            "image": "img",
                            "status": "running",
                        }
                    ],
                },
                "inspect": {
                    "action": "ok",
                    "results": [
                        {
                            "container_id": CONTAINER_ID,
                            "name": "bench-acme",
                            "image": "img",
                            "status": "running",
                            "config_user": "user",
                            "working_dir": "/workspace",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


def _write_tmux_fake(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "containers": {
                    CONTAINER_ID: {
                        "uid": "1000",
                        "sockets": {
                            "default": [
                                {
                                    "session_name": SESSION,
                                    "window_index": 0,
                                    "pane_index": 0,
                                    "pane_id": PANE_ID,
                                    "pane_pid": 12345,
                                    "pane_tty": "/dev/pts/0",
                                    "pane_current_command": "bash",
                                    "pane_current_path": "/workspace",
                                    "pane_title": "title",
                                    "pane_active": True,
                                }
                            ]
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def _write_proc_root(root: Path) -> None:
    """Materialize a fake /proc + /etc tree that puts FEAT-005 in-container."""
    (root / "proc" / "self").mkdir(parents=True, exist_ok=True)
    (root / "proc" / "1").mkdir(parents=True, exist_ok=True)
    (root / "etc").mkdir(parents=True, exist_ok=True)
    (root / "run").mkdir(parents=True, exist_ok=True)
    (root / ".dockerenv").write_text("")
    (root / "proc" / "self" / "cgroup").write_text(f"0::/docker/{CONTAINER_ID}\n")
    (root / "proc" / "1" / "cgroup").write_text(f"0::/docker/{CONTAINER_ID}\n")


def _setup_env(env_with_fake) -> tuple[dict, Path]:
    """Reuse the conftest ``env_with_fake`` fixture, then layer FEAT-006 fakes."""
    env, fake_path, home = env_with_fake
    _write_docker_fake(fake_path)
    tmux_fake = home.parent / "tmux-fake.json"
    _write_tmux_fake(tmux_fake)
    proc_root = home.parent / "proc-root"
    _write_proc_root(proc_root)
    env["AGENTTOWER_TEST_TMUX_FAKE"] = str(tmux_fake)
    env["AGENTTOWER_TEST_PROC_ROOT"] = str(proc_root)
    env["TMUX"] = f"{SOCKET_PATH},12345,$0"
    env["TMUX_PANE"] = PANE_ID
    env["AGENTTOWER_CONTAINER_ID"] = CONTAINER_ID
    return env, home


def _run_cli(env, *args, timeout: float = 10.0):
    return subprocess.run(
        ["agenttower", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_register_self_happy_path(env_with_fake) -> None:
    """SC-001: register-self from a simulated in-container env returns 0,
    prints the assigned agent_id, and persists exactly one new agents row."""
    env, home = _setup_env(env_with_fake)
    ensure_daemon(env)
    # First scan to seed FEAT-003 + FEAT-004 tables.
    _run_cli(env, "scan", "--containers")
    _run_cli(env, "scan", "--panes")

    proc = _run_cli(
        env,
        "register-self",
        "--role", "slave",
        "--capability", "codex",
        "--label", "codex-01",
        "--project", "/workspace/acme",
        "--json",
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    result = payload["result"]
    assert result["role"] == "slave"
    assert result["capability"] == "codex"
    assert result["label"] == "codex-01"
    assert result["project_path"] == "/workspace/acme"
    assert result["agent_id"].startswith("agt_")
    assert result["created_or_reactivated"] == "created"

    # Verify directly via SQLite.
    paths = resolved_paths(home)
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        rows = conn.execute("SELECT agent_id, role, label FROM agents").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0][0] == result["agent_id"]
    assert rows[0][1] == "slave"
    assert rows[0][2] == "codex-01"


def test_register_self_idempotent_returns_same_id(env_with_fake) -> None:
    """SC-002: re-running register-self from the same pane returns the
    same agent_id, leaves the row count at 1, and updates last_registered_at."""
    env, home = _setup_env(env_with_fake)
    ensure_daemon(env)
    _run_cli(env, "scan", "--containers")
    _run_cli(env, "scan", "--panes")

    first = json.loads(
        _run_cli(env, "register-self", "--role", "slave", "--json").stdout
    )["result"]
    second = json.loads(
        _run_cli(env, "register-self", "--role", "slave", "--json").stdout
    )["result"]
    assert second["agent_id"] == first["agent_id"]
    assert second["last_registered_at"] >= first["last_registered_at"]
    assert second["created_or_reactivated"] == "updated"
    paths = resolved_paths(home)
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    finally:
        conn.close()
    assert count == 1


def test_list_agents_tsv_has_required_columns(env_with_fake) -> None:
    """SC-007 + FR-029: list-agents default form has the locked
    nine-column TSV schema with required header row."""
    env, _home = _setup_env(env_with_fake)
    ensure_daemon(env)
    _run_cli(env, "scan", "--containers")
    _run_cli(env, "scan", "--panes")
    _run_cli(env, "register-self", "--role", "slave", "--label", "codex-01", "--json")

    proc = _run_cli(env, "list-agents")
    assert proc.returncode == 0
    lines = proc.stdout.strip().splitlines()
    assert (
        lines[0]
        == "AGENT_ID\tLABEL\tROLE\tCAPABILITY\tCONTAINER\tPANE\tPROJECT\tPARENT\tACTIVE"
    )
    fields = lines[1].split("\t")
    assert len(fields) == 9
    assert fields[1] == "codex-01"
    assert fields[2] == "slave"
    assert fields[4] == SHORT_ID  # 12-char short
    assert fields[7] == "-"        # PARENT null
    assert fields[8] == "true"


def test_register_self_master_rejected_e2e(env_with_fake) -> None:
    """SC-003 / FR-010: register-self --role master rejected end-to-end.

    The CLI does not expose ``--confirm`` on register-self (FR-010 makes
    confirm-bypass unreachable by surface design); the test exercises
    the daemon-side rejection path by passing ``--role master`` alone.
    """
    env, home = _setup_env(env_with_fake)
    ensure_daemon(env)
    _run_cli(env, "scan", "--containers")
    _run_cli(env, "scan", "--panes")

    proc = _run_cli(env, "register-self", "--role", "master", "--json")
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "master_via_register_self_rejected"

    paths = resolved_paths(home)
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    finally:
        conn.close()
    assert count == 0
