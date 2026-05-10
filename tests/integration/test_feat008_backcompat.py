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

import subprocess
from pathlib import Path

import pytest

from . import _daemon_helpers as helpers


_FIXTURES_DIR = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "feat007_baseline"
)


_ARGV_BY_SLUG: dict[str, list[str]] = {
    "help": ["--help"],
    "config-init": ["config", "init"],
    "config-paths": ["config", "paths"],
    "config-paths--json": ["config", "paths", "--json"],
    "config-doctor": ["config", "doctor"],
    "config-doctor--json": ["config", "doctor", "--json"],
    "status": ["status"],
    "status--json": ["status", "--json"],
    "ensure-daemon": ["ensure-daemon"],
    "ensure-daemon--json": ["ensure-daemon", "--json"],
    "scan-containers": ["scan", "--containers"],
    "scan-containers--json": ["scan", "--containers", "--json"],
    "list-containers": ["list", "--containers"],
    "list-containers--json": ["list", "--containers", "--json"],
    "scan-panes": ["scan", "--panes"],
    "list-panes": ["list", "--panes"],
}


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


def test_t092_backcompat_fixtures_or_skip(tmp_path: Path) -> None:
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

    env = helpers.isolated_env(tmp_path / "home")
    try:
        for fixture_dir in fixture_dirs:
            argv = _ARGV_BY_SLUG.get(fixture_dir.name)
            assert argv is not None, (
                f"no replay argv mapping for fixture {fixture_dir.name!r}"
            )
            result = subprocess.run(
                ["agenttower", *argv],
                env=env,
                capture_output=True,
                timeout=20,
                check=False,
            )

            expected_returncode = int(
                (fixture_dir / "exit").read_text(encoding="ascii").strip()
            )
            assert result.returncode == expected_returncode, fixture_dir.name
            assert result.stdout == (fixture_dir / "stdout").read_bytes(), (
                fixture_dir.name
            )
            assert result.stderr == (fixture_dir / "stderr").read_bytes(), (
                fixture_dir.name
            )
    finally:
        helpers.stop_daemon_if_alive(env)
