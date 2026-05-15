"""T016 — events DAO filter combination tests.

Asserts that every filter combination from
``contracts/socket-events.md`` C-EVT-001 produces correct results
against an in-memory SQLite database; default ordering matches FR-028
``(observed_at ASC, byte_range_start ASC, event_id ASC)``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agenttower.events.dao import (
    EventFilter,
    EventRow,
    insert_audit_event,
    insert_event,
    mark_jsonl_appended,
    select_event_by_id,
    select_events,
    select_pending_jsonl,
)
from agenttower.state import schema


def _open_v6(tmp_path: Path) -> sqlite3.Connection:
    state_db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(state_db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (5)")
    for v in (2, 3, 4, 5, 6):
        schema._MIGRATIONS[v](conn)
    conn.commit()
    return conn


def _make_row(
    *,
    event_type: str = "activity",
    agent_id: str = "agt_a1b2c3d4e5f6",
    attachment_id: str = "atc_aabbccddeeff",
    log_path: str = "/tmp/agent.log",
    byte_range_start: int = 0,
    byte_range_end: int = 10,
    line_offset_start: int = 0,
    line_offset_end: int = 1,
    observed_at: str = "2026-05-10T12:00:00.000000+00:00",
    excerpt: str = "x",
    classifier_rule_id: str = "activity.fallback.v1",
) -> EventRow:
    return EventRow(
        event_id=0,
        event_type=event_type,
        agent_id=agent_id,
        attachment_id=attachment_id,
        log_path=log_path,
        byte_range_start=byte_range_start,
        byte_range_end=byte_range_end,
        line_offset_start=line_offset_start,
        line_offset_end=line_offset_end,
        observed_at=observed_at,
        record_at=None,
        excerpt=excerpt,
        classifier_rule_id=classifier_rule_id,
        debounce_window_id=None,
        debounce_collapsed_count=1,
        debounce_window_started_at=None,
        debounce_window_ended_at=None,
        schema_version=1,
        jsonl_appended_at=None,
    )


def _seed_three_agents(conn: sqlite3.Connection) -> dict[str, list[int]]:
    """Insert 6 events: 2 per agent across 3 agents, with varied types."""
    inserted: dict[str, list[int]] = {}
    sequence = [
        ("agt_aaaaaaaaaaaa", "activity", "2026-05-10T12:00:00.000000+00:00", 0, 10),
        ("agt_aaaaaaaaaaaa", "error",    "2026-05-10T12:00:01.000000+00:00", 10, 20),
        ("agt_bbbbbbbbbbbb", "activity", "2026-05-10T12:00:02.000000+00:00", 0, 10),
        ("agt_bbbbbbbbbbbb", "test_passed", "2026-05-10T12:00:03.000000+00:00", 10, 20),
        ("agt_cccccccccccc", "error",    "2026-05-10T12:00:04.000000+00:00", 0, 10),
        ("agt_cccccccccccc", "completed","2026-05-10T12:00:05.000000+00:00", 10, 20),
    ]
    for aid, etype, obs, brs, bre in sequence:
        eid = insert_event(
            conn,
            _make_row(
                agent_id=aid,
                event_type=etype,
                observed_at=obs,
                byte_range_start=brs,
                byte_range_end=bre,
            ),
        )
        inserted.setdefault(aid, []).append(eid)
    conn.commit()
    return inserted


def test_default_ordering_is_oldest_first(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    _seed_three_agents(conn)
    rows, next_cursor = select_events(
        conn, filter=EventFilter(), cursor=None, limit=50, reverse=False
    )
    # All six events, oldest first.
    assert len(rows) == 6
    assert next_cursor is None
    observed_ats = [r.observed_at for r in rows]
    assert observed_ats == sorted(observed_ats)


def test_target_filter(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    _seed_three_agents(conn)
    rows, _ = select_events(
        conn,
        filter=EventFilter(target_agent_id="agt_bbbbbbbbbbbb"),
        cursor=None,
        limit=50,
        reverse=False,
    )
    assert len(rows) == 2
    assert all(r.agent_id == "agt_bbbbbbbbbbbb" for r in rows)


def test_type_filter_single(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    _seed_three_agents(conn)
    rows, _ = select_events(
        conn,
        filter=EventFilter(types=("error",)),
        cursor=None,
        limit=50,
        reverse=False,
    )
    assert {r.event_type for r in rows} == {"error"}
    assert len(rows) == 2  # one per matching agent


def test_type_filter_multi(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    _seed_three_agents(conn)
    rows, _ = select_events(
        conn,
        filter=EventFilter(types=("error", "test_passed")),
        cursor=None,
        limit=50,
        reverse=False,
    )
    assert {r.event_type for r in rows} == {"error", "test_passed"}
    assert len(rows) == 3  # 2 errors + 1 test_passed


def test_target_and_type_filter(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    _seed_three_agents(conn)
    rows, _ = select_events(
        conn,
        filter=EventFilter(target_agent_id="agt_aaaaaaaaaaaa", types=("activity",)),
        cursor=None,
        limit=50,
        reverse=False,
    )
    assert len(rows) == 1
    assert rows[0].agent_id == "agt_aaaaaaaaaaaa"
    assert rows[0].event_type == "activity"


def test_since_filter(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    _seed_three_agents(conn)
    rows, _ = select_events(
        conn,
        filter=EventFilter(since_iso="2026-05-10T12:00:03.000000+00:00"),
        cursor=None,
        limit=50,
        reverse=False,
    )
    assert len(rows) == 3  # observed_at >= since
    assert all(r.observed_at >= "2026-05-10T12:00:03.000000+00:00" for r in rows)


def test_until_filter(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    _seed_three_agents(conn)
    rows, _ = select_events(
        conn,
        filter=EventFilter(until_iso="2026-05-10T12:00:03.000000+00:00"),
        cursor=None,
        limit=50,
        reverse=False,
    )
    assert len(rows) == 3  # observed_at < until (exclusive)
    assert all(r.observed_at < "2026-05-10T12:00:03.000000+00:00" for r in rows)


def test_since_and_until_window(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    _seed_three_agents(conn)
    rows, _ = select_events(
        conn,
        filter=EventFilter(
            since_iso="2026-05-10T12:00:01.000000+00:00",
            until_iso="2026-05-10T12:00:04.000000+00:00",
        ),
        cursor=None,
        limit=50,
        reverse=False,
    )
    # Window includes T+1, T+2, T+3 (until is exclusive).
    assert len(rows) == 3


def test_pagination_via_cursor(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    _seed_three_agents(conn)
    page1, cursor = select_events(
        conn, filter=EventFilter(), cursor=None, limit=2, reverse=False
    )
    assert len(page1) == 2
    assert cursor is not None
    page2, cursor2 = select_events(
        conn, filter=EventFilter(), cursor=cursor, limit=2, reverse=False
    )
    assert len(page2) == 2
    # No overlap with page1.
    assert {r.event_id for r in page1}.isdisjoint({r.event_id for r in page2})
    page3, cursor3 = select_events(
        conn, filter=EventFilter(), cursor=cursor2, limit=2, reverse=False
    )
    assert len(page3) == 2
    assert cursor3 is None  # Last page.


def test_cursor_uses_full_sort_tuple_not_event_id_only(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    # Insert event_ids in an order that differs from FR-028 ordering.
    id_late_low = insert_event(
        conn,
        _make_row(
            observed_at="2026-05-10T12:00:00.000000+00:00",
            byte_range_start=10,
            byte_range_end=20,
            excerpt="late-low-id",
        ),
    )
    id_early_high = insert_event(
        conn,
        _make_row(
            observed_at="2026-05-10T11:00:00.000000+00:00",
            byte_range_start=0,
            byte_range_end=10,
            excerpt="early-high-id",
        ),
    )
    id_later_high = insert_event(
        conn,
        _make_row(
            observed_at="2026-05-10T12:00:00.000000+00:00",
            byte_range_start=20,
            byte_range_end=30,
            excerpt="later-high-id",
        ),
    )
    conn.commit()

    page1, cursor = select_events(
        conn, filter=EventFilter(), cursor=None, limit=2, reverse=False
    )
    assert [r.event_id for r in page1] == [id_early_high, id_late_low]
    assert cursor is not None
    page2, cursor2 = select_events(
        conn, filter=EventFilter(), cursor=cursor, limit=2, reverse=False
    )
    assert [r.event_id for r in page2] == [id_later_high]
    assert cursor2 is None


def test_reverse_cursor_uses_full_sort_tuple_not_event_id_only(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    id_late_low = insert_event(
        conn,
        _make_row(
            observed_at="2026-05-10T12:00:00.000000+00:00",
            byte_range_start=10,
            byte_range_end=20,
        ),
    )
    id_early_high = insert_event(
        conn,
        _make_row(
            observed_at="2026-05-10T11:00:00.000000+00:00",
            byte_range_start=0,
            byte_range_end=10,
        ),
    )
    id_later_high = insert_event(
        conn,
        _make_row(
            observed_at="2026-05-10T12:00:00.000000+00:00",
            byte_range_start=20,
            byte_range_end=30,
        ),
    )
    conn.commit()

    page1, cursor = select_events(
        conn, filter=EventFilter(), cursor=None, limit=2, reverse=True
    )
    assert [r.event_id for r in page1] == [id_later_high, id_late_low]
    assert cursor is not None
    page2, cursor2 = select_events(
        conn, filter=EventFilter(), cursor=cursor, limit=2, reverse=True
    )
    assert [r.event_id for r in page2] == [id_early_high]
    assert cursor2 is None


def test_reverse_inverts_order(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    _seed_three_agents(conn)
    forward_rows, _ = select_events(
        conn, filter=EventFilter(), cursor=None, limit=50, reverse=False
    )
    reverse_rows, _ = select_events(
        conn, filter=EventFilter(), cursor=None, limit=50, reverse=True
    )
    assert [r.event_id for r in forward_rows] == list(
        reversed([r.event_id for r in reverse_rows])
    )


def test_pagination_cursor_handles_audit_rows_with_null_byte_ranges(tmp_path: Path) -> None:
    conn, _ = schema.open_registry(tmp_path / "state.sqlite3")
    insert_event(
        conn,
        _make_row(
            observed_at="2026-05-10T12:00:00.000000+00:00",
            byte_range_start=0,
            byte_range_end=10,
        ),
    )
    insert_audit_event(
        conn,
        event_type="queue_message_enqueued",
        agent_id="agt_aaaaaaaaaaaa",
        observed_at="2026-05-10T12:00:01.000000+00:00",
        excerpt="audit row",
    )
    insert_event(
        conn,
        _make_row(
            observed_at="2026-05-10T12:00:02.000000+00:00",
            byte_range_start=10,
            byte_range_end=20,
        ),
    )
    conn.commit()

    page1, cursor = select_events(
        conn, filter=EventFilter(), cursor=None, limit=2, reverse=False
    )
    assert len(page1) == 2
    assert cursor is not None
    page2, cursor2 = select_events(
        conn, filter=EventFilter(), cursor=cursor, limit=2, reverse=False
    )
    assert len(page2) == 1
    assert cursor2 is None


def test_cursor_direction_mismatch_raises(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    _seed_three_agents(conn)
    _, cursor = select_events(
        conn, filter=EventFilter(), cursor=None, limit=2, reverse=False
    )
    assert cursor is not None
    # Forward cursor + reverse query must error (not silently misorder).
    with pytest.raises(Exception):  # CursorError, but imported lazily
        select_events(
            conn, filter=EventFilter(), cursor=cursor, limit=2, reverse=True
        )


def test_select_pending_jsonl_returns_only_unflagged(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    inserted = _seed_three_agents(conn)
    all_ids = sorted(eid for ids in inserted.values() for eid in ids)
    # Mark first three as appended.
    for eid in all_ids[:3]:
        mark_jsonl_appended(conn, eid, "2026-05-10T12:00:10.000000+00:00")
    conn.commit()
    pending = select_pending_jsonl(conn, limit=50)
    assert {r.event_id for r in pending} == set(all_ids[3:])
    assert all(r.jsonl_appended_at is None for r in pending)


def test_select_event_by_id_present_and_missing(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    inserted = _seed_three_agents(conn)
    first_id = next(iter(inserted.values()))[0]
    row = select_event_by_id(conn, first_id)
    assert row is not None
    assert row.event_id == first_id
    assert select_event_by_id(conn, 999_999) is None


def test_insert_event_rejects_unknown_event_type(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    bad = _make_row(event_type="not_a_real_type")
    with pytest.raises(ValueError):
        insert_event(conn, bad)


def test_insert_event_rejects_inverted_byte_range(tmp_path: Path) -> None:
    conn = _open_v6(tmp_path)
    bad = _make_row(byte_range_start=20, byte_range_end=5)
    with pytest.raises(ValueError):
        insert_event(conn, bad)
