"""Shared helpers for FEAT-006 unit tests.

Builds an :class:`AgentService` against a temporary SQLite database with
the v4 schema applied, plus convenience helpers to seed FEAT-003
``containers`` rows and FEAT-004 ``panes`` rows so the dynamic parent
check / re-registration paths have realistic input. No daemon, no
socket, no Docker, no tmux — pure in-process.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from agenttower.agents.mutex import AgentLockMap, RegisterLockMap
from agenttower.agents.service import AgentService
from agenttower.state.schema import open_registry


# A 64-char hex container id and a stable pane composite key tuple per
# data-model.md §2.1. Tests can use ``CK_DEFAULT`` directly or build new
# tuples by altering one field.
CONTAINER_ID = "c" * 64
CONTAINER_NAME = "bench-test"
TMUX_SOCKET = "/tmp/tmux-1000/default"  # NOSONAR - test fixture path
SESSION = "main"

CK_DEFAULT = (CONTAINER_ID, TMUX_SOCKET, SESSION, 0, 0, "%0")


def make_service(tmp_path: Path, *, schema_version: int = 4) -> AgentService:
    """Build an :class:`AgentService` against ``tmp_path/agenttower.sqlite3``."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700, exist_ok=True)
    state_db = state_dir / "agenttower.sqlite3"

    # Initialize the registry (creates v4 schema).
    conn, _ = open_registry(state_db, namespace_root=state_dir)
    conn.close()

    return AgentService(
        connection_factory=lambda: sqlite3.connect(
            str(state_db), isolation_level=None
        ),
        register_locks=RegisterLockMap(),
        agent_locks=AgentLockMap(),
        events_file=tmp_path / "events.jsonl",
        schema_version=schema_version,
    )


def seed_container(
    service: AgentService,
    *,
    container_id: str = CONTAINER_ID,
    name: str = CONTAINER_NAME,
    active: bool = True,
) -> None:
    """Insert a containers row so register_agent's pane key is joinable."""
    conn = service.connection_factory()
    try:
        conn.execute(
            "INSERT INTO containers (container_id, name, image, status, "
            "labels_json, mounts_json, inspect_json, config_user, working_dir, "
            "active, first_seen_at, last_scanned_at) VALUES "
            "(?, ?, 'image', 'running', '{}', '[]', '{}', 'user', '/w', ?, "
            "'2026-05-07T00:00:00.000000+00:00', "
            "'2026-05-07T00:00:00.000000+00:00')",
            (container_id, name, 1 if active else 0),
        )
    finally:
        conn.close()


def seed_pane(
    service: AgentService,
    *,
    container_id: str = CONTAINER_ID,
    container_name: str = CONTAINER_NAME,
    tmux_socket_path: str = TMUX_SOCKET,
    tmux_session_name: str = SESSION,
    tmux_window_index: int = 0,
    tmux_pane_index: int = 0,
    tmux_pane_id: str = "%0",
    active: bool = True,
) -> tuple[str, str, str, int, int, str]:
    """Insert a panes row for the given composite key. Returns the key."""
    conn = service.connection_factory()
    try:
        conn.execute(
            "INSERT INTO panes VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, '/dev/pts/0', 'bash', '/w', 'title', "
            "1, ?, '2026-05-07T00:00:00.000000+00:00', "
            "'2026-05-07T00:00:00.000000+00:00')",
            (
                container_id,
                tmux_socket_path,
                tmux_session_name,
                tmux_window_index,
                tmux_pane_index,
                tmux_pane_id,
                container_name,
                "user",
                12345,
                1 if active else 0,
            ),
        )
    finally:
        conn.close()
    return (
        container_id,
        tmux_socket_path,
        tmux_session_name,
        tmux_window_index,
        tmux_pane_index,
        tmux_pane_id,
    )


def register_params(
    composite_key: tuple = CK_DEFAULT,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a register_agent params dict. Caller passes only supplied fields."""
    out: dict[str, Any] = {
        "container_id": composite_key[0],
        "pane_composite_key": {
            "container_id": composite_key[0],
            "tmux_socket_path": composite_key[1],
            "tmux_session_name": composite_key[2],
            "tmux_window_index": composite_key[3],
            "tmux_pane_index": composite_key[4],
            "tmux_pane_id": composite_key[5],
        },
    }
    out.update(overrides)
    return out


def read_events(service: AgentService) -> list[dict[str, Any]]:
    """Read every JSONL row appended to the events file (for audit assertions)."""
    import json as _json

    events_file = service.events_file
    if events_file is None or not Path(events_file).exists():
        return []
    out = []
    for line in Path(events_file).read_text().splitlines():
        if line.strip():
            out.append(_json.loads(line))
    return out
