"""FEAT-013 lifecycle event emitter (T014).

Emits the 12 event types from research §R11 via the FEAT-008 JSONL audit
pipeline. Managed-* events ride the JSONL pipeline ONLY; they do NOT
write to the SQLite ``events`` table (FEAT-008's event_type CHECK enum
is closed to agent-activity types like ``activity`` / ``waiting_for_input``
/ etc., and intentionally does not include managed_*; expanding it
would touch FEAT-008's data model unnecessarily).

This module:

* Names the 12 event types as ``Final[str]`` constants (closed catalog).
* Provides ``redact_env(env)`` for the FR-021 amendment redaction policy.
* Provides ``build_event(...)`` for envelope assembly (per-pane FIFO +
  per-layout FIFO ordering via a per-pane sequence counter held by the
  caller; FR-015 amendment).
* The actual JSONL write site (``append_event(jsonl_path, payload)``)
  is wired by T032 (Phase 4 service integration); this module returns
  the dict the caller is expected to append.
"""

from __future__ import annotations

import datetime as _dt
import logging
import re
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Final, Optional


_LOG = logging.getLogger(__name__)


# ─── 12-entry event-type catalog (research §R11) ────────────────────────

LAYOUT_CREATED: Final[str] = "managed_layout_created"
LAYOUT_STATE_CHANGED: Final[str] = "managed_layout_state_changed"
PANE_CREATED: Final[str] = "managed_pane_created"
PANE_STATE_CHANGED: Final[str] = "managed_pane_state_changed"
PANE_RECREATED: Final[str] = "managed_pane_recreated"
PANE_REMOVED: Final[str] = "managed_pane_removed"
PANE_PENDING_MARKER_SET: Final[str] = "managed_pane_pending_marker_set"
PANE_PENDING_MARKER_CLEARED: Final[str] = "managed_pane_pending_marker_cleared"
PANE_LAUNCH_COMMAND_EXITED: Final[str] = "managed_pane_launch_command_exited"
PANE_LOG_ATTACH_FAILED: Final[str] = "managed_pane_log_attach_failed"
LAYOUT_RECOVERY_REATTACHED: Final[str] = "managed_layout_recovery_reattached"
LAYOUT_RECOVERY_FAILED: Final[str] = "managed_layout_recovery_failed"


ALL_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        LAYOUT_CREATED,
        LAYOUT_STATE_CHANGED,
        PANE_CREATED,
        PANE_STATE_CHANGED,
        PANE_RECREATED,
        PANE_REMOVED,
        PANE_PENDING_MARKER_SET,
        PANE_PENDING_MARKER_CLEARED,
        PANE_LAUNCH_COMMAND_EXITED,
        PANE_LOG_ATTACH_FAILED,
        LAYOUT_RECOVERY_REATTACHED,
        LAYOUT_RECOVERY_FAILED,
    }
)


# ─── Origin tag (FEAT-008 audit) ────────────────────────────────────────

ORIGIN: Final[str] = "managed"


# ─── FR-021 amendment: env-var redaction policy ─────────────────────────
#
# Substring (not whole-word) match against the env key; case-insensitive.
# Per spec §Clarifications "Session 2026-05-24 (pre-implement walk)" Q3.

_REDACT_KEY_PATTERNS: Final[tuple[str, ...]] = (
    "TOKEN",
    "SECRET",
    "KEY",
    "PASSWORD",
    # L5 hardening: extend the substring set to cover the common
    # credential-naming conventions that the original 4-entry list
    # missed. All matched as case-insensitive substrings.
    "PASSWD",
    "PWD",  # matches "DB_PWD" etc.
    "AUTH",
    "BEARER",
    "CREDENTIAL",  # matches CREDENTIAL + CREDENTIALS
    "COOKIE",
    "SESSION",
    "PRIVATE",  # matches PRIVATE_KEY (caught) + PRIVATE_TOKEN etc.
    "API",  # matches API_KEY (caught) + API_SECRET (caught) but also
            # plain "API_HOST" — over-redacts. Trade-off accepted:
            # FR-021 amendment treats the env redaction as best-
            # effort defense in depth (no payload currently carries
            # env at all).
)

