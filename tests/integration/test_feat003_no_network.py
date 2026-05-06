"""FEAT-003 no-network-listener guard (FR-021 / SC-007).

Equivalent to FEAT-002's `test_daemon_no_network.py`, but exercised
against a daemon that has the FEAT-003 dispatch table loaded (with
the new `scan_containers` and `list_containers` methods registered).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon_if_alive,
)


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


@pytest.fixture()
def env_with_fake(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    fake_path = tmp_path / "docker-fake.json"
    fake_path.write_text(
        json.dumps({"list_running": {"action": "ok", "containers": []}, "inspect": {"action": "ok"}}),
        encoding="utf-8",
    )
    env = isolated_env(home)
    env["AGENTTOWER_TEST_DOCKER_FAKE"] = str(fake_path)
    run_config_init(env)
    try:
        yield env, home
    finally:
        stop_daemon_if_alive(env)


def test_feat003_daemon_opens_no_inet_listener(env_with_fake) -> None:
    env, home = env_with_fake
    ensure_daemon(env)
    pid_path = resolved_paths(home)["pid_file"]
    deadline = time.monotonic() + 2.0
    pid: int | None = None
    while time.monotonic() < deadline:
        try:
            pid = int(pid_path.read_text(encoding="ascii").strip())
            break
        except (FileNotFoundError, ValueError):
            time.sleep(0.05)
    assert pid is not None, "daemon pid file never appeared"

    inodes = _socket_inodes_for_pid(pid)
    net = _read_proc_net(pid)

    # Each /proc/<pid>/net/* file lists sockets by inode in column 9.
    # Assert none of the daemon's socket inodes appear in tcp{,6} / udp{,6}
    # listings — i.e., the daemon owns only AF_UNIX sockets.
    for name, body in net.items():
        for line in body.splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 10:
                inode = cols[9]
                assert inode not in inodes, (
                    f"FEAT-003 daemon owns an {name} socket (inode={inode}) — "
                    "must be AF_UNIX only (FR-021)"
                )
