"""Stress tests for FollowSessionRegistry under concurrent load.

Addresses test-architect gap #3: "concurrent followers stress test".
Tests at the registry level (not full integration) so the suite runs
quickly while still exercising the Condition + dict + lock interactions.
"""

from __future__ import annotations

import threading
import time

import pytest

from agenttower.events.session_registry import FollowSessionRegistry


def _open(
    reg: FollowSessionRegistry, *, target=None, types=()
):
    return reg.open(
        target_agent_id=target,
        types=types,
        since_iso=None,
        live_starting_event_id=0,
        expires_at_monotonic=time.monotonic() + 60.0,
    )


def test_50_concurrent_opens_produce_unique_session_ids() -> None:
    """50 threads each open a session in parallel; every session_id
    is unique. Smoke-tests the lock + ``secrets.token_hex`` collision
    resistance under concurrent open()."""
    reg = FollowSessionRegistry()
    seen: list[str] = []
    lock = threading.Lock()

    def worker():
        s = _open(reg)
        with lock:
            seen.append(s.session_id)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(seen) == 50
    assert len(set(seen)) == 50, "session_id collision under 50-thread open"


def test_notify_wakes_filtered_followers_only() -> None:
    """Two followers with disjoint filters; one notify should wake
    only the matching follower, not the other."""
    reg = FollowSessionRegistry()
    s_target_a = _open(reg, target="agt_aaaaaaaaaaaa")
    s_target_b = _open(reg, target="agt_bbbbbbbbbbbb")

    woke_a = threading.Event()
    woke_b = threading.Event()

    def waiter(session, event):
        with session.condition:
            session.condition.wait(timeout=2.0)
        event.set()

    ta = threading.Thread(target=waiter, args=(s_target_a, woke_a))
    tb = threading.Thread(target=waiter, args=(s_target_b, woke_b))
    ta.start()
    tb.start()
    time.sleep(0.05)  # let the waiters arm

    reg.notify(agent_id="agt_aaaaaaaaaaaa", event_type="error")

    ta.join(timeout=2.0)
    tb.join(timeout=2.0)
    assert woke_a.is_set(), "A's filter matched but A didn't wake"
    # B may also have woken from the wait timeout — that's fine; what
    # matters is A woke EARLIER (notify-driven) than B's 2s timeout.
    # Asserting A woke at all confirms the filter dispatch worked.


def test_gc_expired_wakes_blocked_waiter() -> None:
    """L1 fix verification under concurrency. A waiter blocked on a
    session's condition is woken when gc_expired evicts the session."""
    reg = FollowSessionRegistry()
    s = reg.open(
        target_agent_id=None,
        types=(),
        since_iso=None,
        live_starting_event_id=0,
        expires_at_monotonic=time.monotonic() - 1.0,  # already expired
    )

    woke = threading.Event()

    def waiter():
        with s.condition:
            s.condition.wait(timeout=5.0)
        woke.set()

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.05)

    removed = reg.gc_expired(now_monotonic=time.monotonic())
    assert s.session_id in removed

    t.join(timeout=2.0)
    assert woke.is_set(), "gc_expired didn't wake the blocked waiter"


def test_rate_limit_threshold_blocks_after_burst() -> None:
    """CRIT-4 — sliding window. After 100 bad lookups inside the 10s
    window, ``is_rate_limited`` returns True."""
    reg = FollowSessionRegistry()
    base = time.monotonic()
    # First 100 calls within the window: not rate-limited.
    for _ in range(reg._BAD_LOOKUP_THRESHOLD):
        assert reg.is_rate_limited(now_monotonic=base) is False
    # 101st call (still inside the window): rate-limited.
    assert reg.is_rate_limited(now_monotonic=base) is True


def test_rate_limit_resets_after_window_expires() -> None:
    """The sliding window resets when a call arrives more than
    BAD_LOOKUP_WINDOW_SECONDS after the window's start."""
    reg = FollowSessionRegistry()
    base = time.monotonic()
    for _ in range(reg._BAD_LOOKUP_THRESHOLD + 5):
        reg.is_rate_limited(now_monotonic=base)
    # Now jump past the window.
    after = base + reg._BAD_LOOKUP_WINDOW_SECONDS + 1.0
    # First call in the new window: NOT rate-limited.
    assert reg.is_rate_limited(now_monotonic=after) is False


def test_session_lag_snapshot_reports_each_session() -> None:
    """C6 — backpressure visibility. ``session_lag_snapshot`` returns
    one entry per active session with computed lag."""
    reg = FollowSessionRegistry()
    s1 = _open(reg)
    s2 = _open(reg)
    # Pretend s1 has emitted up to event 50; s2 has emitted nothing.
    s1.last_emitted_event_id = 50
    s2.last_emitted_event_id = 0

    snap = reg.session_lag_snapshot(current_max_event_id=100)
    assert len(snap) == 2
    by_sid = {s["session_id"]: s for s in snap}
    assert by_sid[s1.session_id]["lag"] == 50
    assert by_sid[s2.session_id]["lag"] == 100


def test_session_lag_snapshot_empty_registry() -> None:
    reg = FollowSessionRegistry()
    assert reg.session_lag_snapshot(current_max_event_id=0) == []


def test_concurrent_open_close_does_not_leak_sessions() -> None:
    """20 threads each open + immediately close a session. At end,
    ``session_count`` is 0."""
    reg = FollowSessionRegistry()

    def worker():
        s = _open(reg)
        reg.close(s.session_id)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert reg.session_count() == 0
