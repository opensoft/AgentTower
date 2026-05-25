"""FEAT-013 daemon-boot recovery.

Reconciles durable ``managed_layout`` / ``managed_pane`` rows against
live tmux panes (FR-020, SC-008). Reattaches surviving panes; transitions
unreachable rows to ``failed`` with ``failed_stage = recovery_reattach``.
Per contracts/state-machine.md §Recovery.

Implementation in T046, T047 (daemon-boot wiring).
"""

from __future__ import annotations
