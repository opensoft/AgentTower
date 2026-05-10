"""Host-filesystem adapter for FEAT-007.

Wraps ``os.stat`` / ``os.path`` / ``os.makedirs`` / ``os.access`` / ``os.open``
into a small surface that can be substituted via the
``AGENTTOWER_TEST_LOG_FS_FAKE`` env var (Research R-013, FR-060). Production
code paths use the real syscalls verbatim; the fake is consulted ONLY by this
module.

The fake's JSON shape is documented in data-model.md §6 and re-stated here:

    {
      "/host/path/A.log": {
        "exists": true,
        "inode": "234:1234567",
        "size": 4096,
        "mtime_iso": "2026-05-08T14:23:45.123456+00:00",
        "contents": "line one\\nline two\\n..."
      },
      "/host/path/B.log": { "exists": false }
    }
"""

from __future__ import annotations

import datetime
import errno
import json
import os
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..config import _DIR_MODE, _FILE_MODE, _verify_file_mode

_FAKE_ENV_VAR: Final[str] = "AGENTTOWER_TEST_LOG_FS_FAKE"

_fake_lock = threading.Lock()
_fake_cache: dict[str, dict] | None = None
_fake_cache_path: str | None = None


@dataclass(frozen=True)
class FileStat:
    """Filesystem observation for a host log file (R-010)."""

    inode: str  # "<dev>:<ino>" string
    size: int
    mtime_iso: str  # ISO-8601 microsecond UTC

    @staticmethod
    def from_os_stat(st: os.stat_result) -> "FileStat":
        ts = datetime.datetime.fromtimestamp(
            st.st_mtime, tz=datetime.timezone.utc
        ).isoformat(timespec="microseconds")
        return FileStat(
            inode=f"{st.st_dev}:{st.st_ino}",
            size=int(st.st_size),
            mtime_iso=ts,
        )


