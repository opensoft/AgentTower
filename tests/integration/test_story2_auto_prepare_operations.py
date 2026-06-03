"""FEAT-013 US2 integration test (T028).

Covers the three US2 acceptance scenarios with the spawn pipeline driven
synchronously against canned backends. Per N34 sub-scope split, this
file exercises:

1. **US2 AS-1**: a managed pane has role / capability / label / state /
   log-attach state populated after the spawn pipeline runs (FR-005).
2. **US2 AS-2**: managed-pane output is classifiable + routable through
   the same event surfaces as adopted panes (FR-008 — exercised by
   verifying the events emitted by the spawn pipeline are well-formed
   JSONL-audit-pipeline shape, with `origin = "managed"`).
3. **US2 AS-3**: managed + adopted agents coexist in the same container
   without separate workflows (FR-009 — exercised by seeding an adopted
   row alongside the managed one and asserting both surface side-by-side
   via the M3 detail handler).

Additional assertions:
- **FR-015 per-pane FIFO + per-layout FIFO ordering** — the recorded
  event sequence for any single pane appears in state-transition order
  (PANE_CREATED before PANE_PENDING_MARKER_SET before PANE_STATE_CHANGED
  etc.); same for any single layout.
- **FR-021 env-var redaction policy** — currently asserted in the
  "redaction-as-absence" form per N35 (research §R11 reconciliation):
  no event payload field carries env-keyed values. When a later feature
  adds diagnostic env to a failure event, this assertion tightens to
  "TOKEN/SECRET/KEY/PASSWORD substring keys redacted; others preserved;
  argv + working_dir preserved unredacted".

Production end-to-end (real daemon socket + real tmux/docker-exec)
remains gated on the spawn-backends factory wiring described in
`managed_sessions/spawn_backends.py`. Until then, these tests use
canned backends to exercise the orchestration / event shape without
needing a bench container.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from agenttower.managed_sessions.dao import select_panes_for_layout
from agenttower.managed_sessions.handlers.app import app_managed_layout_detail
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.managed_sessions.service import (
    create_layout,
    spawn_layout_in_background,
)
from agenttower.managed_sessions.state_machine import ManagedState
from agenttower.state.schema import _apply_migration_v9


# ─── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """In-memory SQLite with FEAT-001 ``agents`` stub + ``containers`` row
    + FEAT-013 v9 schema. The ``agents`` table is created here as a stub
    just deep enough to satisfy the ``managed_pane.agent_id REFERENCES
    agents(agent_id)`` FK — the register backend inserts rows into it
    during the spawn pipeline."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY, origin TEXT)")
    c.execute("CREATE TABLE containers (container_id TEXT PRIMARY KEY, active INTEGER DEFAULT 1)")
    c.execute(
        "INSERT INTO containers (container_id, active) VALUES (?, 1)",
        ("bench-alpha",),
    )
    _apply_migration_v9(c)
    c.commit()
    return c


@pytest.fixture()
def serializer() -> ContainerSerializer:
    return ContainerSerializer()


def _tmux_ok(pane):  # noqa: ANN001
    return {
        "ok": True,
        "tmux_pane_id": f"%t-{pane.tmux_pane_index}",
        "launch_alive": True,
    }


def _register_into_agents(conn):  # noqa: ANN001
    """Build a register backend that inserts the agent_id into the
    FK-target ``agents`` table with ``origin='managed'`` so the FEAT-005
    distinction is verifiable via direct SQL."""
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


# ─── US2 AS-1: managed pane populates the expected attributes ───────────


def test_us2_as1_managed_pane_has_full_attribute_set(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """After spawn pipeline runs, every managed pane has populated
    role / capability / label / state / log-attached attribute set
    (FR-005 / SC-002)."""
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="us2-as1",
    )
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_tmux_ok,
        register_fn=_register_into_agents(conn),
        log_attach_fn=_log_ok,
    )

    panes = select_panes_for_layout(conn, result.layout_id)
    assert len(panes) == 3
    # FR-005 + US2 AS-1: every pane carries role, capability, label,
    # state, and (after spawn) agent_id + cleared marker.
    for p in panes:
        assert p.role in ("master", "slave")
        assert p.capability in ("orchestrator", "worker")
        assert p.label  # non-empty
        assert p.state == ManagedState.READY
        assert p.agent_id is not None
        assert p.pending_marker_token is None

    # Verify origin=managed propagated into the agents table (the FEAT-006
    # surface FR-008 expects). Operators see managed agents alongside
    # adopted agents in the existing `app.agent.list` shape.
    rows = conn.execute("SELECT agent_id, origin FROM agents").fetchall()
    assert len(rows) == 3
    assert all(r[1] == "managed" for r in rows)


