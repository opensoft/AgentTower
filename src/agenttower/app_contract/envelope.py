"""FEAT-011 response envelope builders.

Every ``app.*`` response uses one of two shapes (FR-033):

    Success: {"ok": True,  "app_contract_version": "1.0", "result": {...}}
    Failure: {"ok": False, "app_contract_version": "1.0",
              "error":   {"code": "<closed_set>",
                          "message": "<prose>",
                          "details": {...}}}

``app_contract_version`` is always present on both shapes (FR-033).
``error.details`` is always a JSON object, even when empty (FR-033, FR-034a).
"""

from __future__ import annotations

import sys
from typing import Any

from . import errors as errors_mod
from .versioning import APP_CONTRACT_VERSION


def success(result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a success envelope for an ``app.*`` method.

    ``result`` may be None for handshake-like methods whose success
    response carries no payload beyond the envelope marker, but we
    return ``result: {}`` rather than omit the field to keep the shape
    uniform for client decoders.
    """
    return {
        "ok": True,
        "app_contract_version": APP_CONTRACT_VERSION,
        "result": result if result is not None else {},
    }


def failure(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a failure envelope for an ``app.*`` method.

    Validates the code against the FR-034 closed set and the per-code
    ``details`` registry (FR-034a). If a handler passes an unknown code
    or omits required ``details`` keys, raises ``ContractViolation`` —
    callers in the dispatcher catch this and map to ``internal_error``
    so the wire still sees a structurally-valid envelope.
    """
    if details is None:
        details = {}
    errors_mod.validate_details(code, details)
    return {
        "ok": False,
        "app_contract_version": APP_CONTRACT_VERSION,
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
    }


def internal_error(message: str = "internal daemon error") -> dict[str, Any]:
    """Build an ``internal_error`` envelope. Used as the safety-net code
    when a handler raises an unexpected exception or emits a malformed
    failure (caught by the dispatcher). Never carries structured details
    — the closed set ``internal_error`` row carries ``details == {}``.
    """
    return failure(errors_mod.INTERNAL_ERROR, message, {})


def internal_error_logged(operation: str, detail: object) -> dict[str, Any]:
    """Log full failure detail to stderr; return a generic ``internal_error``.

    The wire ``message`` names only ``operation`` — never the exception
    string or upstream service message, which can embed absolute host
    paths, SQL text, or fragments of the client's request payload. This
    mirrors the dispatcher ``_wrap_handler`` redaction policy (FR-033):
    an operator correlates the wire error to the stderr line by the
    ``operation`` label. ``detail`` may be an exception (formatted as
    ``Type: message``) or any stringifiable value.
    """
    if isinstance(detail, BaseException):
        detail_text = f"{type(detail).__name__}: {detail}"
    else:
        detail_text = str(detail)
    print(
        f"FEAT-011: {operation} failed: {detail_text}",
        file=sys.stderr,
        flush=True,
    )
    return internal_error(f"{operation} failed; see daemon stderr")


__all__ = [
    "success",
    "failure",
    "internal_error",
    "internal_error_logged",
]
