"""FEAT-010 closed-set vocabulary: CLI codes, skip reasons, sub-reasons,
internal-error codes, and the RouteError exception hierarchy.

Re-exports the eight CLI string codes from
:mod:`agenttower.socket_api.errors` (the canonical declaration site),
then defines:

* :data:`SKIP_REASONS` — the ten ``route_skipped(reason=...)`` values
  per FR-037 / contracts/error-codes.md §2.
* :data:`TEMPLATE_SUB_REASONS` — the five sub-reasons that appear only
  when ``reason='template_render_error'`` per contracts/error-codes.md §3.
* :data:`INTERNAL_ERROR_CODES` — internal-error vocabulary per
  contracts/error-codes.md §4 (NOT CLI codes; surfaced via the
  ``routing_worker_degraded`` status field per FR-051).
* :class:`RouteError` and subclasses — typed exceptions raised by the
  routes service / DAO / worker, each mapping to one CLI code.

These constants are part of the public CLI + audit contract (FR-049
revised + research §R13); they MUST NOT be renamed or removed except
via a SemVer major bump of the daemon.
"""

from __future__ import annotations

from typing import Final

# ──────────────────────────────────────────────────────────────────────
# Re-export the eight CLI-surface codes from the canonical site so
# FEAT-010 modules don't have to import socket_api/errors.py directly.
# Listed alphabetically; matches FR-049 / contracts/error-codes.md §1.
# ──────────────────────────────────────────────────────────────────────

from agenttower.socket_api.errors import (
    QUEUE_ORIGIN_INVALID,
    ROUTE_CREATION_FAILED,
    ROUTE_EVENT_TYPE_INVALID,
    ROUTE_ID_NOT_FOUND,
    ROUTE_MASTER_RULE_INVALID,
    ROUTE_SOURCE_SCOPE_INVALID,
    ROUTE_TARGET_RULE_INVALID,
    ROUTE_TEMPLATE_INVALID,
)

CLI_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        QUEUE_ORIGIN_INVALID,
        ROUTE_CREATION_FAILED,
        ROUTE_EVENT_TYPE_INVALID,
        ROUTE_ID_NOT_FOUND,
        ROUTE_MASTER_RULE_INVALID,
        ROUTE_SOURCE_SCOPE_INVALID,
        ROUTE_TARGET_RULE_INVALID,
        ROUTE_TEMPLATE_INVALID,
    }
)
"""The eight FEAT-010 CLI / socket error codes."""


# ──────────────────────────────────────────────────────────────────────
# Skip-reason vocabulary (FR-037 + contracts/error-codes.md §2)
# These appear in ``route_skipped(reason=...)`` JSONL audit entries
# ONLY — NOT as CLI exit codes.
# ──────────────────────────────────────────────────────────────────────

# §2a — arbitration failures
NO_ELIGIBLE_MASTER: Final[str] = "no_eligible_master"
MASTER_INACTIVE: Final[str] = "master_inactive"
MASTER_NOT_FOUND: Final[str] = "master_not_found"

# §2b — target-resolution failures (also raised by FEAT-009 internals)
TARGET_NOT_FOUND: Final[str] = "target_not_found"
TARGET_ROLE_NOT_PERMITTED: Final[str] = "target_role_not_permitted"
TARGET_NOT_ACTIVE: Final[str] = "target_not_active"
TARGET_PANE_MISSING: Final[str] = "target_pane_missing"
TARGET_CONTAINER_INACTIVE: Final[str] = "target_container_inactive"
NO_ELIGIBLE_TARGET: Final[str] = "no_eligible_target"

# §2c — template render failures
TEMPLATE_RENDER_ERROR: Final[str] = "template_render_error"

SKIP_REASONS: Final[frozenset[str]] = frozenset(
    {
        NO_ELIGIBLE_MASTER,
        MASTER_INACTIVE,
        MASTER_NOT_FOUND,
        TARGET_NOT_FOUND,
        TARGET_ROLE_NOT_PERMITTED,
        TARGET_NOT_ACTIVE,
        TARGET_PANE_MISSING,
        TARGET_CONTAINER_INACTIVE,
        NO_ELIGIBLE_TARGET,
        TEMPLATE_RENDER_ERROR,
    }
)
"""The ten closed-set ``route_skipped(reason=...)`` values (FR-037)."""


# ──────────────────────────────────────────────────────────────────────
# Template sub-reasons (contracts/error-codes.md §3)
# Appear only when reason='template_render_error'; sub_reason is null
# for every other skip reason.
# ──────────────────────────────────────────────────────────────────────

