"""Daemon lifecycle primitives: lock, paths-safety, pid file, lifecycle log.

Per FEAT-002 research:

* R-001: lock acquisition with ``fcntl.flock(LOCK_EX | LOCK_NB)``.
* R-002: pid file is informational; lock is the authority on liveness.
* R-011: every host-user-only invariant is enforced by ``assert_paths_safe``.
* R-012: lifecycle log is a tab-separated single file with six event tokens.

Stale-artifact classification + recovery is added by FEAT-002 US3 (T024).
"""

from __future__ import annotations

import errno
import fcntl
import io
import os
import stat
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


class LockHeldError(RuntimeError):
    """Raised when ``LOCK_EX | LOCK_NB`` could not be acquired immediately."""


def acquire_exclusive_lock(lock_path: Path) -> int:
    """Open *lock_path* and acquire a non-blocking exclusive ``flock``.

    Returns the open file descriptor; the caller MUST keep it open for the
    duration of the held lock and close it (``os.close``) to release the
    lock. The kernel also releases the lock automatically on process exit
    (R-001).

    The lock file is created with mode ``0600`` if absent. If the file
    already exists with a broader mode or wrong owner, this raises
    :class:`PermissionError` rather than silently chmodding it (FR-011 /
    R-011 policy: refuse rather than fix).
    """
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        st = os.fstat(fd)
        if (st.st_mode & 0o777) != 0o600 or st.st_uid != os.geteuid():
            raise PermissionError(
                errno.EACCES,
                f"unsafe permissions on lock file (mode={oct(st.st_mode & 0o777)}, uid={st.st_uid})",
                str(lock_path),
            )
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
            raise LockHeldError(f"lock already held: {lock_path}") from exc
        raise
    return fd


def release_lock(fd: int) -> None:
    """Release the lock held by *fd* by closing it."""
    try:
        os.close(fd)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Path safety verification (R-011)
# ---------------------------------------------------------------------------


class UnsafePathError(RuntimeError):
    """Raised when a required path's mode/owner does not meet FR-011."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"unsafe path {path}: {reason}")
        self.path = path
        self.reason = reason


def _check_mode_and_owner(path: Path, *, expected_mode: int, kind: str) -> None:
    try:
        st = path.lstat()
    except FileNotFoundError as exc:
        raise UnsafePathError(path, "missing") from exc

    actual_kind: str
    if stat.S_ISDIR(st.st_mode):
        actual_kind = "dir"
    elif stat.S_ISREG(st.st_mode):
        actual_kind = "file"
    elif stat.S_ISSOCK(st.st_mode):
        actual_kind = "socket"
    else:
        actual_kind = "other"

    if actual_kind != kind:
        raise UnsafePathError(path, f"expected {kind}, got {actual_kind}")
    if (st.st_mode & 0o777) != expected_mode:
        raise UnsafePathError(
            path, f"mode is {oct(st.st_mode & 0o777)}, expected {oct(expected_mode)}"
        )
    if st.st_uid != os.geteuid():
        raise UnsafePathError(path, f"owned by uid {st.st_uid}, expected {os.geteuid()}")


def assert_paths_safe(
    *,
    state_dir: Path,
    logs_dir: Path,
    lock_file: Path | None = None,
    pid_file: Path | None = None,
    log_file: Path | None = None,
) -> None:
    """Verify host-user-only modes and ownership for every FEAT-002 path.

    Raises :class:`UnsafePathError` on the first violation. Directories are
    expected at mode ``0700``; files (lock, pid, log) at ``0600``.
    """
    _check_mode_and_owner(state_dir, expected_mode=0o700, kind="dir")
    _check_mode_and_owner(logs_dir, expected_mode=0o700, kind="dir")
    if lock_file is not None and lock_file.exists():
        _check_mode_and_owner(lock_file, expected_mode=0o600, kind="file")
    if pid_file is not None and pid_file.exists():
        _check_mode_and_owner(pid_file, expected_mode=0o600, kind="file")
    if log_file is not None and log_file.exists():
        _check_mode_and_owner(log_file, expected_mode=0o600, kind="file")


# ---------------------------------------------------------------------------
# Pid file
# ---------------------------------------------------------------------------


def write_pid_file(path: Path, pid: int) -> None:
    """Write *pid* to *path* with mode ``0600`` (atomic best-effort)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC, 0o600)
    try:
        os.write(fd, f"{int(pid)}\n".encode("ascii"))
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def read_pid_file(path: Path) -> int | None:
    """Return the pid recorded in *path*, or ``None`` if absent or malformed."""
    try:
        text = path.read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    text = text.strip()
    if not text or not text.isdigit():
        return None
    return int(text)


def remove_pid_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Lifecycle log (R-012)
# ---------------------------------------------------------------------------


# Closed event-token set in FEAT-002.
EVENT_DAEMON_STARTING = "daemon_starting"
EVENT_DAEMON_READY = "daemon_ready"
EVENT_DAEMON_RECOVERING = "daemon_recovering"
EVENT_DAEMON_SHUTDOWN = "daemon_shutdown"
EVENT_DAEMON_EXITED = "daemon_exited"
EVENT_ERROR_FATAL = "error_fatal"

# FEAT-003 additions (research R-015).
EVENT_SCAN_STARTED = "scan_started"
EVENT_SCAN_COMPLETED = "scan_completed"
EVENT_SCAN_JSONL_FAILED = "scan_jsonl_failed"

