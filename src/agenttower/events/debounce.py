"""FEAT-008 debounce manager (FR-014 / FR-015).

Per-attachment, per-event-class debounce. Only ``activity`` is
collapse-eligible; the other nine types pass through one-to-one. State
is purely in-memory and does NOT span daemon restarts (FR-015) — a
fresh manager starts with an empty window dict.

Public surface:

* :class:`PendingEvent` — emit-ready record produced by the manager.
* :class:`DebounceWindow` — per-(attachment, class) collapse state.
* :class:`DebounceManager` — submit() and flush() entry points.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import DEBOUNCE_ACTIVITY_WINDOW_SECONDS
from .classifier import ClassifierOutcome


# The single collapse-eligible event class (FR-014).
_COLLAPSE_ELIGIBLE: frozenset[str] = frozenset({"activity"})


@dataclass(frozen=True)
class PendingEvent:
    """One ready-to-emit event from the debounce manager.

    Carries everything the reader needs to construct an
    :class:`agenttower.events.dao.EventRow` and persist it. Position
    fields (``byte_range_*``, ``line_offset_*``) come from the
    underlying record(s) — for collapsed activity windows, they
    span from the FIRST record's start to the LATEST record's end.
    """

    event_type: str
    rule_id: str
    excerpt: str
    observed_at: str
    byte_range_start: int
    byte_range_end: int
    line_offset_start: int
    line_offset_end: int
    debounce_window_id: Optional[str]
    debounce_collapsed_count: int
    debounce_window_started_at: Optional[str]
    debounce_window_ended_at: Optional[str]


@dataclass
class DebounceWindow:
    """In-memory state for one (attachment, event_class) window.

    Only used for ``activity``-class records. Every other class's
    submit() emits immediately and never opens a window.
    """

    window_id: str
    started_at: str
    started_at_monotonic: float
    first_byte_range_start: int
    first_line_offset_start: int
    collapsed_count: int = 0
    latest_excerpt: str = ""
    latest_rule_id: str = ""
    latest_observed_at: str = ""
    latest_byte_range_end: int = 0
    latest_line_offset_end: int = 0


def _new_window_id() -> str:
    """Opaque 12-hex window identifier (per data-model.md §5)."""
    return secrets.token_hex(6)


class DebounceManager:
    """Per-attachment, per-class debounce.

    The reader calls :meth:`submit` for every classified record. The
    return value is a list of :class:`PendingEvent` ready to commit
    (zero, one, or — when an open window closes — two events). The
    reader also calls :meth:`flush_expired` once per cycle visit to
    close any window whose wall-clock budget elapsed without a new
    record.

    State is per-process; restart resets it (FR-015).
    """

    def __init__(
        self,
        *,
        activity_window_seconds: float = DEBOUNCE_ACTIVITY_WINDOW_SECONDS,
    ) -> None:
        self._window_seconds = float(activity_window_seconds)
        # key = (attachment_id, event_class)
        self._windows: dict[tuple[str, str], DebounceWindow] = {}

    def submit(
        self,
        *,
        attachment_id: str,
        outcome: ClassifierOutcome,
        observed_at: str,
        monotonic: float,
        byte_range_start: int,
        byte_range_end: int,
        line_offset_start: int,
        line_offset_end: int,
    ) -> list[PendingEvent]:
        """Submit one classified record; return any events ready to emit.

        For non-collapse classes (FR-014: 9 of 10 types), this emits
        exactly one event with ``collapsed_count=1`` and no window
        metadata. For ``activity`` it either:

        * opens a new window and returns an empty list, OR
        * the prior window is still open: increment its collapsed
          count, replace ``latest_*`` fields, return empty, OR
        * the prior window's wall-clock budget elapsed: close it
          (one emitted event), open a new window seeded with this
          record (no second emission yet), and return the closed
          window's event.
        """
        if outcome.event_type not in _COLLAPSE_ELIGIBLE:
            # One-to-one classes (FR-014).
            return [
                PendingEvent(
                    event_type=outcome.event_type,
                    rule_id=outcome.rule_id,
                    excerpt=outcome.excerpt,
                    observed_at=observed_at,
                    byte_range_start=byte_range_start,
                    byte_range_end=byte_range_end,
                    line_offset_start=line_offset_start,
                    line_offset_end=line_offset_end,
                    debounce_window_id=None,
                    debounce_collapsed_count=1,
                    debounce_window_started_at=None,
                    debounce_window_ended_at=None,
                )
            ]

        # Collapse-eligible (``activity``).
        key = (attachment_id, outcome.event_type)
        window = self._windows.get(key)
        emitted: list[PendingEvent] = []

        if window is not None:
            elapsed = monotonic - window.started_at_monotonic
            if elapsed >= self._window_seconds:
                # Close the prior window before opening a new one.
                emitted.append(self._close_window(key, window, observed_at))

        if window is None or emitted:
            # Open a new window seeded with this record.
            self._windows[key] = DebounceWindow(
                window_id=_new_window_id(),
                started_at=observed_at,
                started_at_monotonic=monotonic,
                first_byte_range_start=byte_range_start,
                first_line_offset_start=line_offset_start,
                collapsed_count=1,
                latest_excerpt=outcome.excerpt,
                latest_rule_id=outcome.rule_id,
                latest_observed_at=observed_at,
                latest_byte_range_end=byte_range_end,
                latest_line_offset_end=line_offset_end,
            )
            return emitted

        # Within the existing window: collapse this record into it.
        window.collapsed_count += 1
        window.latest_excerpt = outcome.excerpt
        window.latest_rule_id = outcome.rule_id
        window.latest_observed_at = observed_at
        window.latest_byte_range_end = byte_range_end
        window.latest_line_offset_end = line_offset_end
        return emitted

    def flush_expired(
        self, *, monotonic: float, observed_at: str
    ) -> list[PendingEvent]:
        """Close any window whose budget has elapsed.

        Called by the reader once per per-attachment cycle visit
        (Plan §R5). Returns the events emitted for closed windows
        (zero or one per attachment under MVP scale).
        """
        emitted: list[PendingEvent] = []
        for key in list(self._windows.keys()):
            window = self._windows[key]
            if monotonic - window.started_at_monotonic >= self._window_seconds:
                emitted.append(self._close_window(key, window, observed_at))
        return emitted

    def reset(self) -> None:
        """Drop every open window. Used by tests and on daemon restart
        (FR-015 — though restart simply discards the manager process-
        wide; this method is for in-process resets like
        ``conftest.py`` autouse fixtures)."""
        self._windows.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _close_window(
        self,
        key: tuple[str, str],
        window: DebounceWindow,
        ended_at: str,
    ) -> PendingEvent:
        """Build the emit record for a closed window and remove it
        from the dict."""
        event_type = key[1]
        emitted = PendingEvent(
            event_type=event_type,
            rule_id=window.latest_rule_id,
            excerpt=window.latest_excerpt,
            observed_at=window.latest_observed_at,
            byte_range_start=window.first_byte_range_start,
            byte_range_end=window.latest_byte_range_end,
            line_offset_start=window.first_line_offset_start,
            line_offset_end=window.latest_line_offset_end,
            debounce_window_id=window.window_id,
            debounce_collapsed_count=window.collapsed_count,
            debounce_window_started_at=window.started_at,
            debounce_window_ended_at=ended_at,
        )
        del self._windows[key]
        return emitted


__all__ = ["DebounceManager", "DebounceWindow", "PendingEvent"]
