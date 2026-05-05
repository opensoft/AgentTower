"""Production Docker adapter that shells out via `subprocess.run`.

Argv is constructed as a typed list with `shell=False`; container ids and
names never reach a shell string (FR-027). Each subprocess call has a
5-second timeout (FR-024) and a hung process is killed and waited
before returning a `docker_timeout` `DockerError` (FR-029).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

from ..socket_api import errors as _errors
from .adapter import (
    ContainerSummary,
    DockerAdapter,
    DockerError,
    InspectResult,
    PerContainerError,
)
from .parsers import parse_docker_inspect_array, parse_docker_ps_lines

_TIMEOUT_SECONDS = 5.0
_PS_FORMAT = "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}"
_MAX_TEXT = 2048

_PERMISSION_PATTERNS = (
    "permission denied",
    "Got permission denied",
    "dial unix /var/run/docker.sock: connect: permission denied",
)


def _bound(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = "".join(ch for ch in text if ch == "\t" or ch == "\n" or ord(ch) >= 32)
    return cleaned[:_MAX_TEXT]


def _classify_failure(stderr: str, returncode: int) -> str:
    s = (stderr or "").lower()
    for pattern in _PERMISSION_PATTERNS:
        if pattern.lower() in s:
            return _errors.DOCKER_PERMISSION_DENIED
    return _errors.DOCKER_FAILED


class SubprocessDockerAdapter(DockerAdapter):
    """Real `DockerAdapter` implementation using the `docker` CLI."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env: dict[str, str] = dict(env if env is not None else os.environ)

    # -- DockerAdapter Protocol -------------------------------------------------

    def list_running(self) -> Sequence[ContainerSummary]:
        argv = self._argv("ps", "--no-trunc", "--format", _PS_FORMAT)
        completed = self._run(argv)
        if completed.returncode != 0:
            code = _classify_failure(completed.stderr, completed.returncode)
            raise DockerError(
                code=code,
                message=_bound(
                    f"docker ps exited {completed.returncode}: {completed.stderr.strip()}"
                ),
            )
        return parse_docker_ps_lines(completed.stdout or "")

    def inspect(
        self, ids: Sequence[str]
    ) -> tuple[Mapping[str, InspectResult], Sequence[PerContainerError]]:
        if not ids:
            return {}, []
        argv = self._argv("inspect", *ids)
        completed = self._run(argv)
        if completed.returncode != 0:
            code = _classify_failure(completed.stderr, completed.returncode)
            # `docker inspect` returns non-zero when ANY id fails. We still
            # parse stdout because Docker emits a partial JSON array for the
            # ids it did succeed on; per-container errors are recorded for
            # the rest in `error_details`.
            try:
                successes, failures = parse_docker_inspect_array(
                    completed.stdout or "[]", ids
                )
            except DockerError:
                raise DockerError(
                    code=code,
                    message=_bound(
                        f"docker inspect exited {completed.returncode}: "
                        f"{completed.stderr.strip()}"
                    ),
                )
            # If the partial parse covered all ids successfully, treat the
            # non-zero exit as a whole failure to be safe — but in practice
            # there's always at least one missing id when returncode != 0.
            if not failures:
                raise DockerError(
                    code=code,
                    message=_bound(
                        f"docker inspect exited {completed.returncode}: "
                        f"{completed.stderr.strip()}"
                    ),
                )
            return successes, failures

        return parse_docker_inspect_array(completed.stdout or "[]", ids)

    # -- Internals -----------------------------------------------------------

    def _argv(self, *args: str) -> list[str]:
        binary = self._resolve_docker()
        return [binary, *args]

    def _resolve_docker(self) -> str:
        path = self._env.get("PATH", os.defpath)
        binary = shutil.which("docker", path=path)
        if not binary:
            raise DockerError(
                code=_errors.DOCKER_UNAVAILABLE,
                message="docker binary not found on PATH",
            )
        return binary

    def _run(self, argv: list[str]) -> "subprocess.CompletedProcess[str]":
        try:
            return subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
                shell=False,
                env=self._env,
            )
        except subprocess.TimeoutExpired as exc:
            # `subprocess.run` kills and waits for the child before raising
            # TimeoutExpired, which is the cleanup behavior FR-029 requires.
            raise DockerError(
                code=_errors.DOCKER_TIMEOUT,
                message=_bound(
                    f"docker {argv[1] if len(argv) > 1 else ''} exceeded "
                    f"{_TIMEOUT_SECONDS:.1f}s"
                ),
            ) from exc
        except FileNotFoundError as exc:
            raise DockerError(
                code=_errors.DOCKER_UNAVAILABLE,
                message=_bound(f"docker binary not executable: {exc}"),
            ) from exc
