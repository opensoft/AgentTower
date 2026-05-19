"""``app.hello`` handler (FR-010, FR-036, FR-039).

Bootstrap handshake. Issues an app session and returns daemon identity,
schema/runtime versions, contract version, supported minor range,
``capability_flags = {}`` at v1.0, and host UID for verification.

Failure paths:
- bench-container peer → ``host_only`` (FR-042)
- client major != daemon major → ``app_contract_major_unsupported`` with
  both versions in ``details`` (FR-036). No session is issued.

Request params (all optional, per Story 1 acceptance and FR-010):
    {
      "client_id": "<str, ≤128 chars>",
      "client_version": "<str, ≤64 chars>",
      "client_app_contract_major": <int, default 1>
    }
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from . import envelope, sessions, versioning
from .errors import APP_CONTRACT_MAJOR_UNSUPPORTED, HOST_ONLY, VALIDATION_FAILED

if TYPE_CHECKING:
    from ..socket_api.methods import DaemonContext

# Sentinel value mirroring ``socket_api.methods._NO_PEER_UID``. Defined
# locally to avoid a circular import at module-load.
_NO_PEER_UID: int = -1


_CLIENT_ID_MAX_LEN = 128
_CLIENT_VERSION_MAX_LEN = 64


def _coerce_client_major(value: Any) -> tuple[int | None, dict[str, Any] | None]:
    """Coerce ``client_app_contract_major`` to int, default 1.

    Returns ``(major, None)`` on success or ``(None, error_envelope)`` on
    validation failure.
    """
    if value is None:
        return 1, None
    if isinstance(value, bool) or not isinstance(value, int):
        return None, envelope.failure(
            VALIDATION_FAILED,
            "client_app_contract_major must be an integer",
            details={
                "field": "client_app_contract_major",
                "reason": "must be an integer",
            },
        )
    if value < 1:
        return None, envelope.failure(
            VALIDATION_FAILED,
            "client_app_contract_major must be >= 1",
            details={
                "field": "client_app_contract_major",
                "reason": "must be >= 1",
            },
        )
    return value, None


def _coerce_str(
    value: Any, *, field: str, max_len: int
) -> tuple[str | None, dict[str, Any] | None]:
    """Coerce an optional string field with a length cap."""
    if value is None:
        return "", None
    if not isinstance(value, str):
        return None, envelope.failure(
            VALIDATION_FAILED,
            f"{field} must be a string",
            details={"field": field, "reason": "must be a string"},
        )
    if len(value) > max_len:
        return None, envelope.failure(
            VALIDATION_FAILED,
            f"{field} exceeds {max_len} characters",
            details={"field": field, "reason": f"max length {max_len}"},
        )
    return value, None


def app_hello(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    """Handler for ``app.hello``.

    Returns the FR-010 envelope on success, the major-mismatch envelope
    when ``client_app_contract_major`` does not match (FR-036), or the
    host-only envelope from a container peer (FR-042).
    """
    # FR-042: host-only gate applies to app.hello (no session yet, but the
    # peer-origin gate fires before any session work). Lazy-imported to
    # avoid a module-load circular import via socket_api.methods.
    from .host_only import is_host_peer

    if not is_host_peer(peer_uid):
        return envelope.failure(
            HOST_ONLY,
            "app.* namespace is host-only; bench-container callers refused",
            details={},
        )

    if not isinstance(params, dict):
        params = {}

    client_id, err = _coerce_str(
        params.get("client_id"), field="client_id", max_len=_CLIENT_ID_MAX_LEN
    )
    if err is not None:
        return err

    client_version, err = _coerce_str(
        params.get("client_version"),
        field="client_version",
        max_len=_CLIENT_VERSION_MAX_LEN,
    )
    if err is not None:
        return err

    client_major, err = _coerce_client_major(params.get("client_app_contract_major"))
    if err is not None:
        return err
    assert client_major is not None  # narrowed by _coerce_client_major

    # FR-036: major mismatch → no session issued.
    if not versioning.is_major_compatible(client_major):
        return envelope.failure(
            APP_CONTRACT_MAJOR_UNSUPPORTED,
            f"daemon implements app_contract_version {versioning.APP_CONTRACT_VERSION}; "
            f"client declared major {client_major}",
            details={
                "daemon_app_contract_version": versioning.APP_CONTRACT_VERSION,
                "client_app_contract_major": client_major,
            },
        )

    host_user_id = str(peer_uid) if peer_uid != _NO_PEER_UID else str(os.geteuid())
    try:
        session = sessions.get_registry().create(
            client_id=client_id or "",
            client_version=client_version or "",
            client_app_contract_major=client_major,
            host_user_id=host_user_id,
        )
    except sessions.SessionCapExceeded:
        # FR-008b: reject the 9th concurrent app.hello.
        return envelope.failure(
            VALIDATION_FAILED,
            f"session cap reached ({sessions.MAX_SESSIONS} concurrent sessions); "
            "wait for an existing session to be invalidated or restart the daemon",
            details={
                "field": "app.hello",
                "reason": "too_many_sessions",
            },
        )

    # FR-010: enumerated success-envelope fields. Order chosen for readability;
    # JSON object field order is not normative.
    schema_version = ctx.schema_version if ctx.schema_version is not None else 0
    # Defensive copy: ``SUPPORTED_MINOR_RANGE`` and ``CAPABILITY_FLAGS_V1_0``
    # are module-level dict singletons. Returning them by reference means
    # any in-process caller (or test) that mutates the returned dict would
    # corrupt every subsequent ``app.hello`` response — and would also
    # silently change the module constants for everyone. ``dict(...)``
    # gives each call its own shallow copy.
    return envelope.success({
        "app_session_token": session.app_session_token,
        "app_session_id": session.app_session_id,
        "daemon_version": ctx.daemon_version,
        "schema_version": schema_version,
        "app_contract_version": versioning.APP_CONTRACT_VERSION,
        "supported_minor_range": dict(versioning.SUPPORTED_MINOR_RANGE),
        "host_user_id": host_user_id,
        "capability_flags": dict(versioning.CAPABILITY_FLAGS_V1_0),
        "state": "ok",
    })


__all__ = [
    "app_hello",
]
