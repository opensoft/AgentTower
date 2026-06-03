"""FEAT-013 T054 + T055 + T056: SC perf-marker SLA tests.

Wall-clock assertions for the three time-budgeted success criteria:

- **T054 / SC-001**: layout-create returns from the synchronous portion
  (row insertion) well under the 120s p95 budget. The spawn pipeline
  itself runs in the background and is NOT covered here — the SC-001
  budget is for the operator-visible response shape, which the
  synchronous path bounds.
- **T055 / SC-008**: ``recovery.reconcile()`` against a healthy ≤4-layout
  scenario completes in ≤5 seconds of wall-clock.
- **T056 / SC-009**: post-reconcile, the M3 / M5 detail surfaces return
  the recovery outcome (state + failed_stage) within 5 seconds of
  socket-ready. In-process measurement uses ``time.monotonic()`` between
  reconcile-complete and detail-handler-return.

All three are **in-process** measurements using canned backends —
production wall-clock budgets bake in network + docker-exec latency
which a real bench-container CI run measures separately. These markers
catch regressions in the core orchestration / detail-projection paths.
"""

from __future__ import annotations

import datetime as _dt
import os
import sqlite3
import time
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from agenttower.app_contract.dispatcher import APP_DISPATCH
from agenttower.managed_sessions.dao import (
    ManagedLayoutRow,
    ManagedPaneRow,
    insert_layout,
    insert_pane,
)
from agenttower.managed_sessions.recovery import reconcile
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.service import create_layout
from agenttower.managed_sessions.state_machine import ManagedState
from agenttower.state.schema import _apply_migration_v9


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    c.execute("CREATE TABLE containers (container_id TEXT PRIMARY KEY, active INTEGER DEFAULT 1)")
    c.execute("INSERT INTO containers (container_id, active) VALUES (?, 1)", ("bench-alpha",))
    _apply_migration_v9(c)
    c.commit()
    return c


@pytest.fixture()
def serializer() -> ContainerSerializer:
    return ContainerSerializer()


@pytest.fixture()
def ctx(conn, serializer) -> Any:  # noqa: ANN001
    return SimpleNamespace(state_conn=conn, managed_serializer=serializer)


HOST_PEER_UID = 1000


@pytest.fixture(autouse=True)
def force_host_peer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    from agenttower.socket_api.methods import (
        _clear_request_peer_context,
        _set_request_peer_context,
    )
    _set_request_peer_context(peer_pid=os.getpid())
    yield
    _clear_request_peer_context()


def _ts(when: _dt.datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.UTC)
    return when.isoformat(timespec="microseconds").replace("+00:00", "Z")


# ─── T054 / SC-001: layout-create synchronous response under p95 budget ─


