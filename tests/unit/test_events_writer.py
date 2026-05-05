from __future__ import annotations

import json
import os
import re
import stat
import threading
from pathlib import Path

import pytest

from agenttower.events.writer import append_event

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00$")


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_single_append_produces_one_line(tmp_path: Path) -> None:
    events_file = tmp_path / "opensoft/agenttower/events.jsonl"
    append_event(events_file, {"event_type": "smoke", "n": 1})

    text = events_file.read_text()
    assert text.endswith("\n")
    lines = text.splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event_type"] == "smoke"
    assert record["n"] == 1
    assert "ts" in record


def test_ts_matches_iso_microsecond_utc_regex(tmp_path: Path) -> None:
    events_file = tmp_path / "opensoft/agenttower/events.jsonl"
    append_event(events_file, {})
    record = json.loads(events_file.read_text().splitlines()[0])
    assert _TS_RE.match(record["ts"]), record["ts"]


def test_caller_supplied_ts_overrides_writer(tmp_path: Path) -> None:
    events_file = tmp_path / "opensoft/agenttower/events.jsonl"
    append_event(events_file, {"ts": "carrier-supplied"})
    record = json.loads(events_file.read_text().splitlines()[0])
    assert record["ts"] == "carrier-supplied"


def test_file_created_with_mode_0600(tmp_path: Path) -> None:
    events_file = tmp_path / "opensoft/agenttower/events.jsonl"
    append_event(events_file, {"k": 1})
    assert _mode(events_file) == 0o600


def test_file_mode_0600_under_permissive_umask(tmp_path: Path) -> None:
    events_file = tmp_path / "opensoft/agenttower/events.jsonl"
    old = os.umask(0o022)  # NOSONAR - intentionally broad umask fixture.
    try:
        append_event(events_file, {"k": 1})
    finally:
        os.umask(old)
    assert _mode(events_file) == 0o600


def test_parent_chain_created_with_mode_0700(tmp_path: Path) -> None:
    deep = tmp_path / "a/b/c/agenttower/events.jsonl"
    append_event(deep, {"k": 1})
    for ancestor in (deep.parent, deep.parent.parent, deep.parent.parent.parent):
        assert ancestor.is_dir(), ancestor
        assert _mode(ancestor) == 0o700, f"{ancestor}: {oct(_mode(ancestor))}"


def test_concurrent_100_threads_produce_100_distinct_lines(tmp_path: Path) -> None:
    events_file = tmp_path / "opensoft/agenttower/events.jsonl"
    threads: list[threading.Thread] = []
    for i in range(100):
        t = threading.Thread(target=append_event, args=(events_file, {"i": i}))
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = events_file.read_text().splitlines()
    assert len(lines) == 100
    decoded = [json.loads(line) for line in lines]
    seen = sorted(record["i"] for record in decoded)
    assert seen == list(range(100))


def test_append_only_preserves_existing_lines(tmp_path: Path) -> None:
    events_file = tmp_path / "opensoft/agenttower/events.jsonl"
    append_event(events_file, {"k": 1})
    first_line = events_file.read_text()
    append_event(events_file, {"k": 2})
    second = events_file.read_text()
    assert second.startswith(first_line)
    lines = second.splitlines()
    assert len(lines) == 2


def test_pre_existing_file_with_broader_mode_raises_oserror(tmp_path: Path) -> None:
    events_file = tmp_path / "opensoft/agenttower/events.jsonl"
    events_file.parent.mkdir(parents=True, mode=0o700)
    os.chmod(events_file.parent, 0o700)
    events_file.write_text("# pre-existing\n")
    os.chmod(events_file, 0o644)  # NOSONAR - intentionally unsafe mode fixture.
    original = events_file.read_bytes()

    with pytest.raises(OSError):
        append_event(events_file, {"k": 1})

    assert events_file.read_bytes() == original
    assert _mode(events_file) == 0o644


def test_oserror_propagates_from_readonly_parent(tmp_path: Path) -> None:
    parent = tmp_path / "opensoft/agenttower"
    parent.mkdir(parents=True, mode=0o700)
    os.chmod(parent, 0o500)
    events_file = parent / "events.jsonl"
    try:
        with pytest.raises(OSError):
            append_event(events_file, {"k": 1})
    finally:
        os.chmod(parent, 0o700)
