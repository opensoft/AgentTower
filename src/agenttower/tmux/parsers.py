"""Pure parsers + sanitization helpers for FEAT-004.

No I/O; no Docker dependency; no tmux dependency. Every function takes a
``str`` (subprocess stdout, in production) and returns a typed dataclass
or a list. Per-field length caps and byte-class stripping live here so
the reconciler stays focused on per-(container, socket) write-set
construction (R-009).
"""

from __future__ import annotations

from dataclasses import dataclass


# Per-field max lengths (UTF-8-aware, character count) per FR-023 / R-009.
MAX_TITLE = 2048
MAX_COMMAND = 2048
MAX_PATH = 4096
MAX_DEFAULT = 2048


@dataclass(frozen=True)
class ParsedPane:
    """One ``tmux list-panes`` row, post-split, pre-sanitization."""

    tmux_session_name: str
    tmux_window_index: int
    tmux_pane_index: int
    tmux_pane_id: str
    pane_pid: int
    pane_tty: str
    pane_current_command: str
    pane_current_path: str
    pane_title: str
    pane_active: bool


@dataclass(frozen=True)
class MalformedRow:
    """A ``tmux list-panes`` row that failed shape validation (R-002)."""

    raw_line: str
    expected_fields: int
    actual_fields: int


def sanitize_text(value: str, max_length: int) -> tuple[str, bool]:
    """Strip NUL + C0 control bytes; replace tabs/newlines with spaces; truncate.

    Returns ``(value, truncated)`` where ``truncated`` is True iff the
    pre-truncation character count exceeded ``max_length`` (R-009 / FR-023).

    - NUL byte (``\\x00``) is dropped.
    - C0 control range (``\\x01``-``\\x08``, ``\\x0b``-``\\x1f``, ``\\x7f``) is dropped.
    - ``\\t`` and ``\\n`` are replaced with a single space (so the human
      TSV view stays one row per pane).
    - Truncation is character-based (UTF-8-aware), not byte-based.
    """
    if value is None:
        return "", False
    chars: list[str] = []
    for ch in value:
        ord_ch = ord(ch)
        if ord_ch == 0x00:
            continue
        if ch == "\t" or ch == "\n":
            chars.append(" ")
            continue
        if ord_ch < 0x20 or ord_ch == 0x7F:
            continue
        chars.append(ch)
    cleaned = "".join(chars)
    truncated = len(cleaned) > max_length
    if truncated:
        cleaned = cleaned[:max_length]
    return cleaned, truncated


def parse_id_u(stdout: str) -> str:
    """Parse the stdout of ``id -u`` and return the digit string.

    Raises ``ValueError`` when the stdout is empty after stripping or the
    first non-empty line is not a positive integer.
    """
    if stdout is None:
        raise ValueError("id -u stdout is None")
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.isdigit():
            raise ValueError(f"id -u stdout is not a positive integer: {line!r}")
        return line
    raise ValueError("id -u stdout is empty")


def parse_socket_listing(stdout: str) -> list[str]:
    """Parse ``ls -1 -- /tmp/tmux-<uid>`` stdout into candidate socket names.

    Skips empty lines and any name that contains ``/`` (defensive — ``ls -1``
    against a directory should never emit those, but this prevents path
    traversal if the kernel surprises us). Returns the names in the order
    ``ls`` emitted them; preserves duplicates so the reconciler can detect
    them as malformed if they ever appear.
    """
    if stdout is None:
        return []
    out: list[str] = []
    for raw in stdout.splitlines():
        name = raw.rstrip("\r")
        if not name:
            continue
        if "/" in name or name in (".", ".."):
            continue
        out.append(name)
    return out


def parse_list_panes(stdout: str) -> tuple[list[ParsedPane], list[MalformedRow]]:
    """Parse ``tmux list-panes -a -F <format>`` stdout (R-002).

    The format string emits 10 tab-separated fields per row:

        session_name, window_index, pane_index, pane_id, pane_pid,
        pane_tty, pane_current_command, pane_current_path, pane_title,
        pane_active

    Rows with the wrong field count, non-integer numerics, or unparseable
    booleans are returned as ``MalformedRow`` rather than raising.
    """
    parsed: list[ParsedPane] = []
    malformed: list[MalformedRow] = []
    if stdout is None:
        return parsed, malformed
    for raw in stdout.splitlines():
        line = raw.rstrip("\r")
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 10:
            malformed.append(
                MalformedRow(
                    raw_line=line[:256],
                    expected_fields=10,
                    actual_fields=len(fields),
                )
            )
            continue
        try:
            window_index = int(fields[1])
            pane_index = int(fields[2])
            pane_pid = int(fields[4])
            active = _parse_bool(fields[9])
        except (ValueError, TypeError):
            malformed.append(
                MalformedRow(
                    raw_line=line[:256],
                    expected_fields=10,
                    actual_fields=len(fields),
                )
            )
            continue
        parsed.append(
            ParsedPane(
                tmux_session_name=fields[0],
                tmux_window_index=window_index,
                tmux_pane_index=pane_index,
                tmux_pane_id=fields[3],
                pane_pid=pane_pid,
                pane_tty=fields[5],
                pane_current_command=fields[6],
                pane_current_path=fields[7],
                pane_title=fields[8],
                pane_active=active,
            )
        )
    return parsed, malformed


def _parse_bool(value: str) -> bool:
    """Parse a tmux ``#{pane_active}`` field as ``"1"`` or ``"0"``."""
    v = value.strip()
    if v == "1":
        return True
    if v == "0":
        return False
    raise ValueError(f"unparseable boolean: {value!r}")
