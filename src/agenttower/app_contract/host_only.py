"""FEAT-011 host-only peer gate (FR-042).

Every ``app.*`` method MUST reject bench-container peers with the
closed-set code ``host_only``. The check reuses the FEAT-002 socket
server's host-vs-container distinction (``_peer_is_host_process``)
so FEAT-011 inherits a single source of truth and FR-042's "MUST
reuse the same mechanism" requirement is trivially satisfied.

The legacy FEAT-002..FEAT-010 socket methods continue to accept
bench-container callers unchanged (FR-040). Only the ``app.*``
namespace is gated.
"""

from __future__ import annotations

# Reuse the existing FEAT-002 host-vs-container predicate. Importing
# from socket_api.methods is intentional — it is the canonical
# implementation per FR-042.
from ..socket_api.methods import (
    _NO_PEER_UID,
    _peer_is_host_process,
    _request_peer_pid,
)


def is_host_peer(peer_uid: int) -> bool:
    """Return True iff the current request peer is a host process.

    Implements the FR-042 gate predicate: the caller must run on the
    host (not inside a bench container) AND have presented valid
    SO_PEERCRED credentials matching the daemon's uid.

    On non-Linux platforms or when SO_PEERCRED returns no uid, this
    returns False — a host-only security gate that allows on "no
    credentials" is bypassable, so we treat "no credentials" as the
    same as a container caller (matching the FR-042 / routing-toggle
    rationale in ``socket_api/methods.py``).
    """
    if peer_uid == _NO_PEER_UID:
        return False
    pid = _request_peer_pid()
    return _peer_is_host_process(pid)


__all__ = [
    "is_host_peer",
]
