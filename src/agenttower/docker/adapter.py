"""Docker adapter Protocol and shared dataclasses for FEAT-003.

The Protocol decouples discovery code from the underlying Docker invocation
mechanism so the production `SubprocessDockerAdapter` and the test
`FakeDockerAdapter` are interchangeable behind the same surface.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ContainerSummary:
    """One row of `docker ps --format ...` output, normalized."""

    container_id: str
    name: str
    image: str
    status: str


@dataclass(frozen=True)
class Mount:
    source: str
    target: str
    type: str
    mode: str
    rw: bool


@dataclass(frozen=True)
class InspectResult:
    container_id: str
    name: str
    image: str
    status: str
    labels: Mapping[str, str]
    mounts: Sequence[Mount]
    config_user: str | None
    working_dir: str | None
    env_keys: Sequence[str]
    inspect_blob: Mapping[str, Any]


@dataclass(frozen=True)
class PerContainerError:
    container_id: str
    code: str
    message: str


@dataclass(frozen=True)
class DockerError(Exception):
    """Normalized Docker subprocess failure.

    Use the closed-set codes from :mod:`agenttower.socket_api.errors`.
    Carries an optional `container_id` so per-container failures can be
    distinguished from whole-scan failures during reconciliation.
    """

    code: str
    message: str
    container_id: str | None = None

    def __str__(self) -> str:
        if self.container_id is not None:
            return f"[{self.code}] {self.container_id}: {self.message}"
        return f"[{self.code}] {self.message}"


@dataclass(frozen=True)
class ScanResult:
    scan_id: str
    started_at: str
    completed_at: str
    status: Literal["ok", "degraded"]
    matched_count: int
    inactive_reconciled_count: int
    ignored_count: int
    error_code: str | None = None
    error_message: str | None = None
    error_details: Sequence[PerContainerError] = field(default_factory=tuple)


class DockerAdapter(Protocol):
    """Protocol implemented by `SubprocessDockerAdapter` and `FakeDockerAdapter`."""

    def list_running(self) -> Sequence[ContainerSummary]:
        """Return one summary per running container.

        Raises `DockerError` when `docker ps` fails as a whole.
        """

    def inspect(
        self, ids: Sequence[str]
    ) -> tuple[Mapping[str, InspectResult], Sequence[PerContainerError]]:
        """Inspect each id; return (successes_by_id, per-container_failures).

        Whole-batch failures (e.g., `docker` not on PATH) raise `DockerError`;
        per-container failures appear in the second tuple element so the
        successful candidates can still be reconciled.
        """
