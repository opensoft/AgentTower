"""FEAT-011 smoke / unit tests for the foundational app_contract slice.

Covers the bootstrap handlers (``app.preflight``, ``app.hello``) and the
closed-set / envelope invariants that every downstream handler will rely
on. Pure in-process tests — no socket, no subprocess (SC-001).

Larger contract and integration tests (per ``plan.md`` §Project Structure)
are deferred to follow-up work; this file proves the foundational slice
is callable and matches the contract envelopes.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttower.app_contract import (
    APP_CONTRACT_VERSION,
    SUPPORTED_MINOR_RANGE,
)
from agenttower.app_contract import errors as app_errors
from agenttower.app_contract import envelope, hello as hello_mod
from agenttower.app_contract import preflight as preflight_mod
from agenttower.app_contract import sessions, versioning
from agenttower.socket_api.methods import (
    DISPATCH,
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def daemon_ctx(tmp_path: Path) -> DaemonContext:
    """Minimal DaemonContext for handlers that only need version + schema."""
    return DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=tmp_path / "state.db",
        daemon_version="0.0.0-test",
        schema_version=10,
    )


@pytest.fixture(autouse=True)
def fresh_session_registry() -> None:
    """Ensure each test sees a clean SessionRegistry."""
    sessions.set_registry(sessions.SessionRegistry())


@pytest.fixture
def host_peer(monkeypatch: pytest.MonkeyPatch):
    """Set thread-local request peer context to the daemon's own pid (host).

    Uses the documented FEAT-002 test seam ``AGENTTOWER_TEST_FORCE_HOST_PEER=1``
    to bypass the ``/proc/<pid>/cgroup`` + ``/.dockerenv`` container probe —
    in WSL2 / Docker-in-Docker / sandboxed CI runners those markers false-
    positive even though the test process and daemon share the same uid +
    namespace.
    """
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    uid = os.geteuid()
    _set_request_peer_context(peer_pid=os.getpid())
    try:
        yield uid
    finally:
        _clear_request_peer_context()


# ─── Dispatcher merge (FR-001, FR-002) ───────────────────────────────────


def test_app_methods_registered_in_dispatch() -> None:
    """FR-001 + plan T002: `app.*` methods reach the FEAT-002 dispatcher."""
    assert "app.preflight" in DISPATCH
    assert "app.hello" in DISPATCH


def test_legacy_methods_still_in_dispatch() -> None:
    """FR-002: legacy CLI methods continue to work unchanged."""
    # A representative sample across FEAT-002..FEAT-010.
    for name in (
        "ping",
        "status",
        "list_agents",
        "register_agent",
        "queue.list",
        "routes.list",
    ):
        assert name in DISPATCH, f"legacy method {name!r} was removed"


# ─── Closed-set / regex invariants (FR-034, FR-034a) ─────────────────────


def test_error_codes_match_regex() -> None:
    """FR-034: every closed-set code matches ^[a-z][a-z0-9_]*$."""
    pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    for code in app_errors.ERROR_CODES:
        assert pattern.match(code), f"code {code!r} violates FR-034 regex"


def test_error_codes_count_is_26() -> None:
    """FR-034 v1.0: exactly 26 closed-set codes."""
    assert len(app_errors.ERROR_CODES) == 26


def test_details_registry_codes_are_in_closed_set() -> None:
    """FR-034a: per-code registry only contains codes from the closed set."""
    for code in app_errors.DETAILS_REQUIRED_KEYS:
        assert code in app_errors.ERROR_CODES, (
            f"registry code {code!r} not in FR-034 closed set"
        )


def test_validate_details_rejects_unknown_code() -> None:
    """FR-034a: handler that emits a non-registry code → ContractViolation."""
    with pytest.raises(app_errors.ContractViolation):
        app_errors.validate_details("invented_code", {})


def test_validate_details_rejects_missing_required_key() -> None:
    """FR-034a: validation_failed without ``field`` is malformed."""
    with pytest.raises(app_errors.ContractViolation):
        app_errors.validate_details(app_errors.VALIDATION_FAILED, {"field": "x"})
        # Missing ``reason`` key — must raise.


def test_validate_details_rejects_non_object_details() -> None:
    """FR-033: ``error.details`` is always an object (never null/list/scalar)."""
    with pytest.raises(app_errors.ContractViolation):
        app_errors.validate_details(app_errors.INTERNAL_ERROR, None)  # type: ignore[arg-type]
    with pytest.raises(app_errors.ContractViolation):
        app_errors.validate_details(app_errors.INTERNAL_ERROR, [])  # type: ignore[arg-type]


# ─── Envelope shape (FR-033) ─────────────────────────────────────────────


def test_success_envelope_shape() -> None:
    """FR-033: success envelope is {ok: true, app_contract_version, result}."""
    env = envelope.success({"x": 1})
    assert env == {
        "ok": True,
        "app_contract_version": APP_CONTRACT_VERSION,
        "result": {"x": 1},
    }


def test_success_envelope_defaults_to_empty_result() -> None:
    """FR-033: result is always present, even when handler has no payload."""
    env = envelope.success()
    assert env["ok"] is True
    assert env["result"] == {}


def test_failure_envelope_shape() -> None:
    """FR-033 + FR-034a: failure envelope has version + code + message + details."""
    env = envelope.failure(
        app_errors.AGENT_NOT_FOUND,
        "agent does not exist",
        details={"agent_id": "abc-123"},
    )
    assert env == {
        "ok": False,
        "app_contract_version": APP_CONTRACT_VERSION,
        "error": {
            "code": app_errors.AGENT_NOT_FOUND,
            "message": "agent does not exist",
            "details": {"agent_id": "abc-123"},
        },
    }


def test_failure_envelope_unknown_code_raises() -> None:
    """FR-034a: emitting an unknown code surfaces ContractViolation to the daemon."""
    with pytest.raises(app_errors.ContractViolation):
        envelope.failure("not_a_real_code", "msg", {})


# ─── app.preflight (FR-011, FR-042) ──────────────────────────────────────


def test_preflight_host_peer_returns_ok(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-011: host peer → success envelope with code == 'ok'."""
    env = preflight_mod.app_preflight(daemon_ctx, {}, peer_uid=host_peer)
    assert env["ok"] is True
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    assert env["result"]["code"] == "ok"
    assert env["result"]["socket_reachable"] is True
    assert env["result"]["daemon_reachable"] is True