def _load_fake_or_none() -> dict[str, dict] | None:
    """Return the fake JSON map if ``AGENTTOWER_TEST_LOG_FS_FAKE`` is set, else None.

    Reads once, caches forever (consumers reset by calling :func:`_reset_for_test`).
    """
    global _fake_cache, _fake_cache_path
    fake_path = os.environ.get(_FAKE_ENV_VAR)
    if fake_path is None:
        return None
    with _fake_lock:
        if _fake_cache_path == fake_path and _fake_cache is not None:
            return _fake_cache
        with open(fake_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(
                f"AGENTTOWER_TEST_LOG_FS_FAKE at {fake_path!r} must be a JSON object"
            )
        _fake_cache = data
        _fake_cache_path = fake_path
        return _fake_cache


def _reset_for_test() -> None:
    """Drop the cached fake map. Tests rewrite the JSON between scenarios."""
    global _fake_cache, _fake_cache_path
    with _fake_lock:
        _fake_cache = None
        _fake_cache_path = None


def stat_log_file(host_path: str) -> FileStat | None:
    """Return :class:`FileStat` for ``host_path`` or None if missing.

    Honors the FR-060 test seam. Uses ``os.stat(follow_symlinks=False)`` per
    Research R-010 to defend against symlink trickery (the FR-007 / FR-050
    proof has already vetted the path before any caller reaches stat).
    """
    fake = _load_fake_or_none()
    if fake is not None:
        entry = fake.get(host_path)
        if entry is None or not entry.get("exists", False):
            return None
        inode = entry.get("inode")
        if not isinstance(inode, str):
            raise ValueError(
                f"AGENTTOWER_TEST_LOG_FS_FAKE entry for {host_path!r} missing 'inode'"
            )
        return FileStat(
            inode=inode,
            size=int(entry.get("size", 0)),
            mtime_iso=str(
                entry.get(
                    "mtime_iso",
                    datetime.datetime.now(tz=datetime.timezone.utc).isoformat(
                        timespec="microseconds"
                    ),
                )
            ),
        )
    try:
        st = os.stat(host_path, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return FileStat.from_os_stat(st)


def file_exists(host_path: str) -> bool:
    """Return True if ``host_path`` exists (honors test seam)."""
    return stat_log_file(host_path) is not None


def read_tail_lines(host_path: str, n: int, *, max_line_bytes: int = 65536) -> list[str]:
    """Return the last ``n`` lines of ``host_path`` (FR-033 + FR-064).

    Each line is returned as a ``str`` decoded from UTF-8 with ``surrogateescape``
    error handling. Lines longer than ``max_line_bytes`` are truncated at the
    byte boundary with a trailing ``…`` marker BEFORE decoding (FR-064).

    Honors the FR-060 test seam.
    """
    if n <= 0:
        return []

    fake = _load_fake_or_none()
    if fake is not None:
        entry = fake.get(host_path)
        if entry is None or not entry.get("exists", False):
            raise FileNotFoundError(host_path)
        contents = entry.get("contents", "")
        if not isinstance(contents, str):
            return []
        raw_lines = contents.split("\n")
        # Drop trailing empty fragment from a trailing \n
        if raw_lines and raw_lines[-1] == "":
            raw_lines = raw_lines[:-1]
        tail = raw_lines[-n:]
        return [_truncate_line(line, max_line_bytes) for line in tail]

    # Real filesystem path: tail-read in 8 KiB chunks from the end.
    try:
        size = os.path.getsize(host_path)
    except FileNotFoundError as exc:
        raise FileNotFoundError(host_path) from exc

    if size == 0:
        return []

    with open(host_path, "rb") as f:
        # Step backwards from end, accumulating until we have at least n+1 newlines
        # (the +1 protects against the final partial line).
        block_size = 8192
        data = b""
        offset = size
        newlines_seen = 0
        while offset > 0 and newlines_seen <= n:
            read_bytes = min(block_size, offset)
            offset -= read_bytes
            f.seek(offset)
            chunk = f.read(read_bytes)
            data = chunk + data
            newlines_seen = data.count(b"\n")
            if offset == 0:
                break

    raw = data.decode("utf-8", errors="surrogateescape")
    raw_lines = raw.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines = raw_lines[:-1]
    tail = raw_lines[-n:]
    return [_truncate_line(line, max_line_bytes) for line in tail]


def _truncate_line(line: str, max_bytes: int) -> str:
    """Truncate ``line`` at ``max_bytes`` byte boundary, appending ``…`` (FR-064)."""
    encoded = line.encode("utf-8", errors="surrogateescape")
    if len(encoded) <= max_bytes:
        return line
    truncated = encoded[:max_bytes].decode("utf-8", errors="surrogateescape")
    return truncated + "…"


def ensure_log_directory_and_file(host_path: str) -> None:
    """Create the parent directory at mode 0700 and the file at mode 0600 (FR-008 + FR-048).

    Race-free file creation via ``O_EXCL | O_CREAT | O_WRONLY`` (Research R-011 /
    FR-048). Refuses to broaden modes if the directory or file already exists with
    a wider mode (FR-008 strict-mode invariant).

    Path validation is the caller's responsibility: this function trusts that
    ``host_path`` has already been gated by FR-006 (lexical) + FR-052
    (daemon-owned roots) + FR-053 (special-fs roots) + FR-007 (host-visibility)
    upstream. Adding a redundant namespace assertion here would either duplicate
    those checks or break legitimate operator-supplied ``--log`` paths under
    bind mounts outside the AgentTower namespace.

    The test seam is intentionally NOT consulted for this function — production
    code paths always run real syscalls because the daemon must guarantee on-disk
    file/dir mode invariants. Tests that need to bypass disk creation should use
    integration fixtures rather than the read-side fake.
    """
    parent = Path(host_path).parent
    parent.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
    # Verify parent's mode (FR-008 strict).
    actual = stat.S_IMODE(os.stat(parent).st_mode)
    if actual & ~_DIR_MODE:
        raise OSError(
            errno.EPERM,
            f"log directory mode {oct(actual)} broader than required {oct(_DIR_MODE)}",
            str(parent),
        )

    if not os.path.exists(host_path):
        # TOCTOU on FileExistsError: another process created the file between
        # exists() and open(); FR-048 says we MUST refuse with internal_error,
        # which the unhandled raise (turning into RegistrationError upstream)
        # produces.
        fd = os.open(
            host_path,
            os.O_CREAT | os.O_WRONLY | os.O_EXCL,
            _FILE_MODE,
        )
        os.close(fd)
        # Belt-and-braces chmod: ``os.open(..., _FILE_MODE)`` requests
        # mode 0o600 but the kernel applies the process umask to clear
        # bits — never to add them. This chmod re-asserts exact mode
        # against any umask that would have NARROWED the requested
        # mode further (which would not violate FR-008's strict 0o600
        # invariant, but would surface confusing modes elsewhere).
        os.chmod(host_path, _FILE_MODE)
    else:
        _verify_file_mode(Path(host_path), _FILE_MODE)
