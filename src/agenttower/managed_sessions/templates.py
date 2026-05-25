"""FEAT-013 layout template registry (T008).

Two built-in templates ship in code (``1m+2s``, ``2m+2s``). Operator
overrides load from ``~/.config/opensoft/agenttower/managed_templates/*.yaml``.

Per FR-024 (and the pre-implement walk Q8 clarification):
* The daemon NEVER auto-creates files under the override directory.
* If the override directory does not exist, the loader treats it as
  "no overrides" — no I/O on the user's home is attempted beyond reading.
* Operator file with the same ``name`` as a built-in OVERRIDES the built-in.

See ``specs/013-managed-session-lifecycle/research.md`` §R8.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import yaml

from .errors import MANAGED_TEMPLATE_NOT_FOUND, ManagedSessionsError


CANONICAL_TEMPLATE_DIR: Final[Path] = Path(
    "~/.config/opensoft/agenttower/managed_templates"
).expanduser()


@dataclass(frozen=True, slots=True)
class TemplatePane:
    """One pane entry inside a ``ManagedTemplate``."""

    role: str
    capability: str
    label_pattern: str
    default_launch_command_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ManagedTemplate:
    """An operator-selectable layout template (FR-001)."""

    name: str
    panes: tuple[TemplatePane, ...]

    @property
    def pane_count(self) -> int:
        return len(self.panes)


# ─── Built-in templates (always available) ──────────────────────────────

_BUILTIN_1M_2S: Final[ManagedTemplate] = ManagedTemplate(
    name="1m+2s",
    panes=(
        TemplatePane(role="master", capability="orchestrator", label_pattern="m{ordinal}"),
        TemplatePane(role="slave", capability="worker", label_pattern="s{ordinal}"),
        TemplatePane(role="slave", capability="worker", label_pattern="s{ordinal}"),
    ),
)

_BUILTIN_2M_2S: Final[ManagedTemplate] = ManagedTemplate(
    name="2m+2s",
    panes=(
        TemplatePane(role="master", capability="orchestrator", label_pattern="m{ordinal}"),
        TemplatePane(role="master", capability="orchestrator", label_pattern="m{ordinal}"),
        TemplatePane(role="slave", capability="worker", label_pattern="s{ordinal}"),
        TemplatePane(role="slave", capability="worker", label_pattern="s{ordinal}"),
    ),
)


BUILTINS: Final[dict[str, ManagedTemplate]] = {
    _BUILTIN_1M_2S.name: _BUILTIN_1M_2S,
    _BUILTIN_2M_2S.name: _BUILTIN_2M_2S,
}


# ─── Loader ─────────────────────────────────────────────────────────────


def load_templates(override_dir: Path | None = None) -> dict[str, ManagedTemplate]:
    """Return the merged template registry: built-ins + operator overrides.

    Operator files with the same ``name`` override the built-in (FR-024).
    ``override_dir`` defaults to ``CANONICAL_TEMPLATE_DIR``; this argument
    exists for testability — production callers omit it.

    Per FR-024 the daemon MUST NOT create the override directory; if it
    does not exist, the function returns the built-ins unchanged. No
    ``os.makedirs`` / ``mkdir`` / ``Path.touch`` calls anywhere.
    """
    directory = override_dir if override_dir is not None else CANONICAL_TEMPLATE_DIR
    registry: dict[str, ManagedTemplate] = dict(BUILTINS)

    if not directory.is_dir():
        return registry

    for entry in sorted(directory.glob("*.yaml")):
        try:
            parsed = yaml.safe_load(entry.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            # Skip malformed files — defensive. Production would log a
            # warning; for MVP we silently ignore so a single bad file
            # does not break the daemon.
            continue
        tmpl = _coerce_template(parsed)
        if tmpl is not None:
            registry[tmpl.name] = tmpl

    return registry


def _coerce_template(raw: object) -> ManagedTemplate | None:
    """Best-effort conversion of a parsed YAML doc into ``ManagedTemplate``.

    Returns ``None`` if the shape is invalid (missing keys, wrong types).
    """
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    panes_raw = raw.get("panes")
    if not isinstance(name, str) or not name:
        return None
    if not isinstance(panes_raw, list) or not panes_raw:
        return None

    panes: list[TemplatePane] = []
    for item in panes_raw:
        if not isinstance(item, dict):
            return None
        role = item.get("role")
        capability = item.get("capability")
        label_pattern = item.get("label_pattern")
        default_ref = item.get("default_launch_command_ref")
        if (
            not isinstance(role, str)
            or not isinstance(capability, str)
            or not isinstance(label_pattern, str)
        ):
            return None
        if default_ref is not None and not isinstance(default_ref, str):
            return None
        panes.append(
            TemplatePane(
                role=role,
                capability=capability,
                label_pattern=label_pattern,
                default_launch_command_ref=default_ref,
            )
        )
    return ManagedTemplate(name=name, panes=tuple(panes))


def resolve_template(name: str, *, override_dir: Path | None = None) -> ManagedTemplate:
    """Look up a template by ``name`` from the merged registry.

    Raises ``ManagedSessionsError(MANAGED_TEMPLATE_NOT_FOUND)`` if the
    template is not found.
    """
    registry = load_templates(override_dir=override_dir)
    tmpl = registry.get(name)
    if tmpl is None:
        raise ManagedSessionsError(
            MANAGED_TEMPLATE_NOT_FOUND,
            details={
                "template_name": name,
                "known_templates": sorted(registry.keys()),
            },
        )
    return tmpl
