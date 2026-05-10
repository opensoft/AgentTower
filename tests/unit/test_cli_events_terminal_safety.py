"""CRIT-1 — terminal control-byte injection safety.

Event excerpts come from arbitrary log content (post-redaction). They
flow through ``redact_one_line`` (FEAT-007) but the redactor strips
secrets, not control bytes. ANSI escape sequences (`\\x1b[...m`,
`\\x1b]0;...\\x07`), carriage returns, backspaces, and tabs survive.

Without sanitization, the human-mode CLI renderer would write these
bytes verbatim to the operator's terminal — letting an attacker who
can write to a pane log manipulate the operator's terminal: clear
screen, hide subsequent events, spoof the terminal title, corrupt
column alignment.

The fix is ``cli._sanitize_for_terminal``: every C0 control byte +
DEL is replaced with its `\\xNN` escape representation before print.
JSON output is unaffected (Python's json escapes control bytes
already).
"""

from __future__ import annotations

import importlib

cli = importlib.import_module("agenttower.cli")


def test_sanitize_strips_ansi_color_sequence() -> None:
    raw = "\x1b[31mERROR\x1b[0m: boom"
    out = cli._sanitize_for_terminal(raw)
    assert "\x1b" not in out
    # Sentinel form is readable: \x1b[31mERROR...
    assert "\\x1b" in out


def test_sanitize_strips_clear_screen() -> None:
    raw = "\x1b[2J\x1b[H[INJECTED]"
    out = cli._sanitize_for_terminal(raw)
    assert "\x1b" not in out
    assert "[INJECTED]" in out


def test_sanitize_strips_osc_title_spoof() -> None:
    raw = "\x1b]0;PWNED\x07normal text"
    out = cli._sanitize_for_terminal(raw)
    assert "\x1b" not in out
    assert "\x07" not in out
    assert "PWNED" in out  # the visible portion is still readable


def test_sanitize_strips_carriage_return() -> None:
    raw = "info\rmalicious"
    out = cli._sanitize_for_terminal(raw)
    assert "\r" not in out
    assert "malicious" in out
    assert "info" in out


def test_sanitize_strips_backspace_and_tab() -> None:
    raw = "col1\tcol2\bx"
    out = cli._sanitize_for_terminal(raw)
    assert "\t" not in out
    assert "\b" not in out


def test_sanitize_passes_through_printable_ascii() -> None:
    raw = "Error: division by zero (x=42)"
    assert cli._sanitize_for_terminal(raw) == raw


def test_sanitize_passes_through_unicode() -> None:
    raw = "résumé 中文 🎉"
    assert cli._sanitize_for_terminal(raw) == raw


def test_sanitize_strips_del_byte() -> None:
    raw = "before\x7fafter"
    out = cli._sanitize_for_terminal(raw)
    assert "\x7f" not in out
    assert "before" in out
    assert "after" in out


def test_sanitize_handles_empty_string() -> None:
    assert cli._sanitize_for_terminal("") == ""


def test_sanitize_handles_only_control_bytes() -> None:
    raw = "\x00\x01\x02\x03\x04\x05\x06\x07\x08"
    out = cli._sanitize_for_terminal(raw)
    assert "\x00" not in out
    assert "\x07" not in out
    # All represented as escape sentinels.
    assert all(c in "\\x0123456789abcdef" for c in out)
