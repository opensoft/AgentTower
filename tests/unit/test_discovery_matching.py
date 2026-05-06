"""Unit tests for the FEAT-003 matching predicate."""

from __future__ import annotations

from agenttower.discovery.matching import MatchingRule, default_rule


def test_default_rule_is_bench() -> None:
    assert default_rule().name_contains == ("bench",)


def test_substring_match_is_case_insensitive() -> None:
    rule = default_rule()
    assert rule.matches("py-bench")
    assert rule.matches("PY-BENCH")
    assert rule.matches("MyBenchContainer")


def test_non_matching_name_returns_false() -> None:
    rule = default_rule()
    assert not rule.matches("redis")
    assert not rule.matches("postgres")
    assert not rule.matches("")


def test_multiple_substrings_any_match() -> None:
    rule = MatchingRule(name_contains=("bench", "dev"))
    assert rule.matches("api-dev")
    assert rule.matches("py-bench")
    assert not rule.matches("postgres")


def test_empty_substring_is_ignored() -> None:
    rule = MatchingRule(name_contains=("",))
    assert not rule.matches("anything")


def test_casefold_preserves_unicode_equivalence() -> None:
    rule = MatchingRule(name_contains=("ß",))
    # casefold() folds 'ß' to 'ss'; both should match
    assert rule.matches("strasse")
    assert rule.matches("straße")
