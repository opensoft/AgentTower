"""FEAT-011 app-session registry (FR-005..FR-010, FR-036).

In-memory only. Per-connection sessions issued by ``app.hello``,
invalidated when the underlying socket connection closes (FR-008).
Never persisted across daemon restarts (FR-006).

Note: in the current FEAT-002 daemon, every connection processes a
single request and is then closed (FR-026 one-request-per-connection).
That makes connection-scoped session lifetimes very short — every
``app.*`` request that requires a session would, in practice, have
its token presented over a fresh connection. The session table is
still useful for audit attribution (``app_session_id`` flows to
JSONL per FR-044) and for the major-mismatch guard from FR-036.

For follow-up tightening, the dispatcher could maintain a session-token-
indexed map that survives a connection close for a short TTL, but
that is explicitly NOT FEAT-011 v1.0 behavior — the contract says
"session invalidated on connection close" (FR-008).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass


_session_id_counter = 0
_counter_lock = threading.Lock()


def _next_session_id() -> int:
    """Monotonic, daemon-process-scoped integer for audit attribution."""
    global _session_id_counter
    with _counter_lock:
        _session_id_counter += 1
        return _session_id_counter


def _generate_token() -> str:
    """uuid v4 hex with hyphens, 36 chars (FR-006 + Research §R-005)."""
    return str(uuid.uuid4())


@dataclass(frozen=True)
class AppSession:
    """In-memory session record. See ``data-model.md`` §App Session.

    Attributes:
        app_session_token: Opaque uuid v4 hex string. Never persisted,
            never logged (FR-009, SC-008).
        app_session_id: Monotonic int for JSONL audit attribution.
        client_id: Informational; echoed from app.hello.
        client_version: Informational; echoed from app.hello.
        client_app_contract_major: Client's declared major version
            (defaults to 1 if absent). Used for the FR-036 mismatch check.
        host_user_id: Numeric UID as string, resolved at app.hello.
        connection_started_at_ms: Unix milliseconds.
    """

    app_session_token: str
    app_session_id: int
    client_id: str
    client_version: str
    client_app_contract_major: int
    host_user_id: str
    connection_started_at_ms: int


class SessionRegistry:
    """Thread-safe in-memory app session table.

    Currently single-process scoped. Session tokens are keyed by
    ``app_session_token``; lookup is O(1).

    The registry is intentionally minimal at v1.0 because FEAT-002's
    one-request-per-connection model means tokens are seldom re-presented
    over the same connection; future tightening could add per-connection
    binding and a short TTL on disconnect.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, AppSession] = {}

    def create(
        self,
        *,
        client_id: str,
        client_version: str,
        client_app_contract_major: int,
        host_user_id: str,
    ) -> AppSession:
        """Issue a new session and record it."""
        session = AppSession(
            app_session_token=_generate_token(),
            app_session_id=_next_session_id(),
            client_id=client_id,
            client_version=client_version,
            client_app_contract_major=client_app_contract_major,
            host_user_id=host_user_id,
            connection_started_at_ms=int(time.time() * 1000),
        )
        with self._lock:
            self._sessions[session.app_session_token] = session
        return session

    def lookup(self, token: str) -> AppSession | None:
        """Return the session for the given token or None if unknown/invalidated."""
        with self._lock:
            return self._sessions.get(token)

    def invalidate(self, token: str) -> None:
        """Remove a session (e.g., on connection close)."""
        with self._lock:
            self._sessions.pop(token, None)


# Module-level singleton wired into the dispatcher at daemon startup.
# Tests can replace it via ``set_registry``.
_REGISTRY: SessionRegistry = SessionRegistry()


def get_registry() -> SessionRegistry:
    return _REGISTRY


def set_registry(registry: SessionRegistry) -> None:
    """Test seam — override the module-level registry."""
    global _REGISTRY
    _REGISTRY = registry


__all__ = [
    "AppSession",
    "SessionRegistry",
    "get_registry",
    "set_registry",
]
