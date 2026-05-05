"""User-facing AgentTower CLI entrypoint."""

from __future__ import annotations

from . import __version__


def main() -> int:
    """Run the AgentTower CLI."""
    print(f"agenttower {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
