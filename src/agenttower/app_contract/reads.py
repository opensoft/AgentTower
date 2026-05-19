"""FEAT-011 T039+T040 — pane/agent read surfaces (``app.<entity>.list/detail``).

Read-only projection over the existing FEAT-004 ``panes`` and FEAT-006
``agents`` DAOs. The handlers in this module are thin: they call the
existing service-layer queries, project each row through the
``view_models`` builders, and apply FR-020/020a/020b pagination and
FR-021/021a/021b ordering on top.

What's implemented at this slice:

* **Pagination** — ``limit`` default 50, cap 200 (FR-020a). ``cursor_next``
  is an opaque base64-encoded JSON envelope ``{offset, order_by, filters}``
  bounded at 512 chars (FR-020b). Reusing a cursor under a different
  ``order_by`` or filter set returns ``validation_failed.details.field
  == "cursor_next"``.
* **Default ordering** — Pane: ``(container_name, session_name,
  window_index, pane_index) ASC`` (already enforced by the DAO).
  Agent: ``(role_priority, registered_at) ASC`` (FR-021a normative).
* **Direction suffix** — ``field`` / ``field:asc`` / ``field:desc``
  (FR-021b). Unknown direction → ``validation_failed.details.field ==
  "order_by"``.
* **Filters** — Pane: ``container_id``, ``registered``. Agent: ``role``,
  ``capability``, ``container_id``, ``log_attached``. All exact-match
  (FR-024a).
* **Derived fields** — Pane: ``registered``, ``agent_id``. Agent:
  ``log_attached``, ``pane_active``, ``role_priority``. All computed
  via joins against the same SQLite connection.

Out of scope (intentionally deferred to dedicated tasks):

* Total-count vs total-estimate optimization on large fixtures (T085
  cursor-opacity contract test will exercise it).
* The remaining 5 entities (container, log_attachment, event, queue,
  route) — those are US3 work (T043..T047).
"""

from __future__ import annotations

import base64
import json
import sqlite3
from typing import TYPE_CHECKING, Any, Final

from . import envelope as _envelope
from . import sessions as _sessions
from . import view_models as _vm
from .errors import (
    AGENT_NOT_FOUND,
    INTERNAL_ERROR,
    PANE_NOT_FOUND,
    VALIDATION_FAILED,
)

if TYPE_CHECKING:
    from ..socket_api.methods import DaemonContext


DEFAULT_LIMIT: Final[int] = 50
MAX_LIMIT: Final[int] = 200
MAX_CURSOR_BYTES: Final[int] = 512


# ─── Pagination helpers ──────────────────────────────────────────────────


