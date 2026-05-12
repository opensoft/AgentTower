"""FEAT-009 redacted-excerpt rendering pipeline (FR-047b).

Applied uniformly to every operator-visible surface that exposes the
queue body:

* ``agenttower queue`` human listing (``excerpt`` column)
* ``agenttower queue --json`` (``excerpt`` field)
* ``send-input --json`` (``excerpt`` field)
* ``events.jsonl`` audit (``excerpt`` field for ``queue_message_*`` rows)
* The FEAT-008 ``events.excerpt`` SQLite column for dual-written audit rows

The persisted ``message_queue.envelope_body`` BLOB, the tmux paste
buffer, and the bytes delivered to the target pane MUST NEVER be
redacted (FR-047a / Clarifications Q1 of 2026-05-11).

Pipeline (FR-047b):

1. UTF-8 decode the body bytes.
2. Apply the FEAT-007 redactor (default
   :func:`agenttower.logs.redaction.redact_one_line`).
3. Collapse every run of whitespace (``\\s+``) to a single ASCII space.
4. Truncate to the configured cap (default 240 chars).
5. Append the U+2026 ellipsis character ``…`` if and only if step (4)
   actually discarded characters.

On any exception raised by step (2) (catastrophic regex backtracking,
unhandled UTF-8 edge in the redactor, etc.), the pipeline substitutes
the fixed literal placeholder defined by
:data:`REDACTOR_FAILED_PLACEHOLDER` and skips steps (3)–(5). The raw
body MUST NEVER appear as a fallback (Group-A walk Q3).
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Final

from agenttower.logs.redaction import redact_one_line as _default_redactor


__all__ = [
    "DEFAULT_EXCERPT_CAP",
    "ELLIPSIS",
    "REDACTOR_FAILED_PLACEHOLDER",
    "render_excerpt",
]


DEFAULT_EXCERPT_CAP: Final[int] = 240
"""Maximum excerpt length BEFORE the ellipsis marker (FR-011 / FR-047b /
Assumptions §"Excerpt size in queue listings and audit")."""


ELLIPSIS: Final[str] = "…"
"""U+2026 truncation marker. Appended iff truncation actually occurred."""


REDACTOR_FAILED_PLACEHOLDER: Final[str] = "[excerpt unavailable: redactor failed]"
"""Fixed-literal fallback substituted when the redactor raises (Group-A
walk Q3). The raw body MUST NEVER appear as a fallback."""


_WHITESPACE_RUN = re.compile(r"\s+")


_log = logging.getLogger(__name__)


# Public callable signature for the redactor. The default
# :func:`agenttower.logs.redaction.redact_one_line` takes one ``str``
# (a single line) and returns one ``str``. FEAT-009 wraps it to accept
# multi-line input (the body may contain ``\n``).
Redactor = Callable[[str], str]


def _redact_multiline(redactor: Redactor, text: str) -> str:
    """Apply ``redactor`` line-by-line. FEAT-007's ``redact_one_line``
    is documented as single-line-only; bodies may contain ``\\n``. We
    split on ``\\n``, redact each line, and re-join.
    """
    parts = text.split("\n")
    return "\n".join(redactor(part) for part in parts)


def render_excerpt(
    body_bytes: bytes,
    redactor: Redactor | None = None,
    *,
    cap: int = DEFAULT_EXCERPT_CAP,
) -> str:
    """Render the redacted, whitespace-collapsed, truncated excerpt.

    See module docstring for the four-step pipeline. The result is
    always single-line and at most ``cap + 1`` characters long (the
    extra char is the U+2026 ellipsis when truncation occurred).

    Args:
        body_bytes: Raw envelope body bytes (the SQLite ``envelope_body``
            BLOB content). Decoded as UTF-8.
        redactor: Override the FEAT-007 redactor (test seam). Defaults
            to :func:`agenttower.logs.redaction.redact_one_line`.
        cap: Maximum length before the ellipsis. Defaults to
            :data:`DEFAULT_EXCERPT_CAP`.

    Returns:
        The single-line redacted excerpt.
    """
    if redactor is None:
        redactor = _default_redactor

    try:
        raw_str = body_bytes.decode("utf-8")
        redacted = _redact_multiline(redactor, raw_str)
    except Exception as exc:
        # Group-A walk Q3: any exception from the redactor (or the
        # initial UTF-8 decode, which FR-003 should have ruled out at
        # submit time but we defend in depth) → fixed placeholder.
        # The raw body MUST NEVER leak as a fallback.
        _log.warning(
            "render_excerpt: redactor raised %s; substituting placeholder",
            type(exc).__name__,
        )
        return REDACTOR_FAILED_PLACEHOLDER

    # Step 3: collapse every run of whitespace (incl. \n, \t, \r,
    # ASCII space, and Unicode whitespace via \s) to a single space.
    one_line = _WHITESPACE_RUN.sub(" ", redacted)

    # Step 4 + 5: truncate + maybe append ellipsis.
    if len(one_line) <= cap:
        return one_line
    return one_line[:cap] + ELLIPSIS
