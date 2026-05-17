"""T032 — FEAT-009 RoutingFlagService tests.

Covers:

* Seed value: a fresh DB reads ``enabled``.
* Toggle: ``disable`` then ``enable`` round-trip, ``ToggleResult`` shape.
* Idempotency: re-enabling an already-enabled flag returns
  ``changed=False`` AND does NOT touch SQLite (the cached / persisted
  ``last_updated_at`` and ``last_updated_by`` reflect the LAST ACTUAL
  change, not the no-op caller).
* Write-through: after a toggle, ``is_enabled()`` returns the new value
  without re-reading SQLite (cache hit).
* Cache coherence across a simulated out-of-band SQLite write
  (``invalidate_cache``).
* Audit emission is the caller's responsibility — service returns
  ``changed=True/False`` and the dispatch layer branches on it
  (contracts/socket-routing.md).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from agenttower.routing.dao import DaemonStateDao
from agenttower.routing.kill_switch import RoutingFlagService, ToggleResult
from agenttower.state import schema


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _open_v7(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "state.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (schema.CURRENT_SCHEMA_VERSION,))
    for v in range(2, schema.CURRENT_SCHEMA_VERSION + 1):
        schema._MIGRATIONS[v](conn)
    conn.commit()
    return conn


def _make_service(tmp_path: Path) -> RoutingFlagService:
    conn = _open_v7(tmp_path)
    return RoutingFlagService(DaemonStateDao(conn))


# ──────────────────────────────────────────────────────────────────────
# Seed value
# ──────────────────────────────────────────────────────────────────────


def test_fresh_db_reads_enabled(tmp_path: Path) -> None:
    """A fresh v7 DB seeds routing_enabled=enabled."""
    svc = _make_service(tmp_path)
    assert svc.is_enabled() is True


def test_fresh_db_full_read_returns_daemon_init_sentinel(tmp_path: Path) -> None:
    """The seed row's ``last_updated_by`` is ``(daemon-init)`` —
    distinct from real operator actions."""
    svc = _make_service(tmp_path)
    value, _, by = svc.read_full()
    assert value == "enabled"
    assert by == "(daemon-init)"


# ──────────────────────────────────────────────────────────────────────
# Toggle: disable / enable round-trip
# ──────────────────────────────────────────────────────────────────────


def test_disable_changes_value(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    result = svc.disable(operator="host-operator", ts="2026-05-12T00:00:01.000Z")
    assert result == ToggleResult(
        previous_value="enabled",
        current_value="disabled",
        changed=True,
        last_updated_at="2026-05-12T00:00:01.000Z",
        last_updated_by="host-operator",
    )
    assert svc.is_enabled() is False


def test_enable_after_disable_round_trips(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.disable(operator="host-operator", ts="2026-05-12T00:00:01.000Z")
    result = svc.enable(operator="host-operator", ts="2026-05-12T00:00:02.000Z")
    assert result.previous_value == "disabled"
    assert result.current_value == "enabled"
    assert result.changed is True
    assert svc.is_enabled() is True


def test_toggle_with_agent_id_operator(tmp_path: Path) -> None:
    """The operator parameter accepts either ``host-operator`` or an
    ``agt_<12-hex>`` agent_id — the dispatch layer enforces the
    host-only constraint."""
    svc = _make_service(tmp_path)
    result = svc.disable(operator="agt_aaaaaa111111", ts="2026-05-12T00:00:01.000Z")
    assert result.last_updated_by == "agt_aaaaaa111111"


# ──────────────────────────────────────────────────────────────────────
# Idempotent toggles
# ──────────────────────────────────────────────────────────────────────


def test_enable_on_already_enabled_returns_changed_false(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    result = svc.enable(operator="host-operator", ts="2026-05-12T00:00:01.000Z")
    assert result.changed is False
    assert result.previous_value == "enabled"
    assert result.current_value == "enabled"


def test_disable_on_already_disabled_returns_changed_false(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    svc.disable(operator="host-operator", ts="2026-05-12T00:00:01.000Z")
    result = svc.disable(operator="host-operator", ts="2026-05-12T00:00:02.000Z")
    assert result.changed is False
    assert result.previous_value == "disabled"
    assert result.current_value == "disabled"


def test_idempotent_no_op_returns_existing_metadata(tmp_path: Path) -> None:
    """When ``changed=False``, the returned ``last_updated_at`` and
    ``last_updated_by`` reflect the LAST ACTUAL change (not the
    no-op caller). Otherwise the audit trail would lie."""
    svc = _make_service(tmp_path)
    # Initial seed: (daemon-init) at some migration timestamp.
    seed_value, seed_ts, seed_by = svc.read_full()
    assert seed_by == "(daemon-init)"
    # Idempotent enable (no-op) MUST NOT advertise the no-op caller as
    # the last updater.
    result = svc.enable(
        operator="host-operator", ts="2026-05-12T00:00:01.000Z"
    )
    assert result.last_updated_by == "(daemon-init)"
    assert result.last_updated_at == seed_ts


def test_idempotent_no_op_does_not_emit_audit_row(tmp_path: Path) -> None:
    """The DAO's write_routing_flag is NOT called on a no-op. We verify
    by reading the row's last_updated_at before and after the no-op —
    it shouldn't change."""
    svc = _make_service(tmp_path)
    pre_value, pre_ts, pre_by = svc.read_full()
    svc.enable(operator="host-operator", ts="2026-05-12T00:00:01.000Z")
    post_value, post_ts, post_by = svc.read_full()
    assert (post_value, post_ts, post_by) == (pre_value, pre_ts, pre_by)


