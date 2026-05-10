"""Unit tests for FEAT-002 socket_api method dispatch (T013)."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from agenttower.events.session_registry import FollowSessionRegistry
from agenttower.socket_api.methods import (
    DISPATCH,
    DaemonContext,
    _events_validate_filter,
)


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
    # FEAT-002 keys + FEAT-003 additions + FEAT-004 additions + FEAT-006
    # additions + FEAT-007 additions + FEAT-008 additions (FR-022 /
    # FR-030 backward-compat; FR-023 for FEAT-006; FR-038 for FEAT-007).
    assert set(DISPATCH.keys()) == {
        "ping",
        "status",
        "shutdown",
        "scan_containers",
        "list_containers",
        "scan_panes",
        "list_panes",
        "register_agent",
        "list_agents",
        "set_role",
        "set_label",
        "set_capability",
        "attach_log",
        "detach_log",
        "attach_log_status",
        "attach_log_preview",
        "events.list",
        "events.follow_open",
        "events.follow_next",
        "events.follow_close",
        "events.classifier_rules",
    }


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
        # FEAT-008 — data-model.md §7. With ``ctx.events_reader is
        # None`` (no FEAT-008 reader wired in this test context), both
        # fields are present with the documented "not running" defaults.
        "events_reader",
        "events_persistence",
    }
    assert set(result.keys()) == expected_keys
    assert result["events_reader"] == {
        "running": False,
        "last_cycle_started_at": None,
        "last_cycle_duration_ms": None,
        "active_attachments": 0,
        "attachments_in_failure": [],
    }
    assert result["events_persistence"] == {
        "degraded_sqlite": None,
        "degraded_jsonl": None,
    }
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


class _ReaderSnapshot:
    def __init__(self) -> None:
        self.last_cycle_started_at = None
        self.last_cycle_duration_ms = None
        self.active_attachments = 0
        # Per-instance list — keeping this as a class attribute would
        # share the same list across every test that constructs a snapshot.
        self.attachments_in_failure: list[dict] = []
        self.degraded_sqlite = None
        self.degraded_jsonl = None


class _StoppedEventsReader:
    def status_snapshot(self) -> _ReaderSnapshot:
        return _ReaderSnapshot()

    def is_running(self) -> bool:
        return False


def test_status_reports_events_reader_not_running_when_thread_stopped(
    tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path)
    ctx.events_reader = _StoppedEventsReader()
    envelope = DISPATCH["status"](ctx, {})
    assert envelope["ok"] is True
    assert envelope["result"]["events_reader"]["running"] is False


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


# ---------------------------------------------------------------------------
# Review-pass-1: peer_uid is plumbed out-of-band, not via params.
# Regression for the FEAT-006 review finding that ``params.pop("__socket_peer_uid__")``
# allowed a client to spoof audit provenance (and silently fell back to -1
# whether or not the server populated it). The dispatcher MUST source
# peer_uid from the third positional arg the server provides from
# SO_PEERCRED, and MUST NOT consult the params object for it.
# ---------------------------------------------------------------------------


class _RecordingAgentService:
    """Minimal stand-in for ``AgentService`` used to capture peer_uid."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, int | None]] = []

    def register_agent(self, params, *, socket_peer_uid):  # noqa: ANN001
        self.calls.append(("register_agent", dict(params), socket_peer_uid))
        return {"agent_id": "agt_000000000001", "role": "unknown"}

    def set_role(self, params, *, socket_peer_uid):  # noqa: ANN001
        self.calls.append(("set_role", dict(params), socket_peer_uid))
        return {"agent_id": params.get("agent_id"), "role": params.get("role")}


def _agent_ctx(tmp_path: Path, service: _RecordingAgentService) -> DaemonContext:
    ctx = _ctx(tmp_path)
    ctx.agent_service = service
    return ctx


def test_register_agent_uses_third_arg_peer_uid(tmp_path: Path) -> None:
    service = _RecordingAgentService()
    ctx = _agent_ctx(tmp_path, service)
    DISPATCH["register_agent"](ctx, {"role": "slave"}, 4242)
    assert service.calls == [("register_agent", {"role": "slave"}, 4242)]


