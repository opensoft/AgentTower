"""Typed dataclasses + read/write helpers for the FEAT-007 ``log_attachments`` table.

Helpers accept an open ``sqlite3.Connection`` and do NOT begin or commit
transactions on their own. The transaction boundary belongs to
:class:`agenttower.logs.service.LogService`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..agents.mutex import PaneCompositeKey


@dataclass(frozen=True)
class LogAttachmentRecord:
    """One row of the ``log_attachments`` table (data-model.md §1.1)."""

    attachment_id: str
    agent_id: str
    container_id: str
    tmux_socket_path: str
    tmux_session_name: str
    tmux_window_index: int
    tmux_pane_index: int
    tmux_pane_id: str
    log_path: str
    status: str
    source: str
    pipe_pane_command: str
    prior_pipe_target: str | None
    attached_at: str
    last_status_at: str
    superseded_at: str | None
    superseded_by: str | None
    created_at: str

    @property
    def composite_key(self) -> PaneCompositeKey:
        return (
            self.container_id,
            self.tmux_socket_path,
            self.tmux_session_name,
            self.tmux_window_index,
            self.tmux_pane_index,
            self.tmux_pane_id,
        )


VALID_STATUSES: tuple[str, ...] = ("active", "superseded", "stale", "detached")
VALID_SOURCES: tuple[str, ...] = ("explicit", "register_self")


_COLUMNS = (
    "attachment_id, agent_id, container_id, tmux_socket_path, "
    "tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id, "
    "log_path, status, source, pipe_pane_command, prior_pipe_target, "
    "attached_at, last_status_at, superseded_at, superseded_by, created_at"
)


def _row_to_record(row: tuple) -> LogAttachmentRecord:
    return LogAttachmentRecord(
        attachment_id=row[0],
        agent_id=row[1],
        container_id=row[2],
        tmux_socket_path=row[3],
        tmux_session_name=row[4],
        tmux_window_index=int(row[5]),
        tmux_pane_index=int(row[6]),
        tmux_pane_id=row[7],
        log_path=row[8],
        status=row[9],
        source=row[10],
        pipe_pane_command=row[11],
        prior_pipe_target=row[12],
        attached_at=row[13],
        last_status_at=row[14],
        superseded_at=row[15],
        superseded_by=row[16],
        created_at=row[17],
    )


def insert(conn: sqlite3.Connection, record: LogAttachmentRecord) -> None:
    """Insert a fresh attachment row (data-model.md §1.1)."""
    if record.status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {record.status!r}")
    if record.source not in VALID_SOURCES:
        raise ValueError(f"invalid source: {record.source!r}")
    conn.execute(
        f"INSERT INTO log_attachments ({_COLUMNS}) VALUES "
        f"({','.join(['?'] * 18)})",
        (
            record.attachment_id,
            record.agent_id,
            record.container_id,
            record.tmux_socket_path,
            record.tmux_session_name,
            record.tmux_window_index,
            record.tmux_pane_index,
            record.tmux_pane_id,
            record.log_path,
            record.status,
            record.source,
            record.pipe_pane_command,
            record.prior_pipe_target,
            record.attached_at,
            record.last_status_at,
            record.superseded_at,
            record.superseded_by,
            record.created_at,
        ),
    )


def update_status(
    conn: sqlite3.Connection,
    *,
    attachment_id: str,
    new_status: str,
    last_status_at: str,
    superseded_at: str | None = None,
    superseded_by: str | None = None,
) -> None:
    """Update an existing row's status + timestamps."""
    if new_status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {new_status!r}")
    conn.execute(
        """
        UPDATE log_attachments
           SET status = ?, last_status_at = ?,
               superseded_at = ?, superseded_by = ?
         WHERE attachment_id = ?
        """,
        (new_status, last_status_at, superseded_at, superseded_by, attachment_id),
    )


def select_active_for_agent_path(
    conn: sqlite3.Connection, *, agent_id: str, log_path: str
) -> LogAttachmentRecord | None:
    """Return the active row for ``(agent_id, log_path)`` or None."""
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM log_attachments "
        "WHERE agent_id = ? AND log_path = ? AND status = 'active'",
        (agent_id, log_path),
    )
    row = cur.fetchone()
    return _row_to_record(row) if row else None


