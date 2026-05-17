"""T028 — FEAT-010 ``agenttower route`` CLI contract tests.

Asserts the CLI parser construction + the dispatch wiring matches
contracts/cli-routes.md:

* The ``agenttower route`` subparser group registers all six
  subcommands (add, list, show, remove, enable, disable).
* Each subcommand has the documented required + optional flag set.
* Flag rejection at argparse layer surfaces with exit code 2.

The actual socket round-trip is covered by
``test_socket_routes.py`` (T027) — this test exercises the CLI
parser surface in isolation (no daemon required) by inspecting
the parser tree.
"""

from __future__ import annotations

import argparse

import pytest

from agenttower.cli import _build_parser


@pytest.fixture(scope="module")
def parser() -> argparse.ArgumentParser:
    return _build_parser()


def _find_subparser(
    parser: argparse.ArgumentParser, *path: str,
) -> argparse.ArgumentParser:
    """Walk down a chain of subparser groups, returning the inner parser."""
    current = parser
    for name in path:
        sub_action = next(
            a for a in current._actions
            if isinstance(a, argparse._SubParsersAction)
        )
        assert name in sub_action.choices, (
            f"{name!r} not found in {list(sub_action.choices.keys())}"
        )
        current = sub_action.choices[name]
    return current


def _flag_names(parser: argparse.ArgumentParser) -> set[str]:
    return {
        opt
        for action in parser._actions
        for opt in action.option_strings
        if opt.startswith("--")
    }


# ──────────────────────────────────────────────────────────────────────
# Subcommand registration
# ──────────────────────────────────────────────────────────────────────


def test_route_subcommand_group_registered(parser: argparse.ArgumentParser) -> None:
    sub_action = next(
        a for a in parser._actions
        if isinstance(a, argparse._SubParsersAction)
    )
    assert "route" in sub_action.choices


@pytest.mark.parametrize(
    "subcommand",
    ["add", "list", "show", "remove", "enable", "disable"],
)
def test_each_route_subcommand_registered(
    parser: argparse.ArgumentParser, subcommand: str,
) -> None:
    route = _find_subparser(parser, "route")
    sub_action = next(
        a for a in route._actions
        if isinstance(a, argparse._SubParsersAction)
    )
    assert subcommand in sub_action.choices


# ──────────────────────────────────────────────────────────────────────
# `route add` — flag set per contracts/cli-routes.md §1
# ──────────────────────────────────────────────────────────────────────


def test_route_add_required_flags_present(parser: argparse.ArgumentParser) -> None:
    add = _find_subparser(parser, "route", "add")
    flags = _flag_names(add)
    # Required per contract.
    assert "--event-type" in flags
    assert "--target-rule" in flags
    assert "--template" in flags
    # Optional but documented in contract.
    assert "--source-scope" in flags
    assert "--source-scope-value" in flags
    assert "--target" in flags
    assert "--master-rule" in flags
    assert "--master" in flags
    assert "--json" in flags


def test_route_add_missing_required_flag_exits_two(
    parser: argparse.ArgumentParser, capsys: pytest.CaptureFixture[str],
) -> None:
    """Missing --event-type → argparse exit 2 (FEAT-002 convention)."""
    with pytest.raises(SystemExit) as info:
        parser.parse_args(["route", "add",
                           "--target-rule", "explicit", "--target", "agt_a1b2c3d4e5f6",
                           "--template", "x"])
    assert info.value.code == 2


def test_route_add_source_scope_choices_restricted(
    parser: argparse.ArgumentParser,
) -> None:
    """argparse rejects out-of-set --source-scope BEFORE any socket call."""
    with pytest.raises(SystemExit) as info:
        parser.parse_args([
            "route", "add",
            "--event-type", "waiting_for_input",
            "--source-scope", "not_a_kind",
            "--target-rule", "explicit",
            "--target", "agt_a1b2c3d4e5f6",
            "--template", "x",
        ])
    assert info.value.code == 2


def test_route_add_master_rule_choices_restricted(
    parser: argparse.ArgumentParser,
) -> None:
    with pytest.raises(SystemExit) as info:
        parser.parse_args([
            "route", "add",
            "--event-type", "waiting_for_input",
            "--target-rule", "explicit",
            "--target", "agt_a1b2c3d4e5f6",
            "--master-rule", "round_robin",
            "--template", "x",
        ])
    assert info.value.code == 2


def test_route_add_target_rule_choices_restricted(
    parser: argparse.ArgumentParser,
) -> None:
    with pytest.raises(SystemExit) as info:
        parser.parse_args([
            "route", "add",
            "--event-type", "waiting_for_input",
            "--target-rule", "not_a_rule",
            "--template", "x",
        ])
    assert info.value.code == 2


# ──────────────────────────────────────────────────────────────────────
# `route list`
# ──────────────────────────────────────────────────────────────────────


def test_route_list_flags(parser: argparse.ArgumentParser) -> None:
    listp = _find_subparser(parser, "route", "list")
    flags = _flag_names(listp)
    assert "--enabled-only" in flags
    assert "--json" in flags


def test_route_list_no_args_parses_clean(parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args(["route", "list"])
    assert args.route_command == "list"
    assert args.enabled_only is False
    assert args.json is False
    assert callable(args._handler)


# ──────────────────────────────────────────────────────────────────────
# `route show` / `remove` / `enable` / `disable` — positional route_id
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "subcommand",
    ["show", "remove", "enable", "disable"],
)
def test_route_lifecycle_subcommand_takes_route_id_positional(
    parser: argparse.ArgumentParser, subcommand: str,
) -> None:
    args = parser.parse_args([
        "route", subcommand, "11111111-2222-4333-8444-555555555555",
    ])
    assert args.route_command == subcommand
    assert args.route_id == "11111111-2222-4333-8444-555555555555"
    assert callable(args._handler)


@pytest.mark.parametrize(
    "subcommand",
    ["show", "remove", "enable", "disable"],
)
def test_route_lifecycle_missing_route_id_exits_two(
    parser: argparse.ArgumentParser, subcommand: str,
) -> None:
    with pytest.raises(SystemExit) as info:
        parser.parse_args(["route", subcommand])
    assert info.value.code == 2


@pytest.mark.parametrize(
    "subcommand",
    ["show", "remove", "enable", "disable"],
)
def test_route_lifecycle_json_flag_available(
    parser: argparse.ArgumentParser, subcommand: str,
) -> None:
    sub = _find_subparser(parser, "route", subcommand)
    assert "--json" in _flag_names(sub)


# ──────────────────────────────────────────────────────────────────────
# Handler wiring
# ──────────────────────────────────────────────────────────────────────


def test_route_top_level_has_handler(parser: argparse.ArgumentParser) -> None:
    """``agenttower route`` with no subcommand prints usage + exits 2."""
    args = parser.parse_args(["route"])
    assert args.route_command is None
    assert callable(args._handler)


def test_route_add_handler_is_callable(parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args([
        "route", "add",
        "--event-type", "waiting_for_input",
        "--target-rule", "explicit",
        "--target", "agt_a1b2c3d4e5f6",
        "--template", "hello {event_excerpt}",
    ])
    assert callable(args._handler)
    assert args.event_type == "waiting_for_input"
    assert args.target_rule == "explicit"
    assert args.target_value == "agt_a1b2c3d4e5f6"
    assert args.template == "hello {event_excerpt}"
