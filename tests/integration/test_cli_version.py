from __future__ import annotations

import os
import subprocess
import sys
import time
from importlib.metadata import version as _version
from pathlib import Path

import pytest


def _isolated_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    bin_dir = os.path.dirname(sys.executable)
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        env.pop(var, None)
    return env


def test_agenttower_version_exits_zero_with_version_string(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    expected = _version("agenttower")
    start = time.monotonic()
    proc = subprocess.run(
        ["agenttower", "--version"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    elapsed = time.monotonic() - start
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"agenttower {expected}\n"
    assert elapsed < 5.0


def test_agenttowerd_version_exits_zero_with_matching_version(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    expected = _version("agenttower")
    start = time.monotonic()
    proc = subprocess.run(
        ["agenttowerd", "--version"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    elapsed = time.monotonic() - start
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"agenttowerd {expected}\n"
    assert elapsed < 5.0


def test_agenttower_help_lists_required_substrings(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    proc = subprocess.run(
        ["agenttower", "--help"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    for needle in ("usage: agenttower", "--version", "config", "paths", "init", "config paths", "config init"):
        assert needle in out, f"missing substring {needle!r} in --help output:\n{out}"


def test_version_does_not_create_files_under_resolved_paths(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    subprocess.run(
        ["agenttower", "--version"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    namespace = tmp_path / ".config/opensoft"
    state_namespace = tmp_path / ".local/state/opensoft"
    cache_namespace = tmp_path / ".cache/opensoft"
    assert not namespace.exists()
    assert not state_namespace.exists()
    assert not cache_namespace.exists()


@pytest.mark.parametrize("invocation", [["agenttower"], ["agenttower", "-h"]])
def test_no_args_and_short_help_print_usage_text(tmp_path: Path, invocation: list[str]) -> None:
    env = _isolated_env(tmp_path)
    proc = subprocess.run(invocation, env=env, capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stderr
    assert "usage: agenttower" in proc.stdout
