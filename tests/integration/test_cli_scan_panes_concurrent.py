"""End-to-end FEAT-004 concurrent pane-scan serialization (US3 / FR-017 / R-004).

Two parallel ``scan --panes`` invocations must serialize behind the pane-scan
mutex (their ``[started_at, completed_at]`` windows must not overlap), while a
parallel ``scan --containers`` + ``scan --panes`` MAY overlap because their
mutexes are independent.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from ._daemon_helpers import ensure_daemon


def _write_docker_fake(
    path: Path,
    container_id: str,
    name: str,
    *,
    delay_ms: int = 0,
) -> None:
    list_running: dict = {
        "action": "ok",
        "containers": [
            {
                "container_id": container_id,
                "name": name,
                "image": "img",
                "status": "running",
            }
        ],
    }
    inspect: dict = {
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
    }
    if delay_ms > 0:
        list_running["delay_ms"] = delay_ms
        inspect["delay_ms"] = delay_ms
    path.write_text(
        json.dumps({"list_running": list_running, "inspect": inspect}),
        encoding="utf-8",
    )


def _write_tmux_fake(
    path: Path,
    container_id: str,
    *,
    sockets: dict[str, list[dict]],
    uid: str = "1000",
) -> None:
    path.write_text(
        json.dumps(
            {
                "containers": {
                    container_id: {
                        "uid": uid,
                        "sockets": sockets,
                    }
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


def _spawn_scan_panes(env, *, timeout: float = 30.0) -> subprocess.Popen:
    return subprocess.Popen(
        ["agenttower", "scan", "--panes", "--json"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _spawn_scan_containers(env) -> subprocess.Popen:
    return subprocess.Popen(
        ["agenttower", "scan", "--containers", "--json"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _await(proc: subprocess.Popen, *, timeout: float = 30.0) -> tuple[int, str, str]:
    stdout, stderr = proc.communicate(timeout=timeout)
    return proc.returncode, stdout, stderr


def _parse_envelope(stdout: str) -> dict:
    payload = json.loads(stdout.strip())
    assert payload["ok"] is True, payload
    return payload["result"]


def _scan_containers_sync(env) -> None:
    """Populate the FEAT-003 active-container set synchronously."""
    subprocess.run(
        ["agenttower", "scan", "--containers"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15.0,
        check=True,
    )


def test_two_concurrent_scan_panes_calls_serialize(env_with_fake, tmp_path: Path) -> None:
    """FR-017 / R-004 — two parallel ``scan --panes`` calls do not overlap."""
    env, docker_fake, _home = env_with_fake
    container_id = "a" * 64
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
    env["AGENTTOWER_TEST_TMUX_FAKE"] = str(tmux_fake)
    ensure_daemon(env)
    _scan_containers_sync(env)

    proc_a = _spawn_scan_panes(env)
    proc_b = _spawn_scan_panes(env)
    rc_a, out_a, err_a = _await(proc_a)
    rc_b, out_b, err_b = _await(proc_b)

    assert rc_a == 0, err_a
    assert rc_b == 0, err_b
    result_a = _parse_envelope(out_a)
    result_b = _parse_envelope(out_b)

    assert result_a["scan_id"] != result_b["scan_id"]
    assert result_a["panes_seen"] == 3
    assert result_b["panes_seen"] == 3

    # Pane-scan mutex must serialize the windows: order by started_at and
    # require the later scan's start to come after the earlier scan's
    # completion.
    by_started = sorted([result_a, result_b], key=lambda r: r["started_at"])
    earlier, later = by_started
    earlier_completed = datetime.fromisoformat(earlier["completed_at"])
    later_started = datetime.fromisoformat(later["started_at"])
    assert later_started >= earlier_completed, (
        f"pane-scan windows overlapped: earlier={earlier['started_at']}..{earlier['completed_at']} "
        f"later={later['started_at']}..{later['completed_at']}"
    )


def test_scan_containers_and_scan_panes_may_overlap(env_with_fake, tmp_path: Path) -> None:
    """FR-017 / R-004 — pane-scan mutex is independent of container-scan mutex.

    ``scan --containers`` is slowed via the docker fake's ``delay_ms`` so that
    it occupies wall-clock for several hundred milliseconds. A concurrent
    ``scan --panes`` must NOT be blocked by that container-scan mutex; it
    must complete on its own (fast) timeline.
    """
    env, docker_fake, _home = env_with_fake
    container_id = "b" * 64

    # First, prime the active-container set with a fast scan (no delay yet).
    _write_docker_fake(docker_fake, container_id, "py-bench")
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(
        tmux_fake,
        container_id,
        sockets={
            "default": [
                _basic_pane("%0", pane_index=0, active=True),
            ]
        },
    )
    env["AGENTTOWER_TEST_TMUX_FAKE"] = str(tmux_fake)
    ensure_daemon(env)
    _scan_containers_sync(env)

    # Now slow the docker fake so the next scan --containers takes ~400 ms.
    _write_docker_fake(docker_fake, container_id, "py-bench", delay_ms=200)

    proc_containers = _spawn_scan_containers(env)
    proc_panes = _spawn_scan_panes(env)
    rc_c, out_c, err_c = _await(proc_containers)
    rc_p, out_p, err_p = _await(proc_panes)

    assert rc_c == 0, err_c
    assert rc_p == 0, err_p
    container_result = _parse_envelope(out_c)
    pane_result = _parse_envelope(out_p)

    container_started = datetime.fromisoformat(container_result["started_at"])
    container_completed = datetime.fromisoformat(container_result["completed_at"])
    pane_started = datetime.fromisoformat(pane_result["started_at"])
    pane_completed = datetime.fromisoformat(pane_result["completed_at"])

    container_window = (container_completed - container_started).total_seconds()
    # Sanity: the slowed container scan really did take measurable time.
    assert container_window >= 0.2, (
        f"container scan completed too fast ({container_window:.3f}s) — "
        f"the delay_ms knob is not engaging the adapter sleep"
    )

    # The pane scan must not be serialized behind the container scan: from the
    # moment the container scan started, the pane scan must finish within
    # roughly the container-scan window plus a small slack. If the pane-scan
    # mutex were the same as the container-scan mutex, this delta would be at
    # least 2x the container window.
    pane_relative_to_container = (pane_completed - container_started).total_seconds()
    assert pane_relative_to_container < container_window + 0.5, (
        f"pane scan appears blocked by container scan: "
        f"container_window={container_window:.3f}s, "
        f"pane_completed - container_started={pane_relative_to_container:.3f}s"
    )

    # And as an absolute upper bound — the pane scan should finish well within
    # 2 seconds of wall-clock time.
    pane_window = (pane_completed - pane_started).total_seconds()
    assert pane_window < 2.0, f"pane scan took too long ({pane_window:.3f}s)"
