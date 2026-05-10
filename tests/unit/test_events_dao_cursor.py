"""T015 — cursor codec round-trip tests.

The cursor is opaque at the CLI boundary; internally it is
``base64url(json({"e": <event_id>, "r": <reverse>}))``. Tests assert
positive round-trip stability and a documented ``CursorError`` for
every malformed-input class.
"""

from __future__ import annotations

import base64
import json

import pytest

from agenttower.events.dao import CursorError, decode_cursor, encode_cursor


def test_cursor_roundtrip_forward() -> None:
    token = encode_cursor(42, reverse=False)
    e, r = decode_cursor(token)
    assert e == 42
    assert r is False


def test_cursor_roundtrip_reverse() -> None:
    token = encode_cursor(99, reverse=True)
    e, r = decode_cursor(token)
    assert e == 99
    assert r is True


def test_cursor_high_event_id() -> None:
    token = encode_cursor(2**40, reverse=False)
    e, r = decode_cursor(token)
    assert e == 2**40
    assert r is False


def test_cursor_padding_is_stripped() -> None:
    """Encoded cursor MUST NOT carry trailing ``=`` padding."""
    token = encode_cursor(42, reverse=False)
    assert "=" not in token


def test_cursor_decode_handles_missing_padding_on_input() -> None:
    """The decoder restores padding internally; encoded form omits it."""
    token = encode_cursor(7, reverse=True)
    # Add then strip padding to confirm both forms decode.
    decode_cursor(token)
    decode_cursor(token + "==")  # extra padding still works


# --- Negative / error cases -----------------------------------------------


def test_encode_rejects_non_int_event_id() -> None:
    with pytest.raises(CursorError):
        encode_cursor(3.14, reverse=False)  # type: ignore[arg-type]


def test_encode_rejects_zero_event_id() -> None:
    with pytest.raises(CursorError):
        encode_cursor(0, reverse=False)


def test_encode_rejects_negative_event_id() -> None:
    with pytest.raises(CursorError):
        encode_cursor(-1, reverse=False)


def test_decode_rejects_empty_token() -> None:
    with pytest.raises(CursorError):
        decode_cursor("")


def test_decode_rejects_non_base64() -> None:
    with pytest.raises(CursorError):
        decode_cursor("!!!!not_b64!!!")


def test_decode_rejects_non_json_payload() -> None:
    bad = base64.urlsafe_b64encode(b"not json at all").rstrip(b"=").decode("ascii")
    with pytest.raises(CursorError):
        decode_cursor(bad)


def test_decode_rejects_array_payload() -> None:
    bad = base64.urlsafe_b64encode(b"[1, 2]").rstrip(b"=").decode("ascii")
    with pytest.raises(CursorError):
        decode_cursor(bad)


def test_decode_rejects_missing_e_key() -> None:
    bad = base64.urlsafe_b64encode(json.dumps({"r": False}).encode()).rstrip(b"=").decode()
    with pytest.raises(CursorError):
        decode_cursor(bad)


def test_decode_rejects_missing_r_key() -> None:
    bad = base64.urlsafe_b64encode(json.dumps({"e": 42}).encode()).rstrip(b"=").decode()
    with pytest.raises(CursorError):
        decode_cursor(bad)


def test_decode_rejects_string_e_value() -> None:
    bad = base64.urlsafe_b64encode(
        json.dumps({"e": "42", "r": False}).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(CursorError):
        decode_cursor(bad)


def test_decode_rejects_zero_e_value() -> None:
    bad = base64.urlsafe_b64encode(
        json.dumps({"e": 0, "r": False}).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(CursorError):
        decode_cursor(bad)


def test_decode_rejects_int_r_value() -> None:
    bad = base64.urlsafe_b64encode(
        json.dumps({"e": 42, "r": 1}).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(CursorError):
        decode_cursor(bad)


def test_decode_is_forward_tolerant_of_extra_keys() -> None:
    """A future encoder may add an optional key; the current decoder
    ignores it as long as the documented two keys are valid."""
    forward = base64.urlsafe_b64encode(
        json.dumps({"e": 42, "r": False, "v": 2}).encode()
    ).rstrip(b"=").decode()
    e, r = decode_cursor(forward)
    assert e == 42
    assert r is False