# ─── US2 AS-2: lifecycle event surface is uniform with FEAT-008 audit ───


def test_us2_as2_events_share_jsonl_audit_shape(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Lifecycle events from the managed spawn pipeline carry the same
    envelope shape FEAT-008 already accepts (origin / event_type / actor
    / layout_id / pane_id / sequence / payload / timestamp). Validates
    FR-008 (managed-pane events flow through the same event surfaces
    as adopted panes) at the JSONL-payload shape level."""
    events: list[dict[str, Any]] = []

    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="us2-as2",
        event_emitter=events.append,
    )
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_tmux_ok,
        register_fn=_register_into_agents(conn),
        log_attach_fn=_log_ok,
        event_emitter=events.append,
    )

    # Every event carries the full FR-015 envelope shape.
    required_keys = {"origin", "event_type", "actor", "layout_id",
                     "pane_id", "sequence", "payload", "timestamp"}
    for e in events:
        assert required_keys.issubset(e.keys()), e
        assert e["origin"] == "managed"
        assert e["actor"] in ("operator", "daemon")
        assert isinstance(e["sequence"], int)

    # Sync side emits 3 actor=operator events per pane (1 layout +
    # 2 per pane) — actually 1 LAYOUT_CREATED + 3×2 pane events = 7.
    operator_events = [e for e in events if e["actor"] == "operator"]
    daemon_events = [e for e in events if e["actor"] == "daemon"]
    assert len(operator_events) == 7  # 1 layout_created + 6 pane sync events
    # Bg pipeline emits at least 3 PANE_PENDING_MARKER_CLEARED +
    # 3 PANE_STATE_CHANGED + 1 LAYOUT_STATE_CHANGED = 7 events minimum.
    assert len(daemon_events) >= 7


# ─── US2 AS-3: managed + adopted coexist ────────────────────────────────


def test_us2_as3_managed_and_adopted_agents_coexist(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """A managed-created pane and an adopted pane share the agents table
    side by side without separate workflows (FR-009 / SC-004). Verified
    by seeding one adopted row before spawn and asserting both rows
    appear after spawn (managed origin in agents.origin column = 'managed',
    adopted = 'adopted')."""
    conn.execute(
        "INSERT INTO agents (agent_id, origin) VALUES (?, ?)",
        ("agent-adopted-001", "adopted"),
    )
    conn.commit()

    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="us2-as3",
    )
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_tmux_ok,
        register_fn=_register_into_agents(conn),
        log_attach_fn=_log_ok,
    )

    rows = conn.execute("SELECT origin, COUNT(*) FROM agents GROUP BY origin").fetchall()
    by_origin = dict(rows)
    assert by_origin["managed"] == 3
    assert by_origin["adopted"] == 1
    # The adopted agent's row is unchanged by the managed spawn.
    adopted_row = conn.execute(
        "SELECT agent_id FROM agents WHERE origin = 'adopted'"
    ).fetchone()
    assert adopted_row[0] == "agent-adopted-001"


# ─── FR-015 per-pane FIFO + per-layout FIFO ordering ────────────────────


def test_fr015_per_pane_fifo_ordering(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Every event for a given ``pane_id`` MUST appear in non-decreasing
    sequence order. (Per FR-015 the sequence counter is per-scope; the
    cross-pane order is best-effort timestamp.)"""
    events: list[dict[str, Any]] = []
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="us2-fifo-pane",
        event_emitter=events.append,
    )
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_tmux_ok,
        register_fn=_register_into_agents(conn),
        log_attach_fn=_log_ok,
        event_emitter=events.append,
    )

    # Group by pane_id (skipping layout-scoped events with pane_id=None).
    by_pane: dict[str, list[int]] = {}
    for e in events:
        pid = e.get("pane_id")
        if pid is None:
            continue
        by_pane.setdefault(pid, []).append(e["sequence"])

    for pid, seqs in by_pane.items():
        assert seqs == sorted(seqs), (
            f"Per-pane FIFO violated for {pid}: sequence list {seqs} is not "
            f"monotonically non-decreasing"
        )


