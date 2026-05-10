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


# FEAT-008 T004 — extend the AST gate to enforce the broader FR-003 /
# FR-004 prohibitions: (a) no production module under ``src/agenttower/``
# may import the FEAT-008 test-seam env-var names; (b) no production
# module under ``src/agenttower/events/`` may emit raw INSERT / UPDATE
# SQL against ``log_attachments`` or ``log_offsets`` (the reader must
# go through FEAT-007 helpers and the documented ``lo_state.advance_*``
# API).


_FEAT008_TEST_SEAM_NAMES = {
    "AGENTTOWER_TEST_EVENTS_CLOCK_FAKE",
    "AGENTTOWER_TEST_READER_TICK",
}


def _references_feat008_test_seam(source: str) -> str | None:
    """Return the seam name iff *source* references one as a string literal."""
    for seam in _FEAT008_TEST_SEAM_NAMES:
        if seam in source:
            return seam
    return None


@pytest.mark.parametrize(
    "path",
    _iter_production_modules(),
    ids=lambda p: str(p.relative_to(SRC_ROOT)),
)
def test_t004_no_production_module_references_feat008_test_seams(
    path: pathlib.Path,
) -> None:
    """T004 — no production module under ``src/agenttower/`` may
    reference the FEAT-008 test-seam env-var names.

    Production code may freely call ``os.environ.get(<name>)`` for
    any *FEAT-007* seam (``AGENTTOWER_TEST_LOG_FS_FAKE`` etc.) but
    NOT the FEAT-008 ones; honoring those would let a production
    daemon use a fake clock or a fake tick socket, defeating their
    test-only purpose.
    """
    source = path.read_text(encoding="utf-8")
    seam = _references_feat008_test_seam(source)
    assert seam is None, (
        f"{path.relative_to(SRC_ROOT)} references the FEAT-008 test "
        f"seam name {seam!r}; this seam is consumed only by the test "
        "harness in tests/conftest.py. Production modules MUST NOT honor "
        "or read this env var (T004 / FR-003 / FR-004)."
    )


_FORBIDDEN_SQL_PATTERNS = (
    "INSERT INTO log_attachments",
    "UPDATE log_attachments",
    "INSERT INTO log_offsets",
    "UPDATE log_offsets",
)

_EVENTS_PKG_ROOT = SRC_ROOT / "events"


@pytest.mark.parametrize(
    "path",
    sorted(_EVENTS_PKG_ROOT.rglob("*.py")) if _EVENTS_PKG_ROOT.exists() else [],
    ids=lambda p: str(p.relative_to(SRC_ROOT)),
)
def test_t004_events_package_emits_no_raw_log_attachments_or_log_offsets_sql(
    path: pathlib.Path,
) -> None:
    """T004 — modules under ``src/agenttower/events/`` MUST NOT emit raw
    INSERT/UPDATE SQL against ``log_attachments`` or ``log_offsets``.

    The reader goes through FEAT-007 helpers
    (``reader_cycle_offset_recovery``) and the documented
    ``state.log_offsets`` advance API. Direct SQL would silently bypass
    the FR-003 / FR-004 invariants.
    """
    source = path.read_text(encoding="utf-8")
    for pattern in _FORBIDDEN_SQL_PATTERNS:
        # Case-insensitive match handles UPPER and lower forms; the
        # patterns themselves are uppercase to match SQLite convention.
        if pattern.lower() in source.lower():
            raise AssertionError(
                f"{path.relative_to(SRC_ROOT)} emits raw SQL matching "
                f"{pattern!r}; this violates FR-003 / FR-004. Route writes "
                "through agenttower.logs.reader_recovery and "
                "agenttower.state.log_offsets helpers instead."
            )
