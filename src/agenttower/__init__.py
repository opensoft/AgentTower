"""AgentTower package."""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("agenttower")
except PackageNotFoundError:
    __version__ = "0.0.0+local"
