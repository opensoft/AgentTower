"""End-to-end integration test for `agenttower scan --panes` (FEAT-004 US1)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from ._daemon_helpers import ensure_daemon, resolved_paths


def _write_docker_fake(path: Path, container_id: str, name: str) -> None:
    path.write_text(
        json.dumps(
            {
                "list_running": {
                    "action": "ok",
                    "containers": [
                        {
                            "container_id": container_id,
                            "name": name,
                            "image": "img",
                            "status": "running",
                        }
                    ],
                },
                "inspect": {
                    "action": "ok",
                    "results": [
                        {
                            "container_id": container_id,
                            "name": name,
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


def _write_tmux_fake(
    path: Path,
    container_id: str,
    *,
    sockets: dict[str, list[dict]] | None = None,
    uid: str = "1000",
) -> None:
    path.write_text(
        json.dumps(
            {
                "containers": {
                    container_id: {
                        "uid": uid,
                        "sockets": sockets or {"default": []},
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def _scan_panes(env, *, json_mode: bool = False, timeout: float = 30.0):
    cmd = ["agenttower", "scan", "--panes"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


def _scan_containers(env, *, timeout: float = 15.0):
    return subprocess.run(
        ["agenttower", "scan", "--containers"],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _basic_pane(pane_id: str, *, pane_index: int, active: bool) -> dict:
    return {
        "session_name": "work",
        "window_index": 0,
        "pane_index": pane_index,
        "pane_id": pane_id,
        "pane_pid": 1000 + pane_index,
        "pane_tty": f"/dev/pts/{pane_index}",
        "pane_current_command": "bash",
        "pane_current_path": "/workspace",
        "pane_title": f"user@bench [{pane_index}]",
        "pane_active": active,
    }


def _set_tmux_fake(env, fake_path: Path) -> None:
    env["AGENTTOWER_TEST_TMUX_FAKE"] = str(fake_path)


def test_scan_panes_default_summary(env_with_fake, tmp_path: Path) -> None:
    """SC-001 — single container with one socket and three panes."""
    env, docker_fake, home = env_with_fake
    container_id = "c" * 64
    _write_docker_fake(docker_fake, container_id, "py-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={
            "default": [
                _basic_pane("%0", pane_index=0, active=True),
                _basic_pane("%1", pane_index=1, active=False),
                _basic_pane("%2", pane_index=2, active=False),
            ]
        },
    )
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)  # populate FEAT-003 active set

    result = _scan_panes(env)
    assert result.returncode == 0, result.stderr
    by_key: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            by_key[k] = v
    assert by_key["status"] == "ok"
    assert by_key["containers_scanned"] == "1"
    assert by_key["sockets_scanned"] == "1"
    assert by_key["panes_seen"] == "3"
    assert by_key["panes_newly_active"] == "3"
    assert by_key["panes_reconciled_inactive"] == "0"
    assert by_key["containers_skipped_inactive"] == "0"
    assert by_key["containers_tmux_unavailable"] == "0"


def test_scan_panes_json_envelope_uses_alias_field_name(env_with_fake, tmp_path: Path) -> None:
    """FR-014 + data-model §6 note 5 — JSON wire uses panes_reconciled_to_inactive."""
    env, docker_fake, home = env_with_fake
    container_id = "a" * 64
    _write_docker_fake(docker_fake, container_id, "py-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={"default": [_basic_pane("%0", pane_index=0, active=True)]},
    )
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)

    result = _scan_panes(env, json_mode=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert payload["result"]["status"] == "ok"
    # Alias rename (data-model §6 note 5 / contracts/socket-api.md §3.2).
    assert "panes_reconciled_to_inactive" in payload["result"]
    assert "panes_reconciled_inactive" not in payload["result"]
    assert payload["result"]["error_details"] == []


def test_scan_panes_persists_pane_scans_row_and_panes_rows(
    env_with_fake, tmp_path: Path
) -> None:
    """SC-001 — exactly one pane_scans row + the expected panes rows."""
    env, docker_fake, home = env_with_fake
    container_id = "b" * 64
    _write_docker_fake(docker_fake, container_id, "py-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={"default": [_basic_pane("%0", pane_index=0, active=True)]},
    )
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)
    _scan_panes(env)

    paths = resolved_paths(home)
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        scan_rows = conn.execute(
            "SELECT status, containers_scanned, sockets_scanned, panes_seen FROM pane_scans"
        ).fetchall()
        pane_rows = conn.execute(
            "SELECT container_id, tmux_socket_path, tmux_pane_id, active FROM panes"
        ).fetchall()
    finally:
        conn.close()
    assert scan_rows == [("ok", 1, 1, 1)]
    assert pane_rows == [(container_id, "/tmp/tmux-1000/default", "%0", 1)]


def test_scan_panes_alias_round_trips_sqlite_to_json(
    env_with_fake, tmp_path: Path
) -> None:
    """T020 alias-assertion clause — SQLite short name == JSON long name byte-for-byte."""
    env, docker_fake, home = env_with_fake
    container_id = "d" * 64
    _write_docker_fake(docker_fake, container_id, "py-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={"default": [_basic_pane("%0", pane_index=0, active=True)]},
    )
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)
    json_result = _scan_panes(env, json_mode=True)
    payload = json.loads(json_result.stdout.strip())
    json_value = payload["result"]["panes_reconciled_to_inactive"]

    paths = resolved_paths(home)
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        sqlite_value = conn.execute(
            "SELECT panes_reconciled_inactive FROM pane_scans WHERE scan_id = ?",
            (payload["result"]["scan_id"],),
        ).fetchone()[0]
    finally:
        conn.close()
    assert sqlite_value == json_value


def test_scan_panes_reconciles_to_inactive_without_deletion(
    env_with_fake, tmp_path: Path
) -> None:
    """SC-002 — pane removed between scans flips active=0 and is NOT deleted."""
    env, docker_fake, home = env_with_fake
    container_id = "e" * 64
    _write_docker_fake(docker_fake, container_id, "py-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={
            "default": [
                _basic_pane("%0", pane_index=0, active=True),
                _basic_pane("%1", pane_index=1, active=False),
            ]
        },
    )
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)
    _scan_panes(env)

    # Remove %1 from the next scan.
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={"default": [_basic_pane("%0", pane_index=0, active=True)]},
    )
    result = _scan_panes(env)
    assert result.returncode == 0
    by_key: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            by_key[k] = v
    assert by_key["panes_reconciled_inactive"] == "1"

    paths = resolved_paths(home)
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        rows = conn.execute(
            "SELECT tmux_pane_id, active FROM panes ORDER BY tmux_pane_id"
        ).fetchall()
    finally:
        conn.close()
    # Both panes still present; %1 is now inactive.
    assert rows == [("%0", 1), ("%1", 0)]


def test_scan_panes_healthy_does_not_append_jsonl(env_with_fake, tmp_path: Path) -> None:
    """FR-025 — healthy pane scan MUST NOT append to events.jsonl."""
    env, docker_fake, home = env_with_fake
    container_id = "f" * 64
    _write_docker_fake(docker_fake, container_id, "py-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={"default": [_basic_pane("%0", pane_index=0, active=True)]},
    )
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)
    _scan_panes(env)
    paths = resolved_paths(home)
    events = paths["events_file"]
    if events.exists():
        text = events.read_text(encoding="utf-8")
        assert "pane_scan_degraded" not in text
