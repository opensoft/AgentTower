"""T029 — FEAT-009 ``MessageQueueDao`` + ``DaemonStateDao`` tests.

Covers:

* All four insert / transition / read methods on a real (in-memory)
  SQLite DB initialized via the v7 migration.
* :func:`with_lock_retry` exhaustion path → :class:`SqliteLockConflict`
  (Group-A walk Q5).
* :meth:`MessageQueueDao.recover_in_flight_rows` for FR-040.
* :meth:`MessageQueueDao.list_rows` filter combinations.
* :class:`DaemonStateDao` read + write.

The exhaustive state-machine transition matrix is in
``test_routing_state_machine.py`` (T030).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agenttower.routing.dao import (
    DaemonStateDao,
    MessageQueueDao,
    QueueListFilter,
    QueueRow,
    with_lock_retry,
)
from agenttower.routing.errors import (
    QueueServiceError,
    SqliteLockConflict,
)
from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _open_v7(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh v7 DB and return a connection."""
    db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (6)")
    for v in (2, 3, 4, 5, 6):
        schema._MIGRATIONS[v](conn)
    schema._apply_migration_v7(conn)
    conn.commit()
    return conn


def _insert_queued_sample(
    dao: MessageQueueDao,
    *,
    message_id: str = "12345678-1234-4234-8234-123456789012",
    target_agent_id: str = "agt_bbbbbb222222",
    target_label: str = "worker-1",
    sender_agent_id: str = "agt_aaaaaa111111",
    enqueued_at: str = "2026-05-12T00:00:00.000Z",
) -> None:
    dao.insert_queued(
        message_id=message_id,
        sender={
            "agent_id": sender_agent_id, "label": "queen",
            "role": "master", "capability": "plan",
        },
        target={
            "agent_id": target_agent_id, "label": target_label,
            "role": "slave", "capability": "implement",
            "container_id": "c0123456789a", "pane_id": "%0",
        },
        envelope_body=b"do thing",
        envelope_body_sha256="0" * 64,
        envelope_size_bytes=128,
        enqueued_at=enqueued_at,
    )


# ──────────────────────────────────────────────────────────────────────
# Insert paths
# ──────────────────────────────────────────────────────────────────────


