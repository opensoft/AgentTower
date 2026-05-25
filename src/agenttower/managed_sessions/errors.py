"""FEAT-013 closed-set error codes.

11 new codes added on top of FEAT-011's 27-entry registry (38 total).
See ``specs/013-managed-session-lifecycle/contracts/error-codes.md`` for
the per-code ``details`` schemas:

- managed_template_not_found
- managed_launch_command_not_found
- managed_session_name_conflict (FR-016)
- managed_layout_not_found
- managed_pane_not_found
- managed_pane_protected_adopted (FR-012)
- managed_pane_illegal_transition
- managed_pane_illegal_recreate_source
- managed_pane_recreate_chain_too_deep (FR-023)
- managed_layout_capacity_exceeded (FR-025)
- managed_pane_concurrent_recreate (FR-027)

Implementation in T005.
"""

from __future__ import annotations
