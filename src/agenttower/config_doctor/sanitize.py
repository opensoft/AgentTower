"""Single-source-of-truth sanitization helper for FEAT-005.

Implements R-008's untrusted-string bounding policy: NUL strip, C0 control-byte
strip, ``\\t``/``\\n`` collapse to single space, character-aware truncation, and
an explicit ``…`` (U+2026) marker when truncation occurred. Mirrors FEAT-004
R-009 verbatim.
"""

from __future__ import annotations

ENV_VALUE_CAP = 4096
FILE_CONTENT_CAP = 4096
DETAILS_CAP = 2048
ACTIONABLE_CAP = 2048

_TRUNCATION_MARKER = "…"

_C0_CONTROLS_TO_DROP = frozenset(
    chr(c) for c in range(0x00, 0x20) if c not in (0x09, 0x0A)
) | frozenset({chr(0x7F)})


def sanitize_text(value: str, max_length: int) -> tuple[str, bool]:
    """Sanitize and bound an untrusted string.

    Returns ``(sanitized, truncated)``. The sanitized string contains:

    * no NUL bytes (``\\x00``)
    * no C0 control bytes other than the converted ``\\t`` / ``\\n``
    * no literal ``\\t`` / ``\\n`` — both become single ASCII spaces so the
      doctor's TSV row format stays one row per check
    * at most ``max_length`` *characters* (Python ``str`` slicing is
      character-aware, so multi-byte UTF-8 never splits)
    * a trailing ``…`` (U+2026 — single Unicode character, not three ASCII
      dots) iff truncation occurred

    The ``truncated`` flag is ``True`` when at least one character was dropped
    by the length cap; pure NUL/C0 stripping does not count as truncation.
    """

    if max_length < 1:
        raise ValueError("max_length must be >= 1")

    cleaned_chars: list[str] = []
    for ch in value:
        if ch == "\x00":
            continue
        if ch in ("\t", "\n"):
            cleaned_chars.append(" ")
            continue
        if ch in _C0_CONTROLS_TO_DROP:
            continue
        cleaned_chars.append(ch)
    cleaned = "".join(cleaned_chars)

    if len(cleaned) <= max_length:
        return cleaned, False

    head = cleaned[: max_length - 1]
    return head + _TRUNCATION_MARKER, True


__all__ = [
    "ENV_VALUE_CAP",
    "FILE_CONTENT_CAP",
    "DETAILS_CAP",
    "ACTIONABLE_CAP",
    "sanitize_text",
]
