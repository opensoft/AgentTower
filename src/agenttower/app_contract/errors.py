"""FEAT-011 closed-set error codes and per-code ``details`` registry.

Implements:
- FR-034: 26-entry closed code set; ``error.code`` MUST match ``^[a-z][a-z0-9_]*$``.
- FR-034a: per-code ``details`` registry of required keys. Codes not in the
  registry MUST carry ``error.details == {}``.
- FR-033: ``error.details`` is always a JSON object (never null/array/primitive).

This module does NOT depend on any other ``app_contract`` module — the
envelope builders in ``envelope.py`` consume it.
"""

from __future__ import annotations

import re
from typing import Final


# ─── Closed-set error codes (FR-034) ─────────────────────────────────────

APP_SESSION_REQUIRED: Final[str] = "app_session_required"
APP_SESSION_EXPIRED: Final[str] = "app_session_expired"
APP_CONTRACT_MAJOR_UNSUPPORTED: Final[str] = "app_contract_major_unsupported"
UNKNOWN_METHOD: Final[str] = "unknown_method"
VALIDATION_FAILED: Final[str] = "validation_failed"
NOT_FOUND: Final[str] = "not_found"
STALE_OBJECT: Final[str] = "stale_object"
PANE_ALREADY_REGISTERED: Final[str] = "pane_already_registered"
PANE_NOT_FOUND: Final[str] = "pane_not_found"
AGENT_NOT_FOUND: Final[str] = "agent_not_found"
ROUTE_NOT_FOUND: Final[str] = "route_not_found"
QUEUE_MESSAGE_NOT_FOUND: Final[str] = "queue_message_not_found"
SCAN_TIMEOUT: Final[str] = "scan_timeout"
SCAN_NOT_FOUND: Final[str] = "scan_not_found"
DAEMON_UNAVAILABLE: Final[str] = "daemon_unavailable"
SOCKET_MISSING: Final[str] = "socket_missing"
SOCKET_PERMISSION_DENIED: Final[str] = "socket_permission_denied"
DOCKER_UNAVAILABLE: Final[str] = "docker_unavailable"
TMUX_UNAVAILABLE: Final[str] = "tmux_unavailable"
CONTAINER_INACTIVE: Final[str] = "container_inactive"
LOG_ATTACH_BLOCKED: Final[str] = "log_attach_blocked"
ROUTING_DISABLED: Final[str] = "routing_disabled"
PERMISSION_DENIED: Final[str] = "permission_denied"
HOST_ONLY: Final[str] = "host_only"
PAYLOAD_TOO_LARGE: Final[str] = "payload_too_large"
INTERNAL_ERROR: Final[str] = "internal_error"

# Authoritative closed set — 26 entries at v1.0. Adding a code is an additive
# minor change (FR-034, FR-035); removing or renaming a code requires a major
# bump (FR-035).
ERROR_CODES: Final[frozenset[str]] = frozenset({
    APP_SESSION_REQUIRED,
    APP_SESSION_EXPIRED,
    APP_CONTRACT_MAJOR_UNSUPPORTED,
    UNKNOWN_METHOD,
    VALIDATION_FAILED,
    NOT_FOUND,
    STALE_OBJECT,
    PANE_ALREADY_REGISTERED,
    PANE_NOT_FOUND,
    AGENT_NOT_FOUND,
    ROUTE_NOT_FOUND,
    QUEUE_MESSAGE_NOT_FOUND,
    SCAN_TIMEOUT,
    SCAN_NOT_FOUND,
    DAEMON_UNAVAILABLE,
    SOCKET_MISSING,
    SOCKET_PERMISSION_DENIED,
    DOCKER_UNAVAILABLE,
    TMUX_UNAVAILABLE,
    CONTAINER_INACTIVE,
    LOG_ATTACH_BLOCKED,
    ROUTING_DISABLED,
    PERMISSION_DENIED,
    HOST_ONLY,
    PAYLOAD_TOO_LARGE,
    INTERNAL_ERROR,
})


# Code shape gate (FR-034). Every code MUST match this regex AND be in
# ERROR_CODES.
CODE_REGEX: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_]*$")


# ─── Per-code ``details`` registry (FR-034a) ──────────────────────────────

