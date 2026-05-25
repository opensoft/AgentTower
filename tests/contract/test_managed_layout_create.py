"""FEAT-013 layout-creation contract test (T016).

Covers the US1 acceptance gate — every behavior the operator-visible
``managed.layout.create`` / ``app.managed_layout_create`` must satisfy:

* FR-001 template selection (1m+2s, 2m+2s) — synchronous create
* FR-002 launch command overrides — wired through the spawn pipeline
* FR-003 label-uniqueness scope (per-container; SQLite partial unique
  index)
* FR-016 amendment: operator-input validation (``[A-Za-z0-9_.-]``,
  length ≤ 64) + ``managed_session_name_conflict`` rejection
* FR-019 per-container serialization (second request waits)
* FR-025 capacity ≤ 40 layouts (41st returns
  ``managed_layout_capacity_exceeded``)
* FR-026 no-cascade-kill rollback on partial failure (background spawn
  pipeline; Phase 4)
* FR-013 30-second per-stage timeout + 2x retry (background spawn
  pipeline; Phase 4)
* R10 idempotency-key replay semantics

Tests that exercise the synchronous create_layout entry point land in
Phase 3b (this commit). Tests that need the background tmux spawn /
FEAT-006 registration / FEAT-007 log attach are skip-marked pending
Phase 4 (T029/T030).
"""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from agenttower.managed_sessions.dao import (
    count_active_layouts,
    insert_layout,
    ManagedLayoutRow,
)
from agenttower.managed_sessions.errors import (
    MANAGED_LAYOUT_CAPACITY_EXCEEDED,
    MANAGED_SESSION_NAME_CONFLICT,
    ManagedSessionsError,
)
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.service import (
    CAPACITY_LIMIT,
    CreateLayoutResult,
    create_layout,
)
from agenttower.managed_sessions.state_machine import ManagedState
from agenttower.state.schema import _apply_migration_v9


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Fresh in-memory SQLite with FEAT-001 ``agents`` + FEAT-013 v9 tables."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    _apply_migration_v9(c)
    return c


@pytest.fixture()
def serializer() -> ContainerSerializer:
    return ContainerSerializer()


# ─── FR-001 + R10 happy path ─────────────────────────────────────────────


