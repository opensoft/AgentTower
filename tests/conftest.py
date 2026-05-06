"""Session-level guard: FEAT-003 must never invoke a real `docker` binary.

This fixture is autouse + session-scoped so every test in the suite runs
under the guard. The integration suite supplements this with a named test
(`tests/integration/test_cli_scan_no_real_docker.py`) for SC-007 traceability.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator

import pytest

_REAL_DOCKER_FORBIDDEN = (
    "FEAT-003 tests must not invoke the real `docker` binary. "
    "Set AGENTTOWER_TEST_DOCKER_FAKE to a fixture path or use FakeDockerAdapter."
)


def _argv0_is_docker(args: object) -> bool:
    if isinstance(args, (list, tuple)) and args:
        first = args[0]
        return isinstance(first, str) and os.path.basename(first) == "docker"
    if isinstance(args, str):
        return os.path.basename(args.split()[0]) == "docker" if args else False
    return False


@pytest.fixture(autouse=True, scope="session")
def _no_real_docker() -> Iterator[None]:
    real_run = subprocess.run
    real_popen = subprocess.Popen
    real_which = shutil.which

    def guarded_run(args, *a, **kw):  # type: ignore[no-untyped-def]
        if _argv0_is_docker(args):
            raise RuntimeError(_REAL_DOCKER_FORBIDDEN)
        return real_run(args, *a, **kw)

    def guarded_popen(args, *a, **kw):  # type: ignore[no-untyped-def]
        if _argv0_is_docker(args):
            raise RuntimeError(_REAL_DOCKER_FORBIDDEN)
        return real_popen(args, *a, **kw)

    def guarded_which(name, *a, **kw):  # type: ignore[no-untyped-def]
        if name == "docker":
            return None
        return real_which(name, *a, **kw)

    subprocess.run = guarded_run  # type: ignore[assignment]
    subprocess.Popen = guarded_popen  # type: ignore[assignment]
    shutil.which = guarded_which  # type: ignore[assignment]
    try:
        yield
    finally:
        subprocess.run = real_run  # type: ignore[assignment]
        subprocess.Popen = real_popen  # type: ignore[assignment]
        shutil.which = real_which  # type: ignore[assignment]
