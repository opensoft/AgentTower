"""FEAT-009 canonical timestamp encoding (FR-012b / Clarifications Q5).

Every FEAT-009 timestamp surface — SQLite columns, ``events.jsonl`` rows,
all ``--json`` outputs, the queue listing — uses the same ISO 8601 form:
millisecond resolution, UTC, literal ``Z`` suffix. Example:
``2026-05-11T15:32:04.123Z``.

The :class:`Clock` Protocol seam is consumed by the delivery worker, the
audit writer, and every state transition so tests can advance perceived
time deterministically via the ``AGENTTOWER_TEST_ROUTING_CLOCK_FAKE``
environment variable (T053 conftest seam).

The ``--since`` parser (:func:`parse_since`) accepts both the canonical
millisecond form and the seconds-precision form (operator convenience,
locked in Clarifications session 2 Q5). Anything else raises
:class:`SinceFormatError` which maps to closed-set
``since_invalid_format`` at the CLI boundary (FR-049).
"""

from __future__ import annotations

import os
import re
import time as _time
from datetime import UTC, datetime
from typing import Protocol


# ──────────────────────────────────────────────────────────────────────
# Canonical render
# ──────────────────────────────────────────────────────────────────────

_CANONICAL_REGEX = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"T(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})"
    r"(?:\.(?P<ms>\d{3}))?Z$"
)
"""Matches the canonical millisecond form AND the seconds form.

The optional ``\\.(?P<ms>\\d{3})`` captures the millisecond fragment when
present. Anything else (microseconds, +00:00 offset, lowercase ``z``,
date-only, epoch-seconds) is rejected.
"""


class SinceFormatError(ValueError):
    """Raised by :func:`parse_since` when the input does not match either
    accepted form. The CLI maps this to closed-set ``since_invalid_format``
    (FR-049)."""


def _format_iso_ms_utc(dt: datetime) -> str:
    """Format a tz-aware UTC datetime as ``YYYY-MM-DDTHH:MM:SS.sssZ``."""
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    # Normalize to UTC if a non-UTC tz was supplied.
    dt_utc = dt.astimezone(UTC)
    millis = dt_utc.microsecond // 1000
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def format_iso_ms_utc(dt: datetime) -> str:
    """Public canonical-form formatter (``YYYY-MM-DDTHH:MM:SS.sssZ``).

    Used by callers that need to render a parsed timestamp back to the
    canonical millisecond form before SQL comparisons — e.g. the
    ``queue.list`` dispatcher normalizes the operator's ``--since``
    argument here so a seconds-precision input
    (``2026-05-12T00:00:04Z``) compares correctly against ms-precision
    ``enqueued_at`` values (``2026-05-12T00:00:04.123Z``) under the
    DAO's lexicographic ``>=`` test (string order has
    ``...04.123Z < ...04Z``, so the raw seconds form would
    incorrectly exclude rows in the same second).
    """
    return _format_iso_ms_utc(dt)


# ──────────────────────────────────────────────────────────────────────
# Clock Protocol + production / fake implementations
# ──────────────────────────────────────────────────────────────────────


class Clock(Protocol):
    """Time source consumed by FEAT-009 hot-path code.

    Splitting wall-clock (`utcnow`) from monotonic (`monotonic`) makes
    timing seamable: the FR-009 wait timeout and the per-attempt timeout
    use `monotonic` (drift-free); the `enqueued_at` / transition stamps
    use `utcnow` (operator-readable).
    """

    def utcnow(self) -> datetime: ...
    def monotonic(self) -> float: ...


