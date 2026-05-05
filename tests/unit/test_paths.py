from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.paths import Paths, resolve_paths


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(var, raising=False)
    import os
    return dict(os.environ)


def test_defaults_when_no_xdg_set(tmp_path: Path, isolated_env: dict[str, str]) -> None:
    paths = resolve_paths()
    assert paths.config_file == tmp_path / ".config/opensoft/agenttower/config.toml"
    assert paths.state_db == tmp_path / ".local/state/opensoft/agenttower/agenttower.sqlite3"
    assert paths.events_file == tmp_path / ".local/state/opensoft/agenttower/events.jsonl"
    assert paths.logs_dir == tmp_path / ".local/state/opensoft/agenttower/logs"
    assert paths.socket == tmp_path / ".local/state/opensoft/agenttower/agenttowerd.sock"
    assert paths.cache_dir == tmp_path / ".cache/opensoft/agenttower"


def test_xdg_config_home_redirects_only_config(tmp_path: Path, isolated_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    paths = resolve_paths()
    assert paths.config_file == tmp_path / "cfg/opensoft/agenttower/config.toml"
    assert paths.state_db == tmp_path / ".local/state/opensoft/agenttower/agenttower.sqlite3"
    assert paths.cache_dir == tmp_path / ".cache/opensoft/agenttower"


def test_xdg_state_home_redirects_only_state(tmp_path: Path, isolated_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    paths = resolve_paths()
    assert paths.config_file == tmp_path / ".config/opensoft/agenttower/config.toml"
    assert paths.state_db == tmp_path / "state/opensoft/agenttower/agenttower.sqlite3"
    assert paths.events_file == tmp_path / "state/opensoft/agenttower/events.jsonl"
    assert paths.logs_dir == tmp_path / "state/opensoft/agenttower/logs"
    assert paths.socket == tmp_path / "state/opensoft/agenttower/agenttowerd.sock"
    assert paths.cache_dir == tmp_path / ".cache/opensoft/agenttower"


def test_xdg_cache_home_redirects_only_cache(tmp_path: Path, isolated_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    paths = resolve_paths()
    assert paths.config_file == tmp_path / ".config/opensoft/agenttower/config.toml"
    assert paths.state_db == tmp_path / ".local/state/opensoft/agenttower/agenttower.sqlite3"
    assert paths.cache_dir == tmp_path / "cache/opensoft/agenttower"


def test_all_three_xdg_variables_together(tmp_path: Path, isolated_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    paths = resolve_paths()
    assert paths.config_file == tmp_path / "cfg/opensoft/agenttower/config.toml"
    assert paths.state_db == tmp_path / "state/opensoft/agenttower/agenttower.sqlite3"
    assert paths.events_file == tmp_path / "state/opensoft/agenttower/events.jsonl"
    assert paths.logs_dir == tmp_path / "state/opensoft/agenttower/logs"
    assert paths.socket == tmp_path / "state/opensoft/agenttower/agenttowerd.sock"
    assert paths.cache_dir == tmp_path / "cache/opensoft/agenttower"


def test_empty_string_xdg_treated_as_unset(tmp_path: Path, isolated_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setenv("XDG_STATE_HOME", "")
    monkeypatch.setenv("XDG_CACHE_HOME", "")
    paths = resolve_paths()
    assert paths.config_file == tmp_path / ".config/opensoft/agenttower/config.toml"
    assert paths.state_db == tmp_path / ".local/state/opensoft/agenttower/agenttower.sqlite3"
    assert paths.cache_dir == tmp_path / ".cache/opensoft/agenttower"


def test_socket_falls_back_to_state_dir_even_when_xdg_runtime_dir_set(tmp_path: Path, isolated_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    paths = resolve_paths()
    assert paths.socket == tmp_path / ".local/state/opensoft/agenttower/agenttowerd.sock"


def test_paths_instance_is_frozen(isolated_env: dict[str, str]) -> None:
    paths = resolve_paths()
    with pytest.raises(Exception):
        paths.config_file = Path("/tmp/other")  # type: ignore[misc]


def test_resolve_paths_accepts_explicit_env(tmp_path: Path) -> None:
    env = {
        "HOME": str(tmp_path),
        "XDG_STATE_HOME": str(tmp_path / "explicit-state"),
    }
    paths = resolve_paths(env)
    assert paths.state_db == tmp_path / "explicit-state/opensoft/agenttower/agenttower.sqlite3"
    assert paths.config_file == tmp_path / ".config/opensoft/agenttower/config.toml"


def test_paths_namespace_invariants(isolated_env: dict[str, str]) -> None:
    paths = resolve_paths()
    assert isinstance(paths, Paths)
    for member in (paths.config_file, paths.state_db, paths.events_file, paths.logs_dir, paths.socket, paths.cache_dir):
        assert "opensoft/agenttower" in str(member)
    assert paths.events_file.parent == paths.state_db.parent
    assert paths.logs_dir.parent == paths.state_db.parent
    assert paths.socket.parent == paths.state_db.parent
