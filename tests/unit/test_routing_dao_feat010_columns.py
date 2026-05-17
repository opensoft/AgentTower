"""T010 — round-trip tests for the FEAT-010 message_queue extension.

Covers the three columns added by schema v8:
- ``origin`` (TEXT NOT NULL DEFAULT 'direct')
- ``route_id`` (TEXT)
- ``event_id`` (INTEGER)

Exercises insert_queued and insert_blocked under both code paths:
- Default-args call (existing FEAT-009 direct-send sites) → row has
  origin='direct', route_id=None, event_id=None.
- Explicit route-tagged call (future FEAT-010 worker site) → row has
  origin='route', non-NULL route_id, non-NULL event_id.

Also verifies that the schema v8 partial UNIQUE index on
``(route_id, event_id) WHERE origin='route'`` fires on duplicate
route-tagged inserts.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from agenttower.routing.dao import MessageQueueDao
from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Fixture — fresh DB at schema head (v8)
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def dao(tmp_path: Path) -> MessageQueueDao:
    db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute(
        "INSERT INTO schema_version (version) VALUES (?)",
        (schema.CURRENT_SCHEMA_VERSION,),
    )
    for v in range(2, schema.CURRENT_SCHEMA_VERSION + 1):
        schema._MIGRATIONS[v](conn)
    conn.commit()
    return MessageQueueDao(conn, tx_lock=threading.Lock())


_SENDER = {
    "agent_id": "agt_master00001",
    "label": "primary",
    "role": "master",
    "capability": "plan",
}
_TARGET = {
    "agent_id": "agt_slave000001",
    "label": "worker",
    "role": "slave",
    "capability": "implement",
    "container_id": "c0123456789a",
    "pane_id": "%0",
}


def _insert_queued(
    dao: MessageQueueDao,
    *,
    message_id: str = "msg_direct_001",
    origin: str = "direct",
    route_id: str | None = None,
    event_id: int | None = None,
    enqueued_at: str = "2026-05-17T00:00:00.000Z",
) -> None:
    dao.insert_queued(
        message_id=message_id,
        sender=_SENDER,
        target=_TARGET,
        envelope_body=b"hello",
        envelope_body_sha256="0" * 64,
        envelope_size_bytes=5,
        enqueued_at=enqueued_at,
        origin=origin,
        route_id=route_id,
        event_id=event_id,
    )


def _insert_blocked(
    dao: MessageQueueDao,
    *,
    message_id: str = "msg_blocked_001",
    origin: str = "direct",
    route_id: str | None = None,
    event_id: int | None = None,
    block_reason: str = "kill_switch_off",
) -> None:
    dao.insert_blocked(
        message_id=message_id,
        sender=_SENDER,
        target=_TARGET,
        envelope_body=b"hello",
        envelope_body_sha256="0" * 64,
        envelope_size_bytes=5,
        enqueued_at="2026-05-17T00:00:00.000Z",
        block_reason=block_reason,
        origin=origin,
        route_id=route_id,
        event_id=event_id,
    )


# ──────────────────────────────────────────────────────────────────────
# insert_queued: default args = direct-send path
# ──────────────────────────────────────────────────────────────────────


def test_insert_queued_default_args_yields_direct_origin(
    dao: MessageQueueDao,
) -> None:
    _insert_queued(dao)
    row = dao.get_row_by_id("msg_direct_001")
    assert row is not None
    assert row.origin == "direct"
    assert row.route_id is None
    assert row.event_id is None


def test_insert_queued_with_route_tags_yields_route_origin(
    dao: MessageQueueDao,
) -> None:
    _insert_queued(
        dao,
        message_id="msg_route_001",
        origin="route",
        route_id="11111111-2222-4333-8444-555555555555",
        event_id=42,
    )
    row = dao.get_row_by_id("msg_route_001")
    assert row is not None
    assert row.origin == "route"
    assert row.route_id == "11111111-2222-4333-8444-555555555555"
    assert row.event_id == 42


# ──────────────────────────────────────────────────────────────────────
# insert_blocked: default args = direct-send blocked path
# ──────────────────────────────────────────────────────────────────────


def test_insert_blocked_default_args_yields_direct_origin(
    dao: MessageQueueDao,
) -> None:
    _insert_blocked(dao)
    row = dao.get_row_by_id("msg_blocked_001")
    assert row is not None
    assert row.origin == "direct"
    assert row.route_id is None
    assert row.event_id is None


def test_insert_blocked_with_route_tags_yields_route_origin(
    dao: MessageQueueDao,
) -> None:
    """FEAT-010's worker enqueues route-generated rows through this path
    when the kill switch is off (Story 5 #1)."""
    _insert_blocked(
        dao,
        message_id="msg_route_blocked",
        origin="route",
        route_id="22222222-3333-4444-8555-666666666666",
        event_id=99,
        block_reason="kill_switch_off",
    )
    row = dao.get_row_by_id("msg_route_blocked")
    assert row is not None
    assert row.origin == "route"
    assert row.route_id == "22222222-3333-4444-8555-666666666666"
    assert row.event_id == 99
    assert row.block_reason == "kill_switch_off"


# ──────────────────────────────────────────────────────────────────────
# Partial UNIQUE index fires on duplicate route-tagged insert
# ──────────────────────────────────────────────────────────────────────


def test_partial_unique_rejects_duplicate_route_event(
    dao: MessageQueueDao,
) -> None:
    """FR-030 defense-in-depth: even if a logic bug attempted a second
    insert for the same (route_id, event_id), SQLite rejects it."""
    _insert_queued(
        dao,
        message_id="msg_route_first",
        origin="route",
        route_id="aaaaaaaa-1111-4222-8333-444444444444",
        event_id=10,
    )
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _insert_queued(
            dao,
            message_id="msg_route_second",
            origin="route",
            route_id="aaaaaaaa-1111-4222-8333-444444444444",
            event_id=10,
        )


def test_partial_unique_ignores_direct_rows(dao: MessageQueueDao) -> None:
    """Direct-send rows are excluded from the constraint by the
    ``WHERE origin='route'`` predicate; multiple direct rows always
    coexist freely."""
    for i in range(3):
        _insert_queued(dao, message_id=f"msg_direct_{i}")
    count = dao.get_row_by_id("msg_direct_0") is not None
    assert count is True


# ──────────────────────────────────────────────────────────────────────
# Cross-origin mix: same route_id with different event_id is fine
# ──────────────────────────────────────────────────────────────────────


def test_same_route_different_event_ids_coexist(dao: MessageQueueDao) -> None:
    """Two events fired against the same route MUST produce two queue
    rows (FR-015 fan-out / per-event-cursor semantics)."""
    route = "11111111-2222-4333-8444-555555555555"
    _insert_queued(dao, message_id="msg_e1", origin="route", route_id=route, event_id=100)
    _insert_queued(dao, message_id="msg_e2", origin="route", route_id=route, event_id=101)
    _insert_queued(dao, message_id="msg_e3", origin="route", route_id=route, event_id=102)
    assert dao.get_row_by_id("msg_e1").event_id == 100
    assert dao.get_row_by_id("msg_e2").event_id == 101
    assert dao.get_row_by_id("msg_e3").event_id == 102


def test_same_event_different_routes_coexist(dao: MessageQueueDao) -> None:
    """Two routes firing on the same event MUST produce two queue rows
    (FR-015 fan-out across routes)."""
    _insert_queued(
        dao, message_id="msg_r1", origin="route",
        route_id="11111111-1111-4111-8111-111111111111", event_id=50,
    )
    _insert_queued(
        dao, message_id="msg_r2", origin="route",
        route_id="22222222-2222-4222-8222-222222222222", event_id=50,
    )
    assert dao.get_row_by_id("msg_r1").route_id.startswith("1111")
    assert dao.get_row_by_id("msg_r2").route_id.startswith("2222")


# ──────────────────────────────────────────────────────────────────────
# QueueRow defaults (backward compat for in-process constructions)
# ──────────────────────────────────────────────────────────────────────


def test_queue_row_dataclass_defaults_preserve_pre_feat010_call_sites() -> None:
    """Pre-FEAT-010 code that builds a QueueRow without the new fields
    MUST continue to work — the three new fields have sensible defaults
    (origin='direct', route_id=None, event_id=None)."""
    from agenttower.routing.dao import QueueRow

    row = QueueRow(
        message_id="msg_x", state="queued",
        block_reason=None, failure_reason=None,
        sender_agent_id="agt_a", sender_label="a", sender_role="master",
        sender_capability=None,
        target_agent_id="agt_b", target_label="b", target_role="slave",
        target_capability=None,
        target_container_id="c", target_pane_id="p",
        envelope_body_sha256="x", envelope_size_bytes=1,
        enqueued_at="t", delivery_attempt_started_at=None,
        delivered_at=None, failed_at=None, canceled_at=None,
        last_updated_at="t",
        operator_action=None, operator_action_at=None, operator_action_by=None,
    )
    assert row.origin == "direct"
    assert row.route_id is None
    assert row.event_id is None
