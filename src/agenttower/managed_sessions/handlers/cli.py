"""FEAT-013 legacy ``managed.*`` CLI socket handlers (T023).

Registered with the FEAT-002 socket dispatcher via :func:`register`
called from ``socket_api/methods.py`` at module-import time (T025).

Thin-client peer scoping per research §R12: bench-container callers may
only target their own container; cross-container requests return
``host_only``. Host peers may target any container.

The handlers verify ``container_id`` exists in the FEAT-003 container
registry **before** calling ``service.create_layout`` (else
``container_not_found``); ``ValidationFailedError`` and
``ManagedSessionsError`` from the service are translated into the
FEAT-002 envelope (``ok`` + ``result`` / ``error``).
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from ..dao import (
    count_ready_panes_for_layout,
    list_layouts,
    list_panes,
    select_layout,
    select_pane,
    select_panes_for_layout,
    select_predecessor_chain,
)
from ..errors import (
    CONTAINER_NOT_FOUND,
    MANAGED_LAYOUT_NOT_FOUND,
    MANAGED_PANE_NOT_FOUND,
    ManagedSessionsError,
)
from ..service import (
    ValidationFailedError,
    create_layout,
    promote_from_adopted,
    recreate_pane,
    remove_pane,
)
from ..state_machine import FailedStage, ManagedState
from ..view_models import ManagedLayoutView, ManagedPaneView, ORIGIN_MANAGED

if TYPE_CHECKING:
    from ...socket_api.methods import DaemonContext


# ─── envelope helpers ────────────────────────────────────────────────────


def _ok(result: dict[str, Any]) -> dict[str, Any]:
    """FEAT-002 legacy success envelope."""
    return {"ok": True, "result": result}


def _err(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """FEAT-002 legacy error envelope with FEAT-013 ``details``.

    FEAT-002's :func:`socket_api.errors.make_error` enforces its own
    closed-code set; FEAT-013 codes aren't in that set. We build the
    envelope directly here to keep FEAT-013's closed-set vocabulary on
    the wire without amending FEAT-002's registry (additive-evolution
    rule from contracts/managed-methods.md §Versioning).
    """
    body: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        body["details"] = details
    return {"ok": False, "error": body}


# ─── helpers ─────────────────────────────────────────────────────────────


def _container_exists(conn: sqlite3.Connection, container_id: str) -> bool:
    """Return True iff a FEAT-003 ``containers`` row exists with this id.

    FEAT-013 treats unknown ``container_id`` (no row) as
    ``container_not_found`` and leaves the "exists but inactive" case
    to the spawn-pipeline-side liveness probe (Phase 4 T029). Mirrors
    FEAT-011 mutations.py's pre-check pattern.
    """
    try:
        row = conn.execute(
            "SELECT 1 FROM containers WHERE container_id = ?",
            (container_id,),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def _peer_container_id(ctx: "DaemonContext", peer_uid: int) -> str | None:
    """Return the bench-container id the caller is running inside, or
    ``None`` if the caller is a host peer.

    Reuses FEAT-009's peer-detection surface (per research §R12). If
    peer detection isn't wired, returns ``None`` (treat as host) — this
    matches the legacy CLI's behavior pre-FEAT-013 and falls back to
    the safe path (host can target any container).
    """
    # Lazy import to keep handler-module load lightweight and avoid
    # cycles with socket_api.methods.
    from ...socket_api.methods import _peer_is_host_process, _request_peer_pid

    pid = _request_peer_pid()
    if pid <= 0:
        return None  # no peer credentials → treat as host
    if _peer_is_host_process(pid):
        return None
    # Bench-container peer. FEAT-009 records the peer's container_id in
    # the agents row keyed by tmux_pane_id; we look it up via the
    # peer_pid → /proc/<pid>/cgroup → docker container id chain that
    # FEAT-009 already implements.
    try:
        from ...agents.peer_detection import resolve_peer_container_id  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return resolve_peer_container_id(pid)
    except Exception:  # noqa: BLE001 — defensive: peer detection is best-effort
        return None


def _state_conn(ctx: "DaemonContext") -> sqlite3.Connection | None:
    """Pull the state DB connection from the daemon context.

    Returns None if unwired (defensive — production wiring is mandatory).
    """
    return getattr(ctx, "state_conn", None)


def _serializer(ctx: "DaemonContext") -> Any:
    """Pull the FEAT-013 container serializer from the daemon context.

    Wired into ``DaemonContext`` at daemon boot (Phase 4 follow-up). In
    contract tests, the test fixture sets ``ctx.managed_serializer``
    directly.
    """
    return getattr(ctx, "managed_serializer", None)


# ─── managed.layout.create ───────────────────────────────────────────────


def _managed_layout_create(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """Implements ``managed.layout.create`` (M1).

    Order of checks (matches contracts/managed-methods.md M1 errors list):

    1. Required-field shape (``container_id``, ``template_name``,
       ``tmux_session_name``) → ``validation_failed``.
    2. Thin-client peer scoping (R12) → ``host_only`` for cross-container.
    3. ``container_not_found`` if the FEAT-003 registry has no such id.
    4. Delegate to ``service.create_layout`` (which enforces FR-016
       charset/length validation, FR-019 serializer, FR-025 capacity,
       FR-003 label uniqueness, and the template / launch-profile
       resolvers).
    """
    if not isinstance(params, dict):
        params = {}

    container_id = params.get("container_id")
    template_name = params.get("template_name")
    tmux_session_name = params.get("tmux_session_name")
    launch_command_overrides = params.get("launch_command_overrides") or {}
    idempotency_key = params.get("idempotency_key")

    # 1. Required-field shape checks.
    for field, value in (
        ("container_id", container_id),
        ("template_name", template_name),
        ("tmux_session_name", tmux_session_name),
    ):
        if not isinstance(value, str) or not value:
            return _err(
                "validation_failed",
                f"missing or empty {field!r}",
                details={"field": field, "reason": "missing or empty"},
            )
    if launch_command_overrides and not isinstance(launch_command_overrides, dict):
        return _err(
            "validation_failed",
            "launch_command_overrides must be an object",
            details={"field": "launch_command_overrides", "reason": "wrong type"},
        )
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        return _err(
            "validation_failed",
            "idempotency_key must be a string when provided",
            details={"field": "idempotency_key", "reason": "wrong type"},
        )

    # 2. Thin-client peer scoping (R12): bench-container peers may only
    #    target their own container.
    peer_container = _peer_container_id(ctx, peer_uid)
    if peer_container is not None and peer_container != container_id:
        return _err(
            "host_only",
            "bench-container peers may only target their own container",
            details={
                "peer_container_id": peer_container,
                "requested_container_id": container_id,
            },
        )

    # 3. container_not_found pre-check (handler-layer concern; service
    #    trusts the handler to verify per contracts/managed-methods.md M1).
    conn = _state_conn(ctx)
    if conn is None:
        return _err("internal_error", "daemon state_conn not wired")
    if not _container_exists(conn, container_id):
        return _err(
            CONTAINER_NOT_FOUND,
            f"unknown container_id {container_id!r}",
            details={"container_id": container_id},
        )

    # 4. Serializer must be wired.
    serializer = _serializer(ctx)
    if serializer is None:
        return _err("internal_error", "daemon managed_serializer not wired")

    # 5. Delegate to the service.
    try:
        result = create_layout(
            conn=conn,
            serializer=serializer,
            container_id=container_id,
            template_name=template_name,
            tmux_session_name=tmux_session_name,
            launch_command_overrides=launch_command_overrides if launch_command_overrides else None,
            idempotency_key=idempotency_key,
        )
    except ValidationFailedError as exc:
        return _err(exc.code, str(exc), details=exc.details)
    except ManagedSessionsError as exc:
        return _err(exc.code, str(exc), details=exc.details)
    except Exception as exc:  # noqa: BLE001 — envelope-shape safety net
        return _err(
            "internal_error",
            f"managed.layout.create failed: {type(exc).__name__}",
        )

    return _ok(_layout_result_payload(result))


def _layout_result_payload(result: Any) -> dict[str, Any]:
    """Project a ``CreateLayoutResult`` into the M1 response shape."""
    return {
        "layout_id": result.layout_id,
        "state": _state_str(result.state),
        "intended_pane_count": result.intended_pane_count,
        "panes": [
            {
                "pane_id": p.pane_id,
                "role": p.role,
                "label": p.label,
                "state": _state_str(p.state),
            }
            for p in result.panes
        ],
        "replay": result.replay,
    }


def _state_str(state: Any) -> str:
    """Render a :class:`ManagedState` enum as its wire-format string."""
    if isinstance(state, ManagedState):
        return state.value
    return str(state)


# ─── M2-M5 list / detail handlers (T033 — Phase 4a) ─────────────────────


def _state_filter(value: Any) -> ManagedState | None:
    """Coerce an optional ``state`` filter param to a ManagedState, or
    ``None`` if absent. Raises a ValueError-wrapping inside a closed-set
    validation_failed if the value is non-string or not in the enum."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("state filter must be a string")
    try:
        return ManagedState(value)
    except ValueError:
        valid = ", ".join(s.value for s in ManagedState)
        raise ValueError(f"state filter must be one of: {valid}")


