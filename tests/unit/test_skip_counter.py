"""FEAT-014 T010 — Unit tests for the skip-counter ring buffer.

Exercises ``agenttower.routing.skip_counter`` (created by T013).

Maps to:

* FR-008 — process-local 300_000 ms sliding window; daemon restart → 0 count.
* FR-008 extended (Clarifications R1 Q2) — worker-stall decoupling: the
  counter is structurally independent of FEAT-010 routing-worker liveness.
* Research §CW — strict ``>`` window-edge inclusion (event at exactly
  ``now - 300_000`` is NOT counted; monotonic ms clock).
* Research §RB — bounded memory: ``maxlen = 10_000``, drop-oldest on overflow.
* data-model.md §RecentlySkippedRoutesWindow — public constants and API.

Every assertion is ``@pytest.mark.v1_1`` per tasks.md §Notes 'v1.1 marker
rule' (applied uniformly to new FEAT-014 test files for SC-004 regression
deselectability — same convention as ``test_pane_state_buckets.py`` and
``test_agent_state_buckets.py``).

Public API under test (``agenttower.routing.skip_counter`` — see T013):

- class ``SkipCounter`` (private per-test instances for isolation) with:
    - ``__init__() -> None``  — empty buffer + private ``threading.Lock``
    - ``record_skip(now_ms: int) -> None``
    - ``count_in_window(now_ms: int) -> int``
- module-level convenience functions (production callers — routing
  worker and dashboard) delegating to a process-local default instance:
    - ``record_skip(now_ms: int) -> None``
    - ``count_in_window(now_ms: int) -> int``
- module constants:
    - ``WINDOW_MS: int = 300_000``  (Research §CW / data-model.md)
    - ``MAXLEN: int = 10_000``      (Research §RB / data-model.md)
"""

from __future__ import annotations

import pytest

from agenttower.routing.skip_counter import MAXLEN, WINDOW_MS, SkipCounter


# ─── FR-008 daemon-restart → zero count ─────────────────────────────────────


@pytest.mark.v1_1
def test_construction_returns_zero_count() -> None:
    """FR-008: a freshly-constructed counter (modeling daemon restart) returns
    ``0`` for ``count_in_window`` at any time before any ``record_skip``."""
    counter = SkipCounter()
    assert counter.count_in_window(now_ms=0) == 0
    assert counter.count_in_window(now_ms=1_000_000) == 0
    assert counter.count_in_window(now_ms=10**12) == 0


# ─── Module constants (Research §RB / §CW / data-model.md) ──────────────────


@pytest.mark.v1_1
def test_module_constants_match_design() -> None:
    """data-model.md §RecentlySkippedRoutesWindow + Research §RB / §CW: the
    public constants MUST be ``WINDOW_MS == 300_000`` and ``MAXLEN == 10_000``
    exactly (not "5 minutes", not "about 10k")."""
    assert WINDOW_MS == 300_000
    assert MAXLEN == 10_000


# ─── Insertion stores monotonic ms (Research §CW) ───────────────────────────


@pytest.mark.v1_1
def test_record_skip_stores_single_event() -> None:
    """Single ``record_skip`` then ``count_in_window`` at the same ms → 1."""
    counter = SkipCounter()
    counter.record_skip(now_ms=1_000_000)
    assert counter.count_in_window(now_ms=1_000_000) == 1


@pytest.mark.v1_1
def test_record_skip_stores_multiple_events_in_window() -> None:
    """N skip events at distinct ms within the window → ``count_in_window`` == N."""
    counter = SkipCounter()
    for offset in (0, 100, 200, 300, 400):
        counter.record_skip(now_ms=1_000_000 + offset)
    assert counter.count_in_window(now_ms=1_000_400) == 5


# ─── Research §CW — strict ``>`` window-edge check ──────────────────────────


@pytest.mark.v1_1
def test_count_in_window_excludes_event_exactly_at_window_edge() -> None:
    """Research §CW: an event at exactly ``now - WINDOW_MS`` is NOT counted.
    The inclusion test is strict ``entry_ms > now_ms - WINDOW_MS``."""
    counter = SkipCounter()
    counter.record_skip(now_ms=0)
    # now_ms = WINDOW_MS → entry age == WINDOW_MS → strict ``>`` excludes.
    assert counter.count_in_window(now_ms=WINDOW_MS) == 0


@pytest.mark.v1_1
def test_count_in_window_includes_event_one_ms_inside_window() -> None:
    """One ms inside the window IS counted (``entry > now - WINDOW_MS``)."""
    counter = SkipCounter()
    counter.record_skip(now_ms=1)
    # entry=1, now=WINDOW_MS → 1 > WINDOW_MS - WINDOW_MS == 0 → counted.
    assert counter.count_in_window(now_ms=WINDOW_MS) == 1


