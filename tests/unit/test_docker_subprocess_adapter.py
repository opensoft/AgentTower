"""Unit tests for `SubprocessDockerAdapter`.

The session-scoped `_no_real_docker` fixture in `tests/conftest.py`
already prevents these tests from spawning a real `docker` binary.
We patch `subprocess.run` and `shutil.which` per test to drive every
return-code → DockerError mapping branch.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

import pytest

from agenttower.docker import subprocess_adapter as adapter_module
from agenttower.docker.adapter import DockerError
from agenttower.socket_api import errors as _errors


@pytest.fixture(autouse=True)
def _ungate_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unblock the conftest guard for *this* unit-test module so we can
    drive `SubprocessDockerAdapter` against a patched `subprocess.run`.
    """
    monkeypatch.setattr(shutil, "which", lambda name, **kw: f"/usr/bin/{name}")
    yield


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_argv_for_list_running_is_typed_and_shell_false(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        captured["argv"] = argv
        captured["kw"] = kw
        return _completed(stdout="abc\tpy-bench\timg\trunning\n")

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessDockerAdapter(env={"PATH": "/usr/bin"})
    summaries = adapter.list_running()

    assert summaries[0].container_id == "abc"
    assert captured["argv"] == [
        "/usr/bin/docker",
        "ps",
        "--no-trunc",
        "--format",
        "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}",
    ]
    assert captured["kw"]["shell"] is False
    assert captured["kw"]["timeout"] == 5.0
    assert captured["kw"]["check"] is False


def test_argv_for_inspect_passes_ids_as_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        captured["argv"] = argv
        return _completed(stdout="[]")

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessDockerAdapter(env={"PATH": "/usr/bin"})
    adapter.inspect(["abc", "def"])
    assert captured["argv"] == ["/usr/bin/docker", "inspect", "abc", "def"]


def test_command_not_found_yields_docker_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name, **kw: None)
    adapter = adapter_module.SubprocessDockerAdapter(env={"PATH": "/empty"})
    with pytest.raises(DockerError) as exc_info:
        adapter.list_running()
    assert exc_info.value.code == _errors.DOCKER_UNAVAILABLE


def test_permission_denied_yields_docker_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        return _completed(
            stderr="Got permission denied while trying to connect to the Docker daemon",
            returncode=1,
        )

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessDockerAdapter(env={"PATH": "/usr/bin"})
    with pytest.raises(DockerError) as exc_info:
        adapter.list_running()
    assert exc_info.value.code == _errors.DOCKER_PERMISSION_DENIED


def test_non_zero_exit_yields_docker_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        return _completed(stderr="some other error", returncode=2)

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessDockerAdapter(env={"PATH": "/usr/bin"})
    with pytest.raises(DockerError) as exc_info:
        adapter.list_running()
    assert exc_info.value.code == _errors.DOCKER_FAILED


def test_timeout_yields_docker_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-029: Python's `subprocess.run` kills + waits the child on TimeoutExpired."""

    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout", 5.0))

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessDockerAdapter(env={"PATH": "/usr/bin"})
    with pytest.raises(DockerError) as exc_info:
        adapter.list_running()
    assert exc_info.value.code == _errors.DOCKER_TIMEOUT


def test_malformed_inspect_yields_docker_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        return _completed(stdout="not-json", returncode=0)

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessDockerAdapter(env={"PATH": "/usr/bin"})
    with pytest.raises(DockerError) as exc_info:
        adapter.inspect(["abc"])
    assert exc_info.value.code == _errors.DOCKER_MALFORMED


def test_partial_inspect_failure_returns_per_container_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-zero exit with partial JSON: surface successes + per-container errors."""
    blob = '[{"Id": "abc", "Name": "/py-bench", "Config": {"Image": "i"}, "State": {"Status": "running"}}]'

    def fake_run(argv, **kw):  # noqa: ANN001, ANN201
        return _completed(
            stdout=blob,
            stderr="Error: No such object: missing-id",
            returncode=1,
        )

    monkeypatch.setattr(adapter_module.subprocess, "run", fake_run)
    adapter = adapter_module.SubprocessDockerAdapter(env={"PATH": "/usr/bin"})
    successes, failures = adapter.inspect(["abc", "missing-id"])
    assert "abc" in successes
    failure_ids = {f.container_id for f in failures}
    assert "missing-id" in failure_ids
