"""tmux integration helpers (FEAT-004)."""

from __future__ import annotations

from .adapter import (
    FailedSocketScan,
    OkSocketScan,
    SocketListing,
    SocketScanOutcome,
    TmuxAdapter,
    TmuxError,
)
from .fakes import FakeTmuxAdapter
from .subprocess_adapter import SubprocessTmuxAdapter
from .parsers import (
    MAX_COMMAND,
    MAX_DEFAULT,
    MAX_PATH,
    MAX_TITLE,
    MalformedRow,
    ParsedPane,
    parse_id_u,
    parse_list_panes,
    parse_socket_listing,
    sanitize_text,
)

__all__ = [
    "FailedSocketScan",
    "FakeTmuxAdapter",
    "MAX_COMMAND",
    "MAX_DEFAULT",
    "MAX_PATH",
    "MAX_TITLE",
    "MalformedRow",
    "OkSocketScan",
    "ParsedPane",
    "SocketListing",
    "SocketScanOutcome",
    "SubprocessTmuxAdapter",
    "TmuxAdapter",
    "TmuxError",
    "parse_id_u",
    "parse_list_panes",
    "parse_socket_listing",
    "sanitize_text",
]
