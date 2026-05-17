"""FEAT-010 ``agenttower route`` CLI subcommands (T031).

Six subcommands per contracts/cli-routes.md:

- ``route add``     — create one route (FR-001 / FR-002)
- ``route list``    — list ordered by (created_at, route_id) (FR-046)
- ``route show``    — one route + runtime sub-object (FR-047)
- ``route remove``  — hard-delete (FR-003)
- ``route enable``  — set enabled=true, idempotent (FR-009)
- ``route disable`` — set enabled=false, idempotent (FR-009)

Each subcommand:

1. Resolves the daemon socket path via the standard CLI helper.
2. Calls the matching ``routes.*`` socket method via
   :func:`agenttower.socket_api.client.send_request`.
3. Maps the response: success → stdout (human or ``--json``);
   error → stderr + non-zero exit per
   :data:`agenttower.routing.route_errors.CLI_ERROR_CODES`.

The shape contract is documented in ``contracts/cli-routes.md``
and mirrored in :func:`_route_row_to_payload` on the daemon side.
This module is purely the CLI-side renderer.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from agenttower.socket_api.client import (
    DaemonError,
    DaemonUnavailable,
    send_request,
)


__all__ = ["register"]


# ──────────────────────────────────────────────────────────────────────
# Exit-code mapping (mirrors contracts/error-codes.md §1)
# ──────────────────────────────────────────────────────────────────────


# FEAT-002 conventional exit codes:
#   0 — success
#   2 — argument / validation error (FEAT-002 convention)
#   3 — daemon-returned error (every FEAT-010 closed-set code)
#   2 (or higher) — transient connection failures
_EXIT_OK = 0
_EXIT_ARG_ERROR = 2
_EXIT_DAEMON_ERROR = 3
_EXIT_DAEMON_UNAVAILABLE = 2


_DAEMON_UNAVAILABLE_MESSAGE = (
    "error: agenttowerd is not running (start it with `agenttowerd`)"
)


# ──────────────────────────────────────────────────────────────────────
# Subparser registration
# ──────────────────────────────────────────────────────────────────────


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``agenttower route`` subcommand group.

    Called from :mod:`agenttower.cli` after the FEAT-009 subparsers.
    """
    route = subparsers.add_parser(
        "route",
        help="manage FEAT-010 event-routing rules",
        description=(
            "Operator-facing CRUD for FEAT-010 routes. Routes are "
            "STRUCTURALLY IMMUTABLE in MVP — to change selectors, "
            "targeting, master selection, or template, use "
            "`route remove` + `route add` (FR-009a)."
        ),
    )
    route_subs = route.add_subparsers(dest="route_command", metavar="subcommand")
    route.set_defaults(_handler=lambda args: _print_route_usage(route))

    _register_add(route_subs)
    _register_list(route_subs)
    _register_show(route_subs)
    _register_remove(route_subs)
    _register_enable(route_subs)
    _register_disable(route_subs)


def _print_route_usage(parser: argparse.ArgumentParser) -> int:
    parser.print_help(sys.stderr)
    return _EXIT_ARG_ERROR


# ──────────────────────────────────────────────────────────────────────
# `route add`
# ──────────────────────────────────────────────────────────────────────


def _register_add(subs: argparse._SubParsersAction) -> None:
    p = subs.add_parser(
        "add",
        help="create one route (FR-001/002)",
        description=(
            "Create a route subscribing to a FEAT-008 event type. The "
            "new route's cursor initializes to MAX(events.event_id) — "
            "it will NEVER fire on historical events (FR-002)."
        ),
    )
    p.add_argument("--event-type", required=True, help="FEAT-008 closed-set event type")
    p.add_argument(
        "--source-scope", default="any",
        choices=("any", "agent_id", "role"),
        help="source scope kind (default: any)",
    )
    p.add_argument(
        "--source-scope-value", default=None,
        help="agt_<12-hex> when --source-scope=agent_id; role:<r>[,capability:<c>] when --source-scope=role",
    )
    p.add_argument(
        "--target-rule", required=True,
        choices=("explicit", "source", "role"),
    )
    p.add_argument(
        "--target", default=None, dest="target_value",
        help="agt_<12-hex> or label for --target-rule=explicit; role:<r>[,capability:<c>] for --target-rule=role; omit for --target-rule=source",
    )
    p.add_argument(
        "--master-rule", default="auto",
        choices=("auto", "explicit"),
    )
    p.add_argument(
        "--master", default=None, dest="master_value",
        help="agt_<12-hex> when --master-rule=explicit",
    )
    p.add_argument("--template", required=True, help="render template with {field} placeholders from FR-008 whitelist")
    p.add_argument("--json", action="store_true", help="emit one JSON object to stdout")
    p.set_defaults(_handler=_cmd_add)


def _cmd_add(args: argparse.Namespace) -> int:
    return _call_and_render(
        method="routes.add",
        params={
            "event_type": args.event_type,
            "source_scope_kind": args.source_scope,
            "source_scope_value": args.source_scope_value,
            "target_rule": args.target_rule,
            "target_value": args.target_value,
            "master_rule": args.master_rule,
            "master_value": args.master_value,
            "template": args.template,
        },
        json_mode=args.json,
        render_human=_render_add_human,
    )


def _render_add_human(result: dict[str, Any]) -> None:
    print(
        f"created route {result['route_id']} "
        f"(event_type={result['event_type']} "
        f"enabled={str(result['enabled']).lower()} "
        f"cursor={result['last_consumed_event_id']})"
    )