def test_preflight_no_peer_credentials_returns_host_only(
    daemon_ctx: DaemonContext,
) -> None:
    """FR-042: no peer credentials → host_only (matches routing-toggle rationale)."""
    # No _set_request_peer_context call — request peer is unknown.
    env = preflight_mod.app_preflight(daemon_ctx, {}, peer_uid=-1)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY
    assert env["error"]["details"] == {}


# ─── app.hello (FR-010, FR-036, FR-039, FR-042) ──────────────────────────


def test_hello_happy_path(daemon_ctx: DaemonContext, host_peer: int) -> None:
    """FR-010: app.hello returns the full required field set + capability_flags={}."""
    env = hello_mod.app_hello(
        daemon_ctx,
        {
            "client_id": "smoke-test",
            "client_version": "0.0.0",
            "client_app_contract_major": 1,
        },
        peer_uid=host_peer,
    )
    assert env["ok"] is True
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    r = env["result"]
    # FR-010 required fields
    assert isinstance(r["app_session_token"], str)
    assert len(r["app_session_token"]) == 36  # uuid v4 hex with hyphens
    assert isinstance(r["app_session_id"], int)
    assert r["app_session_id"] >= 1
    assert r["daemon_version"] == "0.0.0-test"
    assert r["schema_version"] == 10
    assert r["app_contract_version"] == APP_CONTRACT_VERSION
    assert r["supported_minor_range"] == SUPPORTED_MINOR_RANGE
    assert r["host_user_id"] == str(host_peer)
    # FR-039: capability_flags is always present and always {} at v1.0
    assert r["capability_flags"] == {}
    assert r["state"] == "ok"


def test_hello_default_major_is_1(daemon_ctx: DaemonContext, host_peer: int) -> None:
    """FR-036: missing client_app_contract_major defaults to 1 (matches daemon)."""
    env = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    assert env["ok"] is True


def test_hello_major_mismatch_emits_app_contract_major_unsupported(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-036 + SC-005: client_app_contract_major != 1 → mismatch envelope, no session."""
    env = hello_mod.app_hello(
        daemon_ctx,
        {"client_app_contract_major": 2},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_CONTRACT_MAJOR_UNSUPPORTED
    # FR-034a: details must include both versions
    details = env["error"]["details"]
    assert details["daemon_app_contract_version"] == APP_CONTRACT_VERSION
    assert details["client_app_contract_major"] == 2
    # FR-036: no session issued — registry stays empty.
    # (sessions are issued by .create(); a successful path would have created
    # one, but here we never reach that branch.)


def test_hello_validation_failed_on_non_int_major(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-029a / FR-034a: validation errors carry field + reason."""
    env = hello_mod.app_hello(
        daemon_ctx,
        {"client_app_contract_major": "1"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.VALIDATION_FAILED
    assert env["error"]["details"]["field"] == "client_app_contract_major"
    assert "reason" in env["error"]["details"]


def test_hello_validation_failed_on_oversized_client_id(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-010: client_id length cap is enforced with structured field/reason."""
    env = hello_mod.app_hello(
        daemon_ctx,
        {"client_id": "x" * 129},  # 129 chars > 128 cap
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.VALIDATION_FAILED
    assert env["error"]["details"]["field"] == "client_id"


def test_hello_container_peer_returns_host_only(
    daemon_ctx: DaemonContext,
) -> None:
    """FR-042: no host-process credentials → host_only on app.hello too."""
    # No peer context set → is_host_peer() returns False.
    env = hello_mod.app_hello(daemon_ctx, {}, peer_uid=-1)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY
    assert env["error"]["details"] == {}


def test_hello_session_token_unique_per_call(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """Sessions are minted fresh each call; tokens are unique."""
    e1 = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    e2 = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    assert e1["ok"] and e2["ok"]
    assert e1["result"]["app_session_token"] != e2["result"]["app_session_token"]
    assert e1["result"]["app_session_id"] < e2["result"]["app_session_id"]


# ─── Versioning helpers ──────────────────────────────────────────────────


def test_parse_major_minor() -> None:
    assert versioning.parse_major_minor("1.0") == (1, 0)
    assert versioning.parse_major_minor("2.5") == (2, 5)
    with pytest.raises(ValueError):
        versioning.parse_major_minor("1")
    with pytest.raises(ValueError):
        versioning.parse_major_minor("1.0.0")
    with pytest.raises(ValueError):
        versioning.parse_major_minor("x.y")


def test_is_major_compatible() -> None:
    assert versioning.is_major_compatible(1) is True
    assert versioning.is_major_compatible(2) is False
    assert versioning.is_major_compatible(0) is False
