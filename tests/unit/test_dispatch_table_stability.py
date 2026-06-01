"""Snapshot test for socket DISPATCH stability (T091 / FR-022 / FR-023).

The dispatch table's KEY ORDER is part of the FEAT-002 stability rule
(insertion order preserved across feature versions). FEAT-001..005
established the first seven entries; FEAT-006 appended five more;
FEAT-007 appended four more; FEAT-008 appended five more; FEAT-009
appended eight more; FEAT-010 appended six more (routes.*); FEAT-011
appended thirty-two more (app.* host-only namespace, US1 + US2 + US3; FR-001/FR-002/FR-042);
FEAT-013 appended sixteen more (8 app.managed_* + 8 legacy managed.*, T025).
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
    # FEAT-013 (managed session lifecycle; T025). Appended after the
    # FEAT-011 app.* block: 8 app.managed_* (host-only app namespace) then
    # 8 legacy managed.* (CLI + bench thin-client). FEAT-014 (app dashboard
    # v1.1) added NO new dispatch keys — its change is additive within the
    # existing app.dashboard method.
    "app.managed_layout_create",
    "app.managed_layout_list",
    "app.managed_layout_detail",
    "app.managed_pane_list",
    "app.managed_pane_detail",
    "app.managed_pane_remove",
    "app.managed_pane_recreate",
    "app.managed_pane_promote_from_adopted",
    "managed.layout.create",
    "managed.layout.list",
    "managed.layout.detail",
    "managed.pane.list",
    "managed.pane.detail",
    "managed.pane.remove",
    "managed.pane.recreate",
    "managed.pane.promote_from_adopted",
]


def test_dispatch_table_key_order_is_locked() -> None:
    assert list(DISPATCH.keys()) == EXPECTED_ORDER


def test_dispatch_table_is_exactly_eightythree_entries() -> None:
    """35 legacy (FEAT-002..010) + 32 (FEAT-011 app.*) + 16 (FEAT-013
    managed: 8 app.managed_* + 8 legacy managed.*) = 83.

    The FEAT-011 v1.0 ``app.*`` surface is 32 methods. FEAT-013 adds 16
    managed-session methods (T025). FEAT-014 (app dashboard v1.1) adds none
    — its evolution is additive within the existing ``app.dashboard``.
    """
    assert len(DISPATCH) == 83
