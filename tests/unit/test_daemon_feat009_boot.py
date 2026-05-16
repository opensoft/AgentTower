"""T048 — daemon boot wiring smoke test for FEAT-009 services.

Verifies that :func:`agenttower.daemon._build_feat009_services` can
instantiate the queue / routing / delivery services against a real v7
SQLite schema and that:

* The :class:`DeliveryWorker` thread starts.
* :meth:`DeliveryWorker.run_recovery_pass` is invoked synchronously
  (the worker must NOT see an in-flight row left from a prior boot —
  the recovery pass commits BEFORE start).
* :meth:`DeliveryWorker.stop` cleanly halts the worker thread.

This smoke test does NOT spin up the full ``agenttowerd`` subprocess
or socket server — those are exercised by the integration suite. It
exists to catch import-time / constructor-signature regressions in
the FEAT-009 service wiring quickly.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from agenttower import daemon
from agenttower.paths import Paths
from agenttower.state import schema


def _bootstrap_v7_db(tmp_path: Path) -> Path:
    """Create a v7 SQLite DB on disk by applying every migration up
    to v7 directly. Mirrors the pattern in test_schema_migration_v7.py
    (avoids :func:`schema.open_registry`'s strict dir-mode check that
    pytest's tmp_path doesn't satisfy)."""
    state_db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(str(state_db))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (7)")
    for v in (2, 3, 4, 5, 6, 7):
        schema._MIGRATIONS[v](conn)  # noqa: SLF001 — test-only direct apply
    conn.commit()
    conn.close()
    return state_db


def _make_paths(tmp_path: Path) -> Paths:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "logs").mkdir()
    state_db = _bootstrap_v7_db(state_dir)
    return Paths(
        config_file=tmp_path / "config" / "config.toml",
        state_db=state_db,
        events_file=state_dir / "events.jsonl",
        logs_dir=state_dir / "logs",
        socket=state_dir / "agenttowerd.sock",
        cache_dir=tmp_path / "cache",
    )


def test_build_feat009_services_returns_wired_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The factory returns the full FEAT-009 service tuple and starts
    the delivery worker thread."""
    # Use the FakeTmuxAdapter to avoid subprocess invocation on hosts
    # without a real tmux.
    fake_fixture = tmp_path / "tmux_fake.json"
    fake_fixture.write_text("{}")
    monkeypatch.setenv("AGENTTOWER_TEST_TMUX_FAKE", str(fake_fixture))

    paths = _make_paths(tmp_path)
    result = daemon._build_feat009_services(
        paths=paths,
        discovery_service=None,
        pane_service=None,
    )
    (
        worker_conn,
        queue_service,
        routing_flag,
        audit_writer,
        delivery_worker,
        message_queue_dao,
        daemon_state_dao,
    ) = result
    try:
        assert worker_conn is not None
        # Routing flag starts ``enabled`` from the migration's seed row.
        assert routing_flag.is_enabled() is True
        # Audit writer is operational (no degraded state yet).
        assert audit_writer.degraded is False
        # Worker thread is alive after start().
        assert delivery_worker._thread is not None  # noqa: SLF001 — smoke test
        assert delivery_worker._thread.is_alive()
        # DAO + state DAO are connected to the same worker connection.
        assert message_queue_dao is not None
        assert daemon_state_dao is not None
    finally:
        # ``stop()`` joins the thread and sets ``_thread`` to ``None``
        # — the thread itself exits within the timeout.
        delivery_worker.stop(timeout=2.0)
        worker_conn.close()
    assert delivery_worker._thread is None  # noqa: SLF001 — smoke test


def test_recovery_pass_runs_before_worker_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An in-flight row from a prior boot is recovered BEFORE the
    worker thread starts (research §R-012). The recovery pass MUST
    commit the ``failed/attempt_interrupted`` transition synchronously
    so the worker never observes a half-stamped row."""
    fake_fixture = tmp_path / "tmux_fake.json"
    fake_fixture.write_text("{}")
    monkeypatch.setenv("AGENTTOWER_TEST_TMUX_FAKE", str(fake_fixture))

    paths = _make_paths(tmp_path)
    # Pre-populate one in-flight row directly via SQLite. This simulates
    # a prior daemon crash mid-attempt.
    conn = sqlite3.connect(str(paths.state_db))
    conn.execute(
        "INSERT INTO message_queue ("
        "  message_id, state, "
        "  sender_agent_id, sender_label, sender_role, sender_capability, "
        "  target_agent_id, target_label, target_role, target_capability, "
        "  target_container_id, target_pane_id, "
        "  envelope_body, envelope_body_sha256, envelope_size_bytes, "
        "  enqueued_at, delivery_attempt_started_at, last_updated_at"
        ") VALUES (?, 'queued', "
        " 'agt_aaaaaaaaaaaa', 'queen', 'master', 'codex', "
        " 'agt_bbbbbbbbbbbb', 'worker-1', 'slave', 'codex', "
        " 'cont_x', '%1', "
        " ?, ?, 64, "
        " '2026-05-12T00:00:00.000Z', '2026-05-12T00:00:00.500Z', "
        " '2026-05-12T00:00:00.500Z')",
        (
            "11111111-2222-4333-8444-555555555555",
            b"hi", "a" * 64,
        ),
    )
    conn.commit()
    conn.close()

    result = daemon._build_feat009_services(
        paths=paths,
        discovery_service=None,
        pane_service=None,
    )
    (
        worker_conn,
        _queue_service,
        _routing_flag,
        _audit_writer,
        delivery_worker,
        _message_queue_dao,
        _daemon_state_dao,
    ) = result
    try:
        # The recovery pass should have transitioned the row to failed.
        check_conn = sqlite3.connect(str(paths.state_db))
        row = check_conn.execute(
            "SELECT state, failure_reason FROM message_queue WHERE message_id = ?",
            ("11111111-2222-4333-8444-555555555555",),
        ).fetchone()
        check_conn.close()
        assert row is not None
        assert row[0] == "failed", f"expected failed, got {row[0]}"
        assert row[1] == "attempt_interrupted", f"expected attempt_interrupted, got {row[1]}"
    finally:
        delivery_worker.stop(timeout=2.0)
        worker_conn.close()
