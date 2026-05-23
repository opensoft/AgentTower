"""``app.preflight`` handler (FR-011).

Lightweight diagnostic. Does NOT require a session token (FR-011);
safe to call before ``app.hello``. Returns the success envelope with
a diagnostic ``code`` field carrying one of:

    ok | daemon_unavailable | socket_missing | socket_permission_denied

If the daemon is reachable enough to respond at all, the success
envelope is the normal path (the diagnostic ``code`` distinguishes
edge conditions).

Daemon-health detection — who reports which ``code``:

* A *fully-dead* daemon cannot run this handler at all. The client's
  ``connect()`` fails at the OS level (the socket file is gone, or
  exists but nothing is listening, or permissions deny it); the client
  library is responsible for mapping those connect failures onto the
  ``socket_missing`` / ``socket_permission_denied`` / ``daemon_unavailable``
  diagnostic codes. The handler never executes, so it cannot report
  them itself.
* A *shutting-down* daemon is the gap this handler covers: the listener
  is still accepting connections and dispatching requests, but the
  daemon has begun its graceful-shutdown sequence and is no longer a
  trustworthy backend. That window is detectable here via
  ``ctx.shutdown_requested`` (a ``threading.Event | None`` on
  ``DaemonContext``). When it is set, the handler returns the success
  envelope with ``code = "daemon_unavailable"``, ``daemon_reachable =
  false`` and ``socket_reachable = true`` — the socket answered, but the
  daemon behind it is on its way out.
* Otherwise the handler reports ``code = "ok"`` with both reachability
  flags ``true``.

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

    # Daemon-health detection. The socket answered (we are running), so
    # ``socket_reachable`` is always true on this path. If the daemon has
    # begun its graceful-shutdown sequence the backend is no longer
    # trustworthy even though it still answered — report the
    # shutting-down window as ``daemon_unavailable``. A fully-dead daemon
    # never reaches this code; the client maps that connect failure to a
    # diagnostic code itself (see the module docstring).
    shutdown = getattr(ctx, "shutdown_requested", None)
    if shutdown is not None and shutdown.is_set():
        return envelope.success({
            "socket_reachable": True,
            "daemon_reachable": False,
            "code": "daemon_unavailable",
        })

    return envelope.success({
        "socket_reachable": True,
        "daemon_reachable": True,
        "code": "ok",
    })


__all__ = [
    "app_preflight",
]
