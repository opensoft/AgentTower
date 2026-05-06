"""FEAT-004 no-network-listener guard (FR-031).

Equivalent to FEAT-002's `test_daemon_no_network.py` and FEAT-003's
`test_feat003_no_network.py`, but exercised against a daemon that has
serviced the FEAT-004 dispatch paths (`scan_panes`, `list_panes`).

For each FEAT-004 surface (`scan --panes`, `list-panes`, and the combined
`scan --containers --panes`) we drive the CLI end-to-end against the fake
docker / tmux backends, then inspect ``/proc/<pid>/net/{tcp,tcp6,udp,udp6}``
and assert none of the daemon's socket inodes appear there. The daemon
must own only AF_UNIX sockets.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from ._daemon_helpers import ensure_daemon, resolved_paths


def _read_proc_net(pid: int) -> dict[str, str]:
    base = Path(f"/proc/{pid}/net")
    out: dict[str, str] = {}
    for name in ("tcp", "tcp6", "udp", "udp6"):
        path = base / name
        try:
            out[name] = path.read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError):
            out[name] = ""
    return out


def _socket_inodes_for_pid(pid: int) -> set[str]:
    fd_dir = Path(f"/proc/{pid}/fd")
    inodes: set[str] = set()
    try:
        entries = list(fd_dir.iterdir())
    except (FileNotFoundError, PermissionError):
        return inodes
    for fd in entries:
        try:
            target = fd.readlink() if hasattr(fd, "readlink") else Path(fd.resolve())
        except OSError:
            continue
        target_str = str(target)
        if target_str.startswith("socket:["):
            inodes.add(target_str[len("socket:[") : -1])
    return inodes


def _read_daemon_pid(home: Path, *, timeout: float = 2.0) -> int:
    pid_path = resolved_paths(home)["pid_file"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return int(pid_path.read_text(encoding="ascii").strip())
        except (FileNotFoundError, ValueError):
            time.sleep(0.05)
    raise AssertionError("daemon pid file never appeared")


def _assert_no_inet_sockets(pid: int, label: str) -> None:
    inodes = _socket_inodes_for_pid(pid)
    net = _read_proc_net(pid)
    # Each /proc/<pid>/net/* file lists sockets by inode in column 9.
    # Assert none of the daemon's socket inodes appear in tcp{,6} / udp{,6}
    # listings — i.e., the daemon owns only AF_UNIX sockets (FR-031).
    for name, body in net.items():
        for line in body.splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 10:
                inode = cols[9]
                assert inode not in inodes, (
                    f"FEAT-004 daemon owns an {name} socket "
                    f"(inode={inode}) after {label} — must be AF_UNIX only "
                    "(FR-031)"
                )


def _write_docker_fake(path: Path, container_id: str, name: str = "py-bench") -> None:
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


def _write_tmux_fake(path: Path, container_id: str) -> None:
    path.write_text(
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


def _set_tmux_fake(env: dict[str, str], path: Path) -> None:
    env["AGENTTOWER_TEST_TMUX_FAKE"] = str(path)


def _run_cli(env: dict[str, str], *args: str, timeout: float = 30.0):
    return subprocess.run(
        ["agenttower", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture()
def feat004_env(env_with_fake, tmp_path: Path):
    env, docker_fake, home = env_with_fake
    container_id = "c" * 64
    _write_docker_fake(docker_fake, container_id)
    tmux_fake = tmp_path / "tmux-fake.json"
    _write_tmux_fake(tmux_fake, container_id)
    _set_tmux_fake(env, tmux_fake)
    ensure_daemon(env)
    yield env, home, container_id


def test_scan_panes_does_not_open_af_inet_listener(feat004_env) -> None:
    """FR-031 — `scan --panes` must not cause the daemon to open AF_INET/AF_INET6 sockets."""
    env, home, _container_id = feat004_env
    # Populate FEAT-003 active set so scan --panes has something to walk.
    pre = _run_cli(env, "scan", "--containers", timeout=15.0)
    assert pre.returncode == 0, pre.stderr
    result = _run_cli(env, "scan", "--panes")
    assert result.returncode == 0, result.stderr

    pid = _read_daemon_pid(home)
    _assert_no_inet_sockets(pid, "scan --panes")


def test_list_panes_does_not_open_af_inet_listener(feat004_env) -> None:
    """FR-031 — `list-panes` must not cause the daemon to open AF_INET/AF_INET6 sockets."""
    env, home, _container_id = feat004_env
    # Seed the panes table so list-panes has rows to read.
    pre = _run_cli(env, "scan", "--containers", timeout=15.0)
    assert pre.returncode == 0, pre.stderr
    seed = _run_cli(env, "scan", "--panes")
    assert seed.returncode == 0, seed.stderr
    result = _run_cli(env, "list-panes", "--json", timeout=10.0)
    assert result.returncode == 0, result.stderr

    pid = _read_daemon_pid(home)
    _assert_no_inet_sockets(pid, "list-panes")


def test_combined_scan_does_not_open_af_inet_listener(feat004_env) -> None:
    """FR-031 — `scan --containers --panes` must not cause the daemon to open AF_INET/AF_INET6 sockets."""
    env, home, _container_id = feat004_env
    result = _run_cli(env, "scan", "--containers", "--panes")
    assert result.returncode == 0, result.stderr

    pid = _read_daemon_pid(home)
    _assert_no_inet_sockets(pid, "scan --containers --panes")
