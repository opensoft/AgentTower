"""Container-runtime detection (FR-003, FR-004, R-003).

Closed-set OR-pipeline over three signals:

1. ``/.dockerenv`` exists (Docker classic marker).
2. ``/run/.containerenv`` exists (Podman marker).
3. Any line in ``/proc/self/cgroup`` whose final segment matches the closed
   prefix set ``{docker/, containerd/, kubepods/, lxc/}``.

If any signal fires, the runtime context is ``ContainerContext`` carrying the
set of signals that fired. Otherwise ``HostContext()``. None of the signals
requires root, none requires a subprocess (FR-011, FR-020).

The detector is rooted at ``os.environ.get("AGENTTOWER_TEST_PROC_ROOT", "/")``
so test fixtures can substitute a fake ``/proc`` + ``/etc`` without touching
the real filesystem (R-011, FR-025).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

CGROUP_PREFIXES: tuple[str, ...] = ("docker/", "containerd/", "kubepods/", "lxc/")
"""Closed FR-004 cgroup-prefix set. Order is fixed for token-stability tests."""

# FR-004's runtime-detection rule is the simple "line contains one of these
# prefix tokens anywhere" check. Identifier extraction (which DOES require
# scanning the segment after the prefix for a hex id) is a separate concern
# implemented in ``identity.py`` per FR-006. A typical Docker cgroup looks
# like ``0::/docker/abc123def456``; a Kubernetes pod looks like
# ``0::/kubepods/burstable/pod-uuid/abc123def456``; a containerd shim looks
# like ``0::/system.slice/containerd.service``. All three carry the prefix
# token literally.
_CGROUP_PATTERN = re.compile(
    "|".join(re.escape(p) for p in CGROUP_PREFIXES)
)


DetectionSignal = Literal["dockerenv", "containerenv", "cgroup"]


@dataclass(frozen=True)
class HostContext:
    """The CLI is running outside any recognized container runtime."""


@dataclass(frozen=True)
class ContainerContext:
    """The CLI is running inside a recognized container runtime.

    ``detection_signals`` carries the closed-set names of every signal that
    fired (one or more of ``dockerenv``, ``containerenv``, ``cgroup``).
    """

    detection_signals: tuple[DetectionSignal, ...] = field(default_factory=tuple)


RuntimeContext = HostContext | ContainerContext


def _resolve_proc_root(proc_root: str | None) -> Path:
    if proc_root is not None:
        return Path(proc_root)
    return Path(os.environ.get("AGENTTOWER_TEST_PROC_ROOT", "/"))


def _path_exists(root: Path, relative: str) -> bool:
    candidate = root / relative.lstrip("/")
    try:
        return candidate.exists()
    except OSError:
        return False


def _scan_cgroup(root: Path) -> bool:
    """Return True iff any /proc/self/cgroup line matches the closed prefix set."""
    cgroup_path = root / "proc" / "self" / "cgroup"
    try:
        with cgroup_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if _CGROUP_PATTERN.search(line):
                    return True
    except (OSError, IOError):
        return False
    return False


def detect(proc_root: str | None = None) -> RuntimeContext:
    """Detect whether the CLI is running inside a container runtime.

    Honors ``AGENTTOWER_TEST_PROC_ROOT`` when ``proc_root`` is ``None``.
    Returns ``ContainerContext`` with the set of signals that fired, or
    ``HostContext()`` when none fire.
    """

    root = _resolve_proc_root(proc_root)
    fired: list[DetectionSignal] = []

    if _path_exists(root, "/.dockerenv"):
        fired.append("dockerenv")
    if _path_exists(root, "/run/.containerenv"):
        fired.append("containerenv")
    if _scan_cgroup(root):
        fired.append("cgroup")

    if fired:
        return ContainerContext(detection_signals=tuple(fired))
    return HostContext()


__all__ = [
    "CGROUP_PREFIXES",
    "ContainerContext",
    "DetectionSignal",
    "HostContext",
    "RuntimeContext",
    "detect",
]
