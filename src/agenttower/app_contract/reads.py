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
    NOT_FOUND,
    PANE_NOT_FOUND,
    QUEUE_MESSAGE_NOT_FOUND,
    ROUTE_NOT_FOUND,
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


def _resolve_state_db_path(ctx: "DaemonContext"):
    """Coerce ``ctx.state_path`` to the SQLite file path.

    The production daemon sets ``state_path`` to the **state directory**
    (containing ``agenttower.sqlite3``), while in-process tests often
    point ``state_path`` directly at the file. Accept both: if the path
    is a directory, return ``state_path / "agenttower.sqlite3"``;
    otherwise return ``state_path`` unchanged.
    """
    from pathlib import Path

    if ctx.state_path is None:
        return None
    p = Path(str(ctx.state_path))
    if p.is_dir():
        return p / "agenttower.sqlite3"
    return p


def _connect_state_db(ctx: "DaemonContext") -> sqlite3.Connection | None:
    """Open a fresh read-only-ish connection to the state DB.

    Returns ``None`` if ``ctx.state_path`` is unwired or the resolved
    file doesn't exist. Callers must close the connection in a
    ``finally`` block.
    """
    path = _resolve_state_db_path(ctx)
    if path is None:
        return None
    try:
        return sqlite3.connect(str(path))
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

    order_field, order_direction, canonical_order, err = _validate_order_by(
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
        return _envelope.internal_error_logged("state-db query", exc)
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

    # Apply the requested (or default) ordering before paginating. FR-021
    # pane default order is (container_name, session_name, window_index,
    # pane_index) ASC; an explicit order_by names a single view-model field.
    # Without this the order_by param was validated and recorded into the
    # cursor but never actually applied (review finding — app_pane_list was
    # the only list handler missing the _sort_rows call).
    _sort_rows(
        filtered_views,
        order_field,
        order_direction,
        default_keys=(
            "container_name",
            "session_name",
            "window_index",
            "pane_index",
        ),
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
        return _envelope.internal_error_logged("state-db query", exc)
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
        return _envelope.internal_error_logged("state-db query", exc)
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


# ─── US3 entity-read shared plumbing ─────────────────────────────────────


# FR-024a / SC-018: v1.0 filters are exact-match only. A filter *value*
# carrying operator-like syntax must be rejected — the daemon never
# interprets `<`, `>`, `~`, SQL `LIKE` wildcards (`*`, `%`), so silently
# matching them exactly would surprise a client expecting operator
# semantics. Adding real operators is an additive minor (FR-035).
_FILTER_OPERATOR_CHARS: frozenset[str] = frozenset("<>~*%")


def _filter_value_operator(value: Any) -> str | None:
    """Return the offending operator token in a filter value, or ``None``.

    Only string values can carry operator syntax; non-strings (the
    boolean ``enabled`` filter, integers) are returned as clean.
    """
    if not isinstance(value, str):
        return None
    for ch in value:
        if ch in _FILTER_OPERATOR_CHARS:
            return ch
    # SQL `LIKE` as a standalone token (case-insensitive).
    if "like" in value.lower().split():
        return "LIKE"
    return None


def _validate_filters_object(
    params: dict[str, Any], allowed: set[str], entity: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Coerce ``params['filters']`` to a dict, reject unknown keys, and
    reject operator-laden values.

    Returns ``(filters, None)`` on success or ``({}, error_envelope)`` on
    failure. ``error.details.field`` is the offending filter field name
    (FR-024a). An unknown filter field is the offending field; a
    non-object ``filters`` value yields ``details.field == "filters"``;
    an operator-laden value yields ``details.field`` set to that filter's
    key with ``details.reason == "operator syntax not supported"``.
    """
    filters_raw = params.get("filters") or {}
    if not isinstance(filters_raw, dict):
        return {}, _envelope.failure(
            VALIDATION_FAILED,
            "filters must be an object",
            details={"field": "filters", "reason": "wrong type"},
        )
    for key in filters_raw:
        if key not in allowed:
            return {}, _envelope.failure(
                VALIDATION_FAILED,
                f"unknown {entity} filter field: {key!r}",
                details={"field": key, "reason": "unknown filter"},
            )
    for key, value in filters_raw.items():
        operator = _filter_value_operator(value)
        if operator is not None:
            return {}, _envelope.failure(
                VALIDATION_FAILED,
                f"{entity} filter {key!r} is exact-match only; "
                f"operator syntax ({operator!r}) is not supported at v1.0",
                details={"field": key, "reason": "operator syntax not supported"},
            )
    return filters_raw, None


def _require_string_param(
    params: dict[str, Any], field: str
) -> tuple[str, dict[str, Any] | None]:
    """Validate that ``params[field]`` is a non-empty string (for
    ``.detail`` id params). Returns ``(value, None)`` or
    ``("", error_envelope)``."""
    value = params.get(field) if isinstance(params, dict) else None
    if not isinstance(value, str) or not value:
        return "", _envelope.failure(
            VALIDATION_FAILED,
            f"{field} must be a non-empty string",
            details={"field": field, "reason": "missing or wrong type"},
        )
    return value, None


def _paginate(
    rows: list[dict[str, Any]],
    *,
    offset: int,
    limit: int,
    canonical_order: str,
    filters: dict[str, Any],
) -> dict[str, Any]:
    """Apply offset/limit slicing and build the standard list envelope.

    ``rows`` must already be projected through a view-model builder and
    sorted in the resolved order. Identical to the slicing block used by
    ``app_pane_list`` / ``app_agent_list``.
    """
    total = len(rows)
    page = rows[offset : offset + limit]
    next_offset = offset + len(page)
    has_more = next_offset < total
    cursor_next = (
        _encode_cursor(next_offset, canonical_order, filters) if has_more else None
    )
    return _envelope.success({
        "rows": page,
        "total": total,
        "total_estimate": None,
        "cursor_next": cursor_next,
        "ordering": canonical_order,
    })


def _sort_rows(
    rows: list[dict[str, Any]],
    field: str,
    direction: str,
    *,
    default_keys: tuple[str, ...],
) -> None:
    """In-place sort of projected view-model rows.

    ``default_keys`` is the composite key tuple used for the ``default``
    order_by. For any non-``default`` order_by field the field name is
    itself the view-model key to sort on (every per-surface closed set
    names fields that are present verbatim on the view model).
    """
    keys = default_keys if field == "default" else (field,)

    def sort_key(r: dict[str, Any]) -> tuple:
        out: list[Any] = []
        for k in keys:
            v = r.get(k)
            # Normalize None so comparisons never raise across rows.
            out.append((v is None, v if v is not None else ""))
        return tuple(out)

    rows.sort(key=sort_key, reverse=(direction == "desc"))


# ─── Container queries (T054) ────────────────────────────────────────────


_CONTAINER_ORDER_BY_FIELDS = frozenset(
    {"name", "first_seen_at", "last_scanned_at"}
)
_CONTAINER_STATE_SET = frozenset({"active", "inactive", "degraded_scan"})


def _derive_container_state(active: Any) -> str:
    """FR-016a state bucket. ``degraded_scan`` needs FEAT-004 scan-health
    data not available at v1.0, so this collapses to ``active`` /
    ``inactive`` from the FEAT-003 ``active`` column (documented
    simplification)."""
    return "active" if bool(active) else "inactive"


def _project_container(row: Any) -> dict[str, Any]:
    return _vm.container_view(
        {
            "container_id": row.container_id,
            "name": row.name,
            "image": row.image,
            "first_seen_at": row.first_seen_at,
            "last_scanned_at": row.last_scanned_at,
        },
        derived_state=_derive_container_state(row.active),
    )


def app_container_list(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.container.list`` (FR-019..FR-024). Default order ``name ASC``."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    limit, err = _validate_limit(params)
    if err:
        return err

    field, direction, canonical_order, err = _validate_order_by(
        params.get("order_by"),
        field_set=_CONTAINER_ORDER_BY_FIELDS,
        default_field="name",
        default_direction="asc",
    )
    if err:
        return err

    filters_raw, err = _validate_filters_object(params, {"state"}, "container")
    if err:
        return err
    state_filter = filters_raw.get("state")
    if state_filter is not None and not isinstance(state_filter, str):
        return _envelope.failure(
            VALIDATION_FAILED,
            "filters.state must be a string",
            details={"field": "state", "reason": "wrong type"},
        )
    if state_filter is not None and state_filter not in _CONTAINER_STATE_SET:
        return _envelope.failure(
            VALIDATION_FAILED,
            f"filters.state {state_filter!r} is not a valid container state",
            details={"field": "state", "reason": "unknown value"},
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
            INTERNAL_ERROR, "state_path unwired or unreadable", details={}
        )
    try:
        from ..state import containers as state_containers

        containers = state_containers.select_containers(conn, active_only=False)
    except sqlite3.Error as exc:
        return _envelope.internal_error_logged("state-db query", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    rows: list[dict[str, Any]] = []
    for ctr in containers:
        view = _project_container(ctr)
        if state_filter is not None and view["state"] != state_filter:
            continue
        rows.append(view)

    _sort_rows(
        rows, field, direction, default_keys=("name",)
    )
    return _paginate(
        rows,
        offset=offset,
        limit=limit,
        canonical_order=canonical_order,
        filters=filters_raw,
    )


def app_container_detail(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.container.detail`` — by ``container_id``."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    container_id, err = _require_string_param(params, "container_id")
    if err:
        return err

    conn = _connect_state_db(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "state_path unwired or unreadable", details={}
        )
    try:
        from ..state import containers as state_containers

        containers = state_containers.select_containers(conn, active_only=False)
    except sqlite3.Error as exc:
        return _envelope.internal_error_logged("state-db query", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    for ctr in containers:
        if ctr.container_id == container_id:
            return _envelope.success({"row": _project_container(ctr)})
    return _envelope.failure(
        NOT_FOUND,
        f"container_id {container_id!r} not in containers table",
        details={},
    )


# ─── Log-attachment queries (T055) ───────────────────────────────────────


_LOG_ATTACHMENT_ORDER_BY_FIELDS = frozenset(
    {"attached_at", "last_status_at", "status"}
)

_LOG_ATTACHMENT_COLUMNS = (
    "attachment_id, agent_id, container_id, log_path, status, source, "
    "attached_at, last_status_at"
)


def _row_to_log_attachment(row: tuple) -> dict[str, Any]:
    return _vm.log_attachment_view(
        {
            "attachment_id": row[0],
            "agent_id": row[1],
            "container_id": row[2],
            "log_path": row[3],
            "status": row[4],
            "source": row[5],
            "attached_at": row[6],
            "last_status_at": row[7],
        }
    )


def app_log_attachment_list(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.log_attachment.list``. Default order ``last_status_at DESC``."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    limit, err = _validate_limit(params)
    if err:
        return err

    field, direction, canonical_order, err = _validate_order_by(
        params.get("order_by"),
        field_set=_LOG_ATTACHMENT_ORDER_BY_FIELDS,
        default_field="last_status_at",
        default_direction="desc",
    )
    if err:
        return err

    filters_raw, err = _validate_filters_object(
        params, {"agent_id", "status"}, "log_attachment"
    )
    if err:
        return err
    for fname in ("agent_id", "status"):
        fval = filters_raw.get(fname)
        if fval is not None and not isinstance(fval, str):
            return _envelope.failure(
                VALIDATION_FAILED,
                f"filters.{fname} must be a string",
                details={"field": fname, "reason": "wrong type"},
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
            INTERNAL_ERROR, "state_path unwired or unreadable", details={}
        )
    try:
        where: list[str] = []
        sql_params: list[Any] = []
        agent_filter = filters_raw.get("agent_id")
        status_filter = filters_raw.get("status")
        if agent_filter is not None:
            where.append("agent_id = ?")
            sql_params.append(agent_filter)
        if status_filter is not None:
            where.append("status = ?")
            sql_params.append(status_filter)
        sql = f"SELECT {_LOG_ATTACHMENT_COLUMNS} FROM log_attachments"
        if where:
            sql += " WHERE " + " AND ".join(where)
        db_rows = conn.execute(sql, tuple(sql_params)).fetchall()
    except sqlite3.Error as exc:
        return _envelope.internal_error_logged("state-db query", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    rows = [_row_to_log_attachment(r) for r in db_rows]
    _sort_rows(
        rows, field, direction, default_keys=("last_status_at",)
    )
    return _paginate(
        rows,
        offset=offset,
        limit=limit,
        canonical_order=canonical_order,
        filters=filters_raw,
    )


def app_log_attachment_detail(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.log_attachment.detail`` — by ``attachment_id``."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    attachment_id, err = _require_string_param(params, "attachment_id")
    if err:
        return err

    conn = _connect_state_db(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "state_path unwired or unreadable", details={}
        )
    try:
        db_row = conn.execute(
            f"SELECT {_LOG_ATTACHMENT_COLUMNS} FROM log_attachments "
            "WHERE attachment_id = ?",
            (attachment_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        return _envelope.internal_error_logged("state-db query", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    if db_row is None:
        return _envelope.failure(
            NOT_FOUND,
            f"attachment_id {attachment_id!r} not in log_attachments table",
            details={},
        )
    return _envelope.success({"row": _row_to_log_attachment(db_row)})


# ─── Event queries (T056) ────────────────────────────────────────────────


_EVENT_ORDER_BY_FIELDS = frozenset({"event_id", "observed_at"})

_EVENT_COLUMNS = (
    "event_id, event_type, agent_id, observed_at, excerpt, classifier_rule_id"
)


def _row_to_event(row: tuple) -> dict[str, Any]:
    return _vm.event_view(
        {
            "event_id": row[0],
            "event_type": row[1],
            "agent_id": row[2],
            "observed_at": row[3],
            "excerpt": row[4],
            "classifier_rule_id": row[5],
        }
    )


def app_event_list(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.event.list``. Default order ``event_id DESC``.

    Filters: ``event_type``, ``agent_id`` (exact match) and the paired
    ``since`` / ``until`` time-range params (matched against
    ``observed_at``). ``since > until`` → ``validation_failed``.
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    limit, err = _validate_limit(params)
    if err:
        return err

    field, direction, canonical_order, err = _validate_order_by(
        params.get("order_by"),
        field_set=_EVENT_ORDER_BY_FIELDS,
        default_field="event_id",
        default_direction="desc",
    )
    if err:
        return err

    filters_raw, err = _validate_filters_object(
        params, {"event_type", "agent_id", "since", "until"}, "event"
    )
    if err:
        return err
    for fname in ("event_type", "agent_id"):
        fval = filters_raw.get(fname)
        if fval is not None and not isinstance(fval, str):
            return _envelope.failure(
                VALIDATION_FAILED,
                f"filters.{fname} must be a string",
                details={"field": fname, "reason": "wrong type"},
            )
    since = filters_raw.get("since")
    until = filters_raw.get("until")
    if since is not None and until is not None and since > until:
        return _envelope.failure(
            VALIDATION_FAILED,
            "since must not be after until",
            details={"field": "since", "reason": "after until"},
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
            INTERNAL_ERROR, "state_path unwired or unreadable", details={}
        )
    try:
        where = []
        sql_params: list[Any] = []
        if filters_raw.get("event_type") is not None:
            where.append("event_type = ?")
            sql_params.append(filters_raw["event_type"])
        if filters_raw.get("agent_id") is not None:
            where.append("agent_id = ?")
            sql_params.append(filters_raw["agent_id"])
        if since is not None:
            where.append("observed_at >= ?")
            sql_params.append(since)
        if until is not None:
            where.append("observed_at <= ?")
            sql_params.append(until)
        sql = f"SELECT {_EVENT_COLUMNS} FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        db_rows = conn.execute(sql, tuple(sql_params)).fetchall()
    except sqlite3.Error as exc:
        return _envelope.internal_error_logged("state-db query", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    rows = [_row_to_event(r) for r in db_rows]
    _sort_rows(rows, field, direction, default_keys=("event_id",))
    return _paginate(
        rows,
        offset=offset,
        limit=limit,
        canonical_order=canonical_order,
        filters=filters_raw,
    )


def app_event_detail(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.event.detail`` — by ``event_id`` (integer-valued string)."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    raw_id = params.get("event_id") if isinstance(params, dict) else None
    # event_id is an integer PK; accept int or numeric string per the
    # generic detail param convention.
    event_id: int | None = None
    if isinstance(raw_id, bool):
        event_id = None
    elif isinstance(raw_id, int):
        event_id = raw_id
    elif isinstance(raw_id, str) and raw_id:
        try:
            event_id = int(raw_id)
        except ValueError:
            event_id = None
    if event_id is None:
        return _envelope.failure(
            VALIDATION_FAILED,
            "event_id must be an integer or integer-valued string",
            details={"field": "event_id", "reason": "missing or wrong type"},
        )

    conn = _connect_state_db(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "state_path unwired or unreadable", details={}
        )
    try:
        db_row = conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        return _envelope.internal_error_logged("state-db query", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    if db_row is None:
        return _envelope.failure(
            NOT_FOUND,
            f"event_id {event_id!r} not in events table",
            details={},
        )
    return _envelope.success({"row": _row_to_event(db_row)})


# ─── Queue queries (T057) ────────────────────────────────────────────────


_QUEUE_ORDER_BY_FIELDS = frozenset(
    {"default", "enqueued_at", "last_updated_at"}
)

_QUEUE_COLUMNS = (
    "message_id, state, block_reason, failure_reason, sender_agent_id, "
    "target_agent_id, enqueued_at, last_updated_at"
)


def _row_to_queue(row: tuple) -> dict[str, Any]:
    return _vm.queue_view(
        {
            "message_id": row[0],
            "state": row[1],
            "block_reason": row[2],
            "failure_reason": row[3],
            "sender_agent_id": row[4],
            "target_agent_id": row[5],
            # FR (Round-5): raw envelope_body is bytes; do not expose.
            # payload redaction is non-trivial — surface "" at v1.0.
            "payload_preview": "",
            "enqueued_at": row[6],
            "last_updated_at": row[7],
        }
    )


def app_queue_list(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.queue.list``. Default order ``(state_priority, enqueued_at) ASC``."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    limit, err = _validate_limit(params)
    if err:
        return err

    field, direction, canonical_order, err = _validate_order_by(
        params.get("order_by"),
        field_set=_QUEUE_ORDER_BY_FIELDS,
        default_field="default",
        default_direction="asc",
    )
    if err:
        return err

    filters_raw, err = _validate_filters_object(
        params,
        {"state", "sender_agent_id", "target_agent_id", "since", "until"},
        "queue",
    )
    if err:
        return err
    for fname in ("state", "sender_agent_id", "target_agent_id"):
        fval = filters_raw.get(fname)
        if fval is not None and not isinstance(fval, str):
            return _envelope.failure(
                VALIDATION_FAILED,
                f"filters.{fname} must be a string",
                details={"field": fname, "reason": "wrong type"},
            )
    since = filters_raw.get("since")
    until = filters_raw.get("until")
    if since is not None and until is not None and since > until:
        return _envelope.failure(
            VALIDATION_FAILED,
            "since must not be after until",
            details={"field": "since", "reason": "after until"},
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
            INTERNAL_ERROR, "state_path unwired or unreadable", details={}
        )
    try:
        where = []
        sql_params: list[Any] = []
        for col in ("state", "sender_agent_id", "target_agent_id"):
            if filters_raw.get(col) is not None:
                where.append(f"{col} = ?")
                sql_params.append(filters_raw[col])
        if since is not None:
            where.append("enqueued_at >= ?")
            sql_params.append(since)
        if until is not None:
            where.append("enqueued_at <= ?")
            sql_params.append(until)
        sql = f"SELECT {_QUEUE_COLUMNS} FROM message_queue"
        if where:
            sql += " WHERE " + " AND ".join(where)
        db_rows = conn.execute(sql, tuple(sql_params)).fetchall()
    except sqlite3.Error as exc:
        return _envelope.internal_error_logged("state-db query", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    rows = [_row_to_queue(r) for r in db_rows]
    # Default ordering is the composite (state_priority, enqueued_at).
    _sort_rows(
        rows,
        field,
        direction,
        default_keys=("state_priority", "enqueued_at"),
    )
    return _paginate(
        rows,
        offset=offset,
        limit=limit,
        canonical_order=canonical_order,
        filters=filters_raw,
    )


def app_queue_detail(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.queue.detail`` — by ``message_id``.

    Not-found code is ``queue_message_not_found`` (FR-034a requires
    ``details.message_id``).
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    message_id, err = _require_string_param(params, "message_id")
    if err:
        return err

    conn = _connect_state_db(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "state_path unwired or unreadable", details={}
        )
    try:
        db_row = conn.execute(
            f"SELECT {_QUEUE_COLUMNS} FROM message_queue WHERE message_id = ?",
            (message_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        return _envelope.internal_error_logged("state-db query", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    if db_row is None:
        return _envelope.failure(
            QUEUE_MESSAGE_NOT_FOUND,
            f"message_id {message_id!r} not in message_queue table",
            details={"message_id": message_id},
        )
    return _envelope.success({"row": _row_to_queue(db_row)})


# ─── Route queries (T058) ────────────────────────────────────────────────


_ROUTE_ORDER_BY_FIELDS = frozenset({"default", "created_at", "updated_at"})

_ROUTE_COLUMNS = (
    "route_id, event_type, source_scope_kind, source_scope_value, "
    "target_rule, target_value, master_rule, master_value, template, "
    "enabled, last_consumed_event_id, created_at, updated_at"
)


def _row_to_route(row: tuple) -> dict[str, Any]:
    return _vm.route_view(
        {
            "route_id": row[0],
            "event_type": row[1],
            "source_scope_kind": row[2],
            "source_scope_value": row[3],
            "target_rule": row[4],
            "target_value": row[5],
            "master_rule": row[6],
            "master_value": row[7],
            "template": row[8],
            "enabled": row[9],
            "last_consumed_event_id": row[10],
            "created_at": row[11],
            "updated_at": row[12],
        }
    )


def app_route_list(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.route.list``. Default order ``(created_at, route_id) ASC``."""
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    limit, err = _validate_limit(params)
    if err:
        return err

    field, direction, canonical_order, err = _validate_order_by(
        params.get("order_by"),
        field_set=_ROUTE_ORDER_BY_FIELDS,
        default_field="default",
        default_direction="asc",
    )
    if err:
        return err

    filters_raw, err = _validate_filters_object(params, {"enabled"}, "route")
    if err:
        return err
    enabled_filter = filters_raw.get("enabled")
    if enabled_filter is not None and not isinstance(enabled_filter, bool):
        return _envelope.failure(
            VALIDATION_FAILED,
            "filters.enabled must be a boolean",
            details={"field": "enabled", "reason": "wrong type"},
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
            INTERNAL_ERROR, "state_path unwired or unreadable", details={}
        )
    try:
        sql = f"SELECT {_ROUTE_COLUMNS} FROM routes"
        sql_params: tuple = ()
        if enabled_filter is not None:
            sql += " WHERE enabled = ?"
            sql_params = (1 if enabled_filter else 0,)
        db_rows = conn.execute(sql, sql_params).fetchall()
    except sqlite3.Error as exc:
        return _envelope.internal_error_logged("state-db query", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    rows = [_row_to_route(r) for r in db_rows]
    _sort_rows(
        rows,
        field,
        direction,
        default_keys=("created_at", "route_id"),
    )
    return _paginate(
        rows,
        offset=offset,
        limit=limit,
        canonical_order=canonical_order,
        filters=filters_raw,
    )


def app_route_detail(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """``app.route.detail`` — by ``route_id``.

    Not-found code is ``route_not_found`` (FR-034a requires
    ``details.route_id``).
    """
    session = _sessions.gate_session_required(params, peer_uid)
    if isinstance(session, dict):
        return session

    route_id, err = _require_string_param(params, "route_id")
    if err:
        return err

    conn = _connect_state_db(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "state_path unwired or unreadable", details={}
        )
    try:
        db_row = conn.execute(
            f"SELECT {_ROUTE_COLUMNS} FROM routes WHERE route_id = ?",
            (route_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        return _envelope.internal_error_logged("state-db query", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    if db_row is None:
        return _envelope.failure(
            ROUTE_NOT_FOUND,
            f"route_id {route_id!r} not in routes table",
            details={"route_id": route_id},
        )
    return _envelope.success({"row": _row_to_route(db_row)})


__all__ = [
    "app_pane_list",
    "app_pane_detail",
    "app_agent_list",
    "app_agent_detail",
    "app_container_list",
    "app_container_detail",
    "app_log_attachment_list",
    "app_log_attachment_detail",
    "app_event_list",
    "app_event_detail",
    "app_queue_list",
    "app_queue_detail",
    "app_route_list",
    "app_route_detail",
]
