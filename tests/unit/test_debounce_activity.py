"""T027 — debounce activity-collapse tests.

Per FR-014: ``activity`` is the only collapse-eligible class. Multiple
activities within one window collapse into one emitted event whose
excerpt is the latest record's redacted excerpt and whose debounce
metadata records the count + window bounds.
"""

from __future__ import annotations

import re

from agenttower.events.classifier import ClassifierOutcome
from agenttower.events.debounce import DebounceManager


def _outcome(rule_id: str = "activity.fallback.v1", excerpt: str = "x") -> ClassifierOutcome:
    return ClassifierOutcome(
        event_type="activity",
        rule_id=rule_id,
        excerpt=excerpt,
        redacted_record=excerpt,
    )


def _submit(
    mgr: DebounceManager,
    attachment_id: str,
    *,
    excerpt: str,
    monotonic: float,
    observed_at: str,
    byte_start: int = 0,
    byte_end: int = 10,
    line_start: int = 0,
    line_end: int = 1,
) -> list:
    return mgr.submit(
        attachment_id=attachment_id,
        outcome=_outcome(excerpt=excerpt),
        observed_at=observed_at,
        monotonic=monotonic,
        byte_range_start=byte_start,
        byte_range_end=byte_end,
        line_offset_start=line_start,
        line_offset_end=line_end,
    )


def test_first_activity_opens_window_emits_nothing() -> None:
    mgr = DebounceManager()
    out = _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="x", monotonic=100.0, observed_at="t1")
    assert out == []


def test_activity_within_window_collapses_no_emission() -> None:
    """Multiple activities within ``debounce_activity_window_seconds``
    collapse into one open window; no event is emitted yet."""
    mgr = DebounceManager(activity_window_seconds=5.0)
    assert _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="x1", monotonic=100.0, observed_at="t1") == []
    assert _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="x2", monotonic=101.0, observed_at="t2") == []
    assert _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="x3", monotonic=104.9, observed_at="t3") == []


def test_activity_window_closes_on_next_record_after_budget() -> None:
    mgr = DebounceManager(activity_window_seconds=5.0)
    _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="x1", monotonic=100.0, observed_at="t1",
            byte_start=0, byte_end=10, line_start=0, line_end=1)
    _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="x2", monotonic=101.0, observed_at="t2",
            byte_start=10, byte_end=20, line_start=1, line_end=2)
    # Now t=106.0 — past the 5 s budget. The arriving record CLOSES
    # the prior window and seeds a new one. We get exactly one emit.
    emitted = _submit(
        mgr, "atc_aaaaaaaaaaaa", excerpt="x3", monotonic=106.0, observed_at="t3",
        byte_start=20, byte_end=30, line_start=2, line_end=3,
    )
    assert len(emitted) == 1
    e = emitted[0]
    assert e.event_type == "activity"
    assert e.rule_id == "activity.fallback.v1"
    assert e.debounce_collapsed_count == 2  # x1 + x2
    assert e.excerpt == "x2"  # latest in the closed window (FR-014)
    assert e.debounce_window_started_at == "t1"
    assert e.debounce_window_ended_at == "t3"
    # Byte/line range spans first record's start to LATEST record's end.
    assert e.byte_range_start == 0
    assert e.byte_range_end == 20
    assert e.line_offset_start == 0
    assert e.line_offset_end == 2
    # window_id is opaque 12-hex.
    assert e.debounce_window_id is not None
    assert re.match(r"^[0-9a-f]{12}$", e.debounce_window_id)


def test_collapsed_count_math_three_records() -> None:
    mgr = DebounceManager(activity_window_seconds=5.0)
    for i in range(3):
        _submit(mgr, "atc_aaaaaaaaaaaa", excerpt=f"x{i}", monotonic=100.0 + i, observed_at=f"t{i}")
    emitted = _submit(
        mgr, "atc_aaaaaaaaaaaa", excerpt="next", monotonic=120.0, observed_at="t99",
    )
    assert len(emitted) == 1
    assert emitted[0].debounce_collapsed_count == 3


def test_latest_excerpt_wins_in_collapsed_window() -> None:
    mgr = DebounceManager(activity_window_seconds=5.0)
    _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="first", monotonic=100.0, observed_at="t1")
    _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="second", monotonic=101.0, observed_at="t2")
    _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="third", monotonic=102.0, observed_at="t3")
    emitted = _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="next", monotonic=110.0, observed_at="t99")
    assert emitted[0].excerpt == "third"


def test_flush_expired_closes_idle_window() -> None:
    """A window can also close on a per-cycle ``flush_expired`` call
    (no new record arrived after the budget)."""
    mgr = DebounceManager(activity_window_seconds=5.0)
    _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="x1", monotonic=100.0, observed_at="t1")
    # Within budget — flush emits nothing.
    assert mgr.flush_expired(monotonic=104.0, observed_at="now") == []
    # Past budget — flush closes the window.
    emitted = mgr.flush_expired(monotonic=106.0, observed_at="now")
    assert len(emitted) == 1
    assert emitted[0].debounce_collapsed_count == 1
    assert emitted[0].excerpt == "x1"
    assert emitted[0].debounce_window_ended_at == "now"


def test_per_attachment_isolation() -> None:
    """Two attachments' activity windows are independent — different
    keys, different ``window_id``s, different ``collapsed_count``s.
    """
    mgr = DebounceManager(activity_window_seconds=5.0)
    _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="A1", monotonic=100.0, observed_at="ta1")
    _submit(mgr, "atc_bbbbbbbbbbbb", excerpt="B1", monotonic=102.0, observed_at="tb1")
    _submit(mgr, "atc_aaaaaaaaaaaa", excerpt="A2", monotonic=103.0, observed_at="ta2")
    # Flush past A's budget but BEFORE B's: only A's window closes.
    # A started at 100, budget 5s → expires at 105. B started at 102 →
    # expires at 107. Flushing at 106 is past A but before B.
    emitted = mgr.flush_expired(monotonic=106.0, observed_at="now")
    assert len(emitted) == 1
    assert emitted[0].excerpt == "A2"
    assert emitted[0].debounce_collapsed_count == 2

    # Now flush past B's budget: B's window closes too.
    emitted2 = mgr.flush_expired(monotonic=110.0, observed_at="now")
    assert len(emitted2) == 1
    assert emitted2[0].excerpt == "B1"
    assert emitted2[0].debounce_collapsed_count == 1


def test_window_id_is_unique_per_window() -> None:
    mgr = DebounceManager(activity_window_seconds=5.0)
    _submit(mgr, "atc_a", excerpt="a1", monotonic=100.0, observed_at="t1")
    e1 = _submit(mgr, "atc_a", excerpt="a2", monotonic=110.0, observed_at="t2")[0]
    # Open a new window after the close.
    e2 = _submit(mgr, "atc_a", excerpt="a3", monotonic=130.0, observed_at="t3")[0]
    assert e1.debounce_window_id != e2.debounce_window_id
