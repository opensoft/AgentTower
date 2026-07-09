"""FEAT-013 T026: log-attach failure → ``degraded`` (FR-006 / SC-003).

When the FEAT-007 log-attach backend fails for a pane, the affected
pane MUST land in ``degraded`` with ``failed_stage = log_attach``, but
the layout MUST still complete (no cascade-kill against siblings whose
log-attach succeeded). The failure event ``managed_pane_log_attach_failed``
MUST be emitted with the failure reason.

SC-003 (≤ 10s visibility after layout creation completion) is enforced
at the operational layer — the spawn pipeline emits the lifecycle event
synchronously when the FEAT-007 backend returns, so the visibility
budget is bounded by the FEAT-007 attach call's own timeout (a separate
budget). This test covers the *state-machine* + *event* shape, not the
wall-clock budget (the latter is covered by Phase 6 T054/T055/T056
perf-marker tasks).
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


# Healthy backends — overridden per-test for the failure injection point.
def _good_tmux(pane):  # noqa: ANN001
    return {
        "ok": True,
        "tmux_pane_id": f"%t-{pane.tmux_pane_index}",
        "launch_alive": True,
    }


def _make_register_backend(conn):  # noqa: ANN001
    """FEAT-006-shaped fake that inserts the agent into the FK-target table."""
    def register(pane, tmux_pane_id):  # noqa: ANN001
        agent_id = f"agent-{pane.id[:8]}"
        conn.execute("INSERT INTO agents (agent_id) VALUES (?)", (agent_id,))
        return {"ok": True, "agent_id": agent_id}
    return register


# ─── FR-006 + SC-003: log-attach failure → degraded ─────────────────────


def test_log_attach_failure_degrades_pane_not_layout(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """One pane's log-attach failure degrades only that pane; others stay ready.

    Data-model.md ManagedLayout lifecycle: aggregate is ``degraded`` iff
    at least one pane is degraded AND no pane is creating/failed.
    """
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="session-logfail",
    )

    def selective_log(pane, agent_id):  # noqa: ANN001
        # Inject log-attach failure on the master pane only.
        if pane.role == "master":
            return {
                "ok": False,
                "error": {
                    "code": "log_path_not_host_visible",
                    "message": "/tmp/feat013-log-001 not bind-mounted to host",
                },
            }
        return {"ok": True}

    outcome = spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_good_tmux,
        register_fn=_make_register_backend(conn),
        log_attach_fn=selective_log,
    )

    all_panes = select_panes_for_layout(conn, result.layout_id)
    masters = [p for p in all_panes if p.role == "master"]
    slaves = [p for p in all_panes if p.role == "slave"]
    assert len(masters) == 1
    master = masters[0]
    assert master.state == ManagedState.DEGRADED
    assert master.failed_stage == FailedStage.LOG_ATTACH
    assert master.agent_id == f"agent-{master.id[:8]}"  # registration still succeeded
    assert master.pending_marker_token is None  # CHECK invariant

    # The two slave panes had healthy log-attach → ready.
    assert len(slaves) == 2
    assert all(p.state == ManagedState.READY for p in slaves)

    # Aggregate: at-least-one degraded, none creating/failed → degraded.
    assert outcome.layout_state == ManagedState.DEGRADED


def test_log_attach_failure_emits_event_with_reason(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """The ``managed_pane_log_attach_failed`` event carries the FEAT-007
    error message in its ``reason`` payload field so operators can
    diagnose without consulting daemon logs."""
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="session-logfail-ev",
    )

    events: list[dict] = []

    def failing_log(pane, agent_id):  # noqa: ANN001
        return {
            "ok": False,
            "error": {"code": "log_path_in_use", "message": "log path already attached to agent-X"},
        }

    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_good_tmux,
        register_fn=_make_register_backend(conn),
        log_attach_fn=failing_log,
        event_emitter=events.append,
    )

    log_failed_events = [
        e for e in events if e["event_type"] == "managed_pane_log_attach_failed"
    ]
    # Every pane in the layout had a log-attach attempt that failed.
    assert len(log_failed_events) == 3
    for e in log_failed_events:
        assert e["actor"] == "daemon"
        assert "log path already attached" in str(e["payload"]["reason"])
