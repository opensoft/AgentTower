"""FR-027 / FR-028 / FR-029 / FR-030 / FR-049 / FR-064 redaction utility.

Pre-compiled regex patterns with the ``re.ASCII`` flag (FR-049) so
``\\b`` / ``\\w`` / ``\\W`` are bytewise-defined and locale-independent.
Per-line application (FR-029); multi-line tokens are NOT redacted.
Pure function: same input → same output across calls (FR-027 / SC-004).
"""

from __future__ import annotations

import re
from typing import Callable, Final

# ---------------------------------------------------------------------------
# Unanchored token patterns (FR-028) — match anywhere within a line with
# \b word-boundary protection on both sides where the boundary is meaningful.
# ---------------------------------------------------------------------------

_UNANCHORED_PATTERNS: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b", re.ASCII),
        "<redacted:openai-key>",
    ),
    (
        re.compile(r"\bgh[ps]_[A-Za-z0-9]{20,}\b", re.ASCII),
        "<redacted:github-token>",
    ),
    (
        re.compile(r"\bAKIA[A-Z0-9]{16}\b", re.ASCII),
        "<redacted:aws-access-key>",
    ),
    (
        re.compile(r"\bBearer ([A-Za-z0-9_\-\.=]{16,})", re.ASCII),
        "Bearer <redacted:bearer>",
    ),
)

# ---------------------------------------------------------------------------
# Anchored line patterns (FR-028) — match ONLY when the entire line conforms.
# JWT length ≥ 32 INCLUDING the two `.` separators (Clarifications Q5 / FR-028
# explicit amendment).
# ---------------------------------------------------------------------------

_JWT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$", re.ASCII
)
_ENV_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^([A-Z_][A-Z0-9_]*(API_?KEY|TOKEN|SECRET|PASSWORD|AUTH))=(.+)$", re.ASCII
)


def _redact_jwt(line: str) -> str:
    m = _JWT_PATTERN.fullmatch(line)
    if m is None:
        return line
    if len(m.group(0)) < 32:
        return line
    return "<redacted:jwt>"


def _redact_env(line: str) -> str:
    m = _ENV_PATTERN.fullmatch(line)
    if m is None:
        return line
    return f"{m.group(1)}=<redacted:env-secret>"


_ANCHORED_REDACTORS: Final[tuple[Callable[[str], str], ...]] = (
    _redact_jwt,
    _redact_env,
)


def redact_lines(text: str) -> str:
    """Redact ``text`` per FR-028 patterns, returning the redacted result.

    Pure function: same input → same output (FR-027). Splits on ``\\n`` (NOT
    ``splitlines`` — preserves ``\\r`` byte-fidelity per Research R-012).
    """
    parts = text.split("\n")
    redacted: list[str] = []
    for line in parts:
        redacted.append(_redact_one_line(line))
    return "\n".join(redacted)


def redact_one_line(line: str) -> str:
    """Redact a single line (no embedded ``\\n``) per FR-028.

    Public entry point for callers that already split.
    """
    return _redact_one_line(line)


def _redact_one_line(line: str) -> str:
    """Apply unanchored patterns first, then anchored patterns (FR-028 ordering)."""
    out = line
    for pattern, replacement in _UNANCHORED_PATTERNS:
        out = pattern.sub(replacement, out)
    for redactor in _ANCHORED_REDACTORS:
        out = redactor(out)
    return out
