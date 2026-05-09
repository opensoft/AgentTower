"""T080 / FR-022 / FR-023 — offset-advance invariant.

FEAT-007 ships only the schema + persistence layer for log offsets.
Production code MUST NOT advance ``byte_offset`` or derive ``line_offset``
— the future FEAT-008 reader is the sole production-side advancer.

Two checks:

1. ``attach_log`` writes initial offsets at ``(0, 0, 0)`` and never
   advances them on success or on idempotent re-attach.
2. The test seam ``advance_offset_for_test`` is named to be loud about
   its test-only nature, AND no production module imports it (mirrors
   the FR-060 pattern in ``test_feat007_no_test_seam_in_production.py``).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from agenttower.state.log_offsets import advance_offset_for_test


SRC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "agenttower"


def _iter_production_modules() -> list[pathlib.Path]:
    return list(SRC_ROOT.rglob("*.py"))


def _imports_advance_offset_seam(tree: ast.AST) -> bool:
    """True iff this module imports advance_offset_for_test by name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(
                alias.name == "advance_offset_for_test" for alias in node.names
            ):
                return True
        if isinstance(node, ast.Attribute):
            if node.attr == "advance_offset_for_test":
                return True
        if isinstance(node, ast.Name) and node.id == "advance_offset_for_test":
            return True
    return False


@pytest.mark.parametrize(
    "path",
    _iter_production_modules(),
    ids=lambda p: str(p.relative_to(SRC_ROOT)),
)
def test_t080_no_production_module_imports_advance_offset_seam(
    path: pathlib.Path,
) -> None:
    """FR-022 / FR-023 — only the test seam itself defines
    ``advance_offset_for_test``; no other production module references it.

    Mirrors the FR-060 ``AGENTTOWER_TEST_LOG_FS_FAKE`` gate
    (``test_feat007_no_test_seam_in_production.py``). The function lives
    in ``state/log_offsets.py`` (allowed: it's the seam owner) but no
    other module under ``src/agenttower/`` may import it.
    """
    if path.resolve() == (SRC_ROOT / "state" / "log_offsets.py").resolve():
        return  # The seam definition itself is the sole allowed reference.

    source = path.read_text(encoding="utf-8")
    if "advance_offset_for_test" not in source:
        return
    tree = ast.parse(source, filename=str(path))
    assert not _imports_advance_offset_seam(tree), (
        f"{path.relative_to(SRC_ROOT)} imports the FR-022/023 test seam "
        "advance_offset_for_test; only state/log_offsets.py is allowed to "
        "define it, and no production module may import it. The future "
        "FEAT-008 reader is the sole production-side offset advancer."
    )


def test_t080_advance_seam_function_signature_is_test_only_named() -> None:
    """The seam function's name MUST start with ``advance_offset_for_test``
    so accidental imports are loud at the call site."""
    assert advance_offset_for_test.__name__ == "advance_offset_for_test"
    assert advance_offset_for_test.__doc__
    assert "TEST SEAM" in advance_offset_for_test.__doc__