def test_fr015_per_layout_fifo_ordering(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Every layout-scoped event for a given ``layout_id`` MUST appear
    in non-decreasing sequence order (FR-015)."""
    events: list[dict[str, Any]] = []
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="us2-fifo-layout",
        event_emitter=events.append,
    )
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_tmux_ok,
        register_fn=_register_into_agents(conn),
        log_attach_fn=_log_ok,
        event_emitter=events.append,
    )

    # Layout-scoped events have layout_id set and pane_id=None.
    layout_event_seqs = [
        e["sequence"] for e in events
        if e.get("layout_id") == result.layout_id and e.get("pane_id") is None
    ]
    assert layout_event_seqs == sorted(layout_event_seqs)
    # We expect at least LAYOUT_CREATED (sync, sequence=0) and
    # LAYOUT_STATE_CHANGED (bg, sequence=1).
    assert len(layout_event_seqs) >= 2


# ─── FR-021 redaction policy — current "absence" form (N35) ────────────


def test_fr021_no_env_argv_working_dir_field_in_any_event_payload(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """Per research §R11's "Payload schema reconciliation with FR-021"
    note (N35), no current event payload carries the diagnostic fields
    FR-021's redaction policy guards: ``env``, ``argv``, ``working_dir``.
    This is the "absence form" of FR-021 compliance — if there's nothing
    to redact, the policy is trivially satisfied.

    When a later feature adds these fields to a failure event payload,
    this assertion tightens to per-key redaction:
    - ``env`` keys matching ``*TOKEN*`` / ``*SECRET*`` / ``*KEY*`` /
      ``*PASSWORD*`` (case-insensitive, substring) MUST have values
      replaced by ``<redacted>``.
    - Other ``env`` keys MUST appear unredacted.
    - ``argv`` and ``working_dir`` MUST appear unredacted.

    The marker-token + token-shaped FEAT-013-internal identifiers (e.g.
    ``marker_token`` in PANE_PENDING_MARKER_SET) are NOT env-var keys
    and remain in scope of operator visibility — they're UUID-like
    correlation handles, not secrets.
    """
    events: list[dict[str, Any]] = []
    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="us2-redaction",
        event_emitter=events.append,
    )
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_tmux_ok,
        register_fn=_register_into_agents(conn),
        log_attach_fn=_log_ok,
        event_emitter=events.append,
    )

    # FR-021-guarded fields: env, argv, working_dir. Absent today.
    fr021_fields = {"env", "argv", "working_dir"}
    for e in events:
        payload = e.get("payload", {})
        present = fr021_fields & set(payload.keys())
        assert present == set(), (
            f"Event {e['event_type']!r} unexpectedly carries FR-021-guarded "
            f"field(s) {present}; if a later feature adds these, tighten this "
            f"test to assert the redaction policy (TOKEN/SECRET/KEY/PASSWORD "
            f"substring keys → <redacted>; others + argv + working_dir preserved)"
        )


# ─── End-to-end shape via M3 handler ────────────────────────────────────


def test_us2_managed_layout_detail_surfaces_ready_panes_with_origin_managed(
    conn: sqlite3.Connection, serializer: ContainerSerializer
) -> None:
    """After the spawn pipeline completes, the M3 ``app.managed_layout_detail``
    handler returns the layout in ``ready`` state with all 3 panes carrying
    ``origin = "managed"`` and a populated ``agent_id`` (FR-008 same-
    surfaces guarantee viewed through the M3 contract shape).
    """
    from types import SimpleNamespace

    result = create_layout(
        conn=conn, serializer=serializer,
        container_id="bench-alpha", template_name="1m+2s",
        tmux_session_name="us2-m3",
    )
    spawn_layout_in_background(
        result.layout_id,
        conn=conn, serializer=serializer,
        tmux_spawn_fn=_tmux_ok,
        register_fn=_register_into_agents(conn),
        log_attach_fn=_log_ok,
    )

    # Force the host-only gate to pass — same fixture pattern as
    # tests/contract/test_managed_dispatch.py.
    import os
    os.environ["AGENTTOWER_TEST_FORCE_HOST_PEER"] = "1"
    try:
        from agenttower.socket_api.methods import _set_request_peer_context
        _set_request_peer_context(peer_pid=os.getpid())
        ctx = SimpleNamespace(state_conn=conn, managed_serializer=serializer)
        resp = app_managed_layout_detail(ctx, {"layout_id": result.layout_id}, 1000)
        assert resp["ok"] is True
        result_payload = resp["result"]
        assert result_payload["state"] == "ready"
        assert result_payload["origin"] == "managed"
        assert len(result_payload["panes"]) == 3
        for p in result_payload["panes"]:
            assert p["state"] == "ready"
            assert p["origin"] == "managed"
            assert p["agent_id"] is not None
    finally:
        os.environ.pop("AGENTTOWER_TEST_FORCE_HOST_PEER", None)
        from agenttower.socket_api.methods import _clear_request_peer_context
        _clear_request_peer_context()
