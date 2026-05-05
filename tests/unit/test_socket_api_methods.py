"""Unit tests for FEAT-002 socket_api method dispatch (T013)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from agenttower.socket_api.methods import DISPATCH, DaemonContext


def _ctx(tmp_path: Path) -> DaemonContext:
    return DaemonContext(
        pid=4242,
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=tmp_path,
        daemon_version="0.0.0+test",
        schema_version=1,
    )


def test_ping_returns_ok_empty_result(tmp_path: Path) -> None:
    envelope = DISPATCH["ping"](_ctx(tmp_path), {})
    assert envelope == {"ok": True, "result": {}}


def test_ping_idempotent(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    a = DISPATCH["ping"](ctx, {})
    b = DISPATCH["ping"](ctx, {})
    assert a == b == {"ok": True, "result": {}}


def test_ping_does_not_mutate_state_dir(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    DISPATCH["ping"](ctx, {})
    DISPATCH["ping"](ctx, {})
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


def test_ping_does_not_open_sqlite_connection(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    # Boobytrap sqlite3.connect: if ping touches the registry, this blows up.
    def fail(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise AssertionError("ping must not open sqlite3")

    monkeypatch.setattr(sqlite3, "connect", fail)
    DISPATCH["ping"](_ctx(tmp_path), {})


def test_dispatch_table_keys_are_closed_set() -> None:
    assert set(DISPATCH.keys()) == {"ping", "status", "shutdown"}


# ---------------------------------------------------------------------------
# T021: status method shape, uptime clamp, schema_version cache.
# ---------------------------------------------------------------------------


from datetime import timedelta


def test_status_returns_documented_shape(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    envelope = DISPATCH["status"](ctx, {})
    assert envelope["ok"] is True
    result = envelope["result"]
    expected_keys = {
        "alive",
        "pid",
        "start_time_utc",
        "uptime_seconds",
        "socket_path",
        "state_path",
        "schema_version",
        "daemon_version",
    }
    assert set(result.keys()) == expected_keys
    assert result["alive"] is True
    assert isinstance(result["pid"], int)
    assert isinstance(result["uptime_seconds"], int)
    assert result["socket_path"] == str(tmp_path / "agenttowerd.sock")
    assert result["state_path"] == str(tmp_path)
    assert result["schema_version"] == 1
    assert result["daemon_version"] == "0.0.0+test"


def test_status_uptime_clamps_on_backwards_clock(tmp_path: Path) -> None:
    # start_time in the future → delta is negative → clamp to 0.
    ctx = _ctx(tmp_path)
    ctx.start_time_utc = datetime.now(timezone.utc) + timedelta(seconds=60)
    envelope = DISPATCH["status"](ctx, {})
    assert envelope["ok"] is True
    assert envelope["result"]["uptime_seconds"] == 0


def test_status_does_not_re_read_schema_version(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    # Trip an alarm if status touches sqlite3 mid-run.
    def fail(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ARG001
        raise AssertionError("status must read schema_version from cache only")

    monkeypatch.setattr(sqlite3, "connect", fail)
    ctx = _ctx(tmp_path)
    envelope = DISPATCH["status"](ctx, {})
    assert envelope["ok"] is True
    assert envelope["result"]["schema_version"] == ctx.schema_version


# ---------------------------------------------------------------------------
# T031: shutdown method shape + event signaling.
# ---------------------------------------------------------------------------


import threading


def test_shutdown_returns_documented_shape(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.shutdown_requested = threading.Event()
    envelope = DISPATCH["shutdown"](ctx, {})
    assert envelope == {"ok": True, "result": {"shutting_down": True}}


def test_shutdown_sets_shutdown_requested_event(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    event = threading.Event()
    ctx.shutdown_requested = event
    DISPATCH["shutdown"](ctx, {})
    assert event.is_set()


def test_shutdown_does_not_unlink_artifacts(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.shutdown_requested = threading.Event()
    sock = tmp_path / "agenttowerd.sock"
    pid = tmp_path / "agenttowerd.pid"
    lock = tmp_path / "agenttowerd.lock"
    for p in (sock, pid, lock):
        p.write_text("")
    DISPATCH["shutdown"](ctx, {})
    # Method itself does NOT unlink — that is the server thread's job (T029).
    for p in (sock, pid, lock):
        assert p.exists()


def test_shutdown_with_no_event_returns_ok_anyway(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)  # shutdown_requested is None by default
    envelope = DISPATCH["shutdown"](ctx, {})
    assert envelope == {"ok": True, "result": {"shutting_down": True}}
