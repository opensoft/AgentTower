"""Socket-path resolution with FR-002 validator (R-001, R-002).

Pure function ``resolve_socket_path(env, host_paths, runtime_context) ->
ResolvedSocket`` runs at every CLI invocation. Priority:

1. ``AGENTTOWER_SOCKET`` when set and valid → ``source = "env_override"``.
2. Mounted-default ``/run/agenttower/agenttowerd.sock``, only when the
   runtime context is ``ContainerContext`` AND the path resolves to a Unix
   socket → ``source = "mounted_default"``.
3. FEAT-001 host default (``host_paths.socket``) → ``source = "host_default"``.

The FR-002 validator gates ``AGENTTOWER_SOCKET``:

* non-empty after ``str.strip``
* absolute (``os.path.isabs(value)`` is true)
* free of NUL bytes
* points at a path whose target satisfies ``stat.S_ISSOCK`` after **exactly
  one** ``os.readlink`` follow

A failure raises :class:`SocketPathInvalid` carrying the closed-set
``<reason>`` token; the CLI maps the exception to exit ``1`` with the
literal stderr ``error: AGENTTOWER_SOCKET must be an absolute path to a
Unix socket: <reason>``.

Per Clarifications 2026-05-06 / analyze finding A4: the "exactly one
``os.readlink`` follow" rule is enforced explicitly. If the target of the
single readlink is itself a symlink (chained symlinks), the second-level
symlink is **not** followed and the path fails with sub-code
``not_a_socket`` reason ``"value is not a Unix socket"``. Cycle detection is
unnecessary because we never follow more than one level.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path

from agenttower.config_doctor.runtime_detect import (
    ContainerContext,
    RuntimeContext,
)
from agenttower.paths import Paths, ResolvedSocket, SocketSource

MOUNTED_DEFAULT_PATH = Path("/run/agenttower/agenttowerd.sock")
"""R-002: the MVP in-container default mounted socket path."""

# FR-002 closed-set ``<reason>`` tokens. These literals are part of the
# stable CLI stderr contract and are referenced by name throughout the
# validator and doctor checks; defining them as constants prevents drift
# under refactor (locked by T009 + T024 spelling assertions).
REASON_EMPTY = "value is empty"
REASON_NOT_ABSOLUTE = "value is not absolute"
REASON_NUL_BYTE = "value contains NUL byte"
REASON_DOES_NOT_EXIST = "value does not exist"
REASON_NOT_UNIX_SOCKET = "value is not a Unix socket"


class SocketPathInvalid(Exception):
    """Raised when AGENTTOWER_SOCKET is set but fails the FR-002 validator.

    ``reason`` is one of the closed-set ``<reason>`` tokens:

    * ``"value is empty"``
    * ``"value is not absolute"``
    * ``"value contains NUL byte"``
    * ``"value does not exist"``
    * ``"value is not a Unix socket"``
    """

    REASONS = (
        REASON_EMPTY,
        REASON_NOT_ABSOLUTE,
        REASON_NUL_BYTE,
        REASON_DOES_NOT_EXIST,
        REASON_NOT_UNIX_SOCKET,
    )

    def __init__(self, reason: str):
        if reason not in self.REASONS:
            raise ValueError(f"invalid SocketPathInvalid reason: {reason!r}")
        super().__init__(reason)
        self.reason = reason


def _validate_env_override(value: str) -> Path:
    """Apply the four FR-002 gates and the A4 single-symlink-follow rule.

    Returns the validated absolute :class:`Path`. Raises
    :class:`SocketPathInvalid` on any gate failure with the closed-set
    ``<reason>`` token.
    """

    stripped = value.strip()
    if not stripped:
        raise SocketPathInvalid(REASON_EMPTY)
    if "\x00" in stripped:
        raise SocketPathInvalid(REASON_NUL_BYTE)
    if not os.path.isabs(stripped):
        raise SocketPathInvalid(REASON_NOT_ABSOLUTE)

    candidate = Path(stripped)

    # Apply exactly one os.readlink follow per FR-002 / R-001.
    # Per analyze finding A4: if the single readlink target is itself a symlink,
    # the path fails with REASON_NOT_UNIX_SOCKET — we do NOT follow a second
    # symlink. This makes the "exactly one follow" rule load-bearing under
    # operator-controlled symlink chains.
    target_for_stat: Path = candidate
    try:
        if candidate.is_symlink():
            link_target_str = os.readlink(candidate)
            link_target = Path(link_target_str)
            if not link_target.is_absolute():
                link_target = candidate.parent / link_target
            # Reject second-level symlinks (A4 chained-symlink policy).
            try:
                if link_target.is_symlink():
                    raise SocketPathInvalid(REASON_NOT_UNIX_SOCKET)
            except OSError:
                # is_symlink() raises on broken parent paths — treat as not a socket
                raise SocketPathInvalid(REASON_DOES_NOT_EXIST)
            target_for_stat = link_target
    except FileNotFoundError:
        raise SocketPathInvalid(REASON_DOES_NOT_EXIST)
    except OSError:
        raise SocketPathInvalid(REASON_DOES_NOT_EXIST)

    try:
        # Use lstat on the post-readlink target to enforce the "no second-level
        # follow" rule explicitly: lstat does not dereference the final symlink
        # if any. Combined with the above is_symlink check, this means a
        # symlink-to-symlink chain fails before we ever stat the second link's
        # target.
        st = os.lstat(target_for_stat)
    except OSError:
        # FileNotFoundError is a subclass of OSError; both map to the same
        # closed-set reason (REASON_DOES_NOT_EXIST).
        raise SocketPathInvalid(REASON_DOES_NOT_EXIST)

    if not stat.S_ISSOCK(st.st_mode):
        raise SocketPathInvalid(REASON_NOT_UNIX_SOCKET)

    return candidate


def _mounted_default_is_reachable() -> bool:
    """Check whether the mounted-default path resolves to a Unix socket.

    Honors a single ``os.readlink`` follow consistent with the FR-002 rule.
    Returns ``False`` quietly on any error (the CLI will fall through to
    the host default).
    """

    path = MOUNTED_DEFAULT_PATH
    try:
        if path.is_symlink():
            link_target_str = os.readlink(path)
            link_target = Path(link_target_str)
            if not link_target.is_absolute():
                link_target = path.parent / link_target
            if link_target.is_symlink():
                return False
            path = link_target
        st = os.lstat(path)
    except OSError:
        # FileNotFoundError is a subclass of OSError; both fall through.
        return False
    return stat.S_ISSOCK(st.st_mode)


def resolve_socket_path(
    env: Mapping[str, str],
    host_paths: Paths,
    runtime_context: RuntimeContext,
) -> ResolvedSocket:
    """Resolve the daemon socket path (R-001, FR-001, FR-002).

    Raises :class:`SocketPathInvalid` when ``AGENTTOWER_SOCKET`` is set but
    fails the FR-002 validator. The CLI MUST NOT silently fall back to a
    default in that case.
    """

    env_value = env.get("AGENTTOWER_SOCKET")
    if env_value is not None:
        validated = _validate_env_override(env_value)
        return ResolvedSocket(path=validated, source="env_override")

    if isinstance(runtime_context, ContainerContext) and _mounted_default_is_reachable():
        return ResolvedSocket(path=MOUNTED_DEFAULT_PATH, source="mounted_default")

    return ResolvedSocket(path=host_paths.socket, source="host_default")


__all__ = [
    "MOUNTED_DEFAULT_PATH",
    "ResolvedSocket",
    "SocketPathInvalid",
    "SocketSource",
    "resolve_socket_path",
]
