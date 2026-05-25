"""FEAT-013 frozen-clock test fixture (T015).

Used by state-machine, sweep, timeout, and recovery tests to make timing
assertions deterministic. See tasks T016 (FR-013 30-second per-stage
timeout + 2x retry assertion), T019 (FR-022 5-minute TTL sweep), T038
and T055 (FR-020 / SC-008 recovery timing).
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass


@dataclass
class FrozenClock:
    """A monotonic-ish frozen clock the tests advance manually.

    Tests inject the ``now()`` callable into the code under test (the
    callers default to ``datetime.datetime.now(datetime.UTC)`` in
    production). Use :meth:`advance` to step forward by a known delta.
    """

    current: _dt.datetime

    @classmethod
    def at(cls, iso8601: str) -> "FrozenClock":
        return cls(current=_dt.datetime.fromisoformat(iso8601))

    def now(self) -> _dt.datetime:
        return self.current

    def advance(self, *, seconds: float = 0, minutes: float = 0) -> None:
        self.current += _dt.timedelta(seconds=seconds, minutes=minutes)

    def rfc3339(self) -> str:
        """Return the current frozen time as an RFC3339 UTC string.

        Matches the format the daemon emits in audit / event records.
        """
        ts = self.current
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_dt.UTC)
        return ts.isoformat(timespec="microseconds").replace("+00:00", "Z")
