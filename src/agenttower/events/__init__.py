"""Event ingestion and classification.

FEAT-008 imports the FR-045 / Plan §"Defaults locked" constants from
this module. The FEAT-001 JSONL writer (``append_event``) is
re-exported unchanged.

This module also defines the ``Clock`` Protocol consumed by every
time-sensitive FEAT-008 surface (debounce, ``pane_exited`` /
``long_running`` synthesis, follow long-poll budget). The
:class:`SystemClock` implementation reads the wall-clock; tests
substitute a fake clock via the
``AGENTTOWER_TEST_EVENTS_CLOCK_FAKE`` env-var seam (Plan §R10).
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import os as _os
import time as _time
from typing import Protocol, runtime_checkable

from .writer import append_event

# FR-045 / Plan §"Defaults locked" — single source of truth for the
# numeric defaults named in spec.md FR-001 / FR-013 / FR-014 / FR-017 /
# FR-019 / FR-030 plus the plan-level additions for the follow long-poll
# surface. ``agenttower.config.load_events_block`` overlays user
# overrides (``[events]`` in ``config.toml``); the constants below are
# the fallback when no override is present.

#: FR-001 / SC-002 — wall-clock cap on a single reader cycle.
READER_CYCLE_WALLCLOCK_CAP_SECONDS: float = 1.0

#: FR-019 — bytes the reader will consume per attachment per cycle.
PER_CYCLE_BYTE_CAP_BYTES: int = 65536

#: spec §"Edge Cases" — cap on a single event's stored excerpt
#: (post-redaction, pre-truncation).
PER_EVENT_EXCERPT_CAP_BYTES: int = 1024

#: spec §"Edge Cases" — appended to truncated excerpts.
EXCERPT_TRUNCATION_MARKER: str = "…[truncated]"

#: FR-014 — collapse window for ``activity`` debounce.
DEBOUNCE_ACTIVITY_WINDOW_SECONDS: float = 5.0

#: FR-017 — grace window before ``pane_exited`` is emitted.
PANE_EXITED_GRACE_SECONDS: float = 30.0

#: FR-013 — grace window before ``long_running`` is emitted.
LONG_RUNNING_GRACE_SECONDS: float = 30.0

#: FR-030 — default page size for ``agenttower events``.
DEFAULT_PAGE_SIZE: int = 50

#: FR-030 — maximum page size accepted from clients.
MAX_PAGE_SIZE: int = 50

#: Plan §"Defaults locked" — server-side wait budget per
#: ``events.follow_next`` call.
FOLLOW_LONG_POLL_MAX_SECONDS: float = 30.0

#: Plan §"Defaults locked" — idle GC for follow sessions.
FOLLOW_SESSION_IDLE_TIMEOUT_SECONDS: float = 300.0


# --------------------------------------------------------------------------
# Clock Protocol (Plan §R10) — owner of the
# ``AGENTTOWER_TEST_EVENTS_CLOCK_FAKE`` test seam.
# --------------------------------------------------------------------------


@runtime_checkable
class Clock(Protocol):
    """Time source for FEAT-008's time-sensitive surfaces.

    Implementations:

    * :class:`SystemClock` — reads wall-clock and ``time.monotonic()``.
    * :class:`FakeClock` (test-only) — reads from
      ``AGENTTOWER_TEST_EVENTS_CLOCK_FAKE``; tests advance the file
      to drive deterministic time without ``time.sleep``.

    Production callers receive a ``Clock`` instance via dependency
    injection (the daemon constructs it once at boot). Direct calls
    to ``time.time()`` / ``time.monotonic()`` from FEAT-008 production
    code are forbidden — every clock read goes through this protocol.
    """

    def now_iso(self) -> str:
        """Return ISO-8601 microsecond UTC timestamp for ``observed_at``."""

    def monotonic(self) -> float:
        """Return ``time.monotonic()``-equivalent for cycle/long-poll budgets."""


class SystemClock:
    """Production :class:`Clock` implementation (wall-clock backed)."""

    def now_iso(self) -> str:
        return _dt.datetime.now(_dt.UTC).isoformat(timespec="microseconds")

    def monotonic(self) -> float:
        return _time.monotonic()


# Owner of the FEAT-008 clock seam. The AST gate at
# ``tests/unit/test_logs_offset_advance_invariant.py`` allows this
# module (and only this module) to reference the env-var name;
# all other FEAT-008 production code receives a ``Clock`` via DI.
_CLOCK_FAKE_ENV_VAR = "AGENTTOWER_TEST_EVENTS_CLOCK_FAKE"


class FakeClock:
    """Test-only :class:`Clock` reading from the
    ``AGENTTOWER_TEST_EVENTS_CLOCK_FAKE`` env var.

    The env var value is a path; the file at that path is JSON of shape
    ``{"observed_at_iso": <ISO>, "monotonic": <float>}``. Tests mutate
    the file to advance time deterministically.
    """

    def __init__(self, fake_path: str) -> None:
        self._fake_path = fake_path

    def _read(self) -> dict[str, object]:
        with open(self._fake_path, encoding="utf-8") as fh:
            data = _json.load(fh)
        if not isinstance(data, dict):
            raise ValueError(
                f"{_CLOCK_FAKE_ENV_VAR} at {self._fake_path!r} must be a JSON object"
            )
        return data

    def now_iso(self) -> str:
        value = self._read().get("observed_at_iso")
        if not isinstance(value, str):
            raise ValueError(
                f"{_CLOCK_FAKE_ENV_VAR} JSON missing 'observed_at_iso' string"
            )
        return value

    def monotonic(self) -> float:
        value = self._read().get("monotonic")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(
                f"{_CLOCK_FAKE_ENV_VAR} JSON missing numeric 'monotonic'"
            )
        return float(value)


def resolve_clock() -> Clock:
    """Return the appropriate :class:`Clock` implementation.

    Honors :data:`_CLOCK_FAKE_ENV_VAR` only when set (test-only path);
    otherwise returns a fresh :class:`SystemClock`. Tests set the env
    var via ``monkeypatch.setenv`` and a temp-file path; production
    daemons unset the var (the conftest fixture
    ``_isolate_feat008_test_seams`` ensures this).
    """
    fake_path = _os.environ.get(_CLOCK_FAKE_ENV_VAR)
    if fake_path:
        return FakeClock(fake_path)
    return SystemClock()


__all__ = [
    "append_event",
    "READER_CYCLE_WALLCLOCK_CAP_SECONDS",
    "PER_CYCLE_BYTE_CAP_BYTES",
    "PER_EVENT_EXCERPT_CAP_BYTES",
    "EXCERPT_TRUNCATION_MARKER",
    "DEBOUNCE_ACTIVITY_WINDOW_SECONDS",
    "PANE_EXITED_GRACE_SECONDS",
    "LONG_RUNNING_GRACE_SECONDS",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "FOLLOW_LONG_POLL_MAX_SECONDS",
    "FOLLOW_SESSION_IDLE_TIMEOUT_SECONDS",
    "Clock",
    "SystemClock",
    "FakeClock",
    "resolve_clock",
]
