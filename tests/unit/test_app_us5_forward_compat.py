"""FEAT-011 T074 — Story 5 forward-compatibility unit tests.

Covers FR-037: an envelope produced by a future-minor daemon may carry
unknown extra top-level fields (and unknown extra ``result`` fields).
A v1.0 consumer that reads only the keys it knows about MUST be
unaffected — unknown additive fields are ignorable, never fatal.

This is the additive-evolution guarantee that lets a v1.x daemon ship a
1.1 with new fields without breaking 1.0 clients.

Pure in-process tests — envelopes built via ``envelope.success(...)``.
"""

from __future__ import annotations

from agenttower.app_contract import APP_CONTRACT_VERSION
from agenttower.app_contract import envelope


# ─── v1.0 consumer: reads only known keys ────────────────────────────────


def _v1_0_consume_envelope(env: dict) -> tuple[bool, str, dict]:
    """A v1.0 client decoder: reads ONLY the FR-033 known keys.

    Returns ``(ok, app_contract_version, result)``. Any extra top-level
    field is never touched, so additive future fields are inert.
    """
    return (
        env["ok"],
        env["app_contract_version"],
        env.get("result", {}),
    )


def test_extra_top_level_field_is_ignored_by_v1_0_consumer() -> None:
    """FR-037: an unknown extra top-level field does not break a v1.0
    consumer that reads only {ok, app_contract_version, result}."""
    env = envelope.success({"value": 1})
    # A future-minor daemon adds a new top-level field.
    env["future_top_level"] = {"introduced_in": "1.1"}

    ok, version, result = _v1_0_consume_envelope(env)
    assert ok is True
    assert version == APP_CONTRACT_VERSION
    assert result == {"value": 1}


def test_extra_result_field_is_ignored_by_v1_0_consumer() -> None:
    """FR-037: an unknown extra field inside ``result`` is ignorable —
    a v1.0 consumer reads only the result keys it knows."""
    env = envelope.success({"known_field": "v1-value"})
    # A future-minor daemon adds a new result field.
    env["result"]["future_result_field"] = ["1.2", "additive"]

    ok, _version, result = _v1_0_consume_envelope(env)
    assert ok is True
    # The v1.0 consumer reads only its known key — unaffected.
    assert result["known_field"] == "v1-value"
    # The extra field is present in the wire payload but simply unread.
    assert "future_result_field" in result


def test_envelope_stays_well_formed_with_extra_fields() -> None:
    """FR-037: adding extra fields keeps the FR-033 required structure
    intact — ``ok``, ``app_contract_version`` and ``result`` all present."""
    env = envelope.success({"a": 1})
    env["extra_one"] = "ignored"
    env["extra_two"] = {"nested": True}

    # FR-033 required structure is still satisfied.
    assert env["ok"] is True
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    assert isinstance(env["result"], dict)
    assert env["result"]["a"] == 1


def test_multiple_extra_fields_do_not_collide_with_known_keys() -> None:
    """FR-037: a future minor may add several top-level fields at once;
    the v1.0 known-key set is read unchanged."""
    env = envelope.success({"core": "data"})
    for i in range(5):
        env[f"future_field_{i}"] = i

    ok, version, result = _v1_0_consume_envelope(env)
    assert ok is True
    assert version == APP_CONTRACT_VERSION
    assert result == {"core": "data"}


def test_v1_0_consumer_tolerates_empty_result_with_extras() -> None:
    """FR-037: a handshake-style success (empty result) plus an extra
    top-level field is still consumed cleanly."""
    env = envelope.success()  # result defaults to {}
    env["future_negotiation_field"] = {"min": "1.0", "max": "1.3"}

    ok, version, result = _v1_0_consume_envelope(env)
    assert ok is True
    assert version == APP_CONTRACT_VERSION
    assert result == {}