# ──────────────────────────────────────────────────────────────────────
# Write-through cache
# ──────────────────────────────────────────────────────────────────────


def test_is_enabled_reflects_toggle_without_re_reading_sqlite(
    tmp_path: Path,
) -> None:
    """After ``disable()``, ``is_enabled()`` returns False WITHOUT
    issuing a SQLite read (write-through cache is updated synchronously)."""
    svc = _make_service(tmp_path)
    svc.disable(operator="host-operator", ts="2026-05-12T00:00:01.000Z")
    # Replace the DAO with a deliberately broken one — if is_enabled
    # tried to re-read SQLite, this would raise.

    class ExplodingDao:
        def read_routing_flag(self):
            raise AssertionError("is_enabled() must not re-read SQLite after a toggle")

        def write_routing_flag(self, *a, **kw):
            raise AssertionError("not expected")

    svc._dao = ExplodingDao()  # type: ignore[assignment]
    assert svc.is_enabled() is False  # served from cache


def test_first_is_enabled_call_warms_cache(tmp_path: Path) -> None:
    svc = _make_service(tmp_path)
    # Initially the cache is None.
    assert svc._cached_value is None  # implementation detail; pinned defensively
    svc.is_enabled()
    assert svc._cached_value == "enabled"


# ──────────────────────────────────────────────────────────────────────
# Cache invalidation (out-of-band write simulation)
# ──────────────────────────────────────────────────────────────────────


def test_invalidate_cache_forces_re_read(tmp_path: Path) -> None:
    """If something writes to ``daemon_state`` outside the service
    (e.g., a parallel test connection), ``invalidate_cache()`` forces
    the next ``is_enabled()`` to re-read SQLite."""
    conn = _open_v7(tmp_path)
    svc = RoutingFlagService(DaemonStateDao(conn))
    assert svc.is_enabled() is True
    # Simulate out-of-band write.
    conn.execute(
        "UPDATE daemon_state SET value = 'disabled', last_updated_at = ?, last_updated_by = ? "
        "WHERE key = 'routing_enabled'",
        ("2026-05-12T00:00:01.000Z", "out-of-band"),
    )
    conn.commit()
    # Cache is stale — is_enabled still returns the cached True.
    assert svc.is_enabled() is True
    # After invalidation, the next read sees the fresh value.
    svc.invalidate_cache()
    assert svc.is_enabled() is False


# ──────────────────────────────────────────────────────────────────────
# Concurrency: lock guards the cache + write-through
# ──────────────────────────────────────────────────────────────────────


def test_service_holds_a_threading_lock(tmp_path: Path) -> None:
    """The service uses a threading.Lock for cache + write-through.
    Pinned defensively so a future refactor doesn't introduce a race.

    Checks the context-manager protocol rather than instantiating a
    throwaway Lock to read its class — the prior form allocated a
    real synchronization primitive on every test run just to inspect
    its type, which is wasteful and obscures intent.
    """
    svc = _make_service(tmp_path)
    assert hasattr(svc._lock, "acquire")
    assert hasattr(svc._lock, "release")
    assert hasattr(svc._lock, "__enter__")
    assert hasattr(svc._lock, "__exit__")