@pytest.mark.v1_1
def test_count_in_window_excludes_event_one_ms_outside_window() -> None:
    """One ms older than the window edge is NOT counted."""
    counter = SkipCounter()
    counter.record_skip(now_ms=0)
    # now=WINDOW_MS+1, entry=0 → age = WINDOW_MS+1 → outside window.
    assert counter.count_in_window(now_ms=WINDOW_MS + 1) == 0


@pytest.mark.v1_1
def test_count_in_window_filters_mixed_inside_and_outside() -> None:
    """Mixed events: only those whose age is strictly less than WINDOW_MS count."""
    counter = SkipCounter()
    now_ms = 1_000_000
    counter.record_skip(now_ms - WINDOW_MS - 100)  # outside (too old) — not counted
    counter.record_skip(now_ms - WINDOW_MS)        # exactly at edge — not counted
    counter.record_skip(now_ms - WINDOW_MS + 1)    # one ms inside — counted
    counter.record_skip(now_ms - 1)                # just before now — counted
    counter.record_skip(now_ms)                    # at now — counted
    assert counter.count_in_window(now_ms=now_ms) == 3


# ─── Research §RB — drop-oldest on MAXLEN overflow ──────────────────────────


@pytest.mark.v1_1
def test_drop_oldest_on_maxlen_overflow() -> None:
    """Research §RB: when MAXLEN entries are exceeded, the oldest is dropped
    (deque semantics). Memory is bounded at ~80 KB worst case."""
    counter = SkipCounter()
    for i in range(MAXLEN):
        counter.record_skip(now_ms=i)
    # All MAXLEN events fit within (MAXLEN - 1) ms of each other → well inside
    # WINDOW_MS for any reasonable observation time.
    assert counter.count_in_window(now_ms=MAXLEN) == MAXLEN

    # Add one more: the oldest (now_ms=0) gets evicted.
    counter.record_skip(now_ms=MAXLEN)
    assert counter.count_in_window(now_ms=MAXLEN) == MAXLEN  # still capped at MAXLEN


@pytest.mark.v1_1
def test_drop_oldest_under_burst_overflow() -> None:
    """Burst of MAXLEN+1000 sub-window-spaced events → count bounded by MAXLEN
    (drop-oldest, not refuse-to-insert)."""
    counter = SkipCounter()
    for i in range(MAXLEN + 1_000):
        counter.record_skip(now_ms=i)
    # All events span (MAXLEN + 999) ms — well below WINDOW_MS — but the
    # buffer can hold at most MAXLEN entries.
    assert counter.count_in_window(now_ms=MAXLEN + 1_000) == MAXLEN


# ─── FR-008 worker-stall decoupling (Clarifications R1 Q2) ──────────────────


@pytest.mark.v1_1
def test_fr008_worker_stall_decoupling_preserves_window_contents() -> None:
    """Clarifications R1 Q2: the skip counter is structurally decoupled from
    FEAT-010 routing-worker liveness. Stopping ``record_skip`` calls (modeling
    a stalled or crashed routing worker) does NOT cause ``count_in_window`` to
    drop to 0 within the active window — previously-recorded entries are still
    counted.

    The routing-worker degradation is surfaced separately by the recommendation
    engine as ``subsystem_degraded`` for ``routing_worker``, not by the counter
    going silently to zero (which would falsely suggest "no recent skips").
    """
    counter = SkipCounter()
    base_ms = 1_000_000
    # Routing worker emits 7 skip decisions spread across 10s.
    for offset in (0, 1_000, 2_000, 3_000, 5_000, 7_000, 10_000):
        counter.record_skip(now_ms=base_ms + offset)
    populated_count = counter.count_in_window(now_ms=base_ms + 10_000)
    assert populated_count == 7

    # Routing worker stalls — NO further record_skip calls happen.
    # Dashboard observes 60s later: all 7 events are still within WINDOW_MS
    # (oldest age 70_000 ms, youngest age 60_000 ms; both < 300_000).
    stall_observation_ms = base_ms + 10_000 + 60_000
    assert counter.count_in_window(now_ms=stall_observation_ms) == 7


@pytest.mark.v1_1
def test_fr008_worker_stall_lets_events_age_out_via_window_arithmetic() -> None:
    """Complement to the decoupling test: after a stall, events DO eventually
    age out — but via the strict-``>`` window filter, NOT via any
    worker-liveness coupling. This documents that "count goes to 0" is
    consistent with the window math, not with worker death."""
    counter = SkipCounter()
    counter.record_skip(now_ms=0)
    counter.record_skip(now_ms=50_000)

    # Just inside window: both events counted.
    assert counter.count_in_window(now_ms=50_000) == 2

    # now=350_000 → age(0)=350_000 (outside), age(50_000)=300_000 (exactly edge → excluded)
    assert counter.count_in_window(now_ms=350_000) == 0

    # now=349_999 → age(0)=349_999 (outside), age(50_000)=299_999 (inside → counted)
    assert counter.count_in_window(now_ms=349_999) == 1
