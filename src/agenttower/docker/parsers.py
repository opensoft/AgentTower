"""Pure parse helpers for `docker ps` and `docker inspect` output."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..socket_api import errors as _errors
from .adapter import ContainerSummary, DockerError, InspectResult, Mount, PerContainerError

_ENV_ALLOWLIST: tuple[str, ...] = ("USER", "HOME", "WORKDIR", "TMUX")
_MAX_TEXT = 2048


def _bound(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = "".join(ch for ch in text if ch == "\t" or ch == "\n" or ord(ch) >= 32)
    return cleaned[:_MAX_TEXT]


def parse_docker_ps_lines(text: str) -> list[ContainerSummary]:
    """Parse one row per line, tab-separated `<id>\\t<names>\\t<image>\\t<status>`.

    Names may be a comma-separated list (Docker shows secondary names this way);
    each name produces its own `ContainerSummary` so the matching predicate
    sees every alias the user could have set.
    """
    summaries: list[ContainerSummary] = []
    for raw_line in text.splitlines():
        line = raw_line.strip("\r")
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 4:
            raise DockerError(
                code=_errors.DOCKER_MALFORMED,
                message=_bound(f"docker ps row has {len(parts)} fields, expected 4: {line!r}"),
            )
        container_id, names_field, image, status = parts
        if not container_id:
            raise DockerError(
                code=_errors.DOCKER_MALFORMED,
                message=_bound(f"docker ps row has empty id: {line!r}"),
            )
        for name in names_field.split(","):
            cleaned = name.strip().lstrip("/")
            if not cleaned:
                continue
            summaries.append(
                ContainerSummary(
                    container_id=container_id,
                    name=cleaned,
                    image=image,
                    status=status,
                )
            )
    return summaries


def _coerce_labels(raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DockerError(
            code=_errors.DOCKER_MALFORMED,
            message=_bound("inspect Labels is not an object"),
        )
    return {str(k): str(v) for k, v in raw.items()}


def _coerce_mounts(raw: Any) -> list[Mount]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DockerError(
            code=_errors.DOCKER_MALFORMED,
            message=_bound("inspect Mounts is not a list"),
        )
    out: list[Mount] = []
    for item in raw:
        if not isinstance(item, dict):
            raise DockerError(
                code=_errors.DOCKER_MALFORMED,
                message=_bound("inspect Mounts entry is not an object"),
            )
        out.append(
            Mount(
                source=str(item.get("Source", "")),
                target=str(item.get("Destination", item.get("Target", ""))),
                type=str(item.get("Type", "")),
                mode=str(item.get("Mode", "")),
                rw=bool(item.get("RW", False)),
            )
        )
    return out


def _filter_env_keys(env: Any) -> list[str]:
    if not isinstance(env, list):
        return []
    keys: list[str] = []
    for entry in env:
        if not isinstance(entry, str) or "=" not in entry:
            continue
        key = entry.split("=", 1)[0]
        if key in _ENV_ALLOWLIST:
            keys.append(key)
    return keys


def _normalize_one(blob: Mapping[str, Any]) -> InspectResult:
    if not isinstance(blob, dict):
        raise DockerError(
            code=_errors.DOCKER_MALFORMED,
            message=_bound("inspect entry is not an object"),
        )

    container_id = str(blob.get("Id") or blob.get("ID") or "")
    if not container_id:
        raise DockerError(
            code=_errors.DOCKER_MALFORMED,
            message=_bound("inspect entry missing Id"),
        )

    raw_name = blob.get("Name", "")
    name = (str(raw_name) if raw_name is not None else "").lstrip("/")

    config = blob.get("Config") if isinstance(blob.get("Config"), dict) else {}
    state = blob.get("State") if isinstance(blob.get("State"), dict) else {}

    image = str(config.get("Image", ""))
    labels = _coerce_labels(config.get("Labels"))
    mounts = _coerce_mounts(blob.get("Mounts"))
    config_user = config.get("User") or None
    if config_user is not None:
        config_user = str(config_user)
    working_dir = config.get("WorkingDir") or None
    if working_dir is not None:
        working_dir = str(working_dir)
    status = str(state.get("Status", ""))
    env_keys = _filter_env_keys(config.get("Env"))

    inspect_blob = {
        "config_user": config_user,
        "working_dir": working_dir,
        "env_keys": env_keys,
        "full_status": status,
    }

    return InspectResult(
        container_id=container_id,
        name=name,
        image=image,
        status=status,
        labels=labels,
        mounts=mounts,
        config_user=config_user,
        working_dir=working_dir,
        env_keys=env_keys,
        inspect_blob=inspect_blob,
    )


def parse_docker_inspect_array(
    blob: str, requested_ids: Sequence[str]
) -> tuple[dict[str, InspectResult], list[PerContainerError]]:
    """Parse the JSON array output of `docker inspect <ids...>`.

    Returns (successes_by_id, per-container_failures). Per-container failures
    cover requested ids that the JSON did not include or whose entries were
    malformed; whole-blob errors raise `DockerError(DOCKER_MALFORMED)`.
    """
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError as exc:
        raise DockerError(
            code=_errors.DOCKER_MALFORMED,
            message=_bound(f"docker inspect output is not JSON: {exc}"),
        ) from exc

    if not isinstance(parsed, list):
        raise DockerError(
            code=_errors.DOCKER_MALFORMED,
            message=_bound("docker inspect output is not a JSON array"),
        )

    successes: dict[str, InspectResult] = {}
    failures: list[PerContainerError] = []
    seen_ids: set[str] = set()
    for entry in parsed:
        try:
            result = _normalize_one(entry)
        except DockerError as exc:
            entry_id = ""
            if isinstance(entry, dict):
                entry_id = str(entry.get("Id") or entry.get("ID") or "")
            failures.append(
                PerContainerError(
                    container_id=entry_id,
                    code=exc.code,
                    message=exc.message,
                )
            )
            continue
        successes[result.container_id] = result
        seen_ids.add(result.container_id)

    for requested in requested_ids:
        if requested not in seen_ids:
            already_failed = any(f.container_id == requested for f in failures)
            if already_failed:
                continue
            failures.append(
                PerContainerError(
                    container_id=requested,
                    code=_errors.DOCKER_MALFORMED,
                    message=_bound(f"docker inspect omitted requested id {requested!r}"),
                )
            )
    return successes, failures
