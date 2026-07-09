"""FEAT-013 templates contract test (T017a).

Covers FR-001 (built-in templates ``1m+2s`` + ``2m+2s``), FR-024 (operator
YAML override with name-wins precedence), ``managed_template_not_found``
rejection, and the FR-024 amendment **no-auto-create post-condition**:
the loader MUST NOT create the override directory on a fresh HOME.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.managed_sessions.errors import (
    MANAGED_TEMPLATE_NOT_FOUND,
    ManagedSessionsError,
)
from agenttower.managed_sessions.templates import (
    BUILTINS,
    load_templates,
    resolve_template,
)


# ─── Built-in templates (FR-001) ──────────────────────────────────────────


def test_builtin_1m_2s_present() -> None:
    tmpl = BUILTINS["1m+2s"]
    assert tmpl.pane_count == 3
    roles = [pane.role for pane in tmpl.panes]
    assert roles == ["master", "slave", "slave"]


def test_builtin_2m_2s_present() -> None:
    tmpl = BUILTINS["2m+2s"]
    assert tmpl.pane_count == 4
    roles = [pane.role for pane in tmpl.panes]
    assert roles == ["master", "master", "slave", "slave"]


def test_load_templates_returns_builtins_when_override_dir_missing(tmp_path: Path) -> None:
    """FR-024 amendment: missing override dir → built-ins only, no I/O on HOME."""
    nonexistent = tmp_path / "nonexistent_dir"
    assert not nonexistent.exists()
    registry = load_templates(override_dir=nonexistent)
    assert set(registry.keys()) == set(BUILTINS.keys())
    # FR-024 no-auto-create — the loader MUST NOT create the directory.
    assert not nonexistent.exists()


# ─── Operator override (FR-024 name-wins precedence) ──────────────────────


def test_operator_override_replaces_builtin(tmp_path: Path) -> None:
    """Operator file with the same `name` as a built-in OVERRIDES the built-in."""
    override = tmp_path / "1m+2s.yaml"
    override.write_text(
        """\
name: 1m+2s
panes:
  - role: master
    capability: orchestrator
    label_pattern: "custom-m{ordinal}"
    default_launch_command_ref: bash-placeholder
  - role: slave
    capability: worker
    label_pattern: "custom-s{ordinal}"
    default_launch_command_ref: bash-placeholder
""",
        encoding="utf-8",
    )

    registry = load_templates(override_dir=tmp_path)
    custom = registry["1m+2s"]
    # Confirm we got the operator file, not the built-in.
    assert custom.pane_count == 2
    assert custom.panes[0].label_pattern == "custom-m{ordinal}"
    assert custom.panes[0].default_launch_command_ref == "bash-placeholder"


def test_operator_new_template_adds_to_registry(tmp_path: Path) -> None:
    """An operator file with a NEW `name` adds to the registry."""
    (tmp_path / "custom.yaml").write_text(
        """\
name: my-custom
panes:
  - role: master
    capability: orchestrator
    label_pattern: "x{ordinal}"
    default_launch_command_ref: null
""",
        encoding="utf-8",
    )
    registry = load_templates(override_dir=tmp_path)
    assert "my-custom" in registry
    # Built-ins still present.
    assert "1m+2s" in registry
    assert "2m+2s" in registry


def test_invalid_yaml_is_silently_skipped(tmp_path: Path) -> None:
    """Malformed YAML files are skipped, not fatal."""
    (tmp_path / "broken.yaml").write_text("not: valid: yaml: [", encoding="utf-8")
    (tmp_path / "good.yaml").write_text(
        """\
name: good-template
panes:
  - role: master
    capability: orchestrator
    label_pattern: "m{ordinal}"
""",
        encoding="utf-8",
    )
    registry = load_templates(override_dir=tmp_path)
    assert "good-template" in registry
    # Built-ins still present.
    assert "1m+2s" in registry


def test_invalid_shape_yaml_is_silently_skipped(tmp_path: Path) -> None:
    """YAML that parses but has wrong shape is skipped."""
    (tmp_path / "wrong.yaml").write_text(
        """\
name: 123  # not a string
panes:
  - role: master
""",
        encoding="utf-8",
    )
    registry = load_templates(override_dir=tmp_path)
    assert 123 not in registry


# ─── Resolver + error code ────────────────────────────────────────────────


def test_resolve_template_returns_builtin() -> None:
    tmpl = resolve_template("1m+2s")
    assert tmpl.name == "1m+2s"


def test_resolve_template_unknown_raises_closed_set_error() -> None:
    with pytest.raises(ManagedSessionsError) as exc:
        resolve_template("nonexistent-template")
    assert exc.value.code == MANAGED_TEMPLATE_NOT_FOUND
    assert exc.value.details["template_name"] == "nonexistent-template"
    assert "known_templates" in exc.value.details
