"""Reader-cycle helper: translate one file-change observation into state.

The FEAT-008 reader will call :func:`reader_cycle_offset_recovery` once per
attached row per cycle. Behavior table (FR-024 / FR-025 / FR-026):

* ``UNCHANGED`` against an active row → no-op (offsets advance via
  FEAT-008's reader, not here).
* ``UNCHANGED`` against a stale row whose file is now present → emit
  ``log_file_returned`` (FR-061 triple-suppressed); status stays stale,
  offsets unchanged.
* ``TRUNCATED`` against an active row → reset offsets, preserve
  ``file_inode``, update ``file_size_seen``, emit ``log_rotation_detected``.
* ``RECREATED`` against an active row → reset offsets, update
  ``file_inode`` + ``file_size_seen``, emit ``log_rotation_detected``.
* ``MISSING`` against an active row → flip ``active → stale``, emit
  ``log_file_missing``, append one ``log_attachment_change`` audit row,
  leave offsets byte-for-byte (FR-026).
* ``MISSING`` against a stale row → emit ``log_file_missing`` (suppression
  swallows the second emit per FR-061); no state change.

The state mutation runs inside one short ``BEGIN IMMEDIATE``. Audit
rows are appended after COMMIT (mirrors the ``pane_service`` cascade
pattern in ``discovery/pane_service.py``).

This module is the FEAT-008 reader's only entry point into FEAT-007's
status / offset machinery; the FEAT-008 reader does not touch
``log_attachments`` or ``log_offsets`` directly.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import audit as logs_audit
from . import host_fs as host_fs_mod
from . import lifecycle as logs_lifecycle
from ..socket_api.lifecycle import LifecycleLogger
from ..state import log_attachments as la_state
from ..state import log_offsets as lo_state


@dataclass(frozen=True)
class ReaderCycleResult:
    """Outcome of one reader-cycle observation."""

    change: lo_state.FileChangeKind
    state_mutated: bool
    lifecycle_event_emitted: Optional[str]
    audit_row_appended: bool


_NOOP_RESULT = ReaderCycleResult(
    change=lo_state.FileChangeKind.UNCHANGED,
    state_mutated=False,
    lifecycle_event_emitted=None,
    audit_row_appended=False,
)


def _select_attachment_for_recovery(
    conn: sqlite3.Connection, *, agent_id: str, log_path: str
) -> la_state.LogAttachmentRecord | None:
    """Find the most recent active-or-stale attachment for ``(agent_id, log_path)``.

    Detached and superseded rows are out of scope for the reader cycle —
    detach is operator-initiated and superseded rows are already replaced.
    """
    candidate = la_state.select_active_for_agent_path(
        conn, agent_id=agent_id, log_path=log_path
    )
    if candidate is not None:
        return candidate
    # Fall back to most-recent across all statuses, but only return if it
    # happens to be stale at the same path.
    most_recent = la_state.select_most_recent_for_agent(conn, agent_id=agent_id)
    if most_recent is None:
        return None
    if most_recent.log_path != log_path or most_recent.status != "stale":
        return None
    return most_recent


def _daemon_uid() -> int:
    try:
        return os.geteuid()
    except OSError:
        return -1


def reader_cycle_offset_recovery(
    *,
    conn: sqlite3.Connection,
    events_file: Path | None,
    lifecycle_logger: LifecycleLogger | None,
    agent_id: str,
    log_path: str,
    timestamp: str,
) -> ReaderCycleResult:
    """Apply one reader-cycle observation for ``(agent_id, log_path)``.

    The ``conn`` MUST be opened with ``isolation_level=None`` so this helper
    can drive ``BEGIN IMMEDIATE`` / ``COMMIT`` explicitly. Audit rows are
    appended to ``events_file`` AFTER the SQLite commit because the FEAT-001
    events writer is an out-of-band JSONL append.
    """
    attachment = _select_attachment_for_recovery(
        conn, agent_id=agent_id, log_path=log_path
    )
    offset_row = lo_state.select(conn, agent_id=agent_id, log_path=log_path)

    # If no row is bound to this (agent_id, log_path), the reader cycle has
    # nothing to do. Returning a MISSING-shaped no-op is least surprising.
    if attachment is None or offset_row is None:
        return ReaderCycleResult(
            change=lo_state.FileChangeKind.MISSING,
            state_mutated=False,
            lifecycle_event_emitted=None,
            audit_row_appended=False,
        )

    current_stat = host_fs_mod.stat_log_file(log_path)

    # ---------- REAPPEARED branch (FR-026) ----------
    # Stale + file present → exactly one ``log_file_returned`` per triple,
    # row remains stale, offsets unchanged.
    if attachment.status == "stale" and current_stat is not None:
        emitted = logs_lifecycle.emit_log_file_returned(
            lifecycle_logger,
            agent_id=agent_id,
            log_path=log_path,
            prior_inode=offset_row.file_inode,
            new_inode=current_stat.inode,
            new_size=current_stat.size,
        )
        return ReaderCycleResult(
            change=lo_state.FileChangeKind.UNCHANGED,
            state_mutated=False,
            lifecycle_event_emitted="log_file_returned" if emitted else None,
            audit_row_appended=False,
        )

    # Pure classifier — same logic as detect_file_change but reusing the
    # stat we already took above to avoid a second syscall.
    change = _classify_from_stat(
        current_stat, offset_row.file_inode, offset_row.file_size_seen
    )

    if change is lo_state.FileChangeKind.UNCHANGED:
        return _NOOP_RESULT

    if attachment.status != "active" and change is not lo_state.FileChangeKind.MISSING:
        # Truncation/recreation against a non-active row is meaningless —
        # nobody is reading. Fall through silently.
        return ReaderCycleResult(
            change=change,
            state_mutated=False,
            lifecycle_event_emitted=None,
            audit_row_appended=False,
        )

    if change is lo_state.FileChangeKind.MISSING:
        return _handle_missing(
            conn=conn,
            events_file=events_file,
            lifecycle_logger=lifecycle_logger,
            attachment=attachment,
            offset_row=offset_row,
            timestamp=timestamp,
        )

    # TRUNCATED or RECREATED against an active row.
    return _handle_rotation(
        conn=conn,
        lifecycle_logger=lifecycle_logger,
        attachment=attachment,
        offset_row=offset_row,
        current_stat=current_stat,  # not None: change is not MISSING
        change=change,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Branch helpers
# ---------------------------------------------------------------------------


def _classify_from_stat(
    current_stat: host_fs_mod.FileStat | None,
    stored_inode: str | None,
    stored_size_seen: int,
) -> lo_state.FileChangeKind:
    """Stat-driven variant of :func:`state.log_offsets.detect_file_change`."""
    if current_stat is None:
        return lo_state.FileChangeKind.MISSING
    if stored_inode is None:
        return lo_state.FileChangeKind.UNCHANGED
    if current_stat.inode != stored_inode:
        return lo_state.FileChangeKind.RECREATED
    if current_stat.size < stored_size_seen:
        return lo_state.FileChangeKind.TRUNCATED
    return lo_state.FileChangeKind.UNCHANGED


def _handle_rotation(
    *,
    conn: sqlite3.Connection,
    lifecycle_logger: LifecycleLogger | None,
    attachment: la_state.LogAttachmentRecord,
    offset_row: lo_state.LogOffsetRecord,
    current_stat: host_fs_mod.FileStat,
    change: lo_state.FileChangeKind,
    timestamp: str,
) -> ReaderCycleResult:
    """Handle TRUNCATED or RECREATED against an active row (FR-024 / FR-025)."""
    # FR-024: truncation preserves the inode. FR-025: recreation updates it.
    new_inode_for_row = (
        offset_row.file_inode
        if change is lo_state.FileChangeKind.TRUNCATED
        else current_stat.inode
    )
    conn.execute("BEGIN IMMEDIATE")
    try:
        lo_state.reset(
            conn,
            agent_id=attachment.agent_id,
            log_path=attachment.log_path,
            file_inode=new_inode_for_row,
            file_size_seen=current_stat.size,
            timestamp=timestamp,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    emitted = logs_lifecycle.emit_log_rotation_detected(
        lifecycle_logger,
        agent_id=attachment.agent_id,
        log_path=attachment.log_path,
        prior_inode=offset_row.file_inode,
        new_inode=new_inode_for_row,
        prior_size=offset_row.file_size_seen,
        new_size=current_stat.size,
    )
    return ReaderCycleResult(
        change=change,
        state_mutated=True,
        lifecycle_event_emitted="log_rotation_detected" if emitted else None,
        audit_row_appended=False,
    )


def _handle_missing(
    *,
    conn: sqlite3.Connection,
    events_file: Path | None,
    lifecycle_logger: LifecycleLogger | None,
    attachment: la_state.LogAttachmentRecord,
    offset_row: lo_state.LogOffsetRecord,
    timestamp: str,
) -> ReaderCycleResult:
    """Handle MISSING against active or stale rows (FR-026)."""
    if attachment.status == "active":
        # Flip active → stale in one BEGIN IMMEDIATE; emit lifecycle and
        # audit AFTER commit (mirrors pane_service cascade).
        conn.execute("BEGIN IMMEDIATE")
        try:
            la_state.update_status(
                conn,
                attachment_id=attachment.attachment_id,
                new_status="stale",
                last_status_at=timestamp,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        emitted = logs_lifecycle.emit_log_file_missing(
            lifecycle_logger,
            agent_id=attachment.agent_id,
            log_path=attachment.log_path,
            last_known_inode=offset_row.file_inode,
            last_known_size=offset_row.file_size_seen,
        )
        logs_audit.append_log_attachment_change(
            events_file,
            attachment_id=attachment.attachment_id,
            agent_id=attachment.agent_id,
            prior_status="active",
            new_status="stale",
            prior_path=attachment.log_path,
            new_path=attachment.log_path,
            prior_pipe_target=None,
            source="explicit",
            socket_peer_uid=_daemon_uid(),
        )
        return ReaderCycleResult(
            change=lo_state.FileChangeKind.MISSING,
            state_mutated=True,
            lifecycle_event_emitted="log_file_missing" if emitted else None,
            audit_row_appended=True,
        )

    # status == "stale" already; second cycle on a still-missing file.
    # Suppression makes the emit a no-op (FR-061). Surface the result so
    # callers can confirm the reader is idempotent.
    emitted = logs_lifecycle.emit_log_file_missing(
        lifecycle_logger,
        agent_id=attachment.agent_id,
        log_path=attachment.log_path,
        last_known_inode=offset_row.file_inode,
        last_known_size=offset_row.file_size_seen,
    )
    return ReaderCycleResult(
        change=lo_state.FileChangeKind.MISSING,
        state_mutated=False,
        lifecycle_event_emitted="log_file_missing" if emitted else None,
        audit_row_appended=False,
    )


