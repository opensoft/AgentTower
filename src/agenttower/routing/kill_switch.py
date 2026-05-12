"""FEAT-009 routing kill-switch service (FR-026 — FR-030).

Reads and writes the `daemon_state.routing_enabled` row with a
write-through cache for the hot-path `is_enabled()` read used by the
delivery worker.

Toggle endpoints (`enable`/`disable`) are host-only (Clarifications
session 2 Q2 + research §R-005); the boundary check lives in
`socket_api/methods.py`. This module is origin-agnostic — it accepts
an operator identity string (either an `agt_<12-hex>` agent_id or the
`host-operator` sentinel) and trusts the dispatch layer to have
enforced the host-only constraint.
"""

from __future__ import annotations
