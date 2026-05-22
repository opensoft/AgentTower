"""FEAT-011 T083 — SC-003 + SC-021 error-contract verification.

Registry-driven assertions over the FEAT-011 closed-set error code
surface (FR-033 / FR-034 / FR-034a):

* every code matches the FR-034 regex and the closed set has exactly
  27 entries;
* the per-code ``details`` registry is honored — codes with required
  keys reject a payload missing one of them, and codes NOT in the
  registry reject a non-empty ``details`` (the FR-034a "unregistered
  codes carry {}" rule);
* ``envelope.failure`` always produces the FR-033 failure shape with a
  ``details`` dict.

These tests touch only the contract modules — no DB, no socket.
"""

from __future__ import annotations

import pytest

from agenttower.app_contract import envelope as app_envelope
from agenttower.app_contract import errors as app_errors
from agenttower.app_contract.errors import ContractViolation
from agenttower.app_contract.versioning import APP_CONTRACT_VERSION


# ─── Closed-set shape (FR-034) ───────────────────────────────────────────


def test_error_codes_is_a_closed_set_of_27() -> None:
    """FR-034: the closed set has exactly 27 entries at v1.0."""
    assert len(app_errors.ERROR_CODES) == 27


def test_malformed_request_is_in_the_closed_set() -> None:
    """Round-4 added ``malformed_request`` to the closed set (FR-003b)."""
    assert "malformed_request" in app_errors.ERROR_CODES
    assert app_errors.MALFORMED_REQUEST == "malformed_request"


def test_every_code_matches_the_fr034_regex() -> None:
    """FR-034: ``error.code`` MUST match ``^[a-z][a-z0-9_]*$``."""
    assert app_errors.CODE_REGEX.pattern == r"^[a-z][a-z0-9_]*$"
    for code in app_errors.ERROR_CODES:
        assert app_errors.CODE_REGEX.match(code), code


def test_named_constants_resolve_to_closed_set_members() -> None:
    """The ``errors.py`` constants are the authoritative spelling."""
    for const in (
        app_errors.VALIDATION_FAILED,
        app_errors.PAYLOAD_TOO_LARGE,
        app_errors.HOST_ONLY,
        app_errors.INTERNAL_ERROR,
        app_errors.PANE_NOT_FOUND,
    ):
        assert const in app_errors.ERROR_CODES


# ─── Per-code ``details`` registry (FR-034a) ─────────────────────────────


@pytest.mark.parametrize("code", sorted(app_errors.DETAILS_REQUIRED_KEYS))
def test_registered_code_accepts_exactly_its_required_keys(code: str) -> None:
    """A ``details`` dict carrying exactly the registered required keys
    passes ``validate_details`` without raising."""
    required = app_errors.DETAILS_REQUIRED_KEYS[code]
    details = {key: "value" for key in required}
    # Must not raise.
    app_errors.validate_details(code, details)


@pytest.mark.parametrize(
    "code",
    sorted(
        c
        for c, req in app_errors.DETAILS_REQUIRED_KEYS.items()
        if req  # only codes that actually require >= 1 key
    ),
)
def test_registered_code_rejects_missing_required_key(code: str) -> None:
    """Dropping a required key triggers ``ContractViolation`` (FR-034a)."""
    required = sorted(app_errors.DETAILS_REQUIRED_KEYS[code])
    omitted = required[0]
    details = {key: "value" for key in required if key != omitted}
    with pytest.raises(ContractViolation):
        app_errors.validate_details(code, details)


def test_unregistered_code_rejects_non_empty_details() -> None:
    """FR-034a: codes NOT in the registry MUST carry ``details == {}``."""
    # host_only is in the closed set but has no registry entry.
    assert app_errors.HOST_ONLY not in app_errors.DETAILS_REQUIRED_KEYS
    with pytest.raises(ContractViolation):
        app_errors.validate_details(app_errors.HOST_ONLY, {"x": 1})


def test_unregistered_code_accepts_empty_details() -> None:
    """An unregistered code with ``{}`` is valid."""
    app_errors.validate_details(app_errors.HOST_ONLY, {})


