"""FEAT-009 closed-set error codes, exit-code map, audit-event sets, exceptions.

Re-exports the FEAT-009 string codes from ``agenttower.socket_api.errors``
(the canonical declaration site — they live in the FEAT-002
``CLOSED_CODE_SET`` frozen-set), then layers on the FEAT-009-specific
public surface:

* :data:`CLI_EXIT_CODE_MAP` — the integer exit-code map from
  ``contracts/error-codes.md`` "Integer exit code map". Integer codes
  MAY shift across MVP revisions per FR-050; the string codes are the
  stable contract.
* :data:`_QUEUE_AUDIT_EVENT_TYPES` — the seven ``queue_message_*`` audit
  event types consumed by the R-008 disjointness test (T086).
* :data:`_ROUTING_AUDIT_EVENT_TYPES` — the singleton ``{"routing_toggled"}``
  audit event type for kill-switch toggles (Contracts §socket-routing).
* Exception classes (:class:`QueueServiceError`, :class:`TargetResolveError`,
  :class:`TmuxDeliveryError`, :class:`SqliteLockConflict`,
  :class:`OperatorPaneInactive`) consumed by the service / DAO / worker
  layers.
"""

from __future__ import annotations

from typing import Final

# Re-export the string codes from the canonical declaration site so
# FEAT-009 modules don't have to import socket_api/errors.py directly.
# (Listed alphabetically — matches FR-049 / data-model §8.)
from agenttower.socket_api.errors import (
    AGENT_NOT_FOUND,
    APPROVAL_NOT_APPLICABLE,
    BODY_EMPTY,
    BODY_INVALID_CHARS,
    BODY_INVALID_ENCODING,
    BODY_TOO_LARGE,
    DAEMON_SHUTTING_DOWN,
    DAEMON_UNAVAILABLE,
    DELAY_NOT_APPLICABLE,
    DELIVERY_IN_PROGRESS,
    DELIVERY_WAIT_TIMEOUT,
    KILL_SWITCH_OFF,
    MESSAGE_ID_NOT_FOUND,
    OPERATOR_PANE_INACTIVE,
    ROUTING_DISABLED,
    ROUTING_TOGGLE_HOST_ONLY,
    SENDER_NOT_IN_PANE,
    SENDER_ROLE_NOT_PERMITTED,
    SINCE_INVALID_FORMAT,
    TARGET_CONTAINER_INACTIVE,
    TARGET_LABEL_AMBIGUOUS,
    TARGET_NOT_ACTIVE,
    TARGET_PANE_MISSING,
    TARGET_ROLE_NOT_PERMITTED,
    TERMINAL_STATE_CANNOT_CHANGE,
)


# ──────────────────────────────────────────────────────────────────────
# Audit event-type closed sets (consumed by R-008 disjointness test T086)
# ──────────────────────────────────────────────────────────────────────

_QUEUE_AUDIT_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "queue_message_enqueued",
        "queue_message_delivered",
        "queue_message_blocked",
        "queue_message_failed",
        "queue_message_canceled",
        "queue_message_approved",
        "queue_message_delayed",
    }
)
"""Seven ``queue_message_*`` audit event types (FR-046)."""


_ROUTING_AUDIT_EVENT_TYPES: Final[frozenset[str]] = frozenset({"routing_toggled"})
"""Singleton routing-toggle audit event type (FR-046 + Contracts §socket-routing)."""


# ──────────────────────────────────────────────────────────────────────
# Failure-reason closed set (matches data-model §4.3 + spec FR-018)
# ──────────────────────────────────────────────────────────────────────

_FAILURE_REASONS: Final[frozenset[str]] = frozenset(
    {
        "attempt_interrupted",
        "tmux_paste_failed",
        "docker_exec_failed",
        "tmux_send_keys_failed",
        "pane_disappeared_mid_attempt",
        "sqlite_lock_conflict",
    }
)


# ──────────────────────────────────────────────────────────────────────
# Block-reason closed set (matches data-model §4.2 + spec FR-017)
# ──────────────────────────────────────────────────────────────────────

_BLOCK_REASONS: Final[frozenset[str]] = frozenset(
    {
        "sender_role_not_permitted",
        "target_role_not_permitted",
        "target_not_active",
        "target_pane_missing",
        "target_container_inactive",
        "kill_switch_off",
        "operator_delayed",
    }
)


# ──────────────────────────────────────────────────────────────────────
# Integer exit-code map (contracts/error-codes.md "Integer exit code map")
# ──────────────────────────────────────────────────────────────────────

