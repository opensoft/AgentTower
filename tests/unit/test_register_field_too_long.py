"""Unit tests for FEAT-006 free-text bounds at register time (T033 / FR-033).

Covers oversized ``label`` and ``project_path`` rejected with
``field_too_long``; values are NEVER silently truncated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.agents.errors import RegistrationError
from agenttower.agents.validation import LABEL_MAX, PROJECT_PATH_MAX

from ._agent_test_helpers import (
    make_service,
    register_params,
    seed_container,
    seed_pane,
)


def test_oversized_label_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(label="x" * (LABEL_MAX + 1)),
            socket_peer_uid=1000,
        )
    assert info.value.code == "field_too_long"


def test_oversized_project_path_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    seed_container(service)
    seed_pane(service)
    with pytest.raises(RegistrationError) as info:
        service.register_agent(
            register_params(project_path="/" + "x" * PROJECT_PATH_MAX),
            socket_peer_uid=1000,
        )
    assert info.value.code == "field_too_long"
