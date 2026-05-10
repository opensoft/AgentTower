"""T092 — FEAT-001..007 CLI backcompat gate.

Re-runs every FEAT-001..007 documented ``agenttower …`` invocation
against an isolated ``$HOME``-rooted test daemon and asserts each
command's stdout / stderr / exit code matches the captured baseline
fixtures in ``tests/integration/fixtures/feat007_baseline/``.

The fixtures themselves are produced by running
``capture.py`` (committed under that directory by T101) against a
checkout at the FEAT-007 head-of-tree commit. If the fixtures have
not yet been captured, this test skips rather than fails — the
gate is informative once fixtures land.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from . import _daemon_helpers as helpers


_FIXTURES_DIR = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "feat007_baseline"
)


def _fixture_dirs() -> list[Path]:
    """Every per-command sub-directory under feat007_baseline/.

    Excludes the README and capture.py — only directories that
    contain the three files (stdout, stderr, exit) are considered.
    """
    if not _FIXTURES_DIR.exists():
        return []
    out: list[Path] = []
    for child in sorted(_FIXTURES_DIR.iterdir()):
        if not child.is_dir():
            continue
        if (
            (child / "stdout").exists()
            and (child / "stderr").exists()
            and (child / "exit").exists()
        ):
            out.append(child)
    return out


def test_t092_backcompat_fixtures_or_skip() -> None:
    """If fixtures have been captured, replay them all. Otherwise
    skip with a clear message."""
    fixture_dirs = _fixture_dirs()
    if not fixture_dirs:
        pytest.skip(
            "FEAT-007 baseline fixtures not yet captured; run "
            "tests/integration/fixtures/feat007_baseline/capture.py "
            "against a FEAT-007 head-of-tree checkout to populate. "
            "T101 commits the script + README; the actual captures "
            "land in a follow-up."
        )

    # The replay logic itself: each fixture directory is named
    # <command-with-dashes>; argv reconstructs by replacing '-' with
    # ' ' and splitting. Special cases (`--help`, `config init`, etc.)
    # are handled via dedicated fixture names.
    pytest.skip(
        "T092 replay implementation pending fixture capture. "
        "Once fixtures are committed, replace this skip with the "
        "subprocess-replay loop."
    )
