"""Shared helpers for FEAT-002 daemon integration tests.

Provides:

* ``isolated_env(home)`` — a clean ``$HOME``-overridden subprocess environment
  with ``$PATH`` extended to include the active Python's ``bin/`` so that the
  ``agenttower`` and ``agenttowerd`` console scripts resolve.
* ``resolved_paths(home)`` — the FEAT-001 path contract evaluated at *home*.
* ``run_config_init(env)`` — convenience wrapper for ``agenttower config init``.
* ``stop_daemon_if_alive(env)`` — best-effort teardown for tests that left a
  daemon running.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def isolated_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    bin_dir = os.path.dirname(sys.executable)
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        env.pop(var, None)
    return env


def resolved_paths(home: Path) -> dict[str, Path]:
    state_dir = home / ".local/state/opensoft/agenttower"
    logs_dir = state_dir / "logs"
    return {
        "config_file": home / ".config/opensoft/agenttower/config.toml",
        "state_db": state_dir / "agenttower.sqlite3",
        "events_file": state_dir / "events.jsonl",
        "state_dir": state_dir,
        "logs_dir": logs_dir,
        "socket": state_dir / "agenttowerd.sock",
        "lock_file": state_dir / "agenttowerd.lock",
        "pid_file": state_dir / "agenttowerd.pid",
        "log_file": logs_dir / "agenttowerd.log",
        "cache_dir": home / ".cache/opensoft/agenttower",
    }


def run_config_init(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["agenttower", "config", "init"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )


def ensure_daemon(env: dict[str, str], *, json_mode: bool = False, timeout: float = 10.0):
    cmd = ["agenttower", "ensure-daemon"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=timeout
    )


def status(env: dict[str, str], *, json_mode: bool = False, timeout: float = 5.0):
    cmd = ["agenttower", "status"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=timeout
    )


def stop_daemon(env: dict[str, str], *, json_mode: bool = False, timeout: float = 10.0):
    cmd = ["agenttower", "stop-daemon"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=timeout
    )


def send_test_signal(pid: int, sig: int) -> None:
    """Signal a daemon pid created by an isolated integration test."""
    os.kill(pid, sig)  # NOSONAR - test-only signal to an isolated child daemon.


def process_exists(pid: int) -> bool:
    """Return whether a test daemon pid is still present in the process table."""
    try:
        os.kill(pid, 0)  # NOSONAR - standard test-only pid liveness probe.
    except ProcessLookupError:
        return False
    return True


def stop_daemon_if_alive(env: dict[str, str]) -> None:
    """Best-effort teardown — succeeds whether or not a daemon is alive."""
    try:
        stop_daemon(env, timeout=5.0)
    except subprocess.TimeoutExpired:
        pass
    # Also poke the pid file in case stop-daemon failed before unlinking.
    paths = resolved_paths(Path(env["HOME"]))
    pid_path = paths["pid_file"]
    try:
        text = pid_path.read_text(encoding="ascii").strip()
        pid = int(text) if text.isdigit() else None
    except OSError:
        pid = None
    if pid is not None:
        try:
            send_test_signal(pid, 15)
            for _ in range(40):
                if not process_exists(pid):
                    break
                time.sleep(0.05)
        except ProcessLookupError:
            pass
