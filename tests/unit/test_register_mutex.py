"""Unit tests for FEAT-006 mutex registries (T017 / FR-038 / FR-039).

Covers:
* Same-key acquisitions serialize.
* Different-key acquisitions parallelize.
* :class:`RegisterLockMap` and :class:`AgentLockMap` are independent.
* Fetch-or-create returns the SAME ``threading.Lock`` object on repeat calls.
* Map entries are not evicted (memory-growth contract).
"""

from __future__ import annotations

import threading
import time

from agenttower.agents.mutex import AgentLockMap, RegisterLockMap


_PANE_KEY_A = ("c1", "/tmp/tmux-1000/default", "main", 0, 0, "%0")
_PANE_KEY_B = ("c2", "/tmp/tmux-1000/default", "main", 0, 0, "%0")


def test_register_lock_map_returns_same_lock_for_same_key() -> None:
    m = RegisterLockMap()
    lock_a = m.for_key(_PANE_KEY_A)
    lock_b = m.for_key(_PANE_KEY_A)
    assert lock_a is lock_b


def test_register_lock_map_returns_different_locks_for_different_keys() -> None:
    m = RegisterLockMap()
    a = m.for_key(_PANE_KEY_A)
    b = m.for_key(_PANE_KEY_B)
    assert a is not b


def test_agent_lock_map_returns_same_lock_for_same_agent_id() -> None:
    m = AgentLockMap()
    a = m.for_key("agt_aaaaaaaaaaaa")
    b = m.for_key("agt_aaaaaaaaaaaa")
    assert a is b


def test_agent_and_register_maps_are_independent() -> None:
    """A pane composite key MUST NOT collide with an agent_id even if they
    share string content (they are distinct registries)."""
    register = RegisterLockMap()
    agent = AgentLockMap()
    # Two registries — entirely independent; they share no state.
    register.for_key(_PANE_KEY_A)
    agent.for_key("agt_aaaaaaaaaaaa")
    assert register.known_keys() == [_PANE_KEY_A]
    assert agent.known_keys() == ["agt_aaaaaaaaaaaa"]


def test_same_key_serializes_concurrent_callers() -> None:
    """Two threads calling ``with lock`` against the same key MUST NOT
    overlap. Asserts via a side-effect counter that both critical sections
    ran serially."""
    m = RegisterLockMap()
    inside = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        with m.for_key(_PANE_KEY_A):
            inside.append("enter")
            time.sleep(0.05)
            inside.append("exit")

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    # Each worker emits enter→exit; serial → ['enter','exit','enter','exit'].
    assert inside == ["enter", "exit", "enter", "exit"]


def test_different_keys_parallelize() -> None:
    """Two threads against different keys MUST proceed in parallel.

    Asserts by overlapping the inner ``time.sleep`` windows; if they were
    serialized, the second thread couldn't observe the first inside its
    critical section.
    """
    m = RegisterLockMap()
    overlap = threading.Event()
    arrived = threading.Event()
    sleep_done = threading.Event()

    def first() -> None:
        with m.for_key(_PANE_KEY_A):
            arrived.set()
            # Wait until the second thread confirms it has entered its own
            # critical section concurrently.
            assert overlap.wait(timeout=2.0)
            sleep_done.set()

    def second() -> None:
        assert arrived.wait(timeout=2.0)
        with m.for_key(_PANE_KEY_B):
            overlap.set()
            assert sleep_done.wait(timeout=2.0)

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join(timeout=3.0)
    t2.join(timeout=3.0)
    assert not t1.is_alive() and not t2.is_alive(), "deadlock between distinct keys"


def test_known_keys_grows_without_eviction() -> None:
    m = RegisterLockMap()
    keys = [
        ("c1", "/tmp/tmux-1000/default", "main", 0, i, "%0") for i in range(20)
    ]
    for k in keys:
        m.for_key(k)
    # FR-038: no LRU at MVP scale; entries persist for the daemon process
    # lifetime.
    assert set(m.known_keys()) == set(keys)
