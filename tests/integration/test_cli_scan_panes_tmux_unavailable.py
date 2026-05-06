"""End-to-end integration tests for `agenttower scan --panes` tmux-unavailable
paths (FEAT-004 US3 / FR-010 / SC-004).

Covers T035:

* "tmux: command not found" path — surfaced via ``id_u_failure`` on the fake
  fixture (per-container ``tmux_unavailable``). Prior pane rows MUST be
  preserved with ``active`` UNCHANGED and ``last_scanned_at`` advanced.
* "no server running" path — every socket returns
  ``FailedSocketScan(tmux_no_server)``; because no socket succeeded the
  container ends up in ``tmux_unavailable_containers`` (see
  ``_scan_one_container`` in ``src/agenttower/discovery/pane_service.py``).
* SC-004 daemon stays alive: after a degraded pane scan ``agenttower status``
  still reports ``alive=true``.
"""

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
    sockets: dict[str, object] | None = None,
    uid: str = "1000",
    id_u_failure: object | None = None,
) -> None:
    container_entry: dict[str, object] = {
        "uid": uid,
        "sockets": sockets if sockets is not None else {"default": []},
    }
    if id_u_failure is not None:
        container_entry["id_u_failure"] = id_u_failure
    path.write_text(
        json.dumps({"containers": {container_id: container_entry}}),
        encoding="utf-8",
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


def _read_pane_rows(home: Path) -> list[tuple[str, str, str, int, str]]:
    """Return ``(container_id, tmux_socket_path, tmux_pane_id, active, last_scanned_at)``."""
    paths = resolved_paths(home)
    conn = sqlite3.connect(str(paths["state_db"]))
    try:
        return conn.execute(
            "SELECT container_id, tmux_socket_path, tmux_pane_id, active, "
            "last_scanned_at FROM panes "
            "ORDER BY container_id, tmux_socket_path, tmux_pane_id"
        ).fetchall()
    finally:
        conn.close()


def test_tmux_unavailable_persists_degraded_scan_with_preserved_panes(
    env_with_fake, tmp_path: Path
) -> None:
    """FR-010 + SC-004 — `tmux: command not found` produces a degraded scan;
    prior pane rows survive with ``active`` unchanged and ``last_scanned_at``
    advanced."""
    env, docker_fake, home = env_with_fake
    container_id = "1" * 64
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

    baseline = _scan_panes(env)
    assert baseline.returncode == 0, baseline.stderr
    pre_rows = _read_pane_rows(home)
    assert pre_rows == [
        (container_id, "/tmp/tmux-1000/default", "%0", 1, pre_rows[0][4])
    ]
    pre_last_scanned = pre_rows[0][4]

    # Mutate fixture so `id -u` fails with tmux_unavailable
    # ("tmux: command not found").
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={"default": [_basic_pane("%0", pane_index=0, active=True)]},
        id_u_failure={
            "code": "tmux_unavailable",
            "message": "tmux: command not found",
        },
    )

    degraded = _scan_panes(env, json_mode=True)
    assert degraded.returncode == 5, degraded.stderr
    payload = json.loads(degraded.stdout.strip())
    assert payload["ok"] is True
    result = payload["result"]
    assert result["status"] == "degraded"
    assert result["containers_tmux_unavailable"] >= 1
    error_codes = {entry.get("error_code") for entry in result["error_details"]}
    assert "tmux_unavailable" in error_codes

    post_rows = _read_pane_rows(home)
    assert len(post_rows) == 1
    post = post_rows[0]
    # Prior pane row preserved; `active` unchanged.
    assert (post[0], post[1], post[2], post[3]) == (
        container_id,
        "/tmp/tmux-1000/default",
        "%0",
        1,
    )
    # `last_scanned_at` strictly advanced (FR-010).
    assert post[4] > pre_last_scanned, (
        f"expected last_scanned_at to advance: pre={pre_last_scanned!r} "
        f"post={post[4]!r}"
    )


def test_no_server_running_path_preserves_panes_and_marks_tmux_unavailable(
    env_with_fake, tmp_path: Path
) -> None:
    """FR-010 — every socket returning ``tmux_no_server`` puts the container
    into ``tmux_unavailable`` (no socket succeeded). Prior pane row is kept
    active and ``last_scanned_at`` advances."""
    env, docker_fake, home = env_with_fake
    container_id = "2" * 64
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

    baseline = _scan_panes(env)
    assert baseline.returncode == 0, baseline.stderr
    pre_rows = _read_pane_rows(home)
    assert pre_rows == [
        (container_id, "/tmp/tmux-1000/default", "%0", 1, pre_rows[0][4])
    ]
    pre_last_scanned = pre_rows[0][4]

    # The single `default` socket now fails with tmux_no_server. Because no
    # socket succeeds, _scan_one_container marks the container tmux_unavailable.
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={
            "default": {
                "failure": {
                    "code": "tmux_no_server",
                    "message": "no server running on /tmp/tmux-1000/default",
                }
            }
        },
    )

    degraded = _scan_panes(env, json_mode=True)
    assert degraded.returncode == 5, degraded.stderr
    payload = json.loads(degraded.stdout.strip())
    assert payload["ok"] is True
    result = payload["result"]
    assert result["status"] == "degraded"
    assert result["containers_tmux_unavailable"] >= 1

    post_rows = _read_pane_rows(home)
    assert len(post_rows) == 1
    post = post_rows[0]
    assert (post[0], post[1], post[2], post[3]) == (
        container_id,
        "/tmp/tmux-1000/default",
        "%0",
        1,
    )
    assert post[4] > pre_last_scanned, (
        f"expected last_scanned_at to advance: pre={pre_last_scanned!r} "
        f"post={post[4]!r}"
    )


def test_tmux_unavailable_does_not_crash_daemon(
    env_with_fake, tmp_path: Path
) -> None:
    """SC-004 — a degraded pane scan from `tmux: command not found` MUST NOT
    crash the daemon; subsequent ``agenttower status --json`` reports
    ``alive=true``."""
    env, docker_fake, _home = env_with_fake
    container_id = "3" * 64
    _write_docker_fake(docker_fake, container_id, "py-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={"default": [_basic_pane("%0", pane_index=0, active=True)]},
        id_u_failure={
            "code": "tmux_unavailable",
            "message": "tmux: command not found",
        },
    )
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)

    degraded = _scan_panes(env, json_mode=True)
    assert degraded.returncode == 5, degraded.stderr
    payload = json.loads(degraded.stdout.strip())
    assert payload["ok"] is True
    assert payload["result"]["status"] == "degraded"
    assert payload["result"]["containers_tmux_unavailable"] >= 1

    status = subprocess.run(
        ["agenttower", "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert status.returncode == 0, status.stderr
    status_payload = json.loads(status.stdout.strip())
    assert status_payload["ok"] is True
    assert status_payload["result"]["alive"] is True
