"""T094a — FR-051..054 negative-requirement guards.

FEAT-009 is deliberately a thin queue primitive. The four MUST-NOT
requirements from spec.md §"Interaction boundaries" lock that scope
in code:

* **FR-051**: System MUST NOT create or transition any queue row in
  response to a FEAT-008 event in MVP.
  → AST-walk ``src/agenttower/socket_api/methods.py``: exactly ONE
    dispatcher (`queue.send_input`) writes to ``message_queue``; no
    other dispatcher contains an ``INSERT INTO message_queue`` or
    calls ``MessageQueueDao.insert_*``.
  → ``send-input`` argparse surface has no flag accepting an
    event payload (e.g., ``--from-event``).

* **FR-052**: System MUST NOT emit an arbitration prompt or any
  inter-master notification in MVP.
  → No socket dispatcher name contains the substring
    ``arbitration``.

* **FR-053**: System MUST NOT infer or interpret semantic content of
  the body. No LLM / model-inference library imported.
  → AST-walk ``src/agenttower/routing/``: no import of any well-known
    LLM library by name (``openai``, ``anthropic``, ``transformers``,
    ``langchain``, etc.).

* **FR-054**: System MUST NOT include a TUI, web UI, or desktop
  notification surface in FEAT-009.
  → AST-walk ``src/agenttower/routing/``: no import of a known TUI
    library (``textual``, ``urwid``, ``npyscreen``, ``rich.live``,
    etc.).

Each check is short and parameterized so adding a new banned library
or dispatcher pattern is a one-line edit.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from agenttower.cli import _build_parser
from agenttower.socket_api.methods import DISPATCH


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_METHODS_PY = _REPO_ROOT / "src" / "agenttower" / "socket_api" / "methods.py"
_ROUTING_DIR = _REPO_ROOT / "src" / "agenttower" / "routing"


# ──────────────────────────────────────────────────────────────────────
# FR-051: exactly one dispatcher inserts into message_queue
# ──────────────────────────────────────────────────────────────────────


def _routing_module_sources() -> list[pathlib.Path]:
    """Return every .py file under src/agenttower/routing/."""
    return sorted(_ROUTING_DIR.rglob("*.py"))


def _walk_imports(tree: ast.Module) -> list[str]:
    """Return the flat list of top-level module names imported by ``tree``.

    ``import a.b.c`` contributes ``a``, ``a.b``, and ``a.b.c``; for
    blocked-module detection we want the topmost component too.
    """
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
                names.append(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
                names.append(node.module.split(".", 1)[0])
    return names


def test_only_queue_send_input_writes_to_message_queue() -> None:
    """AST-walk socket_api/methods.py: only the ``_queue_send_input``
    handler contains a call to ``MessageQueueDao.insert_queued`` /
    ``insert_blocked`` or an ``INSERT INTO message_queue`` string.

    The dispatcher reaches the DAO via ``ctx.queue_service.send_input``,
    so the direct ``insert_*`` text never appears in methods.py — what
    we DO need to verify is that no other handler (operator-action,
    routing, listing) takes a path that creates a new row.

    This test is structural: we walk every function in methods.py and
    check none of them reference ``insert_queued`` or ``insert_blocked``
    or contain the literal string ``INSERT INTO message_queue``.
    """
    src = _METHODS_PY.read_text(encoding="utf-8")
    # Literal SQL string check.
    assert "INSERT INTO message_queue" not in src, (
        "methods.py contains a raw INSERT — all queue row writes MUST "
        "flow through QueueService.send_input"
    )
    # Identifier check: insert_queued / insert_blocked should not be
    # called by any dispatcher (they're only callable via the
    # QueueService façade, which uses them inside .send_input).
    tree = ast.parse(src, filename=str(_METHODS_PY))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr in ("insert_queued", "insert_blocked"):
            offenders.append(
                f"line {node.lineno}: {ast.unparse(node)!r} — direct DAO insert call"
            )
    assert not offenders, (
        f"methods.py calls a DAO insert directly; only "
        f"QueueService.send_input may: {offenders}"
    )


def test_send_input_argparse_has_no_event_subscription_flag() -> None:
    """FR-051: ``send-input`` cannot accept an event payload as input.
    The argparse surface MUST not contain a flag like ``--from-event``
    or ``--event-id`` that would subscribe queue creation to FEAT-008."""
    parser = _build_parser()
    # Walk every action of the send-input subparser.
    send_input_subparser = None
    for action in parser._actions:  # noqa: SLF001 — test-only introspection
        if isinstance(action, type(parser._subparsers._actions[0]).__class__):  # type: ignore[attr-defined]
            continue  # skip the subparsers container itself
    # Find the send-input subparser via the parser's `_subparsers` graph.
    for action in parser._actions:  # noqa: SLF001
        if not hasattr(action, "choices") or action.choices is None:
            continue
        if "send-input" in action.choices:
            send_input_subparser = action.choices["send-input"]
            break
    assert send_input_subparser is not None, (
        "send-input subparser not registered"
    )
    forbidden_substrings = ("event", "subscribe", "trigger")
    for action in send_input_subparser._actions:  # noqa: SLF001
        if not action.option_strings:
            continue
        for option in action.option_strings:
            lowered = option.lower()
            for bad in forbidden_substrings:
                assert bad not in lowered, (
                    f"send-input has flag {option!r} containing {bad!r} — "
                    "FR-051 prohibits event-to-route subscription"
                )


# ──────────────────────────────────────────────────────────────────────
# FR-052: no arbitration / inter-master dispatcher
# ──────────────────────────────────────────────────────────────────────


def test_no_dispatcher_name_contains_arbitration() -> None:
    """FR-052: no socket method dispatcher is named with the substring
    ``arbitration`` or any inter-master coordination verb."""
    forbidden = ("arbitration", "arbitrate", "broadcast")
    offenders = [
        name for name in DISPATCH
        if any(bad in name.lower() for bad in forbidden)
    ]
    assert not offenders, (
        f"socket dispatcher names matching arbitration verbs: {offenders}"
    )


# ──────────────────────────────────────────────────────────────────────
# FR-053: no LLM / model-inference library imported by routing/
# ──────────────────────────────────────────────────────────────────────


_LLM_BLOCKLIST = frozenset({
    "openai",
    "anthropic",
    "transformers",
    "langchain",
    "llama_index",
    "llama-index",
    "litellm",
    "tiktoken",
    "huggingface_hub",
})


@pytest.mark.parametrize("path", _routing_module_sources())
def test_routing_module_does_not_import_llm_libraries(path: pathlib.Path) -> None:
    """FR-053: no module under ``routing/`` imports a known LLM /
    model-inference library — body classification, summarization, or
    intent extraction is out of scope."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = _walk_imports(tree)
    offenders = [name for name in imports if name in _LLM_BLOCKLIST]
    assert not offenders, (
        f"{path.name} imports a blocked LLM library: {offenders}"
    )


# ──────────────────────────────────────────────────────────────────────
# FR-054: no TUI library imported by routing/
# ──────────────────────────────────────────────────────────────────────


_TUI_BLOCKLIST = frozenset({
    "textual",
    "urwid",
    "npyscreen",
    "blessed",
    "asciimatics",
    "prompt_toolkit",
    # rich is fine as a library, but rich.live (animated terminal UI)
    # is the FR-054 surface to avoid.
    "rich.live",
})


@pytest.mark.parametrize("path", _routing_module_sources())
def test_routing_module_does_not_import_tui_libraries(path: pathlib.Path) -> None:
    """FR-054: no module under ``routing/`` imports a TUI / animated-
    terminal library. CLI + JSONL + ``agenttower status`` are the only
    user-facing surfaces."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = _walk_imports(tree)
    offenders = [name for name in imports if name in _TUI_BLOCKLIST]
    assert not offenders, (
        f"{path.name} imports a blocked TUI library: {offenders}"
    )
