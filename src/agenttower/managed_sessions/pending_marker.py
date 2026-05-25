"""FEAT-013 pending-managed marker.

Tracks managed_pane rows mid-creation via the SQLite
``managed_pane.pending_marker_token`` column AND the tmux pane-title
prefix ``@MANAGED:<token>:<label>``. Mitigates the FEAT-004 scan ×
creation-flow race (FR-014, research §R1). Owns the FR-022 5-minute TTL
sweep loop run at boot and every 60s.

Implementation in T012; sweep wiring in T050.
"""

from __future__ import annotations
