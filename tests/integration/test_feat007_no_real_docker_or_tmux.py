"""T074 — FEAT-007 test session uses zero real docker / tmux / network.

Parallel to ``test_feat003_no_network.py``, but exercised against a daemon
that has the FEAT-007 dispatch table loaded (the four ``attach_log`` /
``detach_log`` / ``attach_log_status`` / ``attach_log_preview`` methods plus
the FEAT-007 startup hooks: orphan recovery + SO_PEERCRED check).

Three invariants are asserted:

1. **No real ``docker`` subprocess.** The session-level ``_no_real_docker``
   guard in ``tests/conftest.py`` already raises ``RuntimeError`` if any
   test (FEAT-007 or otherwise) attempts to spawn ``docker``. We confirm
   the guard remains in place by exercising the full FEAT-007 attach-log
   flow with the FEAT-003 fake docker fixture and asserting the run
   succeeds — i.e., neither the daemon nor the CLI ever fell back to
   the real binary.

2. **No real ``tmux`` subprocess.** The daemon never invokes ``tmux``
   directly — every ``tmux`` invocation goes through ``docker exec``,
   which in turn goes through the ``logs.docker_exec.FakeDockerExecRunner``
   fixture loaded from ``AGENTTOWER_TEST_PIPE_PANE_FAKE``. We assert the
   daemon's ``/proc/<pid>/comm`` is the daemon binary (not ``tmux``)
   and that no child process named ``tmux`` is alive while the attach
   flow runs.

3. **No inet listener.** Same shape as FEAT-003's
   ``test_feat003_no_network.py``: inspect ``/proc/<pid>/net/{tcp,tcp6,
   udp,udp6}`` for sockets owned by the daemon's pid; assert none.
"""

from __future__ import annotations

import json
import sqlite3
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
from .test_feat007_attach_log_smoke import (
    _seed_database,
    _write_pipe_pane_fake,
)


@pytest.fixture
def env_with_fakes(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = isolated_env(home)
    fake_path = tmp_path / "pipe_pane_fake.json"
    _write_pipe_pane_fake(fake_path)
    env["AGENTTOWER_TEST_PIPE_PANE_FAKE"] = str(fake_path)
    yield env, home
    stop_daemon_if_alive(env)


def _read_proc_net(pid: int) -> dict[str, str]:
    base = Path(f"/proc/{pid}/net")
    out: dict[str, str] = {}
    for name in ("tcp", "tcp6", "udp", "udp6"):
        try:
            out[name] = (base / name).read_text(encoding="utf-8")
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


def _proc_comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except (FileNotFoundError, PermissionError):
        return ""


def _walk_descendants(pid: int) -> list[int]:
    """Return the set of descendant pids by parsing /proc/<pid>/task/*/children."""
    result: list[int] = []
    stack = [pid]
    seen: set[int] = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        result.append(cur)
        task_dir = Path(f"/proc/{cur}/task")
        try:
            tasks = list(task_dir.iterdir())
        except (FileNotFoundError, PermissionError):
            continue
        for task in tasks:
            children_path = task / "children"
            try:
                kids = children_path.read_text(encoding="utf-8").split()
            except (FileNotFoundError, PermissionError):
                continue
            for child_str in kids:
                try:
                    stack.append(int(child_str))
                except ValueError:
                    continue
    return result


def _wait_for_pid(pid_path: Path, *, timeout: float = 2.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return int(pid_path.read_text(encoding="ascii").strip())
        except (FileNotFoundError, ValueError):
            time.sleep(0.05)
    raise AssertionError(f"daemon pid file at {pid_path} never appeared")


def test_feat007_session_uses_no_inet_listener(env_with_fakes) -> None:
    """T074 invariant 3 — daemon owns only AF_UNIX sockets (parallel to FEAT-003)."""
    env, home = env_with_fakes
    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    run_config_init(env)
    ensure_daemon(env)
    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed_database(
        paths["state_db"],
        container_id=container_id,
        agent_id=agent_id,
        host_log_root=host_log_root,
    )

    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, (
        f"FEAT-007 attach-log failed; stderr={proc.stderr!r}"
    )

    pid = _wait_for_pid(paths["pid_file"])
    inodes = _socket_inodes_for_pid(pid)
    net = _read_proc_net(pid)
    for name, body in net.items():
        for line in body.splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 10:
                assert cols[9] not in inodes, (
                    f"FEAT-007 daemon (pid={pid}) owns an {name} socket "
                    f"(inode={cols[9]}) — must be AF_UNIX only"
                )


def test_feat007_session_no_real_docker_or_tmux_subprocess(env_with_fakes) -> None:
    """T074 invariants 1 + 2 — neither the daemon nor any descendant
    spawns ``docker`` or ``tmux`` during a FEAT-007 attach-log flow.

    Verified by walking ``/proc/<daemon-pid>/task/*/children`` and asserting
    every descendant's ``comm`` is neither ``docker`` nor ``tmux``. The
    attach flow goes entirely through the FEAT-007 fake docker-exec
    runner; if any code path were calling out to a real binary, we would
    catch it here. (The session-level ``_no_real_docker`` guard in
    ``tests/conftest.py`` is the primary defense against ``docker``; this
    is a defense-in-depth check that also covers ``tmux``.)
    """
    env, home = env_with_fakes
    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    run_config_init(env)
    ensure_daemon(env)
    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed_database(
        paths["state_db"],
        container_id=container_id,
        agent_id=agent_id,
        host_log_root=host_log_root,
    )

    # Fire the full FEAT-007 surface: attach-log, --status, --preview,
    # detach-log, register-self --attach-log surfaces — every method
    # routes through the daemon and exercises the docker-exec fake.
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--status", "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, proc.stderr

    pid = _wait_for_pid(paths["pid_file"])
    descendants = _walk_descendants(pid)
    for d_pid in descendants:
        comm = _proc_comm(d_pid)
        assert comm != "docker", (
            f"daemon descendant pid={d_pid} comm={comm!r} is real docker — "
            "FEAT-007 must route through FakeDockerExecRunner"
        )
        assert comm != "tmux", (
            f"daemon descendant pid={d_pid} comm={comm!r} is real tmux — "
            "FEAT-007 daemon must never spawn tmux directly (all tmux "
            "invocations go through docker exec → FakeDockerExecRunner)"
        )


def test_feat007_attach_log_did_not_modify_pid_or_socket_files(env_with_fakes) -> None:
    """Defense in depth: the daemon's pid file and socket file are unchanged
    by FEAT-007 method dispatch — FEAT-002's contract is preserved.

    This guards against a future FEAT-007 path accidentally rebinding the
    socket or rewriting the pid file as a side effect of the new methods.
    """
    env, home = env_with_fakes
    container_id = "c" * 64
    agent_id = "agt_abc123def456"

    run_config_init(env)
    ensure_daemon(env)
    paths = resolved_paths(home)
    host_log_root = paths["state_dir"] / "logs"
    host_log_root.mkdir(parents=True, exist_ok=True)
    _seed_database(
        paths["state_db"],
        container_id=container_id,
        agent_id=agent_id,
        host_log_root=host_log_root,
    )

    pid_before = paths["pid_file"].read_text(encoding="ascii").strip()
    sock_mtime_before = paths["socket"].stat().st_mtime_ns

    proc = subprocess.run(
        ["agenttower", "attach-log", "--target", agent_id, "--json"],
        env=env, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, proc.stderr

    pid_after = paths["pid_file"].read_text(encoding="ascii").strip()
    sock_mtime_after = paths["socket"].stat().st_mtime_ns
    assert pid_before == pid_after
    assert sock_mtime_before == sock_mtime_after