REDACTED_PLACEHOLDER: Final[str] = "<redacted>"


def _key_is_sensitive(key: str) -> bool:
    upper = key.upper()
    return any(pat in upper for pat in _REDACT_KEY_PATTERNS)


def redact_env(env: dict[str, str]) -> dict[str, str]:
    """Return a copy of ``env`` with sensitive values replaced by ``<redacted>``.

    Sensitive keys are matched case-insensitively against the substring
    set in :data:`_REDACT_KEY_PATTERNS` (TOKEN/SECRET/KEY/PASSWORD plus
    the L5-extended set: PASSWD/PWD/AUTH/BEARER/CREDENTIAL/COOKIE/
    SESSION/PRIVATE/API). Argv and ``working_dir`` are NOT redacted
    (operator-visible diagnostics rely on them — FR-021 amendment).
    """
    return {
        k: (REDACTED_PLACEHOLDER if _key_is_sensitive(k) else v) for k, v in env.items()
    }


# ─── Event envelope builder ─────────────────────────────────────────────


def _utc_now_rfc3339() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def build_event(
    event_type: str,
    *,
    actor: str,
    layout_id: str | None = None,
    pane_id: str | None = None,
    sequence: int,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a JSONL audit envelope for a FEAT-013 lifecycle event.

    Parameters
    ----------
    event_type:
        One of ``ALL_EVENT_TYPES``; raises ``ValueError`` otherwise.
    actor:
        Either ``"operator"`` (explicit request) or ``"daemon"`` (sweep /
        recovery / FEAT-004 scan reaction). Required so consumers can
        filter automated from operator-initiated transitions.
    layout_id, pane_id:
        At least one MUST be set. Layout-scoped events (e.g.,
        ``managed_layout_*``) carry ``layout_id``; pane-scoped events
        carry both. Type checks are advisory at this layer.
    sequence:
        Per-pane (when ``pane_id`` is set) or per-layout (otherwise)
        monotonically increasing integer maintained by the caller, so
        consumers can assemble per-pane / per-layout FIFO ordering even
        if the JSONL pipeline interleaves writes from different scopes
        (FR-015 amendment). Cross-scope ordering is best-effort by
        timestamp.
    payload:
        Event-type-specific data; defaults to ``{}``. Callers MUST
        ensure ``env`` fields are pre-redacted via :func:`redact_env`.
    """
    if event_type not in ALL_EVENT_TYPES:
        raise ValueError(f"unknown FEAT-013 event_type: {event_type!r}")
    if actor not in ("operator", "daemon"):
        raise ValueError(f"actor must be 'operator' or 'daemon', got {actor!r}")
    if layout_id is None and pane_id is None:
        raise ValueError("at least one of layout_id / pane_id must be set")
    return {
        "origin": ORIGIN,
        "event_type": event_type,
        "actor": actor,
        "layout_id": layout_id,
        "pane_id": pane_id,
        "sequence": sequence,
        "payload": dict(payload) if payload else {},
        "timestamp": _utc_now_rfc3339(),
    }


# Bounded backlog of lifecycle events awaiting a successful JSONL append.
# Mirrors the FEAT-010 ``QueueAuditWriter`` deque cap — keeps a persistent
# events-file outage from growing memory without bound.
_MAX_PENDING_EVENTS: Final[int] = 1024


class _ManagedEventEmitter:
    """Callable JSONL event emitter with a bounded retry buffer (review P2).

    Managed lifecycle events are spec'd to ride the FEAT-008 JSONL pipeline
    and be retained indefinitely in MVP (FR-015 / FR-021). The previous
    emitter caught a transient ``OSError`` and dropped the event
    permanently and silently. This emitter instead buffers a failed write
    in a bounded FIFO deque and retries the whole backlog on every
    subsequent emit (drain-on-emit): a transient disk/mode error self-heals
    as soon as the next event is emitted. A persistent failure keeps the
    buffer at its cap (oldest evicted and counted as a hard drop) and the
    emitter ``degraded`` — both observable via the properties below and the
    module-level accessors a future status RPC can read.

    The durable SQLite row remains the source of truth for lifecycle state;
    a JSONL write failure must still never fail an operator's mutation, so
    ``__call__`` never raises.
    """

    def __init__(
        self, events_file: Path, *, max_pending: int = _MAX_PENDING_EVENTS
    ) -> None:
        self._events_file = events_file
        self._pending: deque[dict[str, object]] = deque(maxlen=max_pending)
        self._lock = threading.Lock()
        self._degraded_exc_class: Optional[str] = None
        self._dropped = 0

    def __call__(self, envelope: dict[str, object]) -> None:
        from ..events.writer import append_event

        with self._lock:
            if (
                self._pending.maxlen is not None
                and len(self._pending) == self._pending.maxlen
            ):
                # Appending at capacity evicts the oldest still-unwritten
                # event — count it as a hard loss for observability.
                self._dropped += 1
            self._pending.append(envelope)

            # Drain FIFO; stop at the first failure so ordering is
            # preserved and the remainder stays buffered for next time.
            while self._pending:
                head = self._pending[0]
                try:
                    append_event(self._events_file, head)
                except OSError as exc:
                    first_failure = self._degraded_exc_class is None
                    self._degraded_exc_class = type(exc).__name__
                    _LOG.warning(
                        "managed_sessions: events-file append failed; "
                        "buffered for retry (pending=%d dropped=%d): %s",
                        len(self._pending),
                        self._dropped,
                        exc,
                        # Full traceback once per degraded episode only.
                        exc_info=first_failure,
                    )
                    return
                self._pending.popleft()

            # Fully drained — clear the degraded marker.
            self._degraded_exc_class = None

    @property
    def degraded(self) -> bool:
        with self._lock:
            return len(self._pending) > 0

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def dropped_count(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def last_failure_exc_class(self) -> Optional[str]:
        with self._lock:
            return self._degraded_exc_class


# Shared per events-file path so the per-request emitters the handlers
# build (handlers/cli.py, handlers/app.py) and the daemon-boot/recovery
# emitter all funnel through ONE retry buffer + degraded flag.
_EMITTERS_LOCK = threading.Lock()
_EMITTERS: dict[str, _ManagedEventEmitter] = {}


def make_managed_event_emitter(
    events_file: Optional[Path],
) -> Optional[Callable[[dict[str, object]], None]]:
    """Build (or reuse) the JSONL-append event emitter the service expects.

    The managed service entry points (``create_layout`` / ``remove_pane`` /
    ``recreate_pane`` / ``spawn_layout_in_background`` / ``reconcile``) take
    an ``Optional[event_emitter]`` and call ``event_emitter(build_event(...))``.
    This binds that callable to the daemon's FEAT-008 JSONL events file via
    :class:`_ManagedEventEmitter` — the production write site that closes the
    FR-015 "MUST emit observable lifecycle events" gap (the handlers
    previously passed no emitter, so events were never persisted).

    Returns ``None`` when ``events_file`` is ``None`` so callers can pass
    the result straight through to the service's optional parameter (tests
    that own no events file get the historical no-emit behaviour).

    The returned emitter is **shared per events-file path** so a degraded
    episode (and its retry backlog) is visible across the per-request
    emitters the handlers construct.
    """
    if events_file is None:
        return None

    key = str(events_file)
    with _EMITTERS_LOCK:
        emitter = _EMITTERS.get(key)
        if emitter is None:
            emitter = _ManagedEventEmitter(Path(events_file))
            _EMITTERS[key] = emitter
        return emitter


def managed_event_persistence_degraded(events_file: Optional[Path]) -> bool:
    """True iff the shared emitter for ``events_file`` is holding an
    undrained backlog (review P2 — for a future status surface)."""
    if events_file is None:
        return False
    with _EMITTERS_LOCK:
        emitter = _EMITTERS.get(str(events_file))
    return emitter.degraded if emitter is not None else False


def managed_event_pending_count(events_file: Optional[Path]) -> int:
    """Number of lifecycle events buffered awaiting a successful append."""
    if events_file is None:
        return 0
    with _EMITTERS_LOCK:
        emitter = _EMITTERS.get(str(events_file))
    return emitter.pending_count if emitter is not None else 0
