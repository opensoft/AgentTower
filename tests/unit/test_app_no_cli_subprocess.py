"""FEAT-011 T080 — SC-001: app.* methods are reached over the socket, not
by shelling out to the ``agenttower`` CLI.

This is a **static-analysis** test. It walks every FEAT-011 test file
(``tests/unit/test_app_*.py`` and ``tests/integration/test_story*.py`` +
``tests/integration/test_app_*.py``), parses each with ``ast``, and asserts
that no *test body* invokes the ``agenttower`` CLI as a subprocess for an
``app.*`` method call.

SC-001 invariant: the GUI app drives the daemon directly over the Unix
socket. FEAT-011 tests model that contract by speaking raw NDJSON over a
socket; they must not regress into shelling out to ``agenttower`` to render
or invoke an ``app.*`` code path.

Setup-vs-render distinction (IMPORTANT)
---------------------------------------
The integration tests legitimately invoke the ``agenttower`` CLI for
**daemon lifecycle setup** — ``config init``, ``ensure-daemon``,
``stop-daemon``, ``status`` — via the shared ``_daemon_helpers`` module.
That is allowed: it is environment bootstrap, not a UI-rendering or
``app.*`` invocation path. The rule this test enforces is narrower:

* A FEAT-011 *test body* (or a module-level helper in a FEAT-011 test file)
  must not call ``subprocess.run([...])`` / ``subprocess.Popen([...])`` with
  ``"agenttower"`` as ``argv[0]`` **directly inside the test file**.
* CLI lifecycle calls are funneled exclusively through ``_daemon_helpers``
  (``ensure_daemon`` / ``run_config_init`` / ``stop_daemon`` / ``status`` /
  ``stop_daemon_if_alive``). Those helper functions live in
  ``_daemon_helpers.py`` — a non-test setup module — and are deliberately
  out of scope for this scan.

So: the scan flags an ``agenttower``-argv subprocess literal that appears
in a FEAT-011 *test* file. It does not flag ``_daemon_helpers.py``, because
that module is the sanctioned home for setup-only CLI calls.

One further exemption — the CLI-parity test
-------------------------------------------
``test_app_cli_parity.py`` (T082, SC-010) deliberately invokes
``agenttower route add`` — but **not** as a UI-render shortcut for an
``app.*`` call. There the CLI invocation is the *subject under
comparison*: the test creates a route via the CLI and via
``app.route.add`` and asserts the two SQLite rows match. Forbidding the
CLI call there would make the parity test impossible to write. SC-001
forbids substituting the CLI *for* the socket path; the parity test does
the opposite — it exercises both paths to prove they agree. That single
file is therefore exempt, and the exemption is enumerated explicitly
(not pattern-based) so it cannot silently widen.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


_TESTS_ROOT = Path(__file__).resolve().parent.parent
_UNIT = _TESTS_ROOT / "unit"
_INTEGRATION = _TESTS_ROOT / "integration"

# The CLI-parity test (T082) is exempt: its `agenttower route add` call
# is the subject under comparison, not a render shortcut. See the module
# docstring ("One further exemption — the CLI-parity test").
_CLI_PARITY_EXEMPT = frozenset({"test_app_cli_parity.py"})


def _feat011_test_files() -> list[Path]:
    """Collect the FEAT-011 test files this contract covers.

    ``_daemon_helpers.py`` is explicitly excluded — it is the sanctioned
    setup module for daemon-lifecycle CLI calls, not a test body.
    """
    files: list[Path] = []
    files += sorted(_UNIT.glob("test_app_*.py"))
    files += sorted(_INTEGRATION.glob("test_app_*.py"))
    files += sorted(_INTEGRATION.glob("test_story*.py"))
    # Defensive: never let a helper module slip into the test-body scan.
    return [f for f in files if not f.name.startswith("_")]


def _collect_subprocess_argv0_literals(tree: ast.AST) -> list[tuple[int, str]]:
    """Return ``(lineno, argv0)`` for every ``subprocess.run``/``Popen`` call
    whose first positional argument is a list literal with a string first
    element.

    Only list-literal argv with a constant ``argv[0]`` is resolvable
    statically; a dynamically built argv would not be — but FEAT-011 tests
    use literal argv lists exclusively, so this is sufficient and precise.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match `subprocess.run(...)` / `subprocess.Popen(...)` and the
        # bare `run(...)` / `Popen(...)` (in case of a from-import).
        name = None
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name not in ("run", "Popen"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, (ast.List, ast.Tuple)) or not first.elts:
            continue
        head = first.elts[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            found.append((getattr(node, "lineno", -1), head.value))
    return found


def test_feat011_test_files_exist() -> None:
    """Sanity guard: the scan must actually have FEAT-011 files to inspect,
    otherwise a green result would be meaningless."""
    files = _feat011_test_files()
    assert files, "no FEAT-011 test files found to scan"
    names = {f.name for f in files}
    # Story 1 + Story 2 socket integration tests are the canonical
    # examples this contract protects.
    assert "test_story1_dashboard_bootstrap.py" in names
    assert "test_story2_adopt_roundtrip.py" in names


@pytest.mark.parametrize(
    "test_file",
    _feat011_test_files(),
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_no_agenttower_cli_subprocess_in_test_body(test_file: Path) -> None:
    """SC-001: a FEAT-011 test file must not shell out to the ``agenttower``
    CLI. Daemon-lifecycle setup is funneled through ``_daemon_helpers`` —
    which is not a test file and is excluded from this scan.
    """
    if test_file.name in _CLI_PARITY_EXEMPT:
        pytest.skip(
            f"{test_file.name} is the SC-010 CLI-parity test — its "
            "`agenttower route add` call is the comparison subject, not a "
            "render shortcut (see module docstring)"
        )

    source = test_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(test_file))
    argv0_calls = _collect_subprocess_argv0_literals(tree)

    offenders = [
        (lineno, argv0)
        for lineno, argv0 in argv0_calls
        if argv0 == "agenttower"
    ]
    assert not offenders, (
        f"SC-001 violation in {test_file}: FEAT-011 test bodies must drive "
        f"app.* methods over the raw socket, not by shelling out to the "
        f"`agenttower` CLI. Daemon-lifecycle setup belongs in "
        f"`_daemon_helpers`. Offending subprocess calls (line, argv0): "
        f"{offenders!r}"
    )


def test_helper_module_is_the_only_cli_caller() -> None:
    """Positive control for the setup-vs-render distinction: the sanctioned
    ``_daemon_helpers`` module DOES invoke the ``agenttower`` CLI (for
    ``config init`` / ``ensure-daemon`` / ``stop-daemon`` / ``status``).

    This asserts the scan above is meaningful — CLI lifecycle calls really
    are concentrated in the helper module, so excluding it is the correct
    boundary, not a loophole that hides every CLI call.
    """
    helper = _INTEGRATION / "_daemon_helpers.py"
    assert helper.exists(), helper
    tree = ast.parse(helper.read_text(encoding="utf-8"), filename=str(helper))
    argv0_calls = _collect_subprocess_argv0_literals(tree)
    cli_calls = [a for _, a in argv0_calls if a == "agenttower"]
    assert cli_calls, (
        "_daemon_helpers.py is expected to be the home of the sanctioned "
        "`agenttower` lifecycle CLI calls; found none"
    )
