"""FEAT-011 T036/T037/T038 unit tests — scan handlers.

In-process tests for ``app.scan.containers``, ``app.scan.panes``, and
``app.scan.status``. Uses synthetic scan services (no real docker / no
real tmux) so the tests run fast and deterministically.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agenttower.app_contract import scan_handlers, scans, sessions
from agenttower.socket_api.methods import (
    DISPATCH,
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)


# ─── Fakes ───────────────────────────────────────────────────────────────


@dataclass
class FakeScanResult:
    """Stands in for ``ContainerScanResult`` / ``PaneScanResult``.

    Frozen-dataclass projection works through the existing
    ``_result_to_dict`` helper.
    """
    scan_id: str
    status: str
    matched_count: int


class FakeScanService:
    """Synthetic scan service. Records calls and lets the test control
    timing via a ``threading.Event``.
    """

    def __init__(
        self,
        *,
        result: Any = None,
        raise_exc: BaseException | None = None,
        block_until: threading.Event | None = None,
    ) -> None:
        self.result = result or FakeScanResult(
            scan_id="fake-scan",
            status="ok",
            matched_count=3,
        )
        self.raise_exc = raise_exc
        self.block_until = block_until
        self.call_count = 0
        self.call_lock = threading.Lock()

    def scan(self) -> Any:
        with self.call_lock:
            self.call_count += 1
        if self.block_until is not None:
            self.block_until.wait(timeout=10.0)
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_registries() -> None:
    """Reset session + scan registries between tests."""
    sessions.set_registry(sessions.SessionRegistry())
    scans.set_registry(scans.ScanRegistry())


@pytest.fixture
def daemon_ctx(tmp_path: Path) -> DaemonContext:
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
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    _set_request_peer_context(peer_pid=os.getpid())
    try:
        yield os.geteuid()
    finally:
        _clear_request_peer_context()


@pytest.fixture
def host_session(daemon_ctx: DaemonContext, host_peer: int) -> tuple[int, str]:
    from agenttower.app_contract import hello as hello_mod

    env = hello_mod.app_hello(daemon_ctx, {}, peer_uid=host_peer)
    assert env["ok"], env
    return host_peer, env["result"]["app_session_token"]


# ─── app.scan.{containers,panes} happy path ──────────────────────────────


def test_scan_panes_wait_true_returns_completed_state(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """wait=true returns immediately when the underlying scan completes."""
    uid, token = host_session
    daemon_ctx.pane_service = FakeScanService(
        result=FakeScanResult(scan_id="x", status="ok", matched_count=4),
    )
    env = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"app_session_token": token, "wait": True},
        peer_uid=uid,
    )
    assert env["ok"] is True, env
    result = env["result"]
    assert "scan_id" in result
    assert result["state"] == "completed"
    assert result["result"]["matched_count"] == 4


def test_scan_containers_wait_true_returns_completed_state(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    daemon_ctx.discovery_service = FakeScanService(
        result=FakeScanResult(scan_id="x", status="ok", matched_count=2),
    )
    env = scan_handlers.app_scan_containers(
        daemon_ctx,
        {"app_session_token": token, "wait": True},
        peer_uid=uid,
    )
    assert env["ok"] is True, env
    assert env["result"]["state"] == "completed"


def test_scan_wait_false_returns_running_immediately(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """wait=false returns {scan_id, state: 'running'} without waiting."""
    uid, token = host_session
    gate = threading.Event()  # holds the scan in flight
    daemon_ctx.pane_service = FakeScanService(block_until=gate)
    env = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"app_session_token": token, "wait": False},
        peer_uid=uid,
    )
    assert env["ok"] is True, env
    assert env["result"]["state"] == "running"
    assert "scan_id" in env["result"]
    # Release the scan so the daemon thread can complete; otherwise the
    # registry holds a running scan and subsequent tests would coalesce.
    gate.set()
    # Wait for thread to drain (≤ 1 s slack on a normal CI machine).
    record = scans.get_registry().lookup(env["result"]["scan_id"])
    assert record is not None
    record.done.wait(timeout=2.0)


# ─── Coalescing (FR-030d) ────────────────────────────────────────────────


def test_concurrent_same_kind_scans_coalesce(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """FR-030d: a 2nd app.scan.panes while one is in-flight returns the
    same scan_id and the underlying service.scan() is only called once."""
    uid, token = host_session
    gate = threading.Event()
    service = FakeScanService(block_until=gate)
    daemon_ctx.pane_service = service

    # Kick off the first scan in a thread so we don't block.
    first_envelope: list[dict] = []

    def _first() -> None:
        # Thread-local peer context must be re-established per thread
        # (the host_peer fixture only sets it on the main thread).
        _set_request_peer_context(peer_pid=os.getpid())
        try:
            first_envelope.append(
                scan_handlers.app_scan_panes(
                    daemon_ctx,
                    {"app_session_token": token, "wait": True},
                    peer_uid=uid,
                )
            )
        finally:
            _clear_request_peer_context()

    t = threading.Thread(target=_first)
    t.start()
    # Give the first call time to register + spawn the worker thread.
    time.sleep(0.05)

    # Now make a second call from the same session — should coalesce.
    second = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"app_session_token": token, "wait": False},
        peer_uid=uid,
    )
    assert second["ok"] is True
    assert second["result"]["state"] == "running"

    # Release the underlying scan.
    gate.set()
    t.join(timeout=3.0)
    assert first_envelope[0]["ok"] is True, first_envelope[0]
    assert first_envelope[0]["result"]["scan_id"] == second["result"]["scan_id"]
    # Underlying scan was called exactly once (coalesced second caller
    # did NOT trigger a second invocation).
    assert service.call_count == 1


# ─── In-flight cap (FR-030e) ─────────────────────────────────────────────


def test_in_flight_cap_returns_too_many_scans(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """FR-030e: when MAX_IN_FLIGHT scans are running, the next request
    is rejected with validation_failed.too_many_scans_in_flight."""
    uid, token = host_session
    # Shrink the cap for the test.
    scans.set_registry(scans.ScanRegistry(max_in_flight=1))
    gate = threading.Event()
    daemon_ctx.pane_service = FakeScanService(block_until=gate)
    daemon_ctx.discovery_service = FakeScanService(block_until=gate)

    # First call (panes) takes the only slot.
    first = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"app_session_token": token, "wait": False},
        peer_uid=uid,
    )
    assert first["ok"] is True

    # Second call with a DIFFERENT kind (containers) → cap hit.
    second = scan_handlers.app_scan_containers(
        daemon_ctx,
        {"app_session_token": token, "wait": False},
        peer_uid=uid,
    )
    assert second["ok"] is False
    assert second["error"]["code"] == "validation_failed"
    assert second["error"]["details"] == {
        "field": "scan_kind",
        "reason": "too_many_scans_in_flight",
    }

    # Cleanup: release the in-flight panes scan.
    gate.set()
    record = scans.get_registry().lookup(first["result"]["scan_id"])
    if record is not None:
        record.done.wait(timeout=2.0)


# ─── Timeout (FR-030b) ───────────────────────────────────────────────────


def test_wait_true_timeout_returns_scan_timeout(
    daemon_ctx: DaemonContext,
    host_session: tuple[int, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR-030b: wait=true that exceeds the timeout returns scan_timeout
    with details.scan_id. The scan continues server-side."""
    uid, token = host_session
    # Shrink the timeout for the test (faster than 30s, slower than the
    # scan's worker startup).
    monkeypatch.setattr(scan_handlers, "_WAIT_TIMEOUT_SECONDS", 0.2)
    gate = threading.Event()  # never set during this test — scan stays running
    daemon_ctx.pane_service = FakeScanService(block_until=gate)
    env = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"app_session_token": token, "wait": True},
        peer_uid=uid,
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "scan_timeout"
    assert "scan_id" in env["error"]["details"]
    # Scan still in flight server-side.
    record = scans.get_registry().lookup(env["error"]["details"]["scan_id"])
    assert record is not None
    assert record.state == "running"
    # Cleanup.
    gate.set()
    record.done.wait(timeout=2.0)


