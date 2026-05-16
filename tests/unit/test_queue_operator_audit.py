"""T071 — Operator-action audit emission (FR-046 / FR-031–FR-035).

Asserts that :class:`QueueService.approve` / :meth:`.delay` /
:meth:`.cancel` emit one JSONL audit row each with:

* The correct ``event_type`` (``queue_message_approved`` /
  ``queue_message_delayed`` / ``queue_message_canceled``).
* The operator's identity in the ``operator`` field — agent_id for
  bench-container callers, ``host-operator`` sentinel for host callers
  (Group-A walk Q8 / R-005).
* The block_reason carried on ``queue_message_approved`` (FR-033 — the
  operator overrode the original block_reason).

These tests instantiate the production :class:`QueueService` directly
(no daemon process), wired against an in-memory v7 SQLite DB and a real
:class:`QueueAuditWriter` so the audit dual-write actually runs.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from agenttower.routing.audit_writer import QueueAuditWriter
from agenttower.routing.dao import (
    DaemonStateDao,
    MessageQueueDao,
    QueueListFilter,
)
from agenttower.routing.kill_switch import RoutingFlagService
from agenttower.routing.service import QueueService
from agenttower.state import schema


_HOST_OPERATOR = "host-operator"

_SENDER = {
    "agent_id": "agt_aaaaaa111111",
    "label": "queen",
    "role": "master",
    "capability": "codex",
}
_TARGET = {
    "agent_id": "agt_bbbbbb222222",
    "label": "worker-1",
    "role": "slave",
    "capability": "codex",
    "container_id": "cont_xyz",
    "pane_id": "%1",
}


def _open_v7(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(db, check_same_thread=False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (7)")
    for v in (2, 3, 4, 5, 6, 7):
        schema._MIGRATIONS[v](conn)
    conn.commit()
    return conn


class _NullAgentsLookup:
    def get_agent_by_id(self, agent_id: str) -> None:
        return None

    def find_agents_by_label(self, label: str, *, only_active: bool = True) -> list:
        return []


class _NullContainerPaneLookup:
    def is_container_active(self, container_id: str) -> bool:
        return True

    def is_pane_resolvable(self, container_id: str, pane_id: str) -> bool:
        return True


def _seed_row(
    dao: MessageQueueDao, *, message_id: str, state: str,
    block_reason: str | None = None,
) -> None:
    """Seed one row in the documented state. Uses the DAO's insert
    helpers so the SQLite CHECK constraints are honored."""
    ts = "2026-05-12T00:00:00.000Z"
    if state == "queued":
        dao.insert_queued(
            message_id=message_id, sender=_SENDER, target=_TARGET,
            envelope_body=b"hi", envelope_body_sha256="a" * 64,
            envelope_size_bytes=64, enqueued_at=ts,
        )
    elif state == "blocked":
        dao.insert_blocked(
            message_id=message_id, sender=_SENDER, target=_TARGET,
            envelope_body=b"hi", envelope_body_sha256="a" * 64,
            envelope_size_bytes=64, enqueued_at=ts,
            block_reason=block_reason or "target_not_active",
        )
    else:
        raise ValueError(f"unsupported seed state {state}")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().strip().split("\n") if line]


def _make_service(tmp_path: Path) -> tuple[QueueService, MessageQueueDao, Path]:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    state_dao = DaemonStateDao(conn)
    routing = RoutingFlagService(state_dao)
    jsonl = tmp_path / "events.jsonl"
    audit = QueueAuditWriter(conn, jsonl)
    service = QueueService(
        dao=dao,
        routing_flag=routing,
        agents_lookup=_NullAgentsLookup(),
        container_pane_lookup=_NullContainerPaneLookup(),
        audit_writer=audit,
    )
    return service, dao, jsonl


# ──────────────────────────────────────────────────────────────────────
# approve → queue_message_approved + operator + block_reason carry
# ──────────────────────────────────────────────────────────────────────


def test_approve_emits_queue_message_approved_with_host_operator(
    tmp_path: Path,
) -> None:
    service, dao, jsonl = _make_service(tmp_path)
    msg_id = "11111111-2222-4333-8444-555555555555"
    _seed_row(dao, message_id=msg_id, state="blocked", block_reason="target_not_active")

    service.approve(msg_id, operator=_HOST_OPERATOR)

    records = _read_jsonl(jsonl)
    # Two rows: original blocked-enqueue + the approve transition.
    approved = [r for r in records if r["event_type"] == "queue_message_approved"]
    assert len(approved) == 1
    audit = approved[0]
    assert audit["operator"] == _HOST_OPERATOR
    # FR-033: the audit carries the original block_reason for the
    # operator's audit trail. The transition verb is encoded in
    # ``event_type`` (queue_message_approved); ``to_state`` is the
    # resulting queue state, which is ``queued`` because the row is
    # now eligible for the worker again (see audit_writer docstring).
    assert audit["from_state"] == "blocked"
    assert audit["to_state"] == "queued"
    assert audit["reason"] == "target_not_active"


def test_approve_emits_audit_with_bench_caller_agent_id(tmp_path: Path) -> None:
    service, dao, jsonl = _make_service(tmp_path)
    msg_id = "11111111-2222-4333-8444-555555555555"
    _seed_row(dao, message_id=msg_id, state="blocked", block_reason="target_not_active")

    bench_caller = "agt_cccccc333333"
    service.approve(msg_id, operator=bench_caller)

    records = _read_jsonl(jsonl)
    approved = [r for r in records if r["event_type"] == "queue_message_approved"]
    assert len(approved) == 1
    assert approved[0]["operator"] == bench_caller


# ──────────────────────────────────────────────────────────────────────
# delay → queue_message_delayed + operator + operator_delayed reason
# ──────────────────────────────────────────────────────────────────────


def test_delay_emits_queue_message_delayed_with_operator_delayed_reason(
    tmp_path: Path,
) -> None:
    service, dao, jsonl = _make_service(tmp_path)
    msg_id = "11111111-2222-4333-8444-555555555555"
    _seed_row(dao, message_id=msg_id, state="queued")

    service.delay(msg_id, operator=_HOST_OPERATOR)

    records = _read_jsonl(jsonl)
    delayed = [r for r in records if r["event_type"] == "queue_message_delayed"]
    assert len(delayed) == 1
    assert delayed[0]["operator"] == _HOST_OPERATOR
    assert delayed[0]["reason"] == "operator_delayed"
    assert delayed[0]["from_state"] == "queued"
    # The transition verb is encoded in ``event_type``
    # (queue_message_delayed); the resulting queue state is
    # ``blocked`` (the row is no longer eligible for the worker).
    assert delayed[0]["to_state"] == "blocked"


# ──────────────────────────────────────────────────────────────────────
# cancel → queue_message_canceled + operator (no reason field)
# ──────────────────────────────────────────────────────────────────────


def test_cancel_emits_queue_message_canceled_with_host_operator(
    tmp_path: Path,
) -> None:
    service, dao, jsonl = _make_service(tmp_path)
    msg_id = "11111111-2222-4333-8444-555555555555"
    _seed_row(dao, message_id=msg_id, state="queued")

    service.cancel(msg_id, operator=_HOST_OPERATOR)

    records = _read_jsonl(jsonl)
    canceled = [r for r in records if r["event_type"] == "queue_message_canceled"]
    assert len(canceled) == 1
    audit = canceled[0]
    assert audit["operator"] == _HOST_OPERATOR
    assert audit["to_state"] == "canceled"
    # Cancel has no reason carried in the audit (data-model §7).
    assert audit.get("reason") is None


def test_cancel_emits_audit_for_bench_caller_agent_id(tmp_path: Path) -> None:
    service, dao, jsonl = _make_service(tmp_path)
    msg_id = "11111111-2222-4333-8444-555555555555"
    _seed_row(dao, message_id=msg_id, state="queued")

    bench_caller = "agt_cccccc333333"
    service.cancel(msg_id, operator=bench_caller)

    records = _read_jsonl(jsonl)
    canceled = [r for r in records if r["event_type"] == "queue_message_canceled"]
    assert len(canceled) == 1
    assert canceled[0]["operator"] == bench_caller


# ──────────────────────────────────────────────────────────────────────
# Operator audit lands AFTER the SQLite state transition commits
# (FR-046 dual-write ordering)
# ──────────────────────────────────────────────────────────────────────


def test_approve_audit_lands_after_sqlite_transition(tmp_path: Path) -> None:
    """The audit emit is invoked AFTER the DAO's transition commits;
    the row's state at audit-emit time reflects the new state. We
    verify by reading the row back through the DAO immediately after
    the service call and confirming both the row state AND the audit
    line agree."""
    service, dao, jsonl = _make_service(tmp_path)
    msg_id = "11111111-2222-4333-8444-555555555555"
    _seed_row(dao, message_id=msg_id, state="blocked", block_reason="target_not_active")

    service.approve(msg_id, operator=_HOST_OPERATOR)

    row = dao.get_row_by_id(msg_id)
    assert row is not None
    assert row.state == "queued"  # blocked → queued
    audit = next(
        r for r in _read_jsonl(jsonl)
        if r["event_type"] == "queue_message_approved"
    )
    assert audit["message_id"] == msg_id
