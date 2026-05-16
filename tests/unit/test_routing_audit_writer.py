"""T035 — FEAT-009 QueueAuditWriter (FR-046 dual-write) tests.

Covers:

* Happy path: dual-write succeeds; both SQLite row and JSONL line exist
  and match their schemas; ``jsonl_appended_at`` is populated.
* SQLite INSERT failure: exception propagates; nothing written.
* JSONL ``OSError``: SQLite row intact, JSONL record buffered,
  ``degraded`` flag set, exception class captured.
* JSONL non-``OSError`` (Group-A walk Q6): any ``Exception`` is caught;
  same degraded path; specifically tests ``TypeError("not JSON
  serializable")`` and ``RuntimeError``.
* Drain: next cycle drains buffered records FIFO, back-fills
  ``jsonl_appended_at``, clears the degraded flag when fully drained.
* Drain stops on first failure (FIFO preserved).
* Buffer cap: oldest entries drop with a warning when the deque is full.
* ``routing_toggled`` events use the alternate audit shape
  (``previous_value``/``current_value``).
* Per data-model.md §7.1.1: ``events.agent_id`` is the TARGET's
  agent_id for ``queue_message_*`` rows.
* Per data-model.md §7.1.2: ``events.agent_id`` is the operator for
  ``routing_toggled`` rows.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from agenttower.routing.audit_writer import (
    DEFAULT_DEGRADED_AUDIT_BUFFER_MAX_ROWS,
    PendingJsonl,
    QueueAuditWriter,
)
from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _open_v7(tmp_path: Path) -> sqlite3.Connection:
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


def _make_writer(tmp_path: Path, **kwargs) -> QueueAuditWriter:
    conn = _open_v7(tmp_path)
    jsonl_path = tmp_path / "events.jsonl"
    return QueueAuditWriter(conn, jsonl_path, **kwargs)


_SENDER = {
    "agent_id": "agt_aaaaaa111111",
    "label": "queen",
    "role": "master",
    "capability": "plan",
}
_TARGET = {
    "agent_id": "agt_bbbbbb222222",
    "label": "worker-1",
    "role": "slave",
    "capability": "implement",
}


def _append_one(writer: QueueAuditWriter, **overrides) -> int:
    """Convenience: append one queue_message_delivered transition.

    ``event_type`` and ``to_state`` are decoupled in the writer API
    (see audit_writer.append_queue_transition docstring): the default
    here is a delivered transition, but tests can override either or
    both independently.
    """
    kwargs = dict(
        event_type="queue_message_delivered",
        message_id="12345678-1234-4234-8234-123456789012",
        from_state="queued",
        to_state="delivered",
        reason=None,
        operator=None,
        observed_at="2026-05-12T00:00:01.000Z",
        sender=_SENDER,
        target=_TARGET,
        excerpt="do thing",
    )
    kwargs.update(overrides)
    return writer.append_queue_transition(**kwargs)


def _read_jsonl_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().strip().split("\n") if line]


def _read_events_row(conn: sqlite3.Connection, event_id: int) -> tuple:
    return conn.execute(
        "SELECT event_type, agent_id, observed_at, excerpt, jsonl_appended_at, "
        "attachment_id, log_path, classifier_rule_id "
        "FROM events WHERE event_id = ?",
        (event_id,),
    ).fetchone()


# ──────────────────────────────────────────────────────────────────────
# Happy path: dual-write
# ──────────────────────────────────────────────────────────────────────


def test_dual_write_succeeds_both_sqlite_and_jsonl(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    event_id = _append_one(writer)
    # SQLite row exists with the right shape.
    row = _read_events_row(writer._conn, event_id)
    event_type, agent_id, observed_at, excerpt, jsonl_at, att, log, cls = row
    assert event_type == "queue_message_delivered"
    assert agent_id == _TARGET["agent_id"]  # data-model §7.1.1
    assert observed_at == "2026-05-12T00:00:01.000Z"
    assert excerpt == "do thing"
    assert jsonl_at == "2026-05-12T00:00:01.000Z"  # watermark back-filled
    assert att is None and log is None and cls is None
    # JSONL line written with the FR-046 payload shape.
    lines = _read_jsonl_lines(writer._events_jsonl_path)
    assert len(lines) == 1
    payload = lines[0]
    assert payload["event_type"] == "queue_message_delivered"
    assert payload["message_id"] == "12345678-1234-4234-8234-123456789012"
    assert payload["from_state"] == "queued"
    assert payload["to_state"] == "delivered"
    assert payload["sender"] == _SENDER
    assert payload["target"] == _TARGET
    assert payload["excerpt"] == "do thing"
    # writer is not degraded.
    assert writer.degraded is False
    assert writer.pending_count == 0


def test_dual_write_uses_target_agent_id_in_sqlite_row(tmp_path: Path) -> None:
    """Per data-model §7.1.1: events.agent_id ← target.agent_id, so
    `events --target <agent>` surfaces queue events delivered to that
    agent."""
    writer = _make_writer(tmp_path)
    event_id = _append_one(writer)
    row = _read_events_row(writer._conn, event_id)
    assert row[1] == _TARGET["agent_id"]
    assert row[1] != _SENDER["agent_id"]


def test_event_type_stored_in_sqlite_row(tmp_path: Path) -> None:
    """Each of the seven closed-set ``queue_message_*`` event types is
    accepted and stored verbatim in ``events.event_type``. ``event_type``
    and ``to_state`` are decoupled (see audit_writer.append_queue_transition
    docstring); this test passes both, but only event_type lands in the
    SQLite events row."""
    writer = _make_writer(tmp_path)
    for verb in ("delivered", "blocked", "failed", "canceled",
                 "approved", "delayed", "enqueued"):
        eid = _append_one(
            writer,
            event_type=f"queue_message_{verb}",
            to_state=verb if verb in ("delivered", "blocked", "canceled", "failed")
                     else ("queued" if verb in ("approved", "enqueued") else "blocked"),
            observed_at=f"2026-05-12T00:00:01.{ord(verb[0]):03}Z",
        )
        row = _read_events_row(writer._conn, eid)
        assert row[0] == f"queue_message_{verb}"


# ──────────────────────────────────────────────────────────────────────
# SQLite INSERT failure path
# ──────────────────────────────────────────────────────────────────────


def test_sqlite_failure_propagates_no_jsonl_write(tmp_path: Path) -> None:
    """If the SQLite INSERT raises (e.g., CHECK violation on event_type),
    the exception propagates and no JSONL row is written. We trip the
    constraint by passing an event_type that satisfies the
    ``queue_message_`` prefix gate in the writer but is not in the
    events table's closed CHECK set."""
    writer = _make_writer(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        _append_one(writer, event_type="queue_message_not_a_real_state")
    # No JSONL row.
    assert _read_jsonl_lines(writer._events_jsonl_path) == []
    # No SQLite row.
    count = writer._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count == 0
    assert writer.degraded is False


# ──────────────────────────────────────────────────────────────────────
# JSONL failure path: OSError + non-OSError (Group-A walk Q6)
# ──────────────────────────────────────────────────────────────────────


def test_jsonl_oserror_buffers_record_and_marks_degraded(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    # Patch append_event in the writer's namespace to raise OSError.
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = OSError("disk full")
        event_id = _append_one(writer)
    # SQLite row exists.
    row = _read_events_row(writer._conn, event_id)
    assert row is not None
    assert row[4] is None  # jsonl_appended_at NOT set (no watermark)
    # Writer is degraded.
    assert writer.degraded is True
    assert writer.pending_count == 1
    assert writer.last_failure_exc_class == "OSError"
    pending = writer._pending[0]
    assert pending.event_id == event_id


def test_jsonl_typeerror_caught_per_group_a_q6(tmp_path: Path) -> None:
    """Group-A walk Q6: any Exception (not just OSError) is caught."""
    writer = _make_writer(tmp_path)
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = TypeError("not JSON serializable")
        event_id = _append_one(writer)
    # SQLite row remains; writer degraded with TypeError class captured.
    row = _read_events_row(writer._conn, event_id)
    assert row is not None
    assert row[4] is None
    assert writer.degraded is True
    assert writer.last_failure_exc_class == "TypeError"


def test_jsonl_runtime_error_caught(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = RuntimeError("oops")
        _append_one(writer)
    assert writer.degraded is True
    assert writer.last_failure_exc_class == "RuntimeError"


def test_jsonl_failure_does_not_roll_back_sqlite(tmp_path: Path) -> None:
    """The SQLite write is the source of truth (FR-048). A subsequent
    JSONL failure MUST NOT roll back the SQLite row."""
    writer = _make_writer(tmp_path)
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = OSError("disk full")
        event_id = _append_one(writer)
    # SQLite still has the row.
    assert writer._conn.execute(
        "SELECT COUNT(*) FROM events WHERE event_id = ?", (event_id,)
    ).fetchone()[0] == 1


# ──────────────────────────────────────────────────────────────────────
# Drain: FIFO, back-fill, degraded-clear
# ──────────────────────────────────────────────────────────────────────


def test_drain_pending_writes_buffered_records_to_jsonl(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    # Buffer two records.
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = OSError("disk full")
        _append_one(writer, message_id="aa000000-0000-4000-8000-000000000001",
                    observed_at="2026-05-12T00:00:01.000Z")
        _append_one(writer, message_id="bb000000-0000-4000-8000-000000000002",
                    observed_at="2026-05-12T00:00:02.000Z")
    assert writer.pending_count == 2
    # Disk recovers; drain succeeds.
    drained = writer.drain_pending()
    assert drained == 2
    assert writer.pending_count == 0
    assert writer.degraded is False
    assert writer.last_failure_exc_class is None
    # JSONL has both lines, FIFO order.
    lines = _read_jsonl_lines(writer._events_jsonl_path)
    assert len(lines) == 2
    assert lines[0]["message_id"] == "aa000000-0000-4000-8000-000000000001"
    assert lines[1]["message_id"] == "bb000000-0000-4000-8000-000000000002"


def test_drain_back_fills_jsonl_appended_at_watermark(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = OSError("disk full")
        event_id = _append_one(writer)
    # Watermark NULL.
    pre = _read_events_row(writer._conn, event_id)
    assert pre[4] is None
    writer.drain_pending()
    # Watermark back-filled.
    post = _read_events_row(writer._conn, event_id)
    assert post[4] == "2026-05-12T00:00:01.000Z"


def test_drain_stops_on_first_failure_fifo_preserved(tmp_path: Path) -> None:
    """If drain's first attempt fails, the FIFO order is preserved and
    the failed record stays at the head."""
    writer = _make_writer(tmp_path)
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = OSError("disk full")
        _append_one(writer, message_id="aa000000-0000-4000-8000-000000000001",
                    observed_at="2026-05-12T00:00:01.000Z")
        _append_one(writer, message_id="bb000000-0000-4000-8000-000000000002",
                    observed_at="2026-05-12T00:00:02.000Z")
    # Drain attempt: append_event still fails.
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = OSError("disk still full")
        drained = writer.drain_pending()
    assert drained == 0
    assert writer.pending_count == 2
    # Head is still the oldest record.
    assert writer._pending[0].payload["message_id"] == "aa000000-0000-4000-8000-000000000001"


def test_drain_no_op_when_empty(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    assert writer.drain_pending() == 0


# ──────────────────────────────────────────────────────────────────────
# Buffer cap: oldest drops when full
# ──────────────────────────────────────────────────────────────────────


def test_buffer_cap_drops_oldest_when_full(tmp_path: Path) -> None:
    """When the deque reaches max_pending, the next append-while-failed
    drops the OLDEST buffered record (deque.append with maxlen)."""
    writer = _make_writer(tmp_path, max_pending=3)
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = OSError("disk full")
        for i in range(5):
            _append_one(
                writer,
                message_id=f"aa000000-0000-4000-8000-{i:012}",
                observed_at=f"2026-05-12T00:00:0{i}.000Z",
            )
    # Only the 3 most recent survive (oldest 2 dropped).
    assert writer.pending_count == 3
    mids = [p.payload["message_id"] for p in writer._pending]
    assert mids == [
        "aa000000-0000-4000-8000-000000000002",
        "aa000000-0000-4000-8000-000000000003",
        "aa000000-0000-4000-8000-000000000004",
    ]


def test_default_buffer_cap_is_1024(tmp_path: Path) -> None:
    """Group-A walk Q6 + plan §"Defaults locked": cap = 1024 rows."""
    assert DEFAULT_DEGRADED_AUDIT_BUFFER_MAX_ROWS == 1024


# ──────────────────────────────────────────────────────────────────────
# routing_toggled events
# ──────────────────────────────────────────────────────────────────────


def test_routing_toggled_uses_alternate_audit_shape(tmp_path: Path) -> None:
    """contracts/queue-audit-schema.md "Routing toggle audit entry":
    previous_value / current_value, not from_state / to_state."""
    writer = _make_writer(tmp_path)
    event_id = writer.append_routing_toggled(
        previous_value="enabled",
        current_value="disabled",
        operator="host-operator",
        observed_at="2026-05-12T00:00:01.000Z",
    )
    # JSONL payload uses previous_value / current_value.
    lines = _read_jsonl_lines(writer._events_jsonl_path)
    assert len(lines) == 1
    payload = lines[0]
    assert payload["event_type"] == "routing_toggled"
    assert payload["previous_value"] == "enabled"
    assert payload["current_value"] == "disabled"
    assert payload["operator"] == "host-operator"
    assert "from_state" not in payload
    assert "to_state" not in payload
    assert "message_id" not in payload
    # SQLite row uses the operator as agent_id (data-model §7.1.2).
    row = _read_events_row(writer._conn, event_id)
    assert row[0] == "routing_toggled"
    assert row[1] == "host-operator"


def test_routing_toggled_excerpt_is_short_human_summary(tmp_path: Path) -> None:
    """data-model.md §7.1.2: excerpt is `routing <new> (was <prev>)` —
    short, no body content, satisfies the NOT NULL excerpt constraint."""
    writer = _make_writer(tmp_path)
    event_id = writer.append_routing_toggled(
        previous_value="disabled",
        current_value="enabled",
        operator="host-operator",
        observed_at="2026-05-12T00:00:01.000Z",
    )
    row = _read_events_row(writer._conn, event_id)
    assert row[3] == "routing enabled (was disabled)"


def test_routing_toggled_jsonl_failure_buffers_record(tmp_path: Path) -> None:
    """The same degraded path applies to routing_toggled events."""
    writer = _make_writer(tmp_path)
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = OSError("disk full")
        event_id = writer.append_routing_toggled(
            previous_value="enabled",
            current_value="disabled",
            operator="host-operator",
            observed_at="2026-05-12T00:00:01.000Z",
        )
    # SQLite row exists.
    row = _read_events_row(writer._conn, event_id)
    assert row[0] == "routing_toggled"
    assert row[4] is None  # jsonl watermark not set
    assert writer.degraded is True


# ──────────────────────────────────────────────────────────────────────
# Edge: degraded flag clears after successful drain
# ──────────────────────────────────────────────────────────────────────


def test_degraded_flag_clears_after_full_drain(tmp_path: Path) -> None:
    writer = _make_writer(tmp_path)
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = OSError("disk full")
        _append_one(writer)
    assert writer.degraded is True
    assert writer.last_failure_exc_class == "OSError"
    writer.drain_pending()
    assert writer.degraded is False
    assert writer.last_failure_exc_class is None


def test_degraded_flag_remains_after_partial_drain(tmp_path: Path) -> None:
    """If drain succeeds for some records but a later one fails, the
    degraded flag stays on (deque not empty)."""
    writer = _make_writer(tmp_path)
    with patch("agenttower.routing.audit_writer.append_event") as mock_append:
        mock_append.side_effect = OSError("disk full")
        for i in range(3):
            _append_one(
                writer,
                message_id=f"aa000000-0000-4000-8000-{i:012}",
                observed_at=f"2026-05-12T00:00:0{i}.000Z",
            )
    # Drain: first call succeeds, second fails.
    call_count = [0]
    real_append = __import__("agenttower.events.writer",
                             fromlist=["append_event"]).append_event

    def side_effect(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return real_append(*a, **kw)
        raise OSError("disk full again")

    with patch("agenttower.routing.audit_writer.append_event", side_effect=side_effect):
        writer.drain_pending()
    # 2 records still pending; degraded still True.
    assert writer.pending_count == 2
    assert writer.degraded is True
