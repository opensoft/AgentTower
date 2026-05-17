"""Snapshot test for socket DISPATCH stability (T091 / FR-022 / FR-023).

The dispatch table's KEY ORDER is part of the FEAT-002 stability rule
(insertion order preserved across feature versions). FEAT-001..005
established the first seven entries; FEAT-006 appended five more;
FEAT-007 appended four more; FEAT-008 appended five more; FEAT-009
appended eight more. This test pins the exact ordered key list so an
accidental re-ordering or added entry is caught immediately.
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
]


def test_dispatch_table_key_order_is_locked() -> None:
    assert list(DISPATCH.keys()) == EXPECTED_ORDER


def test_dispatch_table_is_exactly_thirtyfive_entries() -> None:
    assert len(DISPATCH) == 35
