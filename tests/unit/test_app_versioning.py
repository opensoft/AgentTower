"""FEAT-014 T021 — Versioning contract regression for the v1.0 → v1.1 bump.

Four sub-assertions, each mapped to its FR for traceability per
tasks.md T021. Every assertion is ``@pytest.mark.v1_1``-marked so T023's
SC-004 v1.0-compat regression can deselect them via ``pytest -m 'not v1_1'``.

This file is NEW. FEAT-011's app-contract assertions live under
`tests/unit/` (the repo's `tests/contract/` directory holds only the
earlier CLI/socket contract tests), so FEAT-014 keeps its app-contract
tests under `tests/unit/` too, per the M4 polish in commit ``768e2ca``.

Maps to:

* **FR-013** — daemon advertises ``app_contract_version == "1.1"`` and
  supported-minor-range maximum includes ``"1.1"``.
* **FR-015** — no new capability flag at v1.1 (the flag dict remains
  empty per the carry-through alias documented in versioning.py).
* **FR-014** + US4 acceptance #2 — major-version rejection behavior is
  unchanged for any client major ≠ 1.
"""

from __future__ import annotations

import pytest

from agenttower.app_contract import versioning


# ─── FR-013 (a) — version advertisement ────────────────────────────────────


@pytest.mark.v1_1
def test_t021a_fr013_app_contract_version_is_1_1() -> None:
    """FR-013 (a): the advertised contract version is exactly ``"1.1"``
    after T002's bump."""
    assert versioning.APP_CONTRACT_VERSION == "1.1"
    assert versioning.APP_CONTRACT_MAJOR == 1
    assert versioning.APP_CONTRACT_MINOR == 1


# ─── FR-013 (b) — supported minor range maximum is 1.1 ─────────────────────


@pytest.mark.v1_1
def test_t021b_fr013_supported_minor_range_max_is_1_1() -> None:
    """FR-013 (b): the supported-minor-range maximum widens to include 1.1
    so range-checking clients see the new advertised minor."""
    assert versioning.SUPPORTED_MINOR_RANGE == {"min": "1.0", "max": "1.1"}
    assert versioning.SUPPORTED_MINOR_RANGE["max"] == "1.1"


# ─── FR-015 (c) — no new capability flag at v1.1 ───────────────────────────


@pytest.mark.v1_1
def test_t021c_fr015_capability_flags_remain_empty() -> None:
    """FR-015 (c): v1.1 introduces no new capability flag. The legacy
    ``CAPABILITY_FLAGS_V1_0`` and the version-agnostic ``CAPABILITY_FLAGS``
    alias both remain the empty dict per the v1.0+v1.1 carry-through note
    in versioning.py (post-M5(a) alias)."""
    assert versioning.CAPABILITY_FLAGS_V1_0 == {}
    assert versioning.CAPABILITY_FLAGS == {}
    assert versioning.CAPABILITY_FLAGS is versioning.CAPABILITY_FLAGS_V1_0


# ─── FR-014 (d) + US4 acceptance #2 — major rejection unchanged ────────────


@pytest.mark.v1_1
@pytest.mark.parametrize(
    "client_major,expected",
    [
        (0, False),  # too old → incompatible
        (1, True),   # only match
        (2, False),  # future major → still incompatible (FR-014 invariant)
        (3, False),  # arbitrary higher major
        (-1, False), # malformed
    ],
)
def test_t021d_fr014_major_version_rejection_behavior_unchanged(
    client_major: int, expected: bool
) -> None:
    """FR-014 (d) + US4 acceptance #2: the major-version compatibility
    helper rejects every major ≠ 1, identical to v1.0's behavior. A v1.0
    client gating on ``is_major_compatible(client_major)`` sees the same
    True/False values whether the daemon advertises 1.0 or 1.1 — this is
    what makes the SC-004 regression suite (T023) re-runnable against a
    v1.1 daemon without modification."""
    assert versioning.is_major_compatible(client_major) is expected


@pytest.mark.v1_1
def test_t021d_fr014_parse_major_minor_handles_v1_1_string() -> None:
    """Companion to T021(d): ``parse_major_minor`` parses ``"1.1"``
    identically to ``"1.0"`` so the bump doesn't accidentally break the
    handshake parser (still returns the integer tuple)."""
    assert versioning.parse_major_minor("1.0") == (1, 0)
    assert versioning.parse_major_minor("1.1") == (1, 1)
    # Hypothetical future minors parse without raising.
    assert versioning.parse_major_minor("1.2") == (1, 2)
    # Different major still parses (rejection is via is_major_compatible).
    assert versioning.parse_major_minor("2.0") == (2, 0)
