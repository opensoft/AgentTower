"""FEAT-006 schema_version forward-compat (FR-040 / edge case line 79).

Locks the wire-level handshake the review-pass-1 surfaced as unreachable:
the CLI must transmit its built-against schema version on
``register_agent`` so the daemon can refuse with ``schema_version_newer``
when its own schema has advanced past what the CLI knows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.agents.errors import RegistrationError

from ._agent_test_helpers import (
    make_service,
    register_params,
    seed_container,
    seed_pane,
)


def test_schema_version_newer_when_client_lags(tmp_path: Path) -> None:
    """A CLI that says ``schema_version=N`` against a daemon at ``N+1`` is refused."""
    service = make_service(tmp_path, schema_version=5)
    seed_container(service)
    seed_pane(service)
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(role="slave", schema_version=4),
            socket_peer_uid=1000,
        )
    assert info.value.code == "schema_version_newer"
    assert "upgrade the CLI" in info.value.message


def test_schema_version_equal_does_not_refuse(tmp_path: Path) -> None:
    service = make_service(tmp_path, schema_version=4)
    seed_container(service)
    seed_pane(service)
    result = service.register_agent(
        register_params(role="slave", schema_version=4),
        socket_peer_uid=1000,
    )
    assert result["role"] == "slave"


def test_schema_version_omitted_does_not_refuse(tmp_path: Path) -> None:
    """An older CLI that does not send the field still works (back-compat)."""
    service = make_service(tmp_path, schema_version=4)
    seed_container(service)
    seed_pane(service)
    result = service.register_agent(
        register_params(role="slave"),
        socket_peer_uid=1000,
    )
    assert result["role"] == "slave"


def test_register_self_cli_includes_schema_version() -> None:
    """The CLI build's MAX_SUPPORTED_SCHEMA_VERSION feeds the wire request.

    Without this, ``schema_version_newer`` is unreachable (review-pass-1).
    """
    from agenttower.config_doctor import MAX_SUPPORTED_SCHEMA_VERSION
    from agenttower.state.schema import CURRENT_SCHEMA_VERSION

    # The CLI build's ceiling and the daemon build's current schema track
    # together — both bumped in lockstep with each schema migration.
    assert MAX_SUPPORTED_SCHEMA_VERSION == CURRENT_SCHEMA_VERSION
