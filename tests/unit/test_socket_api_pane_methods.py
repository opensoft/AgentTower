"""Unit tests for FEAT-004 socket method handlers (T019 / FR-013 / FR-016)."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agenttower.socket_api import errors
from agenttower.socket_api.methods import DISPATCH, DaemonContext


class _FakePaneService:
    def __init__(self, *, list_rows: list[Any] | None = None) -> None:
        self.scan_called = 0
        self.list_called = 0
        self._list_rows = list_rows or []
        self._mutex = threading.Lock()

    def scan(self) -> Any:
        from agenttower.discovery.pane_service import PaneScanResult

        with self._mutex:
            self.scan_called += 1
            return PaneScanResult(
                scan_id="abc",
                started_at="2026-05-06T10:00:00.000000+00:00",
                completed_at="2026-05-06T10:00:00.500000+00:00",
                status="ok",
                containers_scanned=1,
                sockets_scanned=1,
                panes_seen=1,
                panes_newly_active=1,
                panes_reconciled_inactive=0,
                containers_skipped_inactive=0,
                containers_tmux_unavailable=0,
                error_code=None,
                error_message=None,
            )

    def list_panes(self, *, active_only: bool = False, container_filter: str | None = None) -> list[Any]:
        self.list_called += 1
        return list(self._list_rows)

    @property
    def scan_mutex(self) -> threading.Lock:
        return self._mutex


def _ctx(
    tmp_path: Path,
    *,
    pane_service: _FakePaneService | None = None,
) -> DaemonContext:
    return DaemonContext(
        pid=1,
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "sock",
        state_path=tmp_path,
        daemon_version="0.0.1",
        schema_version=3,
        pane_service=pane_service,
    )


def test_scan_panes_returns_ok_envelope_with_alias_renamed(tmp_path: Path) -> None:
    service = _FakePaneService()
    response = DISPATCH["scan_panes"](_ctx(tmp_path, pane_service=service), {})
    assert response["ok"] is True
    result = response["result"]
    # Alias rename per data-model §6 note 5.
    assert "panes_reconciled_to_inactive" in result
    assert "panes_reconciled_inactive" not in result
    assert result["panes_reconciled_to_inactive"] == 0
    assert service.scan_called == 1


def test_list_panes_returns_empty_payload_when_no_rows(tmp_path: Path) -> None:
    service = _FakePaneService(list_rows=[])
    response = DISPATCH["list_panes"](_ctx(tmp_path, pane_service=service), {})
    assert response["ok"] is True
    assert response["result"] == {
        "filter": "all",
        "container_filter": None,
        "panes": [],
    }


def test_list_panes_rejects_non_bool_active_only(tmp_path: Path) -> None:
    service = _FakePaneService()
    response = DISPATCH["list_panes"](
        _ctx(tmp_path, pane_service=service), {"active_only": "yes"}
    )
    assert response["ok"] is False
    assert response["error"]["code"] == errors.BAD_REQUEST


def test_list_panes_rejects_non_string_container_filter(tmp_path: Path) -> None:
    service = _FakePaneService()
    response = DISPATCH["list_panes"](
        _ctx(tmp_path, pane_service=service), {"container": 123}
    )
    assert response["ok"] is False
    assert response["error"]["code"] == errors.BAD_REQUEST


def test_scan_panes_returns_internal_error_when_service_missing(tmp_path: Path) -> None:
    response = DISPATCH["scan_panes"](_ctx(tmp_path, pane_service=None), {})
    assert response["ok"] is False
    assert response["error"]["code"] == errors.INTERNAL_ERROR


def test_list_panes_does_not_acquire_pane_scan_mutex(tmp_path: Path) -> None:
    """FR-016 — list_panes MUST NOT block on the pane-scan mutex."""
    service = _FakePaneService()

    # Hold the mutex on a background thread and confirm list_panes returns
    # immediately rather than waiting.
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with service.scan_mutex:
            held.set()
            release.wait(timeout=2.0)

    t = threading.Thread(target=hold, daemon=True)
    t.start()
    assert held.wait(timeout=1.0)
    t0 = time.monotonic()
    response = DISPATCH["list_panes"](_ctx(tmp_path, pane_service=service), {})
    elapsed = time.monotonic() - t0
    release.set()
    t.join(timeout=2.0)
    assert response["ok"] is True
    assert elapsed < 0.5, f"list_panes blocked on mutex for {elapsed:.2f}s"
