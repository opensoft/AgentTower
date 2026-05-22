"""FEAT-011 T072 — Story 5 contract-version major-mismatch unit tests.

Covers FR-036 / SC-005 / FR-034a: a client declaring a major version
that does not match the daemon's must get the ``app_contract_major_unsupported``
failure envelope — carrying the full ``details`` shape
``{daemon_app_contract_version, client_app_contract_major}`` and issuing
**no** session token. A subsequent session-gated ``app.*`` call with no
token then surfaces ``app_session_required``.

Pure in-process tests — handlers called directly (SC-001).

Fixtures are copied from ``test_app_contract_foundations.py``; pytest fixtures
do not auto-share across files.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttower.app_contract import APP_CONTRACT_VERSION
from agenttower.app_contract import errors as app_errors
from agenttower.app_contract import hello as hello_mod
from agenttower.app_contract import readiness as readiness_mod
from agenttower.app_contract import sessions
from agenttower.socket_api.methods import (
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)


# ─── Fixtures (copied from test_app_contract_foundations.py) ───────────────────


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
    """Set thread-local request peer context to the daemon's own pid (host)."""
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    uid = os.geteuid()
    _set_request_peer_context(peer_pid=os.getpid())
    try:
        yield uid
    finally:
        _clear_request_peer_context()


# ─── FR-036: major mismatch → app_contract_major_unsupported ─────────────


def test_major_2_against_v1_daemon_emits_major_unsupported(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-036 / SC-005: client declares major 2 → app_contract_major_unsupported."""
    env = hello_mod.app_hello(
        daemon_ctx,
        {"client_app_contract_major": 2},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_CONTRACT_MAJOR_UNSUPPORTED


def test_major_mismatch_details_shape_is_complete(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-034a: details carry exactly the two registry-required keys with
    the daemon's contract version and the client's declared major."""
    env = hello_mod.app_hello(
        daemon_ctx,
        {"client_app_contract_major": 2},
        peer_uid=host_peer,
    )
    details = env["error"]["details"]
    # FR-034a registry: both keys required, present, and correct.
    assert set(details.keys()) >= {
        "daemon_app_contract_version",
        "client_app_contract_major",
    }
    assert details["daemon_app_contract_version"] == APP_CONTRACT_VERSION
    assert details["client_app_contract_major"] == 2
    # Cross-check against the FR-034a registry contract directly.
    required = app_errors.DETAILS_REQUIRED_KEYS[
        app_errors.APP_CONTRACT_MAJOR_UNSUPPORTED
    ]
    assert required <= set(details.keys())


def test_major_mismatch_issues_no_session_token(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-036: a major mismatch issues NO session — the result carries no
    token and the registry stays empty."""
    registry = sessions.SessionRegistry()
    sessions.set_registry(registry)
    assert registry.size() == 0

    env = hello_mod.app_hello(
        daemon_ctx,
        {"client_app_contract_major": 2},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    # Failure envelope has no "result" key at all → no token surface.
    assert "result" not in env
    # FR-036: no session was minted.
    assert registry.size() == 0


def test_subsequent_app_call_without_token_is_session_required(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """After a rejected app.hello (major mismatch), a follow-up app.* call
    has no token to present → app_session_required (FR-007)."""
    hello_env = hello_mod.app_hello(
        daemon_ctx,
        {"client_app_contract_major": 2},
        peer_uid=host_peer,
    )
    assert hello_env["ok"] is False
    assert hello_env["error"]["code"] == app_errors.APP_CONTRACT_MAJOR_UNSUPPORTED

    # No token was issued; a downstream app.readiness call with no token
    # falls straight through to the session gate.
    readiness_env = readiness_mod.app_readiness(
        daemon_ctx, {}, peer_uid=host_peer
    )
    assert readiness_env["ok"] is False
    assert readiness_env["error"]["code"] == app_errors.APP_SESSION_REQUIRED
    assert readiness_env["error"]["details"] == {}


@pytest.mark.parametrize("bad_major", [2, 3, 99])
def test_any_non_matching_major_is_rejected(
    daemon_ctx: DaemonContext, host_peer: int, bad_major: int
) -> None:
    """FR-035 / FR-036: only a matching major is compatible — every other
    major (>= 1) is rejected with the mismatch envelope."""
    env = hello_mod.app_hello(
        daemon_ctx,
        {"client_app_contract_major": bad_major},
        peer_uid=host_peer,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_CONTRACT_MAJOR_UNSUPPORTED
    assert env["error"]["details"]["client_app_contract_major"] == bad_major


def test_major_exactly_1_succeeds_and_issues_token(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """FR-036: major exactly 1 matches the v1.x daemon → success + token."""
    env = hello_mod.app_hello(
        daemon_ctx,
        {"client_app_contract_major": 1},
        peer_uid=host_peer,
    )
    assert env["ok"] is True
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    assert isinstance(env["result"]["app_session_token"], str)
    assert env["result"]["app_session_token"]
