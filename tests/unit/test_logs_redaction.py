"""Unit tests for FEAT-007 redaction utility (T100-T104 / FR-027..FR-030 / FR-049).

Covers:
* Unanchored token patterns match anywhere with \b protection.
* Anchored line patterns match only standalone lines.
* Per-line application; tokens spanning \n NOT redacted.
* Pure function: same input → same output across 1000 invocations (SC-004).
* re.ASCII flag verified (locale-independent).
* Byte offsets unaffected by redaction (FR-030 — checked via fixed-byte fixture).
"""

from __future__ import annotations

import re

from agenttower.logs.redaction import (
    _ANCHORED_REDACTORS,
    _UNANCHORED_PATTERNS,
    redact_lines,
    redact_one_line,
)


# ---------------------------------------------------------------------------
# Unanchored token patterns (FR-028)
# ---------------------------------------------------------------------------


class TestUnanchoredPatterns:
    def test_openai_key_replaced(self) -> None:
        out = redact_one_line("auth=sk-AAAAAAAAAAAAAAAAAAAAAA tail")
        assert "sk-AAAA" not in out
        assert "<redacted:openai-key>" in out

    def test_github_pat_replaced(self) -> None:
        out = redact_one_line("token=ghp_BBBBBBBBBBBBBBBBBBBBBB")
        assert "ghp_B" not in out
        assert "<redacted:github-token>" in out

    def test_github_server_token_replaced(self) -> None:
        out = redact_one_line("token=ghs_CCCCCCCCCCCCCCCCCCCCCC")
        assert "ghs_C" not in out
        assert "<redacted:github-token>" in out

    def test_aws_access_key_replaced(self) -> None:
        # AKIA + 16 [A-Z0-9] (20 chars).
        out = redact_one_line("key=AKIAIOSFODNN7EXAMPLE end")
        assert "AKIAIOSFODNN7EXAMPLE" not in out
        assert "<redacted:aws-access-key>" in out

    def test_bearer_token_replaced(self) -> None:
        out = redact_one_line("Authorization: Bearer abcdefghij1234567890.xy")
        assert "abcdefghij1234567890" not in out
        assert "Bearer <redacted:bearer>" in out

    def test_multiple_matches_in_single_line(self) -> None:
        out = redact_one_line(
            "first sk-AAAAAAAAAAAAAAAAAAAAAA second ghp_BBBBBBBBBBBBBBBBBBBBBB"
        )
        assert "sk-A" not in out
        assert "ghp_B" not in out

    def test_word_boundary_protection(self) -> None:
        # "xsk-..." has no \b before sk- → must NOT match.
        out = redact_one_line("xsk-AAAAAAAAAAAAAAAAAAAAAA")
        assert out == "xsk-AAAAAAAAAAAAAAAAAAAAAA"


# ---------------------------------------------------------------------------
# Anchored line patterns (FR-028)
# ---------------------------------------------------------------------------


class TestAnchoredPatterns:
    def test_jwt_replaced_when_standalone(self) -> None:
        jwt = (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        out = redact_one_line(jwt)
        assert out == "<redacted:jwt>"

    def test_jwt_under_32_chars_not_redacted(self) -> None:
        # Three-segment but too short.
        short = "a.b.c"
        out = redact_one_line(short)
        assert out == short

    def test_jwt_in_mixed_line_not_redacted(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.SflKxwRJSMeKKF2QT4fwpMeJ"
        out = redact_one_line(f"prefix {jwt} suffix")
        assert out == f"prefix {jwt} suffix"

    def test_env_secret_redacted(self) -> None:
        out = redact_one_line("OPENAI_API_KEY=sk-secret-12345")
        assert out == "OPENAI_API_KEY=<redacted:env-secret>"

    def test_env_token_redacted(self) -> None:
        out = redact_one_line("MY_AUTH_TOKEN=hunter2hunter2hunter2")
        assert out == "MY_AUTH_TOKEN=<redacted:env-secret>"

    def test_env_non_match_passthrough(self) -> None:
        out = redact_one_line("FOO=bar")
        assert out == "FOO=bar"


# ---------------------------------------------------------------------------
# Per-line semantics (FR-029)
# ---------------------------------------------------------------------------


class TestPerLineSemantics:
    def test_split_on_newline_only(self) -> None:
        # \r should NOT be a line separator (Research R-012).
        text = "line1\r\nline2"
        # split('\n') yields ['line1\r', 'line2'] — the \r is preserved.
        out = redact_lines(text)
        assert "\r" in out

    def test_token_spanning_newlines_not_redacted(self) -> None:
        text = "sk-AAAA\nAAAAAAAAAAAAAAAAAA"
        out = redact_lines(text)
        # Both lines pass through because neither matches anchored OR unanchored
        # patterns on its own (both partial fragments are too short).
        assert out == "sk-AAAA\nAAAAAAAAAAAAAAAAAA"

    def test_join_with_newline(self) -> None:
        text = "ab\ncd\nef"
        out = redact_lines(text)
        assert out == "ab\ncd\nef"

    def test_empty_string(self) -> None:
        assert redact_lines("") == ""

    def test_no_match_passthrough_byte_for_byte(self) -> None:
        text = "Built target ./bin/agenttower in 4.2s"
        assert redact_lines(text) == text


# ---------------------------------------------------------------------------
# Determinism (SC-004)
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_input_same_output_1000_iterations(self) -> None:
        fixture = (
            "build started\n"
            "auth=sk-AAAAAAAAAAAAAAAAAAAAAA tail\n"
            "OPENAI_API_KEY=sk-test-1234\n"
        )
        first = redact_lines(fixture)
        for _ in range(1000):
            assert redact_lines(fixture) == first

    def test_re_ascii_flag_set_on_every_unanchored(self) -> None:
        for pattern, _replacement in _UNANCHORED_PATTERNS:
            assert pattern.flags & re.ASCII, (
                f"{pattern.pattern!r} missing re.ASCII flag (FR-049)"
            )


# ---------------------------------------------------------------------------
# Byte-offset preservation invariant (FR-030)
# ---------------------------------------------------------------------------


def test_redaction_does_not_shrink_offsets() -> None:
    """FR-030: redaction operates on display content; byte_offset advancement
    in log_offsets is computed against the ORIGINAL bytes, not the redacted
    output. This test asserts the original input length and content stay
    available for offset bookkeeping (i.e., the redaction utility doesn't
    consume the input out from under the caller)."""
    original = "auth=sk-AAAAAAAAAAAAAAAAAAAAAA continuing"
    out = redact_lines(original)
    # The original is unchanged in the caller's hand.
    assert original == "auth=sk-AAAAAAAAAAAAAAAAAAAAAA continuing"
    # The redacted version differs but that's a render-time view only.
    assert out != original
