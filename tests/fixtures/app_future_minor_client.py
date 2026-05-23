"""FEAT-011 T078 — synthetic future-minor app client helper.

A small importable helper that simulates a client running one minor
version *ahead* of the daemon (``client_app_contract_major = 1``, but a
notional ``1.x`` where ``x`` is higher than the daemon's). It exists to
exercise the SC-009 forward-compatibility flow: a newer client speaks
the same *major*, so the daemon must serve it normally, and the client
in turn must tolerate response envelopes that lack fields it expects.

This module is plain importable code — no pytest collection is required
to use it. A trivial self-test (``test_*``) is included so the file is
not dead weight when the suite runs, but the helpers are designed to be
imported by ``test_story5_version_drift.py`` and any future SC-009 flow.

Design notes:

* The client declares ``client_app_contract_major = 1`` — it shares the
  daemon's major, so ``app.hello`` succeeds (FR-036 only rejects a major
  *mismatch*).
* ``parse_response`` reads only the keys a v1.0-era client knows about,
  via ``.get(...)`` — unknown extra fields on the wire are ignored, not
  fatal (FR-037).
* ``build_*_request`` produce plain NDJSON-ready request dicts matching
  the FEAT-002 ``{"method", "params"}`` wire shape.
"""

from __future__ import annotations

from typing import Any


# The future-minor client still speaks contract MAJOR 1 — only its minor
# is ahead. FR-035/FR-036: a matching major is compatible.
FUTURE_MINOR_CLIENT_MAJOR: int = 1

# A label the future client reports as its notional minor; purely
# cosmetic — the daemon negotiates on major only.
FUTURE_MINOR_CLIENT_VERSION: str = "1.1.0-future"

# The known FR-010 ``app.hello`` result keys a v1.0-era client reads.
# Anything outside this set on the wire is an additive future field and
# is deliberately ignored by ``parse_response``.
KNOWN_HELLO_RESULT_KEYS: frozenset[str] = frozenset({
    "app_session_token",
    "app_session_id",
    "daemon_version",
    "schema_version",
    "app_contract_version",
    "supported_minor_range",
    "host_user_id",
    "capability_flags",
    "state",
})


class FutureMinorAppClient:
    """Simulates a client one minor ahead of the daemon.

    Stateless aside from an optional captured session token; safe to
    instantiate per test.
    """

    def __init__(
        self,
        *,
        client_id: str = "future-minor-client",
        client_version: str = FUTURE_MINOR_CLIENT_VERSION,
    ) -> None:
        self.client_id = client_id
        self.client_version = client_version
        self.app_session_token: str | None = None

    # ── request builders (NDJSON-ready {"method", "params"} dicts) ──────

    def build_hello_request(self) -> dict[str, Any]:
        """A standard ``app.hello`` request declaring major 1.

        Because the future client shares the daemon's major, this request
        succeeds — the daemon serves the older contract it implements.
        """
        return {
            "method": "app.hello",
            "params": {
                "client_id": self.client_id,
                "client_version": self.client_version,
                "client_app_contract_major": FUTURE_MINOR_CLIENT_MAJOR,
            },
        }

    def build_app_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build an arbitrary session-gated ``app.*`` request.

        If a session token has been captured (see ``remember_token``) it
        is injected into ``params`` unless the caller already supplied
        one.
        """
        merged: dict[str, Any] = dict(params or {})
        if self.app_session_token is not None and "app_session_token" not in merged:
            merged["app_session_token"] = self.app_session_token
        return {"method": method, "params": merged}

    # ── response handling (forward-compatible: ignores unknown fields) ──

    def remember_token(self, hello_result: dict[str, Any]) -> str | None:
        """Capture the session token from a parsed ``app.hello`` result."""
        self.app_session_token = hello_result.get("app_session_token")
        return self.app_session_token

    def parse_response(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """Parse a response envelope reading ONLY known keys.

        Tolerates unknown extra top-level fields and unknown extra
        ``result`` fields — they are simply not read (FR-037). Returns a
        normalized dict with the keys a v1.0-era client cares about:

            {"ok", "app_contract_version", "result"/"error"}

        Never raises on additive future fields.
        """
        ok = bool(envelope.get("ok", False))
        parsed: dict[str, Any] = {
            "ok": ok,
            "app_contract_version": envelope.get("app_contract_version"),
        }
        if ok:
            parsed["result"] = dict(envelope.get("result", {}))
        else:
            error = envelope.get("error", {})
            parsed["error"] = {
                "code": error.get("code"),
                "message": error.get("message", ""),
                "details": dict(error.get("details", {})),
            }
        return parsed

    def read_known_hello_fields(
        self, envelope: dict[str, Any]
    ) -> dict[str, Any]:
        """Project an ``app.hello`` success envelope onto the known v1.0
        FR-010 field set, dropping any additive future fields.

        Usable by an SC-009 forward-compat flow that wants to assert a
        future client still gets exactly the fields it understands — and
        that unknown fields are harmlessly discarded.
        """
        result = self.parse_response(envelope).get("result", {})
        return {k: v for k, v in result.items() if k in KNOWN_HELLO_RESULT_KEYS}


def parse_response(envelope: dict[str, Any]) -> dict[str, Any]:
    """Module-level convenience wrapper around ``FutureMinorAppClient.parse_response``.

    Lets callers do forward-compatible envelope parsing without holding
    a client instance.
    """
    return FutureMinorAppClient().parse_response(envelope)


# ─── Trivial self-test (collected harmlessly if the suite runs this) ─────


def test_future_minor_client_self_check() -> None:
    """Smoke: the helper builds a major-1 hello request and tolerates an
    unknown extra response field."""
    client = FutureMinorAppClient()
    req = client.build_hello_request()
    assert req["method"] == "app.hello"
    assert req["params"]["client_app_contract_major"] == 1

    # A synthetic future-daemon success envelope with an unknown extra
    # top-level field AND an unknown extra result field.
    envelope = {
        "ok": True,
        "app_contract_version": "1.0",
        "result": {
            "app_session_token": "tok-123",
            "future_result_field": "additive",
        },
        "future_top_level_field": {"introduced_in": "1.2"},
    }
    parsed = client.parse_response(envelope)
    assert parsed["ok"] is True
    assert parsed["result"]["app_session_token"] == "tok-123"

    client.remember_token(parsed["result"])
    assert client.app_session_token == "tok-123"

    gated = client.build_app_request("app.dashboard")
    assert gated["params"]["app_session_token"] == "tok-123"

    # Unknown fields are dropped by the known-field projection.
    known = client.read_known_hello_fields(envelope)
    assert "future_result_field" not in known
    assert known["app_session_token"] == "tok-123"
