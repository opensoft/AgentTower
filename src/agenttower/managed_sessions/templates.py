"""FEAT-013 layout template registry.

Built-in templates (``1m+2s``, ``2m+2s``) ship in code; operator overrides
load from ``~/.config/opensoft/agenttower/managed_templates/*.yaml`` (FR-024).
The daemon never auto-creates files under the override directory per the
FR-024 amendment (spec §Clarifications "Session 2026-05-24 (pre-implement
walk)" Q8).

Implementation in T008.
"""

from __future__ import annotations
