"""Error code constants and JSON envelope helpers for the local control API.

Per FEAT-002 research R-014, FEAT-002 ships a closed five-token error code set.
Adding a new code is a spec amendment.
"""

from __future__ import annotations

from typing import Any, Final

# Closed code set (FEAT-002).
BAD_JSON: Final[str] = "bad_json"
BAD_REQUEST: Final[str] = "bad_request"
UNKNOWN_METHOD: Final[str] = "unknown_method"
REQUEST_TOO_LARGE: Final[str] = "request_too_large"
INTERNAL_ERROR: Final[str] = "internal_error"

CLOSED_CODE_SET: Final[frozenset[str]] = frozenset(
    {BAD_JSON, BAD_REQUEST, UNKNOWN_METHOD, REQUEST_TOO_LARGE, INTERNAL_ERROR}
)


def make_ok(result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the canonical success envelope ``{"ok": true, "result": ...}``."""
    return {"ok": True, "result": {} if result is None else result}


def make_error(code: str, message: str) -> dict[str, Any]:
    """Return the canonical error envelope.

    The ``code`` MUST belong to :data:`CLOSED_CODE_SET`. This is enforced at
    runtime so a typo in a caller cannot leak an unknown code onto the wire.
    """
    if code not in CLOSED_CODE_SET:
        raise ValueError(f"unknown error code: {code!r}")
    return {"ok": False, "error": {"code": code, "message": message}}