def _layout_row_to_view(row: Any, panes: list[ManagedPaneView] | None = None) -> ManagedLayoutView:
    """Project a ManagedLayoutRow → ManagedLayoutView (M2/M3 shape)."""
    return ManagedLayoutView(
        layout_id=row.id,
        container_id=row.container_id,
        template_name=row.template_name,
        intended_pane_count=row.intended_pane_count,
        state=row.state,
        failed_stage=row.failed_stage,
        idempotency_key=row.idempotency_key,
        created_at=row.created_at,
        updated_at=row.updated_at,
        panes=panes or [],
    )


def _pane_row_to_view(row: Any) -> ManagedPaneView:
    """Project a ManagedPaneRow → ManagedPaneView (M4/M5 shape)."""
    return ManagedPaneView(
        pane_id=row.id,
        layout_id=row.layout_id,
        container_id=row.container_id,
        role=row.role,
        capability=row.capability,
        label=row.label,
        state=row.state,
        tmux_session_name=row.tmux_session_name,
        tmux_pane_index=row.tmux_pane_index,
        chain_depth=row.chain_depth,
        created_at=row.created_at,
        updated_at=row.updated_at,
        agent_id=row.agent_id,
        launch_command_ref=row.launch_command_ref,
        pending_marker_token=row.pending_marker_token,
        failed_stage=row.failed_stage,
        predecessor_id=row.predecessor_id,
        # log_attached is FEAT-007's concern; it's threaded in Phase 4b
        # alongside the FEAT-007 log-attach wiring.
        log_attached=False,
    )


