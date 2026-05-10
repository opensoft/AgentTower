"""T028 — debounce one-to-one (non-collapse) classes pass through.

Per FR-014: the 9 non-``activity`` event types each emit one event
per qualifying record with ``collapsed_count=1`` and
``window_id=None``.
"""

from __future__ import annotations

import pytest

from agenttower.events.classifier import ClassifierOutcome
from agenttower.events.debounce import DebounceManager


_ONE_TO_ONE_TYPES = (
    "waiting_for_input",
    "completed",
    "error",
    "test_failed",
    "test_passed",
    "manual_review_needed",
    "long_running",
    "pane_exited",
    "swarm_member_reported",
)


def _outcome(event_type: str, rule_id: str | None = None, excerpt: str = "x") -> ClassifierOutcome:
    return ClassifierOutcome(
        event_type=event_type,
        rule_id=rule_id or f"{event_type}.test.v1",
        excerpt=excerpt,
        redacted_record=excerpt,
    )


@pytest.mark.parametrize("event_type", _ONE_TO_ONE_TYPES)
def test_one_to_one_class_emits_immediately(event_type: str) -> None:
    mgr = DebounceManager()
    emitted = mgr.submit(
        attachment_id="atc_aaaaaaaaaaaa",
        outcome=_outcome(event_type),
        observed_at="t1",
        monotonic=100.0,
        byte_range_start=0,
        byte_range_end=10,
        line_offset_start=0,
        line_offset_end=1,
    )
    assert len(emitted) == 1
    e = emitted[0]
    assert e.event_type == event_type
    assert e.debounce_collapsed_count == 1
    assert e.debounce_window_id is None
    assert e.debounce_window_started_at is None
    assert e.debounce_window_ended_at is None


@pytest.mark.parametrize("event_type", _ONE_TO_ONE_TYPES)
def test_two_consecutive_one_to_one_records_emit_two_events(event_type: str) -> None:
    """No collapse for non-activity classes — two records → two events."""
    mgr = DebounceManager()
    emitted_total: list = []
    for i in range(2):
        emitted_total.extend(
            mgr.submit(
                attachment_id="atc_a",
                outcome=_outcome(event_type, excerpt=f"x{i}"),
                observed_at=f"t{i}",
                monotonic=100.0 + i,
                byte_range_start=i * 10,
                byte_range_end=(i + 1) * 10,
                line_offset_start=i,
                line_offset_end=i + 1,
            )
        )
    assert len(emitted_total) == 2
    assert all(e.debounce_collapsed_count == 1 for e in emitted_total)
    assert {e.excerpt for e in emitted_total} == {"x0", "x1"}


def test_mixed_activity_and_one_to_one_does_not_cross_classes() -> None:
    """An ``error`` arrival in the middle of an activity window does NOT
    close the activity window; the error emits immediately and the
    activity window keeps collapsing."""
    mgr = DebounceManager(activity_window_seconds=5.0)
    # Open activity window.
    mgr.submit(
        attachment_id="atc_a",
        outcome=ClassifierOutcome(
            event_type="activity", rule_id="activity.fallback.v1",
            excerpt="a1", redacted_record="a1",
        ),
        observed_at="t1",
        monotonic=100.0,
        byte_range_start=0,
        byte_range_end=10,
        line_offset_start=0,
        line_offset_end=1,
    )
    # Error arrives mid-window → emits one error event, doesn't disturb activity.
    error_emit = mgr.submit(
        attachment_id="atc_a",
        outcome=ClassifierOutcome(
            event_type="error", rule_id="error.line.v1",
            excerpt="boom", redacted_record="boom",
        ),
        observed_at="t2",
        monotonic=101.0,
        byte_range_start=10,
        byte_range_end=20,
        line_offset_start=1,
        line_offset_end=2,
    )
    assert len(error_emit) == 1
    assert error_emit[0].event_type == "error"
    # Continue the activity window.
    activity_emit = mgr.submit(
        attachment_id="atc_a",
        outcome=ClassifierOutcome(
            event_type="activity", rule_id="activity.fallback.v1",
            excerpt="a2", redacted_record="a2",
        ),
        observed_at="t3",
        monotonic=102.0,
        byte_range_start=20,
        byte_range_end=30,
        line_offset_start=2,
        line_offset_end=3,
    )
    # Activity window still open; no emit.
    assert activity_emit == []
    # Flush past the budget — the activity window now closes with count=2.
    flushed = mgr.flush_expired(monotonic=110.0, observed_at="t99")
    assert len(flushed) == 1
    assert flushed[0].event_type == "activity"
    assert flushed[0].debounce_collapsed_count == 2
