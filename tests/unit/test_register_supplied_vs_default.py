"""Unit tests for FEAT-006 supplied-vs-default wire contract (T027 / Q1).

Covers Clarifications session 2026-05-07 Q1:
* Argparse defaults are NOT transmitted on idempotent re-registration.
* Explicit ``--role unknown`` overwrites a stored value.
* Omitted ``--role`` leaves a stored value unchanged.
* On first registration, daemon applies defaults symmetrically.
"""

from __future__ import annotations

from pathlib import Path

from ._agent_test_helpers import (
    make_service,
    register_params,
    seed_container,
    seed_pane,
)


def test_first_registration_applies_defaults(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)

    # No mutable flags supplied at all — daemon applies argparse-style
    # defaults (role=unknown, capability=unknown, label="", project="").
    result = service.register_agent(
        register_params(),
        socket_peer_uid=1000,
    )
    assert result["role"] == "unknown"
    assert result["capability"] == "unknown"
    assert result["label"] == ""
    assert result["project_path"] == ""


def test_explicit_unknown_overwrites_stored_role(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)

    service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    # Explicit --role unknown is still present in params and DOES overwrite.
    result = service.register_agent(
        register_params(role="unknown"), socket_peer_uid=1000
    )
    assert result["role"] == "unknown"


def test_omitted_role_does_not_overwrite_stored(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)

    service.register_agent(
        register_params(role="slave"), socket_peer_uid=1000
    )
    # Re-register without --role — stored value preserved.
    result = service.register_agent(
        register_params(), socket_peer_uid=1000
    )
    assert result["role"] == "slave"