# ─── Failure path ────────────────────────────────────────────────────────


def test_scan_worker_exception_records_failed_state(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """If the underlying service.scan() raises, the registry records
    state=failed and the wait=true caller sees a completed envelope with
    state=failed and the error in result."""
    uid, token = host_session
    daemon_ctx.pane_service = FakeScanService(raise_exc=RuntimeError("docker down"))
    env = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"app_session_token": token, "wait": True},
        peer_uid=uid,
    )
    # The wait=true path returns success with state="failed" because the
    # contract distinguishes wait-timeout from scan-failure: a failed
    # scan IS a terminal result, not a wait failure.
    assert env["ok"] is True, env
    assert env["result"]["state"] == "failed"
    assert "docker down" in str(env["result"]["result"])


# ─── app.scan.status ─────────────────────────────────────────────────────


def test_scan_status_returns_terminal_record(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    daemon_ctx.pane_service = FakeScanService()
    panes_env = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"app_session_token": token, "wait": True},
        peer_uid=uid,
    )
    scan_id = panes_env["result"]["scan_id"]

    status = scan_handlers.app_scan_status(
        daemon_ctx,
        {"app_session_token": token, "scan_id": scan_id},
        peer_uid=uid,
    )
    assert status["ok"] is True, status
    result = status["result"]
    assert result["state"] == "completed"
    assert result["scan_kind"] == "panes"
    assert isinstance(result["started_at"], int)
    assert isinstance(result["completed_at"], int)
    assert result["result"] is not None


