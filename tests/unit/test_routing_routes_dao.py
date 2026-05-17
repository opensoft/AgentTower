"""T008 — FEAT-010 routes-table DAO unit tests.

Covers every public function in :mod:`agenttower.routing.routes_dao`:

* :func:`insert_route` returns route_id; PK collision raises IntegrityError.
* :func:`list_routes` is ordered by ``(created_at ASC, route_id ASC)``;
  ``enabled_only=True`` filters correctly.
* :func:`select_route` returns ``None`` on miss; returns full RouteRow
  on hit; ``enabled`` decodes as bool.
* :func:`update_enabled` returns ``True`` only when the state actually
  changed (FR-009 idempotency); returns ``False`` for no-op AND for
  unknown route_id.
* :func:`delete_route` returns ``True`` on hit, ``False`` on miss.
* :func:`advance_cursor` is monotonic — silent no-op when cursor is
  already ≥ event_id.
* :func:`select_max_event_id` returns 0 on empty events table.

All tests use the production migration path so SQLite CHECK constraints
are in scope.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agenttower.routing import routes_dao as rd
from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    """Fresh in-memory-ish DB at current schema (v8)."""
    state_db = tmp_path / "state.sqlite3"
    c = sqlite3.connect(str(state_db), isolation_level=None)
    c.execute("PRAGMA journal_mode = WAL")
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    c.execute("INSERT INTO schema_version (version) VALUES (?)", (schema.CURRENT_SCHEMA_VERSION,))
    for v in range(2, schema.CURRENT_SCHEMA_VERSION + 1):
        schema._MIGRATIONS[v](c)
    yield c
    c.close()


def _make_row(
    *,
    route_id: str = "11111111-2222-4333-8444-555555555555",
    event_type: str = "waiting_for_input",
    source_scope_kind: str = "any",
    source_scope_value: str | None = None,
    target_rule: str = "explicit",
    target_value: str | None = "agt_slave000001",
    master_rule: str = "auto",
    master_value: str | None = None,
    template: str = "respond to {source_label}: {event_excerpt}",
    enabled: bool = True,
    last_consumed_event_id: int = 0,
    created_at: str = "2026-05-17T00:00:00.000Z",
    updated_at: str = "2026-05-17T00:00:00.000Z",
    created_by_agent_id: str | None = "host-operator",
) -> rd.RouteRow:
    return rd.RouteRow(
        route_id=route_id,
        event_type=event_type,
        source_scope_kind=source_scope_kind,
        source_scope_value=source_scope_value,
        target_rule=target_rule,
        target_value=target_value,
        master_rule=master_rule,
        master_value=master_value,
        template=template,
        enabled=enabled,
        last_consumed_event_id=last_consumed_event_id,
        created_at=created_at,
        updated_at=updated_at,
        created_by_agent_id=created_by_agent_id,
    )


# ──────────────────────────────────────────────────────────────────────
# insert_route
# ──────────────────────────────────────────────────────────────────────


def test_insert_route_returns_route_id(conn: sqlite3.Connection) -> None:
    row = _make_row()
    returned = rd.insert_route(conn, row)
    assert returned == row.route_id
    persisted = rd.select_route(conn, row.route_id)
    assert persisted == row


def test_insert_route_pk_collision_raises_integrity_error(
    conn: sqlite3.Connection,
) -> None:
    rd.insert_route(conn, _make_row(route_id="r1"))
    with pytest.raises(sqlite3.IntegrityError):
        rd.insert_route(conn, _make_row(route_id="r1"))


def test_insert_route_enabled_round_trips_as_bool(
    conn: sqlite3.Connection,
) -> None:
    rd.insert_route(conn, _make_row(route_id="enabled-route", enabled=True))
    rd.insert_route(conn, _make_row(route_id="disabled-route", enabled=False))
    assert rd.select_route(conn, "enabled-route").enabled is True
    assert rd.select_route(conn, "disabled-route").enabled is False


# ──────────────────────────────────────────────────────────────────────
# list_routes
# ──────────────────────────────────────────────────────────────────────


def test_list_routes_orders_by_created_at_then_route_id(
    conn: sqlite3.Connection,
) -> None:
    rd.insert_route(conn, _make_row(
        route_id="zzz", created_at="2026-05-17T00:00:00.000Z",
    ))
    rd.insert_route(conn, _make_row(
        route_id="aaa", created_at="2026-05-17T00:00:00.000Z",
    ))
    rd.insert_route(conn, _make_row(
        route_id="middle", created_at="2026-05-17T00:00:00.500Z",
    ))
    listing = rd.list_routes(conn)
    assert [r.route_id for r in listing] == ["aaa", "zzz", "middle"]


def test_list_routes_empty_returns_empty_list(conn: sqlite3.Connection) -> None:
    assert rd.list_routes(conn) == []
    assert rd.list_routes(conn, enabled_only=True) == []


def test_list_routes_enabled_only_filters(conn: sqlite3.Connection) -> None:
    rd.insert_route(conn, _make_row(route_id="r-on-1", enabled=True))
    rd.insert_route(conn, _make_row(route_id="r-off", enabled=False))
    rd.insert_route(conn, _make_row(route_id="r-on-2", enabled=True))
    all_routes = rd.list_routes(conn)
    enabled_routes = rd.list_routes(conn, enabled_only=True)
    assert len(all_routes) == 3
    assert {r.route_id for r in enabled_routes} == {"r-on-1", "r-on-2"}


# ──────────────────────────────────────────────────────────────────────
# select_route
# ──────────────────────────────────────────────────────────────────────


def test_select_route_returns_none_on_miss(conn: sqlite3.Connection) -> None:
    assert rd.select_route(conn, "does-not-exist") is None


def test_select_route_returns_full_row_on_hit(conn: sqlite3.Connection) -> None:
    original = _make_row(
        route_id="r1",
        source_scope_kind="role",
        source_scope_value="role:slave,capability:codex",
        target_rule="role",
        target_value="role:swarm",
        master_rule="explicit",
        master_value="agt_master00001",
        created_by_agent_id=None,
        last_consumed_event_id=42,
    )
    rd.insert_route(conn, original)
    fetched = rd.select_route(conn, "r1")
    assert fetched == original


# ──────────────────────────────────────────────────────────────────────
# update_enabled (FR-009 idempotency)
# ──────────────────────────────────────────────────────────────────────


def test_update_enabled_returns_true_when_state_changes(
    conn: sqlite3.Connection,
) -> None:
    rd.insert_route(conn, _make_row(route_id="r1", enabled=True))
    changed = rd.update_enabled(
        conn, "r1", enabled=False, updated_at="2026-05-17T00:01:00.000Z",
    )
    assert changed is True
    assert rd.select_route(conn, "r1").enabled is False


def test_update_enabled_returns_false_on_noop_idempotency(
    conn: sqlite3.Connection,
) -> None:
    """FR-009: re-disabling an already-disabled route MUST report no
    change (so the service layer skips the audit emit)."""
    rd.insert_route(conn, _make_row(route_id="r1", enabled=False))
    changed = rd.update_enabled(
        conn, "r1", enabled=False, updated_at="2026-05-17T00:01:00.000Z",
    )
    assert changed is False


def test_update_enabled_returns_false_for_unknown_route(
    conn: sqlite3.Connection,
) -> None:
    changed = rd.update_enabled(
        conn, "nonexistent", enabled=True,
        updated_at="2026-05-17T00:01:00.000Z",
    )
    assert changed is False


# ──────────────────────────────────────────────────────────────────────
# delete_route (FR-003)
# ──────────────────────────────────────────────────────────────────────


def test_delete_route_returns_true_on_hit(conn: sqlite3.Connection) -> None:
    rd.insert_route(conn, _make_row(route_id="r1"))
    deleted = rd.delete_route(conn, "r1")
    assert deleted is True
    assert rd.select_route(conn, "r1") is None


def test_delete_route_returns_false_on_miss(conn: sqlite3.Connection) -> None:
    assert rd.delete_route(conn, "nonexistent") is False


# ──────────────────────────────────────────────────────────────────────
# advance_cursor (FR-012 monotonicity)
# ──────────────────────────────────────────────────────────────────────


def test_advance_cursor_moves_forward(conn: sqlite3.Connection) -> None:
    rd.insert_route(conn, _make_row(route_id="r1", last_consumed_event_id=10))
    rd.advance_cursor(conn, "r1", 20, updated_at="2026-05-17T00:01:00.000Z")
    assert rd.select_route(conn, "r1").last_consumed_event_id == 20


def test_advance_cursor_is_monotonic_noop_when_behind(
    conn: sqlite3.Connection,
) -> None:
    """A buggy caller attempting to move the cursor backwards must be
    silently rejected (storage-layer monotonicity defense per FR-012)."""
    rd.insert_route(conn, _make_row(route_id="r1", last_consumed_event_id=100))
    rd.advance_cursor(conn, "r1", 50, updated_at="2026-05-17T00:01:00.000Z")
    assert rd.select_route(conn, "r1").last_consumed_event_id == 100


def test_advance_cursor_noop_for_unknown_route(conn: sqlite3.Connection) -> None:
    # Should NOT raise; just silently do nothing.
    rd.advance_cursor(conn, "nonexistent", 5, updated_at="x")


# ──────────────────────────────────────────────────────────────────────
# select_max_event_id (FR-002)
# ──────────────────────────────────────────────────────────────────────


def test_select_max_event_id_empty_table_returns_zero(
    conn: sqlite3.Connection,
) -> None:
    assert rd.select_max_event_id(conn) == 0


def test_select_max_event_id_returns_largest(conn: sqlite3.Connection) -> None:
    # Insert FEAT-008-shape events directly to set up the test.
    for excerpt in ("a", "b", "c"):
        conn.execute(
            """
            INSERT INTO events (
                event_type, agent_id, attachment_id, log_path,
                byte_range_start, byte_range_end,
                line_offset_start, line_offset_end,
                observed_at, excerpt, classifier_rule_id
            ) VALUES (
                'waiting_for_input', 'agt_slave000001', 'atc_x', '/tmp/x.log',
                0, 1, 0, 1,
                '2026-05-17T00:00:00.000000+00:00', ?, 'activity.fallback.v1'
            )
            """,
            (excerpt,),
        )
    assert rd.select_max_event_id(conn) == 3


# ──────────────────────────────────────────────────────────────────────
# DAO does NOT start transactions (caller owns BEGIN IMMEDIATE)
# ──────────────────────────────────────────────────────────────────────


def test_dao_writes_inside_caller_transaction(conn: sqlite3.Connection) -> None:
    """Caller opens BEGIN IMMEDIATE; multiple DAO calls commit
    together; rollback discards them all (FR-012 atomicity test surface)."""
    conn.execute("BEGIN IMMEDIATE")
    rd.insert_route(conn, _make_row(route_id="r1"))
    rd.advance_cursor(conn, "r1", 5, updated_at="x")
    conn.execute("ROLLBACK")
    assert rd.select_route(conn, "r1") is None


def test_caller_transaction_commits_all_dao_writes(
    conn: sqlite3.Connection,
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    rd.insert_route(conn, _make_row(route_id="r1", last_consumed_event_id=0))
    rd.advance_cursor(conn, "r1", 5, updated_at="2026-05-17T00:00:01.000Z")
    conn.execute("COMMIT")
    fetched = rd.select_route(conn, "r1")
    assert fetched is not None
    assert fetched.last_consumed_event_id == 5
