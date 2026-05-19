"""Snapshot test for socket DISPATCH stability (T091 / FR-022 / FR-023).

The dispatch table's KEY ORDER is part of the FEAT-002 stability rule
(insertion order preserved across feature versions). FEAT-001..005
established the first seven entries; FEAT-006 appended five more;
FEAT-007 appended four more; FEAT-008 appended five more; FEAT-009
appended eight more; FEAT-010 appended six more (routes.*); FEAT-011
appended twelve more (app.* host-only namespace, US1 + US2; FR-001/FR-002/FR-042).
This test pins the exact ordered key list so an accidental
re-ordering or added entry is caught immediately.
"""

from __future__ import annotations

from agenttower.socket_api.methods import DISPATCH


# Ordered list (NOT a set) — the dict's insertion order MUST match this.
EXPECTED_ORDER = [
    # FEAT-002.
    "ping",
    "status",
    "shutdown",
    # FEAT-003.
    "scan_containers",
    "list_containers",
    # FEAT-004.
    "scan_panes",
    "list_panes",
    # FEAT-006.
    "register_agent",
    "list_agents",
    "set_role",
    "set_label",
    "set_capability",
    # FEAT-007.
    "attach_log",
    "detach_log",
    "attach_log_status",
    "attach_log_preview",
    # FEAT-008.
    "events.list",
    "events.follow_open",
    "events.follow_next",
    "events.follow_close",
    "events.classifier_rules",
    # FEAT-009.
    "queue.send_input",
    "queue.list",
    "queue.approve",
    "queue.delay",
    "queue.cancel",
    "routing.enable",
    "routing.disable",
    "routing.status",
    # FEAT-010 (T030 — operator-facing routes.* CRUD).
    "routes.add",
    "routes.list",
    "routes.show",
    "routes.remove",
    "routes.enable",
    "routes.disable",
    # FEAT-011 (app.* host-only namespace; T002 / FR-001 / FR-042).
    # Appended via DISPATCH.update(APP_DISPATCH) at the end of
    # ``socket_api/methods.py``. Insertion order preserved by Python 3.7+ dict.
    # Order MUST match ``app_contract/dispatcher.py::_build_app_dispatch``.
    "app.preflight",
    "app.hello",
    "app.readiness",
    "app.dashboard",
    "app.scan.containers",
    "app.scan.panes",
    "app.scan.status",
    "app.pane.list",
    "app.pane.detail",
    "app.agent.list",
    "app.agent.detail",
    "app.agent.register_from_pane",
]


def test_dispatch_table_key_order_is_locked() -> None:
    assert list(DISPATCH.keys()) == EXPECTED_ORDER


def test_dispatch_table_is_exactly_fortyseven_entries() -> None:
    """35 legacy (FEAT-002..010) + 12 new (FEAT-011 app.*) = 47.

    The FEAT-011 v1.0 contract documents 30 ``app.*`` methods total
    (see ``contracts/app-methods.md`` §Method Count). This PR ships
    US1 (preflight/hello/readiness/dashboard) + US2 (scans + pane/agent
    reads + adopt mutation) = 12 methods. The remaining 18 are
    operator-mutation handlers shipping in US3.
    """
    assert len(DISPATCH) == 47
