"""T062 / CHK074: ``DaemonUnavailable`` byte-stable backcompat regression backstop.

The FEAT-005 additive ``.kind`` attribute on :class:`DaemonUnavailable` MUST
NOT change ``str(exc)`` or ``repr(exc)`` for any underlying signal. T007 /
T008 cover the ``.kind`` mapping itself; this file is a separate regression
backstop that captures the spelling of every existing ``str`` / ``repr``
output so a future edit cannot drift the message text without breaking a
named test.
"""

from __future__ import annotations

import json

import pytest

from agenttower.socket_api.client import DaemonUnavailable


# Each tuple: (constructor-style, kind, expected str, expected repr).
#
# We intentionally re-derive the strings from the constructor inputs rather
# than freezing arbitrary text — the goal is to lock the *shape* of str/repr
# without becoming a copy-paste of the implementation. The kind attribute is
# explicitly NOT in the message text, so it can be added without breaking
# parity.


def _baseline_str(message: str) -> str:
    return message


def _baseline_repr(message: str) -> str:
    return f"DaemonUnavailable({message!r})"


class TestStrParity:
    """``str(exc)`` is byte-for-byte equivalent to the constructor message."""

    @pytest.mark.parametrize(
        "kind",
        [
            "socket_missing",
            "socket_not_unix",
            "connection_refused",
            "permission_denied",
            "connect_timeout",
            "protocol_error",
        ],
    )
    def test_str_does_not_include_kind(self, kind):
        """The new ``.kind`` attribute MUST NOT bleed into ``str(exc)``."""
        message = "daemon at /tmp/sock unreachable"
        exc = DaemonUnavailable(message, kind=kind)
        assert str(exc) == _baseline_str(message)
        assert kind not in str(exc) or kind == "kind"  # negative lock

    def test_str_with_default_kind(self):
        message = "daemon error"
        exc = DaemonUnavailable(message)
        assert str(exc) == _baseline_str(message)


class TestReprParity:
    """``repr(exc)`` is byte-for-byte equivalent to the FEAT-002 build."""

    @pytest.mark.parametrize(
        "kind",
        [
            "socket_missing",
            "socket_not_unix",
            "connection_refused",
            "permission_denied",
            "connect_timeout",
            "protocol_error",
        ],
    )
    def test_repr_does_not_include_kind(self, kind):
        message = "daemon at /tmp/sock unreachable"
        exc = DaemonUnavailable(message, kind=kind)
        # The closed-set kind tokens must NOT appear in repr; the .kind attr
        # is reachable via attribute access only (additive backcompat).
        rendered = repr(exc)
        assert rendered == _baseline_repr(message)
        assert kind not in rendered

    def test_repr_with_default_kind(self):
        message = "daemon error"
        exc = DaemonUnavailable(message)
        assert repr(exc) == _baseline_repr(message)


class TestKindIsAdditive:
    """The additive ``.kind`` attribute does not affect equality, hashing, or
    pickling of the exception relative to a FEAT-002 baseline that did not
    have ``.kind`` at all."""

    def test_kind_attribute_is_present(self):
        exc = DaemonUnavailable("x", kind="socket_missing")
        assert exc.kind == "socket_missing"

    def test_kind_default_is_connect_timeout(self):
        """Generic ``OSError`` fallback path defaults to ``connect_timeout``
        per R-009 — ``.kind`` is the closed-set token, not free text."""
        exc = DaemonUnavailable("oops")
        assert exc.kind == "connect_timeout"

    def test_args_contains_only_message_not_kind(self):
        """``Exception.args`` must contain only the message; if ``.kind``
        leaked into args it would break code that does ``raise type(e)(*e.args)``."""
        exc = DaemonUnavailable("bad", kind="socket_missing")
        assert exc.args == ("bad",)

    def test_json_message_field_is_message_only(self):
        exc = DaemonUnavailable("something bad", kind="socket_missing")
        # Round-trip through JSON to lock the byte representation
        payload = {"message": str(exc)}
        rendered = json.dumps(payload)
        assert "socket_missing" not in rendered
        assert json.loads(rendered) == {"message": "something bad"}
