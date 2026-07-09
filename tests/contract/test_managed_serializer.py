"""FEAT-013 per-container serializer contract test (T020).

Covers FR-019: a second ``create_layout`` request targeting the same
bench container blocks until the first finishes; cross-container calls
proceed in parallel.

The implementation uses ``threading.Lock`` matching the FEAT-009
``agents/mutex.py`` lock-map pattern (post-Phase-2 spec sync;
``serializer.py`` module docstring documents the deviation from
research §R2's original ``asyncio.Lock`` proposal).
"""

from __future__ import annotations

import threading
import time

import pytest

from agenttower.managed_sessions.serializer import ContainerSerializer


def test_returns_same_lock_for_same_container() -> None:
    """Per-container lock is memoized."""
    s = ContainerSerializer()
    lock_a1 = s.for_container("C1")
    lock_a2 = s.for_container("C1")
    assert lock_a1 is lock_a2


def test_returns_distinct_locks_for_distinct_containers() -> None:
    """Cross-container calls get independent locks → parallel execution."""
    s = ContainerSerializer()
    assert s.for_container("C1") is not s.for_container("C2")


def test_rejects_empty_container_id() -> None:
    s = ContainerSerializer()
    with pytest.raises(ValueError):
        s.for_container("")


def test_known_containers_snapshot_grows_with_use() -> None:
    s = ContainerSerializer()
    assert s.known_containers() == []
    s.for_container("C1")
    s.for_container("C2")
    assert sorted(s.known_containers()) == ["C1", "C2"]


def test_same_container_serializes_concurrent_callers() -> None:
    """FR-019 — two threads on the same container_id MUST observe
    serialized execution (the second waits for the first)."""
    s = ContainerSerializer()
    timeline: list[str] = []
    timeline_guard = threading.Lock()

    def worker(name: str, hold_ms: int) -> None:
        lock = s.for_container("C1")
        with lock:
            with timeline_guard:
                timeline.append(f"{name}:start")
            time.sleep(hold_ms / 1000.0)
            with timeline_guard:
                timeline.append(f"{name}:end")

    t1 = threading.Thread(target=worker, args=("A", 80))
    t2 = threading.Thread(target=worker, args=("B", 10))
    t1.start()
    # Give t1 a head start so its lock acquire happens first.
    time.sleep(0.005)
    t2.start()
    t1.join()
    t2.join()

    # Either "A then B" or "B then A" — but never interleaved
    # (no "A:start, B:start, A:end").
    assert timeline in (
        ["A:start", "A:end", "B:start", "B:end"],
        ["B:start", "B:end", "A:start", "A:end"],
    )


def test_distinct_containers_run_in_parallel() -> None:
    """Two threads on different containers should overlap in time."""
    s = ContainerSerializer()
    observed_overlap: list[bool] = []
    barrier = threading.Barrier(2)

    def worker(container: str) -> None:
        with s.for_container(container):
            # Both threads release the barrier together — they only proceed
            # past barrier.wait() once both are inside their (distinct) locks.
            try:
                barrier.wait(timeout=2.0)
                observed_overlap.append(True)
            except threading.BrokenBarrierError:
                observed_overlap.append(False)

    t1 = threading.Thread(target=worker, args=("C1",))
    t2 = threading.Thread(target=worker, args=("C2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert observed_overlap == [True, True]
