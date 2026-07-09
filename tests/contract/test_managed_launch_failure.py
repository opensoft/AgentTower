"""FEAT-013 T027: launch command failure → ``degraded`` / ``failed`` (Q8 / FR-013).

Two failure modes for the launch command stage:

1. **Immediate-exit recoverable** (Q8 clarification): pane spawns, the
   launch command exits within 1 second. Pane lands in ``degraded`` with
   ``failed_stage = launch_command``. Registration still succeeds
   because the FEAT-006 register path runs against the (now-empty)
   pane, and the pane is still operator-visible — the operator can
   ``managed.pane.recreate`` to retry.

2. **Pane-create-failed non-recoverable**: ``tmux new-session`` /
   ``split-window`` returns a non-zero exit. Pane lands in ``failed``
   with ``failed_stage = pane_create`` (the launch_command stage was
   never reached). Already covered by
   ``test_managed_layout_create.py::test_one_pane_failure_does_not_cascade_kill_siblings``.

This module covers case (1) — the launch-command-degraded path —
because it has a distinct event emission (``PANE_LAUNCH_COMMAND_EXITED``)
and a distinct ``failed_stage`` value.
"""

from __future__ import annotations

import sqlite3

import pytest

from agenttower.managed_sessions.dao import select_panes_for_layout
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.service import (
    create_layout,
    spawn_layout_in_background,
)
from agenttower.managed_sessions.state_machine import FailedStage, ManagedState
from agenttower.state.schema import _apply_migration_v9


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    _apply_migration_v9(c)
    return c


@pytest.fixture()
def serializer() -> ContainerSerializer:
    return ContainerSerializer()


def _make_register_backend(conn):  # noqa: ANN001
    """FEAT-006-shaped fake that inserts the agent into the FK-target table."""
    def register(pane, tmux_pane_id):  # noqa: ANN001
        agent_id = f"agent-{pane.id[:8]}"
        conn.execute("INSERT INTO agents (agent_id) VALUES (?)", (agent_id,))
        return {"ok": True, "agent_id": agent_id}
    return register


def _good_log(pane, agent_id):  # noqa: ANN001
    return {"ok": True}


# ─── Q8 / FR-013: launch immediate-exit → degraded(launch_command) ──────


def test_launch_command_immediate_exit_lands_pane_in_degraded(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Pane spawns but the launch command exits within 1s. Per Q8 +
    FR-013, the pane lands in ``degraded`` with
    ``failed_stage = launch_command``. The pane still gets an
    ``agent_id`` because FEAT-006 registration succeeds against the
    now-empty pane.
    """
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="session-launch-exit",
    )

    def exiting_tmux(pane):  # noqa: ANN001
        return {
            "ok": True,
            "tmux_pane_id": f"%t-{pane.tmux_pane_index}",
            "launch_alive": False,  # ← immediate-exit signal
            "exit_code": 1,
            "elapsed_ms": 200,
        }

    outcome = spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=exiting_tmux,
        register_fn=_make_register_backend(conn),
        log_attach_fn=_good_log,
    )

    panes = select_panes_for_layout(conn, result.layout_id)
    for p in panes:
        assert p.state == ManagedState.DEGRADED, p.id
        assert p.failed_stage == FailedStage.LAUNCH_COMMAND, p.id
        assert p.agent_id is not None, p.id  # registration still ran
        assert p.pending_marker_token is None, p.id  # CHECK invariant

    # Aggregate: all degraded, no creating/failed → degraded.
    assert outcome.layout_state == ManagedState.DEGRADED


def test_launch_command_immediate_exit_emits_event(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """``managed_pane_launch_command_exited`` event carries ``exit_code``
    and ``elapsed_ms`` per the R11 catalog payload schema."""
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="session-launch-event",
    )

    events: list[dict] = []

    def exiting_tmux(pane):  # noqa: ANN001
        return {
            "ok": True,
            "tmux_pane_id": f"%t-{pane.tmux_pane_index}",
            "launch_alive": False,
            "exit_code": 127,
            "elapsed_ms": 450,
        }

    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=exiting_tmux,
        register_fn=_make_register_backend(conn),
        log_attach_fn=_good_log,
        event_emitter=events.append,
    )

    exit_events = [
        e for e in events if e["event_type"] == "managed_pane_launch_command_exited"
    ]
    assert len(exit_events) == 3  # one per pane
    for e in exit_events:
        assert e["actor"] == "daemon"
        assert e["payload"]["exit_code"] == 127
        assert e["payload"]["elapsed_ms"] == 450


def test_partial_launch_exit_mixed_layout_aggregates_to_degraded(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Only one pane has immediate-exit; the others are healthy. Layout
    aggregates to ``degraded`` (FR-026 + data-model.md rules) — the
    healthy panes are NOT cascade-killed."""
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="session-launch-partial",
    )

    def selective_tmux(pane):  # noqa: ANN001
        if pane.role == "master":
            return {
                "ok": True,
                "tmux_pane_id": f"%t-{pane.tmux_pane_index}",
                "launch_alive": False,
                "exit_code": 1, "elapsed_ms": 100,
            }
        return {
            "ok": True,
            "tmux_pane_id": f"%t-{pane.tmux_pane_index}",
            "launch_alive": True,
        }

    outcome = spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=selective_tmux,
        register_fn=_make_register_backend(conn),
        log_attach_fn=_good_log,
    )

    by_role = {p.role: p for p in select_panes_for_layout(conn, result.layout_id)}
    assert by_role["master"].state == ManagedState.DEGRADED
    assert by_role["master"].failed_stage == FailedStage.LAUNCH_COMMAND
    slaves = [p for p in select_panes_for_layout(conn, result.layout_id) if p.role == "slave"]
    assert all(p.state == ManagedState.READY for p in slaves)

    assert outcome.layout_state == ManagedState.DEGRADED
