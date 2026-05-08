"""Single authoritative source for the AgentTower canonical log-root prefix.

Per FR-005, the literal prefix ``~/.local/state/opensoft/agenttower/logs/``
(host-side, after ``~`` is expanded to the daemon user's home) is the
SINGLE authoritative constant referenced by FR-011 (canonical-target
match), FR-043 (orphan detection), FR-052 (daemon-owned-path rejection),
and FR-054 (strict-equality match). Every consumer in the codebase MUST
import from this module — ad-hoc duplication is forbidden.

This module also exposes the daemon-owned root prefixes (FR-052) so the
path-validation layer can reject ``--log`` paths that target daemon
state files.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

# Relative-to-$HOME path; resolve via host_canonical_log_root_for() at runtime
# so the constant is testable across isolated $HOME fixtures.
_LOG_ROOT_REL: Final[str] = ".local/state/opensoft/agenttower/logs"

# Daemon-owned roots under $HOME (FR-052). The canonical log subdirectory
# is the ONLY allowed exception under .local/state/opensoft/agenttower.
_DAEMON_OWNED_ROOTS_REL: Final[tuple[str, ...]] = (
    ".local/state/opensoft/agenttower",
    ".config/opensoft",
    ".cache/opensoft",
)

# Special filesystem prefixes (FR-053). Realpath of the supplied --log
# path MUST NOT lie under any of these.
_SPECIAL_FS_ROOTS: Final[tuple[str, ...]] = ("/proc/", "/sys/", "/dev/", "/run/")


def host_canonical_log_root_for(home: str | os.PathLike[str]) -> Path:
    """Return the host-side canonical log root for the given $HOME.

    The result is the realpath-normalized form ``<home>/.local/state/opensoft/agenttower/logs``.
    """
    return Path(home) / _LOG_ROOT_REL


def host_canonical_log_path_for(
    home: str | os.PathLike[str], container_id: str, agent_id: str
) -> Path:
    """Return the FR-005 default host-side log path for ``(container_id, agent_id)``.

    ``container_id`` MUST be the FULL 64-char id (FR-005); ``agent_id`` MUST
    be ``agt_<12-hex>`` (FEAT-006). Callers are responsible for shape
    validation BEFORE invoking this helper — it does no input checking
    because every code path that constructs the canonical path has already
    resolved both fields against persisted FEAT-006 / FEAT-003 state.
    """
    return host_canonical_log_root_for(home) / container_id / f"{agent_id}.log"


def daemon_owned_roots_for(home: str | os.PathLike[str]) -> tuple[Path, ...]:
    """Return the absolute daemon-owned root prefixes under ``home`` (FR-052).

    A supplied ``--log <path>`` MUST be rejected with ``log_path_invalid``
    if it lies under any of these prefixes — EXCEPT for the canonical log
    subdirectory under ``.local/state/opensoft/agenttower/logs/<container>/``.
    """
    home_path = Path(home)
    return tuple(home_path / rel for rel in _DAEMON_OWNED_ROOTS_REL)


def is_under_canonical_log_root(
    candidate: Path, *, home: str | os.PathLike[str]
) -> bool:
    """Return True iff ``candidate`` lies under the canonical log root.

    Uses the lexical prefix check; callers that need symlink-safe semantics
    MUST call ``os.path.realpath`` first (FR-050).
    """
    try:
        candidate.resolve(strict=False).relative_to(
            host_canonical_log_root_for(home).resolve(strict=False)
        )
        return True
    except ValueError:
        return False


SPECIAL_FS_PREFIXES: Final[tuple[str, ...]] = _SPECIAL_FS_ROOTS
"""Read-only export of the FR-053 special-filesystem prefix list."""