def test_validate_details_rejects_code_outside_closed_set() -> None:
    """A regex-valid but non-closed-set code is a ContractViolation."""
    with pytest.raises(ContractViolation):
        app_errors.validate_details("not_a_real_code", {})


def test_validate_details_rejects_bad_code_shape() -> None:
    """A code violating the FR-034 regex is rejected."""
    for bad in ("HostOnly", "1bad", "has-dash", ""):
        with pytest.raises(ContractViolation):
            app_errors.validate_details(bad, {})


def test_validate_details_rejects_non_object_details() -> None:
    """FR-033: ``error.details`` must be a JSON object."""
    for bad in (None, [], "x", 7):
        with pytest.raises(ContractViolation):
            app_errors.validate_details(app_errors.HOST_ONLY, bad)  # type: ignore[arg-type]


def test_registered_code_allows_extra_keys_beyond_required() -> None:
    """FR-034a: registered codes MAY carry additional keys (additive)."""
    required = sorted(app_errors.DETAILS_REQUIRED_KEYS[app_errors.VALIDATION_FAILED])
    details = {key: "value" for key in required}
    details["extra"] = "additive"
    app_errors.validate_details(app_errors.VALIDATION_FAILED, details)


# ─── envelope.failure end-to-end shape (FR-033) ──────────────────────────


def test_failure_envelope_shape_for_registered_code() -> None:
    """``envelope.failure`` produces the FR-033 failure shape."""
    env = app_envelope.failure(
        app_errors.VALIDATION_FAILED,
        "bad input",
        {"field": "limit", "reason": "out of bounds"},
    )
    assert env["ok"] is False
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    err = env["error"]
    assert set(err.keys()) == {"code", "message", "details"}
    assert err["code"] == app_errors.VALIDATION_FAILED
    assert err["message"] == "bad input"
    assert isinstance(err["details"], dict)
    assert err["details"]["field"] == "limit"


def test_failure_envelope_details_defaults_to_empty_dict() -> None:
    """An unregistered code with no details still gets ``details == {}``."""
    env = app_envelope.failure(app_errors.HOST_ONLY, "host only")
    assert env["ok"] is False
    assert env["error"]["details"] == {}
    assert isinstance(env["error"]["details"], dict)


def test_failure_envelope_for_payload_too_large() -> None:
    """``payload_too_large`` carries its registered size/actual keys."""
    env = app_envelope.failure(
        app_errors.PAYLOAD_TOO_LARGE,
        "too big",
        {"size_limit_bytes": 65536, "actual_size_bytes": 70000},
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "payload_too_large"
    assert env["error"]["details"]["size_limit_bytes"] == 65536
    assert env["error"]["details"]["actual_size_bytes"] == 70000


def test_failure_envelope_drives_several_codes() -> None:
    """Every closed-set code that is constructible with its registered
    details produces a structurally-valid envelope."""
    for code in sorted(app_errors.ERROR_CODES):
        required = app_errors.DETAILS_REQUIRED_KEYS.get(code)
        details = {k: "v" for k in required} if required else {}
        env = app_envelope.failure(code, f"message for {code}", details)
        assert env["ok"] is False
        assert env["app_contract_version"] == APP_CONTRACT_VERSION
        assert env["error"]["code"] == code
        assert isinstance(env["error"]["details"], dict)


def test_failure_raises_on_unknown_code() -> None:
    """A handler passing an unknown code surfaces ContractViolation."""
    with pytest.raises(ContractViolation):
        app_envelope.failure("totally_made_up", "nope")


def test_failure_raises_on_missing_required_detail_key() -> None:
    """A handler omitting a required ``details`` key is a ContractViolation."""
    with pytest.raises(ContractViolation):
        app_envelope.failure(
            app_errors.VALIDATION_FAILED, "missing reason", {"field": "limit"}
        )


def test_internal_error_envelope_is_well_formed() -> None:
    """``envelope.internal_error`` is the safety-net failure shape."""
    env = app_envelope.internal_error("boom")
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.INTERNAL_ERROR
    assert env["error"]["details"] == {}
