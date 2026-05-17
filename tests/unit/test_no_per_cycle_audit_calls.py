"""T058 — AST invariant: routing worker must NOT emit per-cycle audit.

Per Clarifications Q3 / FR-035 / contracts/routes-audit-schema.md
§AST-test invariant: the routing worker's hot path may only emit
the five per-(route, event) and per-route-lifecycle audit event
types — NEVER ``routing_cycle_started`` or ``routing_cycle_completed``.

Per-cycle audit emission was explicitly rejected during clarify
because at the 1-second default cycle interval it would produce
~172,800 JSONL entries/day of pure noise that drowns out real
audit signal. Cycle-level observability lives in ``agenttower
status`` (last_routing_cycle_at + counters) and in the rate-
limited ``routing_worker_heartbeat`` audit entry (default 60s
cadence per FR-039a).

This AST walk asserts the contract by inspecting the source of
:mod:`agenttower.routing.worker` and confirming no string literal
``routing_cycle_*`` appears. A future refactor that accidentally
introduces per-cycle emission fails this test immediately at
code-review time.
"""

from __future__ import annotations

import ast
import inspect

from agenttower.routing import worker as wkr


def test_worker_source_has_no_routing_cycle_started_literal() -> None:
    source = inspect.getsource(wkr)
    assert "routing_cycle_started" not in source, (
        "FR-035 / Clarifications Q3 violation: the routing worker "
        "MUST NOT emit 'routing_cycle_started' audit entries — cycle "
        "observability lives in `agenttower status` + the rate-limited "
        "`routing_worker_heartbeat` per FR-039a."
    )


def test_worker_source_has_no_routing_cycle_completed_literal() -> None:
    source = inspect.getsource(wkr)
    assert "routing_cycle_completed" not in source, (
        "FR-035 / Clarifications Q3 violation: the routing worker "
        "MUST NOT emit 'routing_cycle_completed' audit entries — cycle "
        "observability lives in `agenttower status` + the rate-limited "
        "`routing_worker_heartbeat` per FR-039a."
    )


def test_worker_emit_calls_only_use_documented_six_audit_methods() -> None:
    """Walk every Call node in worker.py; assert every `emit_route_*`
    method call goes through the documented set of six methods on the
    audit writer (route_matched / route_skipped / route_created /
    route_updated / route_deleted / routing_worker_heartbeat). Any
    `emit_routing_cycle_*` or other `emit_*` method call would fail
    this test."""
    source = inspect.getsource(wkr)
    tree = ast.parse(source)

    allowed_emit_methods = {
        "emit_route_matched",
        "emit_route_skipped",
        # The worker itself does NOT emit catalog (created/updated/
        # deleted) or heartbeat entries; those are emitted by
        # routes_service.py / heartbeat.py respectively. But if a
        # future refactor moves them in, they're still valid.
        "emit_route_created",
        "emit_route_updated",
        "emit_route_deleted",
        "emit_routing_worker_heartbeat",
    }

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Look for self._audit.emit_*(...) or similar attribute calls.
        if not isinstance(node.func, ast.Attribute):
            continue
        method_name = node.func.attr
        if method_name.startswith("emit_"):
            assert method_name in allowed_emit_methods, (
                f"FR-035 / Clarifications Q3 violation: worker.py "
                f"emits {method_name!r}, which is not in the documented "
                f"set of six audit emit methods. Allowed: "
                f"{sorted(allowed_emit_methods)}"
            )
