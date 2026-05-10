"""Unit tests for :func:`agenttower.state.bench_user.normalize_bench_user_for_exec`.

The helper is the FEAT-007 / FR-043 share point with FEAT-004's FR-020
``_resolve_bench_user`` for the ``user:uid`` stripping rule. These
cases pin the contract so the FEAT-004 and FEAT-007 paths cannot drift.
"""

from __future__ import annotations

import pytest

from agenttower.state.bench_user import normalize_bench_user_for_exec


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("brett", "brett"),                  # plain username
        ("brett:1000", "brett"),             # FR-020 ``:uid`` strip
        ("brett:1000:extra", "brett"),       # split on FIRST colon only
        ("  brett  ", "brett"),              # surrounding whitespace
        ("  brett  :1000", "brett"),         # whitespace + suffix
        ("", "root"),                        # empty → root fallback
        (None, "root"),                      # null → root fallback
        (":1000", "root"),                   # all-suffix → root
        ("   ", "root"),                     # whitespace-only → root
    ],
)
def test_normalize_strips_uid_suffix_and_falls_back_to_root(
    raw: str | None, expected: str
) -> None:
    assert normalize_bench_user_for_exec(raw) == expected
