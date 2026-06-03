"""FEAT-013 ``app.managed_*`` host-only socket handlers (T024).

Registered with FEAT-011's ``app_contract`` dispatcher via :func:`register`
called from ``app_contract/dispatcher.py`` (T025). Uses FEAT-011's
host-only peer gate (``host_only`` rejection for bench-container peers).

Same service entry point as the legacy CLI handler — this module wraps
it in the FEAT-011 envelope (``ok`` + ``app_contract_version`` + ``result``
/ ``error``). FEAT-011's ``_wrap_handler`` (in dispatcher.py) provides
the safety net that turns unexpected exceptions into a structurally-valid
``internal_error`` envelope; this module only needs to surface FEAT-013's
own closed-set errors.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from ...app_contract import envelope as _envelope
from ...app_contract.errors import (
    HOST_ONLY,
    INTERNAL_ERROR,
    VALIDATION_FAILED,
)
# NOTE: host_only is imported lazily inside each handler — eagerly
# importing it here triggers a circular import with socket_api.methods
# (which itself imports APP_DISPATCH at module load to merge with the
# legacy DISPATCH table). The pre-existing FEAT-011 handlers
# (preflight.py, hello.py, sessions.py) use the same lazy pattern.
from ..dao import (
    count_ready_panes_for_layout,
    count_ready_panes_for_layouts,
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


# ─── helpers ─────────────────────────────────────────────────────────────


def _container_exists(conn: sqlite3.Connection, container_id: str) -> bool:
    """Same predicate as the legacy handler — mirrored here to avoid an
    inter-handler import that would couple the two namespaces.
    """
    try:
        row = conn.execute(
            "SELECT 1 FROM containers WHERE container_id = ?",
            (container_id,),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def _state_conn(ctx: "DaemonContext") -> sqlite3.Connection | None:
    return getattr(ctx, "state_conn", None)


def _serializer(ctx: "DaemonContext") -> Any:
    return getattr(ctx, "managed_serializer", None)


def _session_conflict_fn(ctx: "DaemonContext"):  # noqa: ANN202
    """FR-016 synchronous session-name conflict checker (``session_conflict``
    backend), or ``None`` when spawn backends aren't boot-wired."""
    backends = getattr(ctx, "managed_spawn_backends", None)
    if not backends:
        return None
    return backends.get("session_conflict")


def _remove_pane_backends(ctx: "DaemonContext"):  # noqa: ANN202
    """FR-010 remove-pane side-effect backends as ``(tmux_kill,
    route_cleanup, log_detach)``; each ``None`` when boot wiring is
    incomplete."""
    backends = getattr(ctx, "managed_spawn_backends", None) or {}
    return (
        backends.get("tmux_kill"),
        backends.get("route_cleanup"),
        backends.get("log_detach"),
    )


def _state_str(state: Any) -> str:
    if isinstance(state, ManagedState):
        return state.value
    return str(state)


# ─── app.managed_layout_create ───────────────────────────────────────────


