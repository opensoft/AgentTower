"""FEAT-013 pending-managed marker (T012).

Tracks ``managed_pane`` rows mid-creation via:

* SQLite — the ``managed_pane.pending_marker_token TEXT NULL`` column
  (set on row insert before tmux spawn; cleared on transition to ``ready``).
* Tmux pane title — ``@MANAGED:<token>:<label>`` set via ``tmux select-pane -T``
  immediately before the spawning ``new-session`` / ``split-window`` call.
  Visible to FEAT-004's ``list-panes -F '#{pane_title}'`` formatter so the
  scan can skip pending-managed panes without modification.

Per FR-022 (research §R5), markers older than 5 minutes are swept:
``managed_pane`` rows still in ``state='creating'`` are transitioned to
``failed`` with ``failed_stage='pane_create'`` (no tmux pane) or
``'registration'`` (tmux pane exists but never registered). The sweep
runs at boot and every 60 seconds.

This module exposes the data-shape constants + a parse helper. The
SQLite read/write side is owned by ``service.py`` (T022/T046); the tmux
title side is owned by ``tmux_create.py`` (T011). The actual sweep loop
is wired by ``T050`` in Phase 6.
"""

from __future__ import annotations

import re
import uuid
from typing import Final

# Marker TTL — research §R5, codified in FR-022.
MARKER_TTL_SECONDS: Final[int] = 5 * 60

# Periodic sweep cadence (research §R5: "boot + 60s periodic").
SWEEP_INTERVAL_SECONDS: Final[int] = 60

# Tmux pane-title prefix that the FEAT-004 scan skips on.
MARKER_TITLE_PREFIX: Final[str] = "@MANAGED:"

# Regex for parsing a tmux pane title set by this module:
#   ``@MANAGED:<token>:<label>``
# ``<token>`` is a uuid4 string (or an operator-supplied idempotency_key
# per research §R10). ``<label>`` is the human-readable pane label
# (FR-003).
_TITLE_RE: Final[re.Pattern[str]] = re.compile(
    r"^@MANAGED:(?P<token>[^:]+):(?P<label>.+)$"
)


def new_marker_token() -> str:
    """Return a fresh marker token (uuid4 string).

    Service callers use the operator-supplied ``idempotency_key`` when
    present (research §R10 collapses dedupe-key and marker-token into a
    single identifier); this helper is the fallback.
    """
    return str(uuid.uuid4())


def format_title(token: str, label: str) -> str:
    """Build the tmux pane title for a pending-managed pane.

    Service callers set this title via ``tmux select-pane -T <title>``
    BEFORE the spawning ``new-session`` / ``split-window`` call so the
    FEAT-004 scan never sees a pane without the marker.
    """
    if not token:
        raise ValueError("token must be non-empty")
    if not label:
        raise ValueError("label must be non-empty")
    if ":" in token:
        raise ValueError("token must not contain ':'")
    return f"{MARKER_TITLE_PREFIX}{token}:{label}"


def parse_title(title: str) -> tuple[str, str] | None:
    """Return ``(token, label)`` if ``title`` is a marker title, else ``None``.

    The FEAT-004 scan calls this on every observed tmux pane title; a
    non-``None`` return value means "this pane belongs to an in-flight
    managed creation — skip adoption" (FR-014).
    """
    match = _TITLE_RE.match(title)
    if match is None:
        return None
    return match.group("token"), match.group("label")


def is_marker_title(title: str) -> bool:
    """Convenience: True iff ``title`` is a marker title."""
    return parse_title(title) is not None
