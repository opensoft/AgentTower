"""Concurrent ``ensure-daemon`` integration test (T016 / FR-028 / SC-009).

Also asserts the SC-009 timing budget for the slowest invocation (T037).
"""

from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from ._daemon_helpers import (
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


def test_five_concurrent_ensure_daemon_yields_one_daemon(env: dict[str, str]) -> None:
    run_config_init(env)

    def _one() -> tuple[int, str]:
        proc = subprocess.run(
            ["agenttower", "ensure-daemon", "--json"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode, proc.stdout, proc.stderr  # type: ignore[return-value]

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_one) for _ in range(5)]
        results = [f.result() for f in as_completed(futures)]
    elapsed = time.monotonic() - start
    # SC-009 (with +50% slack on CI): all 5 invocations resolve within 3 s.
    assert elapsed < 3.0, f"5-way concurrent ensure-daemon took {elapsed:.2f}s"

    pids: set[int] = set()
    for code, stdout, stderr in results:
        assert code == 0, stderr
        payload = json.loads(stdout)
        assert payload["ok"] is True
        pids.add(payload["pid"])

    # Exactly one daemon serves all five invocations.
    assert len(pids) == 1, f"expected exactly one pid, got {pids}"

    # Confirm the live daemon owns the lock and socket.
    paths = resolved_paths(Path(env["HOME"]))
    assert paths["socket"].exists()
    assert paths["pid_file"].exists()
    on_disk_pid = int(paths["pid_file"].read_text().strip())
    assert on_disk_pid in pids
