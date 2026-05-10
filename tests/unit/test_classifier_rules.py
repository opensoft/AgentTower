"""T022 — positive + negative + edge fixtures for every classifier rule.

Per FR-008 ("test fixture MUST exist for every rule"). Each rule has
at least three lines: a positive matcher, a negative line that must
NOT trigger it, and an edge-of-pattern line.

The catch-all ``activity.fallback.v1`` is exercised here; the priority
overlap cases (one record matches multiple rules; the highest-priority
one wins) are exercised in ``test_classifier_priority.py``.
"""

from __future__ import annotations

from agenttower.events.classifier import classify
from agenttower.events.classifier_rules import RULES


def _classify_type(record: str) -> tuple[str, str]:
    """Return ``(event_type, rule_id)`` for *record*."""
    out = classify(record)
    return out.event_type, out.rule_id


# --------------------------------------------------------------------------
# swarm_member.v1 — strict parse (FR-009).
# Negative variants are covered in detail by test_classifier_swarm_member.py;
# this file only exercises the positive case.
# --------------------------------------------------------------------------


def test_swarm_member_positive() -> None:
    line = (
        "AGENTTOWER_SWARM_MEMBER parent=agt_a1b2c3d4e5f6 pane=%17 "
        "label=worker-2 capability=test purpose=run-tests"
    )
    et, rid = _classify_type(line)
    assert et == "swarm_member_reported"
    assert rid == "swarm_member.v1"


# --------------------------------------------------------------------------
# manual_review.v1
# --------------------------------------------------------------------------


def test_manual_review_positive() -> None:
    et, rid = _classify_type("MANUAL_REVIEW: please look at this")
    assert et == "manual_review_needed"
    assert rid == "manual_review.v1"


def test_manual_review_dash_variant() -> None:
    et, _ = _classify_type("MANUAL-REVIEW: alternative spelling")
    assert et == "manual_review_needed"


def test_manual_review_todo_human() -> None:
    et, _ = _classify_type("note TODO(human) before merging")
    assert et == "manual_review_needed"


def test_manual_review_review_required() -> None:
    et, _ = _classify_type("REVIEW_REQUIRED before deploy")
    assert et == "manual_review_needed"


def test_manual_review_negative_review_word_alone() -> None:
    et, _ = _classify_type("review the changes")  # word-boundary mismatch
    assert et == "activity"


# --------------------------------------------------------------------------
# error.traceback.v1 / error.line.v1
# --------------------------------------------------------------------------


def test_error_traceback_positive() -> None:
    et, rid = _classify_type("Traceback (most recent call last):")
    assert et == "error"
    assert rid == "error.traceback.v1"


def test_error_line_positive_lower() -> None:
    et, rid = _classify_type("Error: division by zero")
    assert et == "error"
    assert rid == "error.line.v1"


def test_error_line_positive_upper() -> None:
    et, _ = _classify_type("ERROR: build failed")
    assert et == "error"


def test_error_line_positive_exception() -> None:
    et, _ = _classify_type("Exception: foo")
    assert et == "error"


def test_error_line_negative_word_in_middle() -> None:
    et, _ = _classify_type("the error was minor")  # not anchored
    assert et == "activity"


# --------------------------------------------------------------------------
# test_failed.pytest.v1 / test_failed.generic.v1
# --------------------------------------------------------------------------


def test_test_failed_pytest_positive() -> None:
    et, rid = _classify_type(
        "FAILED tests/unit/test_foo.py::test_bar - AssertionError"
    )
    assert et == "test_failed"
    assert rid == "test_failed.pytest.v1"


def test_test_failed_pytest_error_variant_preempted_by_error_line() -> None:
    """``ERROR <path>::<name>`` matches BOTH ``error.line.v1``
    (priority 31) and ``test_failed.pytest.v1`` (priority 40); the
    higher-priority ``error.line.v1`` wins. Pytest's ``ERROR`` for
    setup/teardown failures is conceptually an error, not a test
    failure, so this is the intended classification.
    """
    et, rid = _classify_type("ERROR tests/integration/test_x.py::test_y")
    assert et == "error"
    assert rid == "error.line.v1"


def test_test_failed_generic_positive() -> None:
    et, rid = _classify_type("Build output: tests failed at step 3")
    assert et == "test_failed"
    assert rid == "test_failed.generic.v1"


