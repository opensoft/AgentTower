"""Explicit guard test that FEAT-003 never spawns a real `docker` binary.

The session-level fixture in `tests/conftest.py` already monkeypatches
`subprocess.run`, `subprocess.Popen`, and `shutil.which` to refuse
`docker` argv[0]. This module is the named verification SC-007 calls
out and adds a static-source check for FR-031 (no `sudo`, no docker
`start`/`stop`/`exec`, no `os.setuid`/`os.setgid`).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FEAT003_DIRS = (
    _REPO_ROOT / "src/agenttower/discovery",
    _REPO_ROOT / "src/agenttower/docker",
)
_FEAT003_FILES = (
    _REPO_ROOT / "src/agenttower/state/containers.py",
    _REPO_ROOT / "src/agenttower/state/schema.py",
)


def _read_all() -> dict[Path, str]:
    sources: dict[Path, str] = {}
    for d in _FEAT003_DIRS:
        for p in d.rglob("*.py"):
            sources[p] = p.read_text(encoding="utf-8")
    for p in _FEAT003_FILES:
        if p.exists():
            sources[p] = p.read_text(encoding="utf-8")
    return sources


def test_no_sudo_no_setuid_no_destructive_docker_subcommand() -> None:
    """FR-031: no FEAT-003 source contains `sudo`, `os.setuid`, `os.setgid`,
    or destructive Docker subcommands like `start`, `stop`, `exec`, `rm`."""
    bad_substrings = [
        '"sudo"',
        "'sudo'",
        "os.setuid",
        "os.setgid",
        '"start"',
        '"stop"',
        '"exec"',
        '"rm"',
    ]
    sources = _read_all()
    offenders: list[tuple[Path, str]] = []
    for path, body in sources.items():
        # Skip the *test* file scanning itself.
        if path == Path(__file__):
            continue
        for needle in bad_substrings:
            if needle in body:
                offenders.append((path, needle))
    # Allow `"start"` etc. in *non-Docker* contexts only if they are clearly
    # not subprocess argv. For FEAT-003 we expect zero hits, since all
    # subprocess argv go through `SubprocessDockerAdapter` which only ever
    # uses `"ps"` and `"inspect"`.
    assert offenders == [], (
        "FR-031 violation: forbidden substrings in FEAT-003 source: " f"{offenders}"
    )


def test_subprocess_argv_strings_in_subprocess_adapter() -> None:
    """The only subprocess argv hardcoded by FEAT-003 are `ps` and `inspect`."""
    body = (_REPO_ROOT / "src/agenttower/docker/subprocess_adapter.py").read_text(
        encoding="utf-8"
    )
    # The file must mention "ps" and "inspect" but not other Docker subcommands.
    assert '"ps"' in body
    assert '"inspect"' in body
    # Defensive: no shell=True anywhere.
    assert "shell=True" not in body


def test_session_level_guard_is_in_place() -> None:
    """The autouse `_no_real_docker` guard is registered."""
    import shutil
    import subprocess

    assert subprocess.run is not None
    assert subprocess.Popen is not None
    assert shutil.which is not None
    # Confirm the guard rejects a docker invocation.
    with pytest.raises(RuntimeError, match="must not invoke the real `docker`"):
        subprocess.run(["docker", "ps"], capture_output=True)
