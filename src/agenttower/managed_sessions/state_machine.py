"""FEAT-013 lifecycle state machine.

Implements the closed-set state graph from
``specs/013-managed-session-lifecycle/contracts/state-machine.md``: states
``creating | ready | degraded | failed | removed`` plus the reserved
``promoted_from_adopted`` transition. See spec §FR-007.

Implementation in T006.
"""

from __future__ import annotations