# Maps code → set of required key names. Codes not listed MUST carry
# ``error.details == {}``. Extra keys are allowed and additive across
# minors; removing a required key requires a major bump (FR-034a).
DETAILS_REQUIRED_KEYS: Final[dict[str, frozenset[str]]] = {
    VALIDATION_FAILED: frozenset({"field", "reason"}),
    APP_CONTRACT_MAJOR_UNSUPPORTED: frozenset({
        "daemon_app_contract_version",
        "client_app_contract_major",
    }),
    PANE_ALREADY_REGISTERED: frozenset({"agent_id"}),
    PANE_NOT_FOUND: frozenset({"pane_id"}),
    AGENT_NOT_FOUND: frozenset({"agent_id"}),
    ROUTE_NOT_FOUND: frozenset({"route_id"}),
    QUEUE_MESSAGE_NOT_FOUND: frozenset({"message_id"}),
    SCAN_TIMEOUT: frozenset({"scan_id"}),
    SCAN_NOT_FOUND: frozenset({"scan_id"}),
    CONTAINER_INACTIVE: frozenset({"container_id"}),
    LOG_ATTACH_BLOCKED: frozenset({"agent_id", "reason"}),
    PAYLOAD_TOO_LARGE: frozenset({"size_limit_bytes", "actual_size_bytes"}),
}


class ContractViolation(Exception):
    """Raised by ``envelope.failure()`` when a handler emits a malformed
    failure envelope (unknown code, missing required ``details`` key,
    or non-object ``details``). Should NEVER reach a client — the
    dispatcher catches it and emits a generic ``internal_error`` instead.
    Indicates a daemon-side bug.
    """


def validate_details(code: str, details: dict) -> None:
    """Assert that ``details`` carries every required key for ``code``.

    Raises ContractViolation if:
    - ``code`` is not in the closed set, OR
    - ``code`` does not match the FR-034 regex, OR
    - ``details`` is not a dict, OR
    - a code with structured ``details`` is missing a required key.

    Codes not in ``DETAILS_REQUIRED_KEYS`` MUST carry ``details == {}``
    or any superset that does not include reserved keys; FR-034a leaves
    additional optional keys permitted across all codes.
    """
    if not isinstance(code, str) or not CODE_REGEX.match(code):
        raise ContractViolation(
            f"error.code must match ^[a-z][a-z0-9_]*$, got {code!r}"
        )
    if code not in ERROR_CODES:
        raise ContractViolation(
            f"error.code {code!r} is not in the FR-034 closed set"
        )
    if not isinstance(details, dict):
        raise ContractViolation(
            f"error.details must be a JSON object, got {type(details).__name__}"
        )
    required = DETAILS_REQUIRED_KEYS.get(code, frozenset())
    missing = required - set(details.keys())
    if missing:
        raise ContractViolation(
            f"error.details for {code!r} missing required key(s): "
            f"{sorted(missing)}"
        )


__all__ = [
    "APP_SESSION_REQUIRED",
    "APP_SESSION_EXPIRED",
    "APP_CONTRACT_MAJOR_UNSUPPORTED",
    "UNKNOWN_METHOD",
    "VALIDATION_FAILED",
    "NOT_FOUND",
    "STALE_OBJECT",
    "PANE_ALREADY_REGISTERED",
    "PANE_NOT_FOUND",
    "AGENT_NOT_FOUND",
    "ROUTE_NOT_FOUND",
    "QUEUE_MESSAGE_NOT_FOUND",
    "SCAN_TIMEOUT",
    "SCAN_NOT_FOUND",
    "DAEMON_UNAVAILABLE",
    "SOCKET_MISSING",
    "SOCKET_PERMISSION_DENIED",
    "DOCKER_UNAVAILABLE",
    "TMUX_UNAVAILABLE",
    "CONTAINER_INACTIVE",
    "LOG_ATTACH_BLOCKED",
    "ROUTING_DISABLED",
    "PERMISSION_DENIED",
    "HOST_ONLY",
    "PAYLOAD_TOO_LARGE",
    "INTERNAL_ERROR",
    "ERROR_CODES",
    "CODE_REGEX",
    "DETAILS_REQUIRED_KEYS",
    "ContractViolation",
    "validate_details",
]