def _layout_view_to_list_payload(
    view: ManagedLayoutView, ready_pane_count: int
) -> dict[str, Any]:
    """Project a layout view into the M2 list-row payload (with ready_pane_count)."""
    return {
        "layout_id": view.layout_id,
        "container_id": view.container_id,
        "template_name": view.template_name,
        "state": view.state.value,
        "intended_pane_count": view.intended_pane_count,
        "ready_pane_count": ready_pane_count,
        "created_at": view.created_at,
        "origin": ORIGIN_MANAGED,
    }


def _pane_view_to_payload(view: ManagedPaneView) -> dict[str, Any]:
    """Project a pane view into the M3/M4/M5 pane payload shape."""
    payload: dict[str, Any] = {
        "pane_id": view.pane_id,
        "layout_id": view.layout_id,
        "container_id": view.container_id,
        "role": view.role,
        "capability": view.capability,
        "label": view.label,
        "state": view.state.value,
        "tmux_session_name": view.tmux_session_name,
        "tmux_pane_index": view.tmux_pane_index,
        "chain_depth": view.chain_depth,
        "agent_id": view.agent_id,
        "predecessor_id": view.predecessor_id,
        "log_attached": view.log_attached,
        "origin": ORIGIN_MANAGED,
    }
    if view.failed_stage is not None:
        payload["failed_stage"] = (
            view.failed_stage.value if isinstance(view.failed_stage, FailedStage)
            else str(view.failed_stage)
        )
    return payload


