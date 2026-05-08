"""Closed-set validators and free-text bounds for FEAT-006.

All validators raise :class:`RegistrationError` carrying the FEAT-006
closed-set code so the service layer maps straight to the wire envelope.
Case-sensitivity is strict per Clarifications session
2026-05-07-continued Q2 — mixed-case inputs are rejected, not normalized.
"""

from __future__ import annotations

import re
from typing import Final

from ..tmux.parsers import sanitize_text
from .errors import RegistrationError
from .identifiers import AGENT_ID_RE


VALID_ROLES: Final[tuple[str, ...]] = (
    "master",
    "slave",
    "swarm",
    "test-runner",
    "shell",
    "unknown",
)
VALID_CAPABILITIES: Final[tuple[str, ...]] = (
    "claude",
    "codex",
    "gemini",
    "opencode",
    "shell",
    "test-runner",
    "unknown",
)

# Per-field bounds (FR-033 / FR-034).
LABEL_MAX = 64
PROJECT_PATH_MAX = 4096

# FR-026: filter accepts the 12-char short-id form OR the full 64-char id.
# Lengths in between are not part of the documented surface — accepting them
# here would let arbitrary 13..63-char prefixes silently match via the
# ``substr(...)`` fallback the daemon uses for short ids.
_CONTAINER_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{12}([0-9a-f]{52})?$")


def validate_role(value: object) -> str:
    """Return *value* if it is in :data:`VALID_ROLES` (case-sensitive), else raise.

    Mixed-case (``Slave``, ``MASTER``, ``Test-Runner``) is rejected with
    ``value_out_of_set`` and NOT normalized (FR-004 / Clarifications Q2).
    """
    if not isinstance(value, str) or value not in VALID_ROLES:
        raise RegistrationError(
            "value_out_of_set",
            f"role must be one of {list(VALID_ROLES)}; got {value!r}",
        )
    return value


def validate_capability(value: object) -> str:
    """Return *value* if it is in :data:`VALID_CAPABILITIES`, else raise.

    Case-sensitive per FR-005 / Clarifications Q2. Mixed-case is rejected.
    """
    if not isinstance(value, str) or value not in VALID_CAPABILITIES:
        raise RegistrationError(
            "value_out_of_set",
            f"capability must be one of {list(VALID_CAPABILITIES)}; got {value!r}",
        )
    return value


def validate_label(value: object) -> str:
    """Return *value* sanitized (NUL-strip, C0-strip) if ≤ 64 chars, else raise.

    Oversized values raise ``field_too_long`` per FR-033 — never silently
    truncated. Inherits :func:`agenttower.tmux.parsers.sanitize_text` byte
    classes so the rule matches FEAT-004 sanitization.
    """
    if not isinstance(value, str):
        raise RegistrationError(
            "value_out_of_set",
            f"label must be a string; got {type(value).__name__}",
        )
    cleaned, truncated = sanitize_text(value, LABEL_MAX)
    if truncated:
        raise RegistrationError(
            "field_too_long",
            f"label exceeds maximum length {LABEL_MAX}",
        )
    return cleaned


def validate_project_path(value: object) -> str:
    """Validate *value* against FR-034 + FR-033 and return a sanitized copy.

    - non-empty, absolute path (starts with ``/``)
    - no NUL byte
    - no ``..`` segment after :func:`os.path.normpath`
    - ≤ 4096 chars (FR-033)

    Existence on the host filesystem is NOT checked (the path is observed
    inside the container's mount namespace).
    """
    if not isinstance(value, str):
        raise RegistrationError(
            "project_path_invalid",
            f"project_path must be a string; got {type(value).__name__}",
        )
    if "\x00" in value:
        raise RegistrationError(
            "project_path_invalid",
            "project_path must not contain NUL bytes",
        )
    value = "".join(ch for ch in value if ord(ch) >= 0x20 and ord(ch) != 0x7F)
    if value == "":
        raise RegistrationError(
            "project_path_invalid",
            "project_path must be a non-empty absolute path",
        )
    if not value.startswith("/"):
        raise RegistrationError(
            "project_path_invalid",
            f"project_path must be absolute (start with '/'); got {value!r}",
        )
    # ``..`` segment check on the *supplied* path so social-engineered values
    # like ``/a/../b`` are rejected even though ``os.path.normpath`` would
    # collapse them to ``/b`` (spec edge case line 99 + FR-034).
    if ".." in value.split("/"):
        raise RegistrationError(
            "project_path_invalid",
            f"project_path must not contain '..' segment; got {value!r}",
        )
    if len(value) > PROJECT_PATH_MAX:
        raise RegistrationError(
            "field_too_long",
            f"project_path exceeds maximum length {PROJECT_PATH_MAX}",
        )
    return value


def validate_container_id_filter(value: object) -> str:
    """Validate ``container_id`` filter shape (FR-026); case-sensitive lowercase hex.

    Accepts exactly the 12-char short-id form OR the full 64-char id —
    no in-between lengths.
    """
    if not isinstance(value, str) or not _CONTAINER_ID_RE.match(value):
        raise RegistrationError(
            "value_out_of_set",
            "container_id must be a 12-char short id or a 64-char full id "
            f"(lowercase hex); got {value!r}",
        )
    return value


def validate_parent_agent_id_shape(value: object) -> str:
    """Validate ``parent_agent_id`` against the agent_id shape regex."""
    if not isinstance(value, str) or not AGENT_ID_RE.match(value):
        raise RegistrationError(
            "value_out_of_set",
            f"parent_agent_id must match agt_<12-hex-lowercase>; got {value!r}",
        )
    return value
