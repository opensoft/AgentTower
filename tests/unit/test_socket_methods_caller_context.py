"""T050 — FEAT-009 socket dispatch caller-context gate tests.

Verifies the boundary checks each FEAT-009 dispatcher applies before
delegating to the service layer:

* ``queue.send_input`` from host-origin context (``caller_pane is None``) →
  closed-set ``sender_not_in_pane``.
* ``routing.enable`` / ``routing.disable`` from a bench-container context
  (``caller_pane is not None``) → ``routing_toggle_host_only``. Same gate
  also refuses peer-uid mismatch.
* ``routing.status`` and ``queue.list`` accept both origins.
* ``queue.approve`` / ``queue.delay`` / ``queue.cancel`` operator-action
  liveness (Group-A walk Q8):
  - caller pane resolves to an inactive registered agent →
    closed-set ``operator_pane_inactive``.
  - caller pane resolves to an active agent → proceeds and writes that
    agent_id to ``operator_action_by``.
  - host-origin caller (no pane) → proceeds and writes the
    ``host-operator`` sentinel.

These tests substitute simple stubs for ``QueueService`` /
``RoutingFlagService`` / SQLite connection; the integration tests in
US3 / US4 exercise the full path.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agenttower.routing.dao import QueueListFilter, QueueRow
from agenttower.routing.errors import (
    OperatorPaneInactive,
    QueueServiceError,
)
from agenttower.socket_api.methods import DISPATCH, DaemonContext


HOST_OPERATOR = "host-operator"


# ──────────────────────────────────────────────────────────────────────
# Stubs for the FEAT-009 services consumed by the dispatchers
# ──────────────────────────────────────────────────────────────────────


class _FakeRoutingFlagService:
    """Minimal :class:`RoutingFlagService` stub for dispatch tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def is_enabled(self) -> bool:
        return True

    def read_full(self) -> tuple[str, str, str]:
        return "enabled", "2026-05-11T00:00:00.000Z", HOST_OPERATOR

    def enable(self, *, operator: str, ts: str) -> Any:
        self.calls.append(("enable", operator, ts))

        class _R:
            previous_value = "disabled"
            current_value = "enabled"
            changed = True
            last_updated_at = ts
            last_updated_by = operator
        return _R()

    def disable(self, *, operator: str, ts: str) -> Any:
        self.calls.append(("disable", operator, ts))

        class _R:
            previous_value = "enabled"
            current_value = "disabled"
            changed = True
            last_updated_at = ts
            last_updated_by = operator
        return _R()


def _make_row(*, message_id: str = "11111111-2222-3333-4444-555555555555") -> QueueRow:
    return QueueRow(
        message_id=message_id,
        state="queued",
        block_reason=None,
        failure_reason=None,
        sender_agent_id="agt_000000000001",
        sender_label="alice",
        sender_role="master",
        sender_capability="codex",
        target_agent_id="agt_000000000002",
        target_label="bob",
        target_role="slave",
        target_capability="codex",
        target_container_id="cont_xyz",
        target_pane_id="%1",
        envelope_body_sha256="abc" * 21 + "d",  # 64 chars
        envelope_size_bytes=64,
        enqueued_at="2026-05-11T00:00:00.000Z",
        delivery_attempt_started_at=None,
        delivered_at=None,
        failed_at=None,
        canceled_at=None,
        last_updated_at="2026-05-11T00:00:00.000Z",
        operator_action=None,
        operator_action_at=None,
        operator_action_by=None,
    )


