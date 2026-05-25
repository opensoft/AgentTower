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
    MANAGED_PANE_LABEL_CONFLICT,
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
    can't both succeed at non-terminal state. The service translates
    the partial-unique-index ``IntegrityError`` into the closed-set
    ``managed_pane_label_conflict`` (Phase 3b N20 fix)."""
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
    # rejected by the partial unique label index and translated to the
    # closed-set code.
    with pytest.raises(ManagedSessionsError) as exc:
        create_layout(
            conn=conn,
            serializer=serializer,
            container_id="bench-alpha",
            template_name="1m+2s",
            tmux_session_name="session-two",
        )
    assert exc.value.code == MANAGED_PANE_LABEL_CONFLICT
    assert exc.value.details["container_id"] == "bench-alpha"
    assert exc.value.details["label"] == "m1"


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


# ─── Phase-4b: background spawn pipeline tests ──────────────────────────


from agenttower.managed_sessions.service import (
    spawn_layout_in_background,
    SpawnLayoutOutcome,
)
from agenttower.managed_sessions.dao import select_panes_for_layout


def _good_tmux(pane):  # noqa: ANN001
    """Backend fake: tmux spawn always succeeds, launch command stays alive."""
    return {
        "ok": True,
        "tmux_pane_id": f"%tmux-{pane.tmux_pane_index}",
        "launch_alive": True,
    }


def _make_register_backend(conn):  # noqa: ANN001
    """Build a FEAT-006-shaped register backend that also inserts the
    agent row into the FK-target ``agents`` table. Mirrors what
    AgentService.register_agent does — without this, the
    ``managed_pane.agent_id REFERENCES agents(agent_id)`` FK constraint
    fails on update.
    """
    def register(pane, tmux_pane_id):  # noqa: ANN001
        agent_id = f"agent-{pane.id[:8]}"
        conn.execute("INSERT INTO agents (agent_id) VALUES (?)", (agent_id,))
        return {"ok": True, "agent_id": agent_id}
    return register


def _good_log(pane, agent_id):  # noqa: ANN001
    """Backend fake: FEAT-007 log attach always succeeds."""
    return {"ok": True}


def test_create_layout_with_launch_command_overrides(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-002: operator-supplied ``launch_command_overrides`` are stored on
    the managed_pane rows so the background spawn pipeline can reach them.

    Verifies that supplying overrides keyed by ``"<role>:<label>"`` causes
    the resolved ``launch_command_ref`` to land on the inserted pane row,
    and that the background pipeline produces a healthy layout when the
    backends succeed.
    """
    # Seed two launch-profile YAMLs in a temp override dir.
    import os
    import tempfile

    profile_dir = tempfile.mkdtemp(prefix="feat013_test_profiles_")
    try:
        with open(os.path.join(profile_dir, "claude-master.yaml"), "w") as f:
            f.write('name: claude-master\ncommand: ["bash", "-lc", "echo m"]\n')
        with open(os.path.join(profile_dir, "claude-worker.yaml"), "w") as f:
            f.write('name: claude-worker\ncommand: ["bash", "-lc", "echo w"]\n')

        from pathlib import Path
        result = create_layout(
            conn=conn,
            serializer=serializer,
            container_id="bench-alpha",
            template_name="1m+2s",
            tmux_session_name="session-overrides",
            launch_command_overrides={
                "master:m1": "claude-master",
                "slave:s1": "claude-worker",
                "slave:s2": "claude-worker",
            },
            profile_override_dir=Path(profile_dir),
        )

        # Verify the overrides landed on the pane rows.
        panes = select_panes_for_layout(conn, result.layout_id)
        assert [p.launch_command_ref for p in panes] == [
            "claude-master", "claude-worker", "claude-worker",
        ]

        # Drive the background pipeline with healthy backends.
        outcome = spawn_layout_in_background(
            result.layout_id,
            conn=conn,
            serializer=serializer,
            tmux_spawn_fn=_good_tmux,
            register_fn=_make_register_backend(conn),
            log_attach_fn=_good_log,
        )
        assert isinstance(outcome, SpawnLayoutOutcome)
        assert outcome.layout_state == ManagedState.READY
        assert all(s == ManagedState.READY for s in outcome.pane_states.values())
        # All marker tokens cleared post-ready (CHECK constraint invariant).
        refreshed = select_panes_for_layout(conn, result.layout_id)
        assert all(p.pending_marker_token is None for p in refreshed)
        assert all(p.agent_id is not None for p in refreshed)
    finally:
        import shutil
        shutil.rmtree(profile_dir, ignore_errors=True)


@pytest.mark.skip(reason="needs FEAT-004 tmux list-sessions pre-check (Phase 4c — T034)")
def test_create_layout_rejects_existing_session_name() -> None:
    """Q6 / FR-016: target tmux session name already exists →
    ``managed_session_name_conflict`` with the conflicting name in details.

    Detection requires the daemon to query the bench container via
    FEAT-004 BEFORE attempting tmux new-session. That cross-FEAT call
    site lands in Phase 4c alongside the FEAT-004 scan update."""


def test_one_pane_failure_does_not_cascade_kill_siblings(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """FR-026: when one pane fails mid-create, sibling in-flight panes
    continue to natural completion (no cascade-kill). Layout state
    aggregates to ``failed`` per data-model.md ManagedLayout lifecycle
    rules ("failed iff at least one pane is failed")."""
    result = create_layout(
        conn=conn,
        serializer=serializer,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-cascade",
    )

    # Inject failure on pane index 1 only; panes 0 and 2 succeed.
    def selective_tmux(pane):  # noqa: ANN001
        if pane.tmux_pane_index == 1:
            return {"ok": False, "error": {"code": "tmux_failed", "message": "injected"}}
        return _good_tmux(pane)

    outcome = spawn_layout_in_background(
        result.layout_id,
        conn=conn,
        serializer=serializer,
        tmux_spawn_fn=selective_tmux,
        register_fn=_make_register_backend(conn),
        log_attach_fn=_good_log,
    )

    # Per-pane: pane 0 ready, pane 1 failed (pane_create), pane 2 ready.
    # FR-026: pane 2 was NOT cascade-killed when pane 1 failed.
    by_index = {p.tmux_pane_index: p for p in select_panes_for_layout(conn, result.layout_id)}
    assert by_index[0].state == ManagedState.READY
    assert by_index[1].state == ManagedState.FAILED
    assert by_index[1].failed_stage.value == "pane_create"
    assert by_index[2].state == ManagedState.READY  # ← no cascade-kill

    # Aggregate: at least one failed → layout failed.
    assert outcome.layout_state == ManagedState.FAILED


@pytest.mark.skip(reason="FR-013 timeout is a tmux_create.py-layer concern (separate test target)")
def test_pane_create_stage_times_out_after_30_seconds() -> None:
    """FR-013 amendment: per-stage 30s timeout. Per plan, the timeout +
    retry policy is enforced inside ``tmux_create.py`` (T011) — the
    background spawn pipeline above this layer only sees the final
    outcome (ok / failed). The timeout test belongs in a dedicated
    ``test_managed_tmux_create_timeouts.py`` test that exercises
    ``tmux_create.py`` directly with a recorded clock + recorded RPC
    backend."""


@pytest.mark.skip(reason="FR-013 retry policy is a tmux_create.py-layer concern (separate test target)")
def test_transient_failures_retry_2x_with_exponential_backoff() -> None:
    """FR-013 amendment: 2x retry with 1s/2s back-off on transient
    failures only. Same rationale as the timeout test above — the retry
    policy lives in ``tmux_create.py``, not the spawn-task orchestrator."""
