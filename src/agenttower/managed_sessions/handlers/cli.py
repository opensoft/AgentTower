"""FEAT-013 legacy ``managed.*`` CLI socket handlers.

Registered with the FEAT-002 socket dispatcher. Thin-client peer scoping
per research §R12: bench-container callers may only target their own
container; cross-container requests return ``host_only``.

Implementation in T023 (US1 layout.create + list/detail/pane.list/pane.detail),
T025 (dispatcher registration), T033 (US2 list/detail wiring), T048 (US3
remove/recreate/promote wiring).
"""

from __future__ import annotations
