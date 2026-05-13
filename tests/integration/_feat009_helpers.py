"""Helpers for FEAT-009 integration tests.

Used by every FEAT-009 integration test, all of which are either
**socket-level** (the default — talk to the daemon via the FEAT-002
``send_request`` client, bypass the CLI's pane-discovery layer) or
**CLI-level** (a small subset that exercises the CLI's pane resolution
+ caller-context handling). The container fresh-tmux E2E lives outside
the pytest harness — see ``specs/009-safe-prompt-queue/quickstart.md``.

Each helper is scoped to seeding registry state the daemon's FEAT-009
services need to function:

* :func:`seed_agent` — inserts an ``agents`` row (master / slave /
  swarm) directly via SQLite. Mirrors what
  ``agenttower register-self`` would persist after a successful FEAT-006
  round-trip, without needing to drive FEAT-005's proc_root fake
  pipeline for every test.
* :func:`seed_container` — inserts a ``containers`` row (active=1) so
  ``DiscoveryContainerPaneLookup.is_container_active`` returns True.
* :func:`seed_pane` — inserts a ``panes`` row (active=1) so
  ``DiscoveryContainerPaneLookup.is_pane_resolvable`` returns True and
  the worker's :class:`RegistryDeliveryContextResolver` can fetch
  ``tmux_socket_path`` for the delivery call.
* :func:`write_tmux_fake` — writes a minimal JSON fixture for
  :class:`FakeTmuxAdapter` so the worker's tmux calls succeed (the four
  delivery methods don't read the fixture but the adapter requires the
  file to be parseable JSON).
* :func:`read_audit_jsonl` — parses every line of ``events.jsonl`` into
  a list of dicts. Filter by ``event_type`` in the calling test.
* :func:`get_queue_row` — direct SQLite SELECT of one
  ``message_queue`` row by ``message_id``.

The default scenario these helpers compose is one container (``cont_x``)
with one master pane (``%master``) and one slave pane (``%slave``). The
master sends to the slave via ``queue.send_input`` and the worker
delivers via the FakeTmuxAdapter.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


# 64-char hex container_id (the real Docker shape). The
# ``_looks_like_container_id`` predicate in ``state/panes.py``
# requires this shape to match panes by container_id directly; any
# shorter or non-hex value falls back to matching against
# ``containers.name``, which breaks the FEAT-009 worker's lookup.
DEFAULT_CONTAINER_ID = "c" * 64
DEFAULT_TMUX_SOCKET_PATH = "/tmp/tmux-1000/default"
DEFAULT_TMUX_SESSION = "swarm"


def seed_container(
    state_db: Path,
    *,
    container_id: str = DEFAULT_CONTAINER_ID,
    name: str = "bench-test",
    config_user: str = "bench",
    active: int = 1,
) -> None:
    """Insert one ``containers`` row. ``config_user`` flows through the
    :class:`RegistryDeliveryContextResolver` as ``bench_user`` for the
    tmux delivery call."""
    conn = sqlite3.connect(state_db)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO containers ("
            "container_id, name, image, status, "
            "labels_json, mounts_json, inspect_json, config_user, working_dir, "
            "active, first_seen_at, last_scanned_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                container_id,
                name,
                "test/image:latest",
                "running",
                "{}",
                "[]",
                "{}",
                config_user,
                "/work",
                active,
                "2026-05-12T00:00:00.000Z",
                "2026-05-12T00:00:00.000Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def seed_pane(
    state_db: Path,
    *,
    container_id: str = DEFAULT_CONTAINER_ID,
    tmux_socket_path: str = DEFAULT_TMUX_SOCKET_PATH,
    tmux_session_name: str = DEFAULT_TMUX_SESSION,
    tmux_window_index: int = 0,
    tmux_pane_index: int = 0,
    tmux_pane_id: str = "%1",
    active: int = 1,
) -> None:
    """Insert one ``panes`` row. The composite key matches the agent
    seeded by :func:`seed_agent`."""
    conn = sqlite3.connect(state_db)
    try:
        # Probe the panes table schema so the helper works regardless
        # of which FEAT-004 columns are NOT NULL on a given migration.
        cols = [
            row[1]
            for row in conn.execute("PRAGMA table_info(panes)").fetchall()
        ]
        # Build a minimal-but-complete row.
        values: dict[str, Any] = {
            "container_id": container_id,
            "tmux_socket_path": tmux_socket_path,
            "tmux_session_name": tmux_session_name,
            "tmux_window_index": tmux_window_index,
            "tmux_pane_index": tmux_pane_index,
            "tmux_pane_id": tmux_pane_id,
            "pane_pid": 1234,
            "pane_tty": "/dev/pts/0",
            "pane_current_command": "bash",
            "pane_current_path": "/work",
            "pane_title": "bench",
            "pane_active": 1,
            "container_name": "bench-test",
            "container_user": "bench",
            "active": active,
            "first_seen_at": "2026-05-12T00:00:00.000Z",
            "last_scanned_at": "2026-05-12T00:00:00.000Z",
        }
        present = {k: v for k, v in values.items() if k in cols}
        placeholders = ", ".join("?" for _ in present)
        col_list = ", ".join(present.keys())
        conn.execute(
            f"INSERT OR REPLACE INTO panes ({col_list}) VALUES ({placeholders})",
            tuple(present.values()),
        )
        conn.commit()
    finally:
        conn.close()


def seed_agent(
    state_db: Path,
    *,
    agent_id: str,
    role: str,
    label: str,
    capability: str = "codex",
    container_id: str = DEFAULT_CONTAINER_ID,
    tmux_socket_path: str = DEFAULT_TMUX_SOCKET_PATH,
    tmux_session_name: str = DEFAULT_TMUX_SESSION,
    tmux_window_index: int = 0,
    tmux_pane_index: int = 0,
    tmux_pane_id: str = "%1",
    active: int = 1,
    parent_agent_id: str | None = None,
) -> None:
    """Insert one ``agents`` row matching a previously seeded pane.

    Mirrors what ``agenttower register-self`` would persist; bypasses
    the FEAT-006 round-trip so individual FEAT-009 tests don't have to
    drive the FEAT-005 proc_root fake pipeline.
    """
    conn = sqlite3.connect(state_db)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO agents ("
            "agent_id, container_id, tmux_socket_path, tmux_session_name, "
            "tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "role, capability, label, project_path, parent_agent_id, "
            "effective_permissions, created_at, last_registered_at, "
            "last_seen_at, active"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent_id,
                container_id,
                tmux_socket_path,
                tmux_session_name,
                tmux_window_index,
                tmux_pane_index,
                tmux_pane_id,
                role,
                capability,
                label,
                "/work",
                parent_agent_id,
                "{}",
                "2026-05-12T00:00:00.000Z",
                "2026-05-12T00:00:00.000Z",
                "2026-05-12T00:00:00.000Z",
                active,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def seed_master_and_slave(
    state_db: Path,
    *,
    master_agent_id: str = "agt_aaaaaaaaaaaa",
    slave_agent_id: str = "agt_bbbbbbbbbbbb",
    master_label: str = "queen",
    slave_label: str = "worker-1",
    container_id: str = DEFAULT_CONTAINER_ID,
) -> None:
    """Seed the default master+slave scenario: one container, two
    panes (``%master`` / ``%slave``), one master + one slave agent.
    """
    seed_container(state_db, container_id=container_id)
    seed_pane(
        state_db, container_id=container_id, tmux_pane_id="%master",
        tmux_window_index=0, tmux_pane_index=0,
    )
    seed_pane(
        state_db, container_id=container_id, tmux_pane_id="%slave",
        tmux_window_index=0, tmux_pane_index=1,
    )
    seed_agent(
        state_db,
        agent_id=master_agent_id, role="master", label=master_label,
        container_id=container_id, tmux_pane_id="%master",
        tmux_window_index=0, tmux_pane_index=0,
    )
    seed_agent(
        state_db,
        agent_id=slave_agent_id, role="slave", label=slave_label,
        container_id=container_id, tmux_pane_id="%slave",
        tmux_window_index=0, tmux_pane_index=1,
    )


def write_tmux_fake(path: Path, *, container_id: str = DEFAULT_CONTAINER_ID) -> Path:
    """Write a minimal FakeTmuxAdapter fixture.

    The FEAT-009 delivery methods (``load_buffer`` / ``paste_buffer`` /
    ``send_keys`` / ``delete_buffer``) record call args into an in-memory
    list and only consult ``self._script`` for FEAT-004 scan paths, so a
    minimal ``containers`` block is enough.
    """
    fixture = {
        "containers": {
            container_id: {
                "uid": "1000",
                "sockets": {},
            },
        },
    }
    path.write_text(json.dumps(fixture), encoding="utf-8")
    return path


def read_audit_jsonl(events_jsonl_path: Path) -> list[dict[str, Any]]:
    """Parse every line of ``events.jsonl`` into a list of dicts.
    Returns ``[]`` if the file doesn't exist yet."""
    if not events_jsonl_path.exists():
        return []
    return [
        json.loads(line)
        for line in events_jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def get_queue_row(state_db: Path, *, message_id: str) -> dict[str, Any] | None:
    """Direct SQLite SELECT of one ``message_queue`` row.

    Returns a dict mapping column → value, or ``None`` if missing.
    """
    conn = sqlite3.connect(state_db)
    try:
        cur = conn.execute(
            "SELECT * FROM message_queue WHERE message_id = ?", (message_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    finally:
        conn.close()


def list_queue_rows(state_db: Path) -> list[dict[str, Any]]:
    """Direct SQLite SELECT of every ``message_queue`` row."""
    conn = sqlite3.connect(state_db)
    try:
        cur = conn.execute("SELECT * FROM message_queue ORDER BY enqueued_at")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def wait_for_queue_state(
    state_db: Path,
    *,
    message_id: str,
    expected_state: str,
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.05,
) -> dict[str, Any]:
    """Poll the SQLite ``message_queue`` row until ``state ==
    expected_state`` OR the timeout elapses.

    Returns the row (matching or not). Tests assert on the returned
    state so an early-timeout still reports the row's actual state for
    debugging.
    """
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        row = get_queue_row(state_db, message_id=message_id)
        if row is not None:
            last = row
            if row["state"] == expected_state:
                return row
        time.sleep(poll_interval_seconds)
    return last or {}


def install_tmux_fake_in_env(env: dict[str, str], home: Path) -> Path:
    """Convenience: write the tmux-fake fixture next to ``$HOME`` and
    set ``AGENTTOWER_TEST_TMUX_FAKE`` in ``env``. Returns the fixture
    path."""
    path = home.parent / "tmux-fake.json"
    write_tmux_fake(path)
    env["AGENTTOWER_TEST_TMUX_FAKE"] = str(path)
    return path
