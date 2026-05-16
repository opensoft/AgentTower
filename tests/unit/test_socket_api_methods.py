"""Unit tests for FEAT-002 socket_api method dispatch (T013)."""

from __future__ import annotations

import sqlite3
import time
import os
from datetime import datetime, timezone
from pathlib import Path

from agenttower.agents.permissions import serialize_effective_permissions
from agenttower.events.dao import EventRow, insert_audit_event, insert_event
from agenttower.events.session_registry import FollowSessionRegistry
from agenttower.socket_api import methods as methods_mod
from agenttower.socket_api.methods import (
    DISPATCH,
    DaemonContext,
    _clear_request_peer_context,
    _events_validate_filter,
    _set_request_peer_context,
)
from agenttower.state import schema
from agenttower.state.agents import insert_agent


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
    # additions + FEAT-007 additions + FEAT-008 additions + FEAT-009
    # additions (FR-022 / FR-030 backward-compat; FR-023 for FEAT-006;
    # FR-038 for FEAT-007).
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
        # FEAT-009 — queue + routing dispatch (T049).
        "queue.send_input",
        "queue.list",
        "queue.approve",
        "queue.delay",
        "queue.cancel",
        "routing.enable",
        "routing.disable",
        "routing.status",
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
        # FEAT-009 — plan §"Status surface". With no routing service or
        # audit writer wired, the blocks report the not-running defaults.
        "routing",
        "queue_audit",
    }
    assert set(result.keys()) == expected_keys
    assert result["routing"] == {
        "value": None,
        "last_updated_at": None,
        "last_updated_by": None,
    }
    assert result["queue_audit"] == {
        "degraded": False,
        "pending_rows": 0,
        "last_failure_exc_class": None,
    }
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


def test_events_list_excludes_feat009_audit_rows_by_default(tmp_path: Path) -> None:
    conn, _ = schema.open_registry(tmp_path / "agenttower.sqlite3")
    try:
        insert_event(
            conn,
            EventRow(
                event_id=0,
                event_type="activity",
                agent_id="agt_aaaaaaaaaaaa",
                attachment_id="atc_aabbccddeeff",
                log_path="/tmp/agent.log",
                byte_range_start=0,
                byte_range_end=10,
                line_offset_start=0,
                line_offset_end=1,
                observed_at="2026-05-15T12:00:00.000Z",
                record_at=None,
                excerpt="activity",
                classifier_rule_id="activity.fallback.v1",
                debounce_window_id=None,
                debounce_collapsed_count=1,
                debounce_window_started_at=None,
                debounce_window_ended_at=None,
                schema_version=1,
                jsonl_appended_at=None,
            ),
        )
        insert_audit_event(
            conn,
            event_type="queue_message_enqueued",
            agent_id="agt_aaaaaaaaaaaa",
            observed_at="2026-05-15T12:00:01.000Z",
            excerpt="audit row",
        )
        conn.commit()
    finally:
        conn.close()

    ctx = _ctx(tmp_path)
    envelope = DISPATCH["events.list"](ctx, {})
    assert envelope["ok"] is True
    events = envelope["result"]["events"]
    assert [event["event_type"] for event in events] == ["activity"]


class _QueueListService:
    def resolve_target_agent_id(self, target_input: str) -> str:
        if target_input == "ambiguous":
            from agenttower.routing.errors import TargetResolveError

            raise TargetResolveError("target_label_ambiguous", "ambiguous")
        return "agt_aaaaaaaaaaaa"

    def list_rows(self, filters):  # noqa: ANN001
        return []

    def read_envelope_excerpt(self, message_id: str) -> str:
        return f"excerpt:{message_id}"

    def approve(self, message_id: str, *, operator: str):  # noqa: ANN001
        return self._row(message_id)

    def delay(self, message_id: str, *, operator: str):  # noqa: ANN001
        return self._row(message_id, state="blocked", block_reason="operator_delayed")

    def cancel(self, message_id: str, *, operator: str):  # noqa: ANN001
        return self._row(message_id, state="canceled")

    @staticmethod
    def _row(message_id: str, *, state: str = "queued", block_reason: str | None = None):
        from types import SimpleNamespace

        return SimpleNamespace(
            message_id=message_id,
            state=state,
            block_reason=block_reason,
            failure_reason=None,
            sender_agent_id="agt_aaaaaaaaaaaa",
            sender_label="master-a",
            sender_role="master",
            sender_capability="codex",
            target_agent_id="agt_bbbbbbbbbbbb",
            target_label="slave-1",
            target_role="slave",
            target_capability="codex",
            target_container_id="c" * 64,
            target_pane_id="%2",
            envelope_body_sha256="00" * 32,
            envelope_size_bytes=5,
            enqueued_at="2026-05-15T12:00:00.000Z",
            delivery_attempt_started_at=None,
            delivered_at=None,
            failed_at=None,
            canceled_at=None,
            last_updated_at="2026-05-15T12:00:01.000Z",
            operator_action=None,
            operator_action_at=None,
            operator_action_by=None,
        )


