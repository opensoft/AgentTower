"""FEAT-013 review P2: managed lifecycle event emitter retry buffer.

``make_managed_event_emitter`` must not drop a lifecycle event permanently
on a transient events-file failure. It buffers the failed write and retries
the backlog on the next emit (drain-on-emit), exposing a ``degraded`` signal
while events are undrained.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agenttower.managed_sessions import events as events_mod
from agenttower.managed_sessions.events import (
    _ManagedEventEmitter,
    make_managed_event_emitter,
    managed_event_pending_count,
    managed_event_persistence_degraded,
)


def _envelope(n: int) -> dict[str, object]:
    return {"event_type": "managed_pane_state_changed", "seq": n}


def test_transient_failure_buffers_then_drains_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed append is buffered (degraded), then the backlog flushes in
    FIFO order on the next successful emit."""
    events_file = tmp_path / "events.jsonl"
    written: list[dict[str, Any]] = []
    fail = {"on": True}

    def fake_append(_path: Path, payload: dict[str, Any]) -> None:
        if fail["on"]:
            raise OSError("disk full (injected)")
        written.append(payload)

    monkeypatch.setattr("agenttower.events.writer.append_event", fake_append)

    emitter = _ManagedEventEmitter(events_file)

    # First two emits fail → buffered, degraded.
    emitter(_envelope(1))
    emitter(_envelope(2))
    assert emitter.degraded is True
    assert emitter.pending_count == 2
    assert emitter.last_failure_exc_class == "OSError"
    assert written == []

    # Disk recovers; next emit drains the whole backlog FIFO + the new one.
    fail["on"] = False
    emitter(_envelope(3))
    assert emitter.degraded is False
    assert emitter.pending_count == 0
    assert emitter.last_failure_exc_class is None
    assert [w["seq"] for w in written] == [1, 2, 3]


def test_overflow_counts_dropped_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A persistent failure past the buffer cap evicts oldest events and
    counts them as hard drops, staying degraded."""
    monkeypatch.setattr(
        "agenttower.events.writer.append_event",
        lambda _p, _e: (_ for _ in ()).throw(OSError("down")),
    )
    emitter = _ManagedEventEmitter(tmp_path / "events.jsonl", max_pending=2)

    for i in range(5):
        emitter(_envelope(i))

    assert emitter.pending_count == 2  # capped
    assert emitter.dropped_count == 3  # 5 emitted - 2 retained
    assert emitter.degraded is True


def test_emitter_is_shared_per_path_and_accessors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two factory calls for the same events file share one emitter, so the
    degraded signal is visible through the module-level accessors."""
    events_file = tmp_path / "events.jsonl"
    monkeypatch.setattr(
        "agenttower.events.writer.append_event",
        lambda _p, _e: (_ for _ in ()).throw(OSError("down")),
    )
    # Clear any cached instance from a prior test reusing the registry.
    events_mod._EMITTERS.pop(str(events_file), None)

    a = make_managed_event_emitter(events_file)
    b = make_managed_event_emitter(events_file)
    assert a is b

    assert managed_event_persistence_degraded(events_file) is False
    a(_envelope(1))  # type: ignore[misc]
    assert managed_event_persistence_degraded(events_file) is True
    assert managed_event_pending_count(events_file) == 1


def test_none_events_file_returns_no_emitter(tmp_path: Path) -> None:
    """No events file → no emitter, and accessors are safe no-ops."""
    assert make_managed_event_emitter(None) is None
    assert managed_event_persistence_degraded(None) is False
    assert managed_event_pending_count(None) == 0
