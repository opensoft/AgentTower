"""FEAT-013 managed-template test fixtures (T015).

Canonical ``1m+2s`` and ``2m+2s`` templates plus a custom-override
fixture used by T017 (``test_managed_templates.py`` +
``test_managed_launch_profiles.py``) and T028
(``test_story2_auto_prepare_operations.py``).
"""

from __future__ import annotations

from agenttower.managed_sessions.templates import (
    BUILTINS,
    ManagedTemplate,
    TemplatePane,
)


# Re-export the built-ins under aliases so tests don't depend on the
# private module attribute names.
TEMPLATE_1M_2S: ManagedTemplate = BUILTINS["1m+2s"]
TEMPLATE_2M_2S: ManagedTemplate = BUILTINS["2m+2s"]


# Custom override fixture used by T017 to exercise the FR-024 "operator
# file with same `name` wins" precedence. A test would write this YAML
# into a tmp override-dir and assert ``load_templates()`` returns this
# template instead of the built-in 1m+2s.
TEMPLATE_OVERRIDE_1M_2S_CUSTOM: ManagedTemplate = ManagedTemplate(
    name="1m+2s",  # collides with the built-in name — override semantics
    panes=(
        TemplatePane(
            role="master",
            capability="orchestrator",
            label_pattern="custom-m{ordinal}",
            default_launch_command_ref="bash-placeholder",
        ),
        TemplatePane(
            role="slave",
            capability="worker",
            label_pattern="custom-s{ordinal}",
            default_launch_command_ref="bash-placeholder",
        ),
        TemplatePane(
            role="slave",
            capability="worker",
            label_pattern="custom-s{ordinal}",
            default_launch_command_ref="bash-placeholder",
        ),
    ),
)


# YAML-equivalent text for the above override (used by T017 when writing
# into a temp override directory).
OVERRIDE_1M_2S_YAML = """\
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
  - role: slave
    capability: worker
    label_pattern: "custom-s{ordinal}"
    default_launch_command_ref: bash-placeholder
"""
