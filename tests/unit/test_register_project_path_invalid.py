"""Unit tests for FEAT-006 project_path shape validation (T034 / FR-034).

Covers ``project_path`` being non-empty, absolute, NUL-free, no ``..``
segment. Existence on the host filesystem is NOT checked.
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


@pytest.mark.parametrize(
    "bad_path",
    [
        "workspace/acme",   # relative
        "/a/../b",          # contains '..' segment
        "/a/\x00/b",        # NUL byte
        # empty is treated as "field omitted" via cli.py; the daemon
        # accepts empty as a sentinel meaning "no project path"; we
        # validate only when explicitly supplied non-empty. Asserted
        # in test_first_registration_applies_defaults.
    ],
)
def test_project_path_shape_rejected(tmp_path: Path, bad_path: str) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(project_path=bad_path),
            socket_peer_uid=1000,
        )
    assert info.value.code == "project_path_invalid"


def test_project_path_existence_not_checked(tmp_path: Path) -> None:
    """The path is observed inside the container's mount namespace; the
    host filesystem need NOT contain it (FR-034)."""
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    result = service.register_agent(
        register_params(project_path="/path/that/does/not/exist/on/host"),
        socket_peer_uid=1000,
    )
    assert result["project_path"] == "/path/that/does/not/exist/on/host"
