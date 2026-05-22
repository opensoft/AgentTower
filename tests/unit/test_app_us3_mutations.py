"""FEAT-011 T060–T065 unit tests — US3 operator-mutation handlers.

Covers the 10 operator-mutation methods added to ``app_contract/mutations.py``:

* ``app.agent.update``  (T060) — against a real FEAT-006 ``AgentService``.
* ``app.log.attach`` / ``app.log.detach`` (T061/T062) — against a stub
  ``LogService`` (the real FEAT-007 attach pipeline needs docker-exec).
* ``app.send_input`` (T063) — against a stub FEAT-009 ``QueueService``.
* ``app.queue.{approve,delay,cancel}`` (T064) — stub ``QueueService``.
* ``app.route.{add,remove,update}`` (T065) — stub FEAT-010 ``RoutesService``.

Handlers are called directly (no socket round-trip). Real services are
stood up where cheap (AgentService + state DB); FEAT-007/009/010 use
fakes — the handler's validation, error-mapping, envelope shape, and
audit emission are still exercised end-to-end.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttower.agents.errors import RegistrationError
from agenttower.app_contract import mutations, sessions
from agenttower.routing.errors import QueueServiceError
from agenttower.routing.route_errors import (
    RouteEventTypeInvalid,
    RouteIdNotFound,
)
from agenttower.socket_api.methods import (
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)
from tests.unit._agent_test_helpers import (
    CK_DEFAULT,
    make_service,
    seed_container,
    seed_pane,
)


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_registry() -> None:
    sessions.set_registry(sessions.SessionRegistry())


@pytest.fixture
def host_peer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    _set_request_peer_context(peer_pid=os.getpid())
    try:
        yield os.geteuid()
    finally:
        _clear_request_peer_context()


def _mint_session(ctx: DaemonContext, host_peer: int) -> str:
    from agenttower.app_contract import hello as hello_mod

    env = hello_mod.app_hello(ctx, {}, peer_uid=host_peer)
    assert env["ok"], env
    return env["result"]["app_session_token"]


# ─── AgentService-backed context (T060) ──────────────────────────────────


@pytest.fixture
def agent_ctx(tmp_path: Path) -> DaemonContext:
    service = make_service(tmp_path)
    state_db = tmp_path / "state" / "agenttower.sqlite3"
    seed_container(service)
    seed_pane(service)
    return DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=state_db,
        daemon_version="0.0.0-test",
        schema_version=4,
        agent_service=service,
        events_file=service.events_file,
    )


def _register_agent(ctx: DaemonContext, token: str, uid: int, **overrides) -> str:
    """Adopt the seeded pane → return the new agent_id."""
    params = {
        "app_session_token": token,
        "container_id": CK_DEFAULT[0],
        "tmux_socket": CK_DEFAULT[1],
        "session_name": CK_DEFAULT[2],
        "window_index": CK_DEFAULT[3],
        "pane_index": CK_DEFAULT[4],
        "pane_id": CK_DEFAULT[5],
        "role": "slave",
        "capability": "claude",
        "label": "agt",
    }
    params.update(overrides)
    env = mutations.app_agent_register_from_pane(ctx, params, peer_uid=uid)
    assert env["ok"] is True, env
    return env["result"]["row"]["agent_id"]


# ════════════════════════════════════════════════════════════════════════
# T060 — app.agent.update
# ════════════════════════════════════════════════════════════════════════


def test_agent_update_happy_path_role(agent_ctx: DaemonContext, host_peer: int) -> None:
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "role": "test-runner"},
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["role"] == "test-runner"
    assert env["result"]["row"]["agent_id"] == agent_id


def test_agent_update_capability_and_label(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    env = mutations.app_agent_update(
        agent_ctx,
        {
            "app_session_token": token,
            "agent_id": agent_id,
            "capability": "codex",
            "label": "  renamed  ",
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["capability"] == "codex"
    assert env["result"]["row"]["label"] == "renamed"  # trimmed (FR-028d)


def test_agent_update_clears_project_path_with_empty_string(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-029a: empty string clears project_path."""
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    # First set a project_path.
    set_env = mutations.app_agent_update(
        agent_ctx,
        {
            "app_session_token": token,
            "agent_id": agent_id,
            "project_path": "/workspace/proj",
        },
        peer_uid=host_peer,
    )
    assert set_env["ok"] is True, set_env
    assert set_env["result"]["row"]["project_path"] == "/workspace/proj"
    # Now clear it.
    clear_env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "project_path": ""},
        peer_uid=host_peer,
    )
    assert clear_env["ok"] is True, clear_env
    assert clear_env["result"]["row"]["project_path"] in ("", None)


def test_agent_update_absent_field_no_change(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-029a: an absent field leaves the row unchanged."""
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "label": "only-label"},
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    # role / capability untouched.
    assert env["result"]["row"]["role"] == "slave"
    assert env["result"]["row"]["capability"] == "claude"
    assert env["result"]["row"]["label"] == "only-label"


def test_agent_update_empty_role_rejected(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-029a: empty string on role is NOT clearable → validation_failed."""
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "role": ""},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "role"