# FEAT-004 additions (R-014). Distinct from FEAT-003 tokens so operators
# can grep them apart.
EVENT_PANE_SCAN_STARTED = "pane_scan_started"
EVENT_PANE_SCAN_COMPLETED = "pane_scan_completed"
EVENT_PANE_SCAN_JSONL_FAILED = "pane_scan_jsonl_failed"

LIFECYCLE_EVENTS: frozenset[str] = frozenset(
    {
        EVENT_DAEMON_STARTING,
        EVENT_DAEMON_READY,
        EVENT_DAEMON_RECOVERING,
        EVENT_DAEMON_SHUTDOWN,
        EVENT_DAEMON_EXITED,
        EVENT_ERROR_FATAL,
        EVENT_SCAN_STARTED,
        EVENT_SCAN_COMPLETED,
        EVENT_SCAN_JSONL_FAILED,
        EVENT_PANE_SCAN_STARTED,
        EVENT_PANE_SCAN_COMPLETED,
        EVENT_PANE_SCAN_JSONL_FAILED,
    }
)


def _format_kv(items: Iterable[tuple[str, object]]) -> str:
    parts: list[str] = []
    for key, value in items:
        text = str(value)
        # Tab-separated; collapse internal tabs/newlines defensively.
        text = text.replace("\t", " ").replace("\n", " ")
        parts.append(f"{key}={text}")
    return "\t".join(parts)


class LifecycleLogger:
    """Append-only TSV writer for the FEAT-002 daemon lifecycle log."""

    def __init__(self, log_path: Path) -> None:
        self._path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Open append, line-buffered, mode 0600 enforced post-open.
        fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC, 0o600)
        # Best-effort tighten if file pre-existed with broader mode.
        try:
            st = os.fstat(fd)
            if (st.st_mode & 0o777) != 0o600:
                os.chmod(log_path, 0o600)
        except OSError:
            pass
        self._stream: io.TextIOBase = io.TextIOWrapper(
            os.fdopen(fd, "ab", buffering=0), encoding="utf-8", line_buffering=True
        )

    @property
    def path(self) -> Path:
        return self._path

    def emit(self, event: str, *, level: str = "info", **fields: object) -> None:
        """Append one TSV line for *event* with optional ``key=value`` fields."""
        if event not in LIFECYCLE_EVENTS:
            raise ValueError(f"unknown lifecycle event: {event!r}")
        if level not in ("info", "warn", "error", "fatal"):
            raise ValueError(f"unknown lifecycle level: {level!r}")
        ts = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        head = f"{ts}\tlevel={level}\tevent={event}"
        tail = _format_kv(fields.items())
        line = head if not tail else f"{head}\t{tail}"
        self._stream.write(line + "\n")

    def close(self) -> None:
        try:
            self._stream.flush()
        except OSError:
            pass
        self._stream.close()


# ---------------------------------------------------------------------------
# Stale-artifact classification & recovery (US3 / T024)
#
# Per research R-002 / R-004: the lock is the authority. Once we hold
# ``LOCK_EX``, no live daemon can be using the socket; any pre-existing
# inode at the socket path is safe to classify and (if it's a socket)
# unlink. Anything else (regular file, dir, symlink, FIFO) is *refused*
# rather than removed (FR-009).
# ---------------------------------------------------------------------------


class StaleArtifactRefused(RuntimeError):
    """Raised when the socket path holds a non-socket artifact."""

    def __init__(self, path: Path, kind: str) -> None:
        super().__init__(f"refusing to remove {kind} at socket path: {path}")
        self.path = path
        self.kind = kind


def classify_socket_path(path: Path) -> str:
    """Return one of ``"missing"``, ``"stale_socket"``, or ``"refuse"``.

    The caller MUST be holding ``LOCK_EX`` on the lifecycle lock before
    interpreting the result as authoritative.
    """
    try:
        st = path.lstat()
    except FileNotFoundError:
        return "missing"

    mode = st.st_mode
    if stat.S_ISSOCK(mode):
        return "stale_socket"
    return "refuse"


def _kind_label(path: Path) -> str:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return "missing"
    mode = st.st_mode
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "regular file"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
        return "device"
    if stat.S_ISSOCK(mode):
        return "socket"
    return "other"


def recover_stale_artifacts(
    *,
    socket_path: Path,
    pid_path: Path,
    logger: "LifecycleLogger | None" = None,
) -> None:
    """Unlink stale socket/pid artifacts under the held lock; refuse foreign paths.

    ``socket_path``: classified via :func:`classify_socket_path`. ``"stale_socket"``
    is unlinked; ``"refuse"`` raises :class:`StaleArtifactRefused`; ``"missing"``
    is a no-op.

    ``pid_path``: a stale pid file (left by a previously-crashed daemon) is
    always safe to unlink while we hold the lock.
    """
    cls = classify_socket_path(socket_path)
    if cls == "refuse":
        raise StaleArtifactRefused(socket_path, _kind_label(socket_path))
    if cls == "stale_socket":
        socket_path.unlink()
        if logger is not None:
            logger.emit(
                EVENT_DAEMON_RECOVERING,
                unlinked=str(socket_path),
                reason="stale_socket",
            )

    if pid_path.exists():
        pid_path.unlink()
        if logger is not None:
            logger.emit(
                EVENT_DAEMON_RECOVERING,
                unlinked=str(pid_path),
                reason="stale_pid",
            )
