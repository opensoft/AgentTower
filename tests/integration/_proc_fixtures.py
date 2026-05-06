"""Test seam fixtures for FEAT-005's ``AGENTTOWER_TEST_PROC_ROOT`` (R-011, FR-025).

Materializes a controlled fake ``/proc`` + ``/etc`` tree under a pytest
``tmp_path`` so the in-container detection helpers (``runtime_detect.py``,
``identity.py``) can be unit-tested without touching the real filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pytest


def _materialize_fake_root(
    root: Path,
    *,
    dockerenv: bool,
    containerenv: bool,
    cgroup_lines: Iterable[str] | None,
    pid1_cgroup_lines: Iterable[str] | None,
    hostname: str | None,
) -> Path:
    """Create the fake-/proc + fake-/etc tree under ``root``.

    The tree contains the closed set of paths FEAT-005 inspects (R-011):
    ``/.dockerenv``, ``/run/.containerenv``, ``/proc/self/cgroup``,
    ``/proc/1/cgroup``, ``/etc/hostname``. No other path is touched.
    """

    proc_self = root / "proc" / "self"
    proc_one = root / "proc" / "1"
    etc = root / "etc"
    run = root / "run"

    proc_self.mkdir(parents=True, exist_ok=True)
    proc_one.mkdir(parents=True, exist_ok=True)
    etc.mkdir(parents=True, exist_ok=True)
    run.mkdir(parents=True, exist_ok=True)

    if dockerenv:
        (root / ".dockerenv").write_text("")
    if containerenv:
        (run / ".containerenv").write_text("")

    if cgroup_lines is not None:
        (proc_self / "cgroup").write_text("\n".join(cgroup_lines) + "\n")
    else:
        (proc_self / "cgroup").write_text("")

    if pid1_cgroup_lines is not None:
        (proc_one / "cgroup").write_text("\n".join(pid1_cgroup_lines) + "\n")
    else:
        (proc_one / "cgroup").write_text("")

    if hostname is not None:
        (etc / "hostname").write_text(hostname + "\n")

    return root


@pytest.fixture
def fake_proc_root(tmp_path: Path):
    """Pytest fixture returning a builder for a fake `/proc` + `/etc` tree.

    Usage::

        def test_x(fake_proc_root):
            root = fake_proc_root(dockerenv=True, cgroup_lines=["..."])
            # use root as AGENTTOWER_TEST_PROC_ROOT value
    """

    def _build(
        *,
        dockerenv: bool = False,
        containerenv: bool = False,
        cgroup_lines: Iterable[str] | None = None,
        pid1_cgroup_lines: Iterable[str] | None = None,
        hostname: str | None = None,
    ) -> Path:
        return _materialize_fake_root(
            tmp_path,
            dockerenv=dockerenv,
            containerenv=containerenv,
            cgroup_lines=cgroup_lines,
            pid1_cgroup_lines=pid1_cgroup_lines,
            hostname=hostname,
        )

    return _build


__all__ = ["fake_proc_root"]
