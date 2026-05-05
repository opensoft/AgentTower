"""Verify FEAT-002 opens no AF_INET / AF_INET6 listener (T017 / FR-010 / SC-007).

Reads ``/proc/<pid>/net/tcp{,6}`` and ``/proc/<pid>/net/udp{,6}`` for the
daemon's pid and asserts there are zero LISTEN-state IPv4 / IPv6 sockets
attributable to its inode set.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon_if_alive,
)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


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


def _proc_rows(body: str) -> list[tuple[str, list[str]]]:
    rows: list[tuple[str, list[str]]] = []
    for line in body.splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 10:
            rows.append((line, cols))
    return rows


def _tcp_listener_violations(
    proc_net: dict[str, str], inodes: set[str]
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    for fname in ("tcp", "tcp6"):
        for line, cols in _proc_rows(proc_net[fname]):
            state = cols[3]
            inode = cols[9]
            if state == "0A" and inode in inodes:
                violations.append((fname, line))
    return violations


def _udp_socket_violations(
    proc_net: dict[str, str], inodes: set[str]
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    for fname in ("udp", "udp6"):
        for line, cols in _proc_rows(proc_net[fname]):
            if cols[9] in inodes:
                violations.append((fname, line))
    return violations


def test_daemon_opens_no_network_listener(env: dict[str, str]) -> None:
    run_config_init(env)
    proc = ensure_daemon(env, json_mode=True)
    assert proc.returncode == 0, proc.stderr
    pid = json.loads(proc.stdout)["pid"]

    proc_net = _read_proc_net(pid)
    inodes = _socket_inodes_for_pid(pid)
    tcp_violations = _tcp_listener_violations(proc_net, inodes)
    udp_violations = _udp_socket_violations(proc_net, inodes)

    # TCP state '0A' means LISTEN per net/tcp_states.h.
    assert not tcp_violations, (
        f"daemon pid {pid} owns LISTEN sockets: {tcp_violations!r}"
    )
    assert not udp_violations, f"daemon pid {pid} owns UDP sockets: {udp_violations!r}"
