"""AgentTower local app backend contract (FEAT-011).

The ``app.*`` socket namespace is a host-only, versioned façade over the
existing FEAT-002..FEAT-010 service layer. Every method dispatches into
the same daemon-internal services the legacy CLI methods use; FEAT-011
does not introduce a parallel write path.

See ``specs/011-app-backend-contract/`` for the full contract.
"""

from __future__ import annotations

from .versioning import APP_CONTRACT_VERSION, SUPPORTED_MINOR_RANGE

__all__ = [
    "APP_CONTRACT_VERSION",
    "SUPPORTED_MINOR_RANGE",
]
