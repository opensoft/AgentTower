"""Unit tests for FEAT-006 label / project_path sanitization + bounds (T014).

Covers FR-033 / FR-034:
* NUL byte stripping.
* C0 control byte stripping.
* ``label`` ≤ 64 chars (over-bound raises ``field_too_long``, NEVER truncated).
* ``project_path`` ≤ 4096 chars; empty / relative / ``..`` / NUL all rejected
  with ``project_path_invalid``.
* Multi-byte UTF-8 boundary preserved by inheritance from
  :func:`agenttower.tmux.parsers.sanitize_text`.
"""

from __future__ import annotations

import pytest

from agenttower.agents.errors import RegistrationError
from agenttower.agents.validation import (
    LABEL_MAX,
    PROJECT_PATH_MAX,
    validate_label,
    validate_project_path,
)


def test_label_strips_nul_and_c0() -> None:
    assert validate_label("ok\x00\x01\x02") == "ok"
    # \t and \n are normalized to single spaces (FEAT-004 sanitize convention).
    assert validate_label("a\tb\nc") == "a b c"


def test_label_at_bound() -> None:
    s = "x" * LABEL_MAX
    assert validate_label(s) == s


def test_label_over_bound_rejected_not_truncated() -> None:
    s = "x" * (LABEL_MAX + 1)
    with pytest.raises(RegistrationError) as info:
        validate_label(s)
    assert info.value.code == "field_too_long"


def test_label_preserves_multibyte_utf8() -> None:
    s = "ホエール🐳"
    assert validate_label(s) == s


def test_label_rejects_non_string() -> None:
    with pytest.raises(RegistrationError) as info:
        validate_label(12345)  # type: ignore[arg-type]
    assert info.value.code == "value_out_of_set"


# ------------------------- project_path -------------------------- #


def test_project_path_canonical_absolute_accepted() -> None:
    assert validate_project_path("/workspace/acme") == "/workspace/acme"
    assert validate_project_path("/") == "/"


def test_project_path_empty_rejected() -> None:
    with pytest.raises(RegistrationError) as info:
        validate_project_path("")
    assert info.value.code == "project_path_invalid"


def test_project_path_relative_rejected() -> None:
    with pytest.raises(RegistrationError) as info:
        validate_project_path("workspace/acme")
    assert info.value.code == "project_path_invalid"


def test_project_path_dotdot_segment_rejected() -> None:
    with pytest.raises(RegistrationError) as info:
        validate_project_path("/a/../b")
    assert info.value.code == "project_path_invalid"


def test_project_path_nul_byte_rejected() -> None:
    with pytest.raises(RegistrationError) as info:
        validate_project_path("/a\x00b")
    assert info.value.code == "project_path_invalid"


def test_project_path_oversized_rejected() -> None:
    s = "/" + "x" * PROJECT_PATH_MAX
    with pytest.raises(RegistrationError) as info:
        validate_project_path(s)
    assert info.value.code == "field_too_long"


def test_project_path_at_bound_accepted() -> None:
    s = "/" + "x" * (PROJECT_PATH_MAX - 1)
    assert validate_project_path(s) == s
    assert len(s) == PROJECT_PATH_MAX


def test_project_path_control_bytes_are_sanitized() -> None:
    assert validate_project_path("/workspace/\tacme\n\r") == "/workspace/acme"