class SystemClock:
    """Production :class:`Clock` implementation."""

    def utcnow(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return _time.monotonic()


class FakeClock:
    """Test-only :class:`Clock` implementation.

    Driven either programmatically (``FakeClock(utcnow_iso=..., monotonic=...)``)
    or via the ``AGENTTOWER_TEST_ROUTING_CLOCK_FAKE`` environment variable
    consumed at boot by the daemon's `DaemonContext` (T053).
    """

    def __init__(self, *, utcnow_iso: str = "2026-05-11T00:00:00.000Z",
                 monotonic: float = 0.0) -> None:
        self._utcnow = self._parse_canonical(utcnow_iso)
        self._monotonic = monotonic

    @staticmethod
    def _parse_canonical(iso_ms: str) -> datetime:
        m = _CANONICAL_REGEX.match(iso_ms)
        if m is None:
            raise SinceFormatError(f"invalid canonical form: {iso_ms!r}")
        ms_frag = m.group("ms") or "000"
        return datetime(
            int(m["y"]), int(m["mo"]), int(m["d"]),
            int(m["h"]), int(m["mi"]), int(m["s"]),
            int(ms_frag) * 1000,
            tzinfo=UTC,
        )

    def advance(self, *, seconds: float) -> None:
        """Advance both wall-clock and monotonic by ``seconds``."""
        from datetime import timedelta as _td
        self._utcnow = self._utcnow + _td(seconds=seconds)
        self._monotonic = self._monotonic + seconds

    def utcnow(self) -> datetime:
        return self._utcnow

    def monotonic(self) -> float:
        return self._monotonic


# ──────────────────────────────────────────────────────────────────────
# Module-level helpers
# ──────────────────────────────────────────────────────────────────────


_DEFAULT_CLOCK: Clock = SystemClock()


def now_iso_ms_utc(clock: Clock | None = None) -> str:
    """Return the current canonical FEAT-009 timestamp.

    Form: ``YYYY-MM-DDTHH:MM:SS.sssZ`` (millisecond resolution, UTC, ``Z``
    suffix). FR-012b is the spec contract; the FakeClock seam lets tests
    inject deterministic values.
    """
    return _format_iso_ms_utc((clock or _DEFAULT_CLOCK).utcnow())


def parse_since(value: str) -> datetime:
    """Parse a ``--since`` operator argument.

    Accepts either:
      * Canonical millisecond form:  ``2026-05-11T15:32:04.123Z``
      * Seconds-precision form:      ``2026-05-11T15:32:04Z``

    Returns a tz-aware UTC :class:`datetime`. Both forms must end in a
    literal ``Z``; offsets (``+00:00``, ``+05:30``), lowercase ``z``,
    epoch-seconds, and date-only inputs are rejected.

    Raises :class:`SinceFormatError` on any other form. The CLI maps
    this to closed-set ``since_invalid_format`` (FR-049).
    """
    if not isinstance(value, str):
        raise SinceFormatError(f"--since must be a string; got {type(value).__name__}")
    m = _CANONICAL_REGEX.match(value)
    if m is None:
        raise SinceFormatError(
            f"--since must be YYYY-MM-DDTHH:MM:SS[.sss]Z (UTC); got {value!r}"
        )
    ms_frag = m.group("ms") or "000"
    try:
        return datetime(
            int(m["y"]), int(m["mo"]), int(m["d"]),
            int(m["h"]), int(m["mi"]), int(m["s"]),
            int(ms_frag) * 1000,
            tzinfo=UTC,
        )
    except ValueError as exc:
        # E.g., month=13, day=32. Re-raise as our type.
        raise SinceFormatError(f"--since contained out-of-range field: {exc}") from exc


def load_clock_from_env() -> Clock:
    """Construct a :class:`Clock` honoring the test seam env-var.

    Reads ``AGENTTOWER_TEST_ROUTING_CLOCK_FAKE`` per the T053 conftest
    contract:

      * Unset / empty → :class:`SystemClock`.
      * JSON ``{"now_iso_ms_utc": "...Z", "monotonic": <float>}`` →
        :class:`FakeClock`.

    Daemons consume this once at boot via :class:`DaemonContext`; tests
    rewrite the env-var between operations and re-construct the clock.
    """
    raw = os.environ.get("AGENTTOWER_TEST_ROUTING_CLOCK_FAKE")
    if not raw:
        return SystemClock()
    import json
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"AGENTTOWER_TEST_ROUTING_CLOCK_FAKE is not valid JSON: {exc}"
        ) from exc
    return FakeClock(
        utcnow_iso=payload.get("now_iso_ms_utc", "2026-05-11T00:00:00.000Z"),
        monotonic=float(payload.get("monotonic", 0.0)),
    )
