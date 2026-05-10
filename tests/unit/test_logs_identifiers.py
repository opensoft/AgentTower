"""Unit tests for FEAT-007 attachment_id generation (T014 / R-001 / FR-035)."""

from __future__ import annotations

import re

from agenttower.logs.identifiers import (
    ATTACHMENT_ID_RE,
    MAX_ATTACHMENT_ID_RETRIES,
    generate_attachment_id,
    is_valid_attachment_id,
)


def test_shape_lat_12_hex_lowercase() -> None:
    for _ in range(100):
        aid = generate_attachment_id()
        assert ATTACHMENT_ID_RE.match(aid), aid


def test_namespace_non_collision_with_agt() -> None:
    for _ in range(100):
        assert not generate_attachment_id().startswith("agt_")


def test_max_retry_budget_is_5() -> None:
    """FR-035 / R-001: the retry budget is bounded at 5 attempts."""
    assert MAX_ATTACHMENT_ID_RETRIES == 5


def test_is_valid_attachment_id_negative_cases() -> None:
    assert not is_valid_attachment_id("agt_abc123def456")  # wrong prefix
    assert not is_valid_attachment_id("LAT_abc123def456")  # uppercase prefix
    assert not is_valid_attachment_id("lat_ABC123DEF456")  # uppercase hex
    assert not is_valid_attachment_id("lat_abc123def45")   # too short
    assert not is_valid_attachment_id("lat_abc123def4567") # too long
    assert not is_valid_attachment_id(123)                 # not a string
    assert not is_valid_attachment_id(None)


def test_is_valid_attachment_id_positive() -> None:
    aid = generate_attachment_id()
    assert is_valid_attachment_id(aid)
