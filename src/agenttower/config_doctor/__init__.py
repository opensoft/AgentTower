"""FEAT-005 container thin-client diagnostic package.

Pure read-only diagnostic surface: socket-path resolution, container-runtime
detection, identity / tmux self-detection, and the ``agenttower config doctor``
subcommand. Writes nothing to disk (FR-029); reuses the existing FEAT-002
client and FEAT-003 / FEAT-004 socket methods (FR-022, FR-026).
"""

from __future__ import annotations

MAX_SUPPORTED_SCHEMA_VERSION = 8
"""Highest SQLite schema_version this CLI build understands (R-010); bumped to 8 by FEAT-010 (routes table + message_queue origin/route_id/event_id columns + partial UNIQUE index)."""

# Re-exports — see plan §Structure Decision. These are imported lazily inside
# functions to avoid circular imports at package init time; consumers should
# either import from the submodule directly or from this package using
# ``from agenttower.config_doctor import run_doctor`` (lazy hook below).
from agenttower.config_doctor.checks import (  # noqa: E402,F401
    CheckCode,
    CheckResult,
    CheckStatus,
)
from agenttower.config_doctor.identity import (  # noqa: E402,F401
    IdentityCandidate,
)
from agenttower.config_doctor.render import render_json, render_tsv  # noqa: E402,F401
from agenttower.config_doctor.runner import (  # noqa: E402,F401
    CHECK_ORDER,
    DoctorReport,
    run_doctor,
)
from agenttower.config_doctor.socket_resolve import (  # noqa: E402,F401
    SocketPathInvalid,
)
from agenttower.config_doctor.tmux_identity import (  # noqa: E402,F401
    ParsedTmuxEnv,
)
from agenttower.paths import ResolvedSocket  # noqa: E402,F401

__all__ = [
    "CHECK_ORDER",
    "CheckCode",
    "CheckResult",
    "CheckStatus",
    "DoctorReport",
    "IdentityCandidate",
    "MAX_SUPPORTED_SCHEMA_VERSION",
    "ParsedTmuxEnv",
    "ResolvedSocket",
    "SocketPathInvalid",
    "render_json",
    "render_tsv",
    "run_doctor",
]
