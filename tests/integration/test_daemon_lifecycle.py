"""Full ensure → status → stop → re-ensure lifecycle test (T033 / SC-006).

Also asserts the SC-006 timing budget: a re-ensure after a clean stop
should complete in well under 3 s on a normally-loaded host (T037).
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
    status,
    stop_daemon,
    stop_daemon_if_alive,
)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


def test_full_lifecycle_loop(env: dict[str, str]) -> None:
    run_config_init(env)

    first = ensure_daemon(env, json_mode=True)
    assert first.returncode == 0, first.stderr
    first_pid = json.loads(first.stdout)["pid"]

    status_proc = status(env, json_mode=True)
    assert status_proc.returncode == 0, status_proc.stderr
    assert json.loads(status_proc.stdout)["result"]["pid"] == first_pid

    stop_proc = stop_daemon(env)
    assert stop_proc.returncode == 0, stop_proc.stderr

    paths = resolved_paths(Path(env["HOME"]))
    assert not paths["socket"].exists()
    assert not paths["pid_file"].exists()
    # Lock file may or may not be unlinked — kernel released its hold on exit.

    start = time.monotonic()
    second = ensure_daemon(env, json_mode=True)
    elapsed = time.monotonic() - start
    assert second.returncode == 0, second.stderr
    second_pid = json.loads(second.stdout)["pid"]
    assert second_pid != first_pid
    # SC-006: re-ensure after clean stop within 3 s.
    assert elapsed < 3.0
