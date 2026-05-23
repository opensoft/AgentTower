"""FEAT-011 host-only peer gate (FR-042).

Every ``app.*`` method MUST reject bench-container peers with the
closed-set code ``host_only``. The check reuses the FEAT-002 socket
server's host-vs-container distinction (``_peer_is_host_process``)
so FEAT-011 inherits a single source of truth and FR-042's "MUST
reuse the same mechanism" requirement is trivially satisfied.

The legacy FEAT-002..FEAT-010 socket methods continue to accept
bench-container callers unchanged (FR-040). Only the ``app.*``
namespace is gated.

**Defense-in-depth note:** The same-host-uid gate (FR-041) is
enforced by FEAT-002's socket server at accept time: the server reads
``SO_PEERCRED``, compares the peer uid against the daemon's effective
uid, and refuses the connection if they differ — see
``socket_api/server.py``'s peer-credential preflight. By the time
a handler is dispatched, that check has already passed (or the
handler wouldn't be running). This module's ``is_host_peer`` adds the
**host-vs-container** distinction on top: same-uid peers MAY still
live inside a bench container (the daemon socket is bind-mounted into
the bench), and FR-042 forbids those from calling ``app.*``.

A redundant in-handler uid check would only fire if FEAT-002's
accept-time gate were bypassed — that's a different attack surface
than what FR-042 covers, but we include a defensive sentinel check
below (``peer_uid != _NO_PEER_UID``) so the predicate is correct even
in test or non-production wiring where the server gate may not have
run.
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

    Implements the FR-042 **host-vs-container** gate predicate. The
    related FR-041 **same-uid** check is enforced by FEAT-002's socket
    server at connection accept time (``socket_api/server.py``); by
    the time a handler runs, the peer uid has already been verified
    to match the daemon's effective uid. This function adds the
    container-detection layer on top.

    Returns False when:

    * ``peer_uid == _NO_PEER_UID`` — defensive: no SO_PEERCRED
      credentials present. A host-only gate that allows on "no
      credentials" is bypassable, so we treat "no credentials" the
      same as a container caller. In production this branch is
      unreachable because FEAT-002's server rejects the connection
      before dispatch; in tests/non-production wiring it can be
      reached and MUST return False.
    * The peer pid resolves to a bench-container process per
      ``_peer_is_host_process`` (FR-042).
    """
    if peer_uid == _NO_PEER_UID:
        return False
    pid = _request_peer_pid()
    return _peer_is_host_process(pid)


__all__ = [
    "is_host_peer",
]
