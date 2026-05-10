"""FEAT-008 T101 — capture FEAT-007 baseline CLI fixtures.

Run this once, against a checkout at the FEAT-007 head-of-tree (before
any FEAT-008 production code lands), to produce the byte-identical
stdout/stderr/exit-code fixtures consumed by
``tests/integration/test_feat008_backcompat.py``.

Re-running overwrites the captures. See ``README.md`` for the full
procedure.

Usage::

    git checkout <FEAT-007 commit> -- src/agenttower
    python tests/integration/fixtures/feat007_baseline/capture.py
    git checkout HEAD -- src/agenttower
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


_FIXTURES_DIR = Path(__file__).resolve().parent


# The FEAT-001..FEAT-007 CLI surface. Each entry is
# ``(slug, [argv])`` where ``slug`` is the directory name. Argv is
# joined with ``agenttower …`` at invocation time; ``[]`` means the
# bare ``agenttower`` invocation (which prints usage).
#
# Commands that require a running daemon are invoked AFTER ``ensure-
# daemon`` lands one. Commands whose output depends on a registered
# agent are skipped here — they need a fully-driven flow that the
# integration suite exercises explicitly.
_CLI_SURFACE: list[tuple[str, list[str]]] = [
    ("help", ["--help"]),
    ("config-init", ["config", "init"]),
    ("config-paths", ["config", "paths"]),
    ("config-paths--json", ["config", "paths", "--json"]),
    ("config-doctor", ["config", "doctor"]),
    ("config-doctor--json", ["config", "doctor", "--json"]),
    ("status", ["status"]),
    ("status--json", ["status", "--json"]),
    ("ensure-daemon", ["ensure-daemon"]),
    ("ensure-daemon--json", ["ensure-daemon", "--json"]),
    ("scan-containers", ["scan", "--containers"]),
    ("scan-containers--json", ["scan", "--containers", "--json"]),
    ("list-containers", ["list", "--containers"]),
    ("list-containers--json", ["list", "--containers", "--json"]),
    ("scan-panes", ["scan", "--panes"]),
    ("list-panes", ["list", "--panes"]),
    # FEAT-006 / FEAT-007 commands that don't require a registered agent
    # produce stable usage-style output without one. Agent-bound forms
    # are exercised in driven integration tests, not here.
]


def _isolated_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    bin_dir = os.path.dirname(sys.executable)
    env["PATH"] = os.pathsep.join((bin_dir, env.get("PATH", "")))
    for var in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        env.pop(var, None)
    return env


def _run(env: dict[str, str], argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["agenttower", *argv],
        env=env,
        capture_output=True,
        check=False,
    )


def _write_fixture(slug: str, result: subprocess.CompletedProcess[bytes]) -> None:
    out_dir = _FIXTURES_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stdout").write_bytes(result.stdout)
    (out_dir / "stderr").write_bytes(result.stderr)
    (out_dir / "exit").write_text(f"{result.returncode}\n", encoding="ascii")


def main() -> int:
    print(f"capturing FEAT-007 baseline fixtures into {_FIXTURES_DIR}")
    home = Path(tempfile.mkdtemp(prefix="agenttower-baseline-"))
    try:
        env = _isolated_env(home)
        for slug, argv in _CLI_SURFACE:
            print(f"  -> {slug}: agenttower {' '.join(argv)}")
            result = _run(env, argv)
            _write_fixture(slug, result)
    finally:
        # Best-effort daemon teardown.
        try:
            subprocess.run(
                ["agenttower", "stop"], env=_isolated_env(home), capture_output=True
            )
        except Exception:
            pass
        shutil.rmtree(home, ignore_errors=True)
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
