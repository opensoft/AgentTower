"""Filesystem path helpers for AgentTower.

FEAT-005 R-001 / data-model §3.1 add :class:`ResolvedSocket` here so the
``(path, source)`` pair lives next to :class:`Paths` itself; the
``config_doctor`` package consumes it without requiring an extra hop.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_NAMESPACE = ("opensoft", "agenttower")

SocketSource = Literal["env_override", "mounted_default", "host_default"]


@dataclass(frozen=True)
class ResolvedSocket:
    """Output of :func:`agenttower.config_doctor.socket_resolve.resolve_socket_path`.

    The pair ``(path, source)`` is computed at every CLI invocation; not
    persisted. Surfaced by ``agenttower config paths`` (FR-019) and by the
    doctor's ``socket_resolved`` check (FR-015). Lives here (next to
    :class:`Paths`) so existing FEAT-001 / FEAT-002 callers don't need to
    take a transitive dependency on the FEAT-005 ``config_doctor`` package.
    """

    path: Path
    source: SocketSource


@dataclass(frozen=True)
class Paths:
    """Resolved filesystem locations AgentTower will use on this host."""

    config_file: Path
    state_db: Path
    events_file: Path
    logs_dir: Path
    socket: Path
    cache_dir: Path


def _xdg_base(env: Mapping[str, str], var: str, home: Path, fallback: str) -> Path:
    value = env.get(var, "")
    if value:
        return Path(value)
    return home / fallback


def resolve_paths(env: Mapping[str, str] | None = None) -> Paths:
    """Resolve the six-member path set from the given environment mapping."""

    env = os.environ if env is None else env
    home = Path(env["HOME"])

    config_base = _xdg_base(env, "XDG_CONFIG_HOME", home, ".config")
    state_base = _xdg_base(env, "XDG_STATE_HOME", home, ".local/state")
    cache_base = _xdg_base(env, "XDG_CACHE_HOME", home, ".cache")

    config_dir = config_base.joinpath(*_NAMESPACE)
    state_dir = state_base.joinpath(*_NAMESPACE)
    cache_dir = cache_base.joinpath(*_NAMESPACE)

    return Paths(
        config_file=config_dir / "config.toml",
        state_db=state_dir / "agenttower.sqlite3",
        events_file=state_dir / "events.jsonl",
        logs_dir=state_dir / "logs",
        socket=state_dir / "agenttowerd.sock",
        cache_dir=cache_dir,
    )
