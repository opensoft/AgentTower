"""FEAT-009 routing kill-switch service (FR-026 — FR-030).

Wraps :class:`agenttower.routing.dao.DaemonStateDao` with a
write-through cache for ``is_enabled()`` — the delivery worker calls
this on every loop iteration, so the read must not hit SQLite each time.

Toggle endpoints (``enable`` / ``disable``) are host-only (Clarifications
session 2 Q2 + research §R-005); the boundary check lives in
``socket_api/methods.py`` (T049). This module is origin-agnostic — it
accepts an operator identity string (either an ``agt_<12-hex>`` agent_id
or the ``host-operator`` sentinel) and trusts the dispatch layer to
have enforced the host-only constraint.

Idempotency is computed here: if a caller invokes ``enable()`` on a
flag that's already enabled, the returned :class:`ToggleResult` has
``changed=False`` and the audit-emission step (caller's responsibility)
MUST be skipped (contracts/socket-routing.md "Success response").
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from agenttower.routing.dao import DaemonStateDao


__all__ = ["RoutingFlagService", "ToggleResult"]


@dataclass(frozen=True)
class ToggleResult:
    """Outcome of a :meth:`RoutingFlagService.enable` /
    :meth:`RoutingFlagService.disable` call.

    Mirrors the ``contracts/socket-routing.md`` "Success response" shape.
    ``changed=False`` indicates an idempotent no-op call; the audit
    writer MUST NOT emit a ``routing_toggled`` event in that case.
    """

    previous_value: str
    current_value: str
    changed: bool
    last_updated_at: str
    last_updated_by: str


class RoutingFlagService:
    """Read/toggle the routing kill switch with a write-through cache.

    Thread-safety: the cache is guarded by a :class:`threading.Lock` so
    that the delivery worker's hot-path read and the socket-dispatch
    layer's toggle don't race. Every toggle: acquire lock → write SQLite
    → update cache → release. Every read: lock-protected snapshot of
    the cached value.

    The cache is initialized from SQLite on first :meth:`is_enabled`
    call (lazy) — the daemon's boot path does NOT need to pre-warm it
    because the first delivery-worker cycle does that for free.
    """

    def __init__(self, dao: DaemonStateDao) -> None:
        self._dao = dao
        self._lock = threading.Lock()
        # ``None`` means "not yet read from SQLite". Lazy init keeps the
        # constructor side-effect-free.
        self._cached_value: str | None = None

    # ─── Read ─────────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        """Return ``True`` iff the routing flag is currently ``enabled``.

        Hot-path read for the delivery worker. Uses the cache; falls
        through to SQLite on first call.
        """
        with self._lock:
            if self._cached_value is None:
                self._cached_value = self._dao.read_routing_flag().value
            return self._cached_value == "enabled"

    def read_full(self) -> tuple[str, str, str]:
        """Return ``(value, last_updated_at, last_updated_by)`` for
        ``routing.status``. Always reads SQLite (the cache is value-only,
        not metadata). Cheap (one row, single primary-key lookup)."""
        flag = self._dao.read_routing_flag()
        # Refresh the cache while we're here.
        with self._lock:
            self._cached_value = flag.value
        return flag.value, flag.last_updated_at, flag.last_updated_by

    # ─── Toggles ──────────────────────────────────────────────────────

    def enable(self, *, operator: str, ts: str) -> ToggleResult:
        """Set the flag to ``enabled``. Idempotent if already enabled.

        Args:
            operator: ``agt_<12-hex>`` (bench-container caller) or the
                ``host-operator`` sentinel. The host-only boundary check
                lives in the socket dispatch layer.
            ts: Canonical ISO 8601 ms UTC timestamp (FR-012b).
        """
        return self._set("enabled", operator=operator, ts=ts)

    def disable(self, *, operator: str, ts: str) -> ToggleResult:
        """Set the flag to ``disabled``. Idempotent if already disabled."""
        return self._set("disabled", operator=operator, ts=ts)

    def _set(self, value: str, *, operator: str, ts: str) -> ToggleResult:
        """Shared body for ``enable`` and ``disable``. Always reads the
        current SQLite value first (single PK lookup) to determine
        idempotency — the cache may be stale relative to another writer
        (defensive, even though there's only one writer in MVP)."""
        with self._lock:
            current_flag = self._dao.read_routing_flag()
            previous = current_flag.value
            changed = previous != value
            if changed:
                self._dao.write_routing_flag(value, ts=ts, updated_by=operator)
                self._cached_value = value
                # On the host-driven write-through path, the audit
                # caller is responsible for emitting the
                # ``routing_toggled`` event ONLY when changed=True.
                return ToggleResult(
                    previous_value=previous,
                    current_value=value,
                    changed=True,
                    last_updated_at=ts,
                    last_updated_by=operator,
                )
            # No-op: don't touch SQLite, don't emit audit. Return the
            # CURRENT row's metadata (not the caller's ts / operator —
            # those would misrepresent the last actual change).
            self._cached_value = previous
            return ToggleResult(
                previous_value=previous,
                current_value=previous,
                changed=False,
                last_updated_at=current_flag.last_updated_at,
                last_updated_by=current_flag.last_updated_by,
            )

    # ─── Cache hygiene (test / restart hook) ──────────────────────────

    def invalidate_cache(self) -> None:
        """Force the next ``is_enabled()`` call to re-read SQLite.

        Production code never needs this — write-through keeps the
        cache coherent. Tests use it to model an out-of-band SQLite
        write (e.g., a second daemon process in a parallel test).
        """
        with self._lock:
            self._cached_value = None