def _scope_to_peer_container(
    peer_container: str | None, requested_container_id: str | None
) -> tuple[str | None, dict[str, Any] | None]:
    """R12 thin-client peer scoping for list filters.

    If the caller is a bench-container peer:
    - cross-container explicit filters return ``host_only``
    - missing filter is silently scoped to the peer's container (per
      contracts/managed-methods.md §Bench-container thin-client peer scoping)
    """
    if peer_container is None:
        # Host peer (or unknown — treat as host per existing pattern).
        return requested_container_id, None
    if requested_container_id is not None and requested_container_id != peer_container:
        return None, _err(
            "host_only",
            "bench-container peers may only list their own container",
            details={
                "peer_container_id": peer_container,
                "requested_container_id": requested_container_id,
            },
        )
    return peer_container, None


def _managed_layout_list(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``managed.layout.list`` (M2) — paginated by ``(created_at DESC, id DESC)``."""
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _err("internal_error", "daemon state_conn not wired")

    peer_container = _peer_container_id(ctx, peer_uid)
    container_id, scope_err = _scope_to_peer_container(
        peer_container, params.get("container_id")
    )
    if scope_err is not None:
        return scope_err

    try:
        state = _state_filter(params.get("state"))
    except ValueError as exc:
        return _err(
            "validation_failed", str(exc),
            details={"field": "state", "reason": str(exc)},
        )

    limit = params.get("limit", 50)
    after = params.get("after")
    if after is not None and not isinstance(after, str):
        return _err(
            "validation_failed", "after cursor must be a string",
            details={"field": "after", "reason": "wrong type"},
        )

    rows, next_cursor = list_layouts(
        conn,
        container_id=container_id,
        state=state,
        limit=int(limit) if isinstance(limit, int) else 50,
        after=after,
    )

    items: list[dict[str, Any]] = []
    for layout_row in rows:
        ready = count_ready_panes_for_layout(conn, layout_row.id)
        items.append(_layout_view_to_list_payload(_layout_row_to_view(layout_row), ready))

    return _ok({"items": items, "next": next_cursor})


def _managed_layout_detail(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``managed.layout.detail`` (M3) — full layout + (optionally) terminal panes."""
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _err("internal_error", "daemon state_conn not wired")

    layout_id = params.get("layout_id")
    if not isinstance(layout_id, str) or not layout_id:
        return _err(
            "validation_failed", "missing or empty 'layout_id'",
            details={"field": "layout_id", "reason": "missing or empty"},
        )
    include_terminal = bool(params.get("include_terminal_panes", False))

    layout_row = select_layout(conn, layout_id)
    if layout_row is None:
        return _err(
            MANAGED_LAYOUT_NOT_FOUND,
            f"unknown layout_id {layout_id!r}",
            details={"layout_id": layout_id},
        )

    # R12 peer scoping — bench peer cannot read another container's layout.
    peer_container = _peer_container_id(ctx, peer_uid)
    if peer_container is not None and layout_row.container_id != peer_container:
        return _err(
            "host_only",
            "bench-container peers may only read their own container's layouts",
            details={
                "peer_container_id": peer_container,
                "layout_container_id": layout_row.container_id,
            },
        )

    panes = select_panes_for_layout(conn, layout_id)
    if not include_terminal:
        panes = [
            p for p in panes
            if p.state not in (ManagedState.REMOVED,)
        ]
    pane_views = [_pane_row_to_view(p) for p in panes]
    view = _layout_row_to_view(layout_row, panes=pane_views)
    return _ok(
        {
            "layout_id": view.layout_id,
            "container_id": view.container_id,
            "template_name": view.template_name,
            "state": view.state.value,
            "failed_stage": view.failed_stage.value if view.failed_stage else None,
            "intended_pane_count": view.intended_pane_count,
            "panes": [_pane_view_to_payload(p) for p in pane_views],
            "created_at": view.created_at,
            "updated_at": view.updated_at,
            "origin": ORIGIN_MANAGED,
        }
    )


def _managed_pane_list(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``managed.pane.list`` (M4) — filtered + paginated by ``(layout_id, tmux_pane_index, id)``."""
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _err("internal_error", "daemon state_conn not wired")

    peer_container = _peer_container_id(ctx, peer_uid)
    container_id, scope_err = _scope_to_peer_container(
        peer_container, params.get("container_id")
    )
    if scope_err is not None:
        return scope_err

    layout_id = params.get("layout_id")
    if layout_id is not None and not isinstance(layout_id, str):
        return _err(
            "validation_failed", "layout_id must be a string",
            details={"field": "layout_id", "reason": "wrong type"},
        )

    try:
        state = _state_filter(params.get("state"))
    except ValueError as exc:
        return _err(
            "validation_failed", str(exc),
            details={"field": "state", "reason": str(exc)},
        )

    limit = params.get("limit", 50)
    after = params.get("after")
    if after is not None and not isinstance(after, str):
        return _err(
            "validation_failed", "after cursor must be a string",
            details={"field": "after", "reason": "wrong type"},
        )

    rows, next_cursor = list_panes(
        conn,
        container_id=container_id,
        layout_id=layout_id,
        state=state,
        limit=int(limit) if isinstance(limit, int) else 50,
        after=after,
    )
    items = [_pane_view_to_payload(_pane_row_to_view(r)) for r in rows]
    return _ok({"items": items, "next": next_cursor})


def _managed_pane_detail(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``managed.pane.detail`` (M5) — single pane + optional predecessor chain."""
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _err("internal_error", "daemon state_conn not wired")

    pane_id = params.get("pane_id")
    if not isinstance(pane_id, str) or not pane_id:
        return _err(
            "validation_failed", "missing or empty 'pane_id'",
            details={"field": "pane_id", "reason": "missing or empty"},
        )
    include_chain = bool(params.get("include_predecessor_chain", False))

    row = select_pane(conn, pane_id)
    if row is None:
        return _err(
            MANAGED_PANE_NOT_FOUND,
            f"unknown pane_id {pane_id!r}",
            details={"pane_id": pane_id},
        )

    # R12 peer scoping.
    peer_container = _peer_container_id(ctx, peer_uid)
    if peer_container is not None and row.container_id != peer_container:
        return _err(
            "host_only",
            "bench-container peers may only read their own container's panes",
            details={
                "peer_container_id": peer_container,
                "pane_container_id": row.container_id,
            },
        )

    payload = _pane_view_to_payload(_pane_row_to_view(row))
    if include_chain and row.predecessor_id is not None:
        chain = select_predecessor_chain(conn, row.predecessor_id)
        payload["predecessor_chain"] = [
            {
                "pane_id": p.id,
                "state": p.state.value,
                "chain_depth": p.chain_depth,
                "predecessor_id": p.predecessor_id,
            }
            for p in chain
        ]
    return _ok(payload)


# ─── M6 / M7 / M8 lifecycle handlers (T048 — Phase 5c) ──────────────────


def _managed_pane_remove(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``managed.pane.remove`` (M6) — kill underlying tmux pane + cleanup
    routes/logs + transition to ``removed``. R12 peer scoping: thin-client
    peers may only remove panes in their own container."""
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _err("internal_error", "daemon state_conn not wired")
    serializer = _serializer(ctx)
    if serializer is None:
        return _err("internal_error", "daemon managed_serializer not wired")

    pane_id = params.get("pane_id")
    if not isinstance(pane_id, str) or not pane_id:
        return _err(
            "validation_failed", "missing or empty 'pane_id'",
            details={"field": "pane_id", "reason": "missing or empty"},
        )

    # R12 peer scoping — for known managed panes, refuse cross-container
    # operations from bench-container peers. (Unknown pane_id falls through
    # to service.remove_pane's protected_adopted / not_found check.)
    pane_row = select_pane(conn, pane_id)
    if pane_row is not None:
        peer_container = _peer_container_id(ctx, peer_uid)
        if peer_container is not None and pane_row.container_id != peer_container:
            return _err(
                "host_only",
                "bench-container peers may only remove panes in their own container",
                details={
                    "peer_container_id": peer_container,
                    "pane_container_id": pane_row.container_id,
                },
            )

    # Service performs the actual lifecycle work + raises closed-set errors.
    # The tmux kill / route / log cleanup backends are pulled from ctx
    # (production wiring) or default to None (test fixtures + the spawn-
    # backends factory pattern from Phase 4c).
    tmux_kill_fn = getattr(ctx, "managed_tmux_kill_fn", None)
    route_cleanup_fn = getattr(ctx, "managed_route_cleanup_fn", None)
    log_detach_fn = getattr(ctx, "managed_log_detach_fn", None)

    try:
        result = remove_pane(
            conn=conn, serializer=serializer, pane_id=pane_id,
            tmux_kill_fn=tmux_kill_fn,
            route_cleanup_fn=route_cleanup_fn,
            log_detach_fn=log_detach_fn,
        )
    except ManagedSessionsError as exc:
        return _err(exc.code, str(exc), details=exc.details)
    except Exception as exc:  # noqa: BLE001
        return _err(
            "internal_error",
            f"managed.pane.remove failed: {type(exc).__name__}",
        )

    return _ok({"pane_id": result.pane_id, "state": result.state.value})


def _managed_pane_recreate(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``managed.pane.recreate`` (M7) — produce a new pane row linked via
    ``predecessor_id``. Same R12 scoping + ctx-injected backends pattern
    as M6."""
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _err("internal_error", "daemon state_conn not wired")
    serializer = _serializer(ctx)
    if serializer is None:
        return _err("internal_error", "daemon managed_serializer not wired")

    predecessor_pane_id = params.get("predecessor_pane_id")
    if not isinstance(predecessor_pane_id, str) or not predecessor_pane_id:
        return _err(
            "validation_failed", "missing or empty 'predecessor_pane_id'",
            details={"field": "predecessor_pane_id", "reason": "missing or empty"},
        )

    launch_command_override = params.get("launch_command_override")
    if launch_command_override is not None and not isinstance(launch_command_override, str):
        return _err(
            "validation_failed", "launch_command_override must be a string when provided",
            details={"field": "launch_command_override", "reason": "wrong type"},
        )

    idempotency_key = params.get("idempotency_key")
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        return _err(
            "validation_failed", "idempotency_key must be a string when provided",
            details={"field": "idempotency_key", "reason": "wrong type"},
        )

    # R12 peer scoping — for known managed predecessors, refuse cross-
    # container recreate from a bench-container peer.
    predecessor = select_pane(conn, predecessor_pane_id)
    if predecessor is not None:
        peer_container = _peer_container_id(ctx, peer_uid)
        if peer_container is not None and predecessor.container_id != peer_container:
            return _err(
                "host_only",
                "bench-container peers may only recreate panes in their own container",
                details={
                    "peer_container_id": peer_container,
                    "pane_container_id": predecessor.container_id,
                },
            )

    try:
        result = recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id=predecessor_pane_id,
            launch_command_override=launch_command_override,
            idempotency_key=idempotency_key,
        )
    except ManagedSessionsError as exc:
        return _err(exc.code, str(exc), details=exc.details)
    except Exception as exc:  # noqa: BLE001
        return _err(
            "internal_error",
            f"managed.pane.recreate failed: {type(exc).__name__}",
        )

    return _ok({
        "pane_id": result.pane_id,
        "predecessor_id": result.predecessor_id,
        "chain_depth": result.chain_depth,
        "state": result.state.value,
    })


def _managed_pane_promote_from_adopted(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``managed.pane.promote_from_adopted`` (M8) — STUB. Always returns
    ``not_implemented`` with ``details.reserved_since = "FEAT-013"``."""
    if not isinstance(params, dict):
        params = {}
    agent_id = params.get("agent_id", "")
    if not isinstance(agent_id, str):
        agent_id = ""
    stub = promote_from_adopted(agent_id)
    return _err(stub.error_code, "promote_from_adopted is reserved for a later feature",
                details=stub.details)


# ─── Registration ────────────────────────────────────────────────────────


_LEGACY_METHODS: dict[str, Any] = {
    "managed.layout.create": _managed_layout_create,
    "managed.layout.list": _managed_layout_list,
    "managed.layout.detail": _managed_layout_detail,
    "managed.pane.list": _managed_pane_list,
    "managed.pane.detail": _managed_pane_detail,
    "managed.pane.remove": _managed_pane_remove,
    "managed.pane.recreate": _managed_pane_recreate,
    "managed.pane.promote_from_adopted": _managed_pane_promote_from_adopted,
}


def register() -> dict[str, Any]:
    """Return the legacy ``managed.*`` method → handler mapping.

    Imported by ``socket_api/methods.py`` at module-import time (T025);
    the returned dict is merged into the FEAT-002 ``DISPATCH`` table
    after the FEAT-011 ``APP_DISPATCH`` merge. Purely additive — no
    existing method binding is altered.
    """
    return dict(_LEGACY_METHODS)


__all__ = [
    "register",
]
