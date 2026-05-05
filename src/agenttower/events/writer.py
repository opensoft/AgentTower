"""JSONL append-only event-writer utility for AgentTower."""

from __future__ import annotations

import datetime as _dt
import errno
import json
import os
import stat
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_FILE_MODE = 0o600
_DIR_MODE = 0o700

_lock = threading.Lock()


def _verify_dir_mode(path: Path) -> None:
    actual = stat.S_IMODE(os.stat(path).st_mode)
    if actual & ~_DIR_MODE:
        raise OSError(
            errno.EPERM,
            f"directory mode {oct(actual)} broader than required {oct(_DIR_MODE)}",
            str(path),
        )


def _verify_file_mode(path: Path) -> None:
    actual = stat.S_IMODE(os.stat(path).st_mode)
    if actual & ~_FILE_MODE:
        raise OSError(
            errno.EPERM,
            f"file mode {oct(actual)} broader than required {oct(_FILE_MODE)}",
            str(path),
        )


def _ensure_parent(events_file: Path) -> None:
    parent = events_file.parent
    if parent.exists():
        _verify_dir_mode(parent)
        return

    missing: list[Path] = []
    cursor = parent
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if cursor.exists():
        # We won't validate cursor's mode — it's outside what this writer
        # is creating. The caller's resolved namespace is the unit of policy.
        pass

    for path in reversed(missing):
        path.mkdir(mode=_DIR_MODE, exist_ok=False)
        os.chmod(path, _DIR_MODE)


def append_event(events_file: Path, payload: Mapping[str, Any]) -> None:
    """Append a single JSON-encoded record to *events_file*.

    Behavior is governed by ``contracts/event-writer.md`` C-EVT-001..004.
    Raises ``OSError`` on filesystem errors or on a pre-existing file/dir
    with broader-than-required mode (FR-015).
    """
    record: dict[str, Any] = {
        "ts": _dt.datetime.now(_dt.UTC).isoformat(timespec="microseconds"),
    }
    record.update(payload)
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    payload_bytes = (line + "\n").encode("utf-8")

    with _lock:
        _ensure_parent(events_file)

        pre_existed = events_file.exists()
        if pre_existed:
            _verify_file_mode(events_file)

        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(events_file, flags, _FILE_MODE)
        try:
            if not pre_existed:
                os.fchmod(fd, _FILE_MODE)
            os.write(fd, payload_bytes)
            os.fsync(fd)
        finally:
            os.close(fd)
