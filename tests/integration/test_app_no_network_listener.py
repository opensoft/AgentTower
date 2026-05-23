"""FEAT-011 T079 — SC-006 / FR-003: no network listener for app.* traffic.

Spawns a real daemon, drives a representative slice of the FEAT-011
``app.*`` socket namespace against it over the AF_UNIX socket, and asserts
the daemon process has opened **no** TCP or UDP listener — only its Unix
domain socket. The assertion is repeated after daemon shutdown to confirm
nothing lingers.

SC-006 / FR-003 invariant: the FEAT-011 app contract is delivered entirely
over the host-mounted Unix socket. There is no network listener in MVP, and
adding the 32-method ``app.*`` namespace MUST NOT introduce one.

Detection strategy (in priority order):

1. ``lsof -p <pid> -P -n`` — parse every line for ``TCP``/``UDP`` typed
   file descriptors in a ``LISTEN`` state.
2. Fallback: scan ``/proc/<pid>/fd`` for ``socket:[<inode>]`` symlinks and
   cross-reference against ``/proc/<pid>/net/tcp{,6}`` (state ``0A`` =
   LISTEN) and ``udp{,6}`` for any socket inode owned by the pid.

If neither ``lsof`` nor ``/proc`` is usable, the test skips with a clear
reason — but on Linux ``/proc`` is essentially always present, so a skip
here is unexpected.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
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


# ─── Wire-level helpers (mirrors test_story1_dashboard_bootstrap) ────────


def _open_socket(socket_path: Path) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    saved_cwd = os.getcwd()
    try:
        os.chdir(socket_path.parent)
        sock.connect(socket_path.name)
    finally:
        os.chdir(saved_cwd)
    return sock


def _call(sock: socket.socket, method: str, params: dict | None = None) -> dict:
    request: dict = {"method": method}
    if params is not None:
        request["params"] = params
    sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    return json.loads(buf.decode("utf-8"))


def _one_shot_call(socket_path: Path, method: str, params: dict | None = None) -> dict:
    sock = _open_socket(socket_path)
    try:
        return _call(sock, method, params)
    finally:
        sock.close()


# ─── Listener-detection helpers ─────────────────────────────────────────


def _lsof_listeners(pid: int) -> list[str] | None:
    """Return a list of offending lsof lines, or ``None`` if lsof is absent.

    An empty list means lsof ran and found zero TCP/UDP listeners.
    """
    lsof = shutil.which("lsof")
    if lsof is None:
        return None
    try:
        proc = subprocess.run(
            [lsof, "-p", str(pid), "-P", "-n"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    offenders: list[str] = []
    for line in proc.stdout.splitlines():
        # lsof TYPE column is IPv4 / IPv6 for network sockets; the NAME
        # column carries "(LISTEN)" for a listening TCP socket. UDP
        # sockets have no state, so any IPv4/IPv6 UDP fd is flagged.
        cols = line.split()
        if len(cols) < 5:
            continue
        type_col = cols[4]
        if type_col not in ("IPv4", "IPv6"):
            continue
        upper = line.upper()
        if "(LISTEN)" in upper or "UDP" in upper:
            offenders.append(line)
    return offenders


def _proc_socket_inodes(pid: int) -> set[str]:
    fd_dir = Path(f"/proc/{pid}/fd")
    inodes: set[str] = set()
    try:
        entries = list(fd_dir.iterdir())
    except (FileNotFoundError, PermissionError):
        return inodes
    for fd in entries:
        try:
            target = str(fd.readlink())
        except OSError:
            continue
        if target.startswith("socket:["):
            inodes.add(target[len("socket:[") : -1])
    return inodes


def _read_proc_net(pid: int) -> dict[str, str]:
    base = Path(f"/proc/{pid}/net")
    out: dict[str, str] = {}
    for name in ("tcp", "tcp6", "udp", "udp6"):
        try:
            out[name] = (base / name).read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError):
            out[name] = ""
    return out


def _proc_state(pid: int) -> str | None:
    """Return the single-letter process state from ``/proc/<pid>/stat``
    (``R``/``S``/``D``/``Z``/``T``...), or ``None`` if the pid is fully
    gone from the process table.

    ``os.kill(pid, 0)`` reports a **zombie** (already-exited but not yet
    reaped) process as alive. A zombie has released every file
    descriptor, so for the SC-006 ``no listener`` invariant a zombie is
    equivalent to terminated — this helper lets the test tell the two
    apart.
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError):
        return None
    # The state field is the char after the ")" that closes comm.
    rparen = stat.rfind(")")
    if rparen == -1 or rparen + 2 >= len(stat):
        return None
    return stat[rparen + 2]


def _daemon_terminated(pid: int) -> bool:
    """Return whether the daemon is no longer a live, running process.

    True when the pid is fully reaped OR is a zombie (state ``Z``) — in
    both cases the process holds no open sockets.
    """
    state = _proc_state(pid)
    return state is None or state == "Z"


