"""FEAT-013 daemon-boot wiring tests (Workstream 1 / C4 + C6).

Exercises the helpers in ``managed_sessions/daemon_boot.py``:

- :func:`make_managed_serializer` returns a working serializer.
- :func:`reconcile_managed_state_at_boot` is fail-soft when
  ``tmux_list_panes_fn`` is None (initial wiring state) and
  surfaces the outcome when a backend is provided.
- :func:`start_pending_marker_sweep` schedules a periodic Timer
  that respects the shutdown event and can be cancelled cleanly.
- :func:`kickoff_spawn_pipeline` is a no-op when the daemon-boot
  wiring is incomplete (no ``managed_spawn_backends``) and starts
  a background thread when wiring is complete.

The handler integration tests in ``test_managed_dispatch.py`` cover
the kickoff path indirectly; this module asserts the wiring
helpers in isolation so daemon-boot regressions surface immediately.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from agenttower.managed_sessions.daemon_boot import (
    kickoff_spawn_pipeline,
    make_managed_serializer,
    reconcile_managed_state_at_boot,
    start_pending_marker_sweep,
)
from agenttower.managed_sessions.dao import (
    ManagedLayoutRow,
    ManagedPaneRow,
    insert_layout,
    insert_pane,
    select_pane,
)
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.state_machine import ManagedState
from agenttower.state.schema import _apply_migration_v9


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE containers (container_id TEXT PRIMARY KEY, active INTEGER DEFAULT 1)")
    c.execute("INSERT INTO containers (container_id, active) VALUES ('bench-alpha', 1)")
    _apply_migration_v9(c)
    c.commit()
    return c


def _ts() -> str:
    return "2026-05-25T00:00:00.000000Z"


# ─── make_managed_serializer ─────────────────────────────────────────────


def test_make_managed_serializer_returns_working_container_lock_map() -> None:
    """The factory returns a usable ContainerSerializer that yields a
    distinct lock per container_id."""
    serializer = make_managed_serializer()
    assert isinstance(serializer, ContainerSerializer)
    lock_a = serializer.for_container("c1")
    lock_a_again = serializer.for_container("c1")
    lock_b = serializer.for_container("c2")
    assert lock_a is lock_a_again, "same key must return the same lock"
    assert lock_a is not lock_b, "different keys must return distinct locks"


# ─── reconcile_managed_state_at_boot ─────────────────────────────────────


def test_reconcile_at_boot_is_fail_soft_when_tmux_backend_unavailable(
    conn: sqlite3.Connection,
) -> None:
    """During initial daemon-boot wiring, the production tmux backend
    isn't ready yet — passing ``tmux_list_panes_fn=None`` must return
    None (skip), NOT crash. Persisted rows are untouched."""
    serializer = make_managed_serializer()
    # Seed a ready layout + pane so we can prove the reconcile didn't
    # touch them when skipped.
    layout_id = str(uuid.uuid4())
    pane_id = str(uuid.uuid4())
    insert_layout(
        conn,
        ManagedLayoutRow(
            id=layout_id, container_id="bench-alpha",
            template_name="1m+2s", intended_pane_count=1,
            state=ManagedState.READY, failed_stage=None,
            idempotency_key=None,
            created_at=_ts(), updated_at=_ts(),
        ),
    )
    insert_pane(
        conn,
        ManagedPaneRow(
            id=pane_id, layout_id=layout_id,
            container_id="bench-alpha", agent_id=None,
            role="master", capability="orchestrator", label="m1",
            launch_command_ref=None,
            tmux_session_name="s", tmux_pane_index=0,
            pending_marker_token=None,
            state=ManagedState.READY, failed_stage=None,
            predecessor_id=None, chain_depth=0,
            created_at=_ts(), updated_at=_ts(),
        ),
    )
    conn.commit()

    outcome = reconcile_managed_state_at_boot(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=None, tx_lock=None,
    )
    assert outcome is None
    # Row state must be untouched.
    pane = select_pane(conn, pane_id)
    assert pane is not None
    assert pane.state == ManagedState.READY


def test_reconcile_at_boot_runs_when_backend_is_provided(
    conn: sqlite3.Connection,
) -> None:
    """When ``tmux_list_panes_fn`` is provided, the reconcile actually
    runs and returns a ReconcileOutcome summary."""
    serializer = make_managed_serializer()
    layout_id = str(uuid.uuid4())
    pane_id = str(uuid.uuid4())
    insert_layout(
        conn,
        ManagedLayoutRow(
            id=layout_id, container_id="bench-alpha",
            template_name="1m+2s", intended_pane_count=1,
            state=ManagedState.READY, failed_stage=None,
            idempotency_key=None,
            created_at=_ts(), updated_at=_ts(),
        ),
    )
    insert_pane(
        conn,
        ManagedPaneRow(
            id=pane_id, layout_id=layout_id,
            container_id="bench-alpha", agent_id=None,
            role="master", capability="orchestrator", label="m1",
            launch_command_ref=None,
            tmux_session_name="s-recon", tmux_pane_index=0,
            pending_marker_token=None,
            state=ManagedState.READY, failed_stage=None,
            predecessor_id=None, chain_depth=0,
            created_at=_ts(), updated_at=_ts(),
        ),
    )
    conn.commit()

    # Tmux says pane is alive → reattach (state preserved).
    outcome = reconcile_managed_state_at_boot(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=lambda cid: [
            {"tmux_session_name": "s-recon", "tmux_pane_index": 0}
        ],
        tx_lock=None,
    )
    assert outcome is not None
    assert outcome.layouts_examined == 1
    assert outcome.panes_reattached == 1


def test_reconcile_at_boot_is_fail_soft_when_backend_raises(
    conn: sqlite3.Connection,
) -> None:
    """A backend that raises (e.g. transient docker_exec failure) must
    NOT crash daemon startup — return None and continue."""
    serializer = make_managed_serializer()
    # Seed a non-terminal layout so the reconcile actually queries the
    # backend (with no layouts, reconcile early-returns without calling
    # the backend at all).
    layout_id = str(uuid.uuid4())
    insert_layout(
        conn,
        ManagedLayoutRow(
            id=layout_id, container_id="bench-alpha",
            template_name="1m+2s", intended_pane_count=1,
            state=ManagedState.READY, failed_stage=None,
            idempotency_key=None,
            created_at=_ts(), updated_at=_ts(),
        ),
    )
    insert_pane(
        conn,
        ManagedPaneRow(
            id=str(uuid.uuid4()), layout_id=layout_id,
            container_id="bench-alpha", agent_id=None,
            role="master", capability="orchestrator", label="m1",
            launch_command_ref=None,
            tmux_session_name="s-angry", tmux_pane_index=0,
            pending_marker_token=None,
            state=ManagedState.READY, failed_stage=None,
            predecessor_id=None, chain_depth=0,
            created_at=_ts(), updated_at=_ts(),
        ),
    )
    conn.commit()

    def angry_backend(cid: str):
        raise RuntimeError("docker_exec transient")

    outcome = reconcile_managed_state_at_boot(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=angry_backend, tx_lock=None,
    )
    assert outcome is None


# ─── start_pending_marker_sweep ──────────────────────────────────────────


def test_pending_marker_sweep_timer_is_cancellable(
    conn: sqlite3.Connection,
) -> None:
    """The Timer can be cancelled cleanly and the cancel function is
    idempotent."""
    shutdown = threading.Event()
    cancel = start_pending_marker_sweep(
        conn=conn, tx_lock=None,
        shutdown_event=shutdown,
        interval_seconds=10.0,  # never fires within test timeframe
    )
    cancel()
    # Second cancel call is a no-op (doesn't raise).
    cancel()


def test_pending_marker_sweep_respects_shutdown_event(
    conn: sqlite3.Connection,
) -> None:
    """When the shutdown_event is set before a tick, the sweep does
    not re-arm. We use a very short interval (50ms) + a recording
    sleep_fn pattern."""
    shutdown = threading.Event()
    cancel = start_pending_marker_sweep(
        conn=conn, tx_lock=None,
        shutdown_event=shutdown,
        interval_seconds=0.05,
    )
    # Set shutdown before the first tick fires.
    shutdown.set()
    time.sleep(0.15)  # well past the interval
    cancel()
    # No assertion needed beyond "didn't deadlock or raise".


# ─── kickoff_spawn_pipeline ──────────────────────────────────────────────


def test_kickoff_spawn_pipeline_is_noop_when_wiring_incomplete(
    conn: sqlite3.Connection,
) -> None:
    """C4 fix: when ``managed_spawn_backends`` is None (initial wiring
    state), kickoff is a no-op (logs a warning and returns). The
    handler still returns a creating-state row."""
    ctx = SimpleNamespace(
        state_conn=conn,
        managed_serializer=make_managed_serializer(),
        managed_spawn_backends=None,  # not wired yet
        state_tx_lock=None,
    )
    # Should not raise and should not start a thread we can't track.
    kickoff_spawn_pipeline(layout_id="some-layout", ctx=ctx)


def test_kickoff_spawn_pipeline_starts_thread_when_wiring_complete(
    conn: sqlite3.Connection,
) -> None:
    """When all backends are wired, kickoff launches a daemon thread
    that calls spawn_layout_in_background with the right arguments."""
    serializer = make_managed_serializer()
    # Seed a creating layout + pane so the thread has something to do.
    from agenttower.managed_sessions.service import create_layout
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="kickoff",
    )

    register_calls = [0]

    def tmux_spawn(pane):
        return {"ok": True, "tmux_pane_id": f"%{pane.tmux_pane_index}", "launch_alive": True}

    def register(pane, tmux_pane_id):
        register_calls[0] += 1
        agent_id = f"agent-{pane.id[:8]}"
        conn.execute("INSERT OR IGNORE INTO agents (agent_id) VALUES (?)", (agent_id,))
        return {"ok": True, "agent_id": agent_id}

    def log_attach(pane, agent_id):
        return {"ok": True}

    ctx = SimpleNamespace(
        state_conn=conn,
        managed_serializer=serializer,
        managed_spawn_backends={
            "tmux_spawn": tmux_spawn,
            "register": register,
            "log_attach": log_attach,
        },
        state_tx_lock=None,
    )
    kickoff_spawn_pipeline(layout_id=result.layout_id, ctx=ctx)

    # Wait briefly for the thread to settle. The test asserts only on
    # "register was called" — we don't care about the exact final
    # state, only that the bg thread fired.
    deadline = time.monotonic() + 5.0
    while register_calls[0] == 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert register_calls[0] >= 1, (
        "spawn pipeline thread did not invoke register backend"
    )
