"""FEAT-013 Phase 3c dispatcher / handler contract test (T023 / T024 / T025).

Exercises the wire-shape surface for ``managed.layout.create`` (legacy
CLI handler) and ``app.managed_layout_create`` (FEAT-011 host-only
handler), plus the dispatcher registration that lets the FEAT-002 socket
server reach them.

Scoped to behaviors the synchronous service exposes today:

* Dispatcher registration sanity — both namespaces install all 5
  methods (create + list + detail + pane.list + pane.detail) at module-
  import time.
* Required-field validation (``container_id`` / ``template_name`` /
  ``tmux_session_name``) → ``validation_failed``.
* ``container_not_found`` pre-check when the FEAT-003 ``containers``
  registry has no row.
* Happy-path layout creation through both namespaces.
* FEAT-013 closed-set error translation (``managed_template_not_found``
  → both namespaces).

Behaviors that need the background spawn pipeline (Phase 4 T029/T030)
remain skip-marked in ``test_managed_layout_create.py``.
"""

from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest

from agenttower.app_contract.dispatcher import APP_DISPATCH
from agenttower.managed_sessions.errors import (
    CONTAINER_NOT_FOUND,
    MANAGED_TEMPLATE_NOT_FOUND,
)
from agenttower.managed_sessions.handlers.app import (
    app_managed_layout_create,
)
from agenttower.managed_sessions.handlers.cli import register as cli_register
from agenttower.managed_sessions.serializer import ContainerSerializer
from agenttower.socket_api.methods import DISPATCH
from agenttower.state.schema import _apply_migration_v9


