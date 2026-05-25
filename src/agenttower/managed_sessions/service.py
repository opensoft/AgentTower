"""FEAT-013 service entry points.

Orchestrates ``create_layout``, ``remove_pane``, ``recreate_pane``, and
``promote_from_adopted`` (stub) through the per-container serializer
(``serializer.py``), the tmux adapter (``tmux_create.py``), and the
pending-managed marker (``pending_marker.py``).

Implementation in T022 (create_layout), T029-T030 (FEAT-006/007 wiring),
T042 (remove_pane), T043 (recreate_pane), T044 (adopted-pane protection),
T045 (promote stub).
"""

from __future__ import annotations
