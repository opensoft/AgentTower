"""T102 — FR-015: debounce state MUST NOT span daemon restarts.

A fresh :class:`DebounceManager` after restart starts empty; any
in-flight pre-restart ``collapsed_count > 1`` is NOT recoverable.
The first qualifying record post-restart opens a NEW window with
``collapsed_count=1``.
"""

from __future__ import annotations

from agenttower.events.classifier import ClassifierOutcome
from agenttower.events.debounce import DebounceManager


def _outcome(excerpt: str = "x") -> ClassifierOutcome:
    return ClassifierOutcome(
        event_type="activity",
        rule_id="activity.fallback.v1",
        excerpt=excerpt,
        redacted_record=excerpt,
    )


def _submit(mgr: DebounceManager, *, monotonic: float, observed_at: str, excerpt: str = "x") -> list:
    return mgr.submit(
        attachment_id="atc_aaaaaaaaaaaa",
        outcome=_outcome(excerpt=excerpt),
        observed_at=observed_at,
        monotonic=monotonic,
        byte_range_start=0,
        byte_range_end=10,
        line_offset_start=0,
        line_offset_end=1,
    )


def test_fresh_manager_has_empty_window_dict() -> None:
    """A new manager — as constructed at daemon boot — has no
    open windows. This is the FR-015 invariant: nothing carries
    across a daemon restart."""
    mgr = DebounceManager(activity_window_seconds=5.0)
    # Internal-state assertion: no windows at construction.
    assert mgr._windows == {}  # type: ignore[reportPrivateUsage]


def test_first_record_post_restart_opens_new_window_count_one() -> None:
    """Simulate: pre-restart manager had a collapsed window with
    count=3; the daemon restarts, a fresh manager is constructed; the
    first qualifying record opens a NEW window with count=1.
    """
    pre_restart = DebounceManager(activity_window_seconds=5.0)
    for i in range(3):
        _submit(pre_restart, monotonic=100.0 + i, observed_at=f"pre{i}")
    # Pre-restart manager has one open window with collapsed_count=3.
    pre_window = pre_restart._windows[("atc_aaaaaaaaaaaa", "activity")]  # type: ignore[reportPrivateUsage]
    assert pre_window.collapsed_count == 3

    # Daemon "restart" — discard the manager, construct a fresh one.
    post_restart = DebounceManager(activity_window_seconds=5.0)
    assert post_restart._windows == {}  # type: ignore[reportPrivateUsage]

    # First record post-restart → opens new window, no emission.
    emitted = _submit(post_restart, monotonic=200.0, observed_at="post1", excerpt="post1")
    assert emitted == []
    new_window = post_restart._windows[("atc_aaaaaaaaaaaa", "activity")]  # type: ignore[reportPrivateUsage]
    assert new_window.collapsed_count == 1
    # window_id is fresh — not the pre-restart id.
    assert new_window.window_id != pre_window.window_id


def test_post_restart_window_close_emits_count_one_for_single_record() -> None:
    """If only one record arrives post-restart and the window
    eventually closes, the emitted event has collapsed_count=1
    (no pre-restart count carries over)."""
    mgr = DebounceManager(activity_window_seconds=5.0)
    _submit(mgr, monotonic=100.0, observed_at="t1", excerpt="solo")
    flushed = mgr.flush_expired(monotonic=106.0, observed_at="t99")
    assert len(flushed) == 1
    assert flushed[0].debounce_collapsed_count == 1
    assert flushed[0].excerpt == "solo"


def test_reset_clears_all_windows_in_place() -> None:
    """Tests / autouse fixtures that reset between tests use this
    method. Mirrors the daemon-restart semantics — windows go away."""
    mgr = DebounceManager(activity_window_seconds=5.0)
    _submit(mgr, monotonic=100.0, observed_at="t1")
    _submit(mgr, monotonic=101.0, observed_at="t2")
    assert mgr._windows  # type: ignore[reportPrivateUsage]
    mgr.reset()
    assert mgr._windows == {}  # type: ignore[reportPrivateUsage]
