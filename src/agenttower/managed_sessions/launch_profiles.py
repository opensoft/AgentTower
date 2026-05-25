"""FEAT-013 launch command profile loader.

Loads YAML profiles from ``~/.config/opensoft/agenttower/launch_commands/*.yaml``
(FR-002, FR-024). Enforces argv-shape per research §R9 (``command`` MUST
be a list of strings, never a single shell string — Principle III safety).

Implementation in T009.
"""

from __future__ import annotations
