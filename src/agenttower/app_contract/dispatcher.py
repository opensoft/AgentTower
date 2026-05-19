"""FEAT-011 dispatch surface — merges into FEAT-002's DISPATCH table.

The existing FEAT-002 dispatcher uses a closed-set ``DISPATCH`` dict
literal in ``socket_api/methods.py``. FEAT-011 adds the ``app.*`` namespace
by exporting an ``APP_DISPATCH`` mapping that ``methods.py`` imports and
merges into its own table at module-import time. No runtime
``register_method`` API is introduced; the dispatch table remains a
closed, statically-defined dict (consistent with FEAT-002 R-014).

Per FR-001 / FR-002, this is purely additive: the legacy method
mappings in ``DISPATCH`` are unchanged. The host-only gate (FR-042) is
applied inside each ``app.*`` handler itself, not at the dispatcher
boundary — this keeps the dispatcher merge mechanical and the gate
visible at the per-handler entry point.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..socket_api.methods import DaemonContext


_AppHandler = Callable[["DaemonContext", dict[str, Any], int], dict[str, Any]]


def _build_app_dispatch() -> dict[str, _AppHandler]:
    """Construct the ``app.*`` dispatch map.

    Kept in a function (rather than a module-level dict literal) so the
    imports of individual handler modules happen lazily — this avoids
    a circular import on the FEAT-002 ``socket_api.methods`` side
    (``host_only.py`` imports from there, so importing app_contract
    eagerly from methods.py would loop).
    """
    from . import dashboard as _dashboard
    from . import hello as _hello
    from . import preflight as _preflight
    from . import readiness as _readiness

    return {
        "app.preflight": _preflight.app_preflight,
        "app.hello": _hello.app_hello,
        "app.readiness": _readiness.app_readiness,
        "app.dashboard": _dashboard.app_dashboard,
    }


APP_DISPATCH: dict[str, _AppHandler] = _build_app_dispatch()


__all__ = [
    "APP_DISPATCH",
]
