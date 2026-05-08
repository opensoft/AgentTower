"""FR-010 / FR-011 / FR-019 / FR-021c / FR-047 ``tmux pipe-pane`` shell construction.

Builds the argv lists the daemon hands to ``subprocess`` (no ``shell=True``
at the outer Python layer; FR-047 / Constitution Principle III). Every
interpolated value is shell-quoted via ``shlex.quote`` so an FR-006-validated
path with spaces or shell-meaningful (but printable) bytes still constructs
a safe inner shell command.
"""

from __future__ import annotations

import shlex
from typing import Final


# FR-012 / FR-062: stderr excerpt cap (NUL strip, ≤ 2048 chars, no control bytes).
_STDERR_CAP: Final[int] = 2048
# FR-062 / data-model.md §1.1: pipe_pane_command storage cap.
_PIPE_COMMAND_CAP: Final[int] = 4096


def build_attach_argv(
    container_user: str,
    container_id: str,
    pane_short_form: str,
    container_side_log: str,
) -> list[str]:
    """Return the argv list for ``tmux pipe-pane -o`` attach (FR-010 + FR-047).

    Inner shell command is constructed by interpolating ``shlex.quote``-ed
    values into ``cat >> <log>``; the daemon hands this to ``sh -lc`` via
    ``docker exec -u <container_user> <container_id>``.

    Callers MUST validate ``container_side_log`` shape via path_validation
    BEFORE invoking this function (defense in depth — shlex.quote handles the
    remaining shell-meaningful chars per FR-047).
    """
    inner = (
        f"tmux pipe-pane -o -t {shlex.quote(pane_short_form)} "
        f"{shlex.quote(f'cat >> {shlex.quote(container_side_log)}')}"
    )
    return [
        "docker",
        "exec",
        "-u",
        container_user,
        container_id,
        "sh",
        "-lc",
        inner,
    ]


def build_toggle_off_argv(
    container_user: str,
    container_id: str,
    pane_short_form: str,
) -> list[str]:
    """Return the argv list for ``tmux pipe-pane -t <pane>`` toggle-off (FR-019 / FR-021c)."""
    inner = f"tmux pipe-pane -t {shlex.quote(pane_short_form)}"
    return [
        "docker",
        "exec",
        "-u",
        container_user,
        container_id,
        "sh",
        "-lc",
        inner,
    ]


def build_inspection_argv(
    container_user: str,
    container_id: str,
    pane_short_form: str,
) -> list[str]:
    """Return the argv list for FR-011 pipe-state inspection.

    ``tmux list-panes -F '#{pane_pipe} #{pane_pipe_command}' -t <pane>``
    """
    inner = (
        f"tmux list-panes -F {shlex.quote('#{pane_pipe} #{pane_pipe_command}')} "
        f"-t {shlex.quote(pane_short_form)}"
    )
    return [
        "docker",
        "exec",
        "-u",
        container_user,
        container_id,
        "sh",
        "-lc",
        inner,
    ]


def render_pipe_command_for_audit(
    container_user: str,
    container_id: str,
    pane_short_form: str,
    container_side_log: str,
) -> str:
    """Return the literal shell command stored in ``log_attachments.pipe_pane_command``.

    Sanitized + bounded (FR-062 / data-model.md §1.1: ≤ 4096 chars).
    Stored for forensic audit only; never re-executed (FR-065 / NT3).
    """
    rendered = shlex.join(
        build_attach_argv(
            container_user, container_id, pane_short_form, container_side_log
        )
    )
    # Sanitize: drop NUL, drop other C0 control bytes, cap at 4096 chars.
    cleaned = "".join(
        ch for ch in rendered if ord(ch) >= 0x20 or ch in ("\t",)
    )
    if len(cleaned) > _PIPE_COMMAND_CAP:
        return cleaned[: _PIPE_COMMAND_CAP - 1] + "…"
    return cleaned


def sanitize_pipe_pane_stderr(stderr: bytes | str) -> str:
    """Return a sanitized stderr excerpt suitable for ``pipe_pane_failed`` messages.

    NUL-strip, drop C0 control bytes (preserve TAB and newline → space), cap at
    :data:`_STDERR_CAP` chars (FR-012 / FR-062).
    """
    if isinstance(stderr, bytes):
        text = stderr.decode("utf-8", errors="replace")
    else:
        text = stderr
    cleaned_chars: list[str] = []
    for ch in text:
        if ch == "\x00":
            continue
        if ch in ("\n", "\r", "\t"):
            cleaned_chars.append(" ")
            continue
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            continue
        cleaned_chars.append(ch)
    cleaned = "".join(cleaned_chars).strip()
    if len(cleaned) > _STDERR_CAP:
        return cleaned[: _STDERR_CAP - 1] + "…"
    return cleaned


# FR-012: tmux stderr patterns that surface as `pipe_pane_failed` regardless
# of exit code. Daemon checks for substring presence after sanitization.
PIPE_PANE_STDERR_PATTERNS: Final[tuple[str, ...]] = (
    "session not found",
    "pane not found",
    "no current target",
)
