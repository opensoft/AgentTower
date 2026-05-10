"""FEAT-008 events table DAO.

Surface:

* :class:`EventRow` — frozen dataclass mirroring the SQLite ``events``
  schema in ``data-model.md`` §2.
* :class:`EventFilter` — query filter for ``events.list``.
* :func:`encode_cursor` / :func:`decode_cursor` — opaque pagination
  cursor codec (Research §R8). Cursor is integer-backed but
  base64url-encoded JSON at the CLI boundary.
* :func:`insert_event` — single-row insert; returns the new
  ``event_id``. Used inside the reader's atomic SQLite + offset
  commit.
* :func:`mark_jsonl_appended` — set ``jsonl_appended_at`` after a
  successful JSONL write (FR-029 watermark).
* :func:`select_events` — page through events; returns
  ``(rows, next_cursor)``.
* :func:`select_pending_jsonl` — return rows whose
  ``jsonl_appended_at`` is NULL (FR-029 retry queue).
* :func:`select_event_by_id` — single-row lookup, used by the follow
  registry to confirm an event still exists.

This module is the SOLE production-side writer to the ``events``
table. The reader calls these functions; nothing else does.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Optional


# Closed-set ``event_type`` values mirror the spec's FR-008 catalogue.
_EVENT_TYPES: tuple[str, ...] = (
    "activity",
    "waiting_for_input",
    "completed",
    "error",
    "test_failed",
    "test_passed",
    "manual_review_needed",
    "long_running",
    "pane_exited",
    "swarm_member_reported",
)


@dataclass(frozen=True)
class EventRow:
    """One row of the durable ``events`` table.

    Mirrors ``data-model.md`` §2.2 column-for-column. Constructed by
    the reader before insert; returned by ``select_*`` for read paths.
    """

    event_id: int
    event_type: str
    agent_id: str
    attachment_id: str
    log_path: str
    byte_range_start: int
    byte_range_end: int
    line_offset_start: int
    line_offset_end: int
    observed_at: str
    record_at: Optional[str]
    excerpt: str
    classifier_rule_id: str
    debounce_window_id: Optional[str]
    debounce_collapsed_count: int
    debounce_window_started_at: Optional[str]
    debounce_window_ended_at: Optional[str]
    schema_version: int
    jsonl_appended_at: Optional[str]


@dataclass(frozen=True)
class EventFilter:
    """Filter predicate for :func:`select_events`.

    All fields are optional. Empty / ``None`` means "no filter on
    this dimension". The combination is AND-merged at the SQL layer.
    """

    target_agent_id: Optional[str] = None
    types: tuple[str, ...] = field(default_factory=tuple)
    since_iso: Optional[str] = None
    until_iso: Optional[str] = None


# --------------------------------------------------------------------------
# Cursor codec — Research §R8
# --------------------------------------------------------------------------


class CursorError(ValueError):
    """Raised when :func:`decode_cursor` cannot parse its input.

    Maps to the ``events_invalid_cursor`` socket error envelope at
    the dispatcher layer.
    """


def encode_cursor(event_id: int, *, reverse: bool) -> str:
    """Encode ``(event_id, reverse)`` as a base64url-encoded JSON object.

    The CLI treats the result as opaque; clients MUST round-trip it
    verbatim. Padding ``=`` is stripped so the cursor fits in URL/CLI
    contexts without quoting.
    """
    if not isinstance(event_id, int) or isinstance(event_id, bool):
        raise CursorError(f"event_id must be int, got {type(event_id).__name__}")
    if event_id <= 0:
        raise CursorError(f"event_id must be > 0, got {event_id}")
    payload = json.dumps(
        {"e": event_id, "r": bool(reverse)}, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_cursor(token: str) -> tuple[int, bool]:
    """Decode a cursor produced by :func:`encode_cursor`.

    Raises :class:`CursorError` on any malformed input. Forward-tolerant
    of new optional keys (ignored), but strict on the documented two
    keys' types.
    """
    if not isinstance(token, str) or not token:
        raise CursorError("cursor must be a non-empty string")
    # Restore base64 padding (multiples of 4).
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise CursorError(f"cursor is not valid base64url: {exc}") from exc
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CursorError(f"cursor base64 payload is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise CursorError(f"cursor payload must be an object; got {type(obj).__name__}")
    if "e" not in obj or "r" not in obj:
        raise CursorError("cursor payload missing required keys 'e' and 'r'")
    e = obj["e"]
    r = obj["r"]
    if not isinstance(e, int) or isinstance(e, bool):
        raise CursorError(f"cursor 'e' must be int, got {type(e).__name__}")
    if e <= 0:
        raise CursorError(f"cursor 'e' must be > 0, got {e}")
    if not isinstance(r, bool):
        raise CursorError(f"cursor 'r' must be bool, got {type(r).__name__}")
    return e, r


# --------------------------------------------------------------------------
# CRUD — T009
# --------------------------------------------------------------------------


_INSERT_SQL = """
INSERT INTO events (
    event_type,
    agent_id,
    attachment_id,
    log_path,
    byte_range_start,
    byte_range_end,
    line_offset_start,
    line_offset_end,
    observed_at,
    record_at,
    excerpt,
    classifier_rule_id,
    debounce_window_id,
    debounce_collapsed_count,
    debounce_window_started_at,
    debounce_window_ended_at,
    schema_version,
    jsonl_appended_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def insert_event(conn: sqlite3.Connection, row: EventRow) -> int:
    """Insert a single event row; return the new ``event_id``.

    The caller MUST be inside an explicit transaction (the reader's
    FR-006 atomic SQLite + offset commit). ``row.event_id`` is ignored
    on insert — the SQLite ``INTEGER PRIMARY KEY AUTOINCREMENT`` value
    is what's authoritative.
    """
    if row.event_type not in _EVENT_TYPES:
        raise ValueError(
            f"event_type must be one of {_EVENT_TYPES}, got {row.event_type!r}"
        )
    if row.byte_range_start < 0 or row.byte_range_end < row.byte_range_start:
        raise ValueError(
            f"invalid byte range: ({row.byte_range_start}, {row.byte_range_end})"
        )
    if row.line_offset_start < 0 or row.line_offset_end < row.line_offset_start:
        raise ValueError(
            f"invalid line range: ({row.line_offset_start}, {row.line_offset_end})"
        )
    if row.debounce_collapsed_count < 1:
        raise ValueError(
            f"debounce_collapsed_count must be >= 1, got {row.debounce_collapsed_count}"
        )
    cur = conn.execute(
        _INSERT_SQL,
        (
            row.event_type,
            row.agent_id,
            row.attachment_id,
            row.log_path,
            row.byte_range_start,
            row.byte_range_end,
            row.line_offset_start,
            row.line_offset_end,
            row.observed_at,
            row.record_at,
            row.excerpt,
            row.classifier_rule_id,
            row.debounce_window_id,
            row.debounce_collapsed_count,
            row.debounce_window_started_at,
            row.debounce_window_ended_at,
            row.schema_version,
            row.jsonl_appended_at,
        ),
    )
    last_rowid = cur.lastrowid
    if last_rowid is None:
        raise sqlite3.OperationalError("insert_event: lastrowid is None")
    return int(last_rowid)


def mark_jsonl_appended(
    conn: sqlite3.Connection, event_id: int, ts_iso: str
) -> None:
    """Set ``jsonl_appended_at`` on a single row (FR-029 watermark)."""
    conn.execute(
        "UPDATE events SET jsonl_appended_at = ? WHERE event_id = ? "
        "AND jsonl_appended_at IS NULL",
        (ts_iso, event_id),
    )


_SELECT_FIELDS = (
    "event_id, event_type, agent_id, attachment_id, log_path, "
    "byte_range_start, byte_range_end, line_offset_start, line_offset_end, "
    "observed_at, record_at, excerpt, classifier_rule_id, "
    "debounce_window_id, debounce_collapsed_count, "
    "debounce_window_started_at, debounce_window_ended_at, "
    "schema_version, jsonl_appended_at"
)


def _row_to_event(row: tuple) -> EventRow:
    return EventRow(
        event_id=int(row[0]),
        event_type=row[1],
        agent_id=row[2],
        attachment_id=row[3],
        log_path=row[4],
        byte_range_start=int(row[5]),
        byte_range_end=int(row[6]),
        line_offset_start=int(row[7]),
        line_offset_end=int(row[8]),
        observed_at=row[9],
        record_at=row[10],
        excerpt=row[11],
        classifier_rule_id=row[12],
        debounce_window_id=row[13],
        debounce_collapsed_count=int(row[14]),
        debounce_window_started_at=row[15],
        debounce_window_ended_at=row[16],
        schema_version=int(row[17]),
        jsonl_appended_at=row[18],
    )


def select_events(
    conn: sqlite3.Connection,
    *,
    filter: EventFilter,
    cursor: Optional[str],
    limit: int,
    reverse: bool,
) -> tuple[list[EventRow], Optional[str]]:
    """Page through events.

    Returns ``(rows, next_cursor)``; ``next_cursor`` is None when this
    page is the last. Default ordering is per FR-028:
    ``(observed_at ASC, byte_range_start ASC, event_id ASC)`` —
    flipped when ``reverse=True``.

    The cursor encodes the last seen ``event_id``; the next page
    returns rows strictly past it (forward) or strictly before it
    (reverse). This is a stable substitute for OFFSET that does not
    miss or repeat rows under concurrent writes.
    """
    if limit <= 0:
        raise ValueError(f"limit must be > 0; got {limit}")
    where: list[str] = []
    params: list[object] = []
    if filter.target_agent_id is not None:
        where.append("agent_id = ?")
        params.append(filter.target_agent_id)
    if filter.types:
        placeholders = ",".join("?" * len(filter.types))
        where.append(f"event_type IN ({placeholders})")
        params.extend(filter.types)
    if filter.since_iso is not None:
        where.append("observed_at >= ?")
        params.append(filter.since_iso)
    if filter.until_iso is not None:
        where.append("observed_at < ?")
        params.append(filter.until_iso)
    if cursor is not None:
        cursor_event_id, cursor_reverse = decode_cursor(cursor)
        if cursor_reverse != reverse:
            raise CursorError(
                "cursor direction does not match query direction; cursors are "
                "single-direction (encode forward → use forward; encode reverse → "
                "use reverse)"
            )
        if reverse:
            where.append("event_id < ?")
        else:
            where.append("event_id > ?")
        params.append(cursor_event_id)

    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    order = "DESC" if reverse else "ASC"
    sql = (
        f"SELECT {_SELECT_FIELDS} FROM events"
        f"{where_clause}"
        f" ORDER BY observed_at {order}, byte_range_start {order}, event_id {order}"
        f" LIMIT ?"
    )
    # Fetch one extra row to detect "more pages exist".
    params.append(limit + 1)
    cur = conn.execute(sql, tuple(params))
    rows = cur.fetchall()
    has_more = len(rows) > limit
    page = [_row_to_event(r) for r in rows[:limit]]
    next_cursor: Optional[str] = None
    if has_more and page:
        next_cursor = encode_cursor(page[-1].event_id, reverse=reverse)
    return page, next_cursor


def select_pending_jsonl(conn: sqlite3.Connection, *, limit: int) -> list[EventRow]:
    """Return rows with ``jsonl_appended_at IS NULL`` for the FR-029 retry queue.

    Ordered by ``event_id ASC`` (oldest pending first).
    """
    if limit <= 0:
        raise ValueError(f"limit must be > 0; got {limit}")
    sql = (
        f"SELECT {_SELECT_FIELDS} FROM events "
        "WHERE jsonl_appended_at IS NULL "
        "ORDER BY event_id ASC LIMIT ?"
    )
    cur = conn.execute(sql, (limit,))
    return [_row_to_event(r) for r in cur.fetchall()]


def select_event_by_id(
    conn: sqlite3.Connection, event_id: int
) -> Optional[EventRow]:
    """Single-row lookup by ``event_id``."""
    sql = f"SELECT {_SELECT_FIELDS} FROM events WHERE event_id = ?"
    cur = conn.execute(sql, (event_id,))
    row = cur.fetchone()
    return _row_to_event(row) if row else None
