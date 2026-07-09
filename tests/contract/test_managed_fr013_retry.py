"""FEAT-013 FR-013 retry/timeout policy tests (Workstream 1 / C3).

The two FR-013 acceptance tests (timeout + retry) previously lived in
``test_managed_layout_create.py`` as ``@pytest.mark.skip`` placeholders
deferring to "tmux_create.py-layer concern". The actual runtime policy
lives in ``managed_sessions/_retry.py``; this module exercises it
directly with injected sleep + a recording backend so the assertions
are deterministic and don't burn 30 wall-clock seconds.

Covers:

- **Per-attempt 30s budget** — the timeout fires by joining an
  abandonable daemon worker thread and surfaces ``stage_timeout``
  WITHOUT waiting for the hung worker to finish (FR-013).
- **2x retry with 1s/2s back-off on transient failures** — the
  closed-set transient codes
  (``docker_exec_failed``/``docker_exec_timeout``/``tmux_unavailable``/
  ``tmux_no_server``/``stage_timeout``) retry; permanent failures do not.
- **Final-attempt exhaustion semantics** — after 1 + len(RETRY_BACKOFF)
  attempts the last failure dict is returned unmodified.

The default ``timeout_seconds=None`` in-thread path is also covered for
its retry-without-timeout semantic (used by the existing
``spawn_layout_in_background`` tests which can't tolerate cross-thread
SQLite access).
"""

from __future__ import annotations

import time

import pytest

from agenttower.managed_sessions._retry import (
    TRANSIENT_FAILURE_CODES,
    run_stage_with_retry,
)
from agenttower.managed_sessions.tmux_create import RETRY_BACKOFF, TIMEOUT_SECONDS


def test_fr013_constants_match_spec() -> None:
    """Sanity guard: the module-level constants matches the FR-013
    spec wording (30s per-attempt, 1s/2s back-off → 3 attempts max)."""
    assert TIMEOUT_SECONDS == 30
    assert RETRY_BACKOFF == (1.0, 2.0)


def test_happy_path_returns_immediately_no_retries() -> None:
    """A successful first attempt must NOT trigger retries."""
    calls = []

    def stage():  # noqa: ANN201
        calls.append(time.monotonic())
        return {"ok": True, "tmux_pane_id": "%0", "launch_alive": True}

    result = run_stage_with_retry(stage, stage_name="tmux_spawn")
    assert result["ok"] is True
    assert len(calls) == 1


