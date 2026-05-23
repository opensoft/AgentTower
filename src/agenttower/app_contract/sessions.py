"""FEAT-011 app-session registry (FR-005..FR-010, FR-008a, FR-008b, FR-036).

In-memory only. Process-wide. Sessions are keyed by ``app_session_token``
and are NOT bound to the connection that issued them — FEAT-002's
socket dispatcher is one-request-per-connection, so an app session's
lifecycle cannot be tied to a connection (T097, 2026-05-19). Sessions
are invalidated only by daemon process exit (in-memory state is lost)
or explicit ``invalidate()`` calls.

Concurrency cap (FR-008b): the registry holds at most ``MAX_SESSIONS``
(8) concurrent sessions. The 9th ``create()`` attempt raises
``SessionCapExceeded`` and the caller (``app.hello`` handler) translates
this to a ``validation_failed.details = {"field": "app.hello", "reason":
"too_many_sessions"}`` envelope. v1.0 implements the reject-not-evict
mode of FR-008b; LRU eviction is reserved as an additive minor.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Final


MAX_SESSIONS: Final[int] = 8
"""FR-008b: hard cap on concurrent sessions per daemon process."""


class SessionCapExceeded(Exception):
    """Raised by ``SessionRegistry.create()`` when the registry already
    holds ``MAX_SESSIONS`` (FR-008b). The ``app.hello`` handler catches
    this and emits a ``validation_failed`` envelope with
    ``details = {"field": "app.hello", "reason": "too_many_sessions"}``.
    """


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

    Process-wide singleton. Session tokens are keyed by
    ``app_session_token``; lookup is O(1). Sessions are NOT
    connection-bound (T097, 2026-05-19) — a token issued on one
    connection authenticates calls on later fresh connections per
    FR-008.

    Hard cap of ``MAX_SESSIONS`` (FR-008b): a 9th ``create()`` raises
    ``SessionCapExceeded``.
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
        """Issue a new session and record it.

        Raises ``SessionCapExceeded`` if the registry already holds
        ``MAX_SESSIONS`` (FR-008b).
        """
        with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                raise SessionCapExceeded(
                    f"session cap reached ({MAX_SESSIONS} concurrent sessions)"
                )
            session = AppSession(
                app_session_token=_generate_token(),
                app_session_id=_next_session_id(),
                client_id=client_id,
                client_version=client_version,
                client_app_contract_major=client_app_contract_major,
                host_user_id=host_user_id,
                connection_started_at_ms=int(time.time() * 1000),
            )
            self._sessions[session.app_session_token] = session
        return session

    def lookup(self, token: str) -> AppSession | None:
        """Return the session for the given token or None if unknown/invalidated."""
        with self._lock:
            return self._sessions.get(token)

    def invalidate(self, token: str) -> None:
        """Remove a session. Test seam and explicit-logout hook; FEAT-002's
        connection-close path does NOT call this (T097 — sessions are not
        connection-bound).

        Also drops the session's per-session idempotency store so the
        process-wide store registry does not leak one stale store per
        invalidated session over a long-lived daemon.
        """
        with self._lock:
            session = self._sessions.pop(token, None)
        if session is not None:
            # Lazy import — mutations.py imports this module.
            from . import mutations as _mutations

            _mutations.drop_idempotency_store(session.app_session_id)

    def size(self) -> int:
        """Current number of sessions held. For tests/diagnostics."""
        with self._lock:
            return len(self._sessions)


# Module-level singleton wired into the dispatcher at daemon startup.
# Tests can replace it via ``set_registry``.
_REGISTRY: SessionRegistry = SessionRegistry()


def get_registry() -> SessionRegistry:
    return _REGISTRY


def set_registry(registry: SessionRegistry) -> None:
    """Test seam — override the module-level registry."""
    global _REGISTRY
    _REGISTRY = registry


def gate_session_required(
    params: dict | None,
    peer_uid: int,
) -> "AppSession | dict":
    """Combined FR-042 host-only + FR-007 session-token gate.

    Every ``app.*`` method except ``app.preflight`` and ``app.hello`` calls
    this at the top of its handler and either returns the failure envelope
    dict (when either gate rejects) or continues with the resolved
    ``AppSession``.

    Gate order matters (FR-042 + FR-007):
        1. ``host_only`` — container peers are rejected first, regardless
           of token. This prevents leaking session-existence information
           to a container caller that happens to have a valid token.
        2. ``app_session_required`` — token missing / wrong type.
        3. ``app_session_expired`` — token present but not in the registry.

    The session token is read from ``params["app_session_token"]``. Per the
    FEAT-002 dispatch loop (which only knows about ``{method, params}``),
    keeping the token inside ``params`` avoids requiring any
    ``socket_api`` modification.

    Returns:
        ``AppSession`` on success, or a failure-envelope ``dict`` on either
        gate rejection. Callers do ``if isinstance(result, dict): return result``.
    """
    # Lazy imports to avoid module-load circular dependency.
    from . import envelope as _envelope
    from .errors import APP_SESSION_EXPIRED, APP_SESSION_REQUIRED, HOST_ONLY
    from .host_only import is_host_peer

    if not is_host_peer(peer_uid):
        return _envelope.failure(
            HOST_ONLY,
            "app.* namespace is host-only; bench-container callers refused",
            details={},
        )

    if not isinstance(params, dict):
        params = {}
    token = params.get("app_session_token")
    if not token or not isinstance(token, str):
        return _envelope.failure(
            APP_SESSION_REQUIRED,
            "missing or malformed app_session_token; call app.hello first",
            details={},
        )

    session = get_registry().lookup(token)
    if session is None:
        return _envelope.failure(
            APP_SESSION_EXPIRED,
            "app_session_token is not valid; call app.hello to issue a new one",
            details={},
        )

    return session


__all__ = [
    "AppSession",
    "MAX_SESSIONS",
    "SessionCapExceeded",
    "SessionRegistry",
    "get_registry",
    "set_registry",
    "gate_session_required",
]
