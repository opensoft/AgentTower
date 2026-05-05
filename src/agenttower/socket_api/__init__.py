"""AgentTower local control socket API (FEAT-002)."""

from __future__ import annotations

from .errors import (
    BAD_JSON,
    BAD_REQUEST,
    CLOSED_CODE_SET,
    INTERNAL_ERROR,
    REQUEST_TOO_LARGE,
    UNKNOWN_METHOD,
    make_error,
    make_ok,
)

__all__ = [
    "BAD_JSON",
    "BAD_REQUEST",
    "CLOSED_CODE_SET",
    "INTERNAL_ERROR",
    "REQUEST_TOO_LARGE",
    "UNKNOWN_METHOD",
    "make_error",
    "make_ok",
]
