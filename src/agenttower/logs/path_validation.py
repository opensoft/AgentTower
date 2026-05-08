"""FR-006 + FR-051 + FR-052 + FR-053 ``--log <path>`` validation.

Mirrors FEAT-006 ``validate_project_path`` (FR-006) and adds the FEAT-007
hardening rules: shell-meaningful byte rejection (FR-051), daemon-owned-root
rejection (FR-052), special-filesystem rejection (FR-053).

Symlink-escape rejection (FR-050) lives in ``host_visibility.py`` because it
needs the resolved mount Source root for context.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

from .canonical_paths import (
    SPECIAL_FS_PREFIXES,
    daemon_owned_roots_for,
    host_canonical_log_root_for,
)


class LogPathInvalid(Exception):
    """Raised when ``--log <path>`` fails FR-006/FR-051/FR-052/FR-053 shape rules.

    The ``message`` attribute is the actionable, operator-facing string
    suitable for the closed-set ``log_path_invalid`` rejection.
    """


_PATH_MAX: Final[int] = 4096

# FR-051 forbidden bytes beyond NUL/C0/DEL (which FR-006 already rejects).
# Newline/CR/TAB break log-line parsing for FEAT-008 readers.
_C0_RANGE: Final[range] = range(0x00, 0x20)
_FORBIDDEN_BYTES: Final[frozenset[int]] = (
    frozenset(_C0_RANGE) | frozenset({0x7F})  # NUL/C0 + DEL
)


def validate_log_path(value: object, *, home: str | os.PathLike[str]) -> str:
    """Return *value* if it passes FR-006/FR-051/FR-052/FR-053; raise otherwise.

    ``home`` is the daemon user's $HOME used to resolve the daemon-owned roots
    (FR-052). The canonical log subdirectory under ``home`` is exempted from
    the daemon-owned-root rejection so attach-log can still write under the
    documented log directory.

    Does NOT consult the filesystem (no ``stat``, no ``realpath``). Symlink
    semantics are deferred to the FR-050 host-visibility proof which has
    enough context to decide whether a symlink target escapes the bind mount.
    """
    if not isinstance(value, str):
        raise LogPathInvalid(
            f"log_path must be a string; got {type(value).__name__}"
        )

    if "\x00" in value:
        raise LogPathInvalid("log_path must not contain NUL bytes")

    if len(value) == 0:
        raise LogPathInvalid("log_path must not be empty")

    if len(value) > _PATH_MAX:
        raise LogPathInvalid(
            f"log_path exceeds maximum length {_PATH_MAX} (got {len(value)})"
        )

    # FR-051: reject any C0 control byte or DEL.
    forbidden_byte = next(
        (b for b in value.encode("utf-8", errors="surrogatepass") if b in _FORBIDDEN_BYTES),
        None,
    )
    if forbidden_byte is not None:
        raise LogPathInvalid(
            f"log_path contains forbidden control byte 0x{forbidden_byte:02x}"
        )

    if not value.startswith("/"):
        raise LogPathInvalid(
            f"log_path must be an absolute path (start with '/'); got {value!r}"
        )

    # FR-006: no '..' segment.
    parts = value.split("/")
    if any(p == ".." for p in parts):
        raise LogPathInvalid(
            f"log_path must not contain '..' segment; got {value!r}"
        )

    candidate = Path(value)

    # FR-053: realpath under /proc, /sys, /dev, /run is forbidden. We do a
    # lexical check first; if the path is already under the prefix we fail
    # immediately. The realpath check happens later inside the host-visibility
    # proof which has filesystem context.
    for prefix in SPECIAL_FS_PREFIXES:
        if value == prefix.rstrip("/") or value.startswith(prefix):
            raise LogPathInvalid(
                f"log_path resolves under special filesystem {prefix!r}; refusing attach"
            )

    # FR-052: reject paths under any daemon-owned root EXCEPT the canonical
    # log subdirectory.
    log_root = host_canonical_log_root_for(home)
    canonical_log_root_str = str(log_root) + "/"
    if value == str(log_root) or value.startswith(canonical_log_root_str):
        # Allowed: under the canonical log root.
        pass
    else:
        for owned in daemon_owned_roots_for(home):
            owned_str = str(owned)
            if value == owned_str or value.startswith(owned_str + "/"):
                raise LogPathInvalid(
                    f"log_path lies under daemon-owned root {owned_str!r}; "
                    f"the only allowed exception is {canonical_log_root_str.rstrip('/')!r}"
                )

    return value
