"""End-to-end integration test for `agenttower list-panes` (FEAT-004 US1)."""

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


def _set_fakes(env, *, docker_fake: Path, tmux_fake: Path) -> None:
    env["AGENTTOWER_TEST_DOCKER_FAKE"] = str(docker_fake)
    env["AGENTTOWER_TEST_TMUX_FAKE"] = str(tmux_fake)


def _scan_containers(env, *, timeout: float = 15.0):
    return subprocess.run(
        ["agenttower", "scan", "--containers"],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _scan_panes(env, *, timeout: float = 30.0):
    return subprocess.run(
        ["agenttower", "scan", "--panes"],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _list_panes(env, *args: str, timeout: float = 5.0):
    return subprocess.run(
        ["agenttower", "list-panes", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _seed(env, *, docker_fake: Path, tmux_fake: Path, container_id: str, name: str = "py-bench") -> None:
    _write_docker_fake(docker_fake, container_id, name)
    tmux_fake.write_text(
        json.dumps(
            {
                "containers": {
                    container_id: {
                        "uid": "1000",
                        "sockets": {
                            "default": [
                                _basic_pane("%0", pane_index=0, active=True),
                                _basic_pane("%1", pane_index=1, active=False),
                            ]
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _set_fakes(env, docker_fake=docker_fake, tmux_fake=tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)
    _scan_panes(env)


def test_list_panes_default_tsv_header_and_rows(env_with_fake, tmp_path: Path) -> None:
    env, docker_fake, _home = env_with_fake
    tmux_fake = tmp_path / "tmux-fake.json"
    _seed(env, docker_fake=docker_fake, tmux_fake=tmux_fake, container_id="g" * 64)
    result = _list_panes(env)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.rstrip("\n").splitlines()
    assert lines[0].split("\t") == [
        "ACTIVE",
        "FOCUSED",
        "CONTAINER",
        "SOCKET",
        "SESSION",
        "W",
        "P",
        "PANE_ID",
        "PID",
        "TTY",
        "COMMAND",
        "CWD",
        "LAST_SCANNED",
    ]
    body_rows = [line.split("\t") for line in lines[1:]]
    assert len(body_rows) == 2
    # FR-016 deterministic order: pane_index 0 then 1 within the same socket.
    assert [row[7] for row in body_rows] == ["%0", "%1"]


def test_list_panes_json_carries_full_fr006_fields(env_with_fake, tmp_path: Path) -> None:
    env, docker_fake, _home = env_with_fake
    tmux_fake = tmp_path / "tmux-fake.json"
    _seed(env, docker_fake=docker_fake, tmux_fake=tmux_fake, container_id="h" * 64)
    result = _list_panes(env, "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    assert payload["result"]["filter"] == "all"
    assert payload["result"]["container_filter"] is None
    assert len(payload["result"]["panes"]) == 2
    pane = payload["result"]["panes"][0]
    expected_keys = {
        "container_id", "container_name", "container_user",
        "tmux_socket_path", "tmux_session_name", "tmux_window_index",
        "tmux_pane_index", "tmux_pane_id", "pane_pid", "pane_tty",
        "pane_current_command", "pane_current_path", "pane_title",
        "pane_active", "active", "first_seen_at", "last_scanned_at",
    }
    assert expected_keys <= set(pane.keys())
    # data-model §6 note 1 — pane_active and active are distinct booleans.
    assert isinstance(pane["pane_active"], bool)
    assert isinstance(pane["active"], bool)


def test_list_panes_active_only_filter(env_with_fake, tmp_path: Path) -> None:
    env, docker_fake, _home = env_with_fake
    tmux_fake = tmp_path / "tmux-fake.json"
    container_id = "i" * 64
    _seed(env, docker_fake=docker_fake, tmux_fake=tmux_fake, container_id=container_id)

    # Mutate the fixture to drop %1 → second scan flips it to inactive.
    payload = json.loads(tmux_fake.read_text(encoding="utf-8"))
    payload["containers"][container_id]["sockets"]["default"] = [
        _basic_pane("%0", pane_index=0, active=True)
    ]
    tmux_fake.write_text(json.dumps(payload), encoding="utf-8")
    _scan_panes(env)

    # `list-panes` (no flag) shows both rows; `--active-only` hides the inactive one.
    all_rows = _list_panes(env, "--json")
    active_rows = _list_panes(env, "--active-only", "--json")
    all_payload = json.loads(all_rows.stdout.strip())["result"]["panes"]
    active_payload = json.loads(active_rows.stdout.strip())["result"]["panes"]
    assert len(all_payload) == 2
    assert len(active_payload) == 1
    assert active_payload[0]["tmux_pane_id"] == "%0"
    assert active_payload[0]["active"] is True


def test_list_panes_container_filter_unknown_returns_empty_with_zero(
    env_with_fake, tmp_path: Path
) -> None:
    env, docker_fake, _home = env_with_fake
    tmux_fake = tmp_path / "tmux-fake.json"
    _seed(env, docker_fake=docker_fake, tmux_fake=tmux_fake, container_id="j" * 64)
    result = _list_panes(env, "--container", "does-not-exist", "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout.strip())
    assert payload["result"]["panes"] == []
    assert payload["result"]["container_filter"] == "does-not-exist"


def test_list_panes_container_filter_by_exact_name(env_with_fake, tmp_path: Path) -> None:
    env, docker_fake, _home = env_with_fake
    tmux_fake = tmp_path / "tmux-fake.json"
    _seed(
        env,
        docker_fake=docker_fake,
        tmux_fake=tmux_fake,
        container_id="k" * 64,
        name="py-bench",
    )
    result = _list_panes(env, "--container", "py-bench", "--json")
    assert result.returncode == 0
    panes = json.loads(result.stdout.strip())["result"]["panes"]
    assert len(panes) == 2
    assert all(pane["container_name"] == "py-bench" for pane in panes)
