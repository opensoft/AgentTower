"""``events`` table DAO — FEAT-008 classifier events + FEAT-009 audit rows.

Surface:

* :class:`EventRow` — frozen dataclass mirroring the SQLite ``events``
  schema in ``data-model.md`` §2 (FEAT-008 shape).
* :class:`EventFilter` — query filter for ``events.list``.
* :func:`encode_cursor` / :func:`decode_cursor` — opaque pagination
  cursor codec (Research §R8). Cursor is integer-backed but
  base64url-encoded JSON at the CLI boundary.
* :func:`insert_event` — single-row insert for FEAT-008 classifier
  events; returns the new ``event_id``. Used inside the reader's
  FR-006 atomic SQLite + offset commit.
* :func:`insert_audit_event` — single-row insert for FEAT-009
  ``queue_message_*`` / ``routing_toggled`` audit events; NULL-fills
  the FEAT-008-specific columns made nullable by the v6 → v7 migration.
  Used by :class:`agenttower.routing.audit_writer.QueueAuditWriter` for
  the FR-046 dual-write (SQLite + JSONL).
* :func:`mark_jsonl_appended` — set ``jsonl_appended_at`` after a
  successful JSONL write (FR-029 watermark; reused by FEAT-009 audit).
* :func:`select_events` — page through events; returns
  ``(rows, next_cursor)``.
* :func:`select_pending_jsonl` — return rows whose
  ``jsonl_appended_at`` is NULL (FR-029 retry queue).
* :func:`select_event_by_id` — single-row lookup, used by the follow
  registry to confirm an event still exists.

This module is the production-side writer for BOTH FEAT-008 classifier
events and FEAT-009 audit events (per Clarifications session 2026-05-12
Q1 dual-write decision; data-model.md §7.1 column mapping). The FEAT-008
reader calls :func:`insert_event`; the FEAT-009 audit writer calls
:func:`insert_audit_event`. Both rows land in the same ``events``
table and are surfaced through the existing FEAT-008 ``events.list``
reader without a reader-side code change.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import dataclass, field
from typing import NamedTuple, Optional


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

    FEAT-009 audit rows (event_type in the ``queue_message_*`` set or
    ``routing_toggled``) store NULL for the FEAT-008-specific columns
    (``attachment_id`` / ``log_path`` / ``byte_range_*`` /
    ``line_offset_*`` / ``classifier_rule_id`` /
    ``debounce_window_*``). Those fields are typed ``Optional`` here
    so the decoder can return them faithfully.
    """

    event_id: int
    event_type: str
    agent_id: str
    attachment_id: Optional[str]
    log_path: Optional[str]
    byte_range_start: Optional[int]
    byte_range_end: Optional[int]
    line_offset_start: Optional[int]
    line_offset_end: Optional[int]
    observed_at: str
    record_at: Optional[str]
    excerpt: str
    classifier_rule_id: Optional[str]
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


# Upper bound for cursor event_id: SQLite stores INTEGER as int64,
# but the safe range across all SQLite builds (and JSON-number
# precision) is 2^53 - 1. A cursor with a higher value is treated
# as malformed rather than risk silent truncation.
_MAX_SAFE_CURSOR_EVENT_ID = (1 << 53) - 1
_NULL_BYTE_RANGE_CURSOR_SENTINEL = -1


