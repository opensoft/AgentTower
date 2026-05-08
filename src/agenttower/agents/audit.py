"""JSONL audit-row writer for FEAT-006 role transitions (FR-014).

Every successful role transition (creation OR change) appends one row
to the existing FEAT-001 ``events.jsonl`` file via the shared
``events.writer.append_event`` helper. The on-disk record is the
standard nested envelope — ``{"ts": <utc-iso>, "type":
"agent_role_change", "payload": {...}}`` — with ``ts`` prepended by
the writer and FEAT-006-specific fields nested under ``payload``.

``payload.prior_role`` is JSON ``null`` on creation (Clarifications
Q4); ``payload.confirm_provided`` is the literal request value
(Clarifications session 2026-05-07-continued Q5).

No-op writes (FR-027) and failed writes (FR-014, FR-035) MUST NOT
append. The service layer guards both.
"""

from __future__ import annotations

from pathlib import Path

from ..events import writer as events_writer


def append_role_change(
    events_file: Path | None,
    *,
    agent_id: str,
    prior_role: str | None,
    new_role: str,
    confirm_provided: bool,
    socket_peer_uid: int,
) -> None:
    """Append one ``agent_role_change`` JSONL row.

    *events_file* may be ``None`` (e.g., daemon context that is not
    wired to an events writer in tests) — in that case this is a no-op
    so the unit tests for the service layer can run without a real
    file path. In production the daemon always wires the file.
    """
    if events_file is None:
        return
    payload: dict[str, object] = {
        "type": "agent_role_change",
        "payload": {
            "agent_id": agent_id,
            "prior_role": prior_role,
            "new_role": new_role,
            "confirm_provided": bool(confirm_provided),
            "socket_peer_uid": int(socket_peer_uid),
        },
    }
    events_writer.append_event(events_file, payload)
