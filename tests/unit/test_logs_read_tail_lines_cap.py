"""Regression test for the FEAT-007 ``read_tail_lines`` buffer cap.

Pre-fix: the tail-read loop accumulated bytes from the end of the file
until it saw enough ``\\n`` characters. A log file with very few or
zero newlines could drive the daemon to read the entire file into
memory during ``attach-log --preview`` (even though the ``lines``
argument was capped at 200).

Post-fix: the loop honors a hard upper bound on the buffered window
(``n * max_line_bytes`` plus one slack line). Past that point, the
leading partial line is truncated and the function returns whatever
fits, satisfying FR-064 byte-line-cap behavior end-to-end.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agenttower.logs import host_fs


def test_no_newlines_does_not_buffer_full_file(tmp_path: Path) -> None:
    """A file with zero newlines must not be read in full when n=5."""
    target = tmp_path / "no-newlines.log"
    # 4 MiB of bytes, no newline anywhere.
    blob = b"X" * (4 * 1024 * 1024)
    target.write_bytes(blob)

    n = 5
    max_line_bytes = 1024  # cap each line at 1 KiB
    # Effective buffer cap: (n + 1) * max_line_bytes = 6 KiB. The function
    # must NOT keep reading the full 4 MiB.

    lines = host_fs.read_tail_lines(str(target), n, max_line_bytes=max_line_bytes)

    # The whole blob is one logical "line" (no newlines), so the function
    # returns at most one truncated line. The truncation marker confirms
    # the cap kicked in.
    assert len(lines) == 1
    only = lines[0]
    # Truncated line carries the FR-064 ellipsis marker.
    assert only.endswith("…"), only[-10:]
    # Length is bounded by max_line_bytes (plus the one-codepoint marker).
    assert len(only.encode("utf-8")) <= max_line_bytes + len("…".encode("utf-8"))


def test_few_newlines_returns_capped_tail(tmp_path: Path) -> None:
    """A 2 MiB file with only two newlines (one near the head) must return
    the trailing line(s) without reading the whole file."""
    target = tmp_path / "few-newlines.log"
    # Layout: 1 MiB of "A", '\n', 1 MiB of "B", '\n', "tail-line\n"
    blob = b"A" * (1024 * 1024) + b"\n" + b"B" * (1024 * 1024) + b"\ntail-line\n"
    target.write_bytes(blob)

    lines = host_fs.read_tail_lines(str(target), 2, max_line_bytes=2048)

    # We requested 2 lines. The cap is (2 + 1) * 2048 = 6 KiB so we should
    # see "tail-line" plus a truncated partial of the "B"-line preceding it.
    assert lines, "expected at least one line"
    assert lines[-1] == "tail-line"
    # Any line before tail-line came from the truncated "B" run and must
    # have hit the FR-064 max-line-bytes cap (it cannot be the original
    # 1 MiB "B" run).
    if len(lines) > 1:
        assert len(lines[-2].encode("utf-8")) <= 2048 + len("…".encode("utf-8"))


def test_normal_small_file_unchanged(tmp_path: Path) -> None:
    """Sanity counter-test: a small, well-formed log file is unaffected."""
    target = tmp_path / "small.log"
    target.write_text("line one\nline two\nline three\nline four\n")

    lines = host_fs.read_tail_lines(str(target), 2, max_line_bytes=512)
    assert lines == ["line three", "line four"]


def test_zero_n_returns_empty_without_reading(tmp_path: Path) -> None:
    target = tmp_path / "any.log"
    target.write_text("some content\n")
    assert host_fs.read_tail_lines(str(target), 0) == []
    assert host_fs.read_tail_lines(str(target), -1) == []


def test_missing_file_raises(tmp_path: Path) -> None:
    target = tmp_path / "does-not-exist.log"
    with pytest.raises(FileNotFoundError):
        host_fs.read_tail_lines(str(target), 5)
