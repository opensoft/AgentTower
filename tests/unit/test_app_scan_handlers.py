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


# ─── wait param validation ───────────────────────────────────────────────


def test_scan_wait_non_bool_returns_validation_failed(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """``wait`` is a strict boolean; a string ("false") is rejected rather
    than coerced via bool() (which would surprise callers)."""
    uid, token = host_session
    daemon_ctx.pane_service = FakeScanService()
    env = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"app_session_token": token, "wait": "false"},
        peer_uid=uid,
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"] == {"field": "wait", "reason": "wrong type"}


def test_scan_panes_missing_token_returns_session_required(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """_scan_dispatch is session-gated: no token → gate failure envelope."""
    daemon_ctx.pane_service = FakeScanService()
    env = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"wait": True},
        peer_uid=host_peer,
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "app_session_required"


def test_scan_containers_unwired_service_returns_internal_error(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """app.scan.containers with discovery_service unwired → internal_error."""
    uid, token = host_session
    # discovery_service attribute absent entirely on the context.
    env = scan_handlers.app_scan_containers(
        daemon_ctx,
        {"app_session_token": token, "wait": True},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "internal_error"


# ─── Session gate on app.scan.status ─────────────────────────────────────


def test_scan_status_missing_token_returns_session_required(
    daemon_ctx: DaemonContext, host_peer: int
) -> None:
    """app.scan.status is session-gated: no token → app_session_required."""
    env = scan_handlers.app_scan_status(
        daemon_ctx,
        {"scan_id": "anything"},
        peer_uid=host_peer,
    )
    assert env["ok"] is False, env
    assert env["error"]["code"] == "app_session_required"


def test_scan_status_non_dict_params_returns_validation_failed(
    daemon_ctx: DaemonContext, host_session: tuple[int, str]
) -> None:
    """scan_id resolves to None when params is not a dict — but the gate
    runs first; a non-dict params with a gated handler yields the gate
    failure. Here we exercise the scan_id None branch via an explicit
    None scan_id value."""
    uid, token = host_session
    env = scan_handlers.app_scan_status(
        daemon_ctx,
        {"app_session_token": token, "scan_id": None},
        peer_uid=uid,
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "validation_failed"
    assert env["error"]["details"]["field"] == "scan_id"


# ─── wait=true: record evicted between wait and lookup ───────────────────


def test_wait_true_record_evicted_between_wait_and_lookup(
    daemon_ctx: DaemonContext,
    host_session: tuple[int, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the registry evicts the just-completed record between the
    done.wait() and the lookup(), the handler returns internal_error
    rather than scan_not_found (the caller observed the scan complete)."""
    uid, token = host_session
    daemon_ctx.pane_service = FakeScanService()

    registry = scans.get_registry()
    real_lookup = registry.lookup

    def _lookup_returns_none(scan_id: str):
        # Simulate the record vanishing right after wait() succeeds.
        return None

    monkeypatch.setattr(registry, "lookup", _lookup_returns_none)
    env = scan_handlers.app_scan_panes(
        daemon_ctx,
        {"app_session_token": token, "wait": True},
        peer_uid=uid,
    )
    monkeypatch.setattr(registry, "lookup", real_lookup)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "internal_error"
    assert "evicted between wait and lookup" in env["error"]["message"]


# ─── _result_to_dict / _coerce_to_jsonable helper branches ───────────────


def test_result_to_dict_none_returns_empty_dict() -> None:
    assert scan_handlers._result_to_dict(None) == {}


def test_result_to_dict_plain_dict_passes_through() -> None:
    out = scan_handlers._result_to_dict({"matched_count": 5, "status": "ok"})
    assert out == {"matched_count": 5, "status": "ok"}


def test_result_to_dict_plain_object_attribute_scrape() -> None:
    """A plain (non-dataclass, non-dict) object → best-effort attribute
    scrape skipping private + callable members."""

    class _PlainResult:
        def __init__(self) -> None:
            self.matched = 7
            self.kind = "panes"
            self._private = "hidden"

        def method(self) -> None:  # callable — must be skipped
            pass

    out = scan_handlers._result_to_dict(_PlainResult())
    assert out["matched"] == 7
    assert out["kind"] == "panes"
    assert "_private" not in out
    assert "method" not in out


def test_result_to_dict_dataclass_is_coerced() -> None:
    out = scan_handlers._result_to_dict(
        FakeScanResult(scan_id="s1", status="ok", matched_count=2)
    )
    assert out == {"scan_id": "s1", "status": "ok", "matched_count": 2}


def test_coerce_to_jsonable_tuple_becomes_list() -> None:
    assert scan_handlers._coerce_to_jsonable((1, 2, 3)) == [1, 2, 3]


def test_coerce_to_jsonable_nested_structures() -> None:
    nested = {"items": (FakeScanResult("s", "ok", 1),), "n": 4, "flag": True}
    out = scan_handlers._coerce_to_jsonable(nested)
    assert out["n"] == 4
    assert out["flag"] is True
    assert out["items"] == [{"scan_id": "s", "status": "ok", "matched_count": 1}]


def test_coerce_to_jsonable_unknown_type_stringified() -> None:
    """A value that is none of None/str/num/bool/dict/list/dataclass falls
    through to str()."""

    class _Opaque:
        def __str__(self) -> str:
            return "opaque-repr"

    assert scan_handlers._coerce_to_jsonable(_Opaque()) == "opaque-repr"


# ─── Dispatcher wiring ───────────────────────────────────────────────────


def test_scan_handlers_are_registered_in_dispatch() -> None:
    """T036/T037/T038: handlers reach the FEAT-002 dispatcher."""
    assert "app.scan.containers" in DISPATCH
    assert "app.scan.panes" in DISPATCH
    assert "app.scan.status" in DISPATCH
