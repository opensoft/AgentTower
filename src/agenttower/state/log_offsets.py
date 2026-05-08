"""Typed dataclasses + read/write helpers for the FEAT-007 ``log_offsets`` table.

Helpers accept an open ``sqlite3.Connection``; transaction boundary is
owned by callers (LogService for attach/detach, FEAT-008 reader for
offset advancement).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


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
    conn.execute(
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