def test_scan_status_running_completed_at_and_result_are_null(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """FR-030c: while state==running, completed_at and result are null."""
    uid, token = host_session
    gate = threading.Event()
    daemon_ctx.pane_service = FakeScanService(block_until=gate)
    panes_env = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"app_session_token": token, "wait": False},
        peer_uid=uid,
    )
    scan_id = panes_env["result"]["scan_id"]

    status = scan_handlers.app_scan_status(
        daemon_ctx,
        {"app_session_token": token, "scan_id": scan_id},
        peer_uid=uid,
    )
    assert status["result"]["state"] == "running"
    assert status["result"]["completed_at"] is None
    assert status["result"]["result"] is None

    # Cleanup.
    gate.set()
    record = scans.get_registry().lookup(scan_id)
    if record is not None:
        record.done.wait(timeout=2.0)


def test_scan_status_unknown_scan_id_returns_scan_not_found(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = scan_handlers.app_scan_status(
        daemon_ctx,
        {"app_session_token": token, "scan_id": "deadbeef-no-such-scan"},
        peer_uid=uid,
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "scan_not_found"
    assert env["error"]["details"] == {"scan_id": "deadbeef-no-such-scan"}


def test_scan_status_missing_scan_id_returns_validation_failed(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    uid, token = host_session
    env = scan_handlers.app_scan_status(
        daemon_ctx,
        {"app_session_token": token},
        peer_uid=uid,
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "scan_id"


# ─── Unwired service ─────────────────────────────────────────────────────


def test_scan_panes_unwired_service_returns_internal_error(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """If DaemonContext.pane_service is None, the handler returns
    internal_error — production wiring is mandatory."""
    uid, token = host_session
    daemon_ctx.pane_service = None
    env = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"app_session_token": token, "wait": True},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


# ─── Dispatcher wiring ───────────────────────────────────────────────────


def test_scan_handlers_are_registered_in_dispatch() -> None:
    """T036/T037/T038: handlers reach the FEAT-002 dispatcher."""
    assert "app.scan.containers" in DISPATCH
    assert "app.scan.panes" in DISPATCH
    assert "app.scan.status" in DISPATCH
