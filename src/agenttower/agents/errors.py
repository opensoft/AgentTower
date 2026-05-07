"""Typed exception type for agent-domain validation/service failures.

Each instance carries the closed-set wire code so the service layer can
map straight to the FEAT-002 error envelope (``socket_api/errors.py``)
without string parsing.
"""

from __future__ import annotations


class RegistrationError(Exception):
    """Carries a closed-set wire code + actionable message.

    The ``code`` MUST belong to the FEAT-002 / FEAT-003 / FEAT-004 /
    FEAT-006 closed set declared in :mod:`agenttower.socket_api.errors`.
    The service layer enforces this when mapping to the wire envelope.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
