"""Unit tests for FEAT-007 ``detect_file_change`` (T180 / FR-024 / FR-025 / FR-026).

The classifier walks the host log file and returns one of
``unchanged | truncated | recreated | missing`` based on the supplied
stored ``file_inode`` and ``file_size_seen``. It is consumed by the
FEAT-008 reader cycle (T181) and is also the canonical helper for the
FR-021 file-consistency check inside ``LogService.attach_log``.

Tests that need control over the observed inode use the FR-060
``AGENTTOWER_TEST_LOG_FS_FAKE`` seam (some filesystems, including the
WSL tmpfs used in CI, reuse inodes on unlink+recreate so naive real-fs
tests would be flaky).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agenttower.logs import host_fs
from agenttower.state.log_offsets import FileChangeKind, detect_file_change


def _inode_of(path: Path) -> str:
    st = os.stat(str(path), follow_symlinks=False)
    return f"{st.st_dev}:{st.st_ino}"


@pytest.fixture
def fs_fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide a controllable fake fs so tests can assert exact inode behavior."""
    fake_path = tmp_path / "fs_fake.json"

    def write(entries: dict[str, dict | None]) -> None:
        sanitized = {k: v for k, v in entries.items() if v is not None}
        fake_path.write_text(json.dumps(sanitized))
        host_fs._reset_for_test()

    write({})
    monkeypatch.setenv("AGENTTOWER_TEST_LOG_FS_FAKE", str(fake_path))
    host_fs._reset_for_test()
    yield write
    host_fs._reset_for_test()


class TestMissing:
    def test_missing_file_returns_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "absent.log"
        kind = detect_file_change(
            str(path), stored_inode="234:1234567", stored_size_seen=8192
        )
        assert kind is FileChangeKind.MISSING

    def test_missing_file_with_no_stored_inode_still_missing(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "absent.log"
        kind = detect_file_change(
            str(path), stored_inode=None, stored_size_seen=0
        )
        assert kind is FileChangeKind.MISSING


class TestUnchanged:
    def test_first_observation_with_no_stored_inode_is_unchanged(
        self, tmp_path: Path
    ) -> None:
        """Row was just attached; file_inode is NULL and file_size_seen is 0.

        The first reader cycle observes the real file but MUST NOT classify
        this as a rotation. The cycle records the observation through
        ``update_file_observation``; subsequent cycles compare against it.
        """
        path = tmp_path / "fresh.log"
        path.write_bytes(b"hello\n")
        kind = detect_file_change(
            str(path), stored_inode=None, stored_size_seen=0
        )
        assert kind is FileChangeKind.UNCHANGED

    def test_unchanged_when_inode_and_size_match(self, tmp_path: Path) -> None:
        path = tmp_path / "stable.log"
        path.write_bytes(b"x" * 4096)
        kind = detect_file_change(
            str(path), stored_inode=_inode_of(path), stored_size_seen=4096
        )
        assert kind is FileChangeKind.UNCHANGED

    def test_unchanged_when_file_grew_with_same_inode(self, tmp_path: Path) -> None:
        path = tmp_path / "grew.log"
        path.write_bytes(b"x" * 4096)
        inode = _inode_of(path)
        # File grows after the stored observation — that's normal forward
        # progress, not a rotation.
        with open(path, "ab") as f:
            f.write(b"y" * 4096)
        kind = detect_file_change(
            str(path), stored_inode=inode, stored_size_seen=4096
        )
        assert kind is FileChangeKind.UNCHANGED


class TestTruncated:
    def test_truncated_to_zero(self, tmp_path: Path) -> None:
        path = tmp_path / "truncated.log"
        path.write_bytes(b"x" * 8192)
        inode = _inode_of(path)
        # Truncate in place — same inode, size shrinks.
        with open(path, "wb"):
            pass
        kind = detect_file_change(
            str(path), stored_inode=inode, stored_size_seen=8192
        )
        assert kind is FileChangeKind.TRUNCATED

    def test_truncated_smaller_but_nonzero(self, tmp_path: Path) -> None:
        path = tmp_path / "shrunk.log"
        path.write_bytes(b"x" * 8192)
        inode = _inode_of(path)
        with open(path, "wb") as f:
            f.write(b"x" * 1024)
        kind = detect_file_change(
            str(path), stored_inode=inode, stored_size_seen=8192
        )
        assert kind is FileChangeKind.TRUNCATED


class TestRecreated:
    def test_recreated_with_different_inode(self, fs_fake) -> None:
        fs_fake({
            "/host/log/x.log": {"exists": True, "inode": "234:7654321", "size": 4096},
        })
        kind = detect_file_change(
            "/host/log/x.log", stored_inode="234:1234567", stored_size_seen=4096
        )
        assert kind is FileChangeKind.RECREATED

    def test_recreated_smaller_does_not_classify_as_truncated(self, fs_fake) -> None:
        """Recreation wins over truncation when both apply (different inode).

        Order matters: an inode mismatch is always RECREATED even if the
        new file happens to be smaller than the stored size.
        """
        fs_fake({
            "/host/log/x.log": {"exists": True, "inode": "234:7654321", "size": 1024},
        })
        kind = detect_file_change(
            "/host/log/x.log", stored_inode="234:1234567", stored_size_seen=8192
        )
        assert kind is FileChangeKind.RECREATED


class TestEnumStability:
    def test_kind_values_are_lowercase_strings(self) -> None:
        # FileChangeKind is a str enum so callers can JSON-serialize directly.
        assert FileChangeKind.UNCHANGED.value == "unchanged"
        assert FileChangeKind.TRUNCATED.value == "truncated"
        assert FileChangeKind.RECREATED.value == "recreated"
        assert FileChangeKind.MISSING.value == "missing"

    def test_kind_set_is_closed(self) -> None:
        assert {k.value for k in FileChangeKind} == {
            "unchanged",
            "truncated",
            "recreated",
            "missing",
        }
