"""Unit coverage for FEAT-008 [events] configuration validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.config import ConfigInvalidError, load_events_block


def test_events_default_page_size_cannot_exceed_max_page_size(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "[events]\n"
        "default_page_size = 20\n"
        "max_page_size = 10\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigInvalidError) as excinfo:
        load_events_block(config)

    assert "default_page_size (20) must be" in excinfo.value.message


def test_events_cap_error_uses_resolved_default_without_keyerror(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "[events]\n"
        "default_page_size = 51\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigInvalidError) as excinfo:
        load_events_block(config)

    assert "default_page_size" in excinfo.value.message
    assert "got 51" in excinfo.value.message
