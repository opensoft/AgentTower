"""T030 — FEAT-009 state-machine transition matrix tests.

Pins the closed transition graph from data-model.md §3.1 / §3.2:

* Every ALLOWED transition succeeds (matrix rows).
* Every FORBIDDEN transition raises the matching closed-set error
  (matrix anti-rows).
* Terminal states (`delivered`, `failed`, `canceled`) reject every
  further mutation with `terminal_state_cannot_change` (FR-014).

Distinct from `test_routing_dao.py` which tests individual transition
methods. This file is the matrix-level guarantee.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from agenttower.routing.dao import MessageQueueDao
from agenttower.routing.errors import QueueServiceError
from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Test fixture helpers
# ──────────────────────────────────────────────────────────────────────


def _open_v7(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (schema.CURRENT_SCHEMA_VERSION,))
    for v in range(2, schema.CURRENT_SCHEMA_VERSION + 1):
        schema._MIGRATIONS[v](conn)
    conn.commit()
    return conn


def _insert_queued(dao: MessageQueueDao, mid: str) -> None:
    dao.insert_queued(
        message_id=mid,
        sender={"agent_id": "agt_aaaaaa111111", "label": "q",
                "role": "master", "capability": None},
        target={"agent_id": "agt_bbbbbb222222", "label": "w",
                "role": "slave", "capability": None,
                "container_id": "c0", "pane_id": "%0"},
        envelope_body=b"x", envelope_body_sha256="0" * 64,
        envelope_size_bytes=10,
        enqueued_at="2026-05-12T00:00:00.000Z",
    )


def _insert_blocked(dao: MessageQueueDao, mid: str, block_reason: str = "kill_switch_off") -> None:
    dao.insert_blocked(
        message_id=mid,
        sender={"agent_id": "agt_aaaaaa111111", "label": "q",
                "role": "master", "capability": None},
        target={"agent_id": "agt_bbbbbb222222", "label": "w",
                "role": "slave", "capability": None,
                "container_id": "c0", "pane_id": "%0"},
        envelope_body=b"x", envelope_body_sha256="0" * 64,
        envelope_size_bytes=10,
        enqueued_at="2026-05-12T00:00:00.000Z",
        block_reason=block_reason,
    )


def _make_delivered(dao: MessageQueueDao, mid: str) -> None:
    _insert_queued(dao, mid)
    dao.stamp_delivery_attempt_started(mid, "2026-05-12T00:00:01.000Z")
    dao.transition_queued_to_delivered(mid, "2026-05-12T00:00:02.000Z")


def _make_failed(dao: MessageQueueDao, mid: str) -> None:
    _insert_queued(dao, mid)
    dao.stamp_delivery_attempt_started(mid, "2026-05-12T00:00:01.000Z")
    dao.transition_queued_to_failed(mid, "tmux_paste_failed", "2026-05-12T00:00:02.000Z")


def _make_canceled(dao: MessageQueueDao, mid: str) -> None:
    _insert_queued(dao, mid)
    dao.transition_to_canceled(mid, operator="host-operator", ts="2026-05-12T00:00:01.000Z")


# ──────────────────────────────────────────────────────────────────────
# Allowed transitions (data-model §3.1)
# ──────────────────────────────────────────────────────────────────────


def test_allowed_insert_to_queued(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "aa000000-0000-4000-8000-000000000001"
    _insert_queued(dao, mid)
    assert dao.get_row_by_id(mid).state == "queued"


def test_allowed_insert_to_blocked(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "aa000000-0000-4000-8000-000000000002"
    _insert_blocked(dao, mid)
    assert dao.get_row_by_id(mid).state == "blocked"


def test_allowed_queued_to_delivered(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "aa000000-0000-4000-8000-000000000003"
    _insert_queued(dao, mid)
    dao.stamp_delivery_attempt_started(mid, "2026-05-12T00:00:01.000Z")
    dao.transition_queued_to_delivered(mid, "2026-05-12T00:00:02.000Z")
    assert dao.get_row_by_id(mid).state == "delivered"


def test_allowed_queued_to_failed(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "aa000000-0000-4000-8000-000000000004"
    _insert_queued(dao, mid)
    dao.stamp_delivery_attempt_started(mid, "2026-05-12T00:00:01.000Z")
    dao.transition_queued_to_failed(mid, "tmux_paste_failed", "2026-05-12T00:00:02.000Z")
    assert dao.get_row_by_id(mid).state == "failed"


def test_allowed_queued_to_blocked_re_check(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "aa000000-0000-4000-8000-000000000005"
    _insert_queued(dao, mid)
    dao.transition_queued_to_blocked_re_check(
        mid, "target_pane_missing", "2026-05-12T00:00:01.000Z"
    )
    assert dao.get_row_by_id(mid).state == "blocked"


def test_allowed_queued_to_blocked_delay(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "aa000000-0000-4000-8000-000000000006"
    _insert_queued(dao, mid)
    dao.transition_queued_to_blocked_delay(
        mid, operator="host-operator", ts="2026-05-12T00:00:01.000Z"
    )
    row = dao.get_row_by_id(mid)
    assert row.state == "blocked"
    assert row.block_reason == "operator_delayed"


def test_allowed_queued_to_canceled(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "aa000000-0000-4000-8000-000000000007"
    _insert_queued(dao, mid)
    dao.transition_to_canceled(mid, operator="host-operator", ts="2026-05-12T00:00:01.000Z")
    assert dao.get_row_by_id(mid).state == "canceled"


def test_allowed_blocked_to_queued_approve(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "aa000000-0000-4000-8000-000000000008"
    _insert_blocked(dao, mid, block_reason="operator_delayed")
    dao.transition_blocked_to_queued_approve(
        mid, operator="host-operator", ts="2026-05-12T00:00:01.000Z"
    )
    row = dao.get_row_by_id(mid)
    assert row.state == "queued"
    assert row.block_reason is None


def test_allowed_blocked_to_canceled(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "aa000000-0000-4000-8000-000000000009"
    _insert_blocked(dao, mid)
    dao.transition_to_canceled(mid, operator="host-operator", ts="2026-05-12T00:00:01.000Z")
    assert dao.get_row_by_id(mid).state == "canceled"


def test_allowed_recovery_in_flight_to_failed(tmp_path: Path) -> None:
    """FR-040 recovery transitions in-flight rows to failed/attempt_interrupted."""
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "aa000000-0000-4000-8000-000000000010"
    _insert_queued(dao, mid)
    dao.stamp_delivery_attempt_started(mid, "2026-05-12T00:00:01.000Z")
    count = dao.recover_in_flight_rows("2026-05-12T00:01:00.000Z")
    assert count == 1
    row = dao.get_row_by_id(mid)
    assert row.state == "failed"
    assert row.failure_reason == "attempt_interrupted"


# ──────────────────────────────────────────────────────────────────────
# Forbidden transitions from TERMINAL states (FR-014)
# ──────────────────────────────────────────────────────────────────────


_TERMINAL_BUILDERS = {
    "delivered": _make_delivered,
    "failed": _make_failed,
    "canceled": _make_canceled,
}


@pytest.mark.parametrize("terminal_state", list(_TERMINAL_BUILDERS))
def test_terminal_cancel_raises_terminal_state_cannot_change(
    tmp_path: Path, terminal_state: str
) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = f"tt{terminal_state[:4]}000-0000-4000-8000-000000000001"
    _TERMINAL_BUILDERS[terminal_state](dao, mid)
    with pytest.raises(QueueServiceError) as info:
        dao.transition_to_canceled(
            mid, operator="host-operator", ts="2026-05-12T00:01:00.000Z"
        )
    assert info.value.code == "terminal_state_cannot_change"


@pytest.mark.parametrize("terminal_state", list(_TERMINAL_BUILDERS))
def test_terminal_approve_raises_terminal_state_cannot_change(
    tmp_path: Path, terminal_state: str
) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = f"tt{terminal_state[:4]}000-0000-4000-8000-000000000002"
    _TERMINAL_BUILDERS[terminal_state](dao, mid)
    with pytest.raises(QueueServiceError) as info:
        dao.transition_blocked_to_queued_approve(
            mid, operator="host-operator", ts="2026-05-12T00:01:00.000Z"
        )
    assert info.value.code == "terminal_state_cannot_change"


@pytest.mark.parametrize("terminal_state", list(_TERMINAL_BUILDERS))
def test_terminal_delay_raises_terminal_state_cannot_change(
    tmp_path: Path, terminal_state: str
) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = f"tt{terminal_state[:4]}000-0000-4000-8000-000000000003"
    _TERMINAL_BUILDERS[terminal_state](dao, mid)
    with pytest.raises(QueueServiceError) as info:
        dao.transition_queued_to_blocked_delay(
            mid, operator="host-operator", ts="2026-05-12T00:01:00.000Z"
        )
    assert info.value.code == "terminal_state_cannot_change"


@pytest.mark.parametrize("terminal_state", list(_TERMINAL_BUILDERS))
def test_terminal_recover_is_no_op(tmp_path: Path, terminal_state: str) -> None:
    """A terminal row's `failure_reason` (if any) is preserved across
    a recovery pass — recovery only touches in-flight rows."""
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = f"tt{terminal_state[:4]}000-0000-4000-8000-000000000004"
    _TERMINAL_BUILDERS[terminal_state](dao, mid)
    pre = dao.get_row_by_id(mid)
    count = dao.recover_in_flight_rows("2026-05-12T00:01:00.000Z")
    assert count == 0  # nothing recovered
    post = dao.get_row_by_id(mid)
    assert pre == post  # byte-for-byte preserved


# ──────────────────────────────────────────────────────────────────────
# Forbidden transitions: approve from queued, delay from blocked
# ──────────────────────────────────────────────────────────────────────


def test_approve_from_queued_raises_approval_not_applicable(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "qq000000-0000-4000-8000-000000000001"
    _insert_queued(dao, mid)
    with pytest.raises(QueueServiceError) as info:
        dao.transition_blocked_to_queued_approve(
            mid, operator="host-operator", ts="2026-05-12T00:00:01.000Z"
        )
    assert info.value.code == "approval_not_applicable"


def test_delay_from_blocked_raises_delay_not_applicable(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "bb000000-0000-4000-8000-000000000001"
    _insert_blocked(dao, mid)
    with pytest.raises(QueueServiceError) as info:
        dao.transition_queued_to_blocked_delay(
            mid, operator="host-operator", ts="2026-05-12T00:00:01.000Z"
        )
    assert info.value.code == "delay_not_applicable"


# ──────────────────────────────────────────────────────────────────────
# Forbidden transitions: operator action on in-flight row
# ──────────────────────────────────────────────────────────────────────


def test_approve_in_flight_raises_delivery_in_progress(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "ii000000-0000-4000-8000-000000000001"
    _insert_queued(dao, mid)
    dao.stamp_delivery_attempt_started(mid, "2026-05-12T00:00:01.000Z")
    with pytest.raises(QueueServiceError) as info:
        dao.transition_blocked_to_queued_approve(
            mid, operator="host-operator", ts="2026-05-12T00:00:02.000Z"
        )
    assert info.value.code == "delivery_in_progress"


def test_delay_in_flight_raises_delivery_in_progress(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "ii000000-0000-4000-8000-000000000002"
    _insert_queued(dao, mid)
    dao.stamp_delivery_attempt_started(mid, "2026-05-12T00:00:01.000Z")
    with pytest.raises(QueueServiceError) as info:
        dao.transition_queued_to_blocked_delay(
            mid, operator="host-operator", ts="2026-05-12T00:00:02.000Z"
        )
    assert info.value.code == "delivery_in_progress"


def test_cancel_in_flight_raises_delivery_in_progress(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "ii000000-0000-4000-8000-000000000003"
    _insert_queued(dao, mid)
    dao.stamp_delivery_attempt_started(mid, "2026-05-12T00:00:01.000Z")
    with pytest.raises(QueueServiceError) as info:
        dao.transition_to_canceled(
            mid, operator="host-operator", ts="2026-05-12T00:00:02.000Z"
        )
    assert info.value.code == "delivery_in_progress"


# ──────────────────────────────────────────────────────────────────────
# Operator transitions clear / set the right ancillary state
# ──────────────────────────────────────────────────────────────────────


def test_approve_clears_block_reason(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "cc000000-0000-4000-8000-000000000001"
    _insert_blocked(dao, mid, block_reason="operator_delayed")
    dao.transition_blocked_to_queued_approve(
        mid, operator="host-operator", ts="2026-05-12T00:00:01.000Z"
    )
    row = dao.get_row_by_id(mid)
    assert row.block_reason is None


def test_cancel_from_blocked_clears_block_reason(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "cc000000-0000-4000-8000-000000000002"
    _insert_blocked(dao, mid, block_reason="kill_switch_off")
    dao.transition_to_canceled(
        mid, operator="host-operator", ts="2026-05-12T00:00:01.000Z"
    )
    row = dao.get_row_by_id(mid)
    # block_reason must be cleared (CHECK requires NULL outside state='blocked').
    assert row.block_reason is None


def test_delay_sets_operator_delayed(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "cc000000-0000-4000-8000-000000000003"
    _insert_queued(dao, mid)
    dao.transition_queued_to_blocked_delay(
        mid, operator="host-operator", ts="2026-05-12T00:00:01.000Z"
    )
    row = dao.get_row_by_id(mid)
    assert row.block_reason == "operator_delayed"


def test_operator_action_metadata_set_on_every_operator_transition(
    tmp_path: Path,
) -> None:
    """Every operator transition sets operator_action / operator_action_at /
    operator_action_by atomically (data-model.md §2 coherence CHECK)."""
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    # Approve.
    mid_a = "cc000000-0000-4000-8000-000000000004"
    _insert_blocked(dao, mid_a, block_reason="operator_delayed")
    dao.transition_blocked_to_queued_approve(
        mid_a, operator="host-operator", ts="2026-05-12T00:00:01.000Z"
    )
    row_a = dao.get_row_by_id(mid_a)
    assert row_a.operator_action == "approved"
    assert row_a.operator_action_by == "host-operator"
    assert row_a.operator_action_at == "2026-05-12T00:00:01.000Z"
    # Delay.
    mid_d = "cc000000-0000-4000-8000-000000000005"
    _insert_queued(dao, mid_d)
    dao.transition_queued_to_blocked_delay(
        mid_d, operator="agt_aaaaaa111111", ts="2026-05-12T00:00:02.000Z"
    )
    row_d = dao.get_row_by_id(mid_d)
    assert row_d.operator_action == "delayed"
    assert row_d.operator_action_by == "agt_aaaaaa111111"
    # Cancel.
    mid_c = "cc000000-0000-4000-8000-000000000006"
    _insert_queued(dao, mid_c)
    dao.transition_to_canceled(
        mid_c, operator="host-operator", ts="2026-05-12T00:00:03.000Z"
    )
    row_c = dao.get_row_by_id(mid_c)
    assert row_c.operator_action == "canceled"


def test_failure_reason_set_on_failed_transition(tmp_path: Path) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    mid = "ff000000-0000-4000-8000-000000000001"
    _insert_queued(dao, mid)
    dao.stamp_delivery_attempt_started(mid, "2026-05-12T00:00:01.000Z")
    dao.transition_queued_to_failed(mid, "docker_exec_failed", "2026-05-12T00:00:02.000Z")
    row = dao.get_row_by_id(mid)
    assert row.failure_reason == "docker_exec_failed"


# ──────────────────────────────────────────────────────────────────────
# Unknown message_id propagates appropriately
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "method_name,operator_or_reason",
    [
        ("transition_to_canceled", None),
        ("transition_blocked_to_queued_approve", None),
        ("transition_queued_to_blocked_delay", None),
    ],
)
def test_operator_on_unknown_message_id_raises_message_id_not_found(
    tmp_path: Path, method_name: str, operator_or_reason: str | None
) -> None:
    conn = _open_v7(tmp_path)
    dao = MessageQueueDao(conn)
    fn = getattr(dao, method_name)
    with pytest.raises(QueueServiceError) as info:
        fn("ghost-id", operator="host-operator", ts="2026-05-12T00:00:01.000Z")
    assert info.value.code == "message_id_not_found"
