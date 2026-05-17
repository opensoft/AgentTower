"""T027 — FEAT-010 ``routes.*`` socket method contract tests.

For each of the six ``routes.*`` methods, asserts:

* Successful invocations return the documented ``{"ok": true,
  "result": {...}}`` envelope with the FR-045..048 shape.
* Validation rejections return ``{"ok": false, "error":
  {"code": "<closed-set>", "message": "..."}}`` with one of the
  FEAT-010 CLI codes from
  :data:`agenttower.routing.route_errors.CLI_ERROR_CODES`.
* Unwired daemon (no routes_service in context) returns
  ``daemon_unavailable``.

Uses the production DISPATCH table + a real :class:`RoutesService`
backed by an in-memory SQLite — same surface the live socket
dispatch layer exposes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agenttower.routing import routes_service as svc
from agenttower.routing.route_errors import CLI_ERROR_CODES
from agenttower.socket_api.methods import DISPATCH, DaemonContext
from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _FakeAudit:
    """Capture every emit call so test assertions stay isolated from
    JSONL filesystem state."""

    created: list[dict] = None  # type: ignore[assignment]
    updated: list[dict] = None  # type: ignore[assignment]
    deleted: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.created = []
        self.updated = []
        self.deleted = []

    def emit_route_created(self, events_file: Path, **kw: Any) -> None:
        self.created.append(kw)

    def emit_route_updated(self, events_file: Path, **kw: Any) -> None:
        self.updated.append(kw)

    def emit_route_deleted(self, events_file: Path, **kw: Any) -> None:
        self.deleted.append(kw)


@pytest.fixture
def ctx_with_routes(tmp_path: Path) -> DaemonContext:
    """DaemonContext wired with a real RoutesService + temp DB."""
    db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute(
        "INSERT INTO schema_version (version) VALUES (?)",
        (schema.CURRENT_SCHEMA_VERSION,),
    )
    for v in range(2, schema.CURRENT_SCHEMA_VERSION + 1):
        schema._MIGRATIONS[v](conn)
    conn.commit()
    conn.close()

    def _conn_factory() -> sqlite3.Connection:
        return sqlite3.connect(db, isolation_level=None)

    audit = _FakeAudit()
    routes_service = svc.RoutesService(
        conn_factory=_conn_factory,
        audit_writer=audit,  # type: ignore[arg-type]
        events_file=tmp_path / "events.jsonl",
    )
    from datetime import datetime, timezone
    return DaemonContext(
        pid=1,
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "sock",
        state_path=tmp_path,
        daemon_version="test",
        routes_service=routes_service,
    )


def _add_good_params(**overrides) -> dict[str, Any]:
    base = {
        "event_type": "waiting_for_input",
        "source_scope_kind": "any",
        "source_scope_value": None,
        "target_rule": "explicit",
        "target_value": "agt_slave000001",
        "master_rule": "auto",
        "master_value": None,
        "template": "respond to {source_label}: {event_excerpt}",
    }
    base.update(overrides)
    return base


# ──────────────────────────────────────────────────────────────────────
# routes.add
# ──────────────────────────────────────────────────────────────────────


def test_routes_add_success_returns_ok_envelope(ctx_with_routes: DaemonContext) -> None:
    resp = DISPATCH["routes.add"](ctx_with_routes, _add_good_params())
    assert resp["ok"] is True
    assert "route_id" in resp["result"]
    assert resp["result"]["event_type"] == "waiting_for_input"
    assert resp["result"]["enabled"] is True
    assert resp["result"]["last_consumed_event_id"] == 0
    assert resp["result"]["source_scope"]["kind"] == "any"


def test_routes_add_bad_event_type_returns_route_event_type_invalid(
    ctx_with_routes: DaemonContext,
) -> None:
    resp = DISPATCH["routes.add"](
        ctx_with_routes, _add_good_params(event_type="not_a_real_type"),
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "route_event_type_invalid"


def test_routes_add_bad_master_rule_returns_master_rule_invalid(
    ctx_with_routes: DaemonContext,
) -> None:
    resp = DISPATCH["routes.add"](
        ctx_with_routes, _add_good_params(master_rule="round_robin"),
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "route_master_rule_invalid"


def test_routes_add_bad_target_rule_returns_target_rule_invalid(
    ctx_with_routes: DaemonContext,
) -> None:
    resp = DISPATCH["routes.add"](
        ctx_with_routes, _add_good_params(target_rule="not_a_rule"),
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "route_target_rule_invalid"


def test_routes_add_bad_source_scope_returns_source_scope_invalid(
    ctx_with_routes: DaemonContext,
) -> None:
    resp = DISPATCH["routes.add"](
        ctx_with_routes, _add_good_params(source_scope_kind="not_a_kind"),
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "route_source_scope_invalid"


def test_routes_add_bad_template_returns_template_invalid(
    ctx_with_routes: DaemonContext,
) -> None:
    resp = DISPATCH["routes.add"](
        ctx_with_routes, _add_good_params(template="references {unknown_field}"),
    )
    assert resp["ok"] is False
    assert resp["error"]["code"] == "route_template_invalid"


# ──────────────────────────────────────────────────────────────────────
# routes.list
# ──────────────────────────────────────────────────────────────────────


def test_routes_list_empty(ctx_with_routes: DaemonContext) -> None:
    resp = DISPATCH["routes.list"](ctx_with_routes, {})
    assert resp == {"ok": True, "result": {"routes": []}}


def test_routes_list_returns_all_added(ctx_with_routes: DaemonContext) -> None:
    DISPATCH["routes.add"](ctx_with_routes, _add_good_params())
    DISPATCH["routes.add"](ctx_with_routes, _add_good_params())
    resp = DISPATCH["routes.list"](ctx_with_routes, {})
    assert resp["ok"] is True
    assert len(resp["result"]["routes"]) == 2


def test_routes_list_enabled_only_filters(ctx_with_routes: DaemonContext) -> None:
    r1 = DISPATCH["routes.add"](ctx_with_routes, _add_good_params())
    r2 = DISPATCH["routes.add"](ctx_with_routes, _add_good_params())
    DISPATCH["routes.disable"](ctx_with_routes, {"route_id": r2["result"]["route_id"]})

    resp = DISPATCH["routes.list"](ctx_with_routes, {"enabled_only": True})
    assert resp["ok"] is True
    assert len(resp["result"]["routes"]) == 1
    assert resp["result"]["routes"][0]["route_id"] == r1["result"]["route_id"]


# ──────────────────────────────────────────────────────────────────────
# routes.show
# ──────────────────────────────────────────────────────────────────────


def test_routes_show_returns_row_and_runtime(ctx_with_routes: DaemonContext) -> None:
    added = DISPATCH["routes.add"](ctx_with_routes, _add_good_params())
    route_id = added["result"]["route_id"]
    resp = DISPATCH["routes.show"](ctx_with_routes, {"route_id": route_id})
    assert resp["ok"] is True
    assert resp["result"]["route_id"] == route_id
    assert "runtime" in resp["result"]
    runtime = resp["result"]["runtime"]
    assert set(runtime.keys()) == {
        "last_routing_cycle_at",
        "events_consumed",
        "last_skip_reason",
        "last_skip_at",
    }


def test_routes_show_unknown_id_returns_route_id_not_found(
    ctx_with_routes: DaemonContext,
) -> None:
    resp = DISPATCH["routes.show"](ctx_with_routes, {"route_id": "nope"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "route_id_not_found"


# ──────────────────────────────────────────────────────────────────────
# routes.remove
# ──────────────────────────────────────────────────────────────────────


def test_routes_remove_success(ctx_with_routes: DaemonContext) -> None:
    added = DISPATCH["routes.add"](ctx_with_routes, _add_good_params())
    route_id = added["result"]["route_id"]
    resp = DISPATCH["routes.remove"](ctx_with_routes, {"route_id": route_id})
    assert resp["ok"] is True
    assert resp["result"]["operation"] == "removed"
    assert resp["result"]["route_id"] == route_id
    assert "at" in resp["result"]


def test_routes_remove_unknown_id_returns_route_id_not_found(
    ctx_with_routes: DaemonContext,
) -> None:
    resp = DISPATCH["routes.remove"](ctx_with_routes, {"route_id": "nope"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "route_id_not_found"


# ──────────────────────────────────────────────────────────────────────
# routes.enable / routes.disable (FR-009 idempotent)
# ──────────────────────────────────────────────────────────────────────


def test_routes_enable_idempotent(ctx_with_routes: DaemonContext) -> None:
    added = DISPATCH["routes.add"](ctx_with_routes, _add_good_params())
    route_id = added["result"]["route_id"]
    # Already enabled — no-op succeeds.
    resp = DISPATCH["routes.enable"](ctx_with_routes, {"route_id": route_id})
    assert resp["ok"] is True
    assert resp["result"]["operation"] == "enabled"


def test_routes_disable_then_enable_lifecycle(ctx_with_routes: DaemonContext) -> None:
    added = DISPATCH["routes.add"](ctx_with_routes, _add_good_params())
    route_id = added["result"]["route_id"]
    DISPATCH["routes.disable"](ctx_with_routes, {"route_id": route_id})
    DISPATCH["routes.enable"](ctx_with_routes, {"route_id": route_id})
    # Verify the route is back to enabled.
    show = DISPATCH["routes.show"](ctx_with_routes, {"route_id": route_id})
    assert show["result"]["enabled"] is True


def test_routes_enable_unknown_id_returns_route_id_not_found(
    ctx_with_routes: DaemonContext,
) -> None:
    resp = DISPATCH["routes.enable"](ctx_with_routes, {"route_id": "nope"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "route_id_not_found"


def test_routes_disable_unknown_id_returns_route_id_not_found(
    ctx_with_routes: DaemonContext,
) -> None:
    resp = DISPATCH["routes.disable"](ctx_with_routes, {"route_id": "nope"})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "route_id_not_found"


# ──────────────────────────────────────────────────────────────────────
# Unwired context — daemon_unavailable
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def unwired_ctx(tmp_path: Path) -> DaemonContext:
    from datetime import datetime, timezone
    return DaemonContext(
        pid=1,
        start_time_utc=datetime.now(timezone.utc),
        socket_path=tmp_path / "sock",
        state_path=tmp_path,
        daemon_version="test",
        # routes_service intentionally None
    )


@pytest.mark.parametrize(
    "method",
    [
        "routes.add", "routes.list", "routes.show",
        "routes.remove", "routes.enable", "routes.disable",
    ],
)
def test_unwired_context_returns_daemon_unavailable(
    unwired_ctx: DaemonContext, method: str,
) -> None:
    resp = DISPATCH[method](unwired_ctx, {})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "daemon_unavailable"


# ──────────────────────────────────────────────────────────────────────
# Dispatch table membership
# ──────────────────────────────────────────────────────────────────────


def test_all_six_routes_methods_registered_in_dispatch() -> None:
    for m in (
        "routes.add", "routes.list", "routes.show",
        "routes.remove", "routes.enable", "routes.disable",
    ):
        assert m in DISPATCH, f"FEAT-010 method {m!r} missing from DISPATCH"


def test_every_error_code_returned_is_in_closed_set(
    ctx_with_routes: DaemonContext,
) -> None:
    """Cover the six CLI error codes routes.* can emit; every one MUST
    be in CLI_ERROR_CODES."""
    cases = [
        ("routes.add", _add_good_params(event_type="bad")),
        ("routes.add", _add_good_params(master_rule="bad")),
        ("routes.add", _add_good_params(target_rule="bad")),
        ("routes.add", _add_good_params(source_scope_kind="bad")),
        ("routes.add", _add_good_params(template="bad {x}")),
        ("routes.show", {"route_id": "missing"}),
        ("routes.remove", {"route_id": "missing"}),
        ("routes.enable", {"route_id": "missing"}),
        ("routes.disable", {"route_id": "missing"}),
    ]
    for method, params in cases:
        resp = DISPATCH[method](ctx_with_routes, params)
        assert resp["ok"] is False
        assert resp["error"]["code"] in CLI_ERROR_CODES, (
            f"{method} emitted out-of-closed-set code {resp['error']['code']!r}"
        )