def select_for_agent_path(
    conn: sqlite3.Connection, *, agent_id: str, log_path: str
) -> LogAttachmentRecord | None:
    """Return the most recent row for ``(agent_id, log_path)`` regardless of status, or None."""
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM log_attachments "
        "WHERE agent_id = ? AND log_path = ? "
        "ORDER BY last_status_at DESC LIMIT 1",
        (agent_id, log_path),
    )
    row = cur.fetchone()
    return _row_to_record(row) if row else None


def select_active_by_log_path(
    conn: sqlite3.Connection, *, log_path: str
) -> LogAttachmentRecord | None:
    """Return the active row owning ``log_path`` (any agent), or None."""
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM log_attachments "
        "WHERE log_path = ? AND status = 'active'",
        (log_path,),
    )
    row = cur.fetchone()
    return _row_to_record(row) if row else None


def select_active_for_agent(
    conn: sqlite3.Connection, *, agent_id: str
) -> LogAttachmentRecord | None:
    """Return the (single) active row for ``agent_id`` if any."""
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM log_attachments "
        "WHERE agent_id = ? AND status = 'active' "
        "ORDER BY last_status_at DESC LIMIT 1",
        (agent_id,),
    )
    row = cur.fetchone()
    return _row_to_record(row) if row else None


def select_most_recent_for_agent(
    conn: sqlite3.Connection, *, agent_id: str
) -> LogAttachmentRecord | None:
    """Return the most recent row for ``agent_id`` regardless of status, or None.

    Used by ``--status`` (FR-032) and ``--preview`` (FR-033).
    """
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM log_attachments "
        "WHERE agent_id = ? "
        "ORDER BY last_status_at DESC LIMIT 1",
        (agent_id,),
    )
    row = cur.fetchone()
    return _row_to_record(row) if row else None


def cascade_to_stale_for_panes(
    conn: sqlite3.Connection,
    *,
    pane_keys: list,
    now_iso: str,
) -> list[LogAttachmentRecord]:
    """Flip every active row bound to one of *pane_keys* to ``status=stale``.

    Returns the affected rows BEFORE the update so the caller can emit one
    ``log_attachment_change`` audit row per affected attachment (FR-042 +
    FR-044). The caller MUST append audit rows AFTER the SQLite COMMIT,
    mirroring the FEAT-006 cascade-then-audit pattern.

    ``pane_keys`` is the list of FEAT-004 pane composite keys
    ``(container_id, socket_path, session_name, window_index, pane_index, pane_id)``
    that the FEAT-004 reconcile is flipping to ``active=0``.
    """
    if not pane_keys:
        return []

    affected: list[LogAttachmentRecord] = []
    for key in pane_keys:
        cur = conn.execute(
            f"SELECT {_COLUMNS} FROM log_attachments "
            "WHERE container_id = ? AND tmux_socket_path = ? "
            "AND tmux_session_name = ? AND tmux_window_index = ? "
            "AND tmux_pane_index = ? AND tmux_pane_id = ? "
            "AND status = 'active'",
            tuple(key),
        )
        affected.extend(_row_to_record(r) for r in cur.fetchall())

    for record in affected:
        conn.execute(
            "UPDATE log_attachments SET status = 'stale', last_status_at = ? "
            "WHERE attachment_id = ?",
            (now_iso, record.attachment_id),
        )
    return affected


def select_actives_for_pane(
    conn: sqlite3.Connection,
    *,
    container_id: str,
    tmux_socket_path: str,
    tmux_session_name: str,
    tmux_window_index: int,
    tmux_pane_index: int,
    tmux_pane_id: str,
) -> list[LogAttachmentRecord]:
    """Return every ``status=active`` row bound to a given pane composite key.

    Used by FEAT-004 reconcile (FR-042) to flip active rows to stale.
    """
    cur = conn.execute(
        f"SELECT {_COLUMNS} FROM log_attachments "
        "WHERE container_id = ? AND tmux_socket_path = ? "
        "AND tmux_session_name = ? AND tmux_window_index = ? "
        "AND tmux_pane_index = ? AND tmux_pane_id = ? "
        "AND status = 'active'",
        (
            container_id,
            tmux_socket_path,
            tmux_session_name,
            tmux_window_index,
            tmux_pane_index,
            tmux_pane_id,
        ),
    )
    return [_row_to_record(r) for r in cur.fetchall()]
