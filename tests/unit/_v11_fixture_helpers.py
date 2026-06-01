"""Shared schema-aware seed helpers for FEAT-014 v1.1 unit tests.

Production schema in ``agenttower.state.schema`` has many NOT NULL + CHECK
constraints; tests use these wrappers to insert minimally-valid rows
without repeating the column lists.

The helpers commit each insert so callers can read-after-write within the
same connection.
"""

from __future__ import annotations

from typing import Any

_ISO_TS = "2025-01-01T00:00:00Z"


def seed_container(
    conn: Any,
    *,
    container_id: str = "c1",
    active: int = 1,
) -> None:
    conn.execute(
        """
        INSERT INTO containers (
            container_id, name, image, status, active,
            first_seen_at, last_scanned_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            container_id,
            f"container-{container_id}",
            "ubuntu:24.04",
            "running" if active else "exited",
            active,
            _ISO_TS,
            _ISO_TS,
        ),
    )
    conn.commit()


def seed_pane(
    conn: Any,
    *,
    container_id: str = "c1",
    pane_index: int = 0,
    active: int = 1,
) -> str:
    """Insert a minimally-valid pane row. Returns ``tmux_pane_id`` so the
    caller can reference it from an agent insert."""
    tmux_pane_id = f"%{pane_index}"
    conn.execute(
        """
        INSERT INTO panes (
            container_id, tmux_socket_path, tmux_session_name,
            tmux_window_index, tmux_pane_index, tmux_pane_id,
            container_name, container_user, pane_pid, pane_tty,
            pane_current_command, pane_current_path, pane_title,
            pane_active, active, first_seen_at, last_scanned_at
        ) VALUES (
            ?, '/tmp/tmux.sock', 'sess', 0, ?, ?,
            ?, 'bench', ?, '/dev/pts/0',
            'bash', '/srv/work', '', 1, ?, ?, ?
        )
        """,
        (
            container_id,
            pane_index,
            tmux_pane_id,
            f"container-{container_id}",
            1234 + pane_index,
            active,
            _ISO_TS,
            _ISO_TS,
        ),
    )
    conn.commit()
    return tmux_pane_id


def seed_agent(
    conn: Any,
    *,
    agent_id: str,
    container_id: str = "c1",
    pane_index: int = 0,
    active: int = 1,
    role: str = "master",  # closed set: master/slave/swarm/test-runner/shell/unknown
    capability: str = "shell",  # closed set: claude/codex/gemini/opencode/shell/test-runner/unknown
    label: str = "agent",
) -> None:
    """Insert a minimally-valid agent row.

    ``role`` and ``capability`` are CHECK-constrained to closed sets;
    ``unknown`` is the canonical "partially_configured" trigger value.
    ``label`` is free-form (DEFAULT ''); empty string also triggers
    ``partially_configured`` per Clarifications Q2.
    """
    tmux_pane_id = f"%{pane_index}"
    conn.execute(
        """
        INSERT INTO agents (
            agent_id, container_id, tmux_socket_path, tmux_session_name,
            tmux_window_index, tmux_pane_index, tmux_pane_id,
            role, capability, label, project_path,
            effective_permissions, created_at, last_registered_at, active
        ) VALUES (
            ?, ?, '/tmp/tmux.sock', 'sess',
            0, ?, ?,
            ?, ?, ?, '',
            '{}', ?, ?, ?
        )
        """,
        (
            agent_id,
            container_id,
            pane_index,
            tmux_pane_id,
            role,
            capability,
            label,
            _ISO_TS,
            _ISO_TS,
            active,
        ),
    )
    conn.commit()


def seed_log_attachment(
    conn: Any,
    *,
    attachment_id: str,
    agent_id: str,
    container_id: str = "c1",
    pane_index: int = 0,
    status: str = "active",  # closed set: active/superseded/stale/detached
    log_path: str | None = None,
) -> None:
    tmux_pane_id = f"%{pane_index}"
    # Default a distinct log_path per attachment so two *active* attachments
    # seeded through this helper don't collide on the partial unique index
    # `log_attachments(log_path) WHERE status = 'active'` (state/schema.py).
    if log_path is None:
        log_path = f"/tmp/log-{attachment_id}"
    conn.execute(
        """
        INSERT INTO log_attachments (
            attachment_id, agent_id, container_id,
            tmux_socket_path, tmux_session_name, tmux_window_index,
            tmux_pane_index, tmux_pane_id,
            log_path, status, source, pipe_pane_command,
            attached_at, last_status_at, created_at
        ) VALUES (
            ?, ?, ?, '/tmp/tmux.sock', 'sess', 0, ?, ?,
            ?, ?, 'explicit', ?,
            ?, ?, ?
        )
        """,
        (
            attachment_id,
            agent_id,
            container_id,
            pane_index,
            tmux_pane_id,
            log_path,
            status,
            f"pipe-pane -O cat >{log_path}",
            _ISO_TS,
            _ISO_TS,
            _ISO_TS,
        ),
    )
    conn.commit()


__all__ = ["seed_container", "seed_pane", "seed_agent", "seed_log_attachment"]