def test_insert_queued_creates_row_in_queued_state(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    row = dao.get_row_by_id("12345678-1234-4234-8234-123456789012")
    assert row is not None
    assert row.state == "queued"
    assert row.block_reason is None
    assert row.failure_reason is None
    assert row.sender_agent_id == "agt_aaaaaa111111"
    assert row.target_agent_id == "agt_bbbbbb222222"
    assert row.envelope_size_bytes == 128


def test_insert_blocked_creates_row_with_block_reason(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    dao.insert_blocked(
        message_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        sender={"agent_id": "agt_aaaaaa111111", "label": "q",
                "role": "master", "capability": None},
        target={"agent_id": "agt_bbbbbb222222", "label": "w",
                "role": "slave", "capability": None,
                "container_id": "c0", "pane_id": "%0"},
        envelope_body=b"x", envelope_body_sha256="0" * 64,
        envelope_size_bytes=10,
        enqueued_at="2026-05-12T00:00:00.000Z",
        block_reason="kill_switch_off",
    )
    row = dao.get_row_by_id("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    assert row is not None
    assert row.state == "blocked"
    assert row.block_reason == "kill_switch_off"


# ──────────────────────────────────────────────────────────────────────
# read_envelope_bytes (FR-012a)
# ──────────────────────────────────────────────────────────────────────


def test_read_envelope_bytes_returns_raw_blob(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    body = b"line one\nline two\twith tab"
    dao.insert_queued(
        message_id="11111111-1111-4111-8111-111111111111",
        sender={"agent_id": "agt_aaaaaa111111", "label": "q",
                "role": "master", "capability": None},
        target={"agent_id": "agt_bbbbbb222222", "label": "w",
                "role": "slave", "capability": None,
                "container_id": "c0", "pane_id": "%0"},
        envelope_body=body, envelope_body_sha256="0" * 64,
        envelope_size_bytes=len(body),
        enqueued_at="2026-05-12T00:00:00.000Z",
    )
    out = dao.read_envelope_bytes("11111111-1111-4111-8111-111111111111")
    assert out == body
    assert isinstance(out, bytes)


def test_read_envelope_bytes_missing_row_raises_message_id_not_found(
    tmp_path: Path,
) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    with pytest.raises(QueueServiceError) as info:
        dao.read_envelope_bytes("nonexistent")
    assert info.value.code == "message_id_not_found"


# ──────────────────────────────────────────────────────────────────────
# pick_next_ready_row — FR-031 ordering
# ──────────────────────────────────────────────────────────────────────


def test_pick_next_ready_row_returns_oldest_queued(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    # Insert 3 queued rows out of order.
    _insert_queued_sample(
        dao, message_id="cc000000-0000-4000-8000-000000000003",
        enqueued_at="2026-05-12T00:03:00.000Z",
    )
    _insert_queued_sample(
        dao, message_id="aa000000-0000-4000-8000-000000000001",
        enqueued_at="2026-05-12T00:01:00.000Z",
    )
    _insert_queued_sample(
        dao, message_id="bb000000-0000-4000-8000-000000000002",
        enqueued_at="2026-05-12T00:02:00.000Z",
    )
    picked = dao.pick_next_ready_row()
    assert picked is not None
    assert picked.message_id == "aa000000-0000-4000-8000-000000000001"


def test_pick_next_ready_row_tie_breaks_on_message_id(tmp_path: Path) -> None:
    """When two rows share the same enqueued_at, the lexically-lower
    message_id wins (FR-031 + Edge Cases tie-breaker)."""
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(
        dao, message_id="bb000000-0000-4000-8000-000000000000",
        enqueued_at="2026-05-12T00:00:00.000Z",
    )
    _insert_queued_sample(
        dao, message_id="aa000000-0000-4000-8000-000000000000",
        enqueued_at="2026-05-12T00:00:00.000Z",
    )
    picked = dao.pick_next_ready_row()
    assert picked.message_id == "aa000000-0000-4000-8000-000000000000"


def test_pick_next_ready_row_returns_none_when_empty(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    assert dao.pick_next_ready_row() is None


def test_pick_next_ready_row_skips_blocked(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    dao.insert_blocked(
        message_id="bb000000-0000-4000-8000-000000000000",
        sender={"agent_id": "agt_aaaaaa111111", "label": "q",
                "role": "master", "capability": None},
        target={"agent_id": "agt_bbbbbb222222", "label": "w",
                "role": "slave", "capability": None,
                "container_id": "c0", "pane_id": "%0"},
        envelope_body=b"x", envelope_body_sha256="0" * 64,
        envelope_size_bytes=10,
        enqueued_at="2026-05-12T00:00:00.000Z",
        block_reason="kill_switch_off",
    )
    assert dao.pick_next_ready_row() is None


# ──────────────────────────────────────────────────────────────────────
# Worker-side transitions — FR-041 / FR-042 / FR-043
# ──────────────────────────────────────────────────────────────────────


def test_stamp_then_delivered_happy_path(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    dao.stamp_delivery_attempt_started(
        "12345678-1234-4234-8234-123456789012", "2026-05-12T00:00:01.000Z"
    )
    row = dao.get_row_by_id("12345678-1234-4234-8234-123456789012")
    assert row.delivery_attempt_started_at == "2026-05-12T00:00:01.000Z"
    assert row.state == "queued"

    dao.transition_queued_to_delivered(
        "12345678-1234-4234-8234-123456789012", "2026-05-12T00:00:02.000Z"
    )
    row = dao.get_row_by_id("12345678-1234-4234-8234-123456789012")
    assert row.state == "delivered"
    assert row.delivered_at == "2026-05-12T00:00:02.000Z"
    assert row.failure_reason is None


def test_stamp_then_failed_with_failure_reason(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    dao.stamp_delivery_attempt_started(
        "12345678-1234-4234-8234-123456789012", "2026-05-12T00:00:01.000Z"
    )
    dao.transition_queued_to_failed(
        "12345678-1234-4234-8234-123456789012",
        "tmux_paste_failed",
        "2026-05-12T00:00:02.000Z",
    )
    row = dao.get_row_by_id("12345678-1234-4234-8234-123456789012")
    assert row.state == "failed"
    assert row.failure_reason == "tmux_paste_failed"
    assert row.failed_at == "2026-05-12T00:00:02.000Z"


def test_stamp_twice_raises_delivery_in_progress(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    dao.stamp_delivery_attempt_started(
        "12345678-1234-4234-8234-123456789012", "2026-05-12T00:00:01.000Z"
    )
    with pytest.raises(QueueServiceError) as info:
        dao.stamp_delivery_attempt_started(
            "12345678-1234-4234-8234-123456789012", "2026-05-12T00:00:02.000Z"
        )
    assert info.value.code == "delivery_in_progress"


def test_transition_to_delivered_without_stamp_raises(tmp_path: Path) -> None:
    """A row whose ``delivery_attempt_started_at`` is unset cannot
    transition to delivered."""
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    with pytest.raises(QueueServiceError) as info:
        dao.transition_queued_to_delivered(
            "12345678-1234-4234-8234-123456789012", "2026-05-12T00:00:02.000Z"
        )
    assert info.value.code == "message_id_not_found"


# ──────────────────────────────────────────────────────────────────────
# Pre-paste re-check failure (FR-025)
# ──────────────────────────────────────────────────────────────────────


def test_re_check_queued_to_blocked(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    dao.transition_queued_to_blocked_re_check(
        "12345678-1234-4234-8234-123456789012",
        "target_pane_missing",
        "2026-05-12T00:00:01.000Z",
    )
    row = dao.get_row_by_id("12345678-1234-4234-8234-123456789012")
    assert row.state == "blocked"
    assert row.block_reason == "target_pane_missing"
    assert row.delivery_attempt_started_at is None


def test_re_check_after_stamp_raises(tmp_path: Path) -> None:
    """Once ``delivery_attempt_started_at`` is set, the pre-paste re-check
    contract is violated — the row is past the gating point."""
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    dao.stamp_delivery_attempt_started(
        "12345678-1234-4234-8234-123456789012", "2026-05-12T00:00:01.000Z"
    )
    with pytest.raises(QueueServiceError):
        dao.transition_queued_to_blocked_re_check(
            "12345678-1234-4234-8234-123456789012",
            "target_pane_missing",
            "2026-05-12T00:00:02.000Z",
        )


# ──────────────────────────────────────────────────────────────────────
# Operator transitions — approve / delay / cancel
# ──────────────────────────────────────────────────────────────────────


def test_approve_blocked_to_queued(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    dao.insert_blocked(
        message_id="bb111111-1111-4111-8111-111111111111",
        sender={"agent_id": "agt_aaaaaa111111", "label": "q",
                "role": "master", "capability": None},
        target={"agent_id": "agt_bbbbbb222222", "label": "w",
                "role": "slave", "capability": None,
                "container_id": "c0", "pane_id": "%0"},
        envelope_body=b"x", envelope_body_sha256="0" * 64,
        envelope_size_bytes=10,
        enqueued_at="2026-05-12T00:00:00.000Z",
        block_reason="operator_delayed",
    )
    dao.transition_blocked_to_queued_approve(
        "bb111111-1111-4111-8111-111111111111",
        operator="host-operator",
        ts="2026-05-12T00:00:01.000Z",
    )
    row = dao.get_row_by_id("bb111111-1111-4111-8111-111111111111")
    assert row.state == "queued"
    assert row.block_reason is None  # cleared
    assert row.operator_action == "approved"
    assert row.operator_action_by == "host-operator"


def test_approve_queued_raises_approval_not_applicable(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    with pytest.raises(QueueServiceError) as info:
        dao.transition_blocked_to_queued_approve(
            "12345678-1234-4234-8234-123456789012",
            operator="host-operator",
            ts="2026-05-12T00:00:01.000Z",
        )
    assert info.value.code == "approval_not_applicable"


def test_delay_queued_to_blocked_operator_delayed(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    dao.transition_queued_to_blocked_delay(
        "12345678-1234-4234-8234-123456789012",
        operator="host-operator",
        ts="2026-05-12T00:00:01.000Z",
    )
    row = dao.get_row_by_id("12345678-1234-4234-8234-123456789012")
    assert row.state == "blocked"
    assert row.block_reason == "operator_delayed"
    assert row.operator_action == "delayed"


def test_delay_blocked_raises_delay_not_applicable(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    dao.insert_blocked(
        message_id="bb222222-2222-4222-8222-222222222222",
        sender={"agent_id": "agt_aaaaaa111111", "label": "q",
                "role": "master", "capability": None},
        target={"agent_id": "agt_bbbbbb222222", "label": "w",
                "role": "slave", "capability": None,
                "container_id": "c0", "pane_id": "%0"},
        envelope_body=b"x", envelope_body_sha256="0" * 64,
        envelope_size_bytes=10,
        enqueued_at="2026-05-12T00:00:00.000Z",
        block_reason="kill_switch_off",
    )
    with pytest.raises(QueueServiceError) as info:
        dao.transition_queued_to_blocked_delay(
            "bb222222-2222-4222-8222-222222222222",
            operator="host-operator",
            ts="2026-05-12T00:00:01.000Z",
        )
    assert info.value.code == "delay_not_applicable"


def test_cancel_queued_to_canceled(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    dao.transition_to_canceled(
        "12345678-1234-4234-8234-123456789012",
        operator="host-operator",
        ts="2026-05-12T00:00:01.000Z",
    )
    row = dao.get_row_by_id("12345678-1234-4234-8234-123456789012")
    assert row.state == "canceled"
    assert row.canceled_at == "2026-05-12T00:00:01.000Z"
    assert row.operator_action == "canceled"


def test_cancel_blocked_to_canceled(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    dao.insert_blocked(
        message_id="bb333333-3333-4333-8333-333333333333",
        sender={"agent_id": "agt_aaaaaa111111", "label": "q",
                "role": "master", "capability": None},
        target={"agent_id": "agt_bbbbbb222222", "label": "w",
                "role": "slave", "capability": None,
                "container_id": "c0", "pane_id": "%0"},
        envelope_body=b"x", envelope_body_sha256="0" * 64,
        envelope_size_bytes=10,
        enqueued_at="2026-05-12T00:00:00.000Z",
        block_reason="kill_switch_off",
    )
    dao.transition_to_canceled(
        "bb333333-3333-4333-8333-333333333333",
        operator="host-operator",
        ts="2026-05-12T00:00:01.000Z",
    )
    row = dao.get_row_by_id("bb333333-3333-4333-8333-333333333333")
    assert row.state == "canceled"


def test_cancel_terminal_raises_terminal_state_cannot_change(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    dao.stamp_delivery_attempt_started(
        "12345678-1234-4234-8234-123456789012", "2026-05-12T00:00:01.000Z"
    )
    dao.transition_queued_to_delivered(
        "12345678-1234-4234-8234-123456789012", "2026-05-12T00:00:02.000Z"
    )
    with pytest.raises(QueueServiceError) as info:
        dao.transition_to_canceled(
            "12345678-1234-4234-8234-123456789012",
            operator="host-operator",
            ts="2026-05-12T00:00:03.000Z",
        )
    assert info.value.code == "terminal_state_cannot_change"


def test_cancel_in_flight_raises_delivery_in_progress(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    dao.stamp_delivery_attempt_started(
        "12345678-1234-4234-8234-123456789012", "2026-05-12T00:00:01.000Z"
    )
    with pytest.raises(QueueServiceError) as info:
        dao.transition_to_canceled(
            "12345678-1234-4234-8234-123456789012",
            operator="host-operator",
            ts="2026-05-12T00:00:02.000Z",
        )
    assert info.value.code == "delivery_in_progress"


def test_cancel_unknown_message_id_raises(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    with pytest.raises(QueueServiceError) as info:
        dao.transition_to_canceled(
            "nonexistent", operator="host-operator", ts="2026-05-12T00:00:01.000Z"
        )
    assert info.value.code == "message_id_not_found"


# ──────────────────────────────────────────────────────────────────────
# FR-040 recovery
# ──────────────────────────────────────────────────────────────────────


def test_recover_in_flight_rows_transitions_only_in_flight(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    # Insert: one queued (no stamp), one in-flight (stamp set, no terminal),
    # one delivered, one canceled.
    _insert_queued_sample(
        dao, message_id="aa000000-0000-4000-8000-000000000001",
        enqueued_at="2026-05-12T00:00:00.000Z",
    )  # queued, no stamp
    _insert_queued_sample(
        dao, message_id="bb000000-0000-4000-8000-000000000002",
        enqueued_at="2026-05-12T00:00:00.000Z",
    )
    dao.stamp_delivery_attempt_started(
        "bb000000-0000-4000-8000-000000000002", "2026-05-12T00:00:01.000Z"
    )
    # bb is in-flight (stamp set, no terminal). Now create one delivered:
    _insert_queued_sample(
        dao, message_id="cc000000-0000-4000-8000-000000000003",
        enqueued_at="2026-05-12T00:00:00.000Z",
    )
    dao.stamp_delivery_attempt_started(
        "cc000000-0000-4000-8000-000000000003", "2026-05-12T00:00:01.000Z"
    )
    dao.transition_queued_to_delivered(
        "cc000000-0000-4000-8000-000000000003", "2026-05-12T00:00:02.000Z"
    )

    count = dao.recover_in_flight_rows("2026-05-12T00:01:00.000Z")
    assert count == 1

    aa = dao.get_row_by_id("aa000000-0000-4000-8000-000000000001")
    bb = dao.get_row_by_id("bb000000-0000-4000-8000-000000000002")
    cc = dao.get_row_by_id("cc000000-0000-4000-8000-000000000003")
    assert aa.state == "queued"  # untouched
    assert bb.state == "failed"
    assert bb.failure_reason == "attempt_interrupted"
    assert bb.failed_at == "2026-05-12T00:01:00.000Z"
    assert cc.state == "delivered"  # untouched


def test_recover_in_flight_rows_returns_zero_when_no_in_flight(
    tmp_path: Path,
) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao)
    count = dao.recover_in_flight_rows("2026-05-12T00:01:00.000Z")
    assert count == 0


# ──────────────────────────────────────────────────────────────────────
# list_rows filtering (FR-031)
# ──────────────────────────────────────────────────────────────────────


def test_list_rows_no_filters_returns_all(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(
        dao, message_id="aa000000-0000-4000-8000-000000000001",
        enqueued_at="2026-05-12T00:01:00.000Z",
    )
    _insert_queued_sample(
        dao, message_id="bb000000-0000-4000-8000-000000000002",
        enqueued_at="2026-05-12T00:02:00.000Z",
    )
    rows = dao.list_rows(QueueListFilter())
    assert len(rows) == 2
    # Ordering by enqueued_at ASC.
    assert rows[0].message_id == "aa000000-0000-4000-8000-000000000001"
    assert rows[1].message_id == "bb000000-0000-4000-8000-000000000002"


def test_list_rows_state_filter(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(dao, message_id="aa000000-0000-4000-8000-000000000001")
    dao.insert_blocked(
        message_id="bb000000-0000-4000-8000-000000000002",
        sender={"agent_id": "agt_aaaaaa111111", "label": "q",
                "role": "master", "capability": None},
        target={"agent_id": "agt_bbbbbb222222", "label": "w",
                "role": "slave", "capability": None,
                "container_id": "c0", "pane_id": "%0"},
        envelope_body=b"x", envelope_body_sha256="0" * 64,
        envelope_size_bytes=10,
        enqueued_at="2026-05-12T00:00:00.000Z",
        block_reason="kill_switch_off",
    )
    queued_only = dao.list_rows(QueueListFilter(state="queued"))
    assert len(queued_only) == 1
    assert queued_only[0].state == "queued"
    blocked_only = dao.list_rows(QueueListFilter(state="blocked"))
    assert len(blocked_only) == 1
    assert blocked_only[0].state == "blocked"


def test_list_rows_target_filter(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(
        dao, message_id="aa000000-0000-4000-8000-000000000001",
        target_agent_id="agt_bbbbbb222222",
    )
    _insert_queued_sample(
        dao, message_id="bb000000-0000-4000-8000-000000000002",
        target_agent_id="agt_cccccc333333",
    )
    rows = dao.list_rows(QueueListFilter(target_agent_id="agt_cccccc333333"))
    assert len(rows) == 1
    assert rows[0].target_agent_id == "agt_cccccc333333"


def test_list_rows_since_filter(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(
        dao, message_id="aa000000-0000-4000-8000-000000000001",
        enqueued_at="2026-05-11T00:00:00.000Z",
    )
    _insert_queued_sample(
        dao, message_id="bb000000-0000-4000-8000-000000000002",
        enqueued_at="2026-05-12T00:00:00.000Z",
    )
    rows = dao.list_rows(QueueListFilter(since="2026-05-12T00:00:00.000Z"))
    assert len(rows) == 1
    assert rows[0].message_id == "bb000000-0000-4000-8000-000000000002"


def test_list_rows_limit(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    for i in range(5):
        _insert_queued_sample(
            dao, message_id=f"aa000000-0000-4000-8000-{i:012}",
            enqueued_at=f"2026-05-12T00:0{i}:00.000Z",
        )
    rows = dao.list_rows(QueueListFilter(limit=2))
    assert len(rows) == 2


def test_list_rows_combined_filters_are_and(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    _insert_queued_sample(
        dao, message_id="aa000000-0000-4000-8000-000000000001",
        target_agent_id="agt_bbbbbb222222",
        enqueued_at="2026-05-11T00:00:00.000Z",
    )
    _insert_queued_sample(
        dao, message_id="bb000000-0000-4000-8000-000000000002",
        target_agent_id="agt_bbbbbb222222",
        enqueued_at="2026-05-12T00:00:00.000Z",
    )
    rows = dao.list_rows(QueueListFilter(
        target_agent_id="agt_bbbbbb222222",
        since="2026-05-12T00:00:00.000Z",
    ))
    assert len(rows) == 1
    assert rows[0].message_id == "bb000000-0000-4000-8000-000000000002"


# ──────────────────────────────────────────────────────────────────────
# with_lock_retry behaviour
# ──────────────────────────────────────────────────────────────────────


def test_with_lock_retry_returns_on_first_success() -> None:
    counter = [0]

    def op():
        counter[0] += 1
        return "ok"

    assert with_lock_retry(op) == "ok"
    assert counter[0] == 1


def test_with_lock_retry_retries_on_locked() -> None:
    """The op fails twice then succeeds; the helper returns the result."""
    counter = [0]

    def op():
        counter[0] += 1
        if counter[0] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    # Use a fast retry schedule to keep the test snappy.
    assert with_lock_retry(op, retries=(0.001, 0.001, 0.001)) == "ok"
    assert counter[0] == 3


def test_with_lock_retry_raises_sqlite_lock_conflict_when_exhausted() -> None:
    def op():
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(SqliteLockConflict):
        with_lock_retry(op, retries=(0.001, 0.001, 0.001))


def test_with_lock_retry_propagates_non_lock_operational_errors() -> None:
    """An OperationalError that's NOT a lock conflict (e.g., 'disk I/O
    error') propagates immediately, not retried."""

    def op():
        raise sqlite3.OperationalError("disk I/O error")

    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        with_lock_retry(op)


def test_with_lock_retry_propagates_other_exceptions() -> None:
    """Non-OperationalError exceptions propagate immediately."""

    def op():
        raise ValueError("oops")

    with pytest.raises(ValueError, match="oops"):
        with_lock_retry(op)


# ──────────────────────────────────────────────────────────────────────
# DaemonStateDao
# ──────────────────────────────────────────────────────────────────────


def test_daemon_state_dao_reads_seed_row(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = DaemonStateDao(conn)
    flag = dao.read_routing_flag()
    assert flag.value == "enabled"
    assert flag.last_updated_by == "(daemon-init)"


def test_daemon_state_dao_writes_routing_flag(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = DaemonStateDao(conn)
    dao.write_routing_flag(
        "disabled", ts="2026-05-12T00:00:01.000Z", updated_by="host-operator"
    )
    flag = dao.read_routing_flag()
    assert flag.value == "disabled"
    assert flag.last_updated_by == "host-operator"
    assert flag.last_updated_at == "2026-05-12T00:00:01.000Z"


def test_daemon_state_dao_write_rejects_invalid_value(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = DaemonStateDao(conn)
    with pytest.raises(ValueError, match="must be"):
        dao.write_routing_flag(
            "maybe", ts="2026-05-12T00:00:01.000Z", updated_by="host-operator"
        )
