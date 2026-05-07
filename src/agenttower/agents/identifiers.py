"""Agent identifier generation and shape validation (FEAT-006 FR-001).

``agent_id`` shape is ``agt_<12-character-lowercase-hex>`` (16 chars total,
96 bits of entropy). Strict case-sensitive: only ``[0-9a-f]`` is accepted
in the hex portion (Clarifications session 2026-05-07-continued).
"""

from __future__ import annotations

import re
import secrets
from typing import Final

from .errors import RegistrationError


AGENT_ID_RE: Final[re.Pattern[str]] = re.compile(r"^agt_[0-9a-f]{12}$")


def generate_agent_id() -> str:
    """Return a fresh ``agt_<12-hex>`` identifier (research R-001).

    96 bits of entropy is overwhelmingly conservative at MVP scale; PK
    collisions are retried by the service layer under the per-pane
    registration mutex (FR-001).
    """
    return "agt_" + secrets.token_hex(6)


def validate_agent_id_shape(value: str) -> str:
    """Return *value* unchanged if it matches :data:`AGENT_ID_RE`, else raise.

    Mixed-case inputs (``AGT_abc...``, ``agt_ABC...``) are rejected with
    closed-set code ``value_out_of_set`` per Clarifications session
    2026-05-07-continued Q2 — never normalized.
    """
    if not isinstance(value, str) or not AGENT_ID_RE.match(value):
        raise RegistrationError(
            "value_out_of_set",
            f"agent_id must match agt_<12-hex-lowercase>; got {value!r}",
        )
    return value
