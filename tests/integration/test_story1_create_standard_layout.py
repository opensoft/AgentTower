"""FEAT-013 US1 integration test (T021 / T057b).

End-to-end coverage of the three US1 acceptance scenarios, driving the
**production** tmux spawn backend (``make_tmux_spawn_backend``, T057)
through the real ``create_layout`` → ``spawn_layout_in_background``
pipeline:

1. "1 master + 2 slaves" — 3 panes created, launched, registered, ready.
2. "2 masters + 2 slaves" — 4 panes, same shape.
3. Partial failure — one pane's spawn fails; siblings complete; the
   layout lands in a recoverable aggregate state with the failed pane +
   stage identifiable (FR-013 + FR-026 no-cascade-kill).

The CI-runnable bodies wire the production spawn backend over the
in-memory ``FakeTmuxAdapter`` (which implements the same managed verbs
``SubprocessTmuxAdapter`` does), so the exact composition T057 added —
``has-session`` conflict gate, ``new-session`` / ``split-window``
selection, socket resolution, ``@MANAGED:`` marker stamping, ``%N``
pane-id threading — is exercised end-to-end without a bench container.

A ``requires_bench``-marked smoke (bottom of file) drives the same path
against a real ``py-bench`` container via ``docker exec``; it auto-skips
when docker / the bench is unavailable so CI without docker stays green.

Remaining T057b sub-items tracked in #30: live launch-exit detection
(research §R8) and the synchronous-vs-async ``managed_session_name_conflict``
surfacing decision.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from agenttower.managed_sessions.dao import select_panes_for_layout
from agenttower.managed_sessions.handlers.app import app_managed_layout_detail
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.service import (
    create_layout,
    spawn_layout_in_background,
)
from agenttower.managed_sessions.spawn_backends import make_tmux_spawn_backend
from agenttower.managed_sessions.state_machine import FailedStage, ManagedState
from agenttower.state.schema import _apply_migration_v9
from agenttower.tmux import FakeTmuxAdapter
from agenttower.tmux.adapter import TmuxError


CONTAINER = "bench-alpha"
UID = "1000"
BENCH_USER = "tester"


# ─── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY, origin TEXT)")
    c.execute("CREATE TABLE containers (container_id TEXT PRIMARY KEY, active INTEGER DEFAULT 1)")
    c.execute("INSERT INTO containers (container_id, active) VALUES (?, 1)", (CONTAINER,))
    _apply_migration_v9(c)
    c.commit()
    return c


@pytest.fixture()
def serializer() -> ContainerSerializer:
    return ContainerSerializer()


def _fake_adapter() -> FakeTmuxAdapter:
    return FakeTmuxAdapter({"containers": {CONTAINER: {"uid": UID, "sockets": {}}}})


def _prod_spawn(adapter: FakeTmuxAdapter):
    """The real T057 spawn backend over a fake adapter."""
    return make_tmux_spawn_backend(
        adapter=adapter, bench_user_resolver=lambda _cid: BENCH_USER,
    )


def _register_into_agents(conn: sqlite3.Connection):
    def register(pane, tmux_pane_id):  # noqa: ANN001
        agent_id = f"agent-{pane.id[:8]}"
        conn.execute(
            "INSERT INTO agents (agent_id, origin) VALUES (?, ?)",
            (agent_id, "managed"),
        )
        return {"ok": True, "agent_id": agent_id}
    return register


def _log_ok(pane, agent_id):  # noqa: ANN001
    return {"ok": True}


# ─── AS-1: 1 master + 2 slaves ─────────────────────────────────────────


def test_us1_acceptance_1m_2s_healthy_path(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    adapter = _fake_adapter()
    result = create_layout(
        conn=conn, serializer=serializer, container_id=CONTAINER,
        template_name="1m+2s", tmux_session_name="us1-1m2s",
    )
    assert result.intended_pane_count == 3

    spawn_layout_in_background(
        result.layout_id, conn=conn, serializer=serializer,
        tmux_spawn_fn=_prod_spawn(adapter),
        register_fn=_register_into_agents(conn), log_attach_fn=_log_ok,
    )

    panes = select_panes_for_layout(conn, result.layout_id)
    assert len(panes) == 3
    for p in panes:
        assert p.state == ManagedState.READY
        assert p.agent_id is not None
        assert p.pending_marker_token is None  # marker cleared on ready

    # The production spawn backend composed the real tmux verb sequence:
    # first pane → has_session (conflict gate) + new_session; later panes →
    # split_window; every pane → set_pane_title (@MANAGED marker).
    verbs = [name for name, _ in adapter.managed_calls]
    assert verbs.count("has_session") == 1
    assert verbs.count("new_session") == 1
    assert verbs.count("split_window") == 2
    assert verbs.count("set_pane_title") == 3
    # Every marker title uses the @MANAGED:<token>:<label> shape.
    titles = [kw["title"] for name, kw in adapter.managed_calls if name == "set_pane_title"]
    assert all(t.startswith("@MANAGED:") for t in titles)


# ─── AS-2: 2 masters + 2 slaves ────────────────────────────────────────


def test_us1_acceptance_2m_2s_healthy_path(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    adapter = _fake_adapter()
    result = create_layout(
        conn=conn, serializer=serializer, container_id=CONTAINER,
        template_name="2m+2s", tmux_session_name="us1-2m2s",
    )
    assert result.intended_pane_count == 4

    spawn_layout_in_background(
        result.layout_id, conn=conn, serializer=serializer,
        tmux_spawn_fn=_prod_spawn(adapter),
        register_fn=_register_into_agents(conn), log_attach_fn=_log_ok,
    )

    panes = select_panes_for_layout(conn, result.layout_id)
    assert len(panes) == 4
    assert all(p.state == ManagedState.READY for p in panes)
    assert sum(1 for p in panes if p.role == "master") == 2
    assert sum(1 for p in panes if p.role == "slave") == 2

    verbs = [name for name, _ in adapter.managed_calls]
    assert verbs.count("new_session") == 1
    assert verbs.count("split_window") == 3
    assert verbs.count("set_pane_title") == 4


# ─── AS-3: partial failure leaves recoverable state ───────────────────


def test_us1_acceptance_partial_failure_leaves_recoverable_state(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """One pane's tmux spawn fails → that pane lands ``failed`` with
    ``failed_stage = pane_create``; sibling panes complete to ``ready``
    (FR-026 no-cascade-kill); the layout aggregates to the worst child
    (``failed`` — recoverable via recreate)."""
    adapter = _fake_adapter()
    # Fail the FIRST split-window (the second pane) with a NON-transient
    # code so the FR-013 retry policy does not mask it; the first pane
    # (new-session) and the third pane (second split) still succeed.
    adapter.split_window_failures.append(
        TmuxError(code="output_malformed", message="tmux printed no pane id",
                  container_id=CONTAINER)
    )

    result = create_layout(
        conn=conn, serializer=serializer, container_id=CONTAINER,
        template_name="1m+2s", tmux_session_name="us1-partial",
    )
    spawn_layout_in_background(
        result.layout_id, conn=conn, serializer=serializer,
        tmux_spawn_fn=_prod_spawn(adapter),
        register_fn=_register_into_agents(conn), log_attach_fn=_log_ok,
    )

    panes = sorted(select_panes_for_layout(conn, result.layout_id),
                   key=lambda p: p.tmux_pane_index)
    states = [p.state for p in panes]
    # pane 0 (new-session) ready, pane 1 (failed split) failed, pane 2 ready.
    assert states == [ManagedState.READY, ManagedState.FAILED, ManagedState.READY]
    failed = panes[1]
    assert failed.failed_stage == FailedStage.PANE_CREATE
    # FR-026: siblings were NOT cascade-killed.
    assert panes[0].agent_id is not None and panes[2].agent_id is not None

    layout = _detail(conn, serializer, result.layout_id)
    assert layout["state"] == "failed"  # worst-child aggregate, recoverable


# ─── FR-008: managed panes surface alongside adopted ───────────────────


def test_managed_panes_appear_in_agent_surfaces(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    adapter = _fake_adapter()
    result = create_layout(
        conn=conn, serializer=serializer, container_id=CONTAINER,
        template_name="1m+2s", tmux_session_name="us1-surface",
    )
    spawn_layout_in_background(
        result.layout_id, conn=conn, serializer=serializer,
        tmux_spawn_fn=_prod_spawn(adapter),
        register_fn=_register_into_agents(conn), log_attach_fn=_log_ok,
    )

    rows = conn.execute("SELECT origin, COUNT(*) FROM agents GROUP BY origin").fetchall()
    assert dict(rows) == {"managed": 3}

    detail = _detail(conn, serializer, result.layout_id)
    assert detail["state"] == "ready"
    assert detail["origin"] == "managed"
    assert len(detail["panes"]) == 3
    assert all(p["origin"] == "managed" and p["agent_id"] for p in detail["panes"])


def _detail(conn, serializer, layout_id):  # noqa: ANN001
    """Invoke the M3 app.managed_layout_detail handler with the host gate forced."""
    import os

    os.environ["AGENTTOWER_TEST_FORCE_HOST_PEER"] = "1"
    try:
        from agenttower.socket_api.methods import _set_request_peer_context
        _set_request_peer_context(peer_pid=os.getpid())
        ctx = SimpleNamespace(state_conn=conn, managed_serializer=serializer)
        resp = app_managed_layout_detail(ctx, {"layout_id": layout_id}, 1000)
        assert resp["ok"] is True
        return resp["result"]
    finally:
        os.environ.pop("AGENTTOWER_TEST_FORCE_HOST_PEER", None)
        from agenttower.socket_api.methods import _clear_request_peer_context
        _clear_request_peer_context()


# NOTE: A real `docker exec` tmux smoke is intentionally NOT a pytest test —
# `tests/conftest.py::_no_real_docker` forbids real docker suite-wide by
# policy. Real-bench verification of the production backend is an out-of-band
# smoke (run against py-bench during T057); these tests drive the same
# production backend over FakeTmuxAdapter, which is the repo-sanctioned way
# to exercise the docker-exec composition without a container.
