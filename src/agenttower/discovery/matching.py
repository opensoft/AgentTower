"""Bench-name matching predicate for FEAT-003."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchingRule:
    """Configurable case-insensitive substring rule.

    `name_contains` is a tuple of substrings; a container name matches when
    *any* substring is present after `.casefold()` on both sides.
    """

    name_contains: tuple[str, ...]

    def matches(self, name: str) -> bool:
        folded = name.casefold()
        for needle in self.name_contains:
            if needle and needle.casefold() in folded:
                return True
        return False


def default_rule() -> MatchingRule:
    return MatchingRule(name_contains=("bench",))
