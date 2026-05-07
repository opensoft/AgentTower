"""Unit tests for FEAT-006 last_seen_at + active cascade (T032 / FR-009 / FR-009a).

Covers:
* Every FEAT-004 reconciliation transaction observing pane active=true
  updates ``agents.last_seen_at`` in the same transaction.
* Pane active 1→0 cascades ``agents.active = 0`` in the same transaction.
* Pane inactive→active does NOT auto-flip ``agents.active``.
* CLI calls (register_agent / list_agents / set_*) MUST NOT touch
  ``last_seen_at`` (asserted by snapshot before/after the call).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agenttower.state import agents as state_agents
from agenttower.state import panes as state_panes
from agenttower.state.panes import (
    PaneReconcileWriteSet,
    PaneUpsert,
)

from ._agent_test_helpers import (
    CK_DEFAULT,
    make_service,
    register_params,
    seed_container,
    seed_pane,
)


def _read_last_seen_at(service, agent_id: str) -> str | None:
    conn = service.connection_factory()
    try:
        row = conn.execute(
            "SELECT last_seen_at FROM agents WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def test_update_last_seen_at_helper_updates_only_matching(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    result = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    aid = result["agent_id"]
    assert _read_last_seen_at(service, aid) is None

    # Simulate a FEAT-004 reconciliation transaction.
    conn = service.connection_factory()
    try:
        conn.execute("BEGIN IMMEDIATE")
        state_agents.update_last_seen_at(
            conn,
            pane_keys=[CK_DEFAULT],
            now_iso="2026-05-07T12:00:00.000000+00:00",
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    assert _read_last_seen_at(service, aid) == "2026-05-07T12:00:00.000000+00:00"


def test_cascade_agents_active_from_pane(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    result = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    aid = result["agent_id"]

    conn = service.connection_factory()
    try:
        conn.execute("BEGIN IMMEDIATE")
        state_agents.cascade_agents_active_from_pane(
            conn, pane_keys=[CK_DEFAULT]
        )
        conn.execute("COMMIT")
    finally:
        conn.close()

    conn = service.connection_factory()
    try:
        active = conn.execute(
            "SELECT active FROM agents WHERE agent_id = ?", (aid,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert active == 0


def test_register_does_not_touch_last_seen_at(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    # Simulate a scan that set last_seen_at.
    conn = service.connection_factory()
    try:
        conn.execute("BEGIN IMMEDIATE")
        state_agents.update_last_seen_at(
            conn,
            pane_keys=[CK_DEFAULT],
            now_iso="2026-05-07T12:00:00.000000+00:00",
        )
        conn.execute("COMMIT")
    finally:
        conn.close()

    # Now re-register; last_seen_at MUST NOT be modified by register_agent.
    service.register_agent(
        register_params(role="slave", label="new"), socket_peer_uid=1000
    )
    assert _read_last_seen_at(service, first["agent_id"]) == (
        "2026-05-07T12:00:00.000000+00:00"
    )


def test_set_label_does_not_touch_last_seen_at(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    first = service.register_agent(
        register_params(role="slave", label="orig"), socket_peer_uid=1000
    )
    conn = service.connection_factory()
    try:
        conn.execute("BEGIN IMMEDIATE")
        state_agents.update_last_seen_at(
            conn,
            pane_keys=[CK_DEFAULT],
            now_iso="2026-05-07T12:00:00.000000+00:00",
        )
        conn.execute("COMMIT")
    finally:
        conn.close()

    service.set_label(
        {"agent_id": first["agent_id"], "label": "new"},
        socket_peer_uid=1000,
    )
    assert _read_last_seen_at(service, first["agent_id"]) == (
        "2026-05-07T12:00:00.000000+00:00"
    )


def test_update_last_seen_at_chunks_above_sqlite_param_limit(tmp_path: Path) -> None:
    """Review-pass-3: large scans must not hit SQLITE_MAX_VARIABLE_NUMBER.

    Each pane composite key contributes 6 bound parameters, plus one
    for ``now_iso``. SQLite's default limit is 999 on older builds, so
    a single UPDATE could only handle ~166 keys. Drive a count well
    above the chunk size to prove the helper batches statements rather
    than emitting one giant UPDATE that would fail at runtime.
    """
    from agenttower.state.agents import _PANE_KEY_BATCH

    service = make_service(tmp_path)
    seed_container(service)

    # Build many pane keys — they don't have to match real seeded panes
    # for the UPDATE itself to run; we're proving the SQL emits cleanly.
    bench_keys = [
        (
            CK_DEFAULT[0],
            CK_DEFAULT[1],
            CK_DEFAULT[2],
            window // 32,
            window % 32,
            f"%{window}",
        )
        for window in range(_PANE_KEY_BATCH * 2 + 25)
    ]

    conn = service.connection_factory()
    try:
        conn.execute("BEGIN IMMEDIATE")
        # If we ever regress to a single UPDATE, this raises
        # ``sqlite3.OperationalError: too many SQL variables`` on a
        # default SQLite build.
        state_agents.update_last_seen_at(
            conn,
            pane_keys=bench_keys,
            now_iso="2026-05-07T12:00:00.000000+00:00",
        )
        state_agents.cascade_agents_active_from_pane(
            conn,
            pane_keys=bench_keys,
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


def test_reconcile_updates_last_seen_for_every_observed_pane(tmp_path: Path) -> None:
    """Review-pass-2: agents bound to non-tmux-focused panes still get
    ``last_seen_at`` bumped on reconciliation.

    Regression for the FR-009a finding that the reconciler filtered on
    ``upsert.pane_active`` (the tmux *focus* flag — only one pane per
    window has it set), so agents bound to inactive-but-alive panes
    looked stale even though their panes were observed.
    """
    from agenttower.discovery.pane_service import PaneDiscoveryService
    from agenttower.state.panes import PaneReconcileWriteSet, PaneUpsert

    service = make_service(tmp_path)
    seed_container(service)
    # Two panes in the same window: one focused, one not.
    seed_pane(service, tmux_pane_index=0, tmux_pane_id="%0")
    seed_pane(service, tmux_pane_index=1, tmux_pane_id="%1")
    a = service.register_agent(
        register_params(role="slave", label="focused"), socket_peer_uid=1000
    )
    ck1 = (CK_DEFAULT[0], CK_DEFAULT[1], CK_DEFAULT[2], 0, 1, "%1")
    b = service.register_agent(
        register_params(ck1, role="slave", label="unfocused"),
        socket_peer_uid=1000,
    )

    def _upsert(pane_index: int, pane_id: str, *, is_focused: bool) -> PaneUpsert:
        return PaneUpsert(
            container_id=CK_DEFAULT[0],
            tmux_socket_path=CK_DEFAULT[1],
            tmux_session_name=CK_DEFAULT[2],
            tmux_window_index=0,
            tmux_pane_index=pane_index,
            tmux_pane_id=pane_id,
            container_name="bench-test",
            container_user="user",
            pane_pid=12345,
            pane_tty="/dev/pts/0",
            pane_current_command="bash",
            pane_current_path="/w",
            pane_title="title",
            pane_active=is_focused,
            last_scanned_at="2026-05-07T12:00:00.000000+00:00",
        )

    write_set = PaneReconcileWriteSet(
        upserts=[
            _upsert(0, "%0", is_focused=True),
            _upsert(1, "%1", is_focused=False),
        ],
        panes_seen=2,
    )

    # Drive the same private commit path the reconciler uses.
    conn = service.connection_factory()
    try:
        pds = PaneDiscoveryService.__new__(PaneDiscoveryService)
        pds._conn = conn
        pds._events_file = service.events_file
        pds._commit_scan(
            scan_id="test-scan-001",
            started_at="2026-05-07T12:00:00.000000+00:00",
            status="ok",
            write_set=write_set,
            containers_scanned=1,
            sockets_scanned=1,
            error_code=None,
            error_message=None,
            error_details=[],
        )
    finally:
        conn.close()

    assert (
        _read_last_seen_at(service, a["agent_id"])
        == "2026-05-07T12:00:00.000000+00:00"
    )
    assert (
        _read_last_seen_at(service, b["agent_id"])
        == "2026-05-07T12:00:00.000000+00:00"
    ), "non-focused pane's agent must still bump last_seen_at"