MISSING_FIELD: Final[str] = "missing_field"
BODY_EMPTY: Final[str] = "body_empty"
BODY_INVALID_CHARS: Final[str] = "body_invalid_chars"
BODY_INVALID_ENCODING: Final[str] = "body_invalid_encoding"
BODY_TOO_LARGE: Final[str] = "body_too_large"
REDACTOR_FAILURE: Final[str] = "redactor_failure"

TEMPLATE_SUB_REASONS: Final[frozenset[str]] = frozenset(
    {
        MISSING_FIELD,
        BODY_EMPTY,
        BODY_INVALID_CHARS,
        BODY_INVALID_ENCODING,
        BODY_TOO_LARGE,
        REDACTOR_FAILURE,
    }
)
"""The six closed-set template render sub-reasons.

Includes ``redactor_failure`` (spec Assumptions: redactor exceptions
surface as a skip with this sub-reason rather than substituting a
placeholder).
"""


# ──────────────────────────────────────────────────────────────────────
# Internal-error vocabulary (contracts/error-codes.md §4 + FR-051)
# NOT CLI codes; surfaced via the routing_worker_degraded status field
# and the daemon log only.
# ──────────────────────────────────────────────────────────────────────

ROUTING_SQLITE_LOCKED: Final[str] = "routing_sqlite_locked"
ROUTING_DUPLICATE_INSERT: Final[str] = "routing_duplicate_insert"
ROUTING_INTERNAL_RENDER_FAILURE: Final[str] = "routing_internal_render_failure"
ROUTING_AUDIT_BUFFER_OVERFLOW: Final[str] = "routing_audit_buffer_overflow"

INTERNAL_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        ROUTING_SQLITE_LOCKED,
        ROUTING_DUPLICATE_INSERT,
        ROUTING_INTERNAL_RENDER_FAILURE,
        ROUTING_AUDIT_BUFFER_OVERFLOW,
    }
)
"""The four internal-error codes that drive ``routing_worker_degraded``."""


# ──────────────────────────────────────────────────────────────────────
# Exception hierarchy
# ──────────────────────────────────────────────────────────────────────


class RouteError(Exception):
    """Base for all FEAT-010 typed errors raised by routes service / DAO.

    Each subclass binds to one closed-set CLI code. The socket dispatcher
    maps the exception class → ``code`` field of the FEAT-002 error
    envelope without needing per-method translation tables.
    """

    code: str = ""  # subclasses override

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RouteIdNotFound(RouteError):
    code = ROUTE_ID_NOT_FOUND


class RouteEventTypeInvalid(RouteError):
    code = ROUTE_EVENT_TYPE_INVALID


class RouteTargetRuleInvalid(RouteError):
    code = ROUTE_TARGET_RULE_INVALID


class RouteMasterRuleInvalid(RouteError):
    code = ROUTE_MASTER_RULE_INVALID


class RouteSourceScopeInvalid(RouteError):
    code = ROUTE_SOURCE_SCOPE_INVALID


class RouteTemplateInvalid(RouteError):
    code = ROUTE_TEMPLATE_INVALID


class RouteCreationFailed(RouteError):
    code = ROUTE_CREATION_FAILED


class QueueOriginInvalid(RouteError):
    code = QUEUE_ORIGIN_INVALID


# ──────────────────────────────────────────────────────────────────────
# Worker-internal exceptions (NOT CLI-surfaced)
# ──────────────────────────────────────────────────────────────────────


class RoutingTransientError(Exception):
    """Transient internal error in the routing worker. Cursor is NOT
    advanced; the event is re-evaluated on the next cycle. Carries
    one of the :data:`INTERNAL_ERROR_CODES` constants in
    ``self.code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        if code not in INTERNAL_ERROR_CODES:
            raise ValueError(f"unknown internal error code: {code!r}")
        self.code = code
        self.message = message


class RoutingDuplicateInsert(RoutingTransientError):
    """The partial UNIQUE index on ``message_queue(route_id, event_id)``
    rejected a second insert for the same pair. Indicates a logic bug
    in the worker (the primary cursor-advance-with-enqueue atomicity
    should make this impossible)."""

    def __init__(self, message: str) -> None:
        super().__init__(ROUTING_DUPLICATE_INSERT, message)


class RouteTemplateRenderError(Exception):
    """Template render-time failure. Maps to
    ``route_skipped(reason='template_render_error', sub_reason=<this>)``.

    ``sub_reason`` MUST be one of :data:`TEMPLATE_SUB_REASONS`.
    """

    def __init__(self, sub_reason: str, message: str) -> None:
        super().__init__(message)
        if sub_reason not in TEMPLATE_SUB_REASONS:
            raise ValueError(f"unknown template sub-reason: {sub_reason!r}")
        self.sub_reason = sub_reason
        self.message = message
