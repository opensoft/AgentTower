"""FEAT-011 T053 — Story 3 socket-level integration test.

Exercises the operator-action surface (`app.route.*`, `app.queue.*`,
`app.log.*`, `app.agent.update`, `app.send_input`) against a real
daemon over a real Unix socket.

The **route lifecycle** is the one operator flow that runs cleanly
end-to-end without a live bench container — routes are catalog rows,
not container-bound — so it is exercised fully:
``route.add → route.list → route.update(disable) → route.detail →
route.remove → route.list``.

The container-dependent mutations (`send_input`, `queue.*`, `log.*`,
`agent.update`) cannot reach a happy path without a real bench
container + registered agents; here they are smoke-checked at the
wire level — every call MUST return a structurally-valid FEAT-011
envelope (`{ok, app_contract_version, ...}`) with a closed-set
`error.code`, never an OS error or a malformed response. The
happy-path behavior of those mutations is covered by the US3 unit
suites (`test_app_us3_mutations.py`).
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from agenttower.app_contract import versioning

from ._daemon_helpers import (
    ensure_daemon,
    isolated_env,
    resolved_paths,
    run_config_init,
    stop_daemon_if_alive,
)

# Closed FEAT-011 error-code set (errors.md) — every failure envelope's
# code must be a member. Kept inline so the test has no app_contract
# import dependency.
_CLOSED_ERROR_CODES = frozenset({
    "app_session_required", "app_session_expired", "app_contract_major_unsupported",
    "unknown_method", "malformed_request", "validation_failed", "not_found",
    "stale_object", "pane_already_registered", "pane_not_found", "agent_not_found",
    "route_not_found", "queue_message_not_found", "scan_timeout", "scan_not_found",
    "daemon_unavailable", "socket_missing", "socket_permission_denied",
    "docker_unavailable", "tmux_unavailable", "container_inactive",
    "log_attach_blocked", "routing_disabled", "permission_denied", "host_only",
    "payload_too_large", "internal_error",
})


# ─── Wire helpers ────────────────────────────────────────────────────────


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


def _one_shot(socket_path: Path, method: str, params: dict | None = None) -> dict:
    sock = _open_socket(socket_path)
    try:
        return _call(sock, method, params)
    finally:
        sock.close()


def _assert_well_formed(envelope: dict) -> None:
    """Every app.* response MUST be a structurally-valid FEAT-011 envelope."""
    assert isinstance(envelope, dict)
    assert envelope.get("app_contract_version") == versioning.APP_CONTRACT_VERSION, envelope
    assert "ok" in envelope
    if envelope["ok"]:
        assert "result" in envelope
    else:
        err = envelope["error"]
        assert err["code"] in _CLOSED_ERROR_CODES, err
        assert isinstance(err["details"], dict)


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def env(tmp_path: Path):
    env = isolated_env(tmp_path)
    yield env
    stop_daemon_if_alive(env)


@pytest.fixture
def socket_path(env: dict[str, str]) -> Path:
    run_config_init(env)
    proc = ensure_daemon(env, json_mode=True)
    assert proc.returncode == 0, proc.stderr
    return resolved_paths(Path(env["HOME"]))["socket"]


@pytest.fixture
def token(socket_path: Path) -> str:
    hello = _one_shot(socket_path, "app.hello", {"client_id": "story3-test"})
    assert hello["ok"] is True, hello
    return hello["result"]["app_session_token"]


def _add_route(socket_path: Path, token: str, event_type: str = "completed") -> dict:
    """Create a minimal valid FEAT-010 route over the socket."""
    return _one_shot(
        socket_path,
        "app.route.add",
        {
            "app_session_token": token,
            "event_type": event_type,
            "source_scope": {"kind": "any"},
            "target": {"rule": "source"},
            "master": {"rule": "auto"},
            "template": "done: {event_excerpt}",
        },
    )


# ─── Route lifecycle — full end-to-end operator flow ─────────────────────


def test_story3_route_lifecycle_add_list_disable_detail_remove(
    socket_path: Path, token: str
) -> None:
    """Story 3 core: an operator drives a route through its full
    lifecycle entirely via structured app.* calls."""
    # 1. add
    added = _add_route(socket_path, token)
    assert added["ok"] is True, added
    route_id = added["result"]["row"]["route_id"]
    assert route_id
    assert added["result"]["row"]["enabled"] is True

    # 2. list — the new route appears, enabled
    listed = _one_shot(socket_path, "app.route.list", {"app_session_token": token})
    assert listed["ok"] is True, listed
    rows = listed["result"]["rows"]
    match = [r for r in rows if r["route_id"] == route_id]
    assert len(match) == 1
    assert match[0]["enabled"] is True

    # 3. update — disable it
    disabled = _one_shot(
        socket_path,
        "app.route.update",
        {"app_session_token": token, "route_id": route_id, "enabled": False},
    )
    assert disabled["ok"] is True, disabled
    assert disabled["result"]["row"]["enabled"] is False

    # 4. detail — confirms the disabled state
    detail = _one_shot(
        socket_path,
        "app.route.detail",
        {"app_session_token": token, "route_id": route_id},
    )
    assert detail["ok"] is True, detail
    assert detail["result"]["row"]["enabled"] is False

    # 5. remove
    removed = _one_shot(
        socket_path,
        "app.route.remove",
        {"app_session_token": token, "route_id": route_id},
    )
    assert removed["ok"] is True, removed

    # 6. list — the route is gone
    after = _one_shot(socket_path, "app.route.list", {"app_session_token": token})
    assert after["ok"] is True
    assert [r for r in after["result"]["rows"] if r["route_id"] == route_id] == []


def test_story3_route_update_rejects_extra_fields(
    socket_path: Path, token: str
) -> None:
    """FR-029: app.route.update accepts only {route_id, enabled} — a
    non-enable/disable field is rejected with validation_failed."""
    added = _add_route(socket_path, token)
    route_id = added["result"]["row"]["route_id"]
    env = _one_shot(
        socket_path,
        "app.route.update",
        {
            "app_session_token": token,
            "route_id": route_id,
            "enabled": False,
            "template": "mutated",  # not allowed
        },
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "validation_failed"


def test_story3_route_remove_unknown_returns_route_not_found(
    socket_path: Path, token: str
) -> None:
    env = _one_shot(
        socket_path,
        "app.route.remove",
        {"app_session_token": token, "route_id": "no-such-route"},
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "route_not_found"


# ─── Operator mutations — wire-level envelope smoke checks ───────────────


def test_story3_operator_mutations_return_well_formed_envelopes(
    socket_path: Path, token: str
) -> None:
    """The container-dependent operator mutations cannot reach a happy
    path on a fresh daemon (no bench container, no agents), but every
    call MUST still return a structurally-valid FEAT-011 envelope with
    a closed-set error code — never an OS error or malformed response.
    """
    calls = [
        ("app.agent.update", {"app_session_token": token, "agent_id": "nope",
                               "label": "x"}),
        ("app.log.attach", {"app_session_token": token, "agent_id": "nope"}),
        ("app.log.detach", {"app_session_token": token, "agent_id": "nope"}),
        ("app.send_input", {"app_session_token": token,
                            "target_agent_id": "nope", "payload": {"text": "hi"}}),
        ("app.queue.approve", {"app_session_token": token, "message_id": "nope"}),
        ("app.queue.delay", {"app_session_token": token, "message_id": "nope",
                             "delay_ms": 1000}),
        ("app.queue.cancel", {"app_session_token": token, "message_id": "nope"}),
    ]
    for method, params in calls:
        envelope = _one_shot(socket_path, method, params)
        _assert_well_formed(envelope)


def test_story3_operator_actions_reject_missing_session(socket_path: Path) -> None:
    """FR-007: every operator mutation requires a session token."""
    for method in (
        "app.route.add", "app.route.remove", "app.route.update",
        "app.agent.update", "app.log.attach", "app.log.detach",
        "app.send_input", "app.queue.approve", "app.queue.delay",
        "app.queue.cancel",
    ):
        envelope = _one_shot(socket_path, method, {})
        assert envelope["ok"] is False, (method, envelope)
        assert envelope["error"]["code"] == "app_session_required", (method, envelope)


def test_story3_route_list_and_detail_session_gated(socket_path: Path) -> None:
    """The US3 read surfaces are session-gated too."""
    for method in (
        "app.container.list", "app.log_attachment.list", "app.event.list",
        "app.queue.list", "app.route.list",
    ):
        envelope = _one_shot(socket_path, method, {})
        assert envelope["ok"] is False, (method, envelope)
        assert envelope["error"]["code"] == "app_session_required", (method, envelope)
