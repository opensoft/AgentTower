from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import subprocess
import sys
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


def _resolved_paths(home: Path) -> dict[str, Path]:
    state_dir = home / ".local/state/opensoft/agenttower"
    return {
        "config_file": home / ".config/opensoft/agenttower/config.toml",
        "config_dir": home / ".config/opensoft/agenttower",
        "state_db": state_dir / "agenttower.sqlite3",
        "state_dir": state_dir,
        "events_file": state_dir / "events.jsonl",
        "logs_dir": state_dir / "logs",
        "socket": state_dir / "agenttowerd.sock",
        "cache_dir": home / ".cache/opensoft/agenttower",
        "config_namespace_parent": home / ".config/opensoft",
        "state_namespace_parent": home / ".local/state/opensoft",
        "cache_namespace_parent": home / ".cache/opensoft",
    }


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def _run_init(env: dict[str, str], *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    final_env = dict(env)
    if extra_env:
        final_env.update(extra_env)
    return subprocess.run(
        ["agenttower", "config", "init"],
        env=final_env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_first_init_creates_config_and_registry_with_correct_modes(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    paths = _resolved_paths(tmp_path)

    proc = _run_init(env)

    assert proc.returncode == 0, proc.stderr
    assert f"created config: {paths['config_file']}" in proc.stdout
    assert f"created registry: {paths['state_db']}" in proc.stdout
    assert proc.stderr == ""

    assert paths["config_file"].exists()
    assert paths["state_db"].exists()
    assert paths["logs_dir"].is_dir()
    assert paths["cache_dir"].is_dir()
    assert paths["config_dir"].is_dir()
    assert paths["state_dir"].is_dir()
    assert paths["config_namespace_parent"].is_dir()
    assert paths["state_namespace_parent"].is_dir()
    assert paths["cache_namespace_parent"].is_dir()

    assert _mode(paths["config_file"]) == 0o600
    assert _mode(paths["state_db"]) == 0o600
    for d in (
        paths["config_dir"],
        paths["state_dir"],
        paths["logs_dir"],
        paths["cache_dir"],
        paths["config_namespace_parent"],
        paths["state_namespace_parent"],
        paths["cache_namespace_parent"],
    ):
        assert _mode(d) == 0o700, f"{d}: mode {oct(_mode(d))}"

    assert not paths["events_file"].exists()
    assert not paths["socket"].exists()


def test_idempotent_reruns_leave_bytes_and_rows_unchanged(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    paths = _resolved_paths(tmp_path)

    proc = _run_init(env)
    assert proc.returncode == 0

    config_hash = hashlib.sha256(paths["config_file"].read_bytes()).hexdigest()

    for _ in range(10):
        proc = _run_init(env)
        assert proc.returncode == 0, proc.stderr
        assert f"already initialized: {paths['config_file']}" in proc.stdout
        assert f"already initialized: {paths['state_db']}" in proc.stdout
        assert proc.stderr == ""

        new_hash = hashlib.sha256(paths["config_file"].read_bytes()).hexdigest()
        assert new_hash == config_hash

        with sqlite3.connect(str(paths["state_db"])) as conn:
            ((count,),) = list(conn.execute("SELECT COUNT(*) FROM schema_version"))
            ((version,),) = list(conn.execute("SELECT version FROM schema_version"))
        assert count == 1
        # FEAT-004 bumps the schema to v3 (data-model.md §7); read the
        # current version symbolically so future bumps don't break this gate.
        from agenttower.state.schema import CURRENT_SCHEMA_VERSION

        assert version == CURRENT_SCHEMA_VERSION


def test_modes_correct_under_permissive_umask(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    paths = _resolved_paths(tmp_path)

    wrapper = "umask 022 && agenttower config init"
    proc = subprocess.run(
        ["bash", "-c", wrapper],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr

    assert _mode(paths["config_file"]) == 0o600
    assert _mode(paths["state_db"]) == 0o600
    for d in (paths["config_dir"], paths["state_dir"], paths["logs_dir"], paths["cache_dir"]):
        assert _mode(d) == 0o700


def test_pre_existing_user_edited_config_with_correct_mode_is_preserved(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    paths = _resolved_paths(tmp_path)

    paths["config_dir"].mkdir(parents=True, mode=0o700)
    os.chmod(paths["config_dir"].parent, 0o700)
    user_content = b"# user-edited\n[containers]\nname_contains = ['foo']\n"
    paths["config_file"].write_bytes(user_content)
    os.chmod(paths["config_file"], 0o600)

    proc = _run_init(env)
    assert proc.returncode == 0, proc.stderr
    assert f"already initialized: {paths['config_file']}" in proc.stdout
    assert paths["config_file"].read_bytes() == user_content


def test_pre_existing_config_with_broader_mode_causes_exit_1(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    paths = _resolved_paths(tmp_path)

    paths["config_dir"].mkdir(parents=True, mode=0o700)
    os.chmod(paths["config_dir"].parent, 0o700)
    user_content = b"# user-edited\n"
    paths["config_file"].write_bytes(user_content)
    os.chmod(paths["config_file"], 0o644)  # NOSONAR - intentionally unsafe mode fixture.

    proc = _run_init(env)
    assert proc.returncode == 1
    assert "error:" in proc.stderr
    assert str(paths["config_file"]) in proc.stderr
    assert paths["config_file"].read_bytes() == user_content
    assert _mode(paths["config_file"]) == 0o644


def test_stale_event_log_socket_files_left_byte_identical(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    paths = _resolved_paths(tmp_path)

    paths["state_dir"].mkdir(parents=True, mode=0o700)
    os.chmod(paths["state_dir"].parent, 0o700)
    paths["logs_dir"].mkdir(mode=0o700)

    stale_event = b'{"ts":"old","event":"prior_install"}\n'
    stale_log = b"old log line\n"
    stale_socket_bytes = b"sock-placeholder"

    paths["events_file"].write_bytes(stale_event)
    os.chmod(paths["events_file"], 0o600)

    stale_log_path = paths["logs_dir"] / "old.log"
    stale_log_path.write_bytes(stale_log)
    os.chmod(stale_log_path, 0o600)

    paths["socket"].write_bytes(stale_socket_bytes)
    os.chmod(paths["socket"], 0o600)

    proc = _run_init(env)
    assert proc.returncode == 0, proc.stderr

    assert paths["events_file"].read_bytes() == stale_event
    assert stale_log_path.read_bytes() == stale_log
    assert paths["socket"].read_bytes() == stale_socket_bytes


def test_unwritable_target_exits_1_with_actionable_error_no_partial_db(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    paths = _resolved_paths(tmp_path)

    blocker = paths["state_namespace_parent"]
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.mkdir(mode=0o700)
    os.chmod(blocker, 0o500)
    try:
        proc = _run_init(env)
        assert proc.returncode == 1
        assert proc.stderr.startswith("error:"), proc.stderr
        assert str(blocker) in proc.stderr or "agenttower" in proc.stderr

        for f in (
            paths["state_db"],
            paths["state_db"].with_name(paths["state_db"].name + "-wal"),
            paths["state_db"].with_name(paths["state_db"].name + "-shm"),
            paths["state_db"].with_name(paths["state_db"].name + "-journal"),
        ):
            assert not f.exists(), f"unexpected leftover {f}"
    finally:
        os.chmod(blocker, 0o700)


def test_corrupt_pre_existing_registry_exits_1_without_traceback(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    paths = _resolved_paths(tmp_path)

    paths["state_dir"].mkdir(parents=True, mode=0o700)
    os.chmod(paths["state_dir"].parent, 0o700)
    corrupt_bytes = b"not sqlite\n"
    paths["state_db"].write_bytes(corrupt_bytes)
    os.chmod(paths["state_db"], 0o600)

    proc = _run_init(env)

    assert proc.returncode == 1
    assert proc.stderr.startswith("error: open registry:")
    assert str(paths["state_db"]) in proc.stderr
    assert "Traceback" not in proc.stderr
    assert paths["state_db"].read_bytes() == corrupt_bytes


def test_mixed_init_creates_config_with_pre_existing_registry(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    paths = _resolved_paths(tmp_path)

    proc = _run_init(env)
    assert proc.returncode == 0

    paths["config_file"].unlink()

    proc = _run_init(env)
    assert proc.returncode == 0, proc.stderr
    assert f"created config: {paths['config_file']}" in proc.stdout
    assert f"already initialized: {paths['state_db']}" in proc.stdout
