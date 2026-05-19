"""``app.preflight`` handler (FR-011).

Lightweight diagnostic. Does NOT require a session token (FR-011);
safe to call before ``app.hello``. Returns the success envelope with
a diagnostic ``code`` field carrying one of:

    ok | daemon_unavailable | socket_missing | socket_permission_denied

If the daemon is reachable enough to respond at all, the success
envelope is the normal path (the diagnostic ``code`` distinguishes
edge conditions). Actual OS-level connect failures (socket missing,
permission denied) surface as connection errors to the client; the
client library translates those into the matching diagnostic code.

The host-only gate (FR-042) applies to ``app.preflight`` too — a
bench-container peer receives the closed-set failure envelope
``host_only`` with ``details = {}``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import envelope
from .errors import HOST_ONLY

if TYPE_CHECKING:
    from ..socket_api.methods import DaemonContext

# Sentinel value mirroring ``socket_api.methods._NO_PEER_UID``. Defined
# locally to avoid a circular import at module-load (see the host_only
# import path).
_NO_PEER_UID: int = -1


def app_preflight(
    ctx: "DaemonContext",
    params: dict[str, Any],
    peer_uid: int = _NO_PEER_UID,
) -> dict[str, Any]:
    """Handler for ``app.preflight``.

    Returns a success envelope with a diagnostic ``code`` field on the
    success path (FR-011), or the closed-set ``host_only`` failure
    envelope when the peer is a bench-container caller (FR-042).
    """
    # FR-042: host-only gate applies to every app.* method, including
    # app.preflight. Lazy-imported to keep module-load free of any
    # ``socket_api.methods`` dependency (avoids a circular import).
    from .host_only import is_host_peer

    if not is_host_peer(peer_uid):
        return envelope.failure(
            HOST_ONLY,
            "app.* namespace is host-only; bench-container callers refused",
            details={},
        )

    return envelope.success({
        "socket_reachable": True,
        "daemon_reachable": True,
        "code": "ok",
    })


__all__ = [
    "app_preflight",
]
