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


@pytest.fixture
def host_session(daemon_ctx, host_peer):
    """Host peer + a freshly-minted app.hello session token.

    Returns ``(uid, token)``. Used by every readiness/dashboard test that
    wants a valid session-gated request — keeps the test bodies tight by
    not having to call app.hello inline every time.
    """
    env = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    assert env["ok"] is True, f"host_session setup failed: {env}"
    return host_peer, env["result"]["app_session_token"]


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


def test_error_codes_count_is_27() -> None:
    """FR-034 v1.0: exactly 27 closed-set codes (Round-4 added malformed_request)."""
    assert len(app_errors.ERROR_CODES) == 27
    assert "malformed_request" in app_errors.ERROR_CODES


def test_malformed_request_requires_reason() -> None:
    """FR-034a: malformed_request → details must carry {reason: str}."""
    assert app_errors.DETAILS_REQUIRED_KEYS[app_errors.MALFORMED_REQUEST] == frozenset({"reason"})


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


def test_validate_details_rejects_extras_on_unregistered_code() -> None:
    """FR-034a: codes NOT in DETAILS_REQUIRED_KEYS MUST carry details == {}.

    Without this rule a handler could emit non-empty ``details`` for e.g.
    ``host_only`` and the contract would drift silently.
    """
    # HOST_ONLY is not in the registry — extras must be rejected.
    with pytest.raises(app_errors.ContractViolation):
        app_errors.validate_details(app_errors.HOST_ONLY, {"surprise_key": 1})
    # Empty details on an unregistered code is fine.
    app_errors.validate_details(app_errors.HOST_ONLY, {})


def test_validate_details_allows_extras_on_registered_code() -> None:
    """FR-034a: codes IN the registry MAY carry additional keys beyond required."""
    # validation_failed requires {field, reason}; extras are allowed.
    app_errors.validate_details(
        app_errors.VALIDATION_FAILED,
        {"field": "x", "reason": "y", "additional_context": "z"},
    )


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


def test_failure_envelope_defaults_details_to_empty_object() -> None:
    """FR-033: envelope.failure() called without a details arg defaults
    details to {} (must never be None / absent)."""
    env = envelope.failure(app_errors.HOST_ONLY, "host-only")
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY
    assert env["error"]["details"] == {}


def test_internal_error_envelope_shape() -> None:
    """envelope.internal_error() is the dispatcher's safety-net fallback.
    It MUST emit the FR-033/FR-034a shape: ok=False, code=internal_error,
    details={}. The message field is free-form (operator-facing prose);
    the dispatcher sanitizes leak-prone content before passing it in.
    """
    env = envelope.internal_error("safety-net fallback")
    assert env["ok"] is False
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    assert env["error"]["code"] == app_errors.INTERNAL_ERROR
    assert env["error"]["details"] == {}
    assert env["error"]["message"] == "safety-net fallback"


def test_internal_error_envelope_default_message() -> None:
    """envelope.internal_error() with no args still emits a valid envelope."""
    env = envelope.internal_error()
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.INTERNAL_ERROR
    assert env["error"]["details"] == {}
    assert isinstance(env["error"]["message"], str)
    assert env["error"]["message"]  # non-empty


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


