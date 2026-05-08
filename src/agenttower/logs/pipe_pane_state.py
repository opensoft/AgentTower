"""FR-011 / FR-054 ``tmux list-panes`` pipe-state inspection.

Parses the FR-011 inspection output and classifies the active pipe target as
either AgentTower-canonical or foreign. The canonical-target match is STRICT
EQUALITY against the daemon-computed canonical container-side path
(FR-054); substring tricks like
``cat >> /tmp/innocent.log; cat >> /canonical/path/...`` MUST be classified
as FOREIGN.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class PaneState:
    """Decoded ``tmux list-panes -F '#{pane_pipe} #{pane_pipe_command}'`` output."""

    pipe_active: bool
    pipe_command: str
    """Verbatim ``pane_pipe_command`` field (sanitized for storage by callers)."""


@dataclass(frozen=True)
class PipeTargetClassification:
    is_canonical: bool
    """True iff the pipe command exactly matches ``cat >> <quoted_canonical>``."""

    foreign_target: str | None
    """Sanitized full prior pipe command for audit; None when ``is_canonical`` is True or pipe inactive."""


def parse_list_panes_output(output: str) -> PaneState:
    """Parse the FR-011 inspection output line into a :class:`PaneState`.

    Output shape: ``"<0|1> <pipe_command>\\n"``. Empty pipe_command means
    no pipe is active even when the flag is 1 (defensive — tmux versions
    differ).
    """
    line = output.strip("\n")
    if not line:
        return PaneState(pipe_active=False, pipe_command="")
    parts = line.split(" ", 1)
    flag = parts[0]
    cmd = parts[1] if len(parts) > 1 else ""
    pipe_active = flag == "1"
    if pipe_active and not cmd.strip():
        # Defensive: tmux reports pipe_pipe=1 with empty command when the
        # pipe was started without a command (toggle-off semantics). Treat
        # as "not pipe-active" because there's nothing to dispatch against.
        pipe_active = False
    return PaneState(pipe_active=pipe_active, pipe_command=cmd)


def classify_pipe_target(
    pipe_command: str, expected_canonical_path: str
) -> PipeTargetClassification:
    """Classify ``pipe_command`` against the daemon-computed canonical path (FR-054).

    Strict equality: the parsed command MUST be exactly ``cat >> <quoted_path>``
    where ``<quoted_path>`` is the result of ``shlex.quote(expected_canonical_path)``.

    Substring trickery (chained redirections, embedded shell separators) yields
    "foreign" classification (FR-054 defense against A3/NT4).
    """
    if not pipe_command.strip():
        return PipeTargetClassification(is_canonical=False, foreign_target=None)

    expected_inner = f"cat >> {shlex.quote(expected_canonical_path)}"
    # The pane_pipe_command field is the inner command tmux ran; we compare
    # against the same exact form the daemon would issue. No prefix/substring
    # match is allowed.
    if pipe_command.strip() == expected_inner:
        return PipeTargetClassification(is_canonical=True, foreign_target=None)
    return PipeTargetClassification(
        is_canonical=False, foreign_target=pipe_command.strip()
    )


# Cap for `prior_pipe_target` audit field (FR-062 / FR-044).
PRIOR_PIPE_TARGET_CAP: Final[int] = 2048


def sanitize_prior_pipe_target(value: str) -> str:
    """Sanitize a foreign pipe command for the ``prior_pipe_target`` audit field.

    NUL-strip, drop C0/DEL, normalize whitespace, cap at
    :data:`PRIOR_PIPE_TARGET_CAP` chars (FR-062 / FR-044).
    """
    chars: list[str] = []
    for ch in value:
        if ch == "\x00":
            continue
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            chars.append(" ")
            continue
        chars.append(ch)
    cleaned = "".join(chars).strip()
    if len(cleaned) > PRIOR_PIPE_TARGET_CAP:
        return cleaned[: PRIOR_PIPE_TARGET_CAP - 1] + "…"
    return cleaned
