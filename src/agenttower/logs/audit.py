"""JSONL audit-row writer for FEAT-007 ``log_attachment_change`` events (FR-044).

Every successful attachment status transition appends exactly one row to
the existing FEAT-001 ``events.jsonl`` file. No-op writes (FR-018
idempotent re-attach) and failed attaches (FR-045) MUST NOT append; the
service layer guards both.
"""

from __future__ import annotations

from pathlib import Path

from ..events import writer as events_writer


def append_log_attachment_change(
    events_file: Path | None,
    *,
    attachment_id: str,
    agent_id: str,
    prior_status: str | None,
    new_status: str,
    prior_path: str | None,
    new_path: str,
    prior_pipe_target: str | None,
    source: str,
    socket_peer_uid: int,
) -> None:
    """Append one ``log_attachment_change`` JSONL row (data-model.md §2)."""
    if events_file is None:
        return
    payload: dict[str, object] = {
        "type": "log_attachment_change",
        "payload": {
            "attachment_id": attachment_id,
            "agent_id": agent_id,
            "prior_status": prior_status,
            "new_status": new_status,
            "prior_path": prior_path,
            "new_path": new_path,
            "prior_pipe_target": prior_pipe_target,
            "source": source,
            "socket_peer_uid": int(socket_peer_uid),
        },
    }
    events_writer.append_event(events_file, payload)
