"""Unit tests for the FEAT-003 `[containers] name_contains` config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.config import ConfigInvalidError, load_containers_block
from agenttower.discovery.matching import MatchingRule, default_rule


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_missing_file_returns_default_rule(tmp_path: Path) -> None:
    config = tmp_path / "missing.toml"
    rule = load_containers_block(config)
    assert rule == default_rule()


def test_missing_containers_block_returns_default(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    _write(config, "[other]\nval = 1\n")
    assert load_containers_block(config) == default_rule()


def test_missing_name_contains_returns_default(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    _write(config, "[containers]\nscan_interval_seconds = 5\n")
    assert load_containers_block(config) == default_rule()


def test_valid_list_yields_rule(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    _write(config, '[containers]\nname_contains = ["bench", "dev"]\n')
    rule = load_containers_block(config)
    assert rule == MatchingRule(name_contains=("bench", "dev"))


def test_strip_whitespace(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    _write(config, '[containers]\nname_contains = ["  bench  "]\n')
    assert load_containers_block(config) == MatchingRule(name_contains=("bench",))


def test_empty_list_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    _write(config, "[containers]\nname_contains = []\n")
    with pytest.raises(ConfigInvalidError) as exc_info:
        load_containers_block(config)
    assert "non-empty" in exc_info.value.message


def test_non_list_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    _write(config, '[containers]\nname_contains = "bench"\n')
    with pytest.raises(ConfigInvalidError) as exc_info:
        load_containers_block(config)
    assert "list of strings" in exc_info.value.message


def test_non_string_element_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    _write(config, '[containers]\nname_contains = ["bench", 42]\n')
    with pytest.raises(ConfigInvalidError) as exc_info:
        load_containers_block(config)
    assert "must be a string" in exc_info.value.message


def test_blank_after_strip_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    _write(config, '[containers]\nname_contains = ["bench", "   "]\n')
    with pytest.raises(ConfigInvalidError) as exc_info:
        load_containers_block(config)
    assert "blank after strip()" in exc_info.value.message


def test_too_many_entries_rejected(tmp_path: Path) -> None:
    entries = ", ".join(f'"e{i}"' for i in range(33))
    config = tmp_path / "config.toml"
    _write(config, f"[containers]\nname_contains = [{entries}]\n")
    with pytest.raises(ConfigInvalidError) as exc_info:
        load_containers_block(config)
    assert "max is 32" in exc_info.value.message


def test_too_long_entry_rejected(tmp_path: Path) -> None:
    long = "x" * 129
    config = tmp_path / "config.toml"
    _write(config, f'[containers]\nname_contains = ["{long}"]\n')
    with pytest.raises(ConfigInvalidError) as exc_info:
        load_containers_block(config)
    assert "max is 128" in exc_info.value.message
