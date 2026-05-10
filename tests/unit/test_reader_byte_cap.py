"""T035 — FR-019: per-cycle byte cap.

The reader caps bytes read per attachment per cycle at
``PER_CYCLE_BYTE_CAP_BYTES``; any excess remains on disk and is
processed on the next cycle.
"""

from __future__ import annotations

from pathlib import Path

from agenttower.events.reader import EventsReader


def test_read_bytes_honors_cap(tmp_path: Path) -> None:
    """Direct test of the reader's byte-read primitive."""
    log = tmp_path / "log.txt"
    payload = b"x" * 10_000
    log.write_bytes(payload)

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    out = reader._read_bytes(log, byte_offset=0, cap=4096)
    assert len(out) == 4096
    assert out == payload[:4096]


def test_read_bytes_advances_to_offset(tmp_path: Path) -> None:
    """Reading from a non-zero offset returns bytes starting from that
    position."""
    log = tmp_path / "log.txt"
    log.write_bytes(b"abcdefghij")

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    out = reader._read_bytes(log, byte_offset=3, cap=4)
    assert out == b"defg"


def test_read_bytes_returns_empty_at_eof(tmp_path: Path) -> None:
    log = tmp_path / "log.txt"
    log.write_bytes(b"hello")

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    out = reader._read_bytes(log, byte_offset=5, cap=4096)
    assert out == b""


def test_read_bytes_returns_only_available(tmp_path: Path) -> None:
    """If only N bytes are available and cap > N, return N bytes
    (remainder will appear next cycle once written)."""
    log = tmp_path / "log.txt"
    log.write_bytes(b"hello")  # 5 bytes

    reader = EventsReader(
        state_db=tmp_path / "state.sqlite3",
        events_file=tmp_path / "events.jsonl",
        lifecycle_logger=None,
    )

    out = reader._read_bytes(log, byte_offset=0, cap=4096)
    assert out == b"hello"
