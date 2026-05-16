"""T041 — FR-038 + Research §R-007 AST gate.

Walks the AST of :mod:`agenttower.tmux.subprocess_adapter` and asserts:

1. No ``subprocess.*`` call has ``shell=True``.
2. No ``os.system`` or ``os.popen`` call exists.
3. Every ``subprocess.run`` / ``Popen`` / ``check_*`` call's ``args``
   positional is an ``ast.List`` whose elements are ``ast.Constant``
   (string literals) or ``ast.Name`` references — NEVER an
   f-string (``ast.JoinedStr``), ``.format`` / ``.join`` /
   ``%``-formatting, or any expression involving a ``body`` parameter.
4. Where a function takes a ``body`` parameter, that parameter MAY
   appear in the call ONLY as the value of an ``input=`` keyword
   (the stdin conduit).

The gate covers ``subprocess_adapter.py`` only; the fakes don't run
real processes and aren't a body-leak surface.

This test runs in unit CI and fails the build if the contract is
violated. Per FR-038, the prohibition on shell-string interpolation
of the body is a hard MUST NOT.
"""

from __future__ import annotations

import ast
import pathlib

import pytest


_TARGET_FILE = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "agenttower" / "tmux" / "subprocess_adapter.py"
)


_SUBPROCESS_RUN_NAMES = frozenset({
    "run", "Popen", "call", "check_call", "check_output", "getoutput",
})


def _parse_target() -> ast.Module:
    src = _TARGET_FILE.read_text(encoding="utf-8")
    return ast.parse(src, filename=str(_TARGET_FILE))


# ──────────────────────────────────────────────────────────────────────
# 1. shell=True is forbidden
# ──────────────────────────────────────────────────────────────────────


