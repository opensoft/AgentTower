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
from ..errors import (
    CONTAINER_NOT_FOUND,
    ManagedSessionsError,
)
from ..service import ValidationFailedError, create_layout
from ..state_machine import ManagedState

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
        )
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


# ─── M2-M5 stubs (Phase 4 T033 wires list/detail; placeholder return) ───


def _not_yet_implemented_envelope(method: str) -> dict[str, Any]:
    return _envelope.failure(
        INTERNAL_ERROR,
        f"{method} is dispatch-registered but not yet implemented (T033/T048 follow-up)",
        details={},
    )


def app_managed_layout_list(ctx, params, peer_uid=-1):  # noqa: ANN001
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY, "app.managed_layout_list is host-only",
            details={},
        )
    return _not_yet_implemented_envelope("app.managed_layout_list")


def app_managed_layout_detail(ctx, params, peer_uid=-1):  # noqa: ANN001
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY, "app.managed_layout_detail is host-only",
            details={},
        )
    return _not_yet_implemented_envelope("app.managed_layout_detail")


def app_managed_pane_list(ctx, params, peer_uid=-1):  # noqa: ANN001
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY, "app.managed_pane_list is host-only",
            details={},
        )
    return _not_yet_implemented_envelope("app.managed_pane_list")


def app_managed_pane_detail(ctx, params, peer_uid=-1):  # noqa: ANN001
    from ...app_contract.host_only import is_host_peer  # lazy: see module note

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY, "app.managed_pane_detail is host-only",
            details={},
        )
    return _not_yet_implemented_envelope("app.managed_pane_detail")


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
    }


__all__ = [
    "register",
    "app_managed_layout_create",
    "app_managed_layout_list",
    "app_managed_layout_detail",
    "app_managed_pane_list",
    "app_managed_pane_detail",
]
