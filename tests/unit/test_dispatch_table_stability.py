"""Snapshot test for socket DISPATCH stability (T091 / FR-022 / FR-023).

The dispatch table's KEY ORDER is part of the FEAT-002 stability rule
(insertion order preserved across feature versions). FEAT-001..005
established the first seven entries; FEAT-006 appended five more;
FEAT-007 appended four more; FEAT-008 appended five more; FEAT-009
appended eight more; FEAT-010 appended six more (routes.*); FEAT-011
appended thirty-two more (app.* host-only namespace, US1 + US2 + US3; FR-001/FR-002/FR-042).
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
    # US3 — remaining entity reads (T054–T058).
    "app.container.list",
    "app.container.detail",
    "app.log_attachment.list",
    "app.log_attachment.detail",
    "app.event.list",
    "app.event.detail",
    "app.queue.list",
    "app.queue.detail",
    "app.route.list",
    "app.route.detail",
    # US3 — operator mutations (T060–T065).
    "app.agent.update",
    "app.log.attach",
    "app.log.detach",
    "app.send_input",
    "app.queue.approve",
    "app.queue.delay",
    "app.queue.cancel",
    "app.route.add",
    "app.route.remove",
    "app.route.update",
]


def test_dispatch_table_key_order_is_locked() -> None:
    assert list(DISPATCH.keys()) == EXPECTED_ORDER


def test_dispatch_table_is_exactly_sixtyseven_entries() -> None:
    """35 legacy (FEAT-002..010) + 32 new (FEAT-011 app.*) = 67.

    The full FEAT-011 v1.0 ``app.*`` surface is 32 methods: 4 bootstrap/
    dashboard + 3 scans + 14 entity reads (7 entities × list/detail) +
    1 adopt mutation + 10 operator mutations. US1+US2 shipped 12; US3
    (this phase) adds the remaining 20.
    """
    assert len(DISPATCH) == 67
