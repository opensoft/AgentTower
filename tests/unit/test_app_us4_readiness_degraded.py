"""FEAT-011 US4 (T066) — one test per readiness failure mode.

Story 4 ("degraded & unavailable states") requires that every
subsystem failure surfaces as a *structured* readiness response: the
offending subsystem row carries the right ``status``, the top-level
``state`` aggregates to ``degraded``/``unavailable``, and — for the
docker-unavailable case — a ``docker_unavailable_hint`` is emitted.

This file walks each of the six probes through its failure branch by
constructing a ``DaemonContext`` whose service is unwired (or whose
path is bad) and calling the ``app.readiness`` handler end to end.

Self-contained: all fixtures/helpers are copied in from
``test_app_contract_foundations.py`` / ``test_app_readiness.py`` so there are
no cross-file imports (pytest fixtures do not auto-share across files).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agenttower.app_contract import hello as hello_mod
from agenttower.app_contract import readiness as r
from agenttower.app_contract import sessions
from agenttower.app_contract.versioning import (
    READINESS_STATE_DEGRADED,
    SUBSYSTEM_STATUS_DEGRADED,
    SUBSYSTEM_STATUS_UNAVAILABLE,
)
from agenttower.socket_api.methods import (
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)


# ─── Fixtures (copied from test_app_readiness.py) ────────────────────────


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


@pytest.fixture
def daemon_ctx_with_db(tmp_path: Path) -> DaemonContext:
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


@pytest.fixture
def host_session(daemon_ctx_with_db, host_peer):
    """Host peer + a freshly-minted app.hello session token."""
    env = hello_mod.app_hello(daemon_ctx_with_db, {}, peer_uid=host_peer)
    assert env["ok"] is True, f"host_session setup failed: {env}"
    return host_peer, env["result"]["app_session_token"]


def _readiness_call(ctx, host_uid, token=None):
    params: dict = {}
    if token is not None:
        params["app_session_token"] = token
    return r.app_readiness(ctx, params, peer_uid=host_uid)


def _by_name(env: dict) -> dict[str, dict]:
    return {s["name"]: s for s in env["result"]["subsystems"]}


# ─── Test doubles ────────────────────────────────────────────────────────


class _OkDiscovery:
    """A wired, reachable docker discovery service (probe → ok)."""

    def list_containers(self, active_only: bool = False):
        return []


def _wire_all_ok(monkeypatch, ctx) -> None:
    """Wire every non-sqlite/jsonl service so only the probe under test fails."""
    monkeypatch.setattr(ctx, "discovery_service", _OkDiscovery(), raising=False)
    monkeypatch.setattr(ctx, "pane_service", object(), raising=False)
    monkeypatch.setattr(ctx, "delivery_worker", object(), raising=False)
    monkeypatch.setattr(ctx, "log_service", object(), raising=False)


# ─── docker unavailable ──────────────────────────────────────────────────


def test_docker_unavailable_surfaces_status_state_and_hint(
    daemon_ctx_with_db, host_session
) -> None:
    """Docker unwired → docker.status == 'unavailable', top-level degraded,
    and a docker_unavailable_hint is emitted (FR-013/FR-014/FR-014a)."""
    host_peer, token = host_session
    env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True

    by_name = _by_name(env)
    assert by_name["docker"]["status"] == SUBSYSTEM_STATUS_UNAVAILABLE
    assert by_name["docker"]["reason"] != ""

    # Mixed ok/unavailable rows aggregate to degraded.
    assert env["result"]["state"] == READINESS_STATE_DEGRADED

    codes = {h["code"] for h in env["result"]["hints"]}
    assert "docker_unavailable_hint" in codes


# ─── sqlite degraded ─────────────────────────────────────────────────────


def test_sqlite_degraded_surfaces_status_and_state(
    daemon_ctx_with_db, host_session, monkeypatch
) -> None:
    """A closed SQLite connection → sqlite.status == 'degraded'."""
    host_peer, token = host_session
    _wire_all_ok(monkeypatch, daemon_ctx_with_db)

    dead = sqlite3.connect(":memory:")
    dead.close()  # subsequent execute() raises ProgrammingError
    monkeypatch.setattr(daemon_ctx_with_db, "state_conn", dead, raising=False)

    env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    by_name = _by_name(env)
    assert by_name["sqlite"]["status"] == SUBSYSTEM_STATUS_DEGRADED
    assert "sqlite probe failed" in by_name["sqlite"]["reason"]
    # One degraded row → top-level degraded.
    assert env["result"]["state"] == READINESS_STATE_DEGRADED


# ─── jsonl degraded ──────────────────────────────────────────────────────


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses W_OK checks")
def test_jsonl_degraded_surfaces_status_and_state(
    daemon_ctx_with_db, host_session, monkeypatch, tmp_path: Path
) -> None:
    """A read-only events_file parent directory → jsonl.status == 'degraded'."""
    host_peer, token = host_session
    _wire_all_ok(monkeypatch, daemon_ctx_with_db)

    ro_dir = tmp_path / "readonly"
    ro_dir.mkdir()
    ro_dir.chmod(0o555)  # r-x only — not writable
    try:
        monkeypatch.setattr(
            daemon_ctx_with_db, "events_file", ro_dir / "events.jsonl"
        )
        env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
        by_name = _by_name(env)
        assert by_name["jsonl"]["status"] == SUBSYSTEM_STATUS_DEGRADED
        assert "not writable" in by_name["jsonl"]["reason"]
        assert env["result"]["state"] == READINESS_STATE_DEGRADED
    finally:
        ro_dir.chmod(0o755)


# ─── routing_worker degraded ─────────────────────────────────────────────


def test_routing_worker_degraded_surfaces_status_and_state(
    daemon_ctx_with_db, host_session, monkeypatch
) -> None:
    """A delivery worker whose thread is not alive → routing_worker degraded."""
    import threading

    host_peer, token = host_session
    _wire_all_ok(monkeypatch, daemon_ctx_with_db)

    dead_thread = threading.Thread(target=lambda: None)
    dead_thread.start()
    dead_thread.join()  # real Thread, now finished → not alive

    class _Worker:
        thread = dead_thread

    monkeypatch.setattr(
        daemon_ctx_with_db, "delivery_worker", _Worker(), raising=False
    )
    env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    by_name = _by_name(env)
    assert by_name["routing_worker"]["status"] == SUBSYSTEM_STATUS_DEGRADED
    assert "not alive" in by_name["routing_worker"]["reason"]
    assert env["result"]["state"] == READINESS_STATE_DEGRADED


# ─── log_attachment_workers degraded ─────────────────────────────────────


def test_log_attachment_workers_unavailable_surfaces_status_and_state(
    daemon_ctx_with_db, host_session, monkeypatch
) -> None:
    """An unwired log service → log_attachment_workers unavailable.

    ``probe_log_attachment_workers`` reports ``unavailable`` (not
    ``degraded``) when the service is unwired — that is its sole
    failure branch. Either way the top-level state must aggregate away
    from ``ready`` to a structured degraded response (FR-012/FR-014).
    """
    host_peer, token = host_session
    # Wire everything else ok; leave log_service unwired (None).
    monkeypatch.setattr(
        daemon_ctx_with_db, "discovery_service", _OkDiscovery(), raising=False
    )
    monkeypatch.setattr(daemon_ctx_with_db, "pane_service", object(), raising=False)
    monkeypatch.setattr(
        daemon_ctx_with_db, "delivery_worker", object(), raising=False
    )
    monkeypatch.setattr(daemon_ctx_with_db, "log_service", None, raising=False)

    env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    by_name = _by_name(env)
    assert by_name["log_attachment_workers"]["status"] == (
        SUBSYSTEM_STATUS_UNAVAILABLE
    )
    assert by_name["log_attachment_workers"]["reason"] != ""
    # One unavailable row mixed with ok rows → degraded top-level state.
    assert env["result"]["state"] == READINESS_STATE_DEGRADED