def test_agent_update_empty_capability_rejected(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-029a: empty string on capability is NOT clearable."""
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "capability": ""},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "capability"


def test_agent_update_invalid_role_rejected(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-029a: role outside the closed set → validation_failed.field=role."""
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "role": "not-a-role"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "role"


def test_agent_update_unknown_agent_returns_agent_not_found(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(agent_ctx, host_peer)
    env = mutations.app_agent_update(
        agent_ctx,
        {
            "app_session_token": token,
            "agent_id": "agt_" + "0" * 12,
            "label": "x",
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "agent_not_found"
    assert env["error"]["details"]["agent_id"] == "agt_" + "0" * 12


def test_agent_update_never_returns_stale_object(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-030a: last-write-wins — two updates both succeed, no stale_object."""
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    first = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "label": "first"},
        peer_uid=host_peer,
    )
    second = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "label": "second"},
        peer_uid=host_peer,
    )
    assert first["ok"] is True and second["ok"] is True
    assert second["result"]["row"]["label"] == "second"


def test_agent_update_missing_agent_id_validation_failed(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(agent_ctx, host_peer)
    env = mutations.app_agent_update(
        agent_ctx, {"app_session_token": token}, peer_uid=host_peer
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "agent_id"


def test_agent_update_unwired_service_returns_internal_error(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(agent_ctx, host_peer)
    agent_ctx.agent_service = None
    env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": "agt_x", "label": "y"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


def test_agent_update_emits_audit_row(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-044: a successful update emits an origin='app' audit row."""
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "role": "test-runner"},
        peer_uid=host_peer,
    )
    contents = agent_ctx.events_file.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in contents.splitlines() if line.strip()]
    app_rows = [
        r
        for r in rows
        if r.get("origin") == "app" and r.get("event_type") == "agent_updated"
    ]
    assert len(app_rows) == 1
    assert app_rows[0]["agent_id"] == agent_id
    assert token not in contents  # SC-008


def test_agent_update_session_gate(agent_ctx: DaemonContext, host_peer: int) -> None:
    env = mutations.app_agent_update(
        agent_ctx, {"agent_id": "agt_x", "label": "y"}, peer_uid=host_peer
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "app_session_required"


# ════════════════════════════════════════════════════════════════════════
# Stub services for FEAT-007 / 009 / 010
# ════════════════════════════════════════════════════════════════════════


class _FakeLogService:
    """Minimal FEAT-007 ``LogService`` stand-in.

    ``attach_log`` / ``detach_log`` accept ``(params, *, socket_peer_uid,
    ...)`` and either succeed or raise a ``RegistrationError`` with a
    caller-chosen code, mirroring the real service's exception contract.
    """

    def __init__(
        self,
        *,
        attach_error: RegistrationError | None = None,
        detach_error: RegistrationError | None = None,
    ) -> None:
        self.attach_error = attach_error
        self.detach_error = detach_error
        self.attach_calls = 0
        self.detach_calls = 0

    def attach_log(self, params, *, socket_peer_uid, source="explicit"):
        self.attach_calls += 1
        if self.attach_error is not None:
            raise self.attach_error
        return {"agent_id": params["agent_id"], "status": "active"}

    def detach_log(self, params, *, socket_peer_uid):
        self.detach_calls += 1
        if self.detach_error is not None:
            raise self.detach_error
        return {"agent_id": params["agent_id"], "status": "detached"}


class _FakeQueueRow:
    def __init__(self, **kw) -> None:
        self.message_id = kw.get("message_id", "msg-1")
        self.state = kw.get("state", "queued")
        self.block_reason = kw.get("block_reason")
        self.failure_reason = kw.get("failure_reason")
        self.sender_agent_id = kw.get("sender_agent_id", "agt_sender")
        self.target_agent_id = kw.get("target_agent_id", "agt_target")
        self.enqueued_at = kw.get("enqueued_at", "2026-05-22T00:00:00.000Z")
        self.last_updated_at = kw.get("last_updated_at", "2026-05-22T00:00:00.000Z")


class _FakeSendResult:
    def __init__(self, row: _FakeQueueRow) -> None:
        self.row = row
        self.waited_to_terminal = False


class _FakeQueueService:
    """Minimal FEAT-009 ``QueueService`` stand-in."""

    def __init__(
        self,
        *,
        send_row: _FakeQueueRow | None = None,
        send_error: Exception | None = None,
        resolve_error: Exception | None = None,
        action_rows: dict | None = None,
        action_error: Exception | None = None,
    ) -> None:
        self.send_row = send_row
        self.send_error = send_error
        self.resolve_error = resolve_error
        self.action_rows = action_rows or {}
        self.action_error = action_error
        self.send_calls = 0
        self.last_sender = None

    def resolve_target_agent_id(self, target_input):
        if self.resolve_error is not None:
            raise self.resolve_error
        return target_input

    def send_input(self, *, sender, target_input, body_bytes, wait=True):
        self.send_calls += 1
        self.last_sender = sender
        if self.send_error is not None:
            raise self.send_error
        return _FakeSendResult(self.send_row or _FakeQueueRow())

    def approve(self, message_id, *, operator):
        if self.action_error is not None:
            raise self.action_error
        return self.action_rows.get("approve", _FakeQueueRow(state="queued"))

    def delay(self, message_id, *, operator):
        if self.action_error is not None:
            raise self.action_error
        return self.action_rows.get(
            "delay", _FakeQueueRow(state="blocked", block_reason="operator_delayed")
        )

    def cancel(self, message_id, *, operator):
        if self.action_error is not None:
            raise self.action_error
        return self.action_rows.get("cancel", _FakeQueueRow(state="canceled"))


class _FakeRouteRow:
    def __init__(self, **kw) -> None:
        self.route_id = kw.get("route_id", "route-1")
        self.event_type = kw.get("event_type", "agent_registered")
        self.source_scope_kind = kw.get("source_scope_kind", "any")
        self.source_scope_value = kw.get("source_scope_value")
        self.target_rule = kw.get("target_rule", "explicit")
        self.target_value = kw.get("target_value", "agt_target")
        self.master_rule = kw.get("master_rule", "auto")
        self.master_value = kw.get("master_value")
        self.template = kw.get("template", "hello")
        self.enabled = kw.get("enabled", True)
        self.last_consumed_event_id = kw.get("last_consumed_event_id", 0)
        self.created_at = kw.get("created_at", "2026-05-22T00:00:00.000Z")
        self.updated_at = kw.get("updated_at", "2026-05-22T00:00:00.000Z")


class _FakeRoutesService:
    """Minimal FEAT-010 ``RoutesService`` stand-in."""

    def __init__(
        self,
        *,
        add_error: Exception | None = None,
        remove_error: Exception | None = None,
        update_error: Exception | None = None,
        known_routes: dict | None = None,
    ) -> None:
        self.add_error = add_error
        self.remove_error = remove_error
        self.update_error = update_error
        # route_id → (_FakeRouteRow); the show/enable/disable/remove
        # paths consult this map.
        self.routes = known_routes or {}
        self.removed: list[str] = []
        self.enabled_calls: list[tuple[str, bool]] = []

    def add_route(self, **kw):
        if self.add_error is not None:
            raise self.add_error
        row = _FakeRouteRow(
            event_type=kw["event_type"],
            target_rule=kw["target_rule"],
            target_value=kw["target_value"],
            template=kw["template_string"],
        )
        self.routes[row.route_id] = row
        return row

    def show_route(self, route_id):
        row = self.routes.get(route_id)
        if row is None:
            raise RouteIdNotFound(f"no route with route_id={route_id!r}")
        return row, None

    def remove_route(self, route_id, *, deleted_by_agent_id):
        if route_id not in self.routes:
            raise RouteIdNotFound(f"no route with route_id={route_id!r}")
        if self.remove_error is not None:
            raise self.remove_error
        del self.routes[route_id]
        self.removed.append(route_id)

    def enable_route(self, route_id, *, updated_by_agent_id):
        if route_id not in self.routes:
            raise RouteIdNotFound(f"no route with route_id={route_id!r}")
        if self.update_error is not None:
            raise self.update_error
        self.routes[route_id].enabled = True
        self.enabled_calls.append((route_id, True))
        return True

    def disable_route(self, route_id, *, updated_by_agent_id):
        if route_id not in self.routes:
            raise RouteIdNotFound(f"no route with route_id={route_id!r}")
        if self.update_error is not None:
            raise self.update_error
        self.routes[route_id].enabled = False
        self.enabled_calls.append((route_id, False))
        return True


@pytest.fixture
def stub_ctx(tmp_path: Path) -> DaemonContext:
    """Context with a real state DB (for agent lookups) + stub services."""
    from agenttower.state.schema import open_registry

    state_db = tmp_path / "state" / "agenttower.sqlite3"
    state_db.parent.mkdir(mode=0o700, exist_ok=True)
    conn, _ = open_registry(state_db, namespace_root=state_db.parent)
    conn.close()
    return DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=state_db,
        daemon_version="0.0.0-test",
        schema_version=10,
        events_file=tmp_path / "events.jsonl",
    )


def _seed_agent_row(ctx: DaemonContext, agent_id: str) -> None:
    """Insert a minimal agents row so send_input's sender lookup resolves."""
    conn = sqlite3.connect(str(ctx.state_path))
    try:
        conn.execute(
            "INSERT INTO agents (agent_id, container_id, tmux_socket_path, "
            "tmux_session_name, tmux_window_index, tmux_pane_index, tmux_pane_id, "
            "role, capability, label, project_path, parent_agent_id, "
            "effective_permissions, created_at, last_registered_at, "
            "last_seen_at, active) VALUES "
            "(?, 'c', '/s', 'main', 0, 0, '%0', 'slave', 'claude', 'lbl', "
            "'', NULL, '{}', '2026-05-22T00:00:00Z', '2026-05-22T00:00:00Z', "
            "'2026-05-22T00:00:00Z', 1)",
            (agent_id,),
        )
        conn.commit()
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════
# T061 / T062 — app.log.attach / app.log.detach
# ════════════════════════════════════════════════════════════════════════


def test_log_attach_happy_path(stub_ctx: DaemonContext, host_peer: int) -> None:
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_loga")
    stub_ctx.log_service = _FakeLogService()
    env = mutations.app_log_attach(
        stub_ctx,
        {"app_session_token": token, "agent_id": "agt_loga"},
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["agent_id"] == "agt_loga"
    assert stub_ctx.log_service.attach_calls == 1


def test_log_attach_blocked_maps_to_log_attach_blocked(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_logb")
    stub_ctx.log_service = _FakeLogService(
        attach_error=RegistrationError("log_path_in_use", "path owned by another")
    )
    env = mutations.app_log_attach(
        stub_ctx,
        {"app_session_token": token, "agent_id": "agt_logb"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "log_attach_blocked"
    assert env["error"]["details"]["agent_id"] == "agt_logb"


def test_log_attach_agent_not_found(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.log_service = _FakeLogService(
        attach_error=RegistrationError("agent_not_found", "no such agent")
    )
    env = mutations.app_log_attach(
        stub_ctx,
        {"app_session_token": token, "agent_id": "agt_missing"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "agent_not_found"


def test_log_attach_unwired_service(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    env = mutations.app_log_attach(
        stub_ctx,
        {"app_session_token": token, "agent_id": "agt_x"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


def test_log_detach_happy_path(stub_ctx: DaemonContext, host_peer: int) -> None:
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_logd")
    stub_ctx.log_service = _FakeLogService()
    env = mutations.app_log_detach(
        stub_ctx,
        {"app_session_token": token, "agent_id": "agt_logd"},
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["log_attached"] is False


def test_log_detach_idempotent_on_never_attached(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-029b: detaching a never-attached log → success, log_attached:false."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_neverattached")
    stub_ctx.log_service = _FakeLogService(
        detach_error=RegistrationError(
            "attachment_not_found", "agent has no active attachment"
        )
    )
    env = mutations.app_log_detach(
        stub_ctx,
        {"app_session_token": token, "agent_id": "agt_neverattached"},
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env  # NOT an error
    assert env["result"]["row"]["log_attached"] is False


def test_log_detach_unknown_agent_returns_agent_not_found(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-029b: unknown agent_id is still agent_not_found."""
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.log_service = _FakeLogService(
        detach_error=RegistrationError("agent_not_found", "no such agent")
    )
    env = mutations.app_log_detach(
        stub_ctx,
        {"app_session_token": token, "agent_id": "agt_nope"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "agent_not_found"


def test_log_detach_idempotent_emits_no_audit_row(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """Idempotent detach (never-attached) must NOT emit a detach audit row."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_noaudit")
    stub_ctx.log_service = _FakeLogService(
        detach_error=RegistrationError("attachment_not_found", "none")
    )
    mutations.app_log_detach(
        stub_ctx,
        {"app_session_token": token, "agent_id": "agt_noaudit"},
        peer_uid=host_peer,
    )
    contents = (
        stub_ctx.events_file.read_text(encoding="utf-8")
        if stub_ctx.events_file.exists()
        else ""
    )
    rows = [json.loads(line) for line in contents.splitlines() if line.strip()]
    detach_rows = [
        r for r in rows if r.get("event_type") == "log_attachment_changed"
    ]
    assert detach_rows == []


# ════════════════════════════════════════════════════════════════════════
# T063 — app.send_input
# ════════════════════════════════════════════════════════════════════════


def test_send_input_happy_path(stub_ctx: DaemonContext, host_peer: int) -> None:
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_target")
    stub_ctx.queue_service = _FakeQueueService(
        send_row=_FakeQueueRow(message_id="msg-99", state="queued")
    )
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_target",
            "payload": {"text": "hello"},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert env["result"]["message_id"] == "msg-99"
    assert env["result"]["state"] == "queued"
    assert env["result"]["deduplicated"] is False


def test_send_input_unknown_target_agent_not_found(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-031: unresolvable target_agent_id → agent_not_found."""
    from agenttower.routing.errors import TargetResolveError

    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        resolve_error=TargetResolveError("agent_not_found", "no such target")
    )
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_ghost",
            "payload": {"x": 1},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "agent_not_found"
    assert env["error"]["details"]["agent_id"] == "agt_ghost"


def test_send_input_kill_switch_off_routing_disabled(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-031 / SC-038: kill-switch-off blocked row → routing_disabled."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_ks")
    stub_ctx.queue_service = _FakeQueueService(
        send_row=_FakeQueueRow(state="blocked", block_reason="kill_switch_off")
    )
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_ks",
            "payload": {"x": 1},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "routing_disabled"
    assert env["error"]["details"] == {}


def test_send_input_permission_gate_permission_denied(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-031 / SC-038: permission-gate-refused → permission_denied."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_pg")
    stub_ctx.queue_service = _FakeQueueService(
        send_row=_FakeQueueRow(
            state="blocked", block_reason="sender_role_not_permitted"
        )
    )
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_pg",
            "payload": {"x": 1},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "permission_denied"
    assert env["error"]["details"]["reason"] == "feat009_permission_gate"


def test_send_input_routing_disabled_via_raised_error(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """A raised QueueServiceError(routing_disabled) also maps correctly."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_rd")
    stub_ctx.queue_service = _FakeQueueService(
        send_error=QueueServiceError("routing_disabled", "kill switch off")
    )
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_rd",
            "payload": {"x": 1},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "routing_disabled"


def test_send_input_idempotency_dedup(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-031a: second call with the same idempotency_key replays the first."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_idem")
    svc = _FakeQueueService(
        send_row=_FakeQueueRow(message_id="msg-idem", state="queued")
    )
    stub_ctx.queue_service = svc
    req = {
        "app_session_token": token,
        "target_agent_id": "agt_idem",
        "payload": {"x": 1},
        "idempotency_key": "key-abc",
    }
    first = mutations.app_send_input(stub_ctx, dict(req), peer_uid=host_peer)
    second = mutations.app_send_input(stub_ctx, dict(req), peer_uid=host_peer)
    assert first["ok"] is True and second["ok"] is True
    assert first["result"]["message_id"] == second["result"]["message_id"] == "msg-idem"
    assert first["result"]["deduplicated"] is False
    assert second["result"]["deduplicated"] is True
    # Only ONE queue row was created — the second call short-circuited.
    assert svc.send_calls == 1


def test_send_input_different_key_not_deduped(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-031a: a different idempotency_key produces a fresh send."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_idem2")
    svc = _FakeQueueService(
        send_row=_FakeQueueRow(message_id="msg-k", state="queued")
    )
    stub_ctx.queue_service = svc
    base = {
        "app_session_token": token,
        "target_agent_id": "agt_idem2",
        "payload": {"x": 1},
    }
    mutations.app_send_input(
        stub_ctx, {**base, "idempotency_key": "k1"}, peer_uid=host_peer
    )
    second = mutations.app_send_input(
        stub_ctx, {**base, "idempotency_key": "k2"}, peer_uid=host_peer
    )
    assert second["result"]["deduplicated"] is False
    assert svc.send_calls == 2


def test_send_input_missing_payload_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService()
    env = mutations.app_send_input(
        stub_ctx,
        {"app_session_token": token, "target_agent_id": "agt_x"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "payload"


def test_send_input_oversized_idempotency_key_rejected(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService()
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_x",
            "payload": {"x": 1},
            "idempotency_key": "k" * 300,
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "idempotency_key"


def test_send_input_unwired_service(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_x",
            "payload": {"x": 1},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


# ════════════════════════════════════════════════════════════════════════
# T064 — app.queue.approve / delay / cancel
# ════════════════════════════════════════════════════════════════════════


def test_queue_approve_happy_path(stub_ctx: DaemonContext, host_peer: int) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        action_rows={"approve": _FakeQueueRow(message_id="m1", state="queued")}
    )
    env = mutations.app_queue_approve(
        stub_ctx,
        {"app_session_token": token, "message_id": "m1"},
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["state"] == "queued"
    assert env["result"]["row"]["message_id"] == "m1"


def test_queue_delay_happy_path(stub_ctx: DaemonContext, host_peer: int) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        action_rows={
            "delay": _FakeQueueRow(
                message_id="m2", state="blocked", block_reason="operator_delayed"
            )
        }
    )
    env = mutations.app_queue_delay(
        stub_ctx,
        {"app_session_token": token, "message_id": "m2", "delay_ms": 5000},
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["state"] == "blocked"
    assert env["result"]["row"]["block_reason"] == "operator_delayed"


def test_queue_cancel_happy_path(stub_ctx: DaemonContext, host_peer: int) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        action_rows={"cancel": _FakeQueueRow(message_id="m3", state="canceled")}
    )
    env = mutations.app_queue_cancel(
        stub_ctx,
        {"app_session_token": token, "message_id": "m3"},
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["state"] == "canceled"


def test_queue_delay_missing_delay_ms_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService()
    env = mutations.app_queue_delay(
        stub_ctx,
        {"app_session_token": token, "message_id": "m4"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "delay_ms"


def test_queue_action_unknown_id_returns_queue_message_not_found(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        action_error=QueueServiceError("message_id_not_found", "unknown id")
    )
    env = mutations.app_queue_approve(
        stub_ctx,
        {"app_session_token": token, "message_id": "ghost"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "queue_message_not_found"
    assert env["error"]["details"]["message_id"] == "ghost"


@pytest.mark.parametrize(
    "upstream_code",
    [
        "terminal_state_cannot_change",
        "approval_not_applicable",
        "delay_not_applicable",
        "delivery_in_progress",
    ],
)
def test_queue_action_terminal_state_returns_stale_object(
    stub_ctx: DaemonContext, host_peer: int, upstream_code: str
) -> None:
    """FR-030a terminal-state guard: every not-applicable code → stale_object."""
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        action_error=QueueServiceError(upstream_code, "row is terminal")
    )
    env = mutations.app_queue_cancel(
        stub_ctx,
        {"app_session_token": token, "message_id": "m-terminal"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "stale_object"
    assert env["error"]["details"] == {}


def test_queue_action_emits_audit_row(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        action_rows={"approve": _FakeQueueRow(message_id="m-aud", state="queued")}
    )
    mutations.app_queue_approve(
        stub_ctx,
        {"app_session_token": token, "message_id": "m-aud"},
        peer_uid=host_peer,
    )
    contents = stub_ctx.events_file.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in contents.splitlines() if line.strip()]
    app_rows = [
        r
        for r in rows
        if r.get("origin") == "app"
        and r.get("event_type") == "queue_message_approved"
    ]
    assert len(app_rows) == 1
    assert app_rows[0]["message_id"] == "m-aud"


def test_queue_action_missing_message_id_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService()
    env = mutations.app_queue_approve(
        stub_ctx, {"app_session_token": token}, peer_uid=host_peer
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "message_id"


# ════════════════════════════════════════════════════════════════════════
# T065 — app.route.add / remove / update
# ════════════════════════════════════════════════════════════════════════


def test_route_add_happy_path(stub_ctx: DaemonContext, host_peer: int) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService()
    env = mutations.app_route_add(
        stub_ctx,
        {
            "app_session_token": token,
            "event_type": "agent_registered",
            "template": "hi {{agent_id}}",
            "source_scope": {"kind": "any", "value": None},
            "target": {"rule": "explicit", "value": "agt_target"},
            "master": {"rule": "auto", "value": None},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["event_type"] == "agent_registered"
    assert env["result"]["row"]["route_id"]


def test_route_add_invalid_event_type_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService(
        add_error=RouteEventTypeInvalid("event_type not in FR-005 set")
    )
    env = mutations.app_route_add(
        stub_ctx,
        {
            "app_session_token": token,
            "event_type": "bogus",
            "template": "x",
            "target": {"rule": "explicit", "value": "agt_t"},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"


def test_route_add_emits_audit_row(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService()
    mutations.app_route_add(
        stub_ctx,
        {
            "app_session_token": token,
            "event_type": "agent_registered",
            "template": "hi",
            "target": {"rule": "explicit", "value": "agt_t"},
        },
        peer_uid=host_peer,
    )
    contents = stub_ctx.events_file.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in contents.splitlines() if line.strip()]
    app_rows = [
        r
        for r in rows
        if r.get("origin") == "app" and r.get("event_type") == "route_created"
    ]
    assert len(app_rows) == 1


def test_route_remove_happy_path(stub_ctx: DaemonContext, host_peer: int) -> None:
    token = _mint_session(stub_ctx, host_peer)
    svc = _FakeRoutesService(known_routes={"route-x": _FakeRouteRow(route_id="route-x")})
    stub_ctx.routes_service = svc
    env = mutations.app_route_remove(
        stub_ctx,
        {"app_session_token": token, "route_id": "route-x"},
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["route_id"] == "route-x"
    assert "route-x" in svc.removed


def test_route_remove_unknown_id_route_not_found(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService()
    env = mutations.app_route_remove(
        stub_ctx,
        {"app_session_token": token, "route_id": "no-such-route"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "route_not_found"
    assert env["error"]["details"]["route_id"] == "no-such-route"


def test_route_update_enable_happy_path(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    svc = _FakeRoutesService(
        known_routes={"route-u": _FakeRouteRow(route_id="route-u", enabled=False)}
    )
    stub_ctx.routes_service = svc
    env = mutations.app_route_update(
        stub_ctx,
        {"app_session_token": token, "route_id": "route-u", "enabled": True},
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert env["result"]["row"]["enabled"] is True
    assert ("route-u", True) in svc.enabled_calls


def test_route_update_extra_field_rejected(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """app.route.update accepts only {route_id, enabled} — extras rejected."""
    token = _mint_session(stub_ctx, host_peer)
    svc = _FakeRoutesService(
        known_routes={"route-e": _FakeRouteRow(route_id="route-e")}
    )
    stub_ctx.routes_service = svc
    env = mutations.app_route_update(
        stub_ctx,
        {
            "app_session_token": token,
            "route_id": "route-e",
            "enabled": True,
            "template": "should not be here",
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "template"
    # The route must NOT have been mutated.
    assert svc.enabled_calls == []


def test_route_update_unknown_id_route_not_found(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService()
    env = mutations.app_route_update(
        stub_ctx,
        {"app_session_token": token, "route_id": "ghost-route", "enabled": False},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "route_not_found"


def test_route_update_never_returns_stale_object(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-030a: two route.update calls both succeed, no stale_object."""
    token = _mint_session(stub_ctx, host_peer)
    svc = _FakeRoutesService(
        known_routes={"route-lww": _FakeRouteRow(route_id="route-lww")}
    )
    stub_ctx.routes_service = svc
    first = mutations.app_route_update(
        stub_ctx,
        {"app_session_token": token, "route_id": "route-lww", "enabled": False},
        peer_uid=host_peer,
    )
    second = mutations.app_route_update(
        stub_ctx,
        {"app_session_token": token, "route_id": "route-lww", "enabled": True},
        peer_uid=host_peer,
    )
    assert first["ok"] is True and second["ok"] is True
    assert second["result"]["row"]["enabled"] is True


def test_route_update_missing_enabled_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService()
    env = mutations.app_route_update(
        stub_ctx,
        {"app_session_token": token, "route_id": "r"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "enabled"


def test_route_add_unwired_service(stub_ctx: DaemonContext, host_peer: int) -> None:
    token = _mint_session(stub_ctx, host_peer)
    env = mutations.app_route_add(
        stub_ctx,
        {
            "app_session_token": token,
            "event_type": "agent_registered",
            "template": "x",
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


# ─── Session gate coverage (one per cluster) ─────────────────────────────


@pytest.mark.parametrize(
    "handler,params",
    [
        (mutations.app_log_attach, {"agent_id": "a"}),
        (mutations.app_log_detach, {"agent_id": "a"}),
        (mutations.app_send_input, {"target_agent_id": "a", "payload": {}}),
        (mutations.app_queue_approve, {"message_id": "m"}),
        (mutations.app_route_add, {"event_type": "x", "template": "y"}),
    ],
)
def test_handlers_enforce_session_gate(
    stub_ctx: DaemonContext, host_peer: int, handler, params: dict
) -> None:
    env = handler(stub_ctx, params, peer_uid=host_peer)
    assert env["ok"] is False
    assert env["error"]["code"] == "app_session_required"


# ════════════════════════════════════════════════════════════════════════
# Service-error-mapping coverage (review finding H1) + M1/M2/M4 regression
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "upstream_code,expected",
    [
        ("agent_inactive", "agent_not_found"),
        ("container_inactive", "container_inactive"),
        ("target_container_inactive", "container_inactive"),
        ("tmux_unavailable", "log_attach_blocked"),
        ("pipe_pane_failed", "log_attach_blocked"),
        ("value_out_of_set", "validation_failed"),
        ("field_too_long", "validation_failed"),
        ("project_path_invalid", "validation_failed"),
        ("master_confirm_required", "validation_failed"),
    ],
)
def test_log_attach_maps_registration_error_codes(
    stub_ctx: DaemonContext, host_peer: int, upstream_code: str, expected: str
) -> None:
    """H1: every _map_registration_error_generic arm maps to its FEAT-011 code."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_map")
    stub_ctx.log_service = _FakeLogService(
        attach_error=RegistrationError(upstream_code, f"upstream: {upstream_code}")
    )
    env = mutations.app_log_attach(
        stub_ctx,
        {"app_session_token": token, "agent_id": "agt_map"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == expected


def test_log_attach_unmapped_registration_code_internal_error(
    stub_ctx: DaemonContext, host_peer: int, capsys: pytest.CaptureFixture[str]
) -> None:
    """H1 + M1: an unmapped RegistrationError code -> internal_error; the
    upstream code is logged to stderr, not leaked into the wire message."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_unmap")
    stub_ctx.log_service = _FakeLogService(
        attach_error=RegistrationError("brand_new_upstream_code", "weird")
    )
    env = mutations.app_log_attach(
        stub_ctx,
        {"app_session_token": token, "agent_id": "agt_unmap"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"
    assert "brand_new_upstream_code" not in env["error"]["message"]
    assert "brand_new_upstream_code" in capsys.readouterr().err


@pytest.mark.parametrize(
    "upstream_code,expected,detail_key",
    [
        ("sender_role_not_permitted", "permission_denied", "reason"),
        ("target_not_active", "permission_denied", "reason"),
        ("agent_not_found", "agent_not_found", "agent_id"),
        ("target_label_ambiguous", "agent_not_found", "agent_id"),
    ],
)
def test_send_input_maps_raised_queue_service_errors(
    stub_ctx: DaemonContext,
    host_peer: int,
    upstream_code: str,
    expected: str,
    detail_key: str,
) -> None:
    """H1: send_input's raised-QueueServiceError arms map to FEAT-011 codes."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_qse")
    stub_ctx.queue_service = _FakeQueueService(
        send_error=QueueServiceError(upstream_code, f"upstream {upstream_code}")
    )
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_qse",
            "payload": {"x": 1},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == expected
    assert detail_key in env["error"]["details"]


def test_send_input_unmapped_queue_service_error_internal_error(
    stub_ctx: DaemonContext, host_peer: int, capsys: pytest.CaptureFixture[str]
) -> None:
    """H1 + M1: an unmapped QueueServiceError from send_input -> internal_error;
    the upstream code/message is logged to stderr, not leaked to the wire."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_uqse")
    stub_ctx.queue_service = _FakeQueueService(
        send_error=QueueServiceError("weird_queue_code", "internal queue glitch")
    )
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_uqse",
            "payload": {"x": 1},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"
    assert "internal queue glitch" not in env["error"]["message"]
    assert "weird_queue_code" in capsys.readouterr().err


def test_send_input_generic_exception_from_send_internal_error(
    stub_ctx: DaemonContext, host_peer: int, capsys: pytest.CaptureFixture[str]
) -> None:
    """H1 + M1: a non-QueueServiceError exception from send_input ->
    internal_error, with the raw exception string redacted from the wire."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_boom")
    stub_ctx.queue_service = _FakeQueueService(
        send_error=RuntimeError("queue crash at /home/secret/state.db")
    )
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_boom",
            "payload": {"x": 1},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"
    assert "/home/secret/state.db" not in env["error"]["message"]
    assert "RuntimeError" in capsys.readouterr().err


def test_send_input_resolve_raises_queue_service_error_internal_error(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """H1: resolve_target_agent_id raising a QueueServiceError -> internal_error."""
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        resolve_error=QueueServiceError("resolver_glitch", "resolver internal")
    )
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_x",
            "payload": {"x": 1},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


def test_send_input_resolve_raises_generic_exception_internal_error(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """H1: resolve_target_agent_id raising a generic exception -> internal_error."""
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        resolve_error=RuntimeError("resolver crash")
    )
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_x",
            "payload": {"x": 1},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


def test_send_input_oversized_payload_rejected(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """M2: a payload serializing above the 16 KiB cap -> validation_failed(payload)."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_big")
    stub_ctx.queue_service = _FakeQueueService()
    big_payload = {"blob": "x" * 20000}  # > 16 KiB once serialized
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_big",
            "payload": big_payload,
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "payload"
    assert env["error"]["details"]["reason"] == "too large"


def test_send_input_non_serializable_payload_rejected(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """M1: a payload carrying a non-JSON-serializable value ->
    validation_failed(payload); no exception detail leaked into the message."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_nonser")
    stub_ctx.queue_service = _FakeQueueService()
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_nonser",
            "payload": {"bad": object()},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "payload"
    assert env["error"]["message"] == "payload is not JSON-serializable"


def test_send_input_uses_host_operator_sender(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """M4: send_input attributes the FEAT-009 sender to the synthetic host
    operator (role 'master'), NOT to the target agent's own row — and works
    even though no target agents row is seeded."""
    token = _mint_session(stub_ctx, host_peer)
    svc = _FakeQueueService(
        send_row=_FakeQueueRow(message_id="m-ho", state="queued")
    )
    stub_ctx.queue_service = svc
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_target",
            "payload": {"x": 1},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is True, env
    assert svc.last_sender is not None
    assert svc.last_sender.agent_id == "host-operator"
    assert svc.last_sender.role == "master"
    assert svc.last_sender.agent_id != "agt_target"


def test_queue_action_routing_disabled_maps_correctly(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """H1: a queue action blocked by the kill switch -> routing_disabled."""
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        action_error=QueueServiceError("routing_disabled", "kill switch off")
    )
    env = mutations.app_queue_approve(
        stub_ctx,
        {"app_session_token": token, "message_id": "m-rd"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "routing_disabled"


def test_queue_action_unmapped_code_internal_error(
    stub_ctx: DaemonContext, host_peer: int, capsys: pytest.CaptureFixture[str]
) -> None:
    """H1 + M1: an unmapped QueueServiceError from a queue action ->
    internal_error, with the upstream code logged to stderr only."""
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        action_error=QueueServiceError("weird_action_code", "glitch")
    )
    env = mutations.app_queue_cancel(
        stub_ctx,
        {"app_session_token": token, "message_id": "m-uc"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"
    assert "weird_action_code" in capsys.readouterr().err


def test_queue_action_generic_exception_internal_error(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """H1 + M1: a non-QueueServiceError exception from a queue action ->
    internal_error."""
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.queue_service = _FakeQueueService(
        action_error=RuntimeError("queue action crash")
    )
    env = mutations.app_queue_delay(
        stub_ctx,
        {"app_session_token": token, "message_id": "m-ge", "delay_ms": 1000},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


def test_route_remove_route_error_maps_to_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """H1: a non-RouteIdNotFound RouteError from remove_route -> validation_failed."""
    from agenttower.routing.route_errors import RouteError

    token = _mint_session(stub_ctx, host_peer)
    svc = _FakeRoutesService(
        known_routes={"route-re": _FakeRouteRow(route_id="route-re")},
        remove_error=RouteError("route is referenced elsewhere"),
    )
    stub_ctx.routes_service = svc
    env = mutations.app_route_remove(
        stub_ctx,
        {"app_session_token": token, "route_id": "route-re"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"


def test_route_update_route_error_maps_to_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """H1: a non-RouteIdNotFound RouteError from enable/disable -> validation_failed."""
    from agenttower.routing.route_errors import RouteError

    token = _mint_session(stub_ctx, host_peer)
    svc = _FakeRoutesService(
        known_routes={"route-ue": _FakeRouteRow(route_id="route-ue")},
        update_error=RouteError("route in an un-toggleable state"),
    )
    stub_ctx.routes_service = svc
    env = mutations.app_route_update(
        stub_ctx,
        {"app_session_token": token, "route_id": "route-ue", "enabled": True},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"


def test_route_add_generic_exception_internal_error(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """H1 + M1: a non-RouteError exception from add_route -> internal_error."""
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService(
        add_error=RuntimeError("routes subsystem crash")
    )
    env = mutations.app_route_add(
        stub_ctx,
        {
            "app_session_token": token,
            "event_type": "agent_registered",
            "template": "x",
            "target": {"rule": "explicit", "value": "agt_t"},
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


def test_agent_update_generic_exception_internal_error(
    agent_ctx: DaemonContext, host_peer: int, capsys: pytest.CaptureFixture[str]
) -> None:
    """H1 + M1: a non-RegistrationError exception from a set_* call ->
    internal_error, with the raw exception logged to stderr only."""
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("set_role crash at /home/secret/state.db")

    agent_ctx.agent_service.set_role = _boom
    env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "role": "test-runner"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"
    assert "/home/secret/state.db" not in env["error"]["message"]
    assert "RuntimeError" in capsys.readouterr().err


# ── Validation-branch + idempotency-store coverage (review finding H1) ───


def test_agent_update_role_wrong_type_validation_failed(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "role": 123},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "role"


def test_agent_update_capability_wrong_type_validation_failed(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "capability": 123},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "capability"


def test_agent_update_project_path_wrong_type_validation_failed(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "project_path": 123},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "project_path"


def test_agent_update_label_wrong_type_validation_failed(
    agent_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(agent_ctx, host_peer)
    agent_id = _register_agent(agent_ctx, token, host_peer)
    env = mutations.app_agent_update(
        agent_ctx,
        {"app_session_token": token, "agent_id": agent_id, "label": 123},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "label"


def test_log_attach_missing_agent_id_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    env = mutations.app_log_attach(
        stub_ctx, {"app_session_token": token}, peer_uid=host_peer
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "agent_id"


def test_log_detach_missing_agent_id_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    env = mutations.app_log_detach(
        stub_ctx, {"app_session_token": token}, peer_uid=host_peer
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "agent_id"


def test_send_input_missing_target_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    env = mutations.app_send_input(
        stub_ctx,
        {"app_session_token": token, "payload": {"x": 1}},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "target_agent_id"


def test_send_input_idempotency_key_wrong_type_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    env = mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_x",
            "payload": {"x": 1},
            "idempotency_key": 123,
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "idempotency_key"


def test_route_add_missing_event_type_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService()
    env = mutations.app_route_add(
        stub_ctx,
        {"app_session_token": token, "template": "x"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "event_type"


def test_route_add_non_string_template_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService()
    env = mutations.app_route_add(
        stub_ctx,
        {"app_session_token": token, "event_type": "agent_registered",
         "template": 123},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "template"


@pytest.mark.parametrize("field", ["source_scope", "target", "master"])
def test_route_add_non_dict_scope_fields_validation_failed(
    stub_ctx: DaemonContext, host_peer: int, field: str
) -> None:
    """H1: source_scope / target / master must each be objects."""
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService()
    params = {
        "app_session_token": token,
        "event_type": "agent_registered",
        "template": "x",
        field: "not-a-dict",
    }
    env = mutations.app_route_add(stub_ctx, params, peer_uid=host_peer)
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == field


def test_route_remove_missing_route_id_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService()
    env = mutations.app_route_remove(
        stub_ctx, {"app_session_token": token}, peer_uid=host_peer
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "route_id"


def test_route_update_missing_route_id_validation_failed(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    token = _mint_session(stub_ctx, host_peer)
    stub_ctx.routes_service = _FakeRoutesService()
    env = mutations.app_route_update(
        stub_ctx,
        {"app_session_token": token, "enabled": True},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "route_id"


def test_session_invalidate_drops_idempotency_store(
    stub_ctx: DaemonContext, host_peer: int
) -> None:
    """LOW finding: SessionRegistry.invalidate() drops the session's
    per-session idempotency store so the process-wide registry does not
    leak one stale store per invalidated session."""
    token = _mint_session(stub_ctx, host_peer)
    _seed_agent_row(stub_ctx, "agt_inv")
    stub_ctx.queue_service = _FakeQueueService(
        send_row=_FakeQueueRow(message_id="m-inv", state="queued")
    )
    session = sessions.get_registry().lookup(token)
    # A send carrying an idempotency_key creates the per-session store.
    mutations.app_send_input(
        stub_ctx,
        {
            "app_session_token": token,
            "target_agent_id": "agt_inv",
            "payload": {"x": 1},
            "idempotency_key": "k-inv",
        },
        peer_uid=host_peer,
    )
    assert session.app_session_id in mutations._idempotency_stores
    # Invalidating the session must drop its store.
    sessions.get_registry().invalidate(token)
    assert session.app_session_id not in mutations._idempotency_stores
