"""Signal-driven cleanup integration tests (T034 / FR-022 / SC-006)."""

from __future__ import annotations

import json
import os
import signal
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


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def _wait_for_pid_zombie_or_gone(pid: int, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    stat_path = Path(f"/proc/{pid}/stat")
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        try:
            data = stat_path.read_text(encoding="utf-8", errors="replace")
            after = data[data.rfind(")") + 1 :].split()
            if after and after[0] == "Z":
                return
        except OSError:
            return
        time.sleep(0.05)
    raise AssertionError(f"pid {pid} still alive after {timeout}s")


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_signal_triggers_clean_shutdown_then_re_ensure_succeeds(
    env: dict[str, str], sig: int
) -> None:
    run_config_init(env)
    first = ensure_daemon(env, json_mode=True)
    assert first.returncode == 0, first.stderr
    pid = json.loads(first.stdout)["pid"]

    os.kill(pid, sig)
    _wait_for_pid_zombie_or_gone(pid)

    paths = resolved_paths(Path(env["HOME"]))
    # Brief settle — daemon's finally-block needs to run.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and (
        paths["socket"].exists() or paths["pid_file"].exists()
    ):
        time.sleep(0.05)
    assert not paths["socket"].exists(), f"{sig.name} left socket: {paths['socket']}"
    assert not paths["pid_file"].exists(), f"{sig.name} left pid file"

    second = ensure_daemon(env, json_mode=True)
    assert second.returncode == 0, second.stderr
    new_pid = json.loads(second.stdout)["pid"]
    assert new_pid != pid
