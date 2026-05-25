"""FEAT-013 ``app.managed_*`` host-only socket handlers.

Registered with FEAT-011's ``app_contract`` dispatcher; uses FEAT-011's
host-only peer gate (``host_only`` rejection for bench-container peers).
Same service entry points as the legacy CLI handlers (``handlers/cli.py``)
— this module wraps them in the FEAT-011 envelope (``ok`` + ``app_contract_version``
+ ``result`` / ``error``).

Implementation in T024 (US1 app.managed_layout_create + list/detail/pane.list/pane.detail),
T025 (dispatcher registration), T033 (US2 list/detail wiring), T048 (US3
remove/recreate/promote wiring).
"""

from __future__ import annotations
