"""T041 — FEAT-010 ``queue --origin`` filter contract tests.

Covers the FEAT-010 extension to FEAT-009's ``queue`` CLI:

* ``agenttower queue --origin direct|route`` is accepted by argparse.
* ``agenttower queue --origin <other>`` is rejected by argparse (exit 2).
* JSON output of the underlying ``queue.list`` socket method includes
  ``origin`` / ``route_id`` / ``event_id`` fields on every row
  (FR-029 / FR-033).
* The daemon-side dispatcher rejects unknown origin values with
  ``queue_origin_invalid``.
* The DAO-level filter restricts rows correctly when set.

The actual socket round-trip is covered via the DISPATCH harness
(matches the FEAT-010 socket-contract pattern from T027).
"""

from __future__ import annotations

import argparse
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agenttower.cli import _build_parser
from agenttower.routing.dao import MessageQueueDao, QueueListFilter
from agenttower.socket_api.methods import DISPATCH, DaemonContext
from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# argparse layer — CLI-side validation
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def parser() -> argparse.ArgumentParser:
    return _build_parser()


@pytest.mark.parametrize("origin", ["direct", "route"])
def test_queue_origin_valid_choices_parse(
    parser: argparse.ArgumentParser, origin: str,
) -> None:
    args = parser.parse_args(["queue", "--origin", origin])
    assert args.origin == origin


def test_queue_origin_absent_defaults_to_none(
    parser: argparse.ArgumentParser,
) -> None:
    args = parser.parse_args(["queue"])
    assert args.origin is None


def test_queue_origin_invalid_value_rejected_by_argparse(
    parser: argparse.ArgumentParser,
) -> None:
    """argparse closed-set guard exits with code 2 before any socket
    round-trip — protects operators from typos."""
    with pytest.raises(SystemExit) as info:
        parser.parse_args(["queue", "--origin", "not_an_origin"])
    assert info.value.code == 2


# ──────────────────────────────────────────────────────────────────────
# DAO-level filter
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


def _seed_two_origins(dao: MessageQueueDao) -> None:
    dao.insert_queued(
        message_id="msg_direct",
        sender=_SENDER, target=_TARGET,
        envelope_body=b"d", envelope_body_sha256="0" * 64,
        envelope_size_bytes=1,
        enqueued_at="2026-05-17T00:00:00.000Z",
    )
    dao.insert_queued(
        message_id="msg_route",
        sender=_SENDER, target=_TARGET,
        envelope_body=b"r", envelope_body_sha256="0" * 64,
        envelope_size_bytes=1,
        enqueued_at="2026-05-17T00:00:01.000Z",
        origin="route",
        route_id="11111111-2222-4333-8444-555555555555",
        event_id=42,
    )


def test_dao_filter_origin_none_returns_both(dao: MessageQueueDao) -> None:
    _seed_two_origins(dao)
    rows = dao.list_rows(QueueListFilter(origin=None))
    assert {r.message_id for r in rows} == {"msg_direct", "msg_route"}


def test_dao_filter_origin_direct(dao: MessageQueueDao) -> None:
    _seed_two_origins(dao)
    rows = dao.list_rows(QueueListFilter(origin="direct"))
    assert [r.message_id for r in rows] == ["msg_direct"]


def test_dao_filter_origin_route(dao: MessageQueueDao) -> None:
    _seed_two_origins(dao)
    rows = dao.list_rows(QueueListFilter(origin="route"))
    assert [r.message_id for r in rows] == ["msg_route"]
    assert rows[0].route_id == "11111111-2222-4333-8444-555555555555"
    assert rows[0].event_id == 42


def test_dao_filter_origin_invalid_raises_value_error(
    dao: MessageQueueDao,
) -> None:
    _seed_two_origins(dao)
    with pytest.raises(ValueError, match="origin filter"):
        dao.list_rows(QueueListFilter(origin="not_an_origin"))


# ──────────────────────────────────────────────────────────────────────
# Socket-dispatch layer — queue.list with origin param
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _StubQueueService:
    """Minimal QueueService surface so the queue.list handler can run
    without the full FEAT-009 stack."""

    rows: list[Any] = field(default_factory=list)
    last_filter: QueueListFilter | None = None

    def list_rows(self, filters: QueueListFilter) -> list[Any]:
        self.last_filter = filters
        return self.rows

    def read_envelope_excerpt(self, message_id: str) -> str:
        return ""


class _StubRoutingFlag:
    """Inert kill-switch flag — queue.list reads no routing state."""


@pytest.fixture
def ctx_with_stub_queue(tmp_path: Path) -> tuple[DaemonContext, _StubQueueService]:
    stub = _StubQueueService()
    ctx = DaemonContext(
        pid=1,
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "sock",
        state_path=tmp_path,
        daemon_version="test",
        queue_service=stub,
        # _routing_services_or_error checks both — the queue.list
        # handler doesn't actually consume the routing flag but
        # rejects unwired contexts to surface boot-order bugs.
        routing_flag_service=_StubRoutingFlag(),
    )
    return ctx, stub


def test_queue_list_socket_passes_origin_to_filter(
    ctx_with_stub_queue,
) -> None:
    ctx, stub = ctx_with_stub_queue
    DISPATCH["queue.list"](ctx, {"origin": "route"})
    assert stub.last_filter is not None
    assert stub.last_filter.origin == "route"


def test_queue_list_socket_rejects_invalid_origin(
    ctx_with_stub_queue,
) -> None:
    ctx, _stub = ctx_with_stub_queue
    resp = DISPATCH["queue.list"](ctx, {"origin": "not_an_origin"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "queue_origin_invalid"


def test_queue_list_socket_origin_omitted_passes_none(
    ctx_with_stub_queue,
) -> None:
    ctx, stub = ctx_with_stub_queue
    DISPATCH["queue.list"](ctx, {})
    assert stub.last_filter is not None
    assert stub.last_filter.origin is None


# ──────────────────────────────────────────────────────────────────────
# Wire shape — every row carries origin/route_id/event_id (FR-029)
# ──────────────────────────────────────────────────────────────────────


def test_queue_row_payload_includes_origin_fields(
    ctx_with_stub_queue,
) -> None:
    from agenttower.routing.dao import QueueRow

    ctx, stub = ctx_with_stub_queue
    stub.rows = [
        QueueRow(
            message_id="msg_direct",
            state="queued",
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
        ),
    ]
    resp = DISPATCH["queue.list"](ctx, {})
    assert resp["ok"] is True
    row_payload = resp["result"]["rows"][0]
    # FEAT-010 fields are unconditionally present on every row.
    assert "origin" in row_payload
    assert "route_id" in row_payload
    assert "event_id" in row_payload
    assert row_payload["origin"] == "direct"
    assert row_payload["route_id"] is None
    assert row_payload["event_id"] is None
