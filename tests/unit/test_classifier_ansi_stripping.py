"""T2 (review HIGH) — ANSI escape stripping in the classifier.

PTY-piped log lines often contain ANSI color codes, cursor-motion
sequences, and OSC title sequences. The classifier rule catalogue's
patterns assume escape-free input — anchored regexes like
``^Error:`` would not match ``\\x1b[31mError:`` and a `\\x1b[K`
mid-line could break ``waiting_for_input.v1``'s end-of-line
prompt-shape match.

The fix routes every record through ``strip_ansi()`` (after
redaction, before the matcher walk). The persisted ``excerpt`` is
also the escape-stripped form so terminal-render and JSON consumers
get the same content.
"""

from __future__ import annotations

import pytest

from agenttower.events.classifier import classify, strip_ansi


def test_strip_ansi_removes_csi_color_sequences() -> None:
    raw = "\x1b[31mERROR\x1b[0m"
    assert strip_ansi(raw) == "ERROR"


def test_strip_ansi_removes_cursor_motion() -> None:
    raw = "before\x1b[Kafter"
    assert strip_ansi(raw) == "beforeafter"


def test_strip_ansi_removes_osc_with_bel_terminator() -> None:
    raw = "\x1b]0;new title\x07rest"
    assert strip_ansi(raw) == "rest"


def test_strip_ansi_removes_osc_with_st_terminator() -> None:
    raw = "\x1b]2;title\x1b\\rest"
    assert strip_ansi(raw) == "rest"


def test_strip_ansi_passes_through_plain_text() -> None:
    raw = "no escapes here"
    assert strip_ansi(raw) == raw


def test_strip_ansi_handles_empty_string() -> None:
    assert strip_ansi("") == ""


def test_strip_ansi_handles_lone_escape() -> None:
    """A bare ESC byte without a terminator is not technically valid;
    the regex is conservative and may leave it (acceptable — terminal
    sanitization in the CLI catches it downstream)."""
    raw = "lone\x1b"
    out = strip_ansi(raw)
    # Either it's stripped to "lone" or left as "lone\x1b". Both are
    # acceptable; what matters is that complete sequences are stripped.
    assert "lone" in out


def test_classify_error_with_ansi_color_codes_classifies_as_error() -> None:
    """Without the fix, ``\\x1b[31mError:`` would not match
    ``error.line.v1``'s ``^(?:Error|ERROR|Exception)[: ]`` anchor."""
    out = classify("\x1b[31mError\x1b[0m: division by zero")
    assert out.event_type == "error"
    assert out.rule_id == "error.line.v1"


def test_classify_repl_prompt_with_cursor_motion_classifies_as_waiting() -> None:
    """``waiting_for_input.v1`` checks end-of-line prompt shapes
    (``>>>$``, ``Continue\\?$``). A trailing CSI sequence would break
    the ``$`` anchor without stripping."""
    out = classify("Continue?\x1b[K")
    assert out.event_type == "waiting_for_input"


def test_classify_excerpt_is_ansi_stripped() -> None:
    """The persisted ``excerpt`` is the escape-stripped form so
    terminal-render and JSON consumers see the same content."""
    out = classify("\x1b[31mError\x1b[0m: foo")
    assert "\x1b" not in out.excerpt
    assert "\x1b" not in out.redacted_record
    assert "Error: foo" in out.excerpt