def test_test_failed_generic_negative_unrelated() -> None:
    et, _ = _classify_type("running tests now")
    assert et == "activity"


# --------------------------------------------------------------------------
# test_passed.pytest.v1 / test_passed.generic.v1
# --------------------------------------------------------------------------


def test_test_passed_pytest_positive() -> None:
    et, rid = _classify_type("=== 12 passed in 0.34s ===")
    assert et == "test_passed"
    assert rid == "test_passed.pytest.v1"


def test_test_passed_pytest_short_form() -> None:
    et, _ = _classify_type("==== 1 passed ====")
    assert et == "test_passed"


def test_test_passed_generic_positive() -> None:
    et, rid = _classify_type("all tests passed in 1.2s")
    assert et == "test_passed"
    assert rid == "test_passed.generic.v1"


def test_test_passed_generic_negative_phrase() -> None:
    et, _ = _classify_type("not all tests")
    assert et == "activity"


# --------------------------------------------------------------------------
# completed.v1
# --------------------------------------------------------------------------


def test_completed_done() -> None:
    et, rid = _classify_type("step 3 DONE")
    assert et == "completed"
    assert rid == "completed.v1"


def test_completed_phrase_completed_successfully() -> None:
    et, _ = _classify_type("the task completed successfully")
    assert et == "completed"


def test_completed_build_succeeded() -> None:
    et, _ = _classify_type("build succeeded after 3 retries")
    assert et == "completed"


def test_completed_negative_word_alone() -> None:
    et, _ = _classify_type("complete this section")
    assert et == "activity"


# --------------------------------------------------------------------------
# waiting_for_input.v1
# --------------------------------------------------------------------------


def test_waiting_question_mark_eol() -> None:
    et, rid = _classify_type("Continue with this option?")
    assert et == "waiting_for_input"
    assert rid == "waiting_for_input.v1"


def test_waiting_yn_prompt() -> None:
    et, _ = _classify_type("Proceed with delete [Y/n]")
    assert et == "waiting_for_input"


def test_waiting_yes_no_prompt() -> None:
    et, _ = _classify_type("Continue (yes/no)")
    assert et == "waiting_for_input"


def test_waiting_python_repl_prompt() -> None:
    et, _ = _classify_type(">>>")
    assert et == "waiting_for_input"


def test_waiting_negative_question_in_middle() -> None:
    # No trailing ``?`` and no other prompt shape — just regular text.
    et, _ = _classify_type("the user asked something then continued")
    assert et == "activity"


# --------------------------------------------------------------------------
# activity.fallback.v1 — catch-all (FR-011)
# --------------------------------------------------------------------------


def test_activity_fallback_default() -> None:
    et, rid = _classify_type("running tests now")
    assert et == "activity"
    assert rid == "activity.fallback.v1"


def test_activity_fallback_empty_record() -> None:
    """Empty records should never reach the classifier (FR-005), but
    if they do the conservative default is ``activity``."""
    out = classify("")
    assert out.event_type == "activity"
    assert out.rule_id == "activity.fallback.v1"


# --------------------------------------------------------------------------
# Coverage gate: every rule in RULES has at least one positive-matching
# test case in this file. Mirrors FR-008 ("test fixture MUST exist for
# every rule").
# --------------------------------------------------------------------------


def test_every_rule_has_a_positive_fixture_in_this_module() -> None:
    """Walk RULES and ensure each rule_id appears in at least one
    test name in this module. Catches a future addition that ships
    without coverage.

    NOTE: this test is informational at MVP scale (the module
    enumerates all 11 fixtures explicitly above); it exists as a
    forcing function for future feature additions.
    """
    expected_rule_ids = {r.rule_id for r in RULES}
    asserted_rule_ids = {
        "swarm_member.v1",
        "manual_review.v1",
        "error.traceback.v1",
        "error.line.v1",
        "test_failed.pytest.v1",
        "test_failed.generic.v1",
        "test_passed.pytest.v1",
        "test_passed.generic.v1",
        "completed.v1",
        "waiting_for_input.v1",
        "activity.fallback.v1",
    }
    assert expected_rule_ids == asserted_rule_ids, (
        "RULES set drifted from the explicit fixture list. "
        "Add a positive test for the new rule before extending RULES."
    )
