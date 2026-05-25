"""FEAT-013 frozen-clock test fixture (T015).

Used by state-machine, sweep, timeout, and recovery tests to make timing
assertions deterministic. See tasks T016 (FR-013 30-second per-stage
timeout + 2x retry assertion), T019 (FR-022 5-minute TTL sweep), T038
and T055 (FR-020 / SC-008 recovery timing).
"""

from __future__ import annotations
