"""End-to-end integration test for FEAT-003 US2 — invalid config rejection."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
)


def _scan(env, *, json_mode: bool = True, timeout: float = 15.0):
    cmd = ["agenttower", "scan", "--containers"]
    if json_mode:
        cmd.append("--json")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


def _write_config(home: Path, body: str) -> None:
    config = home / ".config/opensoft/agenttower/config.toml"
    config.write_text(body, encoding="utf-8")


@pytest.mark.parametrize(
    "config_body, expected_substring",
    [
        ("[containers]\nname_contains = []\n", "non-empty"),
        ('[containers]\nname_contains = "bench"\n', "list of strings"),
        ('[containers]\nname_contains = ["", "bench"]\n', "blank"),
    ],
)
def test_invalid_config_returns_config_invalid_envelope(
    env_with_fake, config_body, expected_substring
) -> None:
    env, _fake_path, home = env_with_fake
    _write_config(home, config_body)
    ensure_daemon(env)
    result = _scan(env)
    assert result.returncode == 3
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_invalid"
    assert expected_substring in payload["error"]["message"]
