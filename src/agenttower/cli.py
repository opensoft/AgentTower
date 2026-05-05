"""User-facing AgentTower CLI entrypoint."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import _DIR_MODE, _ensure_dir_chain, write_default_config
from .paths import Paths, resolve_paths
from .state.schema import companion_paths_for, open_registry


def _namespace_root(any_member: Path) -> Path:
    """Return the deepest ``opensoft/agenttower`` ancestor of *any_member*."""
    for parent in [any_member, *any_member.parents]:
        if parent.parent.name == "opensoft" and parent.name == "agenttower":
            return parent
    raise ValueError(f"path {any_member} is not under an opensoft/agenttower namespace")


def _config_init(args: argparse.Namespace) -> int:
    paths: Paths = resolve_paths()

    config_namespace = _namespace_root(paths.config_file)
    state_namespace = _namespace_root(paths.state_db)
    cache_namespace = paths.cache_dir

    state_db_pre_existed_companions = {
        p: p.exists() for p in companion_paths_for(paths.state_db)
    }
    state_db_pre_existed = paths.state_db.exists()

    try:
        _ensure_dir_chain(paths.config_file.parent, namespace_root=config_namespace)
        _ensure_dir_chain(paths.logs_dir, namespace_root=state_namespace)
        _ensure_dir_chain(paths.cache_dir, namespace_root=cache_namespace)

        config_status = write_default_config(
            paths.config_file, namespace_root=config_namespace
        )
        conn, registry_status = open_registry(
            paths.state_db, namespace_root=state_namespace
        )
        conn.close()
    except (OSError, sqlite3.Error) as exc:
        if isinstance(exc, OSError):
            verb = "initialize"
            path = exc.filename or "<unknown>"
            reason = exc.strerror or str(exc)
        else:
            verb = "open registry"
            path = str(paths.state_db)
            reason = str(exc)

        if not state_db_pre_existed and paths.state_db.exists():
            try:
                paths.state_db.unlink()
            except OSError:
                pass
        for companion, was_present in state_db_pre_existed_companions.items():
            if not was_present and companion.exists():
                try:
                    companion.unlink()
                except OSError:
                    pass

        print(f"error: {verb}: {path}: {reason}", file=sys.stderr)
        return 1

    config_prefix = "created config" if config_status == "created" else "already initialized"
    registry_prefix = "created registry" if registry_status == "created" else "already initialized"
    print(f"{config_prefix}: {paths.config_file}")
    print(f"{registry_prefix}: {paths.state_db}")
    return 0


def _config_paths(args: argparse.Namespace) -> int:
    paths: Paths = resolve_paths()
    print(f"CONFIG_FILE={paths.config_file}")
    print(f"STATE_DB={paths.state_db}")
    print(f"EVENTS_FILE={paths.events_file}")
    print(f"LOGS_DIR={paths.logs_dir}")
    print(f"SOCKET={paths.socket}")
    print(f"CACHE_DIR={paths.cache_dir}")
    if not paths.state_db.exists():
        print(
            "note: agenttower has not been initialized; run `agenttower config init`",
            file=sys.stderr,
        )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenttower",
        description="AgentTower CLI — local-first agent control plane.",
        epilog=(
            "config subcommands:\n"
            "  config paths   print resolved KEY=value paths AgentTower will use\n"
            "  config init    create the durable Opensoft layout (idempotent)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"agenttower {__version__}",
    )
    parser.set_defaults(_handler=None)

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    config = subparsers.add_parser(
        "config",
        help="inspect and initialize AgentTower's host layout",
        description="inspect and initialize AgentTower's host layout",
    )
    config.set_defaults(_handler=lambda args: _print_subusage_and_exit(config))

    config_subs = config.add_subparsers(dest="config_command", metavar="subcommand")

    paths_parser = config_subs.add_parser(
        "paths",
        help="print resolved KEY=value paths AgentTower will use",
        description="print resolved KEY=value paths AgentTower will use",
    )
    paths_parser.set_defaults(_handler=_config_paths)

    init_parser = config_subs.add_parser(
        "init",
        help="create the durable Opensoft layout (idempotent)",
        description="create the durable Opensoft layout (idempotent)",
    )
    init_parser.set_defaults(_handler=_config_init)

    return parser


def _print_subusage_and_exit(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the AgentTower CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler: Any = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
