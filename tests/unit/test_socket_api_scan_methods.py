"""In-process tests for FEAT-003 socket method handlers.

These tests bypass the real `AF_UNIX` server and call the dispatch
table directly. They exercise the JSON envelope shape and the
FR-042 SQLite-failure rollback path.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import agenttower.discovery.service as service_module
from agenttower.discovery.matching import MatchingRule, default_rule
from agenttower.discovery.service import DiscoveryService
from agenttower.docker.adapter import (
    ContainerSummary,
    InspectResult,
    Mount,
    PerContainerError,
)
from agenttower.docker.fakes import FakeDockerAdapter
from agenttower.socket_api import errors
from agenttower.socket_api.methods import (
    DISPATCH,
    DaemonContext,
)
from agenttower.state import schema as state_schema


def _seed_v1(state_db: Path) -> None:
    state_db.parent.mkdir(mode=0o700, exist_ok=True)
    conn = sqlite3.connect(str(state_db), isolation_level=None)
    try:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
    finally:
        conn.close()
    os.chmod(state_db, 0o600)


def _build_ctx(
    tmp_path: Path, *, fake_script: dict[str, Any], events_file: Path | None = None
) -> DaemonContext:
    state_db = tmp_path / "state" / "agenttower.sqlite3"
    _seed_v1(state_db)
    conn, _ = state_schema.open_registry(state_db, namespace_root=state_db.parent)

    adapter = FakeDockerAdapter(fake_script)
    service = DiscoveryService(
        connection=conn,
        adapter=adapter,
        rule_provider=default_rule,
        events_file=events_file,
        lifecycle_logger=None,
    )
    return DaemonContext(
        pid=12345,
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "agenttowerd.sock",
        state_path=tmp_path,
        daemon_version="0.0.0-test",
        schema_version=2,
        shutdown_requested=threading.Event(),
        discovery_service=service,
        events_file=None,
        lifecycle_logger=None,
    )


def test_scan_containers_envelope_shape(tmp_path: Path) -> None:
    script = {
        "list_running": {
            "action": "ok",
            "containers": [
                {"container_id": "abc", "name": "py-bench", "image": "img", "status": "running"},
                {"container_id": "def", "name": "redis", "image": "redis", "status": "running"},
            ],
        },
        "inspect": {
            "action": "ok",
            "results": [
                {"container_id": "abc", "name": "py-bench", "image": "img", "status": "running"},
            ],
        },
    }
    ctx = _build_ctx(tmp_path, fake_script=script)
    response = DISPATCH["scan_containers"](ctx, {})
    assert response["ok"] is True
    result = response["result"]
    assert result["status"] == "ok"
    assert result["matched_count"] == 1
    assert result["ignored_count"] == 1
    assert result["inactive_reconciled_count"] == 0
    assert result["error_code"] is None
    assert result["error_details"] == []


def test_list_containers_default_returns_all(tmp_path: Path) -> None:
    script = {
        "list_running": {
            "action": "ok",
            "containers": [
                {"container_id": "abc", "name": "py-bench"},
            ],
        },
        "inspect": {
            "action": "ok",
            "results": [{"container_id": "abc", "name": "py-bench", "image": "img", "status": "running"}],
        },
    }
    ctx = _build_ctx(tmp_path, fake_script=script)
    DISPATCH["scan_containers"](ctx, {})
    response = DISPATCH["list_containers"](ctx, {})
    assert response["ok"] is True
    assert response["result"]["filter"] == "all"
    assert len(response["result"]["containers"]) == 1
    assert response["result"]["containers"][0]["id"] == "abc"
    assert response["result"]["containers"][0]["active"] is True


def test_list_containers_active_only_filters(tmp_path: Path) -> None:
    script_a = {
        "list_running": {"action": "ok", "containers": [{"container_id": "abc", "name": "py-bench"}]},
        "inspect": {"action": "ok", "results": [{"container_id": "abc", "name": "py-bench", "image": "i", "status": "running"}]},
    }
    ctx = _build_ctx(tmp_path, fake_script=script_a)
    DISPATCH["scan_containers"](ctx, {})

    # Now scan with the container gone → previous row is reconciled inactive.
    ctx.discovery_service._adapter = FakeDockerAdapter(
        {"list_running": {"action": "ok", "containers": []}, "inspect": {"action": "ok", "results": []}}
    )
    DISPATCH["scan_containers"](ctx, {})

    all_resp = DISPATCH["list_containers"](ctx, {})
    assert len(all_resp["result"]["containers"]) == 1
    active_resp = DISPATCH["list_containers"](ctx, {"active_only": True})
    assert active_resp["result"]["filter"] == "active_only"
    assert active_resp["result"]["containers"] == []


def test_list_containers_rejects_non_bool_active_only(tmp_path: Path) -> None:
    ctx = _build_ctx(tmp_path, fake_script={"list_running": {"action": "ok", "containers": []}, "inspect": {"action": "ok"}})
    response = DISPATCH["list_containers"](ctx, {"active_only": "yes"})
    assert response["ok"] is False
    assert response["error"]["code"] == errors.BAD_REQUEST


def test_scan_containers_ignores_unknown_params(tmp_path: Path) -> None:
    ctx = _build_ctx(
        tmp_path,
        fake_script={"list_running": {"action": "ok", "containers": []}, "inspect": {"action": "ok"}},
    )
    response = DISPATCH["scan_containers"](ctx, {"active_only": True})
    assert response["ok"] is True


def test_list_containers_ignores_unknown_param(tmp_path: Path) -> None:
    ctx = _build_ctx(
        tmp_path,
        fake_script={"list_running": {"action": "ok", "containers": []}, "inspect": {"action": "ok"}},
    )
    response = DISPATCH["list_containers"](ctx, {"limit": 1})
    assert response["ok"] is True


def test_scan_sqlite_failure_rolls_back_and_releases_mutex(tmp_path: Path, monkeypatch) -> None:
    """FR-042: a SQLite write failure rolls back, no JSONL, mutex released, daemon alive."""
    script = {
        "list_running": {
            "action": "ok",
            "containers": [{"container_id": "abc", "name": "py-bench"}],
        },
        "inspect": {
            "action": "ok",
            "results": [{"container_id": "abc", "name": "py-bench", "image": "img", "status": "running"}],
        },
    }
    ctx = _build_ctx(tmp_path, fake_script=script)
    service = ctx.discovery_service
    assert service is not None

    from agenttower.state import containers as state_containers

    real_upsert = state_containers.upsert_container

    def boom(*a, **kw):  # noqa: ANN001, ANN201
        raise sqlite3.OperationalError("boom")

    monkeypatch.setattr(state_containers, "upsert_container", boom)
    response = DISPATCH["scan_containers"](ctx, {})
    monkeypatch.setattr(state_containers, "upsert_container", real_upsert)

    # Mutex must be released (non-blocking acquire returns True).
    acquired = service.scan_mutex.acquire(blocking=False)
    assert acquired is True
    service.scan_mutex.release()

    # Daemon stays alive: ping/status still work.
    assert response["ok"] is False
    assert response["error"]["code"] == errors.INTERNAL_ERROR

    ping_response = DISPATCH["ping"](ctx, {})
    status_response = DISPATCH["status"](ctx, {})
    assert ping_response["ok"] is True
    assert status_response["ok"] is True

    # No container_scans row was committed for the failed scan.
    rows = service._conn.execute("SELECT scan_id FROM container_scans").fetchall()
    assert rows == []


def test_jsonl_failure_after_commit_returns_internal_error_and_keeps_scan_row(
    tmp_path: Path, monkeypatch
) -> None:
    """FR-043: JSONL failure is surfaced after the DB row is committed."""
    script = {
        "list_running": {
            "action": "ok",
            "containers": [{"container_id": "abc", "name": "py-bench"}],
        },
        "inspect": {
            "action": "ok",
            "results": [],
            "per_container_errors": {
                "abc": {"code": "docker_failed", "message": "fake inspect failed"}
            },
        },
    }
    ctx = _build_ctx(tmp_path, fake_script=script, events_file=tmp_path / "events.jsonl")
    service = ctx.discovery_service
    assert service is not None

    def boom(*_args, **_kwargs):  # noqa: ANN202
        raise OSError("disk full")

    monkeypatch.setattr(service_module.events_writer, "append_event", boom)
    response = DISPATCH["scan_containers"](ctx, {})
    assert response["ok"] is False
    assert response["error"]["code"] == errors.INTERNAL_ERROR

    rows = service._conn.execute(
        "SELECT status, error_code FROM container_scans"
    ).fetchall()
    assert rows == [("degraded", "docker_failed")]


def test_ordered_error_details_preserves_unmatched_failures() -> None:
    failures = [
        PerContainerError("extra", "docker_malformed", "malformed inspect entry"),
        PerContainerError("abc", "docker_failed", "inspect failed"),
    ]
    ordered = service_module._ordered_error_details(failures, ["abc"])
    assert [failure.container_id for failure in ordered] == ["abc", "extra"]
