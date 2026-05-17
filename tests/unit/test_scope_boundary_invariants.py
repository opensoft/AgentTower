"""T063a — FEAT-010 scope-boundary AST invariants (FR-052/053/054).

Three negative requirements that the spec calls out explicitly but
which would otherwise be invisible to test coverage. This module
walks the AST of every ``src/agenttower/routing/*.py`` file and
asserts that no forbidden module name appears in any ``import`` or
``from … import …`` statement.

* **FR-052** — No non-event triggers (timers, polling, file watchers,
  webhooks). The routing worker fires only in response to FEAT-008
  events; auxiliary mechanisms like ``asyncio`` event loops, ``Timer``
  threads, or ``concurrent.futures`` pools would constitute non-event
  triggers and are out of MVP scope.

* **FR-053** — No model-based or LLM-based decisions. The routing
  worker MUST NOT call an LLM for arbitration, target selection,
  template inference, or route suggestion. AST-level guard against
  any LLM-client import.

* **FR-054** — No TUI / web UI / desktop-notification surface. CLI +
  JSONL are the only operator-facing surfaces.

A future refactor that accidentally introduces one of these dependencies
fails the test immediately at code-review time. Adding a new module
to the forbidden list is a one-line change here; relaxing one is a
spec amendment.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


_ROUTING_DIR = (
    Path(__file__).resolve().parents[2]
    / "src" / "agenttower" / "routing"
)


# FR-052 — non-event triggers (timers, polling, async loops).
# Note: ``threading`` itself is fine (the worker + heartbeat use
# threading.Event); ``threading.Timer`` specifically would be a
# non-event scheduled trigger.
_FORBIDDEN_FR052_MODULES: frozenset[str] = frozenset({
    "asyncio",
    "concurrent.futures",
    "sched",
})

# FR-053 — LLM clients. Adding a new LLM SDK to the project would
# require a spec amendment removing it from this set.
_FORBIDDEN_FR053_MODULES: frozenset[str] = frozenset({
    "openai",
    "anthropic",
    "langchain",
    "litellm",
    "cohere",
    "google.generativeai",
    "huggingface_hub",
})

# FR-054 — TUI / web UI / desktop notifications.
_FORBIDDEN_FR054_MODULES: frozenset[str] = frozenset({
    "tkinter",
    "curses",
    "blessings",
    "rich.live",  # rich is OK for static rendering; live UIs are not
    "textual",
    "fastapi",
    "flask",
    "starlette",
    "uvicorn",
    "aiohttp",
    "tornado",
    "pywebview",
    "pync",
    "notify2",
    "dbus",
    "plyer",
})


# Aggregate set for the AST scan — each violation reports back to
# its FR via the imports' membership.
_ALL_FORBIDDEN = (
    _FORBIDDEN_FR052_MODULES
    | _FORBIDDEN_FR053_MODULES
    | _FORBIDDEN_FR054_MODULES
)


def _collect_routing_py_files() -> list[Path]:
    return sorted(p for p in _ROUTING_DIR.glob("*.py") if p.is_file())


def _extract_imports(tree: ast.AST) -> set[str]:
    """Return every top-level module name imported anywhere in the
    tree (including nested function-level imports). For
    ``from x.y import z`` we capture ``x.y`` (so consumers can match
    against the configured forbidden set's dotted names)."""
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                imports.add(node.module)
            for alias in node.names:
                if node.module:
                    imports.add(f"{node.module}.{alias.name}")
                else:
                    imports.add(alias.name)
    return imports


def _fr_for_module(module: str) -> str:
    if module in _FORBIDDEN_FR052_MODULES:
        return "FR-052 (no non-event triggers)"
    if module in _FORBIDDEN_FR053_MODULES:
        return "FR-053 (no LLM decisions)"
    if module in _FORBIDDEN_FR054_MODULES:
        return "FR-054 (no TUI/web/notification)"
    return "<unknown FR>"


def test_routing_dir_exists_and_has_python_files() -> None:
    """Sanity check — guards against the test silently scanning an
    empty directory if the routing/ package moves."""
    files = _collect_routing_py_files()
    assert files, f"no routing/*.py files found under {_ROUTING_DIR}"


@pytest.mark.parametrize("py_file", _collect_routing_py_files())
def test_no_forbidden_imports_in_routing_module(py_file: Path) -> None:
    """For each src/agenttower/routing/*.py file, scan every import
    statement and assert that NO forbidden module name appears.

    A failure prints the file + module + which FR the violation maps
    to so reviewers can decide whether to refactor the import out OR
    amend the spec.
    """
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = _extract_imports(tree)
    violations = imports & _ALL_FORBIDDEN
    assert not violations, (
        f"{py_file.relative_to(_ROUTING_DIR.parent.parent.parent)} "
        f"violates FEAT-010 scope-boundary AST invariant — forbidden "
        f"imports: "
        + ", ".join(
            f"{m} [{_fr_for_module(m)}]" for m in sorted(violations)
        )
    )


def test_forbidden_module_sets_are_disjoint() -> None:
    """The three forbidden sets must be disjoint so a violation maps
    to exactly one FR. (Defends against a future maintainer adding a
    module to two sets, which would produce ambiguous failure
    messages.)"""
    assert _FORBIDDEN_FR052_MODULES.isdisjoint(_FORBIDDEN_FR053_MODULES)
    assert _FORBIDDEN_FR052_MODULES.isdisjoint(_FORBIDDEN_FR054_MODULES)
    assert _FORBIDDEN_FR053_MODULES.isdisjoint(_FORBIDDEN_FR054_MODULES)


def test_threading_is_NOT_forbidden() -> None:
    """Sanity check — the worker uses ``threading.Event`` for the
    shutdown signal and the heartbeat uses ``threading.Lock`` for
    counter snapshots. Plain ``threading`` is on the allowed list.
    Only ``threading.Timer`` would constitute a non-event trigger,
    but the spec is specific about that — see FR-052 nuance in the
    test header."""
    assert "threading" not in _ALL_FORBIDDEN
