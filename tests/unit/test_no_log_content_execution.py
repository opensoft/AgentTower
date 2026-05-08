"""FR-065 AST gate — daemon MUST NOT execute log file bytes (T220).

Defense against A3 (malicious in-container process emitting adversarial
pane content). The daemon reads host log files only via ``host_fs.read_tail_lines``
and ``preview.read_tail_lines``; the bytes flow into the redaction utility
and out via the CLI render path. They MUST NOT reach ``eval`` / ``exec`` /
``compile`` / ``__import__`` / ``subprocess``-based shell construction.

This test scans every production module under ``src/agenttower/`` for
banned patterns. Tests, fixtures, and external dependencies are out of
scope (only the daemon binary is in the trust boundary).
"""

from __future__ import annotations

import ast
import pathlib
from typing import Iterable

import pytest


SRC_ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "agenttower"

# Functions that, when given log-file content as input, would constitute
# a code-execution sink (FR-065). The check is conservative — any direct
# call to these by name in a production module is flagged regardless of
# whether the argument actually traces to log bytes; auditing the
# argument source per call is the next-level rigor (deferred).
_BANNED_CALL_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
    }
)

# Module names whose attribute calls (e.g. ``subprocess.run``) are gated.
# Calls into these modules are LEGITIMATE in many contexts (FEAT-003 / FEAT-004
# adapters issue ``docker exec``/``tmux``); the test allow-lists modules whose
# ``subprocess`` usage is bounded by structured argv lists with no log-content
# interpolation.
_SUBPROCESS_CALLERS_ALLOWLIST = frozenset(
    {
        # FEAT-003 / FEAT-004 / FEAT-005 / FEAT-007 adapters all build argv
        # from structured config or shlex-quoted values. None of them feed
        # log-file bytes into subprocess.
        "src/agenttower/docker/subprocess_adapter.py",
        "src/agenttower/tmux/subprocess_adapter.py",
        "src/agenttower/logs/docker_exec.py",
        # FEAT-005 self-identity probes a small set of /proc files.
        "src/agenttower/config_doctor/checks.py",
        # FEAT-002 server / FEAT-001 lifecycle / daemon entrypoint — no log
        # content reaches subprocess from these.
        "src/agenttower/socket_api/server.py",
        "src/agenttower/socket_api/lifecycle.py",
        "src/agenttower/daemon.py",
        # FEAT-002 ``ensure-daemon`` spawns ``python -m agenttower.daemon run``
        # with a structured argv built from sys.executable, NOT from any
        # user input or log content.
        "src/agenttower/cli.py",
        # FEAT-003 / FEAT-004 fakes are integration helpers, not in this
        # test's prod-only scope but listed for completeness.
        "src/agenttower/docker/fakes.py",
        "src/agenttower/tmux/fakes.py",
    }
)


def _iter_production_files() -> Iterable[pathlib.Path]:
    for path in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _relative(path: pathlib.Path) -> str:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    return str(path.relative_to(repo_root))


class _BannedCallVisitor(ast.NodeVisitor):
    """Find direct calls to ``eval``/``exec``/``compile``/``__import__``."""

    def __init__(self, source_path: str) -> None:
        self.source_path = source_path
        self.findings: list[tuple[str, int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        target = node.func
        if isinstance(target, ast.Name) and target.id in _BANNED_CALL_NAMES:
            self.findings.append(
                (self.source_path, node.lineno, f"call to {target.id}()")
            )
        # Attribute calls like `compile(...)` via `import compile` are rare
        # but covered by Name above. Module-qualified `subprocess.run` is
        # checked separately (allowlisted modules).
        self.generic_visit(node)


class _SubprocessCallVisitor(ast.NodeVisitor):
    """Find ``subprocess.<anything>`` calls outside the allowlist."""

    def __init__(self, source_path: str) -> None:
        self.source_path = source_path
        self.findings: list[tuple[str, int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        target = node.func
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            if target.value.id == "subprocess":
                self.findings.append(
                    (
                        self.source_path,
                        node.lineno,
                        f"subprocess.{target.attr}() call",
                    )
                )
        self.generic_visit(node)


@pytest.mark.parametrize("path", list(_iter_production_files()))
def test_no_eval_exec_compile_in_production(path: pathlib.Path) -> None:
    """FR-065 — no production module may call eval/exec/compile/__import__."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    visitor = _BannedCallVisitor(_relative(path))
    visitor.visit(tree)
    assert not visitor.findings, (
        f"FR-065 banned-call hits in {path}: {visitor.findings!r}"
    )


def test_subprocess_calls_only_in_allowlisted_modules() -> None:
    """FR-065 — subprocess calls are confined to a closed allow-list."""
    offending: list[tuple[str, int, str]] = []
    for path in _iter_production_files():
        rel = _relative(path)
        if rel in _SUBPROCESS_CALLERS_ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        visitor = _SubprocessCallVisitor(rel)
        visitor.visit(tree)
        offending.extend(visitor.findings)
    assert not offending, (
        f"FR-065 — unexpected subprocess.* call sites outside allowlist: "
        f"{offending!r}. Either confine the call to an existing adapter "
        f"module or extend the allowlist with a justification."
    )


def test_log_file_consumers_are_explicitly_enumerated() -> None:
    """FR-065 — only ``host_fs`` and ``preview`` may read host-log content.

    Asserts the ``read_tail_lines`` symbol is exported only by the documented
    consumer modules. A future module that adds a third reader path would
    fail this test, forcing an explicit decision.
    """
    documented_readers = {
        "src/agenttower/logs/host_fs.py": True,
    }
    found: dict[str, list[int]] = {}
    for path in _iter_production_files():
        rel = _relative(path)
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "read_tail_lines"
            ):
                found.setdefault(rel, []).append(node.lineno)
    assert set(found.keys()) == set(documented_readers.keys()), (
        f"FR-065: read_tail_lines is defined in unexpected modules: "
        f"found={set(found.keys())} expected={set(documented_readers.keys())}"
    )