CLI_EXIT_CODE_MAP: Final[dict[str, int]] = {
    # Success path falls through to exit 0 — not in the map.
    DELIVERY_WAIT_TIMEOUT: 1,
    ROUTING_DISABLED: 2,
    SENDER_NOT_IN_PANE: 3,
    SENDER_ROLE_NOT_PERMITTED: 4,
    AGENT_NOT_FOUND: 5,
    TARGET_LABEL_AMBIGUOUS: 6,
    TARGET_NOT_ACTIVE: 7,
    TARGET_ROLE_NOT_PERMITTED: 8,
    TARGET_CONTAINER_INACTIVE: 9,
    TARGET_PANE_MISSING: 10,
    # The four body-validation rejections share exit 11 (different
    # remediation surfaces via the string code).
    BODY_EMPTY: 11,
    BODY_INVALID_ENCODING: 11,
    BODY_INVALID_CHARS: 11,
    BODY_TOO_LARGE: 11,
    DAEMON_UNAVAILABLE: 12,
    DAEMON_SHUTTING_DOWN: 12,
    # Exit 13 is the catch-all for non-`attempt_interrupted` worker
    # failure_reason values surfaced through send-input's terminal-failure
    # path (`tmux_paste_failed`, `docker_exec_failed`,
    # `tmux_send_keys_failed`, `pane_disappeared_mid_attempt`,
    # `sqlite_lock_conflict`). The send-input CLI inspects the row's
    # failure_reason string for operator-readable detail.
    "tmux_paste_failed": 13,
    "docker_exec_failed": 13,
    "tmux_send_keys_failed": 13,
    "pane_disappeared_mid_attempt": 13,
    "sqlite_lock_conflict": 13,
    "attempt_interrupted": 13,
    SINCE_INVALID_FORMAT: 14,
    TERMINAL_STATE_CANNOT_CHANGE: 15,
    DELIVERY_IN_PROGRESS: 16,
    APPROVAL_NOT_APPLICABLE: 17,
    DELAY_NOT_APPLICABLE: 18,
    ROUTING_TOGGLE_HOST_ONLY: 19,
    MESSAGE_ID_NOT_FOUND: 20,
    OPERATOR_PANE_INACTIVE: 21,
    # bad_request / unknown_method use argparse-style exit 64 (FEAT-002).
    "bad_request": 64,
    "unknown_method": 64,
}
"""String-code → integer-exit-code mapping (MVP).

Per FR-050, the *integer* codes may shift across MVP revisions; the
*string* codes are the stable contract. CLI handlers MUST always emit
the string code through ``--json``; the integer is operator-facing
only.
"""


def cli_exit_code(string_code: str) -> int:
    """Map a closed-set string code to its CLI integer exit code.

    Falls back to ``1`` for unknown codes (defensive — the closed set
    is statically enforced by :data:`agenttower.socket_api.errors.CLOSED_CODE_SET`
    so this branch should be unreachable).
    """
    return CLI_EXIT_CODE_MAP.get(string_code, 1)


# ──────────────────────────────────────────────────────────────────────
# FEAT-009 exception classes
# ──────────────────────────────────────────────────────────────────────


class QueueServiceError(Exception):
    """Base class for FEAT-009 service-layer errors that map to closed-set codes.

    Subclasses carry a ``code`` attribute equal to the closed-set string
    code; the socket dispatch layer maps it to the FEAT-002 error envelope
    via ``make_error``.
    """

    code: str = ""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class TargetResolveError(QueueServiceError):
    """Raised by :func:`routing.target_resolver.resolve_target` on lookup miss
    or ambiguous label (code: ``agent_not_found`` / ``target_label_ambiguous``).
    """


class TmuxDeliveryError(QueueServiceError):
    """Raised by the tmux adapter / worker for any FR-018 failure_reason.

    The ``code`` attribute holds the closed-set ``failure_reason`` value
    (not a CLI error code); the worker reads ``code`` to populate
    ``message_queue.failure_reason``.
    """


class SqliteLockConflict(TmuxDeliveryError):
    """Raised after the bounded retry exhausts on a SQLite ``BEGIN IMMEDIATE``
    lock conflict (Group-A walk Q5).

    The worker transitions the row to ``failed`` with
    ``failure_reason='sqlite_lock_conflict'``.
    """

    def __init__(self, message: str = "SQLite BEGIN IMMEDIATE lock conflict") -> None:
        super().__init__("sqlite_lock_conflict", message)


class OperatorPaneInactive(QueueServiceError):
    """Raised at the operator-action dispatch boundary when the caller's
    pane resolves to an inactive or deregistered FEAT-006 agent
    (Group-A walk Q8). Host-origin callers do NOT trigger this; they
    write the ``host-operator`` sentinel."""

    def __init__(self, message: str = "operator caller pane resolves to inactive agent") -> None:
        super().__init__(OPERATOR_PANE_INACTIVE, message)


__all__ = [
    # String code re-exports
    "AGENT_NOT_FOUND",
    "APPROVAL_NOT_APPLICABLE",
    "BODY_EMPTY",
    "BODY_INVALID_CHARS",
    "BODY_INVALID_ENCODING",
    "BODY_TOO_LARGE",
    "DAEMON_SHUTTING_DOWN",
    "DAEMON_UNAVAILABLE",
    "DELAY_NOT_APPLICABLE",
    "DELIVERY_IN_PROGRESS",
    "DELIVERY_WAIT_TIMEOUT",
    "KILL_SWITCH_OFF",
    "MESSAGE_ID_NOT_FOUND",
    "OPERATOR_PANE_INACTIVE",
    "ROUTING_DISABLED",
    "ROUTING_TOGGLE_HOST_ONLY",
    "SENDER_NOT_IN_PANE",
    "SENDER_ROLE_NOT_PERMITTED",
    "SINCE_INVALID_FORMAT",
    "TARGET_CONTAINER_INACTIVE",
    "TARGET_LABEL_AMBIGUOUS",
    "TARGET_NOT_ACTIVE",
    "TARGET_PANE_MISSING",
    "TARGET_ROLE_NOT_PERMITTED",
    "TERMINAL_STATE_CANNOT_CHANGE",
    # Audit event-type sets
    "_QUEUE_AUDIT_EVENT_TYPES",
    "_ROUTING_AUDIT_EVENT_TYPES",
    "_FAILURE_REASONS",
    "_BLOCK_REASONS",
    # Exit-code map
    "CLI_EXIT_CODE_MAP",
    "cli_exit_code",
    # Exceptions
    "QueueServiceError",
    "TargetResolveError",
    "TmuxDeliveryError",
    "SqliteLockConflict",
    "OperatorPaneInactive",
]