# ─── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """Fresh in-memory SQLite with the minimum tables FEAT-013 reads:
    a stub ``agents`` (FEAT-006 FK target), a ``containers`` row to make
    the container_not_found pre-check pass, and the FEAT-013 v9 schema.
    """
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE agents (agent_id TEXT PRIMARY KEY)")
    c.execute(
        "CREATE TABLE containers ("
        "  container_id TEXT PRIMARY KEY,"
        "  active INTEGER NOT NULL DEFAULT 1"
        ")"
    )
    c.execute(
        "INSERT INTO containers (container_id, active) VALUES (?, 1)",
        ("bench-alpha",),
    )
    _apply_migration_v9(c)
    c.commit()
    return c


@pytest.fixture()
def ctx(conn: sqlite3.Connection) -> Any:
    """Minimum daemon context the FEAT-013 handlers reach for.

    ``SimpleNamespace`` is enough because the handlers only ``getattr``
    fields; they don't construct a full ``DaemonContext``.
    """
    return SimpleNamespace(
        state_conn=conn,
        managed_serializer=ContainerSerializer(),
    )


# Pretend-host peer_uid: any non-negative int that's not ``_NO_PEER_UID``.
HOST_PEER_UID = 1000


@pytest.fixture(autouse=True)
def force_host_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    """FEAT-002's :func:`_peer_is_host_process` falls back to ``False`` for
    any unknown / sentinel pid, which makes the host-only gate refuse all
    in-process test calls. The integration-test harness uses the
    ``AGENTTOWER_TEST_FORCE_HOST_PEER=1`` env-var seam already documented
    in :func:`socket_api.methods._peer_is_host_process` — we set it here
    so the FEAT-011 + FEAT-013 host-only gates classify these test calls
    as host peers.

    We also seed the request-peer threadlocal with a non-zero pid so the
    primary FEAT-009 peer-detection short-circuit (``pid <= 0 → host``
    in our managed_sessions handler) doesn't bypass the env-var seam.
    """
    monkeypatch.setenv("AGENTTOWER_TEST_FORCE_HOST_PEER", "1")
    from agenttower.socket_api.methods import _set_request_peer_context, _clear_request_peer_context

    _set_request_peer_context(peer_pid=os.getpid())
    yield
    _clear_request_peer_context()


# ─── Dispatcher registration sanity (T025) ───────────────────────────────


def test_legacy_managed_methods_registered() -> None:
    """T025: all 5 ``managed.*`` methods reachable through FEAT-002 DISPATCH."""
    expected = {
        "managed.layout.create",
        "managed.layout.list",
        "managed.layout.detail",
        "managed.pane.list",
        "managed.pane.detail",
    }
    assert expected.issubset(DISPATCH.keys())


def test_app_managed_methods_registered() -> None:
    """T025: all 5 ``app.managed_*`` methods reachable through FEAT-011 APP_DISPATCH."""
    expected = {
        "app.managed_layout_create",
        "app.managed_layout_list",
        "app.managed_layout_detail",
        "app.managed_pane_list",
        "app.managed_pane_detail",
    }
    assert expected.issubset(APP_DISPATCH.keys())


def test_cli_register_returns_five_methods() -> None:
    """T025: ``cli.register()`` returns the closed 5-method mapping."""
    mapping = cli_register()
    assert set(mapping.keys()) == {
        "managed.layout.create",
        "managed.layout.list",
        "managed.layout.detail",
        "managed.pane.list",
        "managed.pane.detail",
    }


# ─── legacy CLI handler (T023) ──────────────────────────────────────────


def _legacy_create(ctx: Any, **params: Any) -> dict[str, Any]:
    """Invoke ``managed.layout.create`` through the dispatcher."""
    return DISPATCH["managed.layout.create"](ctx, params, HOST_PEER_UID)


def test_legacy_create_missing_container_id_fails_validation(ctx: Any) -> None:
    resp = _legacy_create(
        ctx,
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "validation_failed"
    assert resp["error"]["details"]["field"] == "container_id"


def test_legacy_create_unknown_container_returns_container_not_found(
    ctx: Any,
) -> None:
    resp = _legacy_create(
        ctx,
        container_id="bench-unknown",
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == CONTAINER_NOT_FOUND
    assert resp["error"]["details"] == {"container_id": "bench-unknown"}


def test_legacy_create_happy_path_returns_creating_state(ctx: Any) -> None:
    resp = _legacy_create(
        ctx,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is True
    result = resp["result"]
    assert result["state"] == "creating"
    assert result["intended_pane_count"] == 3
    assert len(result["panes"]) == 3
    assert [p["role"] for p in result["panes"]] == ["master", "slave", "slave"]
    assert [p["label"] for p in result["panes"]] == ["m1", "s1", "s2"]
    assert all(p["state"] == "creating" for p in result["panes"])
    assert result["replay"] is False


def test_legacy_create_unknown_template_returns_closed_set_code(ctx: Any) -> None:
    resp = _legacy_create(
        ctx,
        container_id="bench-alpha",
        template_name="not-a-real-template",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == MANAGED_TEMPLATE_NOT_FOUND


# ─── FEAT-011 app handler (T024) ────────────────────────────────────────


def _app_create(ctx: Any, **params: Any) -> dict[str, Any]:
    """Invoke ``app.managed_layout_create`` directly.

    Bypasses the dispatcher's ``_wrap_handler`` because that wrapper
    only adds a safety-net for unhandled exceptions; the handler's own
    envelope is what we want to assert.
    """
    return app_managed_layout_create(ctx, params, HOST_PEER_UID)


def test_app_create_missing_container_id_fails_validation(ctx: Any) -> None:
    resp = _app_create(
        ctx,
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is False
    assert resp["app_contract_version"] == "1.0"
    assert resp["error"]["code"] == "validation_failed"
    assert resp["error"]["details"]["field"] == "container_id"


def test_app_create_unknown_container_returns_container_not_found(
    ctx: Any,
) -> None:
    resp = _app_create(
        ctx,
        container_id="bench-unknown",
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is False
    assert resp["app_contract_version"] == "1.0"
    assert resp["error"]["code"] == CONTAINER_NOT_FOUND
    assert resp["error"]["details"] == {"container_id": "bench-unknown"}


def test_app_create_happy_path_returns_feat011_envelope(ctx: Any) -> None:
    resp = _app_create(
        ctx,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-test",
    )
    assert resp["ok"] is True
    assert resp["app_contract_version"] == "1.0"
    result = resp["result"]
    assert result["state"] == "creating"
    assert result["intended_pane_count"] == 3
    assert len(result["panes"]) == 3
    assert result["replay"] is False


def test_app_create_idempotency_replay_returns_replay_true(ctx: Any) -> None:
    """R10: same (container_id, idempotency_key) returns the existing layout
    untouched with ``replay: True``."""
    first = _app_create(
        ctx,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-test",
        idempotency_key="op-12345",
    )
    assert first["ok"] is True
    assert first["result"]["replay"] is False
    first_layout_id = first["result"]["layout_id"]

    second = _app_create(
        ctx,
        container_id="bench-alpha",
        template_name="1m+2s",
        tmux_session_name="session-test",
        idempotency_key="op-12345",
    )
    assert second["ok"] is True
    assert second["result"]["replay"] is True
    assert second["result"]["layout_id"] == first_layout_id