def app_managed_layout_create(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = -1,
) -> dict[str, Any]:
    """Implements ``app.managed_layout_create`` (M1).

    Order of checks (matches contracts/managed-methods.md M1 errors list):

    1. FEAT-011 host-only gate (FR-042) → ``host_only`` for bench peers.
    2. Required-field shape → ``validation_failed``.
    3. ``container_not_found`` if FEAT-003 registry has no such id.
    4. Delegate to ``service.create_layout`` (which enforces FR-016
       charset/length, FR-019 serializer, FR-025 capacity, FR-003 label
       uniqueness, and the template / launch-profile resolvers).
    """
    # 1. Host-only gate.
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        # Per FR-034a, codes not in the FR-034 details registry MUST carry
        # ``details == {}``. ``host_only`` is one of those codes.
        return _envelope.failure(
            HOST_ONLY,
            "app.managed_layout_create is host-only",
            details={},
        )

    if not isinstance(params, dict):
        params = {}

    container_id = params.get("container_id")
    template_name = params.get("template_name")
    tmux_session_name = params.get("tmux_session_name")
    launch_command_overrides = params.get("launch_command_overrides") or {}
    idempotency_key = params.get("idempotency_key")

    # 2. Required-field shape checks.
    for field, value in (
        ("container_id", container_id),
        ("template_name", template_name),
        ("tmux_session_name", tmux_session_name),
    ):
        if not isinstance(value, str) or not value:
            return _envelope.failure(
                VALIDATION_FAILED,
                f"missing or empty {field!r}",
                details={"field": field, "reason": "missing or empty"},
            )
    if launch_command_overrides and not isinstance(launch_command_overrides, dict):
        return _envelope.failure(
            VALIDATION_FAILED,
            "launch_command_overrides must be an object",
            details={"field": "launch_command_overrides", "reason": "wrong type"},
        )
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        return _envelope.failure(
            VALIDATION_FAILED,
            "idempotency_key must be a string when provided",
            details={"field": "idempotency_key", "reason": "wrong type"},
        )

    # 3. container_not_found pre-check.
    conn = _state_conn(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "daemon state_conn not wired", details={}
        )
    if not _container_exists(conn, container_id):
        # FEAT-013 closed-set code; the FEAT-011 envelope still validates
        # its shape against the FEAT-011 closed set, so we use
        # _envelope.failure's bypass via the raw shape rather than
        # validate_details (CONTAINER_NOT_FOUND is FEAT-013-owned, not
        # FEAT-011's closed set). The dispatcher's _wrap_handler safety
        # net allows this — the envelope shape itself is FR-033-compliant.
        return _build_managed_error_envelope(
            CONTAINER_NOT_FOUND,
            f"unknown container_id {container_id!r}",
            details={"container_id": container_id},
        )

    # 4. Serializer must be wired.
    serializer = _serializer(ctx)
    if serializer is None:
        return _envelope.failure(
            INTERNAL_ERROR, "daemon managed_serializer not wired", details={}
        )

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
            tx_lock=getattr(ctx, "state_tx_lock", None),
            tmux_has_session_fn=_session_conflict_fn(ctx),
        )
        # C4 fix: kick off the bg spawn pipeline. No-op when
        # daemon-boot wiring is incomplete. Replay results skip
        # (their panes are already past ``creating``).
        if not result.replay:
            from ..daemon_boot import kickoff_spawn_pipeline
            kickoff_spawn_pipeline(layout_id=result.layout_id, ctx=ctx)
    except ValidationFailedError as exc:
        return _envelope.failure(VALIDATION_FAILED, str(exc), details=exc.details)
    except ManagedSessionsError as exc:
        return _build_managed_error_envelope(
            exc.code, str(exc), details=exc.details
        )

    return _envelope.success(
        {
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
    )


def _build_managed_error_envelope(
    code: str, message: str, details: dict[str, Any]
) -> dict[str, Any]:
    """Build a FEAT-011-shaped envelope around a FEAT-013 closed-set code.

    FEAT-011's :func:`envelope.failure` validates against FEAT-011's
    closed code set and per-code details schema. FEAT-013's closed set
    is additive and isn't registered with FEAT-011 (per contracts/
    managed-methods.md §Versioning — additive evolution within
    ``app_contract_version = "1.0"`` does not extend FEAT-011's
    closed-set registry). We build the envelope shape directly here so
    the wire still sees the FR-033-required envelope keys without
    failing FEAT-011's validate_details step.
    """
    from ...app_contract.versioning import APP_CONTRACT_VERSION

    return {
        "ok": False,
        "app_contract_version": APP_CONTRACT_VERSION,
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
    }


# ─── M2-M5 list / detail handlers (T033 — Phase 4a) ─────────────────────


def _state_filter(value: Any) -> ManagedState | None:
    """Coerce the optional ``state`` filter param. Raises ValueError on bad type."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("state filter must be a string")
    try:
        return ManagedState(value)
    except ValueError:
        valid = ", ".join(s.value for s in ManagedState)
        raise ValueError(f"state filter must be one of: {valid}")


def _layout_view_payload_list(row: Any, ready_pane_count: int) -> dict[str, Any]:
    """M2 list-row shape (with ready_pane_count summary)."""
    return {
        "layout_id": row.id,
        "container_id": row.container_id,
        "template_name": row.template_name,
        "state": row.state.value,
        "intended_pane_count": row.intended_pane_count,
        "ready_pane_count": ready_pane_count,
        "created_at": row.created_at,
        "origin": ORIGIN_MANAGED,
    }


def _pane_row_to_payload(row: Any) -> dict[str, Any]:
    """M3/M4/M5 pane-row shape."""
    payload: dict[str, Any] = {
        "pane_id": row.id,
        "layout_id": row.layout_id,
        "container_id": row.container_id,
        "role": row.role,
        "capability": row.capability,
        "label": row.label,
        "state": row.state.value,
        "tmux_session_name": row.tmux_session_name,
        "tmux_pane_index": row.tmux_pane_index,
        "chain_depth": row.chain_depth,
        "agent_id": row.agent_id,
        "predecessor_id": row.predecessor_id,
        "log_attached": False,  # threaded in Phase 4b alongside FEAT-007 wiring
        "origin": ORIGIN_MANAGED,
    }
    if row.failed_stage is not None:
        payload["failed_stage"] = (
            row.failed_stage.value if isinstance(row.failed_stage, FailedStage)
            else str(row.failed_stage)
        )
    return payload


def app_managed_layout_list(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``app.managed_layout_list`` (M2)."""
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY, "app.managed_layout_list is host-only", details={},
        )
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "daemon state_conn not wired", details={}
        )
    try:
        state = _state_filter(params.get("state"))
    except ValueError as exc:
        return _envelope.failure(
            VALIDATION_FAILED, str(exc),
            details={"field": "state", "reason": str(exc)},
        )
    container_id = params.get("container_id")
    if container_id is not None and not isinstance(container_id, str):
        return _envelope.failure(
            VALIDATION_FAILED, "container_id must be a string when provided",
            details={"field": "container_id", "reason": "wrong type"},
        )
    limit = params.get("limit", 50)
    after = params.get("after")
    if after is not None and not isinstance(after, str):
        return _envelope.failure(
            VALIDATION_FAILED, "after cursor must be a string",
            details={"field": "after", "reason": "wrong type"},
        )
    rows, next_cursor = list_layouts(
        conn,
        container_id=container_id if isinstance(container_id, str) else None,
        state=state,
        limit=int(limit) if isinstance(limit, int) else 50,
        after=after,
    )
    # M8 fix: single aggregate query instead of one COUNT per layout.
    ready_counts = count_ready_panes_for_layouts(conn, [r.id for r in rows])
    items = [
        _layout_view_payload_list(r, ready_counts.get(r.id, 0))
        for r in rows
    ]
    return _envelope.success({"items": items, "next": next_cursor})


