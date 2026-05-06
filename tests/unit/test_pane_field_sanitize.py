"""Unit tests for FEAT-004 sanitize_text helper (T016 / FR-023 / R-009)."""

from __future__ import annotations

import pytest

from agenttower.tmux import parsers


def test_sanitize_drops_nul_byte() -> None:
    cleaned, truncated = parsers.sanitize_text("hello\x00world", 100)
    assert cleaned == "helloworld"
    assert truncated is False


def test_sanitize_drops_c0_control_bytes() -> None:
    raw = "a\x01b\x02c\x07d\x1ee\x7ff"
    cleaned, _ = parsers.sanitize_text(raw, 100)
    assert cleaned == "abcdef"


def test_sanitize_replaces_tab_and_newline_with_space() -> None:
    cleaned, _ = parsers.sanitize_text("a\tb\nc", 100)
    assert cleaned == "a b c"


def test_sanitize_truncates_to_max_length_character_aware() -> None:
    cleaned, truncated = parsers.sanitize_text("a" * 4097, parsers.MAX_PATH)
    assert truncated is True
    assert len(cleaned) == parsers.MAX_PATH


def test_sanitize_does_not_truncate_under_limit() -> None:
    cleaned, truncated = parsers.sanitize_text("hi", 10)
    assert cleaned == "hi"
    assert truncated is False


def test_sanitize_utf8_aware_truncation_counts_characters_not_bytes() -> None:
    # Multi-byte chars should count as 1 character each.
    raw = "é" * 3000  # 6000 bytes, 3000 chars
    cleaned, truncated = parsers.sanitize_text(raw, parsers.MAX_TITLE)
    assert truncated is True
    assert len(cleaned) == parsers.MAX_TITLE
    # All survived chars are still the full multi-byte char (no split mid-char).
    assert all(c == "é" for c in cleaned)


def test_sanitize_handles_none() -> None:
    cleaned, truncated = parsers.sanitize_text(None, 100)  # type: ignore[arg-type]
    assert cleaned == ""
    assert truncated is False


def test_sanitize_returns_tuple_with_truncated_flag() -> None:
    cleaned, flag = parsers.sanitize_text("ok", 100)
    assert isinstance(cleaned, str)
    assert isinstance(flag, bool)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("\x00\x01\x02hello", "hello"),
        ("hello\x7f", "hello"),
        ("hello\x08\x0bworld", "helloworld"),
    ],
)
def test_sanitize_strip_specific_byte_classes(raw: str, expected: str) -> None:
    cleaned, _ = parsers.sanitize_text(raw, 100)
    assert cleaned == expected