class _FakeQueueService:
    """Captures the operator argument so tests can assert what
    ``operator_action_by`` the dispatcher resolved."""

    def __init__(
        self,
        *,
        approve_raises: Exception | None = None,
        delay_raises: Exception | None = None,
        cancel_raises: Exception | None = None,
    ) -> None:
        self.send_calls: list[dict[str, Any]] = []
        self.list_calls: list[QueueListFilter] = []
        self.approve_calls: list[tuple[str, str]] = []
        self.delay_calls: list[tuple[str, str]] = []
        self.cancel_calls: list[tuple[str, str]] = []
        self._approve_raises = approve_raises
        self._delay_raises = delay_raises
        self._cancel_raises = cancel_raises

    def send_input(self, **kwargs: Any) -> Any:
        self.send_calls.append(kwargs)

        class _R:
            row = _make_row()
            waited_to_terminal = False
        return _R()

    def list_rows(self, filters: QueueListFilter) -> list[QueueRow]:
        self.list_calls.append(filters)
        return [_make_row()]

    def resolve_target_agent_id(self, target_input: str) -> str:
        # Tests pass plain agent_ids; pass through verbatim.
        return target_input

    def read_envelope_excerpt(self, message_id: str) -> str:
        return ""

    def approve(self, message_id: str, *, operator: str) -> QueueRow:
        self.approve_calls.append((message_id, operator))
        if self._approve_raises is not None:
            raise self._approve_raises
        return _make_row(message_id=message_id)

    def delay(self, message_id: str, *, operator: str) -> QueueRow:
        self.delay_calls.append((message_id, operator))
        if self._delay_raises is not None:
            raise self._delay_raises
        return _make_row(message_id=message_id)

    def cancel(self, message_id: str, *, operator: str) -> QueueRow:
        self.cancel_calls.append((message_id, operator))
        if self._cancel_raises is not None:
            raise self._cancel_raises
        return _make_row(message_id=message_id)


# ──────────────────────────────────────────────────────────────────────
# Test fixtures: a wired DaemonContext + a small in-memory ``agents`` row
# ──────────────────────────────────────────────────────────────────────


