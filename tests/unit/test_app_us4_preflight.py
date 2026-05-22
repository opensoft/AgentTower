"""FEAT-011 US4 (T068) — ``app.preflight`` health-detection unit tests.

Story 4 ("degraded & unavailable states") adds daemon-side health
detection to ``app.preflight`` (T070): a daemon that has begun its
graceful-shutdown sequence still answers the socket, but reports
itself as ``daemon_unavailable`` so the client knows the backend is on
its way out.

Covered:

* happy path — host peer, daemon healthy → ``code == "ok"``;
* the new shutdown path — ``ctx.shutdown_requested`` set →
  ``code == "daemon_unavailable"``, ``daemon_reachable == false``,
  ``socket_reachable == true``;
* the host-only gate — a non-host peer is refused with ``host_only``
  before any health detection runs (FR-042).

Self-contained: all fixtures/helpers are copied in from
``test_app_contract_foundations.py`` so there are no cross-file imports.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttower.app_contract import APP_CONTRACT_VERSION
from agenttower.app_contract import errors as app_errors
from agenttower.app_contract import preflight as preflight_mod
from agenttower.app_contract import sessions
from agenttower.socket_api.methods import (
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)


# ─── Fixtures (copied from test_app_contract_foundations.py) ───────────────────


@pytest.fixture(autouse=True)
def fresh_session_registry() -> None:
    """Ensure each test sees a clean SessionRegistry."""
    sessions.set_registry(sessions.SessionRegistry())


@pytest.fixture
def daemon_ctx(tmp_path: Path) -> DaemonContext:
    """Minimal DaemonContext — no shutdown event wired (healthy daemon)."""
    return DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=tmp_path / "state.db",
        daemon_version="0.0.0-test",
        schema_version=10,
    )


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


# ─── happy path (FR-011) ─────────────────────────────────────────────────


def test_preflight_ok_when_daemon_healthy(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """Host peer + no shutdown signal → ``code == 'ok'``, both flags true."""
    env = preflight_mod.app_preflight(daemon_ctx, {}, peer_uid=host_peer)
    assert env["ok"] is True
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    result = env["result"]
    assert result["code"] == "ok"
    assert result["socket_reachable"] is True
    assert result["daemon_reachable"] is True


def test_preflight_ok_when_shutdown_event_present_but_unset(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """A wired-but-unset shutdown event is a healthy daemon → ``code == 'ok'``.

    The check is ``is_set()`` — merely having the Event attribute
    populated must not trip the daemon_unavailable path."""
    daemon_ctx.shutdown_requested = threading.Event()  # created, not set
    env = preflight_mod.app_preflight(daemon_ctx, {}, peer_uid=host_peer)
    assert env["ok"] is True
    assert env["result"]["code"] == "ok"
    assert env["result"]["daemon_reachable"] is True


# ─── new shutdown path (T070) ────────────────────────────────────────────


def test_preflight_daemon_unavailable_when_shutting_down(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """``ctx.shutdown_requested`` set → ``code == 'daemon_unavailable'``.

    The socket answered (so ``socket_reachable`` stays true) but the
    daemon behind it has begun graceful shutdown, so it reports itself
    as not reachable for real work."""
    shutdown = threading.Event()
    shutdown.set()
    daemon_ctx.shutdown_requested = shutdown

    env = preflight_mod.app_preflight(daemon_ctx, {}, peer_uid=host_peer)
    assert env["ok"] is True  # still a success envelope (FR-011)
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    result = env["result"]
    assert result["code"] == "daemon_unavailable"
    assert result["daemon_reachable"] is False
    assert result["socket_reachable"] is True


# ─── host-only gate (FR-042) ─────────────────────────────────────────────


def test_preflight_host_only_when_peer_not_host(
    daemon_ctx: DaemonContext,
) -> None:
    """A non-host peer is refused with ``host_only`` + ``details == {}``.

    No request peer context is set, so ``is_host_peer()`` returns
    False — the gate fires before any health detection."""
    env = preflight_mod.app_preflight(daemon_ctx, {}, peer_uid=-1)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY
    assert env["error"]["details"] == {}


def test_preflight_host_only_beats_shutdown_detection(
    daemon_ctx: DaemonContext,
) -> None:
    """A non-host peer is refused even while the daemon is shutting down —
    the host-only gate runs first, so the caller never learns the
    daemon's health state (no info leak to a non-host peer)."""
    shutdown = threading.Event()
    shutdown.set()
    daemon_ctx.shutdown_requested = shutdown

    # No peer context set → non-host peer.
    env = preflight_mod.app_preflight(daemon_ctx, {}, peer_uid=-1)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY
