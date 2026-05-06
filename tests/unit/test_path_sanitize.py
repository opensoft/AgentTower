"""Unit tests for sanitize.py — FR-021 / FR-028 / R-008 (CHK043–CHK048)."""

from __future__ import annotations

from agenttower.config_doctor.sanitize import (
    ACTIONABLE_CAP,
    DETAILS_CAP,
    ENV_VALUE_CAP,
    FILE_CONTENT_CAP,
    sanitize_text,
)


class TestCapConstants:
    def test_caps_have_exact_spelling_and_values(self):
        assert ENV_VALUE_CAP == 4096
        assert FILE_CONTENT_CAP == 4096
        assert DETAILS_CAP == 2048
        assert ACTIONABLE_CAP == 2048


class TestNULStripping:
    def test_nul_byte_stripped(self):
        out, truncated = sanitize_text("hello\x00world", DETAILS_CAP)
        assert out == "helloworld"
        assert truncated is False

    def test_only_nul_yields_empty_string(self):
        out, truncated = sanitize_text("\x00\x00\x00", DETAILS_CAP)
        assert out == ""
        assert truncated is False


class TestC0Stripping:
    def test_c0_range_dropped(self):
        raw = "a" + "".join(chr(c) for c in range(0x01, 0x09)) + "b"
        out, truncated = sanitize_text(raw, DETAILS_CAP)
        assert out == "ab"
        assert truncated is False

    def test_high_c0_range_dropped(self):
        raw = "x" + "".join(chr(c) for c in range(0x0B, 0x20)) + "y"
        out, truncated = sanitize_text(raw, DETAILS_CAP)
        assert out == "xy"
        assert truncated is False

    def test_del_byte_dropped(self):
        out, _ = sanitize_text("a\x7fb", DETAILS_CAP)
        assert out == "ab"

    def test_printable_ascii_preserved(self):
        raw = "".join(chr(c) for c in range(0x20, 0x7F))
        out, truncated = sanitize_text(raw, DETAILS_CAP)
        assert out == raw
        assert truncated is False


class TestTabAndNewlineSubstitution:
    def test_tab_becomes_single_space(self):
        out, _ = sanitize_text("a\tb", DETAILS_CAP)
        assert out == "a b"

    def test_newline_becomes_single_space(self):
        out, _ = sanitize_text("a\nb", DETAILS_CAP)
        assert out == "a b"

    def test_consecutive_tabs_each_become_a_space(self):
        out, _ = sanitize_text("a\t\tb", DETAILS_CAP)
        assert out == "a  b"

    def test_mixed_tab_and_newline(self):
        out, _ = sanitize_text("a\tb\nc", DETAILS_CAP)
        assert out == "a b c"


class TestTruncation:
    def test_no_truncation_under_cap(self):
        out, truncated = sanitize_text("abc", DETAILS_CAP)
        assert out == "abc"
        assert truncated is False

    def test_no_truncation_at_exactly_cap(self):
        raw = "a" * DETAILS_CAP
        out, truncated = sanitize_text(raw, DETAILS_CAP)
        assert out == raw
        assert truncated is False
        assert len(out) == DETAILS_CAP

    def test_truncation_over_cap_appends_marker(self):
        raw = "a" * (DETAILS_CAP + 50)
        out, truncated = sanitize_text(raw, DETAILS_CAP)
        assert truncated is True
        assert len(out) == DETAILS_CAP
        assert out.endswith("…")
        assert out[:-1] == "a" * (DETAILS_CAP - 1)

    def test_truncation_marker_is_single_unicode_character(self):
        raw = "a" * (DETAILS_CAP + 1)
        out, truncated = sanitize_text(raw, DETAILS_CAP)
        assert truncated is True
        # U+2026 is a single character, NOT three ASCII dots
        assert out[-1] == "…"
        assert out[-1] != "."
        assert ord(out[-1]) == 0x2026
        # Total length is exactly the cap (one marker char + DETAILS_CAP-1 raw chars)
        assert len(out) == DETAILS_CAP

    def test_truncation_preserves_multibyte_utf8(self):
        # 4-byte UTF-8 character (emoji)
        emoji = "\U0001f600"
        # Build a string of 1000 emojis = 1000 characters
        raw = emoji * 1000
        out, truncated = sanitize_text(raw, 500)
        assert truncated is True
        # Output should still be 500 characters and never split a multi-byte char
        assert len(out) == 500
        # All but the last char should be intact emojis
        assert all(c == emoji for c in out[:-1])
        assert out[-1] == "…"

    def test_truncation_marker_replaces_only_one_character_position(self):
        raw = "x" * 100
        out, truncated = sanitize_text(raw, 10)
        assert truncated is True
        assert out == "x" * 9 + "…"
        assert len(out) == 10


class TestSmallCaps:
    def test_actionable_cap_truncates_at_2048(self):
        raw = "z" * 3000
        out, truncated = sanitize_text(raw, ACTIONABLE_CAP)
        assert truncated is True
        assert len(out) == 2048

    def test_env_value_cap_truncates_at_4096(self):
        raw = "z" * 5000
        out, truncated = sanitize_text(raw, ENV_VALUE_CAP)
        assert truncated is True
        assert len(out) == 4096

    def test_max_length_one_handles_truncation(self):
        out, truncated = sanitize_text("xxxx", 1)
        assert truncated is True
        assert out == "…"

    def test_max_length_zero_rejected(self):
        import pytest

        with pytest.raises(ValueError):
            sanitize_text("anything", 0)


class TestEmpty:
    def test_empty_input_returns_empty(self):
        out, truncated = sanitize_text("", DETAILS_CAP)
        assert out == ""
        assert truncated is False


class TestSanitizeAndTruncateInteraction:
    def test_nul_stripped_first_then_length_check(self):
        # 5 NULs + 5 valid characters; should NOT be truncated since post-strip
        # length is well under cap.
        raw = "\x00\x00\x00\x00\x00abcde"
        out, truncated = sanitize_text(raw, DETAILS_CAP)
        assert out == "abcde"
        assert truncated is False