@pytest.mark.perf
def test_sc001_layout_create_sync_returns_under_2_seconds(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """SC-001's 120s budget is for the operator-visible response; the
    synchronous create_layout call (row insertion) should complete in
    well under 2s on a healthy daemon (in-process measurement). This
    catches regressions in the validation / template-resolve / SQLite
    insert path."""
    start = time.monotonic()
    result = create_layout(
        conn=conn,
        serializer=serializer,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="perf-sc001",
    )
    elapsed = time.monotonic() - start

    assert result.state == ManagedState.CREATING
    # In-process budget: 2s (the SC-001 120s budget includes the
    # background spawn pipeline + tmux RPCs; the sync portion should
    # be orders of magnitude faster).
    assert elapsed < 2.0, (
        f"create_layout synchronous portion took {elapsed:.3f}s; "
        f"SC-001 budgets 120s for the full operator-visible response, "
        f"so the sync portion regressing past 2s is a real signal."
    )


# ─── T055 / SC-008: reconcile completes for ≤4 layouts in ≤5s ──────────


def _seed_layout_for_recovery(
    conn: sqlite3.Connection,
    *,
    container_id: str,
    pane_count: int,
    session_name: str,
) -> str:
    layout_id = str(uuid.uuid4())
    now = _ts(_dt.datetime.now(_dt.UTC))
    insert_layout(
        conn,
        ManagedLayoutRow(
            id=layout_id, container_id=container_id,
            template_name="1m+2s", intended_pane_count=pane_count,
            state=ManagedState.READY, failed_stage=None,
            idempotency_key=None,
            created_at=now, updated_at=now,
        ),
    )
    for i in range(pane_count):
        insert_pane(
            conn,
            ManagedPaneRow(
                id=str(uuid.uuid4()), layout_id=layout_id,
                container_id=container_id, agent_id=None,
                role="master" if i == 0 else "slave",
                capability="orchestrator" if i == 0 else "worker",
                label="m1" if i == 0 else f"s{i}",
                launch_command_ref=None,
                tmux_session_name=session_name, tmux_pane_index=i,
                pending_marker_token=None,
                state=ManagedState.READY, failed_stage=None,
                predecessor_id=None, chain_depth=0,
                created_at=now, updated_at=now,
            ),
        )
    conn.commit()
    return layout_id


@pytest.mark.perf
def test_sc008_reconcile_four_layouts_under_5_seconds(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """SC-008 budgets ≤5s for daemon-restart reattach of up to 4 managed
    layouts. In-process with a canned tmux backend the reconcile should
    finish in well under that — the budget exists to cover the real
    docker-exec latency the production path adds.

    Per FR-003 the per-container label-uniqueness index forbids two
    layouts in the same container sharing labels (and the built-in
    template uses fixed `m1`/`s1`/`s2` labels), so this test seeds
    each layout in a DIFFERENT container — matching the SC-008
    "≤4 managed layouts across ≤10 bench containers" scale envelope.
    """
    # Each layout in its own container (FR-003 label uniqueness).
    containers = [f"bench-perf-{i}" for i in range(4)]
    for cid in containers:
        conn.execute(
            "INSERT OR IGNORE INTO containers (container_id, active) VALUES (?, 1)",
            (cid,),
        )
    conn.commit()
    for i, cid in enumerate(containers):
        _seed_layout_for_recovery(
            conn,
            container_id=cid,
            pane_count=3,
            session_name=f"perf-sc008-{i}",
        )

    def all_alive(container_id: str):  # noqa: ANN001
        # The reconcile asks per-container; return that container's panes.
        if container_id in containers:
            idx = containers.index(container_id)
            return [
                {"tmux_session_name": f"perf-sc008-{idx}", "tmux_pane_index": j}
                for j in range(3)
            ]
        return []

    start = time.monotonic()
    outcome = reconcile(
        conn=conn, serializer=serializer,
        tmux_list_panes_fn=all_alive,
    )
    elapsed = time.monotonic() - start

    assert outcome.layouts_examined == 4
    assert outcome.panes_reattached == 12
    # In-process budget: well under 5s. We use 2s as the regression
    # threshold (the SC-008 budget is wall-clock including docker-exec).
    assert elapsed < 2.0, (
        f"reconcile of 4 layouts took {elapsed:.3f}s in-process; "
        f"SC-008 budgets 5s wall-clock for the same scenario with real "
        f"docker-exec — a sub-2s in-process regression is a real signal."
    )


# ─── T056 / SC-009: post-reconcile M3/M5 visibility under 5s ────────────


@pytest.mark.perf
def test_sc009_m3_detail_visibility_under_5_seconds(
    ctx: Any
) -> None:
    """SC-009 budgets ≤5s between socket-ready and the recovery outcome
    appearing on M3 / M5 detail surfaces. In-process this is the time
    from reconcile-complete to detail-handler-return — should be
    well under 5s (it's a SQLite SELECT + dict projection)."""
    # Seed + reconcile a failed-reattach scenario.
    layout_id = _seed_layout_for_recovery(
        ctx.state_conn,
        container_id="bench-alpha",
        pane_count=3,
        session_name="perf-sc009",
    )
    reconcile(
        conn=ctx.state_conn,
        serializer=ctx.managed_serializer,
        tmux_list_panes_fn=lambda cid: [],  # no tmux → all fail
    )

    # Measure: how long does M3 detail take to return the recovery outcome?
    start = time.monotonic()
    resp = APP_DISPATCH["app.managed_layout_detail"](
        ctx, {"layout_id": layout_id}, HOST_PEER_UID,
    )
    m3_elapsed = time.monotonic() - start

    assert resp["ok"] is True
    assert resp["result"]["state"] == "failed"
    assert resp["result"]["failed_stage"] == "recovery_reattach"

    # Also measure M5 single-pane detail.
    pane_id = resp["result"]["panes"][0]["pane_id"]
    start = time.monotonic()
    pane_resp = APP_DISPATCH["app.managed_pane_detail"](
        ctx, {"pane_id": pane_id}, HOST_PEER_UID,
    )
    m5_elapsed = time.monotonic() - start

    assert pane_resp["ok"] is True
    assert pane_resp["result"]["failed_stage"] == "recovery_reattach"

    # Both should be sub-second in-process. The 5s SC-009 budget covers
    # the daemon-side population (which T055 already measured) + this
    # detail-handler latency.
    assert m3_elapsed < 1.0, f"M3 detail took {m3_elapsed:.3f}s — sub-1s expected"
    assert m5_elapsed < 1.0, f"M5 detail took {m5_elapsed:.3f}s — sub-1s expected"
