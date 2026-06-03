"""FEAT-013 tmux command composer (T011).

Composes the argv vectors that ``service.py`` and ``pending_marker.py``
hand off to FEAT-004's ``docker exec -u "$USER"`` channel. Argv-first
(research §R6) — ``send-keys`` is NOT used for first-line launch
commands (Principle III safety).

This module is pure composition + timeout policy. It does NOT invoke
``docker exec`` directly — the actual subprocess call site lives in
``service.py``'s background spawn task, which uses the existing
FEAT-004 helper. That keeps the cross-FEAT integration point in one
place (T022 wires the FEAT-004 channel).

FR-013 amendment: each tmux RPC stage MUST time out after 30 seconds
and retry transient failures (per spec §Assumptions enum) up to 2 times
with 1s / 2s exponential back-off. The ``Stage`` enum + ``TIMEOUT_SECONDS``
+ ``RETRY_BACKOFF`` constants codify the policy; the actual sleep /
asyncio.wait_for / subprocess.TimeoutExpired handling is in service.py.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Final


# FR-013 amendment — per-stage timeout (research §R7 + pre-implement walk Q1).
TIMEOUT_SECONDS: Final[int] = 30

# Exponential back-off intervals for the 2x transient retry policy.
RETRY_BACKOFF: Final[tuple[float, ...]] = (1.0, 2.0)


class TmuxStage(str, Enum):
    """Stages of the create-layout pipeline that this module composes RPCs for.

    Each stage maps to a ``failed_stage`` value when its tmux RPC fails
    after all retries.
    """

    PANE_CREATE = "pane_create"          # new-session / split-window
    LAUNCH_COMMAND = "launch_command"    # detected via post-spawn poll
    REGISTRATION = "registration"        # FEAT-006 register-self call
    LOG_ATTACH = "log_attach"            # FEAT-007 attach-log call
    TMUX_KILL = "tmux_kill"              # kill-pane on remove


@dataclass(frozen=True, slots=True)
class TmuxCommand:
    """A composed ``tmux ...`` argv vector + the stage it belongs to.

    ``argv`` is the argv passed to ``docker exec -u "$USER" <container>
    tmux ...`` — the caller prepends ``["docker", "exec", "-u", USER,
    container_id, "tmux"]`` before invoking.
    """

    stage: TmuxStage
    argv: tuple[str, ...]


def new_session(
    session_name: str,
    window_name: str,
    launch_argv: tuple[str, ...],
    *,
    working_dir: str | None = None,
) -> TmuxCommand:
    """Compose ``tmux new-session -d -s <session> -n <window> -- <argv...>``.

    ``-d`` keeps the session detached so the daemon can finish registration
    before the operator focuses the window. The ``--`` separator stops
    tmux from treating the launch argv as tmux options.

    ``working_dir`` is applied via tmux's ``-c`` flag (no shell). The
    daemon NEVER uses ``-c "cd /foo && exec ..."`` style shell-prefixed
    commands — Principle III safety. Working dir is the only path token
    that ``shlex.quote`` runs over, defensively.
    """
    argv: list[str] = ["new-session", "-d", "-s", session_name, "-n", window_name]
    if working_dir is not None:
        argv += ["-c", working_dir]
    argv.append("--")
    argv.extend(launch_argv)
    return TmuxCommand(stage=TmuxStage.PANE_CREATE, argv=tuple(argv))


def split_window(
    session_name: str,
    target_pane_index: int,
    direction: str,
    launch_argv: tuple[str, ...],
    *,
    working_dir: str | None = None,
) -> TmuxCommand:
    """Compose ``tmux split-window -t <target> -h|-v -- <argv...>``.

    ``direction`` MUST be ``"h"`` (horizontal split) or ``"v"`` (vertical).
    """
    if direction not in ("h", "v"):
        raise ValueError(f"direction must be 'h' or 'v', got {direction!r}")
    target = f"{session_name}:0.{target_pane_index}"
    argv: list[str] = ["split-window", "-t", target, f"-{direction}"]
    if working_dir is not None:
        argv += ["-c", working_dir]
    argv.append("--")
    argv.extend(launch_argv)
    return TmuxCommand(stage=TmuxStage.PANE_CREATE, argv=tuple(argv))


def select_pane_title(
    session_name: str, pane_index: int, title: str
) -> TmuxCommand:
    """Compose ``tmux select-pane -t <target> -T <title>``.

    Called by ``pending_marker.py`` to attach / clear the
    ``@MANAGED:<token>:<label>`` pane title (research §R1 / FR-014).
    """
    target = f"{session_name}:0.{pane_index}"
    return TmuxCommand(
        stage=TmuxStage.PANE_CREATE,
        argv=("select-pane", "-t", target, "-T", title),
    )


def kill_pane(session_name: str, pane_index: int) -> TmuxCommand:
    """Compose ``tmux kill-pane -t <target>`` (FR-010 / remove action)."""
    target = f"{session_name}:0.{pane_index}"
    return TmuxCommand(stage=TmuxStage.TMUX_KILL, argv=("kill-pane", "-t", target))


def list_panes(session_name: str) -> TmuxCommand:
    """Compose ``tmux list-panes -t <session> -F '#{pane_index} #{pane_title}'``.

    Used by ``recovery.py`` (T046) for boot-time reconcile and by the
    FEAT-004 scan extension (T034) to detect pending-managed marker
    titles.
    """
    return TmuxCommand(
        stage=TmuxStage.PANE_CREATE,
        argv=(
            "list-panes",
            "-t",
            session_name,
            "-F",
            "#{pane_index} #{pane_title}",
        ),
    )


def quote_for_shell(path: str) -> str:
    """Defensive shell-quoting helper for the only path that needs it.

    Used when an operator-supplied ``working_dir`` is forwarded through
    a shell context (rare; ``new-session -c`` avoids the shell). Wraps
    ``shlex.quote`` so callers don't need to import it.
    """
    return shlex.quote(path)
