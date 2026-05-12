"""FEAT-009 permission gate.

Implements the six-step enqueue precedence (FR-019 / FR-020 after
Clarifications 2026-05-12 session 2 Q3) and the delivery-time
target-only re-check (FR-025 / research §R-006).

Steps in order: routing flag enabled → sender role + active → target
registered + active → target role permitted → target container active
→ target pane resolvable. First failing step determines the
`block_reason`.
"""

from __future__ import annotations
