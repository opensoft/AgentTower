"""FEAT-007 attachment identifier generation (R-001 / FR-035).

``attachment_id`` shape is ``lat_<12-hex-lowercase>`` mirroring FEAT-006's
``agt_<12-hex>`` style. 48 bits of entropy from ``secrets.token_hex(6)``;
collision retry budget is bounded at ``MAX_ATTACHMENT_ID_RETRIES = 5``
under the per-(agent_id, log_path) insert mutex.
"""

from __future__ import annotations

import re
import secrets
from typing import Final

ATTACHMENT_ID_RE: Final[re.Pattern[str]] = re.compile(r"^lat_[0-9a-f]{12}$")
"""Strict shape gate; mixed-case rejected with ``value_out_of_set``."""

MAX_ATTACHMENT_ID_RETRIES: Final[int] = 5
"""Bounded retry budget on PK collision (R-001)."""


def generate_attachment_id() -> str:
    """Return a fresh ``lat_<12-hex-lowercase>`` identifier."""
    return "lat_" + secrets.token_hex(6)


def is_valid_attachment_id(value: object) -> bool:
    """Return True iff ``value`` is a string matching :data:`ATTACHMENT_ID_RE`."""
    return isinstance(value, str) and ATTACHMENT_ID_RE.match(value) is not None
