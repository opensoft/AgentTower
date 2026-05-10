"""FEAT-008 follow-session registry.

Server-side state for ``events.follow_open`` / ``events.follow_next`` /
``events.follow_close`` (`contracts/socket-events.md`). Each session
captures the operator's filter, the last-emitted ``event_id``, and an
expiration timestamp. The reader thread, after every successful SQLite
commit, calls :meth:`FollowSessionRegistry.notify` so blocked
``follow_next`` waiters wake.

This module owns no FEAT-008 test seam (no env-var read). The
registry is created once per daemon and lives for the daemon's
lifetime.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Optional


_SESSION_ID_PREFIX = "fs_"


def _new_session_id() -> str:
    """Generate ``fs_<12-hex>`` per data-model.md §6 / contracts/socket-events.md."""
    return _SESSION_ID_PREFIX + secrets.token_hex(6)


def matches_filter(
    *,
    target_agent_id: Optional[str],
    type_filter: frozenset[str],
    event_agent_id: str,
    event_type: str,
) -> bool:
    """Pure predicate: does ``(event_agent_id, event_type)`` match the filter?"""
    if target_agent_id is not None and event_agent_id != target_agent_id:
        return False
    if type_filter and event_type not in type_filter:
        return False
    return True


@dataclass
class FollowSession:
    """One follow session.

    ``last_emitted_event_id == 0`` means "nothing emitted yet"; the
    first ``follow_next`` returns events with ``event_id >
    live_starting_event_id`` (set at ``follow_open`` time).
    """

    session_id: str
    target_agent_id: Optional[str]
    type_filter: frozenset[str]
    since_iso: Optional[str]
    last_emitted_event_id: int
    live_starting_event_id: int
    expires_at_monotonic: float
    condition: threading.Condition = field(default_factory=threading.Condition)


class FollowSessionRegistry:
    """In-memory registry of active :class:`FollowSession` objects.

    Thread-safety: every public method takes ``self._lock`` for the
    short critical section that touches ``self._sessions``. The
    per-session ``threading.Condition`` is a separate lock (created
    per session); callers that block on ``follow_next`` use the
    session's condition, not the registry's lock.
    """

    # CRIT-4 — rate-limit threshold for unknown-session_id lookups.
    # An attacker on the local socket has SO_PEERCRED-bound access but
    # could brute-force the 48-bit session_id space. Once we observe
    # this many bad lookups within
    # ``_BAD_LOOKUP_WINDOW_SECONDS``, we begin returning a generic
    # ``events_session_unknown`` error WITHOUT touching the dict, so
    # the cost of a brute-force attempt stays at constant time and the
    # daemon does not spawn a thread per failed guess.
    _BAD_LOOKUP_THRESHOLD = 100
    _BAD_LOOKUP_WINDOW_SECONDS = 10.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, FollowSession] = {}
        # Sliding-window rate limiter for unknown-session_id lookups.
        self._bad_lookup_count: int = 0
        self._bad_lookup_window_start: float = 0.0

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def open(
        self,
        *,
        target_agent_id: Optional[str],
        types: tuple[str, ...],
        since_iso: Optional[str],
        live_starting_event_id: int,
        expires_at_monotonic: float,
    ) -> FollowSession:
        """Register a new session; return the :class:`FollowSession`."""
        session = FollowSession(
            session_id=_new_session_id(),
            target_agent_id=target_agent_id,
            type_filter=frozenset(types),
            since_iso=since_iso,
            last_emitted_event_id=0,
            live_starting_event_id=live_starting_event_id,
            expires_at_monotonic=expires_at_monotonic,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Optional[FollowSession]:
        with self._lock:
            return self._sessions.get(session_id)

    def is_rate_limited(self, *, now_monotonic: float) -> bool:
        """CRIT-4 sliding-window check for unknown-session_id brute force.

        Call this from the dispatcher on a missing session BEFORE
        returning an error envelope. Returns ``True`` iff the threshold
        has been exceeded inside the current window. Caller MUST still
        return ``events_session_unknown`` to the client; the rate
        limiter is purely a CPU-shedding gate so the dispatcher's hot
        path (dict miss → error) stays cheap.
        """
        with self._lock:
            elapsed = now_monotonic - self._bad_lookup_window_start
            if elapsed >= self._BAD_LOOKUP_WINDOW_SECONDS:
                # New window.
                self._bad_lookup_window_start = now_monotonic
                self._bad_lookup_count = 1
                return False
            self._bad_lookup_count += 1
            return self._bad_lookup_count > self._BAD_LOOKUP_THRESHOLD

    def close(self, session_id: str) -> bool:
        """Remove a session; return True iff it was present."""
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        # Wake any waiter so they can observe the close.
        with session.condition:
            session.condition.notify_all()
        return True

    def refresh_expiration(
        self, session_id: str, *, new_expires_at_monotonic: float
    ) -> bool:
        """Bump ``expires_at_monotonic`` on a still-existing session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.expires_at_monotonic = new_expires_at_monotonic
            return True

    # ------------------------------------------------------------------
    # Cycle-time janitor (called by the reader between cycles, Plan §R9)
    # ------------------------------------------------------------------

    def gc_expired(self, *, now_monotonic: float) -> list[str]:
        """Remove every session whose ``expires_at_monotonic < now``.

        Wakes any waiter blocked on the session's condition so the
        ``follow_next`` long-poll exits promptly with
        ``session_open=false`` instead of waiting up to its full budget.

        Returns the list of removed session ids (for logging).
        """
        removed_pairs: list[tuple[str, FollowSession]] = []
        with self._lock:
            for sid, session in list(self._sessions.items()):
                if session.expires_at_monotonic < now_monotonic:
                    self._sessions.pop(sid, None)
                    removed_pairs.append((sid, session))
        # Wake any waiter on the just-removed sessions; we still hold
        # a reference to each session even though the dict no longer
        # has it, so the condition is reachable.
        for _, session in removed_pairs:
            with session.condition:
                session.condition.notify_all()
        return [sid for sid, _ in removed_pairs]

    # ------------------------------------------------------------------
    # Notification (called by the reader after every successful commit)
    # ------------------------------------------------------------------

    def notify(self, *, agent_id: str, event_type: str) -> None:
        """Wake every session whose filter matches ``(agent_id, event_type)``.

        The reader calls this after each successful SQLite commit (T050
        wires this into the reader's commit path). Each waiting
        ``follow_next`` re-queries the DAO with
        ``event_id > last_emitted_event_id``.
        """
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            if matches_filter(
                target_agent_id=session.target_agent_id,
                type_filter=session.type_filter,
                event_agent_id=agent_id,
                event_type=event_type,
            ):
                with session.condition:
                    session.condition.notify_all()

    def session_count(self) -> int:
        """Diagnostic: number of active sessions (for ``agenttower status``)."""
        with self._lock:
            return len(self._sessions)


__all__ = ["FollowSession", "FollowSessionRegistry", "matches_filter"]