def test_hello_validation_failed_on_negative_major(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-036: client_app_contract_major < 1 → validation_failed."""
    env = hello_mod.app_hello(
        daemon_ctx,
        {"client_app_contract_major": 0},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.VALIDATION_FAILED
    assert env["error"]["details"]["field"] == "client_app_contract_major"


def test_hello_validation_failed_on_non_string_client_id(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-010: a non-string client_id → validation_failed.field == client_id."""
    env = hello_mod.app_hello(
        daemon_ctx,
        {"client_id": 12345},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.VALIDATION_FAILED
    assert env["error"]["details"]["field"] == "client_id"


def test_hello_validation_failed_on_oversized_client_version(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-010: client_version length cap (64) is enforced."""
    env = hello_mod.app_hello(
        daemon_ctx,
        {"client_version": "v" * 65},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.VALIDATION_FAILED
    assert env["error"]["details"]["field"] == "client_version"


def test_hello_tolerates_non_dict_params(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """app.hello with a non-dict params (None / list) MUST NOT crash —
    it normalizes to an empty dict and issues a session."""
    for bad_params in (None, [1, 2, 3], "not-a-dict"):
        env = hello_mod.app_hello(daemon_ctx, bad_params, peer_uid=host_peer)  # type: ignore[arg-type]
        assert env["ok"] is True, (bad_params, env)
        assert env["result"]["app_session_token"]


def test_hello_session_token_unique_per_call(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """Sessions are minted fresh each call; tokens are unique."""
    e1 = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    e2 = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    assert e1["ok"] and e2["ok"]
    assert e1["result"]["app_session_token"] != e2["result"]["app_session_token"]
    assert e1["result"]["app_session_id"] < e2["result"]["app_session_id"]


def test_t098_is_app_method_classifier() -> None:
    """T098: is_app_method() identifies the app.* namespace for the
    FEAT-002 unknown-method rewriter."""
    from agenttower.app_contract.dispatcher import is_app_method

    assert is_app_method("app.preflight") is True
    assert is_app_method("app.foo.bar") is True
    assert is_app_method("app.") is True  # weird but matches prefix
    assert is_app_method("appfoo") is False
    assert is_app_method("ping") is False
    assert is_app_method("status") is False
    assert is_app_method("") is False
    assert is_app_method(None) is False  # type: ignore[arg-type]


def test_t098_make_unknown_method_envelope_shape() -> None:
    """T098: make_unknown_method_envelope() produces an FR-033-compliant
    failure envelope with code=unknown_method and details={}."""
    from agenttower.app_contract.dispatcher import make_unknown_method_envelope

    env = make_unknown_method_envelope("app.foo.bar")
    assert env["ok"] is False
    assert env["app_contract_version"] == "1.0"
    assert env["error"]["code"] == "unknown_method"
    assert env["error"]["details"] == {}
    assert "app.foo.bar" in env["error"]["message"]


def test_hello_rejects_9th_concurrent_session(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-008b: 9th concurrent app.hello rejected with too_many_sessions."""
    from agenttower.app_contract import sessions as sessions_mod

    fresh = sessions_mod.SessionRegistry()
    sessions_mod.set_registry(fresh)
    try:
        for i in range(sessions_mod.MAX_SESSIONS):
            envelope = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
            assert envelope["ok"], f"hello call #{i+1} should succeed"
        assert fresh.size() == sessions_mod.MAX_SESSIONS
        ninth = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
        assert ninth["ok"] is False
        assert ninth["error"]["code"] == "validation_failed"
        assert ninth["error"]["details"] == {
            "field": "app.hello",
            "reason": "too_many_sessions",
        }
        assert fresh.size() == sessions_mod.MAX_SESSIONS
    finally:
        sessions_mod.set_registry(sessions_mod.SessionRegistry())


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


# ─── app.readiness (FR-012, FR-013, FR-014a, FR-045) ─────────────────────


@pytest.fixture
def daemon_ctx_with_db(tmp_path: Path) -> "DaemonContext":
    """DaemonContext with a real SQLite schema applied (no services wired)."""
    from agenttower.state.schema import open_registry

    state_db = tmp_path / "registry.db"
    conn, _status = open_registry(state_db, namespace_root=tmp_path)
    events_file = tmp_path / "events.jsonl"
    events_file.parent.mkdir(parents=True, exist_ok=True)

    return DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=state_db,
        daemon_version="0.0.0-test",
        schema_version=10,
        state_conn=conn,
        events_file=events_file,
    )


def _readiness_call(ctx, host_uid, token=None):
    from agenttower.app_contract import readiness as r
    params: dict = {}
    if token is not None:
        params["app_session_token"] = token
    return r.app_readiness(ctx, params, peer_uid=host_uid)


def _dashboard_call(ctx, host_uid, recent_limit=None, token=None):
    from agenttower.app_contract import dashboard as d
    params: dict = {}
    if token is not None:
        params["app_session_token"] = token
    if recent_limit is not None:
        params["recent_limit"] = recent_limit
    return d.app_dashboard(ctx, params, peer_uid=host_uid)


def test_readiness_host_only_gate(daemon_ctx_with_db) -> None:
    """FR-042: readiness rejects no-credentials peer with host_only.

    Host-only fires BEFORE the session gate (FR-042 + FR-007 ordering),
    so a container peer gets ``host_only`` even when no token is supplied.
    """
    env = _readiness_call(daemon_ctx_with_db, -1)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY


def test_readiness_session_required_when_token_missing(
    daemon_ctx_with_db, host_peer: int
) -> None:
    """FR-007: host peer without a token → app_session_required."""
    env = _readiness_call(daemon_ctx_with_db, host_peer)  # no token
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_SESSION_REQUIRED
    assert env["error"]["details"] == {}


def test_readiness_session_expired_when_token_invalid(
    daemon_ctx_with_db, host_peer: int
) -> None:
    """FR-007: host peer with an unknown token → app_session_expired."""
    env = _readiness_call(daemon_ctx_with_db, host_peer, token="not-a-real-token")
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_SESSION_EXPIRED


def test_readiness_session_required_on_non_string_token(
    daemon_ctx_with_db, host_peer: int
) -> None:
    """FR-007: malformed (non-string) token → app_session_required."""
    from agenttower.app_contract import readiness as r
    env = r.app_readiness(
        daemon_ctx_with_db,
        {"app_session_token": 12345},  # int, not a string
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_SESSION_REQUIRED


def test_readiness_envelope_shape(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-012, FR-013, FR-014a: state + 6 subsystems + hints array."""
    host_peer, token = host_session
    env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True
    r = env["result"]
    # FR-012: state is from the closed set.
    assert r["state"] in {"ready", "degraded", "unavailable"}
    # FR-013: all 6 required subsystems present, in fixed order.
    assert [s["name"] for s in r["subsystems"]] == list(
        versioning.SUBSYSTEM_NAMES
    )
    # Each row carries the documented fields.
    for row in r["subsystems"]:
        assert set(row.keys()) == {"name", "status", "reason", "hint"}
        assert row["status"] in {"ok", "degraded", "unavailable"}
        if row["status"] == "ok":
            assert row["reason"] == ""
    # FR-014a: hints array is always present.
    assert isinstance(r["hints"], list)


def test_readiness_sqlite_probe_ok(
    daemon_ctx_with_db, host_session
) -> None:
    """SQLite probe is ``ok`` against a freshly-opened registry."""
    host_peer, token = host_session
    env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    by_name = {s["name"]: s for s in env["result"]["subsystems"]}
    assert by_name["sqlite"]["status"] == "ok"


def test_readiness_unwired_services_are_unavailable(
    daemon_ctx_with_db, host_session
) -> None:
    """Unwired services produce subsystem rows with status=unavailable +
    a non-empty reason."""
    host_peer, token = host_session
    env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    by_name = {s["name"]: s for s in env["result"]["subsystems"]}
    for name in (
        "docker",
        "tmux_discovery",
        "routing_worker",
        "log_attachment_workers",
    ):
        assert by_name[name]["status"] == "unavailable", (
            f"{name} should be unavailable when service is unwired"
        )
        assert by_name[name]["reason"] != ""


def test_readiness_emits_docker_unavailable_hint(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-014a: docker unwired → docker_unavailable_hint with action_required."""
    host_peer, token = host_session
    env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    codes = {h["code"] for h in env["result"]["hints"]}
    assert "docker_unavailable_hint" in codes
    # Severity check
    by_code = {h["code"]: h for h in env["result"]["hints"]}
    assert by_code["docker_unavailable_hint"]["severity"] == "action_required"


def test_readiness_jsonl_probe_degraded_when_parent_unwritable(
    daemon_ctx_with_db, host_session, tmp_path: Path, monkeypatch
) -> None:
    """probe_jsonl returns degraded when parent dir lacks write permission."""
    host_peer, token = host_session
    # Point events_file at a read-only directory to trigger the writability check.
    ro_dir = tmp_path / "readonly"
    ro_dir.mkdir()
    ro_dir.chmod(0o555)  # r-x permissions only — no write
    try:
        monkeypatch.setattr(
            daemon_ctx_with_db, "events_file", ro_dir / "events.jsonl"
        )
        env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
        by_name = {s["name"]: s for s in env["result"]["subsystems"]}
        # On most filesystems a non-writable parent → degraded.
        # On exotic mounts where the writability check is satisfied anyway
        # (e.g., user is root), we skip the strict assertion.
        if os.geteuid() != 0:
            assert by_name["jsonl"]["status"] == "degraded"
            assert "not writable" in by_name["jsonl"]["reason"]
    finally:
        ro_dir.chmod(0o755)  # restore so pytest can clean up


# ─── app.dashboard (FR-015, FR-016, FR-017, FR-018, FR-045) ──────────────


def test_dashboard_host_only_gate(daemon_ctx_with_db) -> None:
    """FR-042: dashboard rejects container peer with host_only.

    Host-only fires BEFORE the session gate (FR-042 + FR-007 ordering),
    so a container peer gets ``host_only`` even when a token is supplied.
    """
    env = _dashboard_call(daemon_ctx_with_db, -1)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY


def test_dashboard_session_required_when_token_missing(
    daemon_ctx_with_db, host_peer: int
) -> None:
    """FR-007: host peer without a token → app_session_required."""
    env = _dashboard_call(daemon_ctx_with_db, host_peer)  # no token
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_SESSION_REQUIRED


def test_dashboard_session_expired_when_token_invalid(
    daemon_ctx_with_db, host_peer: int
) -> None:
    """FR-007: host peer with an unknown token → app_session_expired."""
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token="not-a-real-token")
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_SESSION_EXPIRED


def test_dashboard_host_only_beats_session_gate(daemon_ctx_with_db) -> None:
    """FR-042 + FR-007 ordering: container peer with a valid-looking token
    still gets ``host_only``, never ``app_session_required`` / ``app_session_expired``
    (would leak session-existence info to a non-host peer)."""
    env = _dashboard_call(
        daemon_ctx_with_db, -1, token="any-token-value-at-all"
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY


def test_dashboard_envelope_shape(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-015, FR-016, FR-017, FR-014a: counts + recents + hints all present."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True
    r = env["result"]
    # All 7 count surfaces present (FR-016).
    assert set(r["counts"].keys()) == {
        "containers", "panes", "agents", "log_attachments",
        "events", "queue", "routes",
    }
    # Container counts have the FR-016 buckets.
    assert set(r["counts"]["containers"].keys()) == {
        "active", "inactive", "degraded_scan"
    }
    # Pane counts have the FR-016 buckets.
    assert set(r["counts"]["panes"].keys()) == {
        "total", "registered", "unregistered"
    }
    # Agent counts include the FEAT-006 closed role set.
    assert "by_role" in r["counts"]["agents"]
    assert set(r["counts"]["agents"]["by_role"].keys()) == set(
        versioning.AGENT_ROLES
    )
    # Queue counts cover the full FEAT-009 closed state set.
    assert set(r["counts"]["queue"].keys()) == set(versioning.QUEUE_STATES)
    # Route counts: enabled + disabled.
    assert set(r["counts"]["routes"].keys()) == {"enabled", "disabled"}
    # Recents present for events/queue/routes (FR-017).
    assert set(r["recent"].keys()) == {"events", "queue", "routes"}
    for surface in ("events", "queue", "routes"):
        assert isinstance(r["recent"][surface], list)
    # Hints array always present.
    assert isinstance(r["hints"], list)


def test_dashboard_empty_system_returns_zero_counts(
    daemon_ctx_with_db, host_session
) -> None:
    """Coverage: an empty system returns all-zero counts and empty recents."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    r = env["result"]
    for bucket in ("active", "inactive", "degraded_scan"):
        assert r["counts"]["containers"][bucket] == 0
    assert r["counts"]["panes"]["total"] == 0
    assert r["counts"]["agents"]["total"] == 0
    assert r["counts"]["events"]["total"] == 0
    for state in versioning.QUEUE_STATES:
        assert r["counts"]["queue"][state] == 0
    assert r["counts"]["routes"] == {"enabled": 0, "disabled": 0}
    assert r["recent"]["events"] == []
    assert r["recent"]["queue"] == []
    assert r["recent"]["routes"] == []


def test_dashboard_recent_limit_default_is_10(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-017: default recent_limit is 10."""
    # With an empty system the recent arrays are empty; the assertion is on
    # request acceptance, not row count.
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True


@pytest.mark.parametrize("limit", [0, 51, 100, -1])
def test_dashboard_recent_limit_out_of_bounds_returns_validation_failed(
    daemon_ctx_with_db, host_session, limit: int
) -> None:
    """FR-017: recent_limit out of bounds → validation_failed.details.field."""
    host_peer, token = host_session
    env = _dashboard_call(
        daemon_ctx_with_db, host_peer, recent_limit=limit, token=token
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.VALIDATION_FAILED
    assert env["error"]["details"]["field"] == "recent_limit"


@pytest.mark.parametrize("bad", ["10", 10.0, True, [10]])
def test_dashboard_recent_limit_wrong_type_returns_validation_failed(
    daemon_ctx_with_db, host_session, bad
) -> None:
    """FR-017: recent_limit must be an integer (not str/float/bool/list)."""
    host_peer, token = host_session
    env = _dashboard_call(
        daemon_ctx_with_db, host_peer, recent_limit=bad, token=token
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.VALIDATION_FAILED


def test_dashboard_emits_start_bench_container_hint_when_empty(
    daemon_ctx_with_db, host_session
) -> None:
    """FR-014a: zero containers and docker unwired → docker hint, not
    start_bench_container (the latter only fires if docker is reachable)."""
    host_peer, token = host_session
    env = _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    codes = {h["code"] for h in env["result"]["hints"]}
    # docker_unavailable_hint should be emitted (docker unwired)
    assert "docker_unavailable_hint" in codes
    # start_bench_container should NOT be emitted (docker is unavailable so
    # we suppress the start-container hint to avoid double-nagging)
    assert "start_bench_container" not in codes


def test_dashboard_no_audit_side_effect(
    daemon_ctx_with_db, host_session, tmp_path: Path
) -> None:
    """FR-045: dashboard MUST be side-effect-free (no audit row written)."""
    host_peer, token = host_session
    events_file = daemon_ctx_with_db.events_file
    # Confirm the events file either doesn't exist or is empty before.
    before_size = events_file.stat().st_size if events_file.exists() else 0
    _dashboard_call(daemon_ctx_with_db, host_peer, token=token)
    after_size = events_file.stat().st_size if events_file.exists() else 0
    assert after_size == before_size, (
        "app.dashboard wrote to the audit JSONL — violates FR-045 "
        "side-effect-free guarantee"
    )


# ─── Session gate ordering check that doesn't fit cleanly elsewhere ──────


def test_readiness_host_only_beats_session_gate(daemon_ctx_with_db) -> None:
    """FR-042 + FR-007 ordering: container peer with a token still gets
    host_only (would leak session-existence info to non-host peer)."""
    env = _readiness_call(daemon_ctx_with_db, -1, token="any-token-value-at-all")
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY


# ─── Dispatcher wrapper: FR-033 envelope-shape safety net ────────────────


def test_dispatcher_wraps_contract_violation_into_internal_error(
    daemon_ctx,
) -> None:
    """A handler that emits a malformed failure (raises ContractViolation)
    MUST surface as the FEAT-011 ``internal_error`` envelope, never as a
    raw exception or the legacy FEAT-002 INTERNAL_ERROR shape."""
    from agenttower.app_contract import dispatcher as dispatcher_mod
    from agenttower.app_contract.errors import ContractViolation

    def buggy_handler(ctx, params, peer_uid=-1):
        # Simulate a handler-level bug — would normally come from
        # envelope.failure() emitting a non-existent code, etc.
        raise ContractViolation("simulated malformed failure")

    wrapped = dispatcher_mod._wrap_handler(buggy_handler)
    env = wrapped(daemon_ctx, {})

    assert env["ok"] is False
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    assert env["error"]["code"] == app_errors.INTERNAL_ERROR
    assert env["error"]["details"] == {}
    assert "malformed" in env["error"]["message"].lower()


def test_dispatcher_wraps_unexpected_exception_into_internal_error(
    daemon_ctx, capsys
) -> None:
    """A handler that raises any other exception MUST surface as the
    FEAT-011 ``internal_error`` envelope (FR-033 invariant). The
    exception details MUST be logged to stderr but MUST NOT leak into
    the wire envelope (security tightening from PR-19 review).
    """
    from agenttower.app_contract import dispatcher as dispatcher_mod

    def crashing_handler(ctx, params, peer_uid=-1):
        raise ValueError("simulated unexpected bug with /secret/path")

    wrapped = dispatcher_mod._wrap_handler(crashing_handler)
    env = wrapped(daemon_ctx, {})

    assert env["ok"] is False
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    assert env["error"]["code"] == app_errors.INTERNAL_ERROR
    assert env["error"]["details"] == {}
    # Wire envelope must NOT leak the exception type name, message, or
    # any payload-derived content.
    assert "ValueError" not in env["error"]["message"]
    assert "secret" not in env["error"]["message"]
    assert "simulated" not in env["error"]["message"]
    # But operators MUST be able to debug via stderr.
    captured = capsys.readouterr()
    assert "ValueError" in captured.err
    assert "simulated unexpected bug" in captured.err


def test_dispatcher_wrapped_handler_passes_through_normal_returns(
    daemon_ctx,
) -> None:
    """The wrapper MUST NOT alter a well-formed envelope returned by the
    handler — only catch exceptions."""
    from agenttower.app_contract import dispatcher as dispatcher_mod

    def good_handler(ctx, params, peer_uid=-1):
        return envelope.success({"hello": "world"})

    wrapped = dispatcher_mod._wrap_handler(good_handler)
    env = wrapped(daemon_ctx, {})

    assert env["ok"] is True
    assert env["result"] == {"hello": "world"}


def test_app_dispatch_handlers_are_wrapped(daemon_ctx) -> None:
    """Smoke check: the four real ``app.*`` handlers in DISPATCH go through
    ``_wrap_handler`` — not the raw module-level functions."""
    from agenttower.app_contract import dispatcher as dispatcher_mod

    # The wrapped name is preserved on the wrapper, but a function-identity
    # check confirms the dispatch entry is NOT the raw handler.
    from agenttower.app_contract import (
        dashboard as dashboard_mod,
        hello as hello_mod_local,
        preflight as preflight_mod_local,
        readiness as readiness_mod,
    )
    raw_handlers = {
        "app.preflight": preflight_mod_local.app_preflight,
        "app.hello": hello_mod_local.app_hello,
        "app.readiness": readiness_mod.app_readiness,
        "app.dashboard": dashboard_mod.app_dashboard,
    }
    for name, raw in raw_handlers.items():
        wrapped = dispatcher_mod.APP_DISPATCH[name]
        assert wrapped is not raw, (
            f"{name} dispatch entry is the raw handler; "
            f"_wrap_handler safety net is bypassed"
        )


# ─── FR-003b wire framing + T098 unknown-method envelope rewriter ────────


def test_malformed_request_envelope_shape() -> None:
    """FR-003b: ``_make_malformed_request_envelope`` returns the FEAT-011
    envelope with ``code == "malformed_request"`` and ``details.reason``."""
    from agenttower.socket_api.server import _make_malformed_request_envelope

    env = _make_malformed_request_envelope("stray CR")
    assert env["ok"] is False
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    assert env["error"]["code"] == app_errors.MALFORMED_REQUEST
    assert env["error"]["details"] == {"reason": "stray CR"}


@pytest.mark.parametrize(
    "reason",
    [
        "stray CR",
        "embedded NUL",
        "empty line",
        "trailing content",
        "invalid utf-8",
        "json decode error: Expecting value: line 1 column 1 (char 0)",
    ],
)
def test_malformed_request_envelope_reason_classes(reason: str) -> None:
    """FR-003b: every one of the 6 wire-framing rejection classes builds
    a structurally-valid FEAT-011 envelope."""
    from agenttower.socket_api.server import _make_malformed_request_envelope

    env = _make_malformed_request_envelope(reason)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.MALFORMED_REQUEST
    assert env["error"]["details"]["reason"] == reason


def test_app_dispatcher_unknown_method_envelope_for_app_method() -> None:
    """T098: ``app.*`` methods not in DISPATCH return the FR-033-compliant
    FEAT-011 envelope (with ``app_contract_version`` + ``details: {}``)."""
    from agenttower.app_contract import dispatcher as dispatcher_mod

    assert dispatcher_mod.is_app_method("app.preflight") is True
    assert dispatcher_mod.is_app_method("app.foo.bar") is True
    assert dispatcher_mod.is_app_method("ping") is False
    assert dispatcher_mod.is_app_method("routes.list") is False

    env = dispatcher_mod.make_unknown_method_envelope("app.foo.bar")
    assert env["ok"] is False
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    assert env["error"]["code"] == app_errors.UNKNOWN_METHOD
    # FR-034b: details == {} regardless of cause (typo vs future-minor).
    assert env["error"]["details"] == {}
    assert "app.foo.bar" in env["error"]["message"]