def app_managed_layout_detail(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``app.managed_layout_detail`` (M3)."""
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY, "app.managed_layout_detail is host-only", details={},
        )
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "daemon state_conn not wired", details={}
        )
    layout_id = params.get("layout_id")
    if not isinstance(layout_id, str) or not layout_id:
        return _envelope.failure(
            VALIDATION_FAILED, "missing or empty 'layout_id'",
            details={"field": "layout_id", "reason": "missing or empty"},
        )
    include_terminal = bool(params.get("include_terminal_panes", False))
    layout_row = select_layout(conn, layout_id)
    if layout_row is None:
        return _build_managed_error_envelope(
            MANAGED_LAYOUT_NOT_FOUND,
            f"unknown layout_id {layout_id!r}",
            details={"layout_id": layout_id},
        )
    panes = select_panes_for_layout(conn, layout_id)
    if not include_terminal:
        panes = [p for p in panes if p.state != ManagedState.REMOVED]
    return _envelope.success(
        {
            "layout_id": layout_row.id,
            "container_id": layout_row.container_id,
            "template_name": layout_row.template_name,
            "state": layout_row.state.value,
            "failed_stage": (
                layout_row.failed_stage.value if layout_row.failed_stage else None
            ),
            "intended_pane_count": layout_row.intended_pane_count,
            "panes": [_pane_row_to_payload(p) for p in panes],
            "created_at": layout_row.created_at,
            "updated_at": layout_row.updated_at,
            "origin": ORIGIN_MANAGED,
        }
    )


def app_managed_pane_list(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``app.managed_pane_list`` (M4)."""
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY, "app.managed_pane_list is host-only", details={},
        )
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "daemon state_conn not wired", details={}
        )
    container_id = params.get("container_id")
    layout_id = params.get("layout_id")
    for field, value in (("container_id", container_id), ("layout_id", layout_id)):
        if value is not None and not isinstance(value, str):
            return _envelope.failure(
                VALIDATION_FAILED, f"{field} must be a string when provided",
                details={"field": field, "reason": "wrong type"},
            )
    try:
        state = _state_filter(params.get("state"))
    except ValueError as exc:
        return _envelope.failure(
            VALIDATION_FAILED, str(exc),
            details={"field": "state", "reason": str(exc)},
        )
    limit = params.get("limit", 50)
    after = params.get("after")
    if after is not None and not isinstance(after, str):
        return _envelope.failure(
            VALIDATION_FAILED, "after cursor must be a string",
            details={"field": "after", "reason": "wrong type"},
        )
    rows, next_cursor = list_panes(
        conn,
        container_id=container_id if isinstance(container_id, str) else None,
        layout_id=layout_id if isinstance(layout_id, str) else None,
        state=state,
        limit=int(limit) if isinstance(limit, int) else 50,
        after=after,
    )
    items = [_pane_row_to_payload(r) for r in rows]
    return _envelope.success({"items": items, "next": next_cursor})


