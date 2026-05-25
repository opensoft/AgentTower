"""FEAT-013 closed-set error codes (T005).

11 new codes added on top of FEAT-011's 27-entry registry (38 total).
See ``specs/013-managed-session-lifecycle/contracts/error-codes.md`` for
each entry's authoritative ``details`` schema.

Codes follow the FEAT-011 convention (lowercase snake_case, matches the
``^[a-z][a-z0-9_]*$`` shape from FR-034). The ``DETAILS_SCHEMAS`` mapping
names the required ``details`` keys per code; callers building error
envelopes assemble the actual values from runtime context.
"""

from __future__ import annotations

from typing import Final


# ─── Closed-set error codes (FEAT-013 additions) ────────────────────────

MANAGED_SESSION_NAME_CONFLICT: Final[str] = "managed_session_name_conflict"
MANAGED_TEMPLATE_NOT_FOUND: Final[str] = "managed_template_not_found"
MANAGED_LAUNCH_COMMAND_NOT_FOUND: Final[str] = "managed_launch_command_not_found"
MANAGED_LAYOUT_NOT_FOUND: Final[str] = "managed_layout_not_found"
MANAGED_PANE_NOT_FOUND: Final[str] = "managed_pane_not_found"
MANAGED_PANE_PROTECTED_ADOPTED: Final[str] = "managed_pane_protected_adopted"
MANAGED_PANE_ILLEGAL_TRANSITION: Final[str] = "managed_pane_illegal_transition"
MANAGED_PANE_ILLEGAL_RECREATE_SOURCE: Final[str] = "managed_pane_illegal_recreate_source"
MANAGED_PANE_RECREATE_CHAIN_TOO_DEEP: Final[str] = "managed_pane_recreate_chain_too_deep"
MANAGED_LAYOUT_CAPACITY_EXCEEDED: Final[str] = "managed_layout_capacity_exceeded"
MANAGED_PANE_CONCURRENT_RECREATE: Final[str] = "managed_pane_concurrent_recreate"


# All FEAT-013 codes as a frozen set for closed-set membership tests
# (contract tests, dispatcher validation, etc.).
ALL_CODES: Final[frozenset[str]] = frozenset(
    {
        MANAGED_SESSION_NAME_CONFLICT,
        MANAGED_TEMPLATE_NOT_FOUND,
        MANAGED_LAUNCH_COMMAND_NOT_FOUND,
        MANAGED_LAYOUT_NOT_FOUND,
        MANAGED_PANE_NOT_FOUND,
        MANAGED_PANE_PROTECTED_ADOPTED,
        MANAGED_PANE_ILLEGAL_TRANSITION,
        MANAGED_PANE_ILLEGAL_RECREATE_SOURCE,
        MANAGED_PANE_RECREATE_CHAIN_TOO_DEEP,
        MANAGED_LAYOUT_CAPACITY_EXCEEDED,
        MANAGED_PANE_CONCURRENT_RECREATE,
    }
)


# ─── Per-code ``details`` schemas (required keys; FEAT-011 FR-034a) ─────
#
# Each value is a tuple of required keys the error envelope's ``details``
# object MUST contain. Optional keys (``known_templates`` etc.) are not
# listed here but ARE part of the published contract — see
# contracts/error-codes.md for the full schemas.

DETAILS_SCHEMAS: Final[dict[str, tuple[str, ...]]] = {
    MANAGED_SESSION_NAME_CONFLICT: ("container_id", "tmux_session_name"),
    MANAGED_TEMPLATE_NOT_FOUND: ("template_name",),
    MANAGED_LAUNCH_COMMAND_NOT_FOUND: ("profile_name",),
    MANAGED_LAYOUT_NOT_FOUND: ("layout_id",),
    MANAGED_PANE_NOT_FOUND: ("pane_id",),
    MANAGED_PANE_PROTECTED_ADOPTED: ("agent_id", "is_adopted"),
    MANAGED_PANE_ILLEGAL_TRANSITION: ("pane_id", "current_state", "requested_action"),
    MANAGED_PANE_ILLEGAL_RECREATE_SOURCE: ("predecessor_pane_id", "current_state"),
    MANAGED_PANE_RECREATE_CHAIN_TOO_DEEP: (
        "predecessor_pane_id",
        "predecessor_chain_depth",
        "limit",
    ),
    MANAGED_LAYOUT_CAPACITY_EXCEEDED: ("current_count", "limit"),
    MANAGED_PANE_CONCURRENT_RECREATE: (
        "predecessor_pane_id",
        "in_flight_successor_pane_id",
    ),
}


class ManagedSessionsError(Exception):
    """Base exception for FEAT-013 closed-set errors.

    Wraps a closed-set ``code`` (one of ``ALL_CODES``) plus a ``details``
    dict that MUST satisfy ``DETAILS_SCHEMAS[code]``. Service entry
    points raise subclasses of this; handlers translate it into the
    FEAT-002 / FEAT-011 envelope.
    """

    code: str

    def __init__(self, code: str, details: dict[str, object], message: str = "") -> None:
        if code not in ALL_CODES:
            raise ValueError(f"unknown FEAT-013 error code: {code!r}")
        required = DETAILS_SCHEMAS.get(code, ())
        missing = [k for k in required if k not in details]
        if missing:
            raise ValueError(
                f"FEAT-013 error {code!r} missing required details keys: {missing!r}"
            )
        self.code = code
        self.details = details
        super().__init__(message or code)
