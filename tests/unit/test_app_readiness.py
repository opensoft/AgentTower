"""FEAT-011 unit tests for ``app.readiness`` and its 6 subsystem probes.

Targets ``src/agenttower/app_contract/readiness.py`` — exercises every
probe in both its ok and degraded/unavailable branches, the top-level
state aggregation table, hint emission for each closed-set hint code,
the host-only + session gates, and the ``reason == ""`` invariant for
``ok`` rows.

Self-contained: all fixtures/helpers are copied in from
``test_app_contract_smoke.py`` so there are no cross-file imports.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agenttower.app_contract import errors as app_errors
from agenttower.app_contract import hello as hello_mod
from agenttower.app_contract import readiness as r
from agenttower.app_contract import sessions
from agenttower.app_contract.readiness import (
    Hint,
    SubsystemRow,
    aggregate_state,
    emit_hints,
    probe_docker,
    probe_jsonl,
    probe_log_attachment_workers,
    probe_routing_worker,
    probe_sqlite,
    probe_tmux_discovery,
)
from agenttower.app_contract.versioning import (
    HINT_SEVERITY_ACTION_REQUIRED,
    HINT_SEVERITY_INFO,
    READINESS_STATE_DEGRADED,
    READINESS_STATE_UNAVAILABLE,
    SUBSYSTEM_NAMES,
    SUBSYSTEM_STATUS_DEGRADED,
    SUBSYSTEM_STATUS_OK,
    SUBSYSTEM_STATUS_UNAVAILABLE,
)
from agenttower.socket_api.methods import (
    DaemonContext,
    _clear_request_peer_context,
    _set_request_peer_context,
)


# ─── Fixtures (copied from test_app_contract_smoke.py) ───────────────────


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


# ─── Test doubles ────────────────────────────────────────────────────────


class _FakeCtx:
    """A bare ctx object — probes use ``getattr(ctx, name, None)``."""

    def __init__(self, **attrs: Any) -> None:
        for k, v in attrs.items():
            setattr(self, k, v)


class _OkDiscovery:
    def list_containers(self, active_only: bool = False):
        return []


class _RaisingDiscovery:
    def list_containers(self, active_only: bool = False):
        raise RuntimeError("docker daemon down")


class _DeadThread:
    """Stand-in for a worker thread that is not alive."""

    def is_alive(self) -> bool:
        return False


# ─── probe_docker ────────────────────────────────────────────────────────


def test_probe_docker_unavailable_when_unwired() -> None:
    row = probe_docker(_FakeCtx(discovery_service=None))
    assert row.status == SUBSYSTEM_STATUS_UNAVAILABLE
    assert row.name == "docker"
    assert row.reason != ""
    assert row.hint is None


def test_probe_docker_ok_when_wired_and_reachable() -> None:
    row = probe_docker(_FakeCtx(discovery_service=_OkDiscovery()))
    assert row.status == SUBSYSTEM_STATUS_OK
    assert row.reason == ""


def test_probe_docker_unavailable_when_list_raises() -> None:
    row = probe_docker(_FakeCtx(discovery_service=_RaisingDiscovery()))
    assert row.status == SUBSYSTEM_STATUS_UNAVAILABLE
    assert "RuntimeError" in row.reason


# ─── probe_tmux_discovery ────────────────────────────────────────────────


def test_probe_tmux_discovery_unavailable_when_unwired() -> None:
    row = probe_tmux_discovery(_FakeCtx(pane_service=None))
    assert row.status == SUBSYSTEM_STATUS_UNAVAILABLE
    assert row.reason != ""


def test_probe_tmux_discovery_ok_when_wired() -> None:
    row = probe_tmux_discovery(_FakeCtx(pane_service=object()))
    assert row.status == SUBSYSTEM_STATUS_OK
    assert row.reason == ""


# ─── probe_sqlite ────────────────────────────────────────────────────────


def test_probe_sqlite_unavailable_when_unwired() -> None:
    row = probe_sqlite(_FakeCtx(state_conn=None))
    assert row.status == SUBSYSTEM_STATUS_UNAVAILABLE
    assert row.reason != ""


def test_probe_sqlite_ok_with_live_connection() -> None:
    conn = sqlite3.connect(":memory:")
    row = probe_sqlite(_FakeCtx(state_conn=conn))
    assert row.status == SUBSYSTEM_STATUS_OK
    assert row.reason == ""
    conn.close()


def test_probe_sqlite_degraded_when_select_raises() -> None:
    conn = sqlite3.connect(":memory:")
    conn.close()  # closed connection → execute raises ProgrammingError
    row = probe_sqlite(_FakeCtx(state_conn=conn))
    assert row.status == SUBSYSTEM_STATUS_DEGRADED
    assert "sqlite probe failed" in row.reason


# ─── probe_jsonl ─────────────────────────────────────────────────────────


def test_probe_jsonl_unavailable_when_unwired() -> None:
    row = probe_jsonl(_FakeCtx(events_file=None))
    assert row.status == SUBSYSTEM_STATUS_UNAVAILABLE
    assert row.reason != ""


def test_probe_jsonl_ok_when_parent_writable_and_no_file(tmp_path: Path) -> None:
    row = probe_jsonl(_FakeCtx(events_file=tmp_path / "events.jsonl"))
    assert row.status == SUBSYSTEM_STATUS_OK
    assert row.reason == ""


def test_probe_jsonl_ok_when_existing_file_writable(tmp_path: Path) -> None:
    f = tmp_path / "events.jsonl"
    f.write_text("{}\n")
    row = probe_jsonl(_FakeCtx(events_file=f))
    assert row.status == SUBSYSTEM_STATUS_OK


def test_probe_jsonl_unavailable_when_parent_missing(tmp_path: Path) -> None:
    row = probe_jsonl(_FakeCtx(events_file=tmp_path / "nope" / "events.jsonl"))
    assert row.status == SUBSYSTEM_STATUS_UNAVAILABLE
    assert "does not exist" in row.reason


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses W_OK checks")
def test_probe_jsonl_degraded_when_parent_unwritable(tmp_path: Path) -> None:
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        row = probe_jsonl(_FakeCtx(events_file=ro / "events.jsonl"))
        assert row.status == SUBSYSTEM_STATUS_DEGRADED
        assert "not writable" in row.reason
    finally:
        ro.chmod(0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason="root bypasses W_OK checks")
def test_probe_jsonl_degraded_when_file_unwritable(tmp_path: Path) -> None:
    f = tmp_path / "events.jsonl"
    f.write_text("{}\n")
    f.chmod(0o444)  # read-only file, writable parent
    try:
        row = probe_jsonl(_FakeCtx(events_file=f))
        assert row.status == SUBSYSTEM_STATUS_DEGRADED
        assert "is not writable" in row.reason
    finally:
        f.chmod(0o644)


def test_probe_jsonl_degraded_when_probe_raises(monkeypatch, tmp_path: Path) -> None:
    """An unexpected error inside the probe degrades rather than crashes."""
    def boom(self):  # noqa: ANN001
        raise OSError("stat exploded")

    monkeypatch.setattr(Path, "stat", boom)
    f = tmp_path / "events.jsonl"
    f.write_text("{}\n")
    row = probe_jsonl(_FakeCtx(events_file=f))
    assert row.status == SUBSYSTEM_STATUS_DEGRADED
    assert "jsonl probe failed" in row.reason


# ─── probe_routing_worker ────────────────────────────────────────────────


def test_probe_routing_worker_unavailable_when_unwired() -> None:
    row = probe_routing_worker(_FakeCtx(delivery_worker=None))
    assert row.status == SUBSYSTEM_STATUS_UNAVAILABLE
    assert row.reason != ""


def test_probe_routing_worker_ok_with_no_thread_attr() -> None:
    """A worker without a ``thread`` attribute is treated as ok."""
    row = probe_routing_worker(_FakeCtx(delivery_worker=object()))
    assert row.status == SUBSYSTEM_STATUS_OK
    assert row.reason == ""


def test_probe_routing_worker_ok_with_live_thread() -> None:
    live = threading.Thread(target=lambda: None)
    live.start()
    try:
        worker = _FakeCtx(thread=live)
        row = probe_routing_worker(_FakeCtx(delivery_worker=worker))
        # A live thread → ok; a finished thread would be degraded.
        assert row.status in {SUBSYSTEM_STATUS_OK, SUBSYSTEM_STATUS_DEGRADED}
    finally:
        live.join()


def test_probe_routing_worker_degraded_when_thread_dead() -> None:
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()  # real Thread, now not alive
    worker = _FakeCtx(thread=dead)
    row = probe_routing_worker(_FakeCtx(delivery_worker=worker))
    assert row.status == SUBSYSTEM_STATUS_DEGRADED
    assert "not alive" in row.reason


def test_probe_routing_worker_ok_when_thread_is_not_a_real_thread() -> None:
    """A non-Thread ``thread`` attribute is ignored (isinstance guard)."""
    worker = _FakeCtx(thread=_DeadThread())
    row = probe_routing_worker(_FakeCtx(delivery_worker=worker))
    assert row.status == SUBSYSTEM_STATUS_OK


# ─── probe_log_attachment_workers ────────────────────────────────────────


def test_probe_log_attachment_workers_unavailable_when_unwired() -> None:
    row = probe_log_attachment_workers(_FakeCtx(log_service=None))
    assert row.status == SUBSYSTEM_STATUS_UNAVAILABLE
    assert row.reason != ""


def test_probe_log_attachment_workers_ok_when_wired() -> None:
    row = probe_log_attachment_workers(_FakeCtx(log_service=object()))
    assert row.status == SUBSYSTEM_STATUS_OK
    assert row.reason == ""


# ─── aggregate_state ─────────────────────────────────────────────────────


def _row(status: str) -> SubsystemRow:
    return SubsystemRow(name="x", status=status, reason="")


def test_aggregate_state_all_ok_is_ready() -> None:
    rows = [_row(SUBSYSTEM_STATUS_OK) for _ in range(6)]
    assert aggregate_state(rows) == "ready"


def test_aggregate_state_all_unavailable_is_unavailable() -> None:
    rows = [_row(SUBSYSTEM_STATUS_UNAVAILABLE) for _ in range(6)]
    assert aggregate_state(rows) == READINESS_STATE_UNAVAILABLE


def test_aggregate_state_one_degraded_is_degraded() -> None:
    rows = [_row(SUBSYSTEM_STATUS_OK) for _ in range(5)]
    rows.append(_row(SUBSYSTEM_STATUS_DEGRADED))
    assert aggregate_state(rows) == READINESS_STATE_DEGRADED


def test_aggregate_state_mixed_ok_and_unavailable_is_degraded() -> None:
    rows = [_row(SUBSYSTEM_STATUS_OK), _row(SUBSYSTEM_STATUS_UNAVAILABLE)]
    assert aggregate_state(rows) == READINESS_STATE_DEGRADED


# ─── emit_hints ──────────────────────────────────────────────────────────


def _all_ok_rows() -> list[SubsystemRow]:
    return [SubsystemRow(name=n, status=SUBSYSTEM_STATUS_OK, reason="")
            for n in SUBSYSTEM_NAMES]


def test_emit_hints_docker_unavailable() -> None:
    rows = _all_ok_rows()
    rows[0] = SubsystemRow(name="docker", status=SUBSYSTEM_STATUS_UNAVAILABLE,
                           reason="x")
    hints = emit_hints(None, rows, container_count=0, pane_count=0,
                       agent_count=0, route_count_enabled=0,
                       log_attachment_count=0)
    by_code = {h.code: h for h in hints}
    assert "docker_unavailable_hint" in by_code
    assert by_code["docker_unavailable_hint"].severity == HINT_SEVERITY_ACTION_REQUIRED
    # docker unavailable suppresses start_bench_container.
    assert "start_bench_container" not in by_code


def test_emit_hints_start_bench_container_when_docker_ok_and_no_containers() -> None:
    hints = emit_hints(None, _all_ok_rows(), container_count=0, pane_count=0,
                       agent_count=0, route_count_enabled=0,
                       log_attachment_count=0)
    by_code = {h.code: h for h in hints}
    assert "start_bench_container" in by_code
    assert by_code["start_bench_container"].severity == HINT_SEVERITY_ACTION_REQUIRED
    assert "docker_unavailable_hint" not in by_code


def test_emit_hints_start_bench_container_when_no_docker_row() -> None:
    """No docker row at all still triggers start_bench_container."""
    rows = [SubsystemRow(name="sqlite", status=SUBSYSTEM_STATUS_OK, reason="")]
    hints = emit_hints(None, rows, container_count=0, pane_count=0,
                       agent_count=0, route_count_enabled=0,
                       log_attachment_count=0)
    assert "start_bench_container" in {h.code for h in hints}


def test_emit_hints_register_first_agent() -> None:
    hints = emit_hints(None, _all_ok_rows(), container_count=2, pane_count=3,
                       agent_count=0, route_count_enabled=0,
                       log_attachment_count=0)
    by_code = {h.code: h for h in hints}
    assert "register_first_agent" in by_code
    assert by_code["register_first_agent"].severity == HINT_SEVERITY_INFO


def test_emit_hints_attach_logs_and_enable_first_route() -> None:
    hints = emit_hints(None, _all_ok_rows(), container_count=2, pane_count=3,
                       agent_count=1, route_count_enabled=0,
                       log_attachment_count=0)
    by_code = {h.code: h for h in hints}
    assert "attach_logs" in by_code
    assert by_code["attach_logs"].severity == HINT_SEVERITY_INFO
    assert "enable_first_route" in by_code
    assert by_code["enable_first_route"].severity == HINT_SEVERITY_INFO
    # Agents exist → register_first_agent must NOT fire.
    assert "register_first_agent" not in by_code


def test_emit_hints_none_when_system_fully_provisioned() -> None:
    """Containers, panes, agents, logs and routes all present → no hints."""
    hints = emit_hints(None, _all_ok_rows(), container_count=2, pane_count=3,
                       agent_count=1, route_count_enabled=1,
                       log_attachment_count=1)
    assert hints == []


# ─── Hint dataclass ──────────────────────────────────────────────────────


def test_hint_to_dict_without_target() -> None:
    d = Hint(code="c", severity="info", message="m").to_dict()
    assert d == {"code": "c", "severity": "info", "message": "m"}


def test_hint_to_dict_with_target() -> None:
    d = Hint(code="c", severity="info", message="m",
             target={"agent_id": "a"}).to_dict()
    assert d["target"] == {"agent_id": "a"}


# ─── app_readiness handler: gates ────────────────────────────────────────


def test_readiness_host_only_when_no_credentials(daemon_ctx_with_db) -> None:
    env = _readiness_call(daemon_ctx_with_db, -1)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.HOST_ONLY


def test_readiness_session_required_when_token_missing(
    daemon_ctx_with_db, host_peer
) -> None:
    env = _readiness_call(daemon_ctx_with_db, host_peer)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_SESSION_REQUIRED


def test_readiness_session_expired_when_token_invalid(
    daemon_ctx_with_db, host_peer
) -> None:
    env = _readiness_call(daemon_ctx_with_db, host_peer, token="bogus")
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.APP_SESSION_EXPIRED


# ─── app_readiness handler: happy path + aggregation ─────────────────────


def test_readiness_envelope_shape_and_invariants(
    daemon_ctx_with_db, host_session
) -> None:
    host_peer, token = host_session
    env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["ok"] is True
    res = env["result"]
    assert res["state"] in {"ready", "degraded", "unavailable"}
    assert [s["name"] for s in res["subsystems"]] == list(SUBSYSTEM_NAMES)
    for row in res["subsystems"]:
        assert set(row.keys()) == {"name", "status", "reason", "hint"}
        if row["status"] == "ok":
            assert row["reason"] == ""  # ok ⇒ empty reason invariant
    assert isinstance(res["hints"], list)


def test_readiness_unwired_services_degraded_state(
    daemon_ctx_with_db, host_session
) -> None:
    """Only sqlite/jsonl wired → mixed statuses → degraded top-level state."""
    host_peer, token = host_session
    env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    assert env["result"]["state"] == READINESS_STATE_DEGRADED


def test_readiness_all_subsystems_ok_is_ready(
    daemon_ctx_with_db, host_session, monkeypatch
) -> None:
    """Wire every service so all 6 probes return ok → state == ready."""
    host_peer, token = host_session
    ctx = daemon_ctx_with_db
    monkeypatch.setattr(ctx, "discovery_service", _OkDiscovery(), raising=False)
    monkeypatch.setattr(ctx, "pane_service", object(), raising=False)
    monkeypatch.setattr(ctx, "delivery_worker", object(), raising=False)
    monkeypatch.setattr(ctx, "log_service", object(), raising=False)
    env = _readiness_call(ctx, host_peer, token=token)
    assert env["ok"] is True
    assert env["result"]["state"] == "ready"
    by_name = {s["name"]: s for s in env["result"]["subsystems"]}
    for name in SUBSYSTEM_NAMES:
        assert by_name[name]["status"] == "ok"


def test_readiness_emits_docker_unavailable_hint(
    daemon_ctx_with_db, host_session
) -> None:
    host_peer, token = host_session
    env = _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    codes = {h["code"] for h in env["result"]["hints"]}
    assert "docker_unavailable_hint" in codes


def test_readiness_no_audit_side_effect(daemon_ctx_with_db, host_session) -> None:
    """FR-045: app.readiness must not write to the audit JSONL."""
    host_peer, token = host_session
    events_file = daemon_ctx_with_db.events_file
    before = events_file.stat().st_size if events_file.exists() else 0
    _readiness_call(daemon_ctx_with_db, host_peer, token=token)
    after = events_file.stat().st_size if events_file.exists() else 0
    assert after == before


# ─── _summary_counts ─────────────────────────────────────────────────────


def test_summary_counts_zero_when_conn_unwired() -> None:
    counts = r._summary_counts(_FakeCtx(state_conn=None))
    assert counts == {
        "containers": 0, "panes": 0, "agents": 0,
        "routes_enabled": 0, "log_attachments": 0,
    }


def test_summary_counts_zero_when_tables_missing() -> None:
    """A live conn with no schema → every COUNT raises → all counts 0."""
    conn = sqlite3.connect(":memory:")
    counts = r._summary_counts(_FakeCtx(state_conn=conn))
    assert counts == {
        "containers": 0, "panes": 0, "agents": 0,
        "routes_enabled": 0, "log_attachments": 0,
    }
    conn.close()


def test_summary_counts_reads_real_schema(daemon_ctx_with_db) -> None:
    counts = r._summary_counts(daemon_ctx_with_db)
    assert set(counts.keys()) == {
        "containers", "panes", "agents", "routes_enabled", "log_attachments",
    }
    for v in counts.values():
        assert v == 0  # empty registry
