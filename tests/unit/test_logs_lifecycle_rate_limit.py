"""SC-014 / T174 — lifecycle event rate limiting (FR-061).

Asserts the FR-061 / FR-046 suppression contracts under flap load:

* ``log_file_missing`` — at most one per ``(agent_id, log_path)`` per
  stale-state entry. The next emission requires the row to first
  transition out of ``stale``.
* ``log_file_returned`` — at most one per ``(agent_id, log_path,
  file_inode)`` triple.
* ``log_rotation_detected`` — at most one per actual rotation
  (``(prior_inode, new_inode)`` tuple).

Restart-durability: the suppression registry lives in process memory only
(data-model.md §3.6). After a daemon restart, a previously-suppressed
event MAY re-fire once for the same triple. This is acceptable because
lifecycle events are observability signals (FR-046), not audit rows.
We simulate restart by calling ``logs_lifecycle.reset_for_test()`` —
the registry implementation backs the same singleton the daemon would
re-create on startup.
"""

from __future__ import annotations

from typing import Any

import pytest

from agenttower.logs import lifecycle as logs_lifecycle


AGENT_A = "agt_aaaaaa111111"
AGENT_B = "agt_bbbbbb222222"
PATH_X = "/host/log/x.log"
PATH_Y = "/host/log/y.log"