def test_register_agent_ignores_params_socket_peer_uid_field(tmp_path: Path) -> None:
    """A client cannot spoof socket_peer_uid via the request body."""
    service = _RecordingAgentService()
    ctx = _agent_ctx(tmp_path, service)
    DISPATCH["register_agent"](
        ctx,
        {"role": "slave", "__socket_peer_uid__": 9999, "socket_peer_uid": 9999},
        1000,
    )
    # The recorded peer_uid is the third arg the server supplied — the
    # spoofed body fields are forwarded unchanged but ignored by audit.
    assert service.calls[0][2] == 1000


class _RecordingPaneService:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def scan_for_container(self, *, container_id: str | None):  # noqa: ANN001
        self.calls.append(container_id)
        return type(
            "PaneScanResultStub",
            (),
            {
                "scan_id": "scan-1",
                "started_at": "2026-05-07T00:00:00.000000+00:00",
                "completed_at": "2026-05-07T00:00:01.000000+00:00",
                "status": "ok",
                "containers_scanned": 1,
                "sockets_scanned": 1,
                "panes_seen": 1,
                "panes_newly_active": 0,
                "panes_reconciled_inactive": 0,
                "containers_skipped_inactive": 0,
                "containers_tmux_unavailable": 0,
                "error_code": None,
                "error_message": None,
                "error_details": (),
            },
        )()


def test_scan_panes_honors_optional_container_scope(tmp_path: Path) -> None:
    service = _RecordingPaneService()
    ctx = _ctx(tmp_path)
    ctx.pane_service = service

    envelope = DISPATCH["scan_panes"](ctx, {"container": "a" * 64})

    assert envelope["ok"] is True
    assert service.calls == ["a" * 64]


def test_scan_panes_rejects_non_string_container_scope(tmp_path: Path) -> None:
    service = _RecordingPaneService()
    ctx = _ctx(tmp_path)
    ctx.pane_service = service

    envelope = DISPATCH["scan_panes"](ctx, {"container": 123})

    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "bad_request"
    assert service.calls == []


def test_register_agent_default_peer_uid_when_called_without_third_arg(
    tmp_path: Path,
) -> None:
    """Tests that exercise DISPATCH directly without a real socket get -1."""
    service = _RecordingAgentService()
    ctx = _agent_ctx(tmp_path, service)
    DISPATCH["register_agent"](ctx, {"role": "slave"})
    assert service.calls[0][2] == -1


def test_set_role_uses_third_arg_peer_uid(tmp_path: Path) -> None:
    service = _RecordingAgentService()
    ctx = _agent_ctx(tmp_path, service)
    DISPATCH["set_role"](ctx, {"agent_id": "agt_x", "role": "slave"}, 1000)
    assert service.calls[-1] == (
        "set_role",
        {"agent_id": "agt_x", "role": "slave"},
        1000,
    )


def test_events_list_rejects_non_boolean_reverse(tmp_path: Path) -> None:
    envelope = DISPATCH["events.list"](_ctx(tmp_path), {"reverse": "false"})
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "events_filter_invalid"


def test_events_filter_compares_since_until_chronologically() -> None:
    """Different offsets must be compared as instants, not strings."""
    err = _events_validate_filter(
        {
            "since": "2026-05-10T10:00:00+02:00",
            "until": "2026-05-10T09:30:00+00:00",
        }
    )
    assert err is None


def test_events_filter_rejects_naive_since_timestamp() -> None:
    err = _events_validate_filter({"since": "2026-05-10T10:00:00"})
    assert err is not None
    assert err["error"]["code"] == "events_filter_invalid"


def test_events_follow_next_rejects_non_numeric_max_wait(tmp_path: Path) -> None:
    registry = FollowSessionRegistry()
    session = registry.open(
        target_agent_id=None,
        types=(),
        since_iso=None,
        live_starting_event_id=0,
        expires_at_monotonic=time.monotonic() + 60.0,
    )
    ctx = _ctx(tmp_path)
    ctx.follow_session_registry = registry
    envelope = DISPATCH["events.follow_next"](
        ctx, {"session_id": session.session_id, "max_wait_seconds": "1"}
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "events_filter_invalid"