def encode_cursor(
    event_id: int,
    *,
    reverse: bool,
    observed_at: str | None = None,
    byte_range_start: int | None = None,
) -> str:
    """Encode an opaque pagination cursor as base64url JSON.

    The CLI treats the result as opaque; clients MUST round-trip it
    verbatim. Padding ``=`` is stripped so the cursor fits in URL/CLI
    contexts without quoting.
    """
    if not isinstance(event_id, int) or isinstance(event_id, bool):
        raise CursorError(f"event_id must be int, got {type(event_id).__name__}")
    if event_id <= 0:
        raise CursorError(f"event_id must be > 0, got {event_id}")
    if event_id > _MAX_SAFE_CURSOR_EVENT_ID:
        raise CursorError(
            f"event_id {event_id} exceeds safe-cursor range "
            f"({_MAX_SAFE_CURSOR_EVENT_ID})"
        )
    if (observed_at is None) != (byte_range_start is None):
        raise CursorError(
            "observed_at and byte_range_start must be supplied together"
        )
    payload_obj: dict[str, object] = {"e": event_id, "r": bool(reverse)}
    if observed_at is not None:
        if not isinstance(observed_at, str) or not observed_at:
            raise CursorError("observed_at must be a non-empty string")
        if (
            not isinstance(byte_range_start, int)
            or isinstance(byte_range_start, bool)
            or byte_range_start < _NULL_BYTE_RANGE_CURSOR_SENTINEL
        ):
            raise CursorError(
                "byte_range_start must be >= -1 (-1 is the audit-row sentinel)"
            )
        payload_obj["o"] = observed_at
        payload_obj["b"] = byte_range_start
    payload = json.dumps(payload_obj, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor_payload(token: str) -> dict[str, object]:
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
    return obj


def _decode_cursor_base(obj: dict[str, object]) -> tuple[int, bool]:
    if "e" not in obj or "r" not in obj:
        raise CursorError("cursor payload missing required keys 'e' and 'r'")
    e = obj["e"]
    r = obj["r"]
    if not isinstance(e, int) or isinstance(e, bool):
        raise CursorError(f"cursor 'e' must be int, got {type(e).__name__}")
    if e <= 0:
        raise CursorError(f"cursor 'e' must be > 0, got {e}")
    if e > _MAX_SAFE_CURSOR_EVENT_ID:
        raise CursorError(
            f"cursor 'e' {e} exceeds safe-cursor range "
            f"({_MAX_SAFE_CURSOR_EVENT_ID})"
        )
    if not isinstance(r, bool):
        raise CursorError(f"cursor 'r' must be bool, got {type(r).__name__}")
    return e, r


def _decode_cursor_details(token: str) -> tuple[int, bool, str | None, int | None]:
    obj = _decode_cursor_payload(token)
    event_id, reverse = _decode_cursor_base(obj)
    observed_at = obj.get("o")
    byte_range_start = obj.get("b")
    if observed_at is None and byte_range_start is None:
        return event_id, reverse, None, None
    if not isinstance(observed_at, str) or not observed_at:
        raise CursorError("cursor 'o' must be a non-empty string")
    if (
        not isinstance(byte_range_start, int)
        or isinstance(byte_range_start, bool)
        or byte_range_start < _NULL_BYTE_RANGE_CURSOR_SENTINEL
    ):
        raise CursorError("cursor 'b' must be >= -1 (-1 is the audit-row sentinel)")
    return event_id, reverse, observed_at, byte_range_start


def decode_cursor(token: str) -> tuple[int, bool]:
    """Decode a cursor produced by :func:`encode_cursor`.

    Raises :class:`CursorError` on any malformed input. Forward-tolerant
    of new optional keys (ignored), but strict on the documented two
    keys' types.
    """
    obj = _decode_cursor_payload(token)
    return _decode_cursor_base(obj)


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
    """Insert a single event row for FEAT-008 classifier output;
    return the new ``event_id``.

    The caller MUST be inside an explicit transaction (the reader's
    FR-006 atomic SQLite + offset commit). ``row.event_id`` is ignored
    on insert — the SQLite ``INTEGER PRIMARY KEY AUTOINCREMENT`` value
    is what's authoritative.

    Audit rows (``queue_message_*`` / ``routing_toggled``) MUST be
    written via :func:`insert_audit_event` instead — those rows leave
    the FEAT-008-specific columns (``attachment_id`` / ``log_path`` /
    ``byte_range_*`` / ``line_offset_*`` / ``classifier_rule_id`` /
    ``debounce_window_*``) NULL, which this function explicitly
    forbids. The :class:`EventRow` dataclass types those fields as
    ``Optional`` so the read-side decoder can return them faithfully,
    but on the write side we still require non-NULL values for the
    classifier-row case.
    """
    if row.event_type not in _EVENT_TYPES:
        raise ValueError(
            f"event_type must be one of {_EVENT_TYPES}, got {row.event_type!r}"
        )
    # Validate non-NULL FEAT-008-specific fields BEFORE the numeric
    # comparisons (which would raise TypeError on None and obscure the
    # actual programmer error — calling insert_event() with an audit-
    # shaped row instead of routing the audit row through
    # ``insert_audit_event``).
    _required = {
        "attachment_id": row.attachment_id,
        "log_path": row.log_path,
        "classifier_rule_id": row.classifier_rule_id,
        "byte_range_start": row.byte_range_start,
        "byte_range_end": row.byte_range_end,
        "line_offset_start": row.line_offset_start,
        "line_offset_end": row.line_offset_end,
    }
    _missing = [name for name, value in _required.items() if value is None]
    if _missing:
        raise ValueError(
            "insert_event requires FEAT-008 classifier-row columns to "
            f"be non-NULL; missing: {sorted(_missing)}. Audit rows must "
            "go through insert_audit_event()."
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
    """Set ``jsonl_appended_at`` on a single row (FR-029 watermark).

    Used by both FEAT-008 (classifier rows) and FEAT-009 (audit rows)
    after their respective JSONL appends succeed.
    """
    conn.execute(
        "UPDATE events SET jsonl_appended_at = ? WHERE event_id = ? "
        "AND jsonl_appended_at IS NULL",
        (ts_iso, event_id),
    )


def insert_audit_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    agent_id: str,
    observed_at: str,
    excerpt: str,
    schema_version: int = 1,
    jsonl_appended_at: str | None = None,
) -> int:
    """Insert a FEAT-009 audit row into the ``events`` table.

    NULL-fills the FEAT-008-specific columns (``attachment_id``,
    ``log_path``, ``byte_range_start``, ``byte_range_end``,
    ``line_offset_start``, ``line_offset_end``, ``classifier_rule_id``,
    ``debounce_window_*``) made nullable by the v6 → v7 migration
    (data-model.md §2 events_new + §7.1 column mapping).

    Used by :class:`agenttower.routing.audit_writer.QueueAuditWriter`
    for the FR-046 dual-write — the SQLite INSERT is the source of
    truth (FR-048); the JSONL append is best-effort with a watermark.

    Caller MUST be inside an explicit transaction. ``event_type`` is
    validated against the closed set at the SQLite layer (the CHECK
    constraint rejects unknown values); we don't repeat the check
    here to keep this module decoupled from ``routing/errors.py``.

    Args:
        conn: SQLite connection (caller manages transaction).
        event_type: One of the 8 FEAT-009 audit types
            (``queue_message_*`` or ``routing_toggled``).
        agent_id: For ``queue_message_*`` rows this is the target's
            ``agent_id`` (data-model.md §7.1.1 — so ``events --target
            <agent>`` surfaces queue events delivered to that agent);
            for ``routing_toggled`` this is the operator identity
            (``host-operator`` since routing toggle is host-only).
        observed_at: Transition timestamp (canonical ISO 8601 ms UTC).
        excerpt: Redacted, whitespace-collapsed, ≤ 240-char excerpt
            (for ``queue_message_*``) or human summary (for
            ``routing_toggled``, e.g., ``"routing disabled (was enabled)"``).
        schema_version: Audit row schema version (default 1).
        jsonl_appended_at: Always ``None`` at initial insert; the caller
            invokes :func:`mark_jsonl_appended` after the JSONL write
            succeeds (Group-A walk Q6 / Clarifications Q1).

    Returns:
        The new ``event_id``.
    """
    cur = conn.execute(
        """
        INSERT INTO events (
            event_type,
            agent_id,
            attachment_id, log_path,
            byte_range_start, byte_range_end,
            line_offset_start, line_offset_end,
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
        ) VALUES (
            ?, ?,
            NULL, NULL,
            NULL, NULL,
            NULL, NULL,
            ?,
            NULL,
            ?,
            NULL,
            NULL,
            1,
            NULL,
            NULL,
            ?,
            ?
        )
        """,
        (event_type, agent_id, observed_at, excerpt, schema_version, jsonl_appended_at),
    )
    last_rowid = cur.lastrowid
    if last_rowid is None:
        raise sqlite3.OperationalError("insert_audit_event: lastrowid is None")
    return int(last_rowid)


_SELECT_FIELDS = (
    "event_id, event_type, agent_id, attachment_id, log_path, "
    "byte_range_start, byte_range_end, line_offset_start, line_offset_end, "
    "observed_at, record_at, excerpt, classifier_rule_id, "
    "debounce_window_id, debounce_collapsed_count, "
    "debounce_window_started_at, debounce_window_ended_at, "
    "schema_version, jsonl_appended_at"
)


def _row_to_event(row: tuple) -> EventRow:
    # FEAT-008 classifier rows populate every numeric column; FEAT-009
    # audit rows leave the byte_range / line_offset columns NULL.
    # ``int(None)`` raises TypeError, so cast only when the column has
    # a value — the dataclass already declares these Optional[int].
    def _opt_int(value: object) -> Optional[int]:
        return int(value) if value is not None else None  # type: ignore[arg-type]

    return EventRow(
        event_id=int(row[0]),
        event_type=row[1],
        agent_id=row[2],
        attachment_id=row[3],
        log_path=row[4],
        byte_range_start=_opt_int(row[5]),
        byte_range_end=_opt_int(row[6]),
        line_offset_start=_opt_int(row[7]),
        line_offset_end=_opt_int(row[8]),
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


class EventPage(NamedTuple):
    """P3 (review MEDIUM) — named result of :func:`select_events`.

    NamedTuple subclass so callers can either use named access
    (``page.rows`` / ``page.next_cursor``) or continue tuple-unpacking
    (``rows, next_cursor = select_events(...)``). Both forms work
    interchangeably; new code SHOULD prefer named access.
    """

    rows: list[EventRow]
    next_cursor: Optional[str]


def select_events(
    conn: sqlite3.Connection,
    *,
    filter: EventFilter,
    cursor: Optional[str],
    limit: int,
    reverse: bool,
) -> EventPage:
    """Page through events.

    Returns ``(rows, next_cursor)``; ``next_cursor`` is None when this
    page is the last. Default ordering is per FR-028:
    ``(observed_at ASC, byte_range_start ASC, event_id ASC)`` —
    flipped when ``reverse=True``.

    New cursors encode the last seen sort tuple
    ``(observed_at, byte_range_start, event_id)`` so the next page
    returns rows strictly past it (forward) or strictly before it
    (reverse). Older event_id-only cursors remain accepted.
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
        (
            cursor_event_id,
            cursor_reverse,
            cursor_observed_at,
            cursor_byte_start,
        ) = _decode_cursor_details(cursor)
        if cursor_reverse != reverse:
            raise CursorError(
                "cursor direction does not match query direction; cursors are "
                "single-direction (encode forward → use forward; encode reverse → "
                "use reverse)"
            )
        if cursor_observed_at is not None and cursor_byte_start is not None:
            if reverse:
                where.append(
                    "((observed_at < ?) OR "
                    "(observed_at = ? AND COALESCE(byte_range_start, -1) < ?) OR "
                    "(observed_at = ? AND COALESCE(byte_range_start, -1) = ? AND event_id < ?))"
                )
            else:
                where.append(
                    "((observed_at > ?) OR "
                    "(observed_at = ? AND COALESCE(byte_range_start, -1) > ?) OR "
                    "(observed_at = ? AND COALESCE(byte_range_start, -1) = ? AND event_id > ?))"
                )
            params.extend(
                [
                    cursor_observed_at,
                    cursor_observed_at,
                    cursor_byte_start,
                    cursor_observed_at,
                    cursor_byte_start,
                    cursor_event_id,
                ]
            )
        else:
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
        f" ORDER BY observed_at {order}, COALESCE(byte_range_start, -1) {order}, event_id {order}"
        " LIMIT ?"
    )
    # Fetch one extra row to detect "more pages exist".
    params.append(limit + 1)
    cur = conn.execute(sql, tuple(params))
    rows = cur.fetchall()
    has_more = len(rows) > limit
    page = [_row_to_event(r) for r in rows[:limit]]
    next_cursor: Optional[str] = None
    if has_more and page:
        next_cursor = encode_cursor(
            page[-1].event_id,
            reverse=reverse,
            observed_at=page[-1].observed_at,
            byte_range_start=(
                page[-1].byte_range_start
                if page[-1].byte_range_start is not None
                else _NULL_BYTE_RANGE_CURSOR_SENTINEL
            ),
        )
    return EventPage(rows=page, next_cursor=next_cursor)


def select_pending_jsonl(conn: sqlite3.Connection, *, limit: int) -> list[EventRow]:
    """Return rows with ``jsonl_appended_at IS NULL`` for the FR-029 retry queue.

    Ordered by ``event_id ASC`` (oldest pending first).

    Excludes FEAT-009 audit rows (``queue_message_*`` /
    ``routing_toggled``). Those rows live in the shared ``events``
    table but use a different JSONL schema; their watermark is owned
    by :class:`agenttower.routing.audit_writer.QueueAuditWriter` via
    :meth:`drain_pending`. If the FEAT-008 EventsReader retry loop
    picked them up here, it would re-emit them with the durable-event
    JSONL shape (with many NULL fields) instead of the FEAT-009
    queue/routing audit shape, violating the
    contracts/queue-audit-schema.md contract.
    """
    if limit <= 0:
        raise ValueError(f"limit must be > 0; got {limit}")
    placeholders = ", ".join(["?"] * len(_EVENT_TYPES))
    sql = (
        f"SELECT {_SELECT_FIELDS} FROM events "
        "WHERE jsonl_appended_at IS NULL "
        f"AND event_type IN ({placeholders}) "
        "ORDER BY event_id ASC LIMIT ?"
    )
    cur = conn.execute(sql, (*_EVENT_TYPES, limit))
    return [_row_to_event(r) for r in cur.fetchall()]


def select_event_by_id(
    conn: sqlite3.Connection, event_id: int
) -> Optional[EventRow]:
    """Single-row lookup by ``event_id``."""
    sql = f"SELECT {_SELECT_FIELDS} FROM events WHERE event_id = ?"
    cur = conn.execute(sql, (event_id,))
    row = cur.fetchone()
    return _row_to_event(row) if row else None


__all__ = [
    "EventRow",
    "EventFilter",
    "EventPage",
    "CursorError",
    "encode_cursor",
    "decode_cursor",
    "insert_event",
    "mark_jsonl_appended",
    "select_events",
    "select_pending_jsonl",
    "select_event_by_id",
]
