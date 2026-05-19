"""Snapshot test for socket DISPATCH stability (T091 / FR-022 / FR-023).

The dispatch table's KEY ORDER is part of the FEAT-002 stability rule
(insertion order preserved across feature versions). FEAT-001..005
established the first seven entries; FEAT-006 appended five more;
FEAT-007 appended four more; FEAT-008 appended five more; FEAT-009
appended eight more; FEAT-010 appended six more (routes.*); FEAT-011
appended four more (app.* host-only namespace, FR-001/FR-002/FR-042).
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
    "app.preflight",
    "app.hello",
    "app.readiness",
    "app.dashboard",
]


def test_dispatch_table_key_order_is_locked() -> None:
    assert list(DISPATCH.keys()) == EXPECTED_ORDER


def test_dispatch_table_is_exactly_thirtynine_entries() -> None:
    """35 legacy (FEAT-002..010) + 4 new (FEAT-011 app.*) = 39."""
    assert len(DISPATCH) == 39
