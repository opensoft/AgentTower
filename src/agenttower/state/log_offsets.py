"""Typed dataclasses + read/write helpers for the FEAT-007 ``log_offsets`` table.

Helpers accept an open ``sqlite3.Connection``; transaction boundary is
owned by callers (LogService for attach/detach, FEAT-008 reader for
offset advancement).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum


class FileChangeKind(str, Enum):
    """Outcome of one ``detect_file_change`` call (FR-024 / FR-025 / FR-026)."""

    UNCHANGED = "unchanged"
    TRUNCATED = "truncated"
    RECREATED = "recreated"
    MISSING = "missing"


def detect_file_change(
    host_path: str,
    stored_inode: str | None,
    stored_size_seen: int,
) -> FileChangeKind:
    """Classify what changed at ``host_path`` relative to stored observation.

    Pure classifier consumed by FEAT-008 reader cycles (via
    ``logs.reader_recovery.reader_cycle_offset_recovery``) and by
    ``LogService.attach_log`` for the FR-021 file-consistency check.

    Returns:
        ``MISSING`` — file does not exist (FR-026).
        ``RECREATED`` — file exists with a different inode than stored
            (FR-025). Wins over ``TRUNCATED`` when both could apply.
        ``TRUNCATED`` — same inode, file is smaller than ``stored_size_seen``
            (FR-024).
        ``UNCHANGED`` — everything else, including the first-observation
            case where ``stored_inode is None``. The first reader cycle
            after attach records the observation through
            ``update_file_observation``; subsequent cycles compare against it.
    """
    # Layer note: ``state`` typically does not import ``logs``, but T180
    # specifies this helper lives here for cohesion with the offsets DAO
    # (data-model.md §1.2 / spec FR-024..FR-026).
    from ..logs.host_fs import stat_log_file

    stat = stat_log_file(host_path)
    if stat is None:
        return FileChangeKind.MISSING
    if stored_inode is None:
        return FileChangeKind.UNCHANGED
    if stat.inode != stored_inode:
        return FileChangeKind.RECREATED
    if stat.size < stored_size_seen:
        return FileChangeKind.TRUNCATED
    return FileChangeKind.UNCHANGED


@dataclass(frozen=True)
class LogOffsetRecord:
    """One row of the ``log_offsets`` table (data-model.md §1.2)."""

    agent_id: str
    log_path: str
    byte_offset: int
    line_offset: int
    last_event_offset: int
    last_output_at: str | None
    file_inode: str | None
    file_size_seen: int
    created_at: str
    updated_at: str


_COLUMNS = (
    "agent_id, log_path, byte_offset, line_offset, last_event_offset, "
    "last_output_at, file_inode, file_size_seen, created_at, updated_at"
)


def _row_to_record(row: tuple) -> LogOffsetRecord:
    return LogOffsetRecord(
        agent_id=row[0],
        log_path=row[1],
        byte_offset=int(row[2]),
        line_offset=int(row[3]),
        last_event_offset=int(row[4]),
        last_output_at=row[5],
        file_inode=row[6],
        file_size_seen=int(row[7]),
        created_at=row[8],
        updated_at=row[9],
    )


def insert_initial(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    log_path: str,
    timestamp: str,
) -> None:
    """Insert a fresh ``(0, 0, 0, NULL, NULL, 0)`` row (FR-015)."""
    conn.execute(
        f"INSERT INTO log_offsets ({_COLUMNS}) VALUES "
        "(?, ?, 0, 0, 0, NULL, NULL, 0, ?, ?)",
        (agent_id, log_path, timestamp, timestamp),
    )


def select(
    conn: sqlite3.Connection, *, agent_id: str, log_path: str
) -> LogOffsetRecord | None:
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM log_offsets "
        "WHERE agent_id = ? AND log_path = ?",
        (agent_id, log_path),
    )
    row = cur.fetchone()
    return _row_to_record(row) if row else None


def reset(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    log_path: str,
    file_inode: str | None,
    file_size_seen: int,
    timestamp: str,
) -> None:
    """Reset offsets to (0, 0, 0); update inode + size (FR-024 / FR-025)."""
    conn.execute(
        """
        UPDATE log_offsets
           SET byte_offset = 0, line_offset = 0, last_event_offset = 0,
               file_inode = ?, file_size_seen = ?, updated_at = ?
         WHERE agent_id = ? AND log_path = ?
        """,
        (file_inode, file_size_seen, timestamp, agent_id, log_path),
    )


def update_file_observation(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    log_path: str,
    file_inode: str | None,
    file_size_seen: int,
    last_output_at: str | None,
    timestamp: str,
) -> None:
    """Update file observation columns without touching offsets."""
    conn.execute(
        """
        UPDATE log_offsets
           SET file_inode = ?, file_size_seen = ?, last_output_at = ?,
               updated_at = ?
         WHERE agent_id = ? AND log_path = ?
        """,
        (file_inode, file_size_seen, last_output_at, timestamp, agent_id, log_path),
    )


def _require_one_updated(cur: sqlite3.Cursor, *, operation: str) -> None:
    if cur.rowcount != 1:
        raise sqlite3.OperationalError(
            f"{operation}: expected to update 1 log_offsets row; "
            f"updated {cur.rowcount}"
        )


def advance_offset(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    log_path: str,
    byte_offset: int,
    line_offset: int,
    last_event_offset: int,
    file_inode: str | None,
    file_size_seen: int,
    last_output_at: str | None,
    timestamp: str,
) -> None:
    """Production-side offset advance (FEAT-008 FR-004).

    The FEAT-008 reader (and ONLY the FEAT-008 reader, per the
    spec) calls this inside its FR-006 atomic SQLite + offset commit.
    Other production callers MUST NOT import this — the AST gate
    at ``tests/unit/test_logs_offset_advance_invariant.py`` enforces
    the prohibition on raw ``UPDATE log_offsets`` SQL in
    ``src/agenttower/events/``, so the only legitimate path is via
    this function (or via the FEAT-007 helpers ``reset`` /
    ``update_file_observation`` which DON'T touch byte/line offsets).

    Raises ``sqlite3.OperationalError`` if the target row does not
    exist; callers rely on this to roll back the paired event insert
    rather than silently re-reading the same bytes next cycle.
    """
    cur = conn.execute(
        """
        UPDATE log_offsets
           SET byte_offset = ?, line_offset = ?, last_event_offset = ?,
               file_inode = ?, file_size_seen = ?, last_output_at = ?,
               updated_at = ?
         WHERE agent_id = ? AND log_path = ?
        """,
        (
            byte_offset,
            line_offset,
            last_event_offset,
            file_inode,
            file_size_seen,
            last_output_at,
            timestamp,
            agent_id,
            log_path,
        ),
    )
    _require_one_updated(cur, operation="advance_offset")


def advance_offset_for_test(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    log_path: str,
    byte_offset: int,
    line_offset: int,
    last_event_offset: int,
    file_inode: str | None,
    file_size_seen: int,
    last_output_at: str | None,
    timestamp: str,
) -> None:
    """TEST SEAM: advance offsets to a specific position (US2 / SC-003 / SC-006).

    Production code MUST NOT call this — the future FEAT-008 reader is the
    sole production-side advancer of offsets (FR-022 / FR-023). Function name
    starts with ``advance_offset_for_test`` to make accidental imports loud.
    """
    cur = conn.execute(
        """
        UPDATE log_offsets
           SET byte_offset = ?, line_offset = ?, last_event_offset = ?,
               file_inode = ?, file_size_seen = ?, last_output_at = ?,
               updated_at = ?
         WHERE agent_id = ? AND log_path = ?
        """,
        (
            byte_offset,
            line_offset,
            last_event_offset,
            file_inode,
            file_size_seen,
            last_output_at,
            timestamp,
            agent_id,
            log_path,
        ),
    )
    _require_one_updated(cur, operation="advance_offset_for_test")