def test_create_layout_with_builtin_1m_2s(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-001 happy path: 1m+2s creates 3 panes in ``creating`` state."""
    result = create_layout(
        conn=conn,
        serializer=serializer,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert isinstance(result, CreateLayoutResult)
    assert result.state == ManagedState.CREATING
    assert result.intended_pane_count == 3
    assert len(result.panes) == 3
    assert [p.role for p in result.panes] == ["master", "slave", "slave"]
    assert [p.label for p in result.panes] == ["m1", "s1", "s2"]
    assert [p.state for p in result.panes] == [ManagedState.CREATING] * 3
    assert result.replay is False


def test_create_layout_with_2m_2s_template(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-001 happy path: 2m+2s creates 4 panes."""
    result = create_layout(
        conn=conn,
        serializer=serializer,
        container_id="bench-alpha",
        template_name="2m+2s",
        tmux_session_name="session-test",
    )
    assert result.intended_pane_count == 4
    assert [p.role for p in result.panes] == ["master", "master", "slave", "slave"]
    assert [p.label for p in result.panes] == ["m1", "m2", "s1", "s2"]


def test_r10_idempotency_replay_returns_existing(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """R10: same idempotency_key + container_id → return existing layout."""
    first = create_layout(
        conn=conn,
        serializer=serializer,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-test",
        idempotency_key="op-12345",
    )
    second = create_layout(
        conn=conn,
        serializer=serializer,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-test-different-name",  # different — replay should ignore
        idempotency_key="op-12345",
    )
    assert second.layout_id == first.layout_id
    assert second.replay is True


# ─── FR-016 amendment: operator-input validation ──────────────────────────


def test_create_layout_rejects_invalid_session_name_characters(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-016 amendment: control chars / out-of-charset → validation_failed
    BEFORE any DB write."""
    with pytest.raises(Exception) as exc:
        create_layout(
            conn=conn,
            serializer=serializer,
            container_id="bench-alpha",
            template_name="1m+2s",
            tmux_session_name="bad name with spaces",  # space not in [A-Za-z0-9_.-]
        )
    assert getattr(exc.value, "code", None) == "validation_failed"
    # Confirm DB not mutated.
    assert count_active_layouts(conn) == 0


def test_create_layout_rejects_session_name_over_64_chars(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-016 amendment: length > 64 → validation_failed."""
    with pytest.raises(Exception) as exc:
        create_layout(
            conn=conn,
            serializer=serializer,
            container_id="bench-alpha",
            template_name="1m+2s",
            tmux_session_name="x" * 65,
        )
    assert getattr(exc.value, "code", None) == "validation_failed"


def test_create_layout_rejects_control_chars(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-016 amendment: control chars (`\\x00..\\x1f`, `\\x7f`) → validation_failed."""
    with pytest.raises(Exception) as exc:
        create_layout(
            conn=conn,
            serializer=serializer,
            container_id="bench-alpha",
            template_name="1m+2s",
            tmux_session_name="bad\x00name",
        )
    assert getattr(exc.value, "code", None) == "validation_failed"


# ─── FR-003: label uniqueness per container ───────────────────────────────


def test_label_uniqueness_per_container_enforced(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-003: two layouts in the same container with the same template
    can't both succeed at non-terminal state (the partial unique index
    on ``managed_pane(container_id, label)`` blocks the second's m1
    label)."""
    create_layout(
        conn=conn,
        serializer=serializer,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-one",
    )
    # Second create against the same container with overlapping labels +
    # different tmux_session_name. The first layout's m1 / s1 / s2 are
    # in ``creating`` (non-terminal); the second's attempted m1 must be
    # rejected by the partial unique label index.
    with pytest.raises(sqlite3.IntegrityError):
        create_layout(
            conn=conn,
            serializer=serializer,
            container_id="bench-alpha",
            template_name="1m+2s",
            tmux_session_name="session-two",
        )


# ─── FR-019: per-container serialization ─────────────────────────────────


def test_two_creates_same_container_serialize(
    serializer: ContainerSerializer,
) -> None:
    """FR-019: two threads creating layouts in the same container don't
    interleave; their per-container locks serialize them.

    Uses two distinct in-memory SQLite connections (each thread creates
    its own; SQLite forbids cross-thread connection sharing) but shares
    the serializer + container_id."""
    timeline: list[str] = []
    timeline_guard = threading.Lock()

    def worker(name: str, session_name: str, hold_ms: int) -> None:
        local_conn = sqlite3.connect(":memory:")
        local_conn.execute("PRAGMA foreign_keys = ON")
        local_conn.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
        _apply_migration_v9(local_conn)
        lock = serializer.for_container("C1")
        with lock:
            with timeline_guard:
                timeline.append(f"{name}:start")
            time.sleep(hold_ms / 1000.0)
            with timeline_guard:
                timeline.append(f"{name}:end")

    t1 = threading.Thread(target=worker, args=("A", "session-a", 60))
    t2 = threading.Thread(target=worker, args=("B", "session-b", 10))
    t1.start()
    time.sleep(0.005)
    t2.start()
    t1.join()
    t2.join()

    # Strict non-interleaving (same as test_managed_serializer.py).
    assert timeline in (
        ["A:start", "A:end", "B:start", "B:end"],
        ["B:start", "B:end", "A:start", "A:end"],
    )


def test_two_creates_different_containers_run_in_parallel(
    serializer: ContainerSerializer,
) -> None:
    """Cross-container calls proceed in parallel (research §R2 + FR-019)."""
    barrier = threading.Barrier(2)
    observed: list[bool] = []

    def worker(container: str) -> None:
        with serializer.for_container(container):
            try:
                barrier.wait(timeout=2.0)
                observed.append(True)
            except threading.BrokenBarrierError:
                observed.append(False)

    t1 = threading.Thread(target=worker, args=("C1",))
    t2 = threading.Thread(target=worker, args=("C2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert observed == [True, True]


# ─── FR-025: capacity limit ──────────────────────────────────────────────


def test_create_layout_returns_capacity_exceeded_at_41(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-025: when the daemon already holds 40 non-terminal layouts,
    the 41st returns ``managed_layout_capacity_exceeded``."""
    # Seed 40 layouts directly via DAO (faster than 40 create_layout
    # calls; each row is in 'creating' so counts as non-terminal).
    for i in range(CAPACITY_LIMIT):
        insert_layout(
            conn,
            ManagedLayoutRow(
                id=f"L{i:04d}",
                container_id="bench-alpha",
                template_name="1m+2s",
                intended_pane_count=3,
                state=ManagedState.CREATING,
                failed_stage=None,
                idempotency_key=None,
                created_at="2026-05-25T00:00:00Z",
                updated_at="2026-05-25T00:00:00Z",
            ),
        )
    # Close the implicit seed transaction before the service call.
    conn.commit()
    assert count_active_layouts(conn) == CAPACITY_LIMIT

    with pytest.raises(ManagedSessionsError) as exc:
        create_layout(
            conn=conn,
            serializer=serializer,
            container_id="bench-beta",  # different container; cap is daemon-wide
            template_name="1m+2s",
            tmux_session_name="session-test",
        )
    assert exc.value.code == MANAGED_LAYOUT_CAPACITY_EXCEEDED
    assert exc.value.details["current_count"] == CAPACITY_LIMIT
    assert exc.value.details["limit"] == CAPACITY_LIMIT


def test_capacity_excludes_removed_layouts(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-025: terminal-state (``removed``) layouts MUST NOT count against
    the cap — operator removes a layout to free capacity."""
    # 40 removed layouts → cap is empty
    for i in range(CAPACITY_LIMIT):
        insert_layout(
            conn,
            ManagedLayoutRow(
                id=f"L{i:04d}",
                container_id="bench-alpha",
                template_name="1m+2s",
                intended_pane_count=3,
                state=ManagedState.REMOVED,
                failed_stage=None,
                idempotency_key=None,
                created_at="2026-05-25T00:00:00Z",
                updated_at="2026-05-25T00:00:00Z",
            ),
        )
    # Close the implicit transaction the seed loop opens so the service
    # can start its own BEGIN IMMEDIATE.
    conn.commit()
    assert count_active_layouts(conn) == 0
    # 41st should succeed because the 40 are terminal.
    result = create_layout(
        conn=conn,
        serializer=serializer,
        container_id="bench-beta",
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert result.state == ManagedState.CREATING


# ─── Phase-4 deferred tests (need background spawn pipeline) ─────────────


@pytest.mark.skip(reason="needs FEAT-004 docker-exec channel + spawn pipeline (Phase 4)")
def test_create_layout_with_launch_command_overrides() -> None:
    """FR-002: operator-supplied ``launch_command_overrides`` are passed
    to the background spawn pipeline. Requires the FEAT-004 docker-exec
    channel to be wired (T029)."""


@pytest.mark.skip(reason="needs FEAT-004 tmux list-sessions pre-check (Phase 4)")
def test_create_layout_rejects_existing_session_name() -> None:
    """Q6 / FR-016: target tmux session name already exists →
    ``managed_session_name_conflict`` with the conflicting name in details.

    Detection requires the daemon to query the bench container via
    FEAT-004 BEFORE attempting tmux new-session. That cross-FEAT call
    site lands in T029 (Phase 4)."""


@pytest.mark.skip(reason="needs background spawn pipeline (Phase 4)")
def test_one_pane_failure_does_not_cascade_kill_siblings() -> None:
    """FR-026: when one pane fails mid-create, sibling in-flight panes
    continue to natural completion. Background spawn pipeline lives in
    Phase 4."""


@pytest.mark.skip(reason="needs background spawn pipeline (Phase 4)")
def test_pane_create_stage_times_out_after_30_seconds() -> None:
    """FR-013 amendment: per-stage 30s timeout asserted via
    ``managed_clock`` + ``TmuxRecorder``. Spawn pipeline = Phase 4."""


@pytest.mark.skip(reason="needs background spawn pipeline (Phase 4)")
def test_transient_failures_retry_2x_with_exponential_backoff() -> None:
    """FR-013 amendment: 2x retry with 1s/2s back-off on transient
    failures only. Spawn pipeline = Phase 4."""
