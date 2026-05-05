"""AgentTower daemon entrypoint."""

from __future__ import annotations

import argparse

from . import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenttowerd",
        description="AgentTower daemon (FEAT-001 stub: --version only).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"agenttowerd {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the AgentTower daemon (FEAT-001 stub)."""
    parser = _build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