class _RecordingLogger:
    """Drop-in for the lifecycle logger; records every event arrival."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event: str, *, level: str = "info", **fields: Any) -> None:
        self.events.append((event, fields))


@pytest.fixture
def logger() -> _RecordingLogger:
    """Fresh logger per test; conftest resets the suppression registry."""
    return _RecordingLogger()


def _emit_missing(logger, *, agent_id: str = AGENT_A, log_path: str = PATH_X,
                  inode: str | None = "234:11", size: int = 4096) -> bool:
    return logs_lifecycle.emit_log_file_missing(
        logger,
        agent_id=agent_id,
        log_path=log_path,
        last_known_inode=inode,
        last_known_size=size,
    )


def _emit_returned(logger, *, agent_id: str = AGENT_A, log_path: str = PATH_X,
                   prior_inode: str | None = "234:11",
                   new_inode: str = "234:22", new_size: int = 1024) -> bool:
    return logs_lifecycle.emit_log_file_returned(
        logger,
        agent_id=agent_id,
        log_path=log_path,
        prior_inode=prior_inode,
        new_inode=new_inode,
        new_size=new_size,
    )


def _emit_rotation(logger, *, agent_id: str = AGENT_A, log_path: str = PATH_X,
                   prior_inode: str | None = "234:11",
                   new_inode: str | None = "234:22",
                   prior_size: int = 8192, new_size: int = 0) -> bool:
    return logs_lifecycle.emit_log_rotation_detected(
        logger,
        agent_id=agent_id,
        log_path=log_path,
        prior_inode=prior_inode,
        new_inode=new_inode,
        prior_size=prior_size,
        new_size=new_size,
    )


# ---------------------------------------------------------------------------
# log_file_missing — at most one per (agent_id, log_path) per stale-entry
# ---------------------------------------------------------------------------


def test_missing_emits_once_then_suppressed_until_reset(logger) -> None:
    """First emit succeeds; subsequent emits suppressed until reset."""
    assert _emit_missing(logger) is True
    for _ in range(99):
        assert _emit_missing(logger) is False
    # Exactly one event recorded.
    assert sum(1 for e, _ in logger.events if e == "log_file_missing") == 1

    # Resetting the per-(agent, path) entry (simulates row leaving stale)
    # allows one fresh emit, but only one.
    logs_lifecycle.reset_suppression_for_path(AGENT_A, PATH_X)
    assert _emit_missing(logger) is True
    assert _emit_missing(logger) is False
    assert sum(1 for e, _ in logger.events if e == "log_file_missing") == 2


def test_missing_separate_keys_independent(logger) -> None:
    """Suppression is keyed on (agent_id, log_path) — independent keys
    each get one emit."""
    assert _emit_missing(logger, agent_id=AGENT_A, log_path=PATH_X) is True
    assert _emit_missing(logger, agent_id=AGENT_A, log_path=PATH_Y) is True
    assert _emit_missing(logger, agent_id=AGENT_B, log_path=PATH_X) is True
    # All three independent — three events.
    assert sum(1 for e, _ in logger.events if e == "log_file_missing") == 3
    # But repeats on any of the three are still suppressed.
    assert _emit_missing(logger, agent_id=AGENT_A, log_path=PATH_X) is False


# ---------------------------------------------------------------------------
# log_file_returned — at most one per (agent_id, log_path, file_inode) triple
# ---------------------------------------------------------------------------


def test_returned_emits_once_per_triple(logger) -> None:
    assert _emit_returned(logger, new_inode="234:99") is True
    for _ in range(99):
        assert _emit_returned(logger, new_inode="234:99") is False
    assert sum(1 for e, _ in logger.events if e == "log_file_returned") == 1


def test_returned_different_inode_emits_again(logger) -> None:
    """A new inode for the same (agent, path) is a new triple — emit fires."""
    assert _emit_returned(logger, new_inode="234:99") is True
    assert _emit_returned(logger, new_inode="234:100") is True  # different inode
    assert _emit_returned(logger, new_inode="234:99") is False  # back to first
    assert sum(1 for e, _ in logger.events if e == "log_file_returned") == 2


# ---------------------------------------------------------------------------
# log_rotation_detected — at most one per (prior_inode, new_inode) per (agent, path)
# ---------------------------------------------------------------------------


def test_rotation_emits_once_per_inode_pair(logger) -> None:
    assert _emit_rotation(logger, prior_inode="234:11", new_inode="234:22") is True
    for _ in range(99):
        assert _emit_rotation(logger, prior_inode="234:11", new_inode="234:22") is False
    assert sum(1 for e, _ in logger.events if e == "log_rotation_detected") == 1


def test_rotation_different_inode_pair_emits_again(logger) -> None:
    """Each distinct rotation event (different prior/new inode pair) emits."""
    assert _emit_rotation(logger, prior_inode="234:11", new_inode="234:22") is True
    assert _emit_rotation(logger, prior_inode="234:22", new_inode="234:33") is True
    assert sum(1 for e, _ in logger.events if e == "log_rotation_detected") == 2


# ---------------------------------------------------------------------------
# SC-014 — 100x flap composite
# ---------------------------------------------------------------------------


def test_sc014_flap_100_iterations_bounds_each_event_class(logger) -> None:
    """SC-014 — flap host file delete/recreate 100 times.

    For one (agent, path), simulate the reader observing:
        cycle i: file missing → would-emit log_file_missing
        cycle i+1: file present at new inode_i → would-emit log_file_returned
        cycle i+2: rotation observed (prior=inode_i-1, new=inode_i)
                                     → would-emit log_rotation_detected

    The FR-061 invariants under sustained flap:
    * At most ONE log_file_missing while the row sits in the same stale
      entry (we never reset suppression here, so exactly one for the
      whole run).
    * One log_file_returned PER UNIQUE inode triple — 100 unique inodes
      → up to 100 events. (This is the spec-allowed ceiling; not a
      regression.)
    * One log_rotation_detected PER UNIQUE (prior, new) pair — same
      ceiling.

    We use unique inodes per cycle to exercise the upper bound.
    """
    inodes = [f"234:{i:04d}" for i in range(100)]
    for i, inode in enumerate(inodes):
        _emit_missing(logger)  # always same (agent, path) — suppressed after first
        _emit_returned(logger, new_inode=inode)
        if i > 0:
            _emit_rotation(logger, prior_inode=inodes[i - 1], new_inode=inode)

    by_kind: dict[str, int] = {}
    for event_name, _ in logger.events:
        by_kind[event_name] = by_kind.get(event_name, 0) + 1

    assert by_kind.get("log_file_missing") == 1, (
        "FR-061: log_file_missing MUST fire at most once per stale entry; "
        f"got {by_kind.get('log_file_missing')!r}"
    )
    assert by_kind.get("log_file_returned") == 100, (
        f"100 unique inodes → 100 returned events allowed; got {by_kind.get('log_file_returned')!r}"
    )
    assert by_kind.get("log_rotation_detected") == 99, (
        f"99 unique inode pairs (i, i+1) → 99 rotation events; "
        f"got {by_kind.get('log_rotation_detected')!r}"
    )


def test_sc014_flap_with_repeated_inode_collapses(logger) -> None:
    """Tighter SC-014 case: the 100 cycles all observe the SAME single
    inode after recreate. Suppression should collapse:

    * 1 log_file_missing (first cycle only — row sits in stale)
    * 1 log_file_returned (same triple → suppressed after first)
    * 1 log_rotation_detected (same prior/new inode pair → suppressed)
    """
    for _ in range(100):
        _emit_missing(logger)
        _emit_returned(logger, new_inode="234:single")
        _emit_rotation(logger, prior_inode="234:11", new_inode="234:single")

    by_kind: dict[str, int] = {}
    for event_name, _ in logger.events:
        by_kind[event_name] = by_kind.get(event_name, 0) + 1

    assert by_kind.get("log_file_missing") == 1
    assert by_kind.get("log_file_returned") == 1
    assert by_kind.get("log_rotation_detected") == 1


# ---------------------------------------------------------------------------
# Restart durability (data-model.md §3.6)
# ---------------------------------------------------------------------------


def test_restart_durability_returned_re_fires_once_per_triple(logger) -> None:
    """data-model.md §3.6 — the suppression registry is in-memory only.

    A previously-suppressed log_file_returned MAY re-fire once for the
    same triple after a daemon restart. We simulate restart with
    ``logs_lifecycle.reset_for_test()`` — the production daemon would
    re-construct the singleton on startup with empty maps.

    This is acceptable because lifecycle events are observability
    signals (FR-046), not audit rows.
    """
    # Pre-restart: emit triple T once (success), once (suppressed).
    assert _emit_returned(logger, new_inode="234:99") is True
    assert _emit_returned(logger, new_inode="234:99") is False
    assert sum(1 for e, _ in logger.events if e == "log_file_returned") == 1

    # Simulate daemon restart.
    logs_lifecycle.reset_for_test()

    # Post-restart: the same triple may re-fire ONCE (the suppression
    # state was in-memory only).
    assert _emit_returned(logger, new_inode="234:99") is True
    assert _emit_returned(logger, new_inode="234:99") is False
    assert sum(1 for e, _ in logger.events if e == "log_file_returned") == 2


def test_restart_durability_missing_can_re_fire_after_reset(logger) -> None:
    """Same restart-durability rule applies to log_file_missing."""
    assert _emit_missing(logger) is True
    assert _emit_missing(logger) is False
    logs_lifecycle.reset_for_test()
    # Post-restart: one fresh emit allowed for the same (agent, path).
    assert _emit_missing(logger) is True
    assert _emit_missing(logger) is False
    assert sum(1 for e, _ in logger.events if e == "log_file_missing") == 2


def test_restart_durability_rotation_can_re_fire_after_reset(logger) -> None:
    """Same restart-durability rule applies to log_rotation_detected."""
    assert _emit_rotation(logger) is True
    assert _emit_rotation(logger) is False
    logs_lifecycle.reset_for_test()
    assert _emit_rotation(logger) is True
    assert sum(1 for e, _ in logger.events if e == "log_rotation_detected") == 2
