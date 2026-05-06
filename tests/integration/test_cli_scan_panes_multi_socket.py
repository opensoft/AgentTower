"""End-to-end integration tests for multi-socket pane scans (FEAT-004 US2 / FR-011).

Covers T029:

* two sockets (`default` + `work`) with disjoint pane sets — union persisted,
  both `tmux_socket_path` values appear in `list-panes --json`;
* second scan with `work` removed inactivates only its panes (sibling-socket
  inactivation is scoped per-socket);
* second scan where `work` returns ``FailedSocketScan(tmux_no_server)`` keeps
  prior `work` panes unchanged with ``last_scanned_at`` advanced.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ._daemon_helpers import ensure_daemon


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


def _basic_pane(
    pane_id: str,
    *,
    pane_index: int,
    active: bool,
    session_name: str = "work",
) -> dict:
    return {
        "session_name": session_name,
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


def _list_panes_json(env, *, timeout: float = 5.0):
    return subprocess.run(
        ["agenttower", "list-panes", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _scan_kv(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def _two_socket_fixture(container_id: str) -> dict[str, object]:
    """Disjoint pane sets across two sockets; pane_id `%0` reused across sockets."""
    return {
        "default": [
            _basic_pane("%0", pane_index=0, active=True, session_name="main"),
            _basic_pane("%1", pane_index=1, active=False, session_name="main"),
            _basic_pane("%2", pane_index=2, active=False, session_name="main"),
        ],
        "work": [
            _basic_pane("%0", pane_index=0, active=True, session_name="work"),
            _basic_pane("%1", pane_index=1, active=False, session_name="work"),
        ],
    }


def test_scan_panes_two_sockets_union_persisted(env_with_fake, tmp_path: Path) -> None:
    """FR-011 — two sockets persist as the union; `tmux_socket_path` distinguishes rows."""
    env, docker_fake, _home = env_with_fake
    container_id = "a" * 64
    _write_docker_fake(docker_fake, container_id, "py-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(tmux_fake, container_id, sockets=_two_socket_fixture(container_id))
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)

    result = _scan_panes(env)
    assert result.returncode == 0, result.stderr
    by_key = _scan_kv(result.stdout)
    assert by_key["status"] == "ok"
    assert by_key["sockets_scanned"] == "2"
    assert by_key["panes_seen"] == "5"

    list_result = _list_panes_json(env)
    assert list_result.returncode == 0, list_result.stderr
    panes = json.loads(list_result.stdout.strip())["result"]["panes"]
    assert len(panes) == 5
    socket_paths = {p["tmux_socket_path"] for p in panes}
    assert socket_paths == {"/tmp/tmux-1000/default", "/tmp/tmux-1000/work"}

    # `%0` is reused — must appear once per socket with distinct socket paths.
    pane0_rows = [p for p in panes if p["tmux_pane_id"] == "%0"]
    assert len(pane0_rows) == 2
    assert {p["tmux_socket_path"] for p in pane0_rows} == {
        "/tmp/tmux-1000/default",
        "/tmp/tmux-1000/work",
    }


def test_scan_panes_socket_removed_inactivates_only_that_sockets_panes(
    env_with_fake, tmp_path: Path
) -> None:
    """FR-011 — removing one socket inactivates only its panes; siblings untouched."""
    env, docker_fake, _home = env_with_fake
    container_id = "b" * 64
    _write_docker_fake(docker_fake, container_id, "py-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(tmux_fake, container_id, sockets=_two_socket_fixture(container_id))
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)

    first = _scan_panes(env)
    assert first.returncode == 0, first.stderr
    assert _scan_kv(first.stdout)["panes_seen"] == "5"

    # Drop `work`; `default` unchanged.
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={
            "default": _two_socket_fixture(container_id)["default"],
        },
    )
    second = _scan_panes(env)
    assert second.returncode == 0, second.stderr
    by_key = _scan_kv(second.stdout)
    # The two `work` panes flipped to inactive; `default` rows are still active.
    assert by_key["panes_reconciled_inactive"] == "2"
    assert by_key["sockets_scanned"] == "1"

    list_result = _list_panes_json(env)
    panes = json.loads(list_result.stdout.strip())["result"]["panes"]
    # All 5 rows still present (no deletion under reconciliation — FR-008).
    assert len(panes) == 5
    by_socket: dict[str, list[dict]] = {}
    for pane in panes:
        by_socket.setdefault(pane["tmux_socket_path"], []).append(pane)
    default_panes = by_socket["/tmp/tmux-1000/default"]
    work_panes = by_socket["/tmp/tmux-1000/work"]
    assert len(default_panes) == 3
    assert len(work_panes) == 2
    assert all(p["active"] is True for p in default_panes)
    assert all(p["active"] is False for p in work_panes)


def test_scan_panes_failed_sibling_socket_preserves_prior_panes(
    env_with_fake, tmp_path: Path
) -> None:
    """FR-011 — `tmux_no_server` on one socket preserves prior panes on that socket;
    `last_scanned_at` advances on the still-healthy socket and the failed socket
    leaves its rows untouched (per FR-011 sibling preservation)."""
    env, docker_fake, _home = env_with_fake
    container_id = "c" * 64
    _write_docker_fake(docker_fake, container_id, "py-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(tmux_fake, container_id, sockets=_two_socket_fixture(container_id))
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)

    first = _scan_panes(env)
    assert first.returncode == 0, first.stderr
    assert _scan_kv(first.stdout)["panes_seen"] == "5"

    pre_panes = json.loads(_list_panes_json(env).stdout.strip())["result"]["panes"]
    work_pre_by_id = {
        p["tmux_pane_id"]: p
        for p in pre_panes
        if p["tmux_socket_path"] == "/tmp/tmux-1000/work"
    }
    assert set(work_pre_by_id.keys()) == {"%0", "%1"}

    # Make the `work` socket fail with tmux_no_server; `default` unchanged.
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={
            "default": _two_socket_fixture(container_id)["default"],
            "work": {
                "failure": {
                    "code": "tmux_no_server",
                    "message": "no server running on /tmp/tmux-1000/work",
                }
            },
        },
    )
    second = _scan_panes(env, json_mode=True)
    # Degraded scans exit `5` per contracts/cli.md §exit codes.
    assert second.returncode == 5, second.stderr
    payload = json.loads(second.stdout.strip())
    assert payload["ok"] is True
    assert payload["result"]["status"] == "degraded"
    # FR-011 sibling-preservation — failed sibling MUST NOT inactivate its own panes.
    assert payload["result"]["panes_reconciled_to_inactive"] == 0
    error_codes = {entry.get("error_code") for entry in payload["result"]["error_details"]}
    assert "tmux_no_server" in error_codes
    work_errors = [
        entry
        for entry in payload["result"]["error_details"]
        if entry.get("tmux_socket_path") == "/tmp/tmux-1000/work"
    ]
    assert work_errors and work_errors[0]["error_code"] == "tmux_no_server"

    post_panes = json.loads(_list_panes_json(env).stdout.strip())["result"]["panes"]
    work_post_by_id = {
        p["tmux_pane_id"]: p
        for p in post_panes
        if p["tmux_socket_path"] == "/tmp/tmux-1000/work"
    }
    # Both `work` panes still present and still active (sibling preservation).
    assert set(work_post_by_id.keys()) == {"%0", "%1"}
    assert all(p["active"] is True for p in work_post_by_id.values())
    # `last_scanned_at` advanced relative to the first scan.
    for pane_id, pre in work_pre_by_id.items():
        post = work_post_by_id[pane_id]
        assert post["last_scanned_at"] > pre["last_scanned_at"], (
            f"expected last_scanned_at to advance for {pane_id}: "
            f"pre={pre['last_scanned_at']!r} post={post['last_scanned_at']!r}"
        )