# ──────────────────────────────────────────────────────────────────────
# `route list`
# ──────────────────────────────────────────────────────────────────────


def _register_list(subs: argparse._SubParsersAction) -> None:
    p = subs.add_parser(
        "list",
        help="list routes by (created_at, route_id) (FR-046)",
    )
    p.add_argument("--enabled-only", action="store_true", help="restrict to enabled routes only")
    p.add_argument("--json", action="store_true", help="emit JSON array to stdout")
    p.set_defaults(_handler=_cmd_list)


def _cmd_list(args: argparse.Namespace) -> int:
    return _call_and_render(
        method="routes.list",
        params={"enabled_only": bool(args.enabled_only)},
        json_mode=args.json,
        render_human=_render_list_human,
        # The socket returns {"routes": [...]} but operators expect the
        # bare array under --json (per contracts/cli-routes.md §2). The
        # renderer collapses for both modes.
        json_extract=lambda r: r["routes"],
    )


def _render_list_human(result: dict[str, Any]) -> None:
    rows = result["routes"]
    enabled = sum(1 for r in rows if r["enabled"])
    disabled = len(rows) - enabled
    print(f"listed {len(rows)} routes ({enabled} enabled, {disabled} disabled)")
    for r in rows:
        flag = "ON " if r["enabled"] else "OFF"
        print(f"  {flag} {r['route_id']} {r['event_type']:24s} → {r['target_rule']}={r['target_value'] or '-'}")


# ──────────────────────────────────────────────────────────────────────
# `route show`
# ──────────────────────────────────────────────────────────────────────


def _register_show(subs: argparse._SubParsersAction) -> None:
    p = subs.add_parser(
        "show",
        help="show one route + runtime stats (FR-047)",
    )
    p.add_argument("route_id", help="route UUIDv4")
    p.add_argument("--json", action="store_true")
    p.set_defaults(_handler=_cmd_show)


def _cmd_show(args: argparse.Namespace) -> int:
    return _call_and_render(
        method="routes.show",
        params={"route_id": args.route_id},
        json_mode=args.json,
        render_human=_render_show_human,
    )


def _render_show_human(result: dict[str, Any]) -> None:
    runtime = result.get("runtime", {})
    print(
        f"showed route {result['route_id']} "
        f"(events_consumed={runtime.get('events_consumed', 0)} "
        f"last_skip_reason={runtime.get('last_skip_reason')})"
    )


# ──────────────────────────────────────────────────────────────────────
# `route remove` / `enable` / `disable` — same shape
# ──────────────────────────────────────────────────────────────────────


def _register_remove(subs: argparse._SubParsersAction) -> None:
    p = subs.add_parser("remove", help="hard-delete one route (FR-003)")
    p.add_argument("route_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(_handler=_cmd_remove)


def _cmd_remove(args: argparse.Namespace) -> int:
    return _call_and_render(
        method="routes.remove",
        params={"route_id": args.route_id},
        json_mode=args.json,
        render_human=lambda r: print(f"removed route {r['route_id']}"),
    )


def _register_enable(subs: argparse._SubParsersAction) -> None:
    p = subs.add_parser("enable", help="set enabled=true (FR-009 idempotent)")
    p.add_argument("route_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(_handler=_cmd_enable)


def _cmd_enable(args: argparse.Namespace) -> int:
    return _call_and_render(
        method="routes.enable",
        params={"route_id": args.route_id},
        json_mode=args.json,
        render_human=lambda r: print(f"enabled route {r['route_id']}"),
    )


def _register_disable(subs: argparse._SubParsersAction) -> None:
    p = subs.add_parser("disable", help="set enabled=false (FR-009 idempotent)")
    p.add_argument("route_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(_handler=_cmd_disable)


def _cmd_disable(args: argparse.Namespace) -> int:
    return _call_and_render(
        method="routes.disable",
        params={"route_id": args.route_id},
        json_mode=args.json,
        render_human=lambda r: print(f"disabled route {r['route_id']}"),
    )


# ──────────────────────────────────────────────────────────────────────
# Shared socket + render plumbing
# ──────────────────────────────────────────────────────────────────────


def _call_and_render(
    *,
    method: str,
    params: dict[str, Any],
    json_mode: bool,
    render_human,
    json_extract=None,
) -> int:
    """Send one socket request + render the response.

    json_extract: optional callable to extract the JSON-mode payload
    from the full result dict (default: emit the full dict). Used by
    ``route list`` which returns ``{"routes": [...]}`` on the wire but
    a bare array to stdout per contracts/cli-routes.md §2.
    """
    # Reuse the canonical CLI socket-resolution helper so this module
    # gets daemon-discovery + the standard FEAT-002 unavailable-message
    # contract for free.
    from agenttower.cli import _resolve_socket_with_paths

    _paths, resolved = _resolve_socket_with_paths()

    try:
        result = send_request(
            resolved.path, method, params,
            connect_timeout=2.0, read_timeout=10.0,
        )
    except DaemonUnavailable:
        print(_DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return _EXIT_DAEMON_UNAVAILABLE
    except DaemonError as exc:
        print(f"error: {exc.code}: {exc.message}", file=sys.stderr)
        return _EXIT_DAEMON_ERROR

    if json_mode:
        payload = json_extract(result) if json_extract else result
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        render_human(result)
    return _EXIT_OK
