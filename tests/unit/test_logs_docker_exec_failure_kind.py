"""Regression test for the FEAT-007 docker-exec failure-kind translation.

Pre-fix: ``SubprocessDockerExecRunner`` returned a generic
``DockerExecResult(returncode=127, ...)`` for ``FileNotFoundError`` and
``returncode=124`` for ``TimeoutExpired``. The downstream pipe-pane
helpers in :mod:`agenttower.logs.service` then raised
``pipe_pane_failed`` regardless of the actual cause, so docker-binary
missing or hitting the 5-second timeout surfaced as a tmux-level
failure to clients.

Post-fix: the runner stamps :attr:`DockerExecResult.failure_kind` with
``"docker_unavailable"`` (FileNotFoundError) or ``"docker_exec_timeout"``
(TimeoutExpired), and the pipe-pane helpers raise that closed-set code
instead.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from agenttower.logs import docker_exec as docker_exec_module
from agenttower.logs.docker_exec import (
    DockerExecResult,
    SubprocessDockerExecRunner,
)


def test_file_not_found_translates_to_docker_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_args: Any, **_kw: Any) -> Any:
        raise FileNotFoundError(2, "No such file or directory: 'docker'")

    monkeypatch.setattr(docker_exec_module.subprocess, "run", fake_run)

    runner = SubprocessDockerExecRunner()
    result = runner.run(["docker", "exec", "x", "true"])

    assert result.returncode == 127
    assert result.failure_kind == "docker_unavailable"
    assert "docker exec not available" in result.stderr


def test_timeout_translates_to_docker_exec_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: Any, **kw: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=args[0] if args else [], timeout=kw.get("timeout", 5.0))

    monkeypatch.setattr(docker_exec_module.subprocess, "run", fake_run)

    runner = SubprocessDockerExecRunner()
    result = runner.run(["docker", "exec", "x", "true"])

    assert result.returncode == 124
    assert result.failure_kind == "docker_exec_timeout"
    assert "docker exec timeout" in result.stderr


def test_normal_exit_carries_no_failure_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful subprocess run leaves ``failure_kind`` as None so callers
    fall through to the pipe-pane stderr-pattern check."""

    class _Completed:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    def fake_run(*_args: Any, **_kw: Any) -> _Completed:
        return _Completed()

    monkeypatch.setattr(docker_exec_module.subprocess, "run", fake_run)

    runner = SubprocessDockerExecRunner()
    result = runner.run(["docker", "exec", "x", "true"])

    assert result.returncode == 0
    assert result.failure_kind is None
    assert result.stdout == "ok\n"


def test_dataclass_default_failure_kind_is_none() -> None:
    """Sanity: callers (incl. ``FakeDockerExecRunner``) constructing a
    result without passing ``failure_kind`` get ``None`` so the
    failure-kind branch is not accidentally tripped."""
    result = DockerExecResult(returncode=0, stdout="", stderr="")
    assert result.failure_kind is None
