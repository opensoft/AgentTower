"""Prompt routing and queueing (FEAT-009).

Public surface for the FEAT-009 ``send-input`` queue, routing kill
switch, and tmux-safe delivery layer. The submodules expose the full
typed API; this ``__init__`` re-exports a curated public set plus the
``[routing]`` configuration defaults.

The ``DEFAULT_*`` constants below match ``plan.md`` §"Defaults locked"
and are the single source of truth for the daemon's defaults when no
``[routing]`` section appears in ``config.toml``.
"""

from __future__ import annotations

from typing import Final

from agenttower.agents.identifiers import HOST_OPERATOR_SENTINEL

from .errors import (
    _QUEUE_AUDIT_EVENT_TYPES,
    _ROUTE_AUDIT_EVENT_TYPES,
    _ROUTING_AUDIT_EVENT_TYPES,
    CLI_EXIT_CODE_MAP,
    OperatorPaneInactive,
    QueueServiceError,
    SqliteLockConflict,
    TargetResolveError,
    TmuxDeliveryError,
    cli_exit_code,
)


# ──────────────────────────────────────────────────────────────────────
# [routing] configuration defaults (plan.md §"Defaults locked")
# ──────────────────────────────────────────────────────────────────────

DEFAULT_ENVELOPE_BODY_MAX_BYTES: Final[int] = 65_536
"""Cap on the SERIALIZED envelope (FR-004 + Assumptions §"Body size cap")."""

DEFAULT_EXCERPT_MAX_CHARS: Final[int] = 240
"""Excerpt cap (FR-011 + FR-047b + Q3 of 2026-05-11)."""

DEFAULT_EXCERPT_TRUNCATION_MARKER: Final[str] = "…"
"""U+2026 truncation marker (FR-047b)."""

DEFAULT_SEND_INPUT_DEFAULT_WAIT_SECONDS: Final[float] = 10.0
"""``send-input`` default wait timeout (FR-009 + Assumptions §"CLI default wait")."""

DEFAULT_DELIVERY_ATTEMPT_TIMEOUT_SECONDS: Final[float] = 5.0
"""Per-tmux-invocation timeout (Assumptions §"Per-attempt delivery timeout";
research §R-009). Strictly less than ``DEFAULT_SEND_INPUT_DEFAULT_WAIT_SECONDS``."""

DEFAULT_DELIVERY_WORKER_IDLE_POLL_SECONDS: Final[float] = 0.1
"""Empty-queue wakeup granularity (plan.md §"Defaults locked")."""

DEFAULT_DEGRADED_AUDIT_BUFFER_MAX_ROWS: Final[int] = 1024
"""Bounded deque cap for JSONL-degraded audit retry buffer (plan.md
§"Defaults locked"; Group-A walk Q6 + research §R-009)."""

DEFAULT_SUBMIT_KEYSTROKE: Final[str] = "Enter"
"""tmux submit key (Assumptions §"Submit keystroke is Enter")."""


# Sanity invariant pinned at module load: attempt timeout < wait timeout.
assert DEFAULT_DELIVERY_ATTEMPT_TIMEOUT_SECONDS < DEFAULT_SEND_INPUT_DEFAULT_WAIT_SECONDS, (
    "Spec §Assumptions: delivery_attempt_timeout_seconds MUST be strictly "
    "less than send_input_default_wait_seconds"
)


__all__ = [
    "HOST_OPERATOR_SENTINEL",
    "DEFAULT_ENVELOPE_BODY_MAX_BYTES",
    "DEFAULT_EXCERPT_MAX_CHARS",
    "DEFAULT_EXCERPT_TRUNCATION_MARKER",
    "DEFAULT_SEND_INPUT_DEFAULT_WAIT_SECONDS",
    "DEFAULT_DELIVERY_ATTEMPT_TIMEOUT_SECONDS",
    "DEFAULT_DELIVERY_WORKER_IDLE_POLL_SECONDS",
    "DEFAULT_DEGRADED_AUDIT_BUFFER_MAX_ROWS",
    "DEFAULT_SUBMIT_KEYSTROKE",
    "_QUEUE_AUDIT_EVENT_TYPES",
    "_ROUTE_AUDIT_EVENT_TYPES",
    "_ROUTING_AUDIT_EVENT_TYPES",
    "CLI_EXIT_CODE_MAP",
    "cli_exit_code",
    "OperatorPaneInactive",
    "QueueServiceError",
    "SqliteLockConflict",
    "TargetResolveError",
    "TmuxDeliveryError",
]