def _proc_listeners(pid: int) -> list[str] | None:
    """Return offending /proc/net lines, or ``None`` if /proc is unusable."""
    if not Path(f"/proc/{pid}/net").exists():
        return None
    inodes = _proc_socket_inodes(pid)
    proc_net = _read_proc_net(pid)
    offenders: list[str] = []
    for fname in ("tcp", "tcp6"):
        for line in proc_net[fname].splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 10 and cols[3] == "0A" and cols[9] in inodes:
                offenders.append(f"{fname}: {line.strip()}")
    for fname in ("udp", "udp6"):
        for line in proc_net[fname].splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 10 and cols[9] in inodes:
                offenders.append(f"{fname}: {line.strip()}")
    return offenders


def _assert_no_listener(pid: int, *, phase: str) -> None:
    """Assert pid owns zero TCP/UDP listeners; skip only if no tool works."""
    lsof_result = _lsof_listeners(pid)
    if lsof_result is not None:
        assert not lsof_result, (
            f"SC-006 violation ({phase}): daemon pid {pid} owns network "
            f"socket(s) per lsof: {lsof_result!r}"
        )
        return
    proc_result = _proc_listeners(pid)
    if proc_result is not None:
        assert not proc_result, (
            f"SC-006 violation ({phase}): daemon pid {pid} owns network "
            f"listener(s) per /proc/net: {proc_result!r}"
        )
        return
    pytest.skip(
        "neither lsof nor /proc/<pid>/net is available to inspect the "
        "daemon's open sockets"
    )


# ─── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


@pytest.fixture
def daemon(env: dict[str, str]) -> dict:
    run_config_init(env)
    proc = ensure_daemon(env, json_mode=True)
    assert proc.returncode == 0, proc.stderr
    paths = resolved_paths(Path(env["HOME"]))
    pid = json.loads(proc.stdout)["pid"]
    return {"env": env, "socket": paths["socket"], "pid": pid, "paths": paths}


# ─── Tests ──────────────────────────────────────────────────────────────


def test_app_traffic_opens_no_network_listener(daemon: dict) -> None:
    """SC-006 / FR-003: after a representative slice of FEAT-011 app.*
    calls, the daemon has opened no TCP/UDP listener — only AF_UNIX."""
    socket_path: Path = daemon["socket"]
    pid: int = daemon["pid"]

    # Representative slice of the FEAT-011 namespace: a read-only path
    # (preflight), a session-establishing call (hello), a gated read
    # (readiness), an aggregate (dashboard), a list, and an unknown-method
    # rejection path. Every one travels over the Unix socket.
    preflight = _one_shot_call(socket_path, "app.preflight")
    assert preflight["ok"] is True, preflight

    hello = _one_shot_call(socket_path, "app.hello", {"client_id": "t079"})
    assert hello["ok"] is True, hello
    token = hello["result"]["app_session_token"]

    readiness = _one_shot_call(
        socket_path, "app.readiness", {"app_session_token": token}
    )
    assert readiness["ok"] is True, readiness

    dashboard = _one_shot_call(
        socket_path, "app.dashboard", {"app_session_token": token}
    )
    assert dashboard["ok"] is True, dashboard

    pane_list = _one_shot_call(
        socket_path, "app.pane.list", {"app_session_token": token}
    )
    assert pane_list["ok"] is True, pane_list

    unknown = _one_shot_call(socket_path, "app.does.not.exist")
    assert unknown["ok"] is False, unknown

    # The daemon must be holding exactly its AF_UNIX socket and no
    # network listener while it is live and serving app.* traffic.
    _assert_no_listener(pid, phase="daemon live, post app.* calls")


def test_no_network_listener_persists_after_shutdown(daemon: dict) -> None:
    """SC-006 / FR-003: stopping the daemon leaves no orphan network
    listener. We snapshot while live, stop the daemon, confirm the daemon
    has terminated, and confirm it owns no socket fds afterwards.

    Note on zombies: the integration daemon is double-forked and its
    parent (the ``ensure-daemon`` CLI) exits immediately, so after
    ``stop-daemon`` the daemon pid can briefly be a **zombie** — exited
    but not yet reaped, because no live ancestor calls ``wait()``. A
    zombie has already released every file descriptor, so it owns no
    network socket. The test therefore asserts ``terminated`` (reaped OR
    zombie), not ``fully reaped``.
    """
    socket_path: Path = daemon["socket"]
    pid: int = daemon["pid"]
    env: dict[str, str] = daemon["env"]

    # Drive one app.* call so the daemon definitely served FEAT-011
    # traffic before we inspect + tear down.
    hello = _one_shot_call(socket_path, "app.hello", {"client_id": "t079-shutdown"})
    assert hello["ok"] is True, hello
    _assert_no_listener(pid, phase="daemon live")

    stop_daemon_if_alive(env)
    # Wait for the daemon to terminate (reaped or zombie).
    for _ in range(60):
        if _daemon_terminated(pid):
            break
        time.sleep(0.05)
    assert _daemon_terminated(pid), (
        f"daemon pid {pid} is still a live running process after "
        f"stop-daemon (proc state {_proc_state(pid)!r})"
    )

    # A terminated (reaped or zombie) daemon owns no open file
    # descriptors — and therefore, by definition, no lingering TCP/UDP
    # listener. /proc/<pid>/fd is empty for a zombie and absent once
    # reaped; either way the socket-inode set must be empty.
    assert _proc_socket_inodes(pid) == set(), (
        f"SC-006 violation: terminated daemon pid {pid} still owns socket "
        f"inode(s) — a lingering listener after shutdown"
    )
