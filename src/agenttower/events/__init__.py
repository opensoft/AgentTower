"""Event ingestion and classification.

FEAT-008 imports the FR-045 / Plan §"Defaults locked" constants from
this module. The FEAT-001 JSONL writer (``append_event``) is
re-exported unchanged.
"""

from __future__ import annotations

from .writer import append_event

# FR-045 / Plan §"Defaults locked" — single source of truth for the
# numeric defaults named in spec.md FR-001 / FR-013 / FR-014 / FR-017 /
# FR-019 / FR-030 plus the plan-level additions for the follow long-poll
# surface. ``agenttower.config.load_events_block`` overlays user
# overrides (``[events]`` in ``config.toml``); the constants below are
# the fallback when no override is present.

#: FR-001 / SC-002 — wall-clock cap on a single reader cycle.
READER_CYCLE_WALLCLOCK_CAP_SECONDS: float = 1.0

#: FR-019 — bytes the reader will consume per attachment per cycle.
PER_CYCLE_BYTE_CAP_BYTES: int = 65536

#: spec §"Edge Cases" — cap on a single event's stored excerpt
#: (post-redaction, pre-truncation).
PER_EVENT_EXCERPT_CAP_BYTES: int = 1024

#: spec §"Edge Cases" — appended to truncated excerpts.
EXCERPT_TRUNCATION_MARKER: str = "…[truncated]"

#: FR-014 — collapse window for ``activity`` debounce.
DEBOUNCE_ACTIVITY_WINDOW_SECONDS: float = 5.0

#: FR-017 — grace window before ``pane_exited`` is emitted.
PANE_EXITED_GRACE_SECONDS: float = 30.0

#: FR-013 — grace window before ``long_running`` is emitted.
LONG_RUNNING_GRACE_SECONDS: float = 30.0

#: FR-030 — default page size for ``agenttower events``.
DEFAULT_PAGE_SIZE: int = 50

#: FR-030 — maximum page size accepted from clients.
MAX_PAGE_SIZE: int = 50

#: Plan §"Defaults locked" — server-side wait budget per
#: ``events.follow_next`` call.
FOLLOW_LONG_POLL_MAX_SECONDS: float = 30.0

#: Plan §"Defaults locked" — idle GC for follow sessions.
FOLLOW_SESSION_IDLE_TIMEOUT_SECONDS: float = 300.0


__all__ = [
    "append_event",
    "READER_CYCLE_WALLCLOCK_CAP_SECONDS",
    "PER_CYCLE_BYTE_CAP_BYTES",
    "PER_EVENT_EXCERPT_CAP_BYTES",
    "EXCERPT_TRUNCATION_MARKER",
    "DEBOUNCE_ACTIVITY_WINDOW_SECONDS",
    "PANE_EXITED_GRACE_SECONDS",
    "LONG_RUNNING_GRACE_SECONDS",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "FOLLOW_LONG_POLL_MAX_SECONDS",
    "FOLLOW_SESSION_IDLE_TIMEOUT_SECONDS",
]
