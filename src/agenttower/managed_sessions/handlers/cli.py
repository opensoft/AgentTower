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

from ..errors import CONTAINER_NOT_FOUND, ManagedSessionsError
from ..service import ValidationFailedError, create_layout
from ..state_machine import ManagedState

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


# ─── M2-M5 stubs (Phase 4 T033 wires list/detail; placeholder return) ───
#
# These exist so the dispatcher registration in T025 can install the
# method names; T033 (Phase 4) replaces the stub body with the actual
# list/detail implementation. We return ``internal_error`` rather than
# ``unknown_method`` so the operator-facing surface is honest about
# "registered but not yet implemented" rather than masking as missing.


def _not_yet_implemented(method: str) -> dict[str, Any]:
    return _err(
        "internal_error",
        f"{method} is dispatch-registered but not yet implemented (T033/T048 follow-up)",
    )


def _managed_layout_list(ctx, params, peer_uid=-1):  # noqa: ANN001
    return _not_yet_implemented("managed.layout.list")


def _managed_layout_detail(ctx, params, peer_uid=-1):  # noqa: ANN001
    return _not_yet_implemented("managed.layout.detail")


def _managed_pane_list(ctx, params, peer_uid=-1):  # noqa: ANN001
    return _not_yet_implemented("managed.pane.list")


def _managed_pane_detail(ctx, params, peer_uid=-1):  # noqa: ANN001
    return _not_yet_implemented("managed.pane.detail")


# ─── Registration ────────────────────────────────────────────────────────


_LEGACY_METHODS: dict[str, Any] = {
    "managed.layout.create": _managed_layout_create,
    "managed.layout.list": _managed_layout_list,
    "managed.layout.detail": _managed_layout_detail,
    "managed.pane.list": _managed_pane_list,
    "managed.pane.detail": _managed_pane_detail,
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
