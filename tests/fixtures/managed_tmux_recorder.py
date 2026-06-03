"""FEAT-013 tmux command recorder fixture (T015).

Records the exact tmux argv sequences issued by ``tmux_create.py`` so
contract tests can assert the argv-first invocation pattern (no shell
metachar interpolation, per research §R6 / Principle III).

The recorder is also pre-programmable with stubbed responses for
``list-panes`` so recovery tests (T038, T055) can simulate "pane
disappeared during restart" without spinning up a real tmux server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agenttower.managed_sessions.tmux_create import TmuxCommand, TmuxStage


@dataclass
class RecordedCall:
    """One captured (composed) tmux command + the simulated response."""

    stage: TmuxStage
    argv: tuple[str, ...]
    returned_stdout: str = ""
    raised: BaseException | None = None


@dataclass
class TmuxRecorder:
    """Drop-in replacement for the tmux RPC channel in unit / contract tests.

    Test callers programme :attr:`_responder` to map argv-prefix → output
    (or raise) so they can assert the daemon's failure-handling, retry,
    and timeout policies without a real tmux.
    """

    calls: list[RecordedCall] = field(default_factory=list)
    _responder: Callable[[TmuxCommand], RecordedCall] | None = None

    def set_responder(
        self, responder: Callable[[TmuxCommand], RecordedCall]
    ) -> None:
        self._responder = responder

    def issue(self, command: TmuxCommand) -> str:
        """Record + dispatch a composed tmux command.

        If no responder is configured, returns an empty stdout (success).
        If the responder raises, the exception propagates AFTER the call
        is recorded so tests can inspect what argv was attempted.
        """
        if self._responder is None:
            recorded = RecordedCall(stage=command.stage, argv=command.argv)
        else:
            recorded = self._responder(command)
            # Defensive: ensure the recorded stage/argv match the command,
            # in case the responder builds them from scratch.
            recorded = RecordedCall(
                stage=command.stage,
                argv=command.argv,
                returned_stdout=recorded.returned_stdout,
                raised=recorded.raised,
            )
        self.calls.append(recorded)
        if recorded.raised is not None:
            raise recorded.raised
        return recorded.returned_stdout

    def argv_of(self, index: int) -> tuple[str, ...]:
        """Convenience accessor for assertions: ``recorder.argv_of(0)``."""
        return self.calls[index].argv

    def reset(self) -> None:
        self.calls.clear()
        self._responder = None
