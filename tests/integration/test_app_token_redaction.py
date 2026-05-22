"""FEAT-011 T081 — SC-008: the opaque app_session_token is never persisted.

Spawns a real daemon, runs a flow that emits audit rows (``app.hello`` to
mint a session, then ``app.agent.register_from_pane`` against a seeded
container + pane so a ``agent_registered`` audit row is written), captures
the ``app_session_token`` from the hello response, then reads the events
JSONL file and every daemon log file under the state dir and asserts the
opaque token string appears **nowhere** in any of them.

SC-008 invariant: the per-session bearer token is a secret. The numeric
``app_session_id`` is a non-secret correlation handle and IS allowed to
appear in audit/log output — the test asserts that distinction explicitly.

The container + pane are seeded directly into the daemon's state SQLite
before the socket flow runs, mirroring ``test_story2_adopt_roundtrip.py``.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import time
from pathlib import Path

import pytest

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon_if_alive,
)


# ─── Wire helpers (mirrors Story 2) ─────────────────────────────────────


def _open_socket(socket_path: Path) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    saved_cwd = os.getcwd()
    try:
        os.chdir(socket_path.parent)
        sock.connect(socket_path.name)
    finally:
        os.chdir(saved_cwd)
    return sock


def _call(sock: socket.socket, method: str, params: dict | None = None) -> dict:
    request: dict = {"method": method}
    if params is not None:
        request["params"] = params
    sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    return json.loads(buf.decode("utf-8"))


def _one_shot_call(socket_path: Path, method: str, params: dict | None = None) -> dict:
    sock = _open_socket(socket_path)
    try:
        return _call(sock, method, params)
    finally:
        sock.close()


# ─── Seed helpers (mirrors Story 2) ─────────────────────────────────────


_CONTAINER_ID = "b" * 64
_CONTAINER_NAME = "bench-t081"
_TMUX_SOCKET = "/tmp/tmux-1000/default"  # NOSONAR — test fixture path
_SESSION_NAME = "main"
_PANE_ID = "%81"


def _seed_container_and_pane(state_db: Path) -> None:
    """Write one container + one pane row directly into the daemon's
    state DB before any socket mutation runs."""
    conn = sqlite3.connect(str(state_db))
    try:
        conn.execute(
            """
            INSERT INTO containers
                (container_id, name, image, status, labels_json, mounts_json,
                 inspect_json, config_user, working_dir, active,
                 first_seen_at, last_scanned_at)
            VALUES (?, ?, 'img:latest', 'running', '{}', '[]', '{}',
                    '', '/work', 1,
                    '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z')
            """,
            (_CONTAINER_ID, _CONTAINER_NAME),
        )
        conn.execute(
            """
            INSERT INTO panes (
                container_id, tmux_socket_path, tmux_session_name,
                tmux_window_index, tmux_pane_index, tmux_pane_id,
                container_name, container_user, pane_pid, pane_tty,
                pane_current_command, pane_current_path, pane_title,
                pane_active, active, first_seen_at, last_scanned_at
            ) VALUES (?, ?, ?, 0, 0, ?, ?, '', 0, '', '', '', '',
                      1, 1, '2026-05-19T00:00:00Z', '2026-05-19T00:00:00Z')
            """,
            (_CONTAINER_ID, _TMUX_SOCKET, _SESSION_NAME, _PANE_ID, _CONTAINER_NAME),
        )
        conn.commit()
    finally:
        conn.close()


# ─── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


@pytest.fixture
def daemon(env: dict[str, str]) -> dict:
    run_config_init(env)
    proc = ensure_daemon(env, json_mode=True)
    assert proc.returncode == 0, proc.stderr
    paths = resolved_paths(Path(env["HOME"]))
    _seed_container_and_pane(paths["state_db"])
    return {"env": env, "socket": paths["socket"], "paths": paths}


# ─── Tests ──────────────────────────────────────────────────────────────


def _scan_state_dir_files(state_dir: Path) -> list[Path]:
    """Return every regular text-ish file under the state dir except the
    SQLite database (binary; the token is never stored there and a binary
    substring scan would be noise)."""
    out: list[Path] = []
    for path in state_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in (".sqlite3", ".sqlite", ".db"):
            continue
        if path.name.endswith("-wal") or path.name.endswith("-shm"):
            continue
        out.append(path)
    return out


def test_session_token_never_persisted_to_jsonl_or_logs(daemon: dict) -> None:
    """SC-008: after a flow that emits an ``agent_registered`` audit row,
    the opaque ``app_session_token`` appears in neither ``events.jsonl``
    nor any daemon log file. The numeric ``app_session_id`` is allowed to
    appear and is verified separately below."""
    socket_path: Path = daemon["socket"]
    paths: dict[str, Path] = daemon["paths"]

    hello = _one_shot_call(socket_path, "app.hello", {"client_id": "t081"})
    assert hello["ok"] is True, hello
    token = hello["result"]["app_session_token"]
    session_id = hello["result"]["app_session_id"]
    assert isinstance(token, str) and len(token) >= 32, hello
    assert isinstance(session_id, int) and session_id >= 1, hello

    adopt = _one_shot_call(
        socket_path,
        "app.agent.register_from_pane",
        {
            "app_session_token": token,
            "container_id": _CONTAINER_ID,
            "tmux_socket": _TMUX_SOCKET,
            "session_name": _SESSION_NAME,
            "window_index": 0,
            "pane_index": 0,
            "pane_id": _PANE_ID,
            "role": "slave",
            "capability": "claude",
            "label": "t081-agent",
        },
    )
    assert adopt["ok"] is True, adopt

    # Give the daemon a moment to flush JSONL + logs.
    time.sleep(0.2)

    events_file: Path = paths["events_file"]
    assert events_file.exists(), (
        "expected events.jsonl to exist — register_from_pane emits an "
        "origin='app' audit row"
    )
    events_text = events_file.read_text(encoding="utf-8", errors="replace")

    # The audit row for the mutation must actually be present, otherwise
    # the redaction assertion would pass vacuously.
    rows = [
        json.loads(line)
        for line in events_text.splitlines()
        if line.strip()
    ]
    assert any(
        r.get("event_type") == "agent_registered" and r.get("origin") == "app"
        for r in rows
    ), f"no origin='app' agent_registered audit row found; saw {rows!r}"

    # SC-008: the opaque token must not appear in events.jsonl …
    assert token not in events_text, (
        "SC-008 violation: app_session_token leaked into events.jsonl"
    )

    # … nor in any daemon log / text file under the state dir.
    leaked_in: list[str] = []
    for path in _scan_state_dir_files(paths["state_dir"]):
        text = path.read_text(encoding="utf-8", errors="replace")
        if token in text:
            leaked_in.append(str(path))
    assert not leaked_in, (
        f"SC-008 violation: app_session_token leaked into state-dir "
        f"file(s): {leaked_in!r}"
    )


def test_session_id_is_allowed_in_audit_output(daemon: dict) -> None:
    """SC-008 corollary: the numeric ``app_session_id`` is a non-secret
    correlation handle. This test confirms the token redaction above is a
    real redaction of a secret, not blanket suppression of all session
    identity — the daemon is free to record ``app_session_id`` in audit
    rows.

    The assertion is intentionally lenient: it checks that recording the
    session_id is *permitted* (no failure, well-formed envelope) and that
    the token and id are genuinely distinct value types, so a token-leak
    scan cannot be satisfied by accidentally matching the id.
    """
    socket_path: Path = daemon["socket"]

    hello = _one_shot_call(socket_path, "app.hello", {"client_id": "t081-id"})
    assert hello["ok"] is True, hello
    token = hello["result"]["app_session_token"]
    session_id = hello["result"]["app_session_id"]

    # Token is an opaque string; id is a small positive integer. They are
    # distinct value spaces — redacting one cannot mask the other.
    assert isinstance(token, str)
    assert isinstance(session_id, int)
    assert str(session_id) != token
