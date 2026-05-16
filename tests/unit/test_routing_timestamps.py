"""T018 — FEAT-009 timestamp helper tests.

Covers FR-012b canonical encoding + Clarifications session 2 Q5
(``--since`` accepts both ms and seconds UTC forms).

Test surface:

* ``now_iso_ms_utc`` returns the exact canonical form (millis, ``Z``).
* ``parse_since`` round-trips the canonical form.
* ``parse_since`` accepts the seconds-precision form (operator convenience).
* ``parse_since`` REJECTS: lowercase ``z``, +HH:MM offsets,
  microsecond precision, epoch-seconds, date-only, naive datetime input.
* :class:`FakeClock` seam advances both wall-clock and monotonic.
* ``load_clock_from_env`` honors ``AGENTTOWER_TEST_ROUTING_CLOCK_FAKE``.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime

import pytest

from agenttower.routing.timestamps import (
    FakeClock,
    SinceFormatError,
    SystemClock,
    load_clock_from_env,
    now_iso_ms_utc,
    parse_since,
)


# ──────────────────────────────────────────────────────────────────────
# now_iso_ms_utc
# ──────────────────────────────────────────────────────────────────────

_CANONICAL_FORM = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


def test_now_iso_ms_utc_returns_canonical_form() -> None:
    out = now_iso_ms_utc()
    assert _CANONICAL_FORM.match(out), f"not canonical: {out!r}"


def test_now_iso_ms_utc_uses_provided_clock() -> None:
    clock = FakeClock(utcnow_iso="2026-07-04T12:34:56.789Z")
    assert now_iso_ms_utc(clock) == "2026-07-04T12:34:56.789Z"


def test_now_iso_ms_utc_normalizes_non_utc_tz_to_utc() -> None:
    """A tz-aware datetime in a non-UTC zone is normalized to UTC before
    formatting; this guards against accidental local-tz timestamps."""
    from datetime import timedelta, timezone

    pacific = timezone(timedelta(hours=-7))

    class FixedClock:
        def utcnow(self) -> datetime:
            # 5pm Pacific = midnight UTC.
            return datetime(2026, 5, 11, 17, 0, 0, 123_000, tzinfo=pacific)

        def monotonic(self) -> float:
            return 0.0

    assert now_iso_ms_utc(FixedClock()) == "2026-05-12T00:00:00.123Z"


def test_now_iso_ms_utc_rejects_naive_datetime() -> None:
    """A tz-naive datetime from a buggy clock must raise (defensive)."""

    class NaiveClock:
        def utcnow(self) -> datetime:
            return datetime(2026, 5, 11, 0, 0, 0)  # naive

        def monotonic(self) -> float:
            return 0.0

    with pytest.raises(ValueError, match="timezone-aware"):
        now_iso_ms_utc(NaiveClock())


# ──────────────────────────────────────────────────────────────────────
# parse_since happy paths
# ──────────────────────────────────────────────────────────────────────


def test_parse_since_accepts_canonical_millisecond_form() -> None:
    out = parse_since("2026-05-11T15:32:04.123Z")
    assert out == datetime(2026, 5, 11, 15, 32, 4, 123_000, tzinfo=UTC)


def test_parse_since_accepts_seconds_precision_form() -> None:
    """Clarifications session 2 Q5: operator convenience form."""
    out = parse_since("2026-05-11T15:32:04Z")
    assert out == datetime(2026, 5, 11, 15, 32, 4, tzinfo=UTC)


def test_parse_since_round_trips_with_now_iso_ms_utc() -> None:
    clock = FakeClock(utcnow_iso="2026-05-11T15:32:04.123Z")
    rendered = now_iso_ms_utc(clock)
    parsed = parse_since(rendered)
    re_rendered = (
        parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"
    )
    assert rendered == re_rendered


# ──────────────────────────────────────────────────────────────────────
# parse_since rejections
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        # Lowercase z is not accepted (per FR-012b).
        "2026-05-11T15:32:04.123z",
        # Offset other than literal Z is rejected.
        "2026-05-11T15:32:04+00:00",
        "2026-05-11T15:32:04.123+00:00",
        "2026-05-11T15:32:04-07:00",
        # Microsecond precision is rejected (FR-012b is millisecond).
        "2026-05-11T15:32:04.123456Z",
        # Epoch seconds.
        "1747000000",
        # Date-only.
        "2026-05-11",
        # Empty.
        "",
        # Whitespace.
        " 2026-05-11T15:32:04.123Z",
        "2026-05-11T15:32:04.123Z ",
        # Wrong separator.
        "2026-05-11 15:32:04.123Z",
        # Garbage.
        "not a timestamp",
    ],
)
def test_parse_since_rejects_invalid_forms(bad: str) -> None:
    with pytest.raises(SinceFormatError):
        parse_since(bad)


def test_parse_since_rejects_out_of_range_fields() -> None:
    """Month=13 must raise SinceFormatError, not let datetime.ValueError leak."""
    with pytest.raises(SinceFormatError):
        parse_since("2026-13-01T00:00:00.000Z")
    with pytest.raises(SinceFormatError):
        parse_since("2026-02-30T00:00:00.000Z")  # not a leap-year edge — just no Feb 30


def test_parse_since_rejects_non_string_input() -> None:
    with pytest.raises(SinceFormatError):
        parse_since(1747000000)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────
# Clock seam
# ──────────────────────────────────────────────────────────────────────


def test_system_clock_monotonic_advances_with_real_time() -> None:
    """SystemClock's monotonic uses time.monotonic; consecutive calls
    are nondecreasing."""
    c = SystemClock()
    a = c.monotonic()
    b = c.monotonic()
    assert b >= a


def test_fake_clock_advance_moves_both_clocks() -> None:
    fc = FakeClock(utcnow_iso="2026-05-11T00:00:00.000Z", monotonic=10.0)
    before_iso = now_iso_ms_utc(fc)
    before_mono = fc.monotonic()
    fc.advance(seconds=2.5)
    after_iso = now_iso_ms_utc(fc)
    after_mono = fc.monotonic()
    assert before_iso == "2026-05-11T00:00:00.000Z"
    assert after_iso == "2026-05-11T00:00:02.500Z"
    assert before_mono == 10.0
    assert after_mono == 12.5


def test_fake_clock_rejects_invalid_initial_iso() -> None:
    with pytest.raises(SinceFormatError):
        FakeClock(utcnow_iso="2026-05-11")  # invalid form


# ──────────────────────────────────────────────────────────────────────
# Env-var seam
# ──────────────────────────────────────────────────────────────────────


def test_load_clock_from_env_returns_system_clock_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENTTOWER_TEST_ROUTING_CLOCK_FAKE", raising=False)
    assert isinstance(load_clock_from_env(), SystemClock)


def test_load_clock_from_env_returns_fake_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AGENTTOWER_TEST_ROUTING_CLOCK_FAKE",
        '{"now_iso_ms_utc":"2026-12-25T00:00:00.000Z","monotonic":42.0}',
    )
    clock = load_clock_from_env()
    assert isinstance(clock, FakeClock)
    assert now_iso_ms_utc(clock) == "2026-12-25T00:00:00.000Z"
    assert clock.monotonic() == 42.0


def test_load_clock_from_env_rejects_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AGENTTOWER_TEST_ROUTING_CLOCK_FAKE",
        "{this is not json}",
    )
    with pytest.raises(ValueError, match="not valid JSON"):
        load_clock_from_env()


def test_load_clock_from_env_with_empty_env_var_returns_system_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty-string env-var (vs unset) should also fall through to SystemClock."""
    monkeypatch.setenv("AGENTTOWER_TEST_ROUTING_CLOCK_FAKE", "")
    assert isinstance(load_clock_from_env(), SystemClock)
