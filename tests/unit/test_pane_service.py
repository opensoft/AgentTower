"""Unit tests for FEAT-004 PaneDiscoveryService gate paths.

Covers:
- T042 (whole-scan-failure on docker_unavailable): the service writes a
  pane_scans row, appends one pane_scan_degraded JSONL event, and emits
  pane_scan_completed before re-raising.
- T043 (strict lifecycle emit): pre-commit pane_scan_started failure
  becomes internal_error before any docker exec; post-commit
  pane_scan_completed failure raises PostCommitSideEffectError after the
  SQLite row has committed.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from agenttower.discovery.pane_service import (
    PaneDiscoveryService,
    PostCommitSideEffectError,
)
from agenttower.socket_api import errors as _errors
from agenttower.state import schema as state_schema
from agenttower.tmux import ParsedPane, SocketListing, TmuxError


class _StubAdapter:
    """Minimal :class:`TmuxAdapter` Protocol stub for unit tests."""

    def __init__(self, *, on_resolve_uid: callable | None = None) -> None:
        self._on_resolve_uid = on_resolve_uid
        self.resolve_uid_calls: list[tuple[str, str]] = []

    def resolve_uid(self, *, container_id: str, bench_user: str) -> str:
        self.resolve_uid_calls.append((container_id, bench_user))
        if self._on_resolve_uid is not None:
            return self._on_resolve_uid(container_id, bench_user)
        return "1000"

    def list_socket_dir(
        self, *, container_id: str, bench_user: str, uid: str
    ) -> SocketListing:
        return SocketListing(container_id=container_id, uid=uid, sockets=())

    def list_panes(
        self, *, container_id: str, bench_user: str, socket_path: str
    ) -> Sequence[ParsedPane]:
        return ()


class _RecordingLogger:
    """Lifecycle logger stub that captures emit calls."""

    def __init__(self, *, fail_on: set[str] | None = None) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self._fail_on = fail_on or set()

    def emit(self, event: str, **kwargs: Any) -> None:
        if event in self._fail_on:
            raise OSError(f"forced failure on {event}")
        self.events.append((event, dict(kwargs)))


def _make_db(tmp_path: Path) -> tuple[sqlite3.Connection, Path]:
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    state_db = state_dir / "agenttower.sqlite3"
    conn, _ = state_schema.open_registry(state_db, namespace_root=state_dir)
    # Seed one active container so the scan has work to do.
    conn.execute(
        "INSERT INTO containers (container_id, name, image, status, labels_json, "
        "mounts_json, inspect_json, config_user, working_dir, active, "
        "first_seen_at, last_scanned_at) VALUES "
        "('c1', 'bench', 'img', 'running', '{}', '[]', '{}', 'user', '/w', 1, "
        "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
    )
    return conn, state_db


def _make_service(
    tmp_path: Path,
    *,
    adapter: _StubAdapter,
    logger: _RecordingLogger | None = None,
    events_file: Path | None = None,
) -> PaneDiscoveryService:
    conn, state_db = _make_db(tmp_path)
    return PaneDiscoveryService(
        connection=conn,
        adapter=adapter,
        list_connection_factory=lambda: sqlite3.connect(str(state_db)),
        events_file=events_file,
        lifecycle_logger=logger,
        env={"USER": "host"},
    )


# ---------------------------------------------------------------------------
# T042 — docker_unavailable whole-scan-failure path
# ---------------------------------------------------------------------------


def test_docker_unavailable_persists_pane_scans_row_and_jsonl_event(
    tmp_path: Path,
) -> None:
    """T042 — when docker is missing, persist a degraded pane_scans row and one JSONL event."""
    def boom(container_id: str, bench_user: str) -> str:
        raise TmuxError(
            code=_errors.DOCKER_UNAVAILABLE,
            message="docker binary not found on PATH",
        )

    adapter = _StubAdapter(on_resolve_uid=boom)
    logger = _RecordingLogger()
    events_file = tmp_path / "state" / "events.jsonl"
    service = _make_service(
        tmp_path, adapter=adapter, logger=logger, events_file=events_file
    )

    with pytest.raises(TmuxError) as caught:
        service.scan()
    assert caught.value.code == _errors.DOCKER_UNAVAILABLE

    # SQLite: exactly one pane_scans row with status='degraded' and the right code.
    conn = sqlite3.connect(str(tmp_path / "state" / "agenttower.sqlite3"))
    try:
        rows = conn.execute(
            "SELECT status, error_code, containers_scanned, sockets_scanned, panes_seen "
            "FROM pane_scans"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0] == ("degraded", _errors.DOCKER_UNAVAILABLE, 0, 0, 0)

    # JSONL: exactly one pane_scan_degraded event.
    assert events_file.exists()
    lines = [ln for ln in events_file.read_text().splitlines() if ln]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["type"] == "pane_scan_degraded"
    assert record["payload"]["error_code"] == _errors.DOCKER_UNAVAILABLE

    # Lifecycle: pane_scan_started + pane_scan_completed (no _jsonl_failed).
    event_names = [e[0] for e in logger.events]
    assert event_names == ["pane_scan_started", "pane_scan_completed"]


# ---------------------------------------------------------------------------
# T043 — strict lifecycle emit
# ---------------------------------------------------------------------------


def test_pre_commit_pane_scan_started_failure_returns_internal_error(
    tmp_path: Path,
) -> None:
    """T043 pre-commit clause — pane_scan_started emit fails → no docker exec, no row."""
    adapter = _StubAdapter()
    logger = _RecordingLogger(fail_on={"pane_scan_started"})
    service = _make_service(tmp_path, adapter=adapter, logger=logger)

    with pytest.raises(TmuxError) as caught:
        service.scan()
    assert caught.value.code == _errors.INTERNAL_ERROR

    # No docker exec call was made (resolve_uid was never reached).
    assert adapter.resolve_uid_calls == []

    # No pane_scans row was written.
    conn = sqlite3.connect(str(tmp_path / "state" / "agenttower.sqlite3"))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM pane_scans").fetchone()
    finally:
        conn.close()
    assert rows[0] == 0


def test_post_commit_pane_scan_completed_failure_preserves_row(
    tmp_path: Path,
) -> None:
    """T043 post-commit clause — pane_scan_completed emit fails after commit; row preserved."""
    adapter = _StubAdapter()
    logger = _RecordingLogger(fail_on={"pane_scan_completed"})
    service = _make_service(tmp_path, adapter=adapter, logger=logger)

    with pytest.raises(PostCommitSideEffectError):
        service.scan()

    # SQLite row is committed despite the post-commit lifecycle failure.
    conn = sqlite3.connect(str(tmp_path / "state" / "agenttower.sqlite3"))
    try:
        rows = conn.execute("SELECT status FROM pane_scans").fetchall()
    finally:
        conn.close()
    assert rows == [("ok",)]

    # Mutex was released — a follow-up scan can acquire it without blocking.
    assert service.scan_mutex.acquire(blocking=False) is True
    service.scan_mutex.release()


def test_output_malformed_with_partial_rows_persists_parsed_subset(
    tmp_path: Path,
) -> None:
    """Partial parse + output_malformed must persist good rows as degraded."""

    class _PartialAdapter(_StubAdapter):
        def list_socket_dir(self, *, container_id: str, bench_user: str, uid: str) -> SocketListing:
            return SocketListing(container_id=container_id, uid=uid, sockets=("default",))

        def list_panes(self, *, container_id: str, bench_user: str, socket_path: str) -> Sequence[ParsedPane]:
            raise TmuxError(
                code=_errors.OUTPUT_MALFORMED,
                message="1 of 2 tmux list-panes rows malformed",
                container_id=container_id,
                tmux_socket_path=socket_path,
                partial_panes=(
                    ParsedPane(
                        tmux_session_name="work",
                        tmux_window_index=0,
                        tmux_pane_index=0,
                        tmux_pane_id="%0",
                        pane_pid=1,
                        pane_tty="/dev/pts/0",
                        pane_current_command="bash",
                        pane_current_path="/workspace",
                        pane_title="title",
                        pane_active=True,
                    ),
                ),
            )

    service = _make_service(tmp_path, adapter=_PartialAdapter())
    result = service.scan()
    assert result.status == "degraded"
    assert result.panes_seen == 1
    assert result.sockets_scanned == 1
    assert result.error_code == _errors.OUTPUT_MALFORMED

    conn = sqlite3.connect(str(tmp_path / "state" / "agenttower.sqlite3"))
    try:
        rows = conn.execute(
            "SELECT tmux_socket_path, tmux_pane_id, active FROM panes"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("/tmp/tmux-1000/default", "%0", 1)]