def _validate_limit(params: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    """FR-020a: limit default 50, cap 200, integer >= 1.

    Returns ``(limit, None)`` on success or ``(0, error_envelope)`` on
    validation failure.
    """
    raw = params.get("limit", DEFAULT_LIMIT)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0, _envelope.failure(
            VALIDATION_FAILED,
            "limit must be an integer",
            details={"field": "limit", "reason": "must be an integer"},
        )
    if raw < 1 or raw > MAX_LIMIT:
        return 0, _envelope.failure(
            VALIDATION_FAILED,
            f"limit must be in [1, {MAX_LIMIT}]",
            details={
                "field": "limit",
                "reason": f"out of bounds [1, {MAX_LIMIT}]",
            },
        )
    return raw, None


def _encode_cursor(offset: int, order_by: str, filters: dict[str, Any]) -> str | None:
    """Build an opaque cursor for the next page. Returns ``None`` for the
    final page (no more rows)."""
    payload = json.dumps(
        {"offset": offset, "order_by": order_by, "filters": filters},
        separators=(",", ":"),
        sort_keys=True,
    )
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    if len(encoded) > MAX_CURSOR_BYTES:
        # Should be unreachable given the simple JSON shape, but
        # enforce the FR-020b cap defensively.
        return None
    return encoded


def _decode_cursor(
    raw: Any,
    *,
    expected_order_by: str,
    expected_filters: dict[str, Any],
) -> tuple[int, dict[str, Any] | None]:
    """Decode an opaque cursor. Returns ``(offset, None)`` on success or
    ``(0, error_envelope)`` on any validation failure (FR-020b)."""
    if raw is None:
        return 0, None
    if not isinstance(raw, str):
        return 0, _envelope.failure(
            VALIDATION_FAILED,
            "cursor_next must be a string",
            details={"field": "cursor_next", "reason": "wrong type"},
        )
    if len(raw) > MAX_CURSOR_BYTES:
        return 0, _envelope.failure(
            VALIDATION_FAILED,
            f"cursor_next exceeds {MAX_CURSOR_BYTES} chars",
            details={"field": "cursor_next", "reason": "too long"},
        )
    try:
        decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
        body = json.loads(decoded)
    except Exception:  # noqa: BLE001 — malformed cursor is a client bug
        return 0, _envelope.failure(
            VALIDATION_FAILED,
            "cursor_next is not a valid daemon-issued cursor",
            details={"field": "cursor_next", "reason": "malformed"},
        )
    if not isinstance(body, dict):
        return 0, _envelope.failure(
            VALIDATION_FAILED,
            "cursor_next payload must be a JSON object",
            details={"field": "cursor_next", "reason": "malformed"},
        )
    if body.get("order_by") != expected_order_by:
        return 0, _envelope.failure(
            VALIDATION_FAILED,
            "cursor_next was issued under a different order_by",
            details={
                "field": "cursor_next",
                "reason": "order_by changed mid-pagination",
            },
        )
    if body.get("filters") != expected_filters:
        return 0, _envelope.failure(
            VALIDATION_FAILED,
            "cursor_next was issued under a different filter set",
            details={
                "field": "cursor_next",
                "reason": "filters changed mid-pagination",
            },
        )
    offset = body.get("offset")
    if not isinstance(offset, int) or offset < 0:
        return 0, _envelope.failure(
            VALIDATION_FAILED,
            "cursor_next has malformed offset",
            details={"field": "cursor_next", "reason": "bad offset"},
        )
    return offset, None


def _validate_order_by(
    raw: Any,
    *,
    field_set: frozenset[str],
    default_field: str,
    default_direction: str,
) -> tuple[str, str, str, dict[str, Any] | None]:
    """FR-021b: order_by accepts ``field``, ``field:asc``, ``field:desc``.

    Returns ``(field, direction, canonical_string, None)`` on success
    or ``("", "", "", error_envelope)`` on failure. ``canonical_string``
    is what gets stored in the cursor so cross-page consistency can be
    verified.
    """
    if raw is None:
        return (
            default_field,
            default_direction,
            f"{default_field}:{default_direction}",
            None,
        )
    if not isinstance(raw, str) or not raw:
        return "", "", "", _envelope.failure(
            VALIDATION_FAILED,
            "order_by must be a non-empty string",
            details={"field": "order_by", "reason": "wrong type"},
        )
    if ":" in raw:
        field, _, direction = raw.partition(":")
    else:
        field, direction = raw, default_direction
    if field not in field_set:
        return "", "", "", _envelope.failure(
            VALIDATION_FAILED,
            f"order_by field {field!r} is not in this surface's closed set",
            details={"field": "order_by", "reason": "unknown field"},
        )
    if direction not in ("asc", "desc"):
        return "", "", "", _envelope.failure(
            VALIDATION_FAILED,
            f"order_by direction must be asc or desc, got {direction!r}",
            details={"field": "order_by", "reason": "bad direction suffix"},
        )
    return field, direction, f"{field}:{direction}", None


# ─── Pane queries ────────────────────────────────────────────────────────


_PANE_ORDER_BY_FIELDS = frozenset({"default", "discovered_at", "last_seen_at"})


def _connect_state_db(ctx: "DaemonContext") -> sqlite3.Connection | None:
    """Open a fresh read-only-ish connection to the state DB.

    Returns ``None`` if ``ctx.state_path`` is unwired. Callers must
    close the connection in a ``finally`` block.
    """
    if ctx.state_path is None:
        return None
    try:
        return sqlite3.connect(str(ctx.state_path))
    except sqlite3.Error:
        return None


def _fetch_pane_agent_lookup(conn: sqlite3.Connection) -> dict[tuple, str]:
    """Return a mapping from a pane's composite key → linked agent_id
    for every **active** agent row. Panes whose composite key isn't in
    the map are unregistered (or only have inactive agents)."""
    rows = conn.execute(
        """
        SELECT agent_id, container_id, tmux_socket_path, tmux_session_name,
               tmux_window_index, tmux_pane_index, tmux_pane_id
        FROM agents
        WHERE active = 1
        """
    ).fetchall()
    return {
        (
            row[1],  # container_id
            row[2],  # tmux_socket_path
            row[3],  # tmux_session_name
            int(row[4]),
            int(row[5]),
            row[6],
        ): row[0]  # agent_id
        for row in rows
    }


def app_pane_list(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.pane.list`` (FR-019, FR-020, FR-021, FR-022, FR-024)."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    limit, err = _validate_limit(params)
    if err:
        return err

    _, _, canonical_order, err = _validate_order_by(
        params.get("order_by"),
        field_set=_PANE_ORDER_BY_FIELDS,
        default_field="default",
        default_direction="asc",
    )
    if err:
        return err

    filters_raw = params.get("filters") or {}
    if not isinstance(filters_raw, dict):
        return _envelope.failure(
            VALIDATION_FAILED,
            "filters must be an object",
            details={"field": "filters", "reason": "wrong type"},
        )
    # Pane filter closed set: container_id, registered.
    allowed = {"container_id", "registered"}
    for key in filters_raw:
        if key not in allowed:
            return _envelope.failure(
                VALIDATION_FAILED,
                f"unknown pane filter field: {key!r}",
                details={"field": key, "reason": "unknown filter"},
            )
    container_filter = filters_raw.get("container_id")
    registered_filter = filters_raw.get("registered")
    if container_filter is not None and not isinstance(container_filter, str):
        return _envelope.failure(
            VALIDATION_FAILED,
            "filters.container_id must be a string",
            details={"field": "container_id", "reason": "wrong type"},
        )
    if registered_filter is not None and not isinstance(registered_filter, bool):
        return _envelope.failure(
            VALIDATION_FAILED,
            "filters.registered must be a boolean",
            details={"field": "registered", "reason": "wrong type"},
        )

    offset, err = _decode_cursor(
        params.get("cursor_next"),
        expected_order_by=canonical_order,
        expected_filters=filters_raw,
    )
    if err:
        return err

    conn = _connect_state_db(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR,
            "state_path unwired or unreadable",
            details={},
        )
    try:
        from ..state import panes as state_panes

        all_panes = state_panes.select_panes_for_listing(
            conn,
            active_only=False,
            container_filter=container_filter if isinstance(container_filter, str) else None,
        )
        agent_lookup = _fetch_pane_agent_lookup(conn)
    except sqlite3.Error as exc:
        conn.close()
        return _envelope.failure(
            INTERNAL_ERROR,
            f"state-db query failed: {type(exc).__name__}: {exc}",
            details={},
        )
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    # Filter by registered:bool if requested.
    filtered_views: list[dict[str, Any]] = []
    for pane in all_panes:
        linked = agent_lookup.get(pane.composite_key)
        if registered_filter is not None:
            is_registered = linked is not None
            if is_registered != registered_filter:
                continue
        filtered_views.append(
            _vm.pane_view(
                {
                    "pane_id": pane.tmux_pane_id,
                    "container_id": pane.container_id,
                    "tmux_socket": pane.tmux_socket_path,
                    "session_name": pane.tmux_session_name,
                    "window_index": pane.tmux_window_index,
                    "pane_index": pane.tmux_pane_index,
                    "discovered_at": pane.first_seen_at,
                    "last_seen_at": pane.last_scanned_at,
                },
                linked_agent_id=linked,
                container_name=pane.container_name,
            )
        )

    total = len(filtered_views)
    page = filtered_views[offset : offset + limit]
    next_offset = offset + len(page)
    has_more = next_offset < total
    cursor_next = (
        _encode_cursor(next_offset, canonical_order, filters_raw) if has_more else None
    )

    return _envelope.success({
        "rows": page,
        "total": total,
        "total_estimate": None,
        "cursor_next": cursor_next,
        "ordering": canonical_order,
    })


def app_pane_detail(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.pane.detail`` — by ``pane_id`` (FR-019, FR-022).

    Returns ``pane_not_found`` when the id doesn't match any row.
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    pane_id = params.get("pane_id") if isinstance(params, dict) else None
    if not isinstance(pane_id, str) or not pane_id:
        return _envelope.failure(
            VALIDATION_FAILED,
            "pane_id must be a non-empty string",
            details={"field": "pane_id", "reason": "missing or wrong type"},
        )

    conn = _connect_state_db(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR,
            "state_path unwired or unreadable",
            details={},
        )
    try:
        from ..state import panes as state_panes

        all_panes = state_panes.select_panes_for_listing(conn, active_only=False)
        agent_lookup = _fetch_pane_agent_lookup(conn)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    # Linear scan — v1.0 fixture sizes are small.
    for pane in all_panes:
        if pane.tmux_pane_id == pane_id:
            linked = agent_lookup.get(pane.composite_key)
            return _envelope.success({
                "row": _vm.pane_view(
                    {
                        "pane_id": pane.tmux_pane_id,
                        "container_id": pane.container_id,
                        "tmux_socket": pane.tmux_socket_path,
                        "session_name": pane.tmux_session_name,
                        "window_index": pane.tmux_window_index,
                        "pane_index": pane.tmux_pane_index,
                        "discovered_at": pane.first_seen_at,
                        "last_seen_at": pane.last_scanned_at,
                    },
                    linked_agent_id=linked,
                    container_name=pane.container_name,
                )
            })
    return _envelope.failure(
        PANE_NOT_FOUND,
        f"pane_id {pane_id!r} not in panes table",
        details={"pane_id": pane_id},
    )


# ─── Agent queries ───────────────────────────────────────────────────────


_AGENT_ORDER_BY_FIELDS = frozenset({"default", "registered_at", "role"})


def _fetch_log_attached_set(conn: sqlite3.Connection) -> set[str]:
    """Return the set of ``agent_id`` values that currently have an
    **active** log_attachment row (FEAT-007 status enum: ``active`` |
    ``superseded`` | ``stale`` | ``detached``). Only ``active`` counts
    as "attached" for the FR-023 derived field. Empty set if the
    FEAT-007 table is absent."""
    try:
        rows = conn.execute(
            "SELECT agent_id FROM log_attachments WHERE status = 'active'"
        ).fetchall()
        return {row[0] for row in rows}
    except sqlite3.OperationalError:
        return set()


def _fetch_active_pane_keys(conn: sqlite3.Connection) -> set[tuple]:
    """Return the set of composite keys for currently-active panes."""
    try:
        rows = conn.execute(
            """
            SELECT container_id, tmux_socket_path, tmux_session_name,
                   tmux_window_index, tmux_pane_index, tmux_pane_id
            FROM panes
            WHERE active = 1
            """
        ).fetchall()
        return {
            (row[0], row[1], row[2], int(row[3]), int(row[4]), row[5])
            for row in rows
        }
    except sqlite3.OperationalError:
        return set()


def app_agent_list(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.agent.list`` (FR-019, FR-020, FR-021, FR-023, FR-024).

    Default ordering ``(role_priority, registered_at) ASC`` per FR-021a
    normative mapping. Filter fields: ``role``, ``capability``,
    ``container_id``, ``log_attached:bool``.
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    limit, err = _validate_limit(params)
    if err:
        return err

    _, _, canonical_order, err = _validate_order_by(
        params.get("order_by"),
        field_set=_AGENT_ORDER_BY_FIELDS,
        default_field="default",
        default_direction="asc",
    )
    if err:
        return err

    filters_raw = params.get("filters") or {}
    if not isinstance(filters_raw, dict):
        return _envelope.failure(
            VALIDATION_FAILED,
            "filters must be an object",
            details={"field": "filters", "reason": "wrong type"},
        )
    allowed = {"role", "capability", "container_id", "log_attached"}
    for key in filters_raw:
        if key not in allowed:
            return _envelope.failure(
                VALIDATION_FAILED,
                f"unknown agent filter field: {key!r}",
                details={"field": key, "reason": "unknown filter"},
            )
    role_filter = filters_raw.get("role")
    capability_filter = filters_raw.get("capability")
    container_filter = filters_raw.get("container_id")
    log_attached_filter = filters_raw.get("log_attached")
    for fname, fval in (
        ("role", role_filter),
        ("capability", capability_filter),
        ("container_id", container_filter),
    ):
        if fval is not None and not isinstance(fval, str):
            return _envelope.failure(
                VALIDATION_FAILED,
                f"filters.{fname} must be a string",
                details={"field": fname, "reason": "wrong type"},
            )
    if log_attached_filter is not None and not isinstance(log_attached_filter, bool):
        return _envelope.failure(
            VALIDATION_FAILED,
            "filters.log_attached must be a boolean",
            details={"field": "log_attached", "reason": "wrong type"},
        )

    offset, err = _decode_cursor(
        params.get("cursor_next"),
        expected_order_by=canonical_order,
        expected_filters=filters_raw,
    )
    if err:
        return err

    conn = _connect_state_db(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR,
            "state_path unwired or unreadable",
            details={},
        )
    try:
        from ..state import agents as state_agents

        agents = state_agents.list_agents(
            conn,
            role=[role_filter] if role_filter else None,
            container_id=container_filter if isinstance(container_filter, str) else None,
            active_only=False,
        )
        log_attached_ids = _fetch_log_attached_set(conn)
        active_pane_keys = _fetch_active_pane_keys(conn)
    except sqlite3.Error as exc:
        return _envelope.failure(
            INTERNAL_ERROR,
            f"state-db query failed: {type(exc).__name__}: {exc}",
            details={},
        )
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    # Apply remaining filters in Python (capability exact match,
    # log_attached derivation).
    from .versioning import ROLE_PRIORITY

    rows: list[dict[str, Any]] = []
    for agent in agents:
        if capability_filter is not None and agent.capability != capability_filter:
            continue
        log_attached = agent.agent_id in log_attached_ids
        if (
            log_attached_filter is not None
            and log_attached != log_attached_filter
        ):
            continue
        pane_active = agent.composite_key in active_pane_keys
        rows.append(
            _vm.agent_view(
                {
                    "agent_id": agent.agent_id,
                    "role": agent.role,
                    "capability": agent.capability,
                    "label": agent.label,
                    "project_path": agent.project_path,
                    "parent_agent_id": agent.parent_agent_id,
                    "container_id": agent.container_id,
                    "pane_id": agent.tmux_pane_id,
                    "registered_at": agent.created_at,
                },
                log_attached=log_attached,
                pane_active=pane_active,
            )
        )

    # Default ordering: (role_priority ASC, registered_at ASC) per FR-021a.
    # The DAO ordering is by creation; we re-sort defensively.
    if canonical_order in ("default:asc", "default:desc"):
        rows.sort(
            key=lambda r: (
                ROLE_PRIORITY.get(r["role"], 99),
                r["registered_at"] or "",
            ),
            reverse=(canonical_order == "default:desc"),
        )

    total = len(rows)
    page = rows[offset : offset + limit]
    next_offset = offset + len(page)
    has_more = next_offset < total
    cursor_next = (
        _encode_cursor(next_offset, canonical_order, filters_raw) if has_more else None
    )

    return _envelope.success({
        "rows": page,
        "total": total,
        "total_estimate": None,
        "cursor_next": cursor_next,
        "ordering": canonical_order,
    })


def app_agent_detail(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.agent.detail`` — by ``agent_id`` (FR-019, FR-023)."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    agent_id = params.get("agent_id") if isinstance(params, dict) else None
    if not isinstance(agent_id, str) or not agent_id:
        return _envelope.failure(
            VALIDATION_FAILED,
            "agent_id must be a non-empty string",
            details={"field": "agent_id", "reason": "missing or wrong type"},
        )

    conn = _connect_state_db(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR,
            "state_path unwired or unreadable",
            details={},
        )
    try:
        from ..state import agents as state_agents

        agent = state_agents.select_agent_by_id(conn, agent_id=agent_id)
        if agent is None:
            return _envelope.failure(
                AGENT_NOT_FOUND,
                f"agent_id {agent_id!r} not in agents table",
                details={"agent_id": agent_id},
            )
        log_attached_ids = _fetch_log_attached_set(conn)
        active_pane_keys = _fetch_active_pane_keys(conn)
    except sqlite3.Error as exc:
        return _envelope.failure(
            INTERNAL_ERROR,
            f"state-db query failed: {type(exc).__name__}: {exc}",
            details={},
        )
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    return _envelope.success({
        "row": _vm.agent_view(
            {
                "agent_id": agent.agent_id,
                "role": agent.role,
                "capability": agent.capability,
                "label": agent.label,
                "project_path": agent.project_path,
                "parent_agent_id": agent.parent_agent_id,
                "container_id": agent.container_id,
                "pane_id": agent.tmux_pane_id,
                "registered_at": agent.created_at,
            },
            log_attached=agent.agent_id in log_attached_ids,
            pane_active=agent.composite_key in active_pane_keys,
        )
    })


__all__ = [
    "app_pane_list",
    "app_pane_detail",
    "app_agent_list",
    "app_agent_detail",
]
