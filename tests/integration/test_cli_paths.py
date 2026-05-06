from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _isolated_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    bin_dir = os.path.dirname(sys.executable)
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        env.pop(var, None)
    return env


def _run_paths(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["agenttower", "config", "paths"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _parse_kv(stdout: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        key, _, value = line.partition("=")
        out[key] = value
    return out


# FEAT-001's six output keys, in declared `Paths` field order. FEAT-005 / FR-019
# appends a seventh line `SOCKET_SOURCE=<token>` so callers can see which
# resolution branch produced the SOCKET path; the original six lines are
# byte-for-byte unchanged (FR-019, FR-026, SC-007).
EXPECTED_KEYS = ("CONFIG_FILE", "STATE_DB", "EVENTS_FILE", "LOGS_DIR", "SOCKET", "CACHE_DIR")
EXPECTED_KEYS_WITH_SOCKET_SOURCE = EXPECTED_KEYS + ("SOCKET_SOURCE",)


def test_config_paths_outputs_seven_lines_in_fixed_order(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    proc = _run_paths(env)
    assert proc.returncode == 0
    lines = proc.stdout.splitlines()
    assert len(lines) == 7, lines
    for line, key in zip(lines, EXPECTED_KEYS_WITH_SOCKET_SOURCE):
        assert line.startswith(f"{key}="), line
        assert line.count("=") >= 1
        assert " " not in line
    # FR-019: SOCKET_SOURCE MUST be the last line
    assert lines[-1].startswith("SOCKET_SOURCE=")


def test_config_paths_values_are_absolute_under_namespace(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    proc = _run_paths(env)
    assert proc.returncode == 0
    kv = _parse_kv(proc.stdout)
    # The six FEAT-001 path keys remain absolute under the namespace.
    for key in EXPECTED_KEYS:
        assert key in kv
        assert kv[key].startswith("/")
        assert "opensoft/agenttower" in kv[key]


def test_config_paths_eval_compatible(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    proc = _run_paths(env)
    assert proc.returncode == 0
    kv = _parse_kv(proc.stdout)
    # FR-019: the seven keys are exactly the six FEAT-001 keys plus SOCKET_SOURCE.
    assert set(kv.keys()) == set(EXPECTED_KEYS_WITH_SOCKET_SOURCE)
    # SOCKET_SOURCE values are closed-set tokens per FR-001.
    assert kv["SOCKET_SOURCE"] in {"env_override", "mounted_default", "host_default"}
    for value in kv.values():
        assert "'" not in value
        assert '"' not in value
        assert "\n" not in value


def test_uninitialized_emits_note_on_stderr(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    proc = _run_paths(env)
    assert proc.returncode == 0
    assert "note: agenttower has not been initialized" in proc.stderr
    assert "agenttower config init" in proc.stderr


def test_initialized_emits_no_stderr_note(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    init_proc = subprocess.run(
        ["agenttower", "config", "init"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert init_proc.returncode == 0, init_proc.stderr

    proc = _run_paths(env)
    assert proc.returncode == 0
    assert proc.stderr == ""
    # FR-019: six FEAT-001 lines + the new trailing SOCKET_SOURCE= line.
    assert proc.stdout.count("\n") == 7


def test_xdg_config_home_redirects_only_config(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "cfg")
    proc = _run_paths(env)
    kv = _parse_kv(proc.stdout)
    assert kv["CONFIG_FILE"] == str(tmp_path / "cfg/opensoft/agenttower/config.toml")
    assert kv["STATE_DB"] == str(tmp_path / ".local/state/opensoft/agenttower/agenttower.sqlite3")
    assert kv["CACHE_DIR"] == str(tmp_path / ".cache/opensoft/agenttower")


def test_xdg_state_home_redirects_state_subset(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    proc = _run_paths(env)
    kv = _parse_kv(proc.stdout)
    assert kv["CONFIG_FILE"] == str(tmp_path / ".config/opensoft/agenttower/config.toml")
    assert kv["STATE_DB"] == str(tmp_path / "state/opensoft/agenttower/agenttower.sqlite3")
    assert kv["EVENTS_FILE"] == str(tmp_path / "state/opensoft/agenttower/events.jsonl")
    assert kv["LOGS_DIR"] == str(tmp_path / "state/opensoft/agenttower/logs")
    assert kv["SOCKET"] == str(tmp_path / "state/opensoft/agenttower/agenttowerd.sock")
    assert kv["CACHE_DIR"] == str(tmp_path / ".cache/opensoft/agenttower")


def test_xdg_cache_home_redirects_only_cache(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    proc = _run_paths(env)
    kv = _parse_kv(proc.stdout)
    assert kv["CONFIG_FILE"] == str(tmp_path / ".config/opensoft/agenttower/config.toml")
    assert kv["STATE_DB"] == str(tmp_path / ".local/state/opensoft/agenttower/agenttower.sqlite3")
    assert kv["CACHE_DIR"] == str(tmp_path / "cache/opensoft/agenttower")


def test_all_three_xdg_set_simultaneously(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "cfg")
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    proc = _run_paths(env)
    kv = _parse_kv(proc.stdout)
    assert kv["CONFIG_FILE"] == str(tmp_path / "cfg/opensoft/agenttower/config.toml")
    assert kv["STATE_DB"] == str(tmp_path / "state/opensoft/agenttower/agenttower.sqlite3")
    assert kv["EVENTS_FILE"] == str(tmp_path / "state/opensoft/agenttower/events.jsonl")
    assert kv["LOGS_DIR"] == str(tmp_path / "state/opensoft/agenttower/logs")
    assert kv["SOCKET"] == str(tmp_path / "state/opensoft/agenttower/agenttowerd.sock")
    assert kv["CACHE_DIR"] == str(tmp_path / "cache/opensoft/agenttower")


def test_config_paths_creates_no_files(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    _run_paths(env)
    for ns in (".config/opensoft", ".local/state/opensoft", ".cache/opensoft"):
        assert not (tmp_path / ns).exists(), f"{ns} should not exist"
