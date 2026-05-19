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

Each handler is wrapped by ``_wrap_handler`` (below) so that:

- A ``ContractViolation`` raised by a handler (e.g., the handler tried
  to emit a malformed failure envelope) is caught and mapped to the
  FEAT-011 ``internal_error`` envelope — NOT propagated up to the
  FEAT-002 catch-all, which would return the legacy ``INTERNAL_ERROR``
  envelope shape (missing ``app_contract_version``).
- Any other unexpected exception from a handler is similarly mapped to
  ``internal_error`` so the wire always sees a structurally-valid
  FEAT-011 envelope (FR-033 invariant).

T098: ``is_app_method()`` and ``make_unknown_method_envelope()`` are
exposed for the FEAT-002 dispatcher to call when a method name in the
``app.*`` namespace misses the DISPATCH table. The default FEAT-002
``unknown_method`` envelope is missing the FR-033 ``details: {}`` field
and the FR-033 ``app_contract_version`` stamp; the rewriter emits the
FEAT-011-compliant shape instead.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..socket_api.methods import DaemonContext


_AppHandler = Callable[["DaemonContext", dict[str, Any], int], dict[str, Any]]


def _wrap_handler(handler: _AppHandler) -> _AppHandler:
    """Wrap an ``app.*`` handler so it always returns a FEAT-011 envelope.

    Catches:
        - ``ContractViolation`` from ``envelope.failure()`` / ``validate_details``
          (signals a daemon-side bug: the handler tried to emit a malformed
          failure envelope). Mapped to ``internal_error`` with a message
          carrying the violation reason — never leaks to the client as a
          raw exception.
        - Any other ``Exception`` — same treatment, with the exception
          type name in the message. Ensures the wire always sees the
          FEAT-011 envelope shape (``ok``, ``app_contract_version``,
          ``error.{code,message,details}``), not the legacy FEAT-002
          ``INTERNAL_ERROR`` shape from ``socket_api/methods.py``'s
          top-level catch-all.

    Lazy-imports ``envelope`` and ``errors`` inside the wrapper to keep
    the dispatcher module-load free of cycles.
    """
    def wrapped(
        ctx: "DaemonContext",
        params: dict[str, Any],
        peer_uid: int = -1,
    ) -> dict[str, Any]:
        from . import envelope as _envelope
        from .errors import ContractViolation

        try:
            return handler(ctx, params, peer_uid)
        except ContractViolation as exc:
            return _envelope.internal_error(
                f"app.* handler emitted malformed envelope: {exc}"
            )
        except Exception as exc:  # noqa: BLE001 — FR-033 envelope-shape safety net
            return _envelope.internal_error(
                f"app.* handler raised {type(exc).__name__}: {exc}"
            )

    wrapped.__name__ = getattr(handler, "__name__", "wrapped")
    wrapped.__qualname__ = getattr(handler, "__qualname__", wrapped.__name__)
    return wrapped


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
    from . import reads as _reads
    from . import scan_handlers as _scan_handlers

    return {
        "app.preflight": _wrap_handler(_preflight.app_preflight),
        "app.hello": _wrap_handler(_hello.app_hello),
        "app.readiness": _wrap_handler(_readiness.app_readiness),
        "app.dashboard": _wrap_handler(_dashboard.app_dashboard),
        "app.scan.containers": _wrap_handler(_scan_handlers.app_scan_containers),
        "app.scan.panes": _wrap_handler(_scan_handlers.app_scan_panes),
        "app.scan.status": _wrap_handler(_scan_handlers.app_scan_status),
        "app.pane.list": _wrap_handler(_reads.app_pane_list),
        "app.pane.detail": _wrap_handler(_reads.app_pane_detail),
        "app.agent.list": _wrap_handler(_reads.app_agent_list),
        "app.agent.detail": _wrap_handler(_reads.app_agent_detail),
    }


APP_DISPATCH: dict[str, _AppHandler] = _build_app_dispatch()


_APP_NAMESPACE_PREFIX = "app."


def is_app_method(name: str) -> bool:
    """Return whether ``name`` belongs to the FEAT-011 ``app.*`` namespace.

    Used by the FEAT-002 dispatcher (server.py) to decide whether an
    unknown method name should get the FEAT-011 envelope shape instead
    of the legacy FEAT-002 ``make_error`` shape. T098.
    """
    return isinstance(name, str) and name.startswith(_APP_NAMESPACE_PREFIX)


def make_unknown_method_envelope(method: str) -> dict[str, Any]:
    """Return the FR-033-compliant ``unknown_method`` envelope for an
    ``app.*`` method name not present in DISPATCH.

    Shape: ``{ok: false, app_contract_version, error: {code, message,
    details: {}}}``. Per FR-034b the ``details`` are always empty for
    ``unknown_method`` regardless of cause (typo vs future-minor vs
    nonexistent). T098.
    """
    # Lazy import to avoid module-load cycle with envelope.py → errors.py.
    from . import envelope as _envelope
    from .errors import UNKNOWN_METHOD

    return _envelope.failure(
        UNKNOWN_METHOD,
        f"unknown app.* method: {method}",
        details={},
    )


__all__ = [
    "APP_DISPATCH",
    "is_app_method",
    "make_unknown_method_envelope",
]
