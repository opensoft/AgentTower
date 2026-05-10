"""T034 — FR-005: partial trailing bytes are NOT consumed.

A cycle ending on a partial line emits zero events; the next cycle
re-reads from the partial-line offset and emits exactly one event
once the newline arrives.
"""

from __future__ import annotations

from agenttower.events.reader import _split_complete_records


def test_complete_record_one_line() -> None:
    raw = b"hello\n"
    records, advance, lines = _split_complete_records(raw)
    assert records == [b"hello"]
    assert advance == 6  # len("hello") + 1 for \n
    assert lines == 1


def test_partial_trailing_bytes_returned_empty() -> None:
    raw = b"hello"  # no terminating newline
    records, advance, lines = _split_complete_records(raw)
    assert records == []
    assert advance == 0
    assert lines == 0


def test_complete_then_partial() -> None:
    raw = b"hello\nworld"  # one full line + partial
    records, advance, lines = _split_complete_records(raw)
    assert records == [b"hello"]
    assert advance == 6  # only the bytes through the \n consumed
    assert lines == 1


def test_two_complete_records() -> None:
    raw = b"a\nb\n"
    records, advance, lines = _split_complete_records(raw)
    assert records == [b"a", b"b"]
    assert advance == 4
    assert lines == 2


def test_empty_input() -> None:
    records, advance, lines = _split_complete_records(b"")
    assert records == []
    assert advance == 0
    assert lines == 0


def test_only_newlines() -> None:
    """Three consecutive newlines = three complete empty records."""
    raw = b"\n\n\n"
    records, advance, lines = _split_complete_records(raw)
    assert records == [b"", b"", b""]
    assert advance == 3
    assert lines == 3


def test_partial_carryover_followed_by_completion() -> None:
    """Cycle 1 reads "hel" — no records, advance=0. Cycle 2 reads
    "hello\\n" (the original "hel" plus new "lo\\n" appended) and
    finds one complete record. Models FR-005's carry-over."""
    cycle1, advance1, lines1 = _split_complete_records(b"hel")
    assert cycle1 == [] and advance1 == 0 and lines1 == 0
    cycle2, advance2, lines2 = _split_complete_records(b"hello\n")
    assert cycle2 == [b"hello"]
    assert advance2 == 6
    assert lines2 == 1
