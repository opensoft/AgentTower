"""Integration-test conftest.

The FEAT-002 helper `isolated_env` overrides `$HOME`, which causes Python
to recompute `site.USER_SITE` from the new HOME. When the agenttower
package is installed under the *real* user's site-packages directory,
the subprocess loses sight of it. Patch `subprocess.run`/`Popen` here so
that any test invoking `agenttower` or `agenttowerd` inherits a
`PYTHONUSERBASE` pointing at the real install location.
"""

from __future__ import annotations

import json
import os
import site
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ._daemon_helpers import isolated_env, run_config_init, stop_daemon_if_alive

_REAL_USER_BASE = site.getuserbase()
_REAL_USER_BIN = os.path.join(_REAL_USER_BASE, "bin")


@pytest.fixture(autouse=True)
def _preserve_user_base(monkeypatch: pytest.MonkeyPatch) -> None:
    real_run = subprocess.run
    real_popen = subprocess.Popen

    def patched_env(env: dict[str, str] | None) -> dict[str, str] | None:
        if env is None:
            return None
        env = dict(env)
        if "PYTHONUSERBASE" not in env:
            env["PYTHONUSERBASE"] = _REAL_USER_BASE
        path_parts = env.get("PATH", "").split(os.pathsep) if env.get("PATH") else []
        if _REAL_USER_BIN not in path_parts:
            env["PATH"] = os.pathsep.join((_REAL_USER_BIN, env.get("PATH", "")))
        return env

    def patched_run(*args: Any, **kwargs: Any):  # noqa: ANN201
        if "env" in kwargs and kwargs["env"] is not None:
            kwargs["env"] = patched_env(kwargs["env"])
        return real_run(*args, **kwargs)

    def patched_popen(*args: Any, **kwargs: Any):  # noqa: ANN201
        if "env" in kwargs and kwargs["env"] is not None:
            kwargs["env"] = patched_env(kwargs["env"])
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", patched_run)
    monkeypatch.setattr(subprocess, "Popen", patched_popen)


@pytest.fixture()
def env_with_fake(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    fake_path = tmp_path / "docker-fake.json"
    fake_path.write_text(
        json.dumps(
            {
                "list_running": {"action": "ok", "containers": []},
                "inspect": {"action": "ok", "results": []},
            }
        ),
        encoding="utf-8",
    )
    env = isolated_env(home)
    env["AGENTTOWER_TEST_DOCKER_FAKE"] = str(fake_path)
    run_config_init(env)
    try:
        yield env, fake_path, home
    finally:
        stop_daemon_if_alive(env)
