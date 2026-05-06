"""Unit tests for the additive ``DaemonUnavailable.kind`` attribute (T008, R-009, FR-026)."""

from __future__ import annotations

import errno

import pytest

from agenttower.socket_api.client import DaemonUnavailable


# ---------------------------------------------------------------------------
# Closed-set kind values (FR-016)
# ---------------------------------------------------------------------------


class TestKindClosedSet:
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
    def test_each_closed_kind_accepted(self, kind):
        exc = DaemonUnavailable("hello", kind=kind)
        assert exc.kind == kind


class TestKindDefault:
    def test_kind_defaults_to_connect_timeout(self):
        exc = DaemonUnavailable("hello")
        assert exc.kind == "connect_timeout"


# ---------------------------------------------------------------------------
# FR-026 byte-parity: str(exc) and repr(exc) unchanged from FEAT-002
# ---------------------------------------------------------------------------


class TestByteParity:
    def test_str_unchanged_with_message_only(self):
        exc = DaemonUnavailable("socket missing: /tmp/x")
        assert str(exc) == "socket missing: /tmp/x"

    def test_str_unchanged_with_kind_kwarg(self):
        exc = DaemonUnavailable("socket missing: /tmp/x", kind="socket_missing")
        assert str(exc) == "socket missing: /tmp/x"

    def test_repr_unchanged_with_kind_kwarg(self):
        # repr of RuntimeError-derived: ClassName('msg')
        exc = DaemonUnavailable("socket missing: /tmp/x", kind="socket_missing")
        assert repr(exc) == "DaemonUnavailable('socket missing: /tmp/x')"

    def test_args_tuple_unchanged(self):
        exc = DaemonUnavailable("hello", kind="connection_refused")
        assert exc.args == ("hello",)


# ---------------------------------------------------------------------------
# FR-026 backward compat: existing callers passing single positional arg work
# ---------------------------------------------------------------------------


class TestBackwardCompatCallers:
    def test_single_positional_arg_works(self):
        # The FEAT-002 / FEAT-003 / FEAT-004 callers do this:
        exc = DaemonUnavailable("legacy message")
        assert isinstance(exc, RuntimeError)
        assert str(exc) == "legacy message"
        assert exc.kind == "connect_timeout"  # default
