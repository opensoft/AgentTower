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
import re
from typing import Final


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