class _QueueSendInputService:
    def __init__(self) -> None:
        self.sender_agent_id: str | None = None

    def send_input(  # noqa: ANN001
        self,
        *,
        sender,
        target_input: str,
        body_bytes: bytes,
        wait: bool,
        wait_timeout: float | None,
    ):
        from types import SimpleNamespace

        self.sender_agent_id = sender.agent_id
        row = _QueueListService._row("msg-1")
        return SimpleNamespace(row=row, waited_to_terminal=False)


def _insert_active_agent_for_ctx(tmp_path: Path) -> None:
    conn, _ = schema.open_registry(tmp_path / "agenttower.sqlite3")
    try:
        insert_agent(
            conn,
            agent_id="agt_aaaaaaaaaaaa",
            pane_key=("c" * 64, "/tmp/tmux.sock", "s", 0, 0, "%1"),
            role="master",
            capability="codex",
            label="master-a",
            project_path="/workspace",
            parent_agent_id=None,
            effective_permissions_json=serialize_effective_permissions("master"),
            created_at="2026-05-15T12:00:00.000Z",
            last_registered_at="2026-05-15T12:00:00.000Z",
            active=True,
        )
        conn.commit()
    finally:
        conn.close()


def test_queue_list_rejects_non_string_target_filter(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.queue_service = _QueueListService()
    ctx.routing_flag_service = object()
    envelope = DISPATCH["queue.list"](ctx, {"target": 123})
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "bad_request"


def test_queue_send_input_resolves_sender_from_pane_key(tmp_path: Path) -> None:
    _insert_active_agent_for_ctx(tmp_path)
    ctx = _ctx(tmp_path)
    ctx.queue_service = _QueueSendInputService()
    ctx.routing_flag_service = object()
    envelope = DISPATCH["queue.send_input"](
        ctx,
        {
            "target": "slave-1",
            "body_bytes": "aGVsbG8=",
            "caller_pane": {
                "agent_id": "agt_aaaaaaaaaaaa",
                "pane_composite_key": {
                    "container_id": "c" * 64,
                    "tmux_socket_path": "/tmp/tmux.sock",
                    "tmux_session_name": "s",
                    "tmux_window_index": 0,
                    "tmux_pane_index": 0,
                    "tmux_pane_id": "%1",
                },
            },
        },
    )
    assert envelope["ok"] is True
    assert ctx.queue_service.sender_agent_id == "agt_aaaaaaaaaaaa"


def test_queue_send_input_rejects_agent_only_caller_identity(tmp_path: Path) -> None:
    _insert_active_agent_for_ctx(tmp_path)
    ctx = _ctx(tmp_path)
    ctx.queue_service = _QueueSendInputService()
    ctx.routing_flag_service = object()
    envelope = DISPATCH["queue.send_input"](
        ctx,
        {
            "target": "slave-1",
            "body_bytes": "aGVsbG8=",
            "caller_pane": {"agent_id": "agt_aaaaaaaaaaaa"},
        },
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "bad_request"


def test_queue_list_rejects_empty_sender_filter(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    ctx.queue_service = _QueueListService()
    ctx.routing_flag_service = object()
    envelope = DISPATCH["queue.list"](ctx, {"sender": ""})
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "bad_request"


def test_queue_operator_actions_return_excerpt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _ctx(tmp_path)
    ctx.queue_service = _QueueListService()
    ctx.routing_flag_service = object()
    # Host-context detection via ``/proc/<pid>`` may flip false on
    # dev machines that carry container markers (e.g. ``/.dockerenv``
    # on WSL2 Docker-in-Docker setups). Force-true so this test
    # exercises the excerpt-rendering path regardless of the host env.
    monkeypatch.setattr(methods_mod, "_peer_is_host_process", lambda pid: True)
    _set_request_peer_context(peer_pid=os.getpid())
    try:
        for method in ("queue.approve", "queue.delay", "queue.cancel"):
            envelope = DISPATCH[method](ctx, {"message_id": "msg-1"})
            assert envelope["ok"] is True
            assert envelope["result"]["excerpt"] == "excerpt:msg-1"
    finally:
        _clear_request_peer_context()


def test_queue_operator_action_without_caller_pane_is_not_host_by_default(
    tmp_path: Path, monkeypatch
) -> None:
    ctx = _ctx(tmp_path)
    ctx.queue_service = _QueueListService()
    ctx.routing_flag_service = object()
    _set_request_peer_context(peer_pid=os.getpid())
    monkeypatch.setattr(methods_mod, "_peer_is_host_process", lambda pid: False)
    try:
        envelope = DISPATCH["queue.approve"](ctx, {"message_id": "msg-1"})
    finally:
        _clear_request_peer_context()
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "bad_request"


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
