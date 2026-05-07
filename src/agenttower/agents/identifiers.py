"""Agent identifier generation and shape validation (FEAT-006 FR-001).

``agent_id`` shape is ``agt_<12-character-lowercase-hex>`` (16 chars total,
48 bits of entropy — 12 hex chars × 4 bits = 48). Strict case-sensitive:
only ``[0-9a-f]`` is accepted in the hex portion (Clarifications session
2026-05-07-continued).

Birthday-bound collision probability stays vanishingly small at MVP
scale: 2^24 ≈ 16M unique agents before the first expected collision.
The PK collision retry budget in the service layer
(``_AGENT_ID_RETRY_LIMIT=5``) covers the impossible case so a real
collision still surfaces as ``internal_error`` rather than crashing
the daemon. If horizontal scale ever pushes past ~10⁵ concurrent
agents, bump ``token_hex(6)`` to ``token_hex(12)`` and update the
regex to ``[0-9a-f]{24}`` (a wire-format break — coordinate with
existing CLI consumers).
"""

from __future__ import annotations

import re
import secrets
from typing import Final

from .errors import RegistrationError


AGENT_ID_RE: Final[re.Pattern[str]] = re.compile(r"^agt_[0-9a-f]{12}$")


def generate_agent_id() -> str:
    """Return a fresh ``agt_<12-hex>`` identifier (research R-001).

    ``secrets.token_hex(6)`` returns 6 random bytes = 12 hex chars =
    48 bits of entropy. Adequate at MVP scale (birthday-bound first
    expected collision at ~16M unique agents). PK collisions are
    retried by the service layer under the per-pane registration
    mutex (FR-001).
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
