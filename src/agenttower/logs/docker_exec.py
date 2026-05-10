"""FEAT-007 docker-exec runner adapter.

Wraps ``subprocess.run`` for the FEAT-007 ``tmux pipe-pane`` invocations
(attach, toggle-off, list-panes inspection). Production path uses
``SubprocessDockerExecRunner``; integration tests inject the
``FakeDockerExecRunner`` via the ``AGENTTOWER_TEST_PIPE_PANE_FAKE`` env
var (JSON fixture).

Test seam (FR-060): only this module reads ``AGENTTOWER_TEST_PIPE_PANE_FAKE``.
Production code paths invoke real ``subprocess.run``.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DockerExecResult:
    """Outcome of one docker-exec invocation.

    ``failure_kind`` (when set) carries the closed-set error code that
    callers should raise instead of the generic ``pipe_pane_failed``:

    * ``"docker_unavailable"`` — ``docker`` binary missing on PATH.
    * ``"docker_exec_timeout"`` — the call hit the timeout budget.

    ``None`` means "the subprocess invocation completed normally"; the
    caller still inspects ``returncode`` / ``stderr`` to decide whether
    the inner ``tmux`` command succeeded.
    """

    returncode: int
    stdout: str
    stderr: str
    failure_kind: str | None = None


class DockerExecRunner(Protocol):
    """Run a ``docker exec ...`` argv list and return the result."""

    def run(self, argv: list[str], *, timeout_seconds: float = 5.0) -> DockerExecResult:
        ...


class SubprocessDockerExecRunner:
    """Production runner — shells out via :func:`subprocess.run`.

    Translates docker-binary / timeout failures into the closed-set
    ``docker_unavailable`` / ``docker_exec_timeout`` codes via the
    :attr:`DockerExecResult.failure_kind` field so they don't masquerade
    as ``pipe_pane_failed`` downstream.
    """

    def run(
        self, argv: list[str], *, timeout_seconds: float = 5.0
    ) -> DockerExecResult:
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return DockerExecResult(
                returncode=124,
                stdout=exc.stdout or "",
                stderr=(exc.stderr or "") + "\ndocker exec timeout",
                failure_kind="docker_exec_timeout",
            )
        except FileNotFoundError as exc:
            return DockerExecResult(
                returncode=127,
                stdout="",
                stderr=f"docker exec not available: {exc}",
                failure_kind="docker_unavailable",
            )
        return DockerExecResult(
            returncode=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )


class FakeDockerExecRunner:
    """Integration-test fake. Loaded from ``AGENTTOWER_TEST_PIPE_PANE_FAKE``.

    Fixture JSON shape::

        {
          "calls": [
            {"argv_match": ["tmux", "pipe-pane", "-o"], "returncode": 0, "stdout": "", "stderr": ""},
            {"argv_match": ["tmux", "list-panes"], "returncode": 0, "stdout": "0 \n", "stderr": ""}
          ]
        }

    Each entry's ``argv_match`` is a substring list — every token in
    ``argv_match`` MUST appear (in order) somewhere in the joined argv
    string. The first matching entry wins.

    Recorded calls are exposed via ``recorded_argv`` for tests to assert
    the daemon issued the documented invocations.
    """

    def __init__(self, fixture: dict) -> None:
        self._fixture = fixture
        self._lock = threading.Lock()
        self.recorded_argv: list[list[str]] = []

    @classmethod
    def from_path(cls, path: str) -> "FakeDockerExecRunner":
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def run(
        self, argv: list[str], *, timeout_seconds: float = 5.0
    ) -> DockerExecResult:
        with self._lock:
            self.recorded_argv.append(list(argv))
        joined = " ".join(argv)
        for entry in self._fixture.get("calls", []):
            match_tokens = entry.get("argv_match", [])
            if not isinstance(match_tokens, list):
                continue
            cursor = 0
            ok = True
            for token in match_tokens:
                idx = joined.find(str(token), cursor)
                if idx < 0:
                    ok = False
                    break
                cursor = idx + len(str(token))
            if ok:
                # Optional side-effect: simulate the bench-side
                # ``cat >> file`` behavior, which opens for append + create
                # under the bench user's umask. Critically, if the file
                # already exists, ``cat >>`` does NOT change its mode; only
                # the create-from-missing case applies the umask-derived
                # mode. The fixture's ``mode`` value is the mode applied
                # IFF the daemon hasn't already created the file.
                #
                # We do NOT create the parent directory here. A real
                # ``cat >> /path/to/file`` inside the container would fail
                # with ``ENOENT`` if the parent doesn't exist; the daemon
                # is expected to ``mkdir`` it at FR-008 mode 0o700 BEFORE
                # issuing pipe-pane. Auto-creating it here would mask
                # regressions where the daemon forgets to pre-create.
                touch = entry.get("touch_path_with_mode")
                if isinstance(touch, dict):
                    target = touch.get("path")
                    mode = touch.get("mode")
                    if isinstance(target, str) and isinstance(mode, int):
                        try:
                            if not os.path.exists(target):
                                fd = os.open(
                                    target,
                                    os.O_CREAT | os.O_WRONLY | os.O_EXCL,
                                    0o666,
                                )
                                os.close(fd)
                                os.chmod(target, mode)
                            # If file exists (daemon pre-created it), leave
                            # the mode alone — this is the fixed behavior.
                        except OSError:
                            # Parent dir missing or create raced — drop the
                            # side-effect quietly. Mirrors what tmux pipe-pane
                            # would surface as a non-zero exit downstream.
                            pass
                return DockerExecResult(
                    returncode=int(entry.get("returncode", 0)),
                    stdout=str(entry.get("stdout", "")),
                    stderr=str(entry.get("stderr", "")),
                )
        # Default: success with empty output (mirrors a successful pipe-pane).
        return DockerExecResult(returncode=0, stdout="", stderr="")


def resolve_docker_exec_runner() -> DockerExecRunner:
    """Production wiring: honors ``AGENTTOWER_TEST_PIPE_PANE_FAKE`` (FR-060)."""
    fake_path = os.environ.get("AGENTTOWER_TEST_PIPE_PANE_FAKE")
    if fake_path:
        return FakeDockerExecRunner.from_path(fake_path)
    return SubprocessDockerExecRunner()