def app_managed_pane_detail(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``app.managed_pane_detail`` (M5) — single pane + optional predecessor chain."""
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY, "app.managed_pane_detail is host-only", details={},
        )
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "daemon state_conn not wired", details={}
        )
    pane_id = params.get("pane_id")
    if not isinstance(pane_id, str) or not pane_id:
        return _envelope.failure(
            VALIDATION_FAILED, "missing or empty 'pane_id'",
            details={"field": "pane_id", "reason": "missing or empty"},
        )
    include_chain = bool(params.get("include_predecessor_chain", False))
    row = select_pane(conn, pane_id)
    if row is None:
        return _build_managed_error_envelope(
            MANAGED_PANE_NOT_FOUND,
            f"unknown pane_id {pane_id!r}",
            details={"pane_id": pane_id},
        )
    payload = _pane_row_to_payload(row)
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
    return _envelope.success(payload)


# ─── M6 / M7 / M8 lifecycle handlers (T048 — Phase 5c) ──────────────────


def app_managed_pane_remove(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``app.managed_pane_remove`` (M6)."""
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY, "app.managed_pane_remove is host-only", details={},
        )
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "daemon state_conn not wired", details={}
        )
    serializer = _serializer(ctx)
    if serializer is None:
        return _envelope.failure(
            INTERNAL_ERROR, "daemon managed_serializer not wired", details={}
        )

    pane_id = params.get("pane_id")
    if not isinstance(pane_id, str) or not pane_id:
        return _envelope.failure(
            VALIDATION_FAILED, "missing or empty 'pane_id'",
            details={"field": "pane_id", "reason": "missing or empty"},
        )

    tmux_kill_fn, route_cleanup_fn, log_detach_fn = _remove_pane_backends(ctx)

    try:
        result = remove_pane(
            conn=conn, serializer=serializer, pane_id=pane_id,
            tmux_kill_fn=tmux_kill_fn,
            route_cleanup_fn=route_cleanup_fn,
            log_detach_fn=log_detach_fn,
            tx_lock=getattr(ctx, "state_tx_lock", None),
        )
    except ManagedSessionsError as exc:
        return _build_managed_error_envelope(exc.code, str(exc), details=exc.details)

    return _envelope.success(
        {"pane_id": result.pane_id, "state": result.state.value}
    )