def _make_state_conn(
    *, agent_id: str, active: bool,
) -> sqlite3.Connection:
    """Build an in-memory state DB with one agents row matching the
    ``select_agent_by_id`` SELECT in ``state/agents.py``.

    Production-side the agents table is created by the schema migration
    chain; here we re-declare the minimal column set used by the
    ``_AGENT_COLUMNS`` projection.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE agents (
            agent_id TEXT PRIMARY KEY,
            container_id TEXT NOT NULL,
            tmux_socket_path TEXT NOT NULL,
            tmux_session_name TEXT NOT NULL,
            tmux_window_index INTEGER NOT NULL,
            tmux_pane_index INTEGER NOT NULL,
            tmux_pane_id TEXT NOT NULL,
            role TEXT NOT NULL,
            capability TEXT NOT NULL,
            label TEXT NOT NULL,
            project_path TEXT NOT NULL,
            parent_agent_id TEXT,
            effective_permissions TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_registered_at TEXT NOT NULL,
            last_seen_at TEXT,
            active INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            agent_id, "cont_xyz", "/tmp/tmux.sock", "swarm", 0, 0, "%1",
            "master", "codex", "alice", "/work/repo", None, "{}",
            "2026-05-11T00:00:00.000Z", "2026-05-11T00:00:00.000Z",
            "2026-05-11T00:00:00.000Z", 1 if active else 0,
        ),
    )
    conn.commit()
    return conn


def _make_ctx(
    tmp_path: Path,
    *,
    queue_service: Any,
    routing_flag_service: Any,
    state_conn: sqlite3.Connection | None = None,
) -> DaemonContext:
    return DaemonContext(
        pid=4242,
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=tmp_path,
        daemon_version="0.0.0+test",
        schema_version=7,
        queue_service=queue_service,
        routing_flag_service=routing_flag_service,
        state_conn=state_conn,
    )


# ──────────────────────────────────────────────────────────────────────
# 1. queue.send_input — host-origin rejected with sender_not_in_pane
# ──────────────────────────────────────────────────────────────────────


def test_send_input_from_host_origin_returns_sender_not_in_pane(tmp_path: Path) -> None:
    ctx = _make_ctx(
        tmp_path,
        queue_service=_FakeQueueService(),
        routing_flag_service=_FakeRoutingFlagService(),
    )
    envelope = DISPATCH["queue.send_input"](
        ctx,
        {"target": "agt_000000000002", "body_bytes": "aGk="},  # 'hi' in base64
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "sender_not_in_pane"


def test_send_input_with_inactive_caller_pane_returns_sender_role_not_permitted(
    tmp_path: Path,
) -> None:
    """An inactive caller pane is functionally equivalent to a missing
    sender; the send-input surface maps it to FR-021/FR-023's
    ``sender_role_not_permitted`` for parity with intrinsic role refusals.
    """
    conn = _make_state_conn(agent_id="agt_000000000001", active=False)
    ctx = _make_ctx(
        tmp_path,
        queue_service=_FakeQueueService(),
        routing_flag_service=_FakeRoutingFlagService(),
        state_conn=conn,
    )
    envelope = DISPATCH["queue.send_input"](
        ctx,
        {
            "target": "agt_000000000002",
            "body_bytes": "aGk=",
            "caller_pane": {"agent_id": "agt_000000000001"},
        },
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "sender_role_not_permitted"


def test_send_input_with_active_caller_pane_invokes_service(tmp_path: Path) -> None:
    conn = _make_state_conn(agent_id="agt_000000000001", active=True)
    fake = _FakeQueueService()
    ctx = _make_ctx(
        tmp_path,
        queue_service=fake,
        routing_flag_service=_FakeRoutingFlagService(),
        state_conn=conn,
    )
    envelope = DISPATCH["queue.send_input"](
        ctx,
        {
            "target": "agt_000000000002",
            "body_bytes": "aGk=",
            "caller_pane": {"agent_id": "agt_000000000001"},
            "wait": False,
        },
    )
    assert envelope["ok"] is True
    assert len(fake.send_calls) == 1
    call = fake.send_calls[0]
    assert call["sender"].agent_id == "agt_000000000001"
    assert call["target_input"] == "agt_000000000002"
    assert call["body_bytes"] == b"hi"


# ──────────────────────────────────────────────────────────────────────
# 2. routing.enable — bench-container caller rejected; host accepted
# ──────────────────────────────────────────────────────────────────────


def test_routing_enable_from_bench_caller_returns_routing_toggle_host_only(
    tmp_path: Path,
) -> None:
    routing = _FakeRoutingFlagService()
    ctx = _make_ctx(
        tmp_path,
        queue_service=_FakeQueueService(),
        routing_flag_service=routing,
    )
    envelope = DISPATCH["routing.enable"](
        ctx, {"caller_pane": {"agent_id": "agt_000000000001"}},
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "routing_toggle_host_only"
    assert routing.calls == []  # service never invoked


def test_routing_enable_from_host_origin_invokes_service(tmp_path: Path) -> None:
    routing = _FakeRoutingFlagService()
    ctx = _make_ctx(
        tmp_path,
        queue_service=_FakeQueueService(),
        routing_flag_service=routing,
    )
    import os
    envelope = DISPATCH["routing.enable"](ctx, {}, peer_uid=os.geteuid())
    assert envelope["ok"] is True, envelope
    assert envelope["result"]["current_value"] == "enabled"
    assert len(routing.calls) == 1
    assert routing.calls[0][0] == "enable"
    assert routing.calls[0][1] == HOST_OPERATOR


def test_routing_disable_from_bench_caller_returns_routing_toggle_host_only(
    tmp_path: Path,
) -> None:
    ctx = _make_ctx(
        tmp_path,
        queue_service=_FakeQueueService(),
        routing_flag_service=_FakeRoutingFlagService(),
    )
    envelope = DISPATCH["routing.disable"](
        ctx, {"caller_pane": {"agent_id": "agt_000000000001"}},
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "routing_toggle_host_only"


def test_routing_toggle_with_peer_uid_mismatch_refused(tmp_path: Path) -> None:
    """Even with no caller_pane, a peer_uid that doesn't match the
    daemon's geteuid() is refused as a defense-in-depth check against
    a same-host attacker who forges a host-origin envelope. The gate
    uses ``geteuid()`` to match the FEAT-002 ``ControlServer`` peer-
    credential check."""
    ctx = _make_ctx(
        tmp_path,
        queue_service=_FakeQueueService(),
        routing_flag_service=_FakeRoutingFlagService(),
    )
    import os
    bogus_uid = os.geteuid() + 1_000_000  # vanishingly unlikely to collide
    envelope = DISPATCH["routing.enable"](ctx, {}, peer_uid=bogus_uid)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "routing_toggle_host_only"


# ──────────────────────────────────────────────────────────────────────
# 3. routing.status and queue.list accept both origins
# ──────────────────────────────────────────────────────────────────────


def test_routing_status_accepts_host_caller(tmp_path: Path) -> None:
    ctx = _make_ctx(
        tmp_path,
        queue_service=_FakeQueueService(),
        routing_flag_service=_FakeRoutingFlagService(),
    )
    envelope = DISPATCH["routing.status"](ctx, {})
    assert envelope["ok"] is True
    assert envelope["result"]["value"] == "enabled"


def test_routing_status_accepts_bench_caller(tmp_path: Path) -> None:
    ctx = _make_ctx(
        tmp_path,
        queue_service=_FakeQueueService(),
        routing_flag_service=_FakeRoutingFlagService(),
    )
    envelope = DISPATCH["routing.status"](
        ctx, {"caller_pane": {"agent_id": "agt_000000000001"}},
    )
    assert envelope["ok"] is True


def test_queue_list_accepts_host_caller(tmp_path: Path) -> None:
    fake = _FakeQueueService()
    ctx = _make_ctx(
        tmp_path,
        queue_service=fake,
        routing_flag_service=_FakeRoutingFlagService(),
    )
    envelope = DISPATCH["queue.list"](ctx, {})
    assert envelope["ok"] is True
    assert isinstance(envelope["result"]["rows"], list)
    assert len(fake.list_calls) == 1


def test_queue_list_accepts_bench_caller(tmp_path: Path) -> None:
    fake = _FakeQueueService()
    ctx = _make_ctx(
        tmp_path,
        queue_service=fake,
        routing_flag_service=_FakeRoutingFlagService(),
    )
    envelope = DISPATCH["queue.list"](
        ctx, {"caller_pane": {"agent_id": "agt_000000000001"}},
    )
    assert envelope["ok"] is True


# ──────────────────────────────────────────────────────────────────────
# 4. Operator-action liveness (Group-A walk Q8)
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method", ["queue.approve", "queue.delay", "queue.cancel"])
def test_operator_action_inactive_caller_returns_operator_pane_inactive(
    tmp_path: Path, method: str,
) -> None:
    conn = _make_state_conn(agent_id="agt_000000000001", active=False)
    fake = _FakeQueueService()
    ctx = _make_ctx(
        tmp_path,
        queue_service=fake,
        routing_flag_service=_FakeRoutingFlagService(),
        state_conn=conn,
    )
    envelope = DISPATCH[method](
        ctx,
        {
            "message_id": "11111111-2222-3333-4444-555555555555",
            "caller_pane": {"agent_id": "agt_000000000001"},
        },
    )
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "operator_pane_inactive"
    # Service was NOT invoked — the gate rejected before delegation.
    assert fake.approve_calls == []
    assert fake.delay_calls == []
    assert fake.cancel_calls == []


@pytest.mark.parametrize(
    "method, attr",
    [
        ("queue.approve", "approve_calls"),
        ("queue.delay", "delay_calls"),
        ("queue.cancel", "cancel_calls"),
    ],
)
def test_operator_action_active_caller_writes_agent_id(
    tmp_path: Path, method: str, attr: str,
) -> None:
    conn = _make_state_conn(agent_id="agt_000000000001", active=True)
    fake = _FakeQueueService()
    ctx = _make_ctx(
        tmp_path,
        queue_service=fake,
        routing_flag_service=_FakeRoutingFlagService(),
        state_conn=conn,
    )
    envelope = DISPATCH[method](
        ctx,
        {
            "message_id": "11111111-2222-3333-4444-555555555555",
            "caller_pane": {"agent_id": "agt_000000000001"},
        },
    )
    assert envelope["ok"] is True, envelope
    calls = getattr(fake, attr)
    assert len(calls) == 1
    _msg, operator = calls[0]
    assert operator == "agt_000000000001"


@pytest.mark.parametrize(
    "method, attr",
    [
        ("queue.approve", "approve_calls"),
        ("queue.delay", "delay_calls"),
        ("queue.cancel", "cancel_calls"),
    ],
)
def test_operator_action_host_origin_writes_host_operator_sentinel(
    tmp_path: Path, method: str, attr: str,
) -> None:
    fake = _FakeQueueService()
    ctx = _make_ctx(
        tmp_path,
        queue_service=fake,
        routing_flag_service=_FakeRoutingFlagService(),
    )
    envelope = DISPATCH[method](
        ctx, {"message_id": "11111111-2222-3333-4444-555555555555"},
    )
    assert envelope["ok"] is True, envelope
    calls = getattr(fake, attr)
    assert len(calls) == 1
    _msg, operator = calls[0]
    assert operator == HOST_OPERATOR
