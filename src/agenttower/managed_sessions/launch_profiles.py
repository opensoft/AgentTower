"""FEAT-013 launch command profile loader (T009).

Loads YAML profiles from ``~/.config/opensoft/agenttower/launch_commands/*.yaml``
(FR-002, FR-024). Enforces argv-shape per research §R9 — ``command`` MUST
be a list of strings, never a single shell string (Principle III safety).

Per FR-024 (and pre-implement walk Q8): the daemon NEVER auto-creates the
override directory; if it doesn't exist, the loader returns an empty
registry — no I/O on the user's home is attempted beyond reading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import yaml

from .errors import (
    MANAGED_LAUNCH_COMMAND_NOT_FOUND,
    ManagedSessionsError,
)


CANONICAL_PROFILE_DIR: Final[Path] = Path(
    "~/.config/opensoft/agenttower/launch_commands"
).expanduser()


@dataclass(frozen=True, slots=True)
class LaunchCommandProfile:
    """An operator-configured launch command (FR-002, research §R9)."""

    name: str
    command: tuple[str, ...]  # argv shape; NEVER a single shell string
    env: dict[str, str] = field(default_factory=dict)
    working_dir: str | None = None


def load_profiles(override_dir: Path | None = None) -> dict[str, LaunchCommandProfile]:
    """Return the registry of operator-defined launch profiles.

    There are no "built-in" launch profiles — every profile is operator-
    supplied via YAML. Missing override directory returns ``{}`` (FR-024
    no-auto-create).
    """
    directory = override_dir if override_dir is not None else CANONICAL_PROFILE_DIR
    registry: dict[str, LaunchCommandProfile] = {}

    if not directory.is_dir():
        return registry

    for entry in sorted(directory.glob("*.yaml")):
        try:
            parsed = yaml.safe_load(entry.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        profile = _coerce_profile(parsed)
        if profile is not None:
            registry[profile.name] = profile

    return registry


def _coerce_profile(raw: object) -> LaunchCommandProfile | None:
    """Best-effort conversion of a parsed YAML doc into ``LaunchCommandProfile``.

    Returns ``None`` if the shape is invalid:

    * ``name`` not a non-empty string
    * ``command`` not a list of strings (research §R9 argv-shape — never
      a single shell string)
    * ``env`` (if present) not a string→string mapping
    * ``working_dir`` (if present) not a string
    """
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    command = raw.get("command")
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(command, list) or not command:
        return None
    if not all(isinstance(arg, str) for arg in command):
        # R9 violation: argv-shape enforcement.
        return None

    env_raw = raw.get("env", {})
    if env_raw is None:
        env_raw = {}
    if not isinstance(env_raw, dict):
        return None
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in env_raw.items()):
        return None

    working_dir = raw.get("working_dir")
    if working_dir is not None and not isinstance(working_dir, str):
        return None

    return LaunchCommandProfile(
        name=name,
        command=tuple(command),
        env=dict(env_raw),
        working_dir=working_dir,
    )


def resolve_profile(
    name: str, *, override_dir: Path | None = None
) -> LaunchCommandProfile:
    """Look up a launch profile by name.

    Raises ``ManagedSessionsError(MANAGED_LAUNCH_COMMAND_NOT_FOUND)`` if
    the profile is not found.
    """
    registry = load_profiles(override_dir=override_dir)
    profile = registry.get(name)
    if profile is None:
        raise ManagedSessionsError(
            MANAGED_LAUNCH_COMMAND_NOT_FOUND,
            details={
                "profile_name": name,
                "known_profiles": sorted(registry.keys()),
            },
        )
    return profile
