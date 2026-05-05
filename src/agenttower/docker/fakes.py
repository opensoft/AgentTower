"""Test-only Docker adapter that scripts canned outcomes from a JSON fixture.

The fixture format is:

```json
{
  "list_running": {"action": "ok", "containers": [...]},
  "inspect": {"action": "ok", "results": [...]}
}
```

Each section's `action` may be one of:

- `"ok"`: return the listed containers / results.
- `"command_not_found"` / `"permission_denied"` / `"non_zero_exit"` /
  `"timeout"` / `"malformed"`: raise the matching `DockerError`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..socket_api import errors as _errors
from .adapter import (
    ContainerSummary,
    DockerError,
    InspectResult,
    Mount,
    PerContainerError,
)

_ACTION_TO_CODE: Mapping[str, str] = {
    "command_not_found": _errors.DOCKER_UNAVAILABLE,
    "permission_denied": _errors.DOCKER_PERMISSION_DENIED,
    "non_zero_exit": _errors.DOCKER_FAILED,
    "timeout": _errors.DOCKER_TIMEOUT,
    "malformed": _errors.DOCKER_MALFORMED,
}


class FakeDockerAdapter:
    """Scriptable adapter that satisfies the `DockerAdapter` Protocol.

    When constructed via :meth:`from_path`, the adapter re-reads the JSON
    fixture on every call so integration tests can mutate the file between
    scans (e.g., to flip a previously-active container to absent).
    """

    def __init__(
        self,
        script: Mapping[str, Any] | None = None,
        *,
        path: Path | None = None,
    ) -> None:
        self._script: dict[str, Any] = dict(script) if script is not None else {}
        self._path = path

    @classmethod
    def from_path(cls, path: str | Path) -> "FakeDockerAdapter":
        return cls(path=Path(path))

    def _load(self) -> dict[str, Any]:
        if self._path is None:
            return self._script
        text = self._path.read_text(encoding="utf-8")
        return json.loads(text)

    # -- DockerAdapter Protocol -------------------------------------------------
    def list_running(self) -> Sequence[ContainerSummary]:
        script = self._load()
        section = script.get("list_running", {"action": "ok", "containers": []})
        action = section.get("action", "ok")
        delay = float(section.get("delay_ms", 0)) / 1000.0
        if delay > 0:
            time.sleep(delay)
        if action != "ok":
            code = _ACTION_TO_CODE.get(action)
            if code is None:
                raise DockerError(
                    code=_errors.DOCKER_FAILED,
                    message=f"unknown fake action: {action!r}",
                )
            raise DockerError(
                code=code,
                message=section.get("message", f"fake {action}"),
            )
        return [
            ContainerSummary(
                container_id=str(c["container_id"]),
                name=str(c["name"]),
                image=str(c.get("image", "")),
                status=str(c.get("status", "running")),
            )
            for c in section.get("containers", [])
        ]

    def inspect(
        self, ids: Sequence[str]
    ) -> tuple[Mapping[str, InspectResult], Sequence[PerContainerError]]:
        script = self._load()
        section = script.get("inspect", {"action": "ok", "results": []})
        action = section.get("action", "ok")
        delay = float(section.get("delay_ms", 0)) / 1000.0
        if delay > 0:
            time.sleep(delay)
        if action != "ok":
            code = _ACTION_TO_CODE.get(action)
            if code is None:
                raise DockerError(
                    code=_errors.DOCKER_FAILED,
                    message=f"unknown fake action: {action!r}",
                )
            raise DockerError(
                code=code,
                message=section.get("message", f"fake {action}"),
            )

        successes: dict[str, InspectResult] = {}
        for entry in section.get("results", []):
            cid = str(entry["container_id"])
            if cid not in ids:
                continue
            mounts = [
                Mount(
                    source=str(m.get("source", "")),
                    target=str(m.get("target", "")),
                    type=str(m.get("type", "")),
                    mode=str(m.get("mode", "")),
                    rw=bool(m.get("rw", False)),
                )
                for m in entry.get("mounts", [])
            ]
            inspect_blob = {
                "config_user": entry.get("config_user"),
                "working_dir": entry.get("working_dir"),
                "env_keys": list(entry.get("env_keys", [])),
                "full_status": entry.get("status", "running"),
            }
            successes[cid] = InspectResult(
                container_id=cid,
                name=str(entry.get("name", cid)),
                image=str(entry.get("image", "")),
                status=str(entry.get("status", "running")),
                labels=dict(entry.get("labels", {})),
                mounts=mounts,
                config_user=entry.get("config_user"),
                working_dir=entry.get("working_dir"),
                env_keys=list(entry.get("env_keys", [])),
                inspect_blob=inspect_blob,
            )

        failures: list[PerContainerError] = []
        per_container = section.get("per_container_errors", {}) or {}
        for cid, info in per_container.items():
            if cid in ids:
                failures.append(
                    PerContainerError(
                        container_id=str(cid),
                        code=str(info.get("code", _errors.DOCKER_FAILED)),
                        message=str(info.get("message", "fake per-container error")),
                    )
                )

        for cid in ids:
            if cid not in successes and not any(f.container_id == cid for f in failures):
                failures.append(
                    PerContainerError(
                        container_id=cid,
                        code=_errors.DOCKER_FAILED,
                        message=f"fake inspect omitted requested id {cid!r}",
                    )
                )
        return successes, failures