def app_managed_pane_recreate(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``app.managed_pane_recreate`` (M7)."""
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY, "app.managed_pane_recreate is host-only", details={},
        )
    if not isinstance(params, dict):
        params = {}
    conn = _state_conn(ctx)
    if conn is None:
        return _envelope.failure(
            INTERNAL_ERROR, "daemon state_conn not wired", details={}
        )
    serializer = _serializer(ctx)
    if serializer is None:
        return _envelope.failure(
            INTERNAL_ERROR, "daemon managed_serializer not wired", details={}
        )

    predecessor_pane_id = params.get("predecessor_pane_id")
    if not isinstance(predecessor_pane_id, str) or not predecessor_pane_id:
        return _envelope.failure(
            VALIDATION_FAILED, "missing or empty 'predecessor_pane_id'",
            details={"field": "predecessor_pane_id", "reason": "missing or empty"},
        )

    launch_command_override = params.get("launch_command_override")
    if launch_command_override is not None and not isinstance(launch_command_override, str):
        return _envelope.failure(
            VALIDATION_FAILED, "launch_command_override must be a string when provided",
            details={"field": "launch_command_override", "reason": "wrong type"},
        )

    idempotency_key = params.get("idempotency_key")
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        return _envelope.failure(
            VALIDATION_FAILED, "idempotency_key must be a string when provided",
            details={"field": "idempotency_key", "reason": "wrong type"},
        )

    try:
        result = recreate_pane(
            conn=conn, serializer=serializer,
            predecessor_pane_id=predecessor_pane_id,
            launch_command_override=launch_command_override,
            idempotency_key=idempotency_key,
            tx_lock=getattr(ctx, "state_tx_lock", None),
        )
        # FR-011: the recreated pane lands in ``creating``; kick off the
        # background spawn pipeline so it actually spawns in production.
        from ..daemon_boot import kickoff_spawn_pipeline
        kickoff_spawn_pipeline(layout_id=result.layout_id, ctx=ctx)
    except ManagedSessionsError as exc:
        return _build_managed_error_envelope(exc.code, str(exc), details=exc.details)

    return _envelope.success({
        "pane_id": result.pane_id,
        "predecessor_id": result.predecessor_id,
        "chain_depth": result.chain_depth,
        "state": result.state.value,
        "replay": result.replay,
    })


def app_managed_pane_promote_from_adopted(ctx, params, peer_uid=-1):  # noqa: ANN001
    """``app.managed_pane_promote_from_adopted`` (M8 stub)."""
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY,
            "app.managed_pane_promote_from_adopted is host-only",
            details={},
        )
    if not isinstance(params, dict):
        params = {}
    agent_id = params.get("agent_id", "")
    if not isinstance(agent_id, str):
        agent_id = ""
    stub = promote_from_adopted(agent_id)
    # `not_implemented` is in the FEAT-011 closed set with required
    # details = {} per FR-034a — but our stub carries reserved_since,
    # which is a FEAT-013-specific extension. Build the envelope
    # directly so FEAT-011's validate_details doesn't reject it.
    from ...app_contract.versioning import APP_CONTRACT_VERSION
    return {
        "ok": False,
        "app_contract_version": APP_CONTRACT_VERSION,
        "error": {
            "code": stub.error_code,
            "message": "promote_from_adopted is reserved for a later feature.",
            "details": dict(stub.details),
        },
    }


# ─── Registration ────────────────────────────────────────────────────────


def register() -> dict[str, Any]:
    """Return the ``app.managed_*`` method → handler mapping.

    Imported by ``app_contract/dispatcher.py`` at module-import time
    (T025); the returned dict is merged into ``APP_DISPATCH`` via the
    same ``_wrap_handler`` pattern that FEAT-011's existing handlers use.
    """
    return {
        "app.managed_layout_create": app_managed_layout_create,
        "app.managed_layout_list": app_managed_layout_list,
        "app.managed_layout_detail": app_managed_layout_detail,
        "app.managed_pane_list": app_managed_pane_list,
        "app.managed_pane_detail": app_managed_pane_detail,
        "app.managed_pane_remove": app_managed_pane_remove,
        "app.managed_pane_recreate": app_managed_pane_recreate,
        "app.managed_pane_promote_from_adopted": app_managed_pane_promote_from_adopted,
    }


__all__ = [
    "register",
    "app_managed_layout_create",
    "app_managed_layout_list",
    "app_managed_layout_detail",
    "app_managed_pane_list",
    "app_managed_pane_detail",
    "app_managed_pane_remove",
    "app_managed_pane_recreate",
    "app_managed_pane_promote_from_adopted",
]
