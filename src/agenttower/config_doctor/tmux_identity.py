"""Tmux self-identity parsing (FR-009, FR-010, FR-011, FR-021, R-005).

Pure read-only parsing of ``$TMUX`` and ``$TMUX_PANE`` from the process
environment. The daemon cross-check classifier shipped as
``checks.check_tmux_pane_match`` — folded into ``checks.py`` for
code-locality with the other doctor checks rather than living in this
module.

FR-009: ``$TMUX`` is comma-separated as
``socket_path,server_pid,session_id``. We split on the first two commas only
so an unusual session id containing commas survives. Only ``socket_path``
participates in the daemon cross-check.

FR-010: ``$TMUX_PANE`` must match ``^%[0-9]+$``.

FR-011: no ``tmux`` subprocess; pure env inspection.
FR-021: every parsed field is sanitized through ``sanitize.py``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from agenttower.config_doctor.sanitize import ENV_VALUE_CAP, sanitize_text

_TMUX_PANE_RE = re.compile(r"^%[0-9]+$")


@dataclass(frozen=True)
class ParsedTmuxEnv:
    """Result of parsing ``$TMUX`` + ``$TMUX_PANE`` (data-model §3.4)."""

    in_tmux: bool
    tmux_socket_path: str | None
    server_pid: str | None
    session_id: str | None
    tmux_pane_id: str | None
    pane_id_valid: bool
    malformed_reason: str | None  # one-line operator-facing detail when malformed


def parse_tmux_env(env: Mapping[str, str]) -> ParsedTmuxEnv:
    """Parse ``$TMUX`` and ``$TMUX_PANE`` per FR-009 / FR-010 / FR-021."""

    raw_tmux = env.get("TMUX")
    raw_pane = env.get("TMUX_PANE")

    if raw_tmux is None or raw_tmux == "":
        # FR-009 / spec edge case: $TMUX unset → not_in_tmux (info, not fail).
        # We do NOT treat $TMUX_PANE alone as "in tmux"; tmux always sets both.
        return ParsedTmuxEnv(
            in_tmux=False,
            tmux_socket_path=None,
            server_pid=None,
            session_id=None,
            tmux_pane_id=None,
            pane_id_valid=False,
            malformed_reason=None,
        )

    sanitized_tmux, _ = sanitize_text(raw_tmux, ENV_VALUE_CAP)

    # Split on the first two commas only so session_id can contain commas.
    parts = sanitized_tmux.split(",", 2)
    if len(parts) != 3:
        return ParsedTmuxEnv(
            in_tmux=True,
            tmux_socket_path=None,
            server_pid=None,
            session_id=None,
            tmux_pane_id=None,
            pane_id_valid=False,
            malformed_reason="$TMUX is set but does not have three comma-separated fields",
        )

    socket_path, server_pid, session_id = parts

    if not socket_path or not server_pid or not session_id:
        return ParsedTmuxEnv(
            in_tmux=True,
            tmux_socket_path=socket_path or None,
            server_pid=server_pid or None,
            session_id=session_id or None,
            tmux_pane_id=None,
            pane_id_valid=False,
            malformed_reason="$TMUX has an empty field",
        )

    # $TMUX_PANE handling
    if raw_pane is None or raw_pane == "":
        return ParsedTmuxEnv(
            in_tmux=True,
            tmux_socket_path=socket_path,
            server_pid=server_pid,
            session_id=session_id,
            tmux_pane_id=None,
            pane_id_valid=False,
            malformed_reason="$TMUX is set but $TMUX_PANE is unset",
        )

    sanitized_pane, _ = sanitize_text(raw_pane, ENV_VALUE_CAP)
    pane_valid = bool(_TMUX_PANE_RE.match(sanitized_pane))

    return ParsedTmuxEnv(
        in_tmux=True,
        tmux_socket_path=socket_path,
        server_pid=server_pid,
        session_id=session_id,
        tmux_pane_id=sanitized_pane,
        pane_id_valid=pane_valid,
        malformed_reason=None
        if pane_valid
        else "$TMUX_PANE does not match the %N shape",
    )


__all__ = ["ParsedTmuxEnv", "parse_tmux_env"]
