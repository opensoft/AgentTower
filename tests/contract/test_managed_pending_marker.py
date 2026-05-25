"""FEAT-013 pending-managed marker contract test (T019).

Covers FR-014 marker format + parsing (the FEAT-004 scan must be able
to detect ``@MANAGED:<token>:<label>`` titles and skip pending panes),
plus the FR-022 5-minute TTL constant + sweep cadence.

The actual SQLite sweep loop is wired by T050 (Phase 6); this contract
exercises only the format / parsing / constants — what the scan and the
service.py spawn path depend on.
"""

from __future__ import annotations

import pytest

from agenttower.managed_sessions.pending_marker import (
    MARKER_TITLE_PREFIX,
    MARKER_TTL_SECONDS,
    SWEEP_INTERVAL_SECONDS,
    format_title,
    is_marker_title,
    new_marker_token,
    parse_title,
)


# ─── Constants (FR-022 + research §R5) ────────────────────────────────────


def test_ttl_is_five_minutes() -> None:
    """FR-022 sweep TTL = 5 minutes = 300 seconds."""
    assert MARKER_TTL_SECONDS == 300


def test_sweep_interval_is_60_seconds() -> None:
    """Research §R5: sweep runs every 60s + at boot."""
    assert SWEEP_INTERVAL_SECONDS == 60


def test_marker_prefix_constant() -> None:
    assert MARKER_TITLE_PREFIX == "@MANAGED:"


# ─── Token generation ────────────────────────────────────────────────────


def test_new_marker_token_is_unique() -> None:
    tokens = {new_marker_token() for _ in range(100)}
    assert len(tokens) == 100  # 100 distinct uuid4 values


def test_new_marker_token_is_non_empty_string() -> None:
    tok = new_marker_token()
    assert isinstance(tok, str)
    assert tok


# ─── Title format + parse round-trip ─────────────────────────────────────


def test_format_title_with_uuid_token_and_label() -> None:
    title = format_title("abc-123", "m1")
    assert title == "@MANAGED:abc-123:m1"


def test_parse_round_trip() -> None:
    """parse_title(format_title(t, l)) == (t, l)."""
    title = format_title("tok-xyz", "s2")
    parsed = parse_title(title)
    assert parsed == ("tok-xyz", "s2")


def test_format_title_rejects_empty_token() -> None:
    with pytest.raises(ValueError):
        format_title("", "label")


def test_format_title_rejects_empty_label() -> None:
    with pytest.raises(ValueError):
        format_title("token", "")


def test_format_title_rejects_token_with_colon() -> None:
    """``:`` separates the token from the label; tokens with ``:`` would
    confuse the parser."""
    with pytest.raises(ValueError):
        format_title("bad:token", "label")


# ─── Parse rejects non-marker titles ─────────────────────────────────────


def test_parse_returns_none_on_non_marker_title() -> None:
    """FEAT-004 scan: non-marker titles return ``None`` so the scan
    proceeds with normal adoption."""
    assert parse_title("just-a-pane-title") is None
    assert parse_title("@MANAGE:tok:lbl") is None  # close but no cigar
    assert parse_title("") is None


def test_is_marker_title_helper() -> None:
    assert is_marker_title("@MANAGED:tok:lbl")
    assert not is_marker_title("regular-title")
    assert not is_marker_title("")


# ─── Labels with special characters round-trip ──────────────────────────


def test_label_with_hyphens_and_dots_round_trips() -> None:
    """Labels resolved from operator templates can contain ``[A-Za-z0-9_.-]``
    per FR-016 amendment; the marker format must round-trip them."""
    title = format_title("uuid-1234", "host.example.com-m1")
    assert parse_title(title) == ("uuid-1234", "host.example.com-m1")


def test_label_with_colon_round_trips_via_greedy_match() -> None:
    """If a label contains ``:`` (rare; allowed character set excludes ``:``
    but be defensive), the parser greedy-matches everything after the
    first ``:`` as the label."""
    # This case is theoretical — FR-016 amendment disallows ``:`` in
    # operator-supplied labels — but the parser shouldn't crash if a
    # legacy title slips through.
    title = "@MANAGED:tok:label:with:colons"
    parsed = parse_title(title)
    assert parsed == ("tok", "label:with:colons")
