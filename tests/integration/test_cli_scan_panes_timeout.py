"""Integration tests for `agenttower scan --panes` timeout handling (FEAT-004 US3).

Covers T037 — FR-018 + SC-006:

* one container's ``id -u`` simulates a ``docker_exec_timeout`` while another
  container in the same scan succeeds. The faulty container is routed to
  ``tmux_unavailable_containers`` and the remaining container's panes are
  persisted normally;
* a ``docker_exec_timeout`` ``error_code`` appears in
  ``error_details[]`` for the failing container, with no ``tmux_socket_path``
  (the failure is at container scope, not socket scope);
* the daemon stays alive across the scan (``agenttower status`` still
  succeeds);
* per-call wall-clock budget for the whole faked pane scan is well under the
  5 s per-call docker-exec budget.

Note on "no orphaned children": the FakeTmuxAdapter (R-017) never spawns a
subprocess, so a terminate/wait counter is not directly observable here. The
operational signal that the timeout was handled cleanly is that the scan
returns within the per-call budget — the same fake-adapter-driven timeout
simulation pattern FEAT-003 used (R-016) and which keeps test latency
predictable.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from ._daemon_helpers import ensure_daemon, status


def _write_docker_fake_two(
    path: Path,
    container_a: str,
    name_a: str,
    container_b: str,
    name_b: str,
) -> None:
    path.write_text(
        json.dumps(
            {
                "list_running": {
                    "action": "ok",
                    "containers": [
                        {
                            "container_id": container_a,
                            "name": name_a,
                            "image": "img",
                            "status": "running",
                        },
                        {
                            "container_id": container_b,
                            "name": name_b,
                            "image": "img",
                            "status": "running",
                        },
                    ],
                },
                "inspect": {
                    "action": "ok",
                    "results": [
                        {
                            "container_id": container_a,
                            "name": name_a,
                            "image": "img",
                            "status": "running",
                            "config_user": "user",
                            "working_dir": "/workspace",
                        },
                        {
                            "container_id": container_b,
                            "name": name_b,
                            "image": "img",
                            "status": "running",
                            "config_user": "user",
                            "working_dir": "/workspace",
                        },
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


def _write_tmux_fake_two(
    path: Path,
    container_a: str,
    container_b: str,
    *,
    pane_for_b: dict,
) -> None:
    """Container *a* simulates a ``docker_exec_timeout`` on ``id -u``;
    container *b* succeeds with one pane on the default socket."""
    path.write_text(
        json.dumps(
            {
                "containers": {
                    container_a: {
                        "uid": "1000",
                        "id_u_failure": {
                            "code": "docker_exec_timeout",
                            "message": "docker exec exceeded 5.0s budget",
                        },
                        "sockets": {},
                    },
                    container_b: {
                        "uid": "1000",
                        "sockets": {"default": [pane_for_b]},
                    },
                }
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


# Two distinct 64-char-hex container ids so docker ps order is well-defined.
_CONTAINER_A = "a" * 64  # The container that times out on id -u.
_CONTAINER_B = "b" * 64  # The container that succeeds.


def _setup_two_container_fixture(env_with_fake, tmp_path: Path):
    env, docker_fake, home = env_with_fake
    _write_docker_fake_two(docker_fake, _CONTAINER_A, "a-bench", _CONTAINER_B, "b-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake_two(
        tmux_fake,
        _CONTAINER_A,
        _CONTAINER_B,
        pane_for_b=_basic_pane("%0", pane_index=0, active=True),
    )
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    _scan_containers(env)  # populate FEAT-003 active set with both containers
    return env, home


def test_timeout_on_one_container_yields_docker_exec_timeout_in_details(
    env_with_fake, tmp_path: Path
) -> None:
    """FR-018 — ``docker_exec_timeout`` appears in ``error_details`` for the
    failing container; the second container still scans successfully."""
    env, _home = _setup_two_container_fixture(env_with_fake, tmp_path)

    result = _scan_panes(env, json_mode=True)
    assert result.returncode == 5, result.stderr  # degraded, partial
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is True
    res = payload["result"]
    assert res["status"] == "degraded"
    assert res["containers_scanned"] == 2
    assert res["panes_seen"] == 1  # container b's single pane only
    assert res["containers_tmux_unavailable"] == 1  # container a

    timeout_entries = [
        e for e in res["error_details"] if e.get("error_code") == "docker_exec_timeout"
    ]
    assert timeout_entries, res["error_details"]
    timeout_entry = timeout_entries[0]
    assert timeout_entry["container_id"] == _CONTAINER_A
    # Container-scope failure (id -u) — no socket path.
    assert timeout_entry.get("tmux_socket_path") is None


def test_timeout_does_not_orphan_subsequent_containers(
    env_with_fake, tmp_path: Path
) -> None:
    """FR-018 — container b's pane is persisted with active=1 even though
    container a's id -u timed out earlier in the scan loop."""
    env, _home = _setup_two_container_fixture(env_with_fake, tmp_path)

    scan_result = _scan_panes(env, json_mode=True)
    assert scan_result.returncode == 5, scan_result.stderr

    list_result = _list_panes_json(env)
    assert list_result.returncode == 0, list_result.stderr
    panes = json.loads(list_result.stdout.strip())["result"]["panes"]
    b_panes = [p for p in panes if p["container_id"] == _CONTAINER_B]
    assert len(b_panes) == 1
    assert b_panes[0]["tmux_pane_id"] == "%0"
    assert b_panes[0]["active"] is True
    assert b_panes[0]["tmux_socket_path"] == "/tmp/tmux-1000/default"


def test_timeout_keeps_daemon_alive(env_with_fake, tmp_path: Path) -> None:
    """SC-006 — daemon must remain alive after a per-container timeout."""
    env, _home = _setup_two_container_fixture(env_with_fake, tmp_path)

    scan_result = _scan_panes(env, json_mode=True)
    assert scan_result.returncode == 5, scan_result.stderr

    status_result = status(env, json_mode=True)
    assert status_result.returncode == 0, status_result.stderr
    payload = json.loads(status_result.stdout.strip())
    assert payload["ok"] is True
    assert payload["result"]["alive"] is True


def test_per_call_budget_is_under_five_seconds(
    env_with_fake, tmp_path: Path
) -> None:
    """FR-018 / SC-006 — fully-faked timeout-bearing scan returns well under 5 s.

    The fake never sleeps; the timeout is simulated synchronously. This is the
    operational signal that the timeout was handled cleanly without spawning
    real subprocesses (R-017): no terminate/wait bookkeeping is needed because
    the fake adapter never forks a child.
    """
    env, _home = _setup_two_container_fixture(env_with_fake, tmp_path)

    start = time.monotonic()
    scan_result = _scan_panes(env, json_mode=True, timeout=10.0)
    elapsed = time.monotonic() - start
    assert scan_result.returncode == 5, scan_result.stderr
    assert elapsed < 5.0, (
        f"faked pane scan with one docker_exec_timeout took {elapsed:.2f}s; "
        "expected < 5.0 s per-call budget"
    )