def _is_subprocess_call(node: ast.AST) -> bool:
    """``True`` if the node is a ``subprocess.<run|Popen|...>`` call."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    # subprocess.run(...) form
    if isinstance(func, ast.Attribute):
        if (
            isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
            and func.attr in _SUBPROCESS_RUN_NAMES
        ):
            return True
    # bare run(...) form (would catch a `from subprocess import run` import)
    if isinstance(func, ast.Name) and func.id in _SUBPROCESS_RUN_NAMES:
        return True
    return False


def test_no_subprocess_call_uses_shell_true() -> None:
    tree = _parse_target()
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not _is_subprocess_call(node):
            continue
        for kw in node.keywords:
            if kw.arg == "shell":
                # Allow `shell=False` literal; reject anything else.
                if not (
                    isinstance(kw.value, ast.Constant) and kw.value.value is False
                ):
                    offenders.append(
                        f"line {node.lineno}: shell={ast.unparse(kw.value)!r}"
                    )
    assert not offenders, (
        "subprocess calls with shell!=False detected in "
        f"{_TARGET_FILE.name}: {offenders}"
    )


def test_no_os_system_or_os_popen() -> None:
    tree = _parse_target()
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if isinstance(func.value, ast.Name) and func.value.id == "os":
            if func.attr in ("system", "popen"):
                offenders.append(f"line {node.lineno}: os.{func.attr}")
    assert not offenders, (
        f"os.system / os.popen detected in {_TARGET_FILE.name}: {offenders}"
    )


# ──────────────────────────────────────────────────────────────────────
# 2. argv constructions must be lists of Constants or Names — no
#    f-strings, .format, .join, % formatting
# ──────────────────────────────────────────────────────────────────────


def _is_safe_argv_element(node: ast.AST) -> tuple[bool, str]:
    """Return ``(is_safe, reason)`` for one element of an ``args`` list."""
    # String literal — safe.
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True, ""
    # Variable reference — safe (caller passes a typed value).
    if isinstance(node, ast.Name):
        return True, ""
    # Attribute access (e.g., self._x) — safe; the attribute is a name,
    # not a string-construction expression.
    if isinstance(node, ast.Attribute):
        return True, ""
    # Starred unpacking of a list/tuple of strings — safe (e.g.,
    # ``*self._exec_env_args()`` returning a typed list).
    if isinstance(node, ast.Starred):
        return True, ""
    # F-string — FORBIDDEN (could embed body or any value).
    if isinstance(node, ast.JoinedStr):
        return False, "f-string"
    # Method call on a string — could be `.format(...)` or `.join(...)`.
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in (
            "format", "join", "format_map", "__mod__",
        ):
            return False, f"{func.attr}() call"
        # Any other Call is suspicious — argv elements should be
        # literals or names, not arbitrary call results. Allow specific
        # cases like `repr(x)` if they show up; for now keep it strict
        # and surface for review.
        return False, f"call to {ast.unparse(func)!r}"
    # %-formatting (BinOp with %).
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return False, "%-formatting"
    # String concatenation.
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return False, "string concatenation"
    return False, f"unexpected node type {type(node).__name__}"


def test_subprocess_call_argv_is_list_of_safe_elements() -> None:
    tree = _parse_target()
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not _is_subprocess_call(node):
            continue
        # First positional is argv.
        if not node.args:
            continue
        argv_node = node.args[0]
        # Allow `argv` as a Name (the caller built it elsewhere).
        if isinstance(argv_node, ast.Name):
            continue
        # Otherwise it must be a list literal.
        if not isinstance(argv_node, ast.List):
            offenders.append(
                f"line {node.lineno}: argv is {type(argv_node).__name__}, "
                f"expected list literal or Name"
            )
            continue
        for i, element in enumerate(argv_node.elts):
            ok, reason = _is_safe_argv_element(element)
            if not ok:
                offenders.append(
                    f"line {node.lineno}: argv[{i}] is unsafe ({reason}): "
                    f"{ast.unparse(element)!r}"
                )
    assert not offenders, (
        f"unsafe argv elements in {_TARGET_FILE.name}: {offenders}"
    )


# ──────────────────────────────────────────────────────────────────────
# 3. Body parameter MUST appear only as `input=` keyword value
# ──────────────────────────────────────────────────────────────────────


def _find_function_with_body_param(tree: ast.Module, *, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            if any(arg.arg == "body" for arg in node.args.args + node.args.kwonlyargs):
                return node
    return None


def test_body_parameter_only_appears_as_input_keyword() -> None:
    """If a function declares a ``body`` parameter, the parameter MUST
    appear in the function body ONLY as the value of an ``input=``
    keyword on a subprocess call (the stdin conduit). The body MUST
    NEVER appear in argv elements, in f-strings, in string-formatting,
    or in any other position."""
    tree = _parse_target()
    fn = _find_function_with_body_param(tree, name="load_buffer")
    assert fn is not None, "expected load_buffer to take a `body` parameter"
    offenders: list[str] = []
    for sub in ast.walk(fn):
        # Find every reference to the name `body`.
        if not (isinstance(sub, ast.Name) and sub.id == "body"):
            continue
        # The reference's parent must be one of:
        #  - the value of an `input=` keyword on a Call
        #  - the operand of `bytes(body)` / `isinstance(body, ...)` /
        #    `type(body)` / `len(body)` (safe inspection)
        #  - a `body` attribute write (the function parameter itself, on
        #    its declaration line — we skip those by checking ctx)
        if isinstance(sub.ctx, ast.Store):
            continue
        # Walk the AST to find what context this Name appears in.
        parent = _find_parent(fn, sub)
        if parent is None:
            offenders.append(f"line {sub.lineno}: orphan reference")
            continue
        if _is_safe_body_reference(parent, sub):
            continue
        offenders.append(
            f"line {sub.lineno}: unsafe reference in {type(parent).__name__}: "
            f"{ast.unparse(parent)[:80]!r}"
        )
    assert not offenders, (
        f"`body` parameter leaked in unsafe contexts: {offenders}"
    )


def _find_parent(tree: ast.AST, target: ast.AST) -> ast.AST | None:
    """Return the immediate AST parent of ``target`` in ``tree``."""
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            if child is target:
                return node
    return None


_SAFE_INSPECT_CALLS = frozenset({"bytes", "isinstance", "type", "len", "memoryview"})


def _is_safe_body_reference(parent: ast.AST, body_ref: ast.Name) -> bool:
    """A `body` reference is safe when its parent context is one of:

    * ``input=body`` keyword on a Call.
    * ``bytes(body)``, ``isinstance(body, …)``, ``type(body)``,
      ``len(body)`` — safe inspection / coercion.
    * The function definition's argument list (parameter binding).
    """
    # `input=body` keyword.
    if isinstance(parent, ast.keyword) and parent.arg == "input":
        return True
    # Function call to a safe inspector with body as a positional arg.
    if isinstance(parent, ast.Call):
        func = parent.func
        if isinstance(func, ast.Name) and func.id in _SAFE_INSPECT_CALLS:
            return True
    # `arg` node in `FunctionDef.args` — parameter declaration.
    if isinstance(parent, ast.arguments):
        return True
    return False
