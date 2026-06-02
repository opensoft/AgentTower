"""FEAT-013 FR-013 per-stage timeout + retry helper (Workstream 1 / C3).

Spec
====

Per spec §FR-013 (amendment), each background-spawn stage (tmux spawn,
FEAT-006 register, FEAT-007 log attach) has:

- A **30-second per-attempt timeout**.
- **Two retries** with a **1s / 2s back-off** between attempts for
  **transient** failures.

A transient failure is one of:

- ``docker_exec_failed`` (docker daemon transiently unreachable)
- ``docker_exec_timeout`` (docker call exceeded our timeout but is
  expected to recover)
- ``tmux_unavailable`` (tmux server crashed; rare but recoverable)
- ``tmux_no_server`` (server gone after a successful socket lookup;
  next attempt may re-establish)

Non-transient failures (``managed_session_name_conflict``,
``managed_pane_label_conflict``, hard YAML errors, etc.) are surfaced
on the first attempt without retry.

The TIMEOUT_SECONDS / RETRY_BACKOFF constants are declared in
:mod:`tmux_create`. This module is the runtime consumer that turns
those constants into the actual retry loop and timeout wrapping for
``_spawn_single_pane``.

Design
======

We are in a threaded daemon (not asyncio). The per-attempt timeout
runs the backend call in a **daemon worker thread** that we join with
``timeout_seconds``. If the join expires, we ABANDON the thread and
return ``stage_timeout`` immediately — we do **not** wait for the hung
worker to finish. This is the critical FR-013 property: the caller
(``spawn_layout_in_background``) holds the per-container serializer
lock, so blocking on a stuck tmux/register/log-attach backend would
stall every later managed operation for that container. A daemon
thread is the right primitive here: Python cannot forcibly kill a
worker thread, but a daemon thread does not block interpreter exit,
so an abandoned hung stage leaks at most one parked thread that the
runtime reaps at shutdown.

An earlier implementation used ``concurrent.futures.ThreadPoolExecutor``
inside a ``with`` block; on timeout, exiting the context called
``shutdown(wait=True)`` and the caller still blocked on the hung
worker — defeating the timeout. The daemon-thread join below fixes
that.

The helper is generic over the backend callable shape: it takes a
zero-argument ``Callable[[], dict[str, object]]`` and the stage name
(for diagnostics), and returns the same result dict the inner call
would. Callers wire it via ``functools.partial`` so the wrapped
function captures its own ``pane``/``tmux_pane_id``/``agent_id``
arguments without leaking them through this helper's signature.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Final

from .tmux_create import RETRY_BACKOFF, TIMEOUT_SECONDS


# Closed set of failure codes we retry on. Anything outside this set
# is surfaced on the first attempt — applying retries to permanent
# errors (e.g. label conflicts) burns the 1+2 = 3 seconds budget for
# no benefit.
TRANSIENT_FAILURE_CODES: Final[tuple[str, ...]] = (
    "docker_exec_failed",
    "docker_exec_timeout",
    "tmux_unavailable",
    "tmux_no_server",
    # Stage timeout from this module itself — when the inner call took
    # longer than ``TIMEOUT_SECONDS``, we retry per the spec.
    "stage_timeout",
)


def _run_with_timeout(
    stage_call: Callable[[], dict[str, object]],
    *,
    timeout_seconds: float,
    stage_name: str,
) -> tuple[bool, dict[str, object] | None]:
    """Run ``stage_call`` in a daemon thread bounded by ``timeout_seconds``.

    Returns ``(timed_out, result)``:

    - ``(False, result)`` — the call completed within budget; ``result``
      is its return value.
    - ``(True, None)`` — the join expired. The worker thread is
      abandoned (daemon, so it cannot block interpreter exit); the
      caller surfaces ``stage_timeout`` and moves on WITHOUT waiting.

    An exception raised inside the worker is captured and re-raised on
    the calling thread once the worker completes within budget — same
    propagation semantics as ``future.result()``.
    """
    box: dict[str, object] = {}

    def _worker() -> None:
        try:
            box["result"] = stage_call()
        except BaseException as exc:  # noqa: BLE001 — re-raised on caller thread
            box["exc"] = exc

    worker = threading.Thread(
        target=_worker, name=f"feat013-{stage_name}", daemon=True,
    )
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        # Budget exceeded. Do not join further — abandon the daemon
        # thread so the serializer-holding caller returns promptly.
        return True, None
    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return False, box.get("result")  # type: ignore[return-value]


def _is_transient(result: dict[str, object]) -> bool:
    """True if ``result`` is a backend failure with a transient code."""
    if result.get("ok"):
        return False
    error = result.get("error")
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    return isinstance(code, str) and code in TRANSIENT_FAILURE_CODES


def run_stage_with_retry(
    stage_call: Callable[[], dict[str, object]],
    *,
    stage_name: str,
    timeout_seconds: float | None = None,
    backoff: tuple[float, ...] = RETRY_BACKOFF,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Run ``stage_call`` with FR-013's per-stage timeout + retry policy.

    Returns either the inner call's success result, or a failure
    dict ``{ok: False, error: {code, message, ...}}``. On stage
    timeout the failure code is ``stage_timeout``; on the final
    retry exhaustion of a transient failure the inner call's last
    failure dict is returned unmodified.

    ``timeout_seconds`` controls per-attempt timeout enforcement:

    - ``None`` (default): the inner call runs synchronously in the
      current thread with NO timeout. Retries still fire on
      transient failures but a hung backend will block indefinitely.
      This is the safe-for-tests default — most contract tests use
      in-memory SQLite connections that forbid cross-thread access,
      so the ThreadPoolExecutor path would crash with
      ``ProgrammingError``.
    - A positive float (production): the inner call runs in a
      ``ThreadPoolExecutor`` worker thread bounded by the timeout;
      exceeded budgets surface as ``stage_timeout``. Production
      wiring sets ``TIMEOUT_SECONDS == 30.0``.

    ``backoff`` is the tuple of sleep durations between retry
    attempts — ``(1.0, 2.0)`` per spec → at most 3 attempts. An
    empty tuple disables retries.

    ``sleep_fn`` is injectable for deterministic tests (default
    ``time.sleep``).
    """
    last_result: dict[str, object] = {
        "ok": False,
        "error": {
            "code": "stage_timeout",
            "message": f"{stage_name} did not run (zero-attempt config)",
        },
    }
    max_attempts = 1 + len(backoff)
    use_executor = timeout_seconds is not None and timeout_seconds > 0
    for attempt_idx in range(max_attempts):
        if use_executor:
            # Per-attempt budget via an abandonable daemon worker
            # thread. On timeout we surface ``stage_timeout`` WITHOUT
            # joining the hung worker, so the serializer-holding caller
            # is never blocked past the budget (FR-013).
            assert timeout_seconds is not None  # narrowing for type-checker
            timed_out, result = _run_with_timeout(
                stage_call,
                timeout_seconds=timeout_seconds,
                stage_name=stage_name,
            )
            if timed_out or result is None:
                last_result = {
                    "ok": False,
                    "error": {
                        "code": "stage_timeout",
                        "message": (
                            f"{stage_name} exceeded "
                            f"{timeout_seconds:g}s per-attempt budget"
                        ),
                    },
                }
            else:
                last_result = result
                if result.get("ok"):
                    return result
                if not _is_transient(result):
                    return result
        else:
            # In-thread call — no timeout enforcement, no cross-thread
            # state issues. The default for tests + any caller that
            # explicitly opts out by passing ``timeout_seconds=None``.
            result = stage_call()
            last_result = result
            if result.get("ok"):
                return result
            if not _is_transient(result):
                return result

        # We're here because the attempt failed transiently (or timed
        # out). Sleep the configured back-off, unless this was the
        # final attempt.
        if attempt_idx < len(backoff):
            sleep_fn(backoff[attempt_idx])

    # All attempts exhausted on transient failures — surface the last
    # one as-is per spec (operator sees the closed-set failure code).
    return last_result


__all__ = [
    "run_stage_with_retry",
    "TRANSIENT_FAILURE_CODES",
]
