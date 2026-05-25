"""FEAT-013 tmux command composer.

Composes ``tmux new-session``, ``split-window``, ``select-pane`` (title
prefix for the pending-managed marker), ``kill-pane``, and ``list-panes``
through the existing FEAT-004 ``docker exec`` channel. Argv-first per
research §R6 (Principle III safety). Enforces the FR-013 per-stage
30-second timeout with 2x transient retry (1s / 2s back-off).

Implementation in T011.
"""

from __future__ import annotations
