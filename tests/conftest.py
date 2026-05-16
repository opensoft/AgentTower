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


@pytest.fixture(autouse=True)
def _reset_feat007_lifecycle_suppression() -> Iterator[None]:
    """Reset the FEAT-007 lifecycle suppression registry between tests.

    The suppression state is module-global (data-model.md §3.6) and survives
    across test boundaries within the same process. Without this fixture,
    a test that emits ``log_file_returned`` for triple ``(A, P, I)`` would
    silently suppress the same triple in a later test that reuses the
    same ids — leading to flaky cross-test behavior. Resetting between
    tests mirrors the daemon-restart semantics the spec already documents.
    """
    from agenttower.logs import lifecycle as logs_lifecycle

    logs_lifecycle.reset_for_test()
    yield
    logs_lifecycle.reset_for_test()


# FEAT-008 — register the two new test seams from plan.md §R10. Both
# are env-var driven (mirrors the FEAT-007 ``AGENTTOWER_TEST_LOG_FS_FAKE``
# pattern). The FEAT-008 reader honors them only when the AGENTTOWER_*
# env var is set; the AST gate at
# ``tests/unit/test_logs_offset_advance_invariant.py`` enforces that no
# production module imports the seam names.

#: T102 — path to a JSON file containing
#: ``{"observed_at_iso": <ISO>, "monotonic": <float>}``, consumed by the
#: reader's ``Clock`` Protocol so debounce windows, ``pane_exited`` grace,
#: and ``long_running`` grace are deterministic in tests without real-time
#: ``time.sleep`` calls.
AGENTTOWER_TEST_EVENTS_CLOCK_FAKE = "AGENTTOWER_TEST_EVENTS_CLOCK_FAKE"

#: T003 — Unix-domain-socket path. When set, the reader replaces its
#: inter-cycle ``Event.wait()`` with a ``socket.recv`` on this path.
#: Tests write one byte to advance the reader by exactly one cycle.
AGENTTOWER_TEST_READER_TICK = "AGENTTOWER_TEST_READER_TICK"


# FEAT-009 — register the two new test seams from plan.md §"Test seams".
# Both are env-var driven (mirrors the FEAT-007 / FEAT-008 pattern).
# Production callers MUST NOT read these names; the FEAT-009 AST gate at
# ``tests/unit/test_no_shell_string_interpolation.py`` plus a follow-on
# test-seam-name scan in the Phase 9 polish slice keep them out of
# production code. Both are no-ops when unset.

#: T053 — inline JSON value of the form
#: ``{"now_iso_ms_utc": <ISO>, "monotonic": <float>}``, consumed by the
#: ``routing.timestamps.Clock`` Protocol so delivery-attempt timing and
#: ``observed_at`` audit timestamps are deterministic in tests without
#: real-time ``time.sleep`` calls. The env var holds the JSON content
#: directly (not a path to a JSON file); see
#: ``routing.timestamps.load_clock_from_env``.
AGENTTOWER_TEST_ROUTING_CLOCK_FAKE = "AGENTTOWER_TEST_ROUTING_CLOCK_FAKE"

#: T053 — Unix-domain-socket path. When set, the delivery worker replaces
#: its inter-cycle wakeup poll with a ``socket.recv`` on this path. Tests
#: write one byte to advance the worker by exactly one cycle.
AGENTTOWER_TEST_DELIVERY_TICK = "AGENTTOWER_TEST_DELIVERY_TICK"


@pytest.fixture(autouse=True)
def _isolate_test_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Ensure the FEAT-008 and FEAT-009 test seams start unset for every test.

    Tests that need a seam set it explicitly via ``monkeypatch.setenv``
    inside the test body. This prevents a value leaking across tests.
    """
    monkeypatch.delenv(AGENTTOWER_TEST_EVENTS_CLOCK_FAKE, raising=False)
    monkeypatch.delenv(AGENTTOWER_TEST_READER_TICK, raising=False)
    monkeypatch.delenv(AGENTTOWER_TEST_ROUTING_CLOCK_FAKE, raising=False)
    monkeypatch.delenv(AGENTTOWER_TEST_DELIVERY_TICK, raising=False)
    yield
