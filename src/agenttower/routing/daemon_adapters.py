"""Production adapters that bridge FEAT-001..006 services to the
FEAT-009 service / worker Protocols.

The FEAT-009 :class:`AgentsLookup`, :class:`ContainerPaneLookup`, and
:class:`DeliveryContextResolver` are intentionally tiny Protocols so the
queue service and delivery worker are unit-testable without the full
daemon. In production these adapters wrap the FEAT-003 / FEAT-004 /
FEAT-006 service surfaces.

Connection ownership:

* The adapters share a connection-factory callable so each method opens
  its own SQLite connection — this matches the existing pattern in
  :class:`agenttower.agents.AgentsService` and avoids cross-thread
  reuse of a single connection (the delivery worker runs on its own
  thread).
* The :class:`DaemonStateDao` + :class:`MessageQueueDao` + the audit
  writer each get a DEDICATED per-worker SQLite connection opened
  with ``check_same_thread=False`` so the worker thread can use them
  without violating SQLite's thread-safety contract. Those connections
  are NOT shared with the adapters here — adapters open ephemeral
  connections so the read-only queries don't block the worker's
  ``BEGIN IMMEDIATE`` transactions.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING

from agenttower.routing.delivery import DeliveryContext
from agenttower.state.agents import (
    AgentRecord,
    list_agents,
    select_agent_by_id,
)

if TYPE_CHECKING:
    from agenttower.discovery.pane_service import PaneDiscoveryService
    from agenttower.discovery.service import DiscoveryService
    from agenttower.routing.dao import QueueRow


__all__ = [
    "RegistryAgentsLookup",
    "DiscoveryContainerPaneLookup",
    "RegistryDeliveryContextResolver",
]


# ──────────────────────────────────────────────────────────────────────
# RegistryAgentsLookup — FEAT-006 agent registry adapter
# ──────────────────────────────────────────────────────────────────────


class RegistryAgentsLookup:
    """Adapter exposing the FEAT-006 agent registry as :class:`AgentsLookup`.

    Used by :class:`QueueService` (for ``--target`` resolution via
    :func:`routing.target_resolver.resolve_target`).
    """

    def __init__(self, connection_factory: Callable[[], sqlite3.Connection]) -> None:
        self._connection_factory = connection_factory

    def get_agent_by_id(self, agent_id: str) -> AgentRecord | None:
        conn = self._connection_factory()
        try:
            return select_agent_by_id(conn, agent_id=agent_id)
        finally:
            conn.close()

    def find_agents_by_label(
        self, label: str, *, only_active: bool = True,
    ) -> list[AgentRecord]:
        conn = self._connection_factory()
        try:
            rows = list_agents(conn, active_only=only_active)
        finally:
            conn.close()
        return [r for r in rows if r.label == label]


# ──────────────────────────────────────────────────────────────────────
# DiscoveryContainerPaneLookup — FEAT-003 + FEAT-004 adapter
# ──────────────────────────────────────────────────────────────────────


class DiscoveryContainerPaneLookup:
    """Adapter exposing FEAT-003 ``DiscoveryService`` + FEAT-004
    ``PaneDiscoveryService`` as :class:`ContainerPaneLookup`.

    Used by :class:`QueueService` for the FR-019 permission gate steps
    5/6 (target container active / pane resolvable) and by the worker
    for the FR-025 pre-paste re-check.
    """

    def __init__(
        self,
        discovery_service: "DiscoveryService",
        pane_service: "PaneDiscoveryService",
    ) -> None:
        self._discovery = discovery_service
        self._panes = pane_service

    def is_container_active(self, container_id: str) -> bool:
        # ``list_containers(active_only=True)`` is a single primary-key
        # range read; not the hot path (delivery worker invokes it once
        # per ``send_input`` + once per re-check).
        try:
            rows = self._discovery.list_containers(active_only=True)
        except Exception:
            # Defensive: a SQLite hiccup must not crash the worker. The
            # row will surface ``target_container_inactive`` in that case.
            return False
        return any(r.container_id == container_id for r in rows)

    def is_pane_resolvable(self, container_id: str, pane_id: str) -> bool:
        try:
            rows = self._panes.list_panes(
                active_only=True, container_filter=container_id,
            )
        except Exception:
            return False
        return any(r.tmux_pane_id == pane_id for r in rows)


# ──────────────────────────────────────────────────────────────────────
# RegistryDeliveryContextResolver — joins agent + container for tmux call
# ──────────────────────────────────────────────────────────────────────


class RegistryDeliveryContextResolver:
    """Adapter producing a :class:`DeliveryContext` for one queue row.

    Used by :class:`DeliveryWorker` for every delivery attempt. Joins
    the row's ``target_container_id`` + ``target_pane_id`` against
    FEAT-003 containers (for ``config_user`` → ``bench_user``) and
    FEAT-004 panes (for ``tmux_socket_path``).
    """

    def __init__(
        self,
        connection_factory: Callable[[], sqlite3.Connection],
    ) -> None:
        self._connection_factory = connection_factory

    def resolve(self, row: "QueueRow") -> DeliveryContext:
        """Read the container + pane rows for ``row`` and assemble a
        :class:`DeliveryContext`.

        Raises:
            RuntimeError: if either join is missing. The caller (the
                worker's ``_deliver_one``) catches and maps to a
                pre-paste re-check failure (``target_pane_missing`` /
                ``target_container_inactive``).
        """
        conn = self._connection_factory()
        try:
            container_row = conn.execute(
                "SELECT config_user FROM containers WHERE container_id = ? AND active = 1",
                (row.target_container_id,),
            ).fetchone()
            if container_row is None:
                raise RuntimeError(
                    f"container row missing or inactive: {row.target_container_id}"
                )
            bench_user = container_row[0] or "root"

            pane_row = conn.execute(
                "SELECT tmux_socket_path FROM panes "
                "WHERE container_id = ? AND tmux_pane_id = ? AND active = 1",
                (row.target_container_id, row.target_pane_id),
            ).fetchone()
            if pane_row is None:
                raise RuntimeError(
                    f"pane row missing or inactive: "
                    f"{row.target_container_id}/{row.target_pane_id}"
                )
            socket_path = pane_row[0]
        finally:
            conn.close()

        return DeliveryContext(
            container_id=row.target_container_id,
            bench_user=bench_user,
            socket_path=socket_path,
            pane_id=row.target_pane_id,
        )