def test_permanent_failure_returns_immediately_no_retries() -> None:
    """A non-transient failure code (e.g. label conflict) surfaces on
    the first attempt — no retries because retrying a permanent error
    burns budget for nothing."""
    calls = []

    def stage():  # noqa: ANN201
        calls.append(1)
        return {
            "ok": False,
            "error": {"code": "managed_pane_label_conflict", "message": "test"},
        }

    sleeps: list[float] = []
    result = run_stage_with_retry(
        stage, stage_name="register", sleep_fn=sleeps.append,
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "managed_pane_label_conflict"
    assert len(calls) == 1
    assert sleeps == []  # no back-off was incurred


def test_transient_failure_retries_with_documented_backoff() -> None:
    """FR-013 amendment: transient failures retry 2x with 1s, 2s
    back-off. Inject the failure on every attempt; the final result
    is the last transient failure (after both retries)."""
    calls = []

    def stage():  # noqa: ANN201
        calls.append(1)
        return {
            "ok": False,
            "error": {"code": "docker_exec_timeout", "message": "test"},
        }

    sleeps: list[float] = []
    result = run_stage_with_retry(
        stage, stage_name="tmux_spawn", sleep_fn=sleeps.append,
    )

    # 1 initial + 2 retries = 3 attempts.
    assert len(calls) == 3
    # Two back-off sleeps between three attempts: (1s, 2s).
    assert sleeps == [1.0, 2.0]
    # Final returned dict is the last transient failure unmodified.
    assert result["ok"] is False
    assert result["error"]["code"] == "docker_exec_timeout"


def test_transient_then_success_returns_success_after_retry() -> None:
    """First call fails transiently; second succeeds → return success.
    Only one back-off sleep should be incurred."""
    attempt = [0]

    def stage():  # noqa: ANN201
        attempt[0] += 1
        if attempt[0] == 1:
            return {
                "ok": False,
                "error": {"code": "docker_exec_failed", "message": "test"},
            }
        return {"ok": True, "tmux_pane_id": "%0", "launch_alive": True}

    sleeps: list[float] = []
    result = run_stage_with_retry(
        stage, stage_name="tmux_spawn", sleep_fn=sleeps.append,
    )
    assert result["ok"] is True
    assert attempt[0] == 2
    assert sleeps == [1.0]  # one back-off between the two attempts


def test_stage_timeout_surfaces_when_inner_call_exceeds_budget() -> None:
    """When ``timeout_seconds`` is set and the inner call takes longer,
    the helper surfaces a ``stage_timeout`` failure. We use a tiny
    timeout (0.05s) + a slow stub to keep the test fast."""

    def slow_stage():  # noqa: ANN201
        time.sleep(0.5)
        return {"ok": True}

    sleeps: list[float] = []
    result = run_stage_with_retry(
        slow_stage,
        stage_name="tmux_spawn",
        timeout_seconds=0.05,
        # Suppress real back-off sleeps to keep the test under a second.
        sleep_fn=sleeps.append,
    )
    # All 3 attempts time out; final result has the stage_timeout code.
    assert result["ok"] is False
    assert result["error"]["code"] == "stage_timeout"


def test_stage_timeout_does_not_block_caller_on_hung_worker() -> None:
    """Regression for the FR-013 timeout-enforcement bug.

    The earlier ``ThreadPoolExecutor`` + ``with`` implementation called
    ``shutdown(wait=True)`` on context exit, so on timeout the caller
    STILL blocked until the hung worker returned — defeating the
    per-stage budget while the serializer lock was held. The
    daemon-thread join must return near the budget regardless of how
    long the worker runs.

    Here the worker sleeps ~5s per attempt but the budget is 0.05s and
    back-off sleeps are suppressed. With the bug, this took ~15s
    (3 × 5s); fixed, it returns in well under a second.
    """

    def hung_stage():  # noqa: ANN201
        time.sleep(5.0)
        return {"ok": True}

    started = time.monotonic()
    result = run_stage_with_retry(
        hung_stage,
        stage_name="tmux_spawn",
        timeout_seconds=0.05,
        sleep_fn=lambda _s: None,  # suppress 1s/2s back-off
    )
    elapsed = time.monotonic() - started

    assert result["ok"] is False
    assert result["error"]["code"] == "stage_timeout"
    # 3 attempts × 0.05s budget = ~0.15s of joins; allow generous slack
    # for scheduler jitter but stay far below the 15s a blocking
    # shutdown(wait=True) would have cost.
    assert elapsed < 1.0, f"caller blocked on hung worker: {elapsed:.2f}s"


def test_all_documented_transient_codes_trigger_retry() -> None:
    """Closed set of transient failure codes — each one should trigger
    the retry loop. A regression that narrowed the set would surface
    here because the test would loop only once for the missing code."""
    for transient_code in TRANSIENT_FAILURE_CODES:
        attempts = [0]

        def stage():  # noqa: ANN201
            attempts[0] += 1
            return {
                "ok": False,
                "error": {"code": transient_code, "message": "test"},
            }

        run_stage_with_retry(
            stage, stage_name="test", sleep_fn=lambda _s: None,
        )
        assert attempts[0] == 3, (
            f"transient code {transient_code!r} did not trigger 3 attempts"
        )


def test_empty_backoff_disables_retries() -> None:
    """Passing ``backoff=()`` reduces the attempt count to 1 — useful
    when an outer scheduler wants to control the retry loop instead."""
    calls = []

    def stage():  # noqa: ANN201
        calls.append(1)
        return {
            "ok": False,
            "error": {"code": "docker_exec_failed", "message": "test"},
        }

    run_stage_with_retry(
        stage, stage_name="tmux_spawn", backoff=(),
        sleep_fn=lambda _s: None,
    )
    assert len(calls) == 1
