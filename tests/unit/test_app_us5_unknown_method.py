"""FEAT-011 T075 — Story 5 unknown-method semantics unit tests.

Covers SC-027 / FR-034b: any ``app.*`` method name not present in the
dispatch table maps to the ``unknown_method`` failure envelope. The
envelope is FR-033-shaped (``app_contract_version`` stamped,
``error.details == {}``) and the cause — typo, future-minor method, or
nonexistent method — is deliberately *not* distinguished: details are
always ``{}``.

An unknown ``app.*`` method causes no state mutation: ``make_unknown_method_envelope``
is a pure builder and the dispatch table is a closed dict that simply
lacks the key.

Pure in-process tests — dispatcher helpers called directly (SC-001).
"""

from __future__ import annotations

import pytest

from agenttower.app_contract import APP_CONTRACT_VERSION
from agenttower.app_contract import dispatcher as dispatcher_mod
from agenttower.app_contract import errors as app_errors


# ─── FR-034b: unknown app.* method → unknown_method, details == {} ───────


@pytest.mark.parametrize(
    "method",
    [
        "app.foo.bar",          # typo / nonexistent
        "app.x.y",              # nonexistent
        "app.future_method",    # plausible future-minor method
    ],
)
def test_unknown_app_method_maps_to_unknown_method(method: str) -> None:
    """SC-027 / FR-034b: every unknown app.* name → unknown_method with
    a stamped contract version and empty details, regardless of cause."""
    env = dispatcher_mod.make_unknown_method_envelope(method)
    assert env["ok"] is False
    assert env["error"]["code"] == app_errors.UNKNOWN_METHOD
    # FR-033: contract version is stamped on the failure envelope.
    assert env["app_contract_version"] == APP_CONTRACT_VERSION
    # FR-034b: details are always {} — cause is not distinguished.
    assert env["error"]["details"] == {}
    # The method name is echoed into the operator-facing message.
    assert method in env["error"]["message"]


def test_unknown_method_details_are_always_empty_regardless_of_cause() -> None:
    """FR-034b: a typo and a future-minor method get IDENTICAL details
    ({})  — the contract does not leak the failure cause."""
    typo = dispatcher_mod.make_unknown_method_envelope("app.dahsboard")
    future = dispatcher_mod.make_unknown_method_envelope("app.events.subscribe")
    assert typo["error"]["details"] == {}
    assert future["error"]["details"] == {}
    assert typo["error"]["details"] == future["error"]["details"]


def test_unknown_app_method_is_classified_by_is_app_method() -> None:
    """FR-034b: the dispatcher recognises an unknown name as app.* so it
    routes to the FEAT-011 envelope rewriter, not the legacy shape."""
    assert dispatcher_mod.is_app_method("app.foo.bar") is True
    assert dispatcher_mod.is_app_method("app.future_method") is True
    # Non-app names are NOT rewritten to the FEAT-011 shape.
    assert dispatcher_mod.is_app_method("frobnicate") is False
    assert dispatcher_mod.is_app_method("ping") is False


def test_unknown_app_method_absent_from_dispatch_table() -> None:
    """SC-027: an unknown app.* key is simply not present in the closed
    APP_DISPATCH table — there is no runtime registration surface."""
    for method in ("app.foo.bar", "app.x.y", "app.future_method"):
        assert method not in dispatcher_mod.APP_DISPATCH
    # A known app.* method IS present (sanity anchor).
    assert "app.hello" in dispatcher_mod.APP_DISPATCH


def test_make_unknown_method_envelope_does_not_mutate_dispatch_table() -> None:
    """FR-034b: building an unknown-method envelope is a pure operation —
    it never inserts the missing method into the dispatch table."""
    before = set(dispatcher_mod.APP_DISPATCH.keys())
    dispatcher_mod.make_unknown_method_envelope("app.brand_new_method")
    after = set(dispatcher_mod.APP_DISPATCH.keys())
    assert before == after
    # And the method is still absent afterwards.
    assert "app.brand_new_method" not in dispatcher_mod.APP_DISPATCH


def test_unknown_method_envelope_is_a_fresh_object_each_call() -> None:
    """Builder produces an independent envelope per call — no shared
    mutable state leaks between unknown-method responses."""
    e1 = dispatcher_mod.make_unknown_method_envelope("app.one")
    e2 = dispatcher_mod.make_unknown_method_envelope("app.two")
    assert e1 is not e2
    assert e1["error"]["details"] is not e2["error"]["details"]
    e1["error"]["details"]["leak"] = True
    assert e2["error"]["details"] == {}
