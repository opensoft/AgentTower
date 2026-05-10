"""FR-060 / T077 — the ``AGENTTOWER_TEST_LOG_FS_FAKE`` seam is single-source.

The host-filesystem test seam lives in ``src/agenttower/logs/host_fs.py`` and
nowhere else. If any other production module imports it directly, the
seam's contract (Research R-013) is violated: tests can no longer
assume that swapping the env var yields a clean fake-fs world for every
caller, and the seam stops being auditable from one place.

This is the FEAT-007 analog of T220's ``eval``/``exec``/``subprocess``
gate (``test_no_log_content_execution.py``), enforcing FR-060 by AST scan.

If a future module legitimately needs the seam, route through
``logs.host_fs`` rather than reading the env var directly.
"""

from __future__ import annotations

import ast
import pathlib

import pytest


SEAM_ENV_VAR = "AGENTTOWER_TEST_LOG_FS_FAKE"
SRC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "agenttower"
ALLOWED_OWNER = SRC_ROOT / "logs" / "host_fs.py"


def _iter_production_modules() -> list[pathlib.Path]:
    """Every .py file under src/agenttower/, excluding the test seam owner."""
    return [
        p for p in SRC_ROOT.rglob("*.py")
        if p.resolve() != ALLOWED_OWNER.resolve()
    ]


def _references_seam(tree: ast.AST) -> bool:
    """True iff this module syntactically references the seam env-var name."""
    for node in ast.walk(tree):
        # Direct string literal of the env-var name.
        if isinstance(node, ast.Constant) and node.value == SEAM_ENV_VAR:
            return True
    return False


@pytest.mark.parametrize(
    "path",
    _iter_production_modules(),
    ids=lambda p: str(p.relative_to(SRC_ROOT)),
)
def test_module_does_not_reference_log_fs_fake_seam(path: pathlib.Path) -> None:
    """Production module MUST NOT mention ``AGENTTOWER_TEST_LOG_FS_FAKE``.

    Only ``logs/host_fs.py`` is allowed to read the env var. Other modules
    that need fs observation must route through ``host_fs.stat_log_file`` /
    ``host_fs.file_exists`` / ``host_fs.read_tail_lines``.
    """
    source = path.read_text(encoding="utf-8")
    if SEAM_ENV_VAR not in source:
        return  # Fast path: file doesn't even mention the string.
    tree = ast.parse(source, filename=str(path))
    assert not _references_seam(tree), (
        f"{path.relative_to(SRC_ROOT)} references the FR-060 seam "
        f"{SEAM_ENV_VAR!r}; only logs/host_fs.py is allowed to read it."
    )


def test_seam_owner_does_reference_seam() -> None:
    """Sanity check: the allowed owner module MUST reference the env var.

    Catches a future refactor that accidentally moves the seam without
    updating ``ALLOWED_OWNER``.
    """
    source = ALLOWED_OWNER.read_text(encoding="utf-8")
    assert SEAM_ENV_VAR in source, (
        f"{ALLOWED_OWNER} no longer references {SEAM_ENV_VAR}; "
        "update ALLOWED_OWNER if the seam moved."
    )
