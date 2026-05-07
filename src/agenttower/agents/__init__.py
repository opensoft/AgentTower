"""Agent registration domain logic for FEAT-006.

See ``specs/006-agent-registration/plan.md``. The package owns the
registration validation order, the per-(container, pane) and
per-agent advisory mutex registries, the ``effective_permissions``
derivation, the JSONL audit-row writer, and the daemon-side
orchestrator that turns a discovered FEAT-004 pane into a registered
agent. Re-exports below are filled in incrementally as each module
lands; the final public surface is locked by T092.
"""

from __future__ import annotations

# Re-exports — keep stable alphabetical order. Final list is locked by T092
# (specs/006-agent-registration/tasks.md).
from .identifiers import AGENT_ID_RE, generate_agent_id, validate_agent_id_shape
from .mutex import AgentLockMap, RegisterLockMap
from .permissions import (
    EffectivePermissions,
    effective_permissions,
    serialize_effective_permissions,
)

__all__ = [
    "AGENT_ID_RE",
    "AgentLockMap",
    "EffectivePermissions",
    "RegisterLockMap",
    "effective_permissions",
    "generate_agent_id",
    "serialize_effective_permissions",
    "validate_agent_id_shape",
]
