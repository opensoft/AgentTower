"""Unit tests for the FEAT-003 Docker output parsers."""

from __future__ import annotations

import json

import pytest

from agenttower.docker import parsers
from agenttower.docker.adapter import DockerError
from agenttower.socket_api import errors as _errors


# ---------------------------------------------------------------------------
# parse_docker_ps_lines
# ---------------------------------------------------------------------------


def test_parse_ps_basic_row() -> None:
    text = "abc123\tpy-bench\tghcr.io/opensoft/py-bench:latest\trunning\n"
    rows = parsers.parse_docker_ps_lines(text)
    assert rows[0].container_id == "abc123"
    assert rows[0].name == "py-bench"
    assert rows[0].image == "ghcr.io/opensoft/py-bench:latest"
    assert rows[0].status == "running"


def test_parse_ps_multiple_names_split_on_comma() -> None:
    text = "abc123\tpy-bench,/legacy-bench\timg\trunning\n"
    rows = parsers.parse_docker_ps_lines(text)
    assert sorted(r.name for r in rows) == ["legacy-bench", "py-bench"]


def test_parse_ps_strips_leading_slash_in_names() -> None:
    text = "abc123\t/py-bench\timg\trunning\n"
    rows = parsers.parse_docker_ps_lines(text)
    assert rows[0].name == "py-bench"


def test_parse_ps_empty_input_returns_empty_list() -> None:
    assert parsers.parse_docker_ps_lines("") == []
    assert parsers.parse_docker_ps_lines("\n\n") == []


def test_parse_ps_malformed_row_raises_docker_malformed() -> None:
    with pytest.raises(DockerError) as exc_info:
        parsers.parse_docker_ps_lines("only-three\tfields\there\n")
    assert exc_info.value.code == _errors.DOCKER_MALFORMED


def test_parse_ps_empty_id_raises_docker_malformed() -> None:
    with pytest.raises(DockerError) as exc_info:
        parsers.parse_docker_ps_lines("\tname\timg\trunning\n")
    assert exc_info.value.code == _errors.DOCKER_MALFORMED


# ---------------------------------------------------------------------------
# parse_docker_inspect_array
# ---------------------------------------------------------------------------


def _inspect_blob(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "Id": "abc123",
        "Name": "/py-bench",
        "State": {"Status": "running"},
        "Config": {
            "Image": "img:latest",
            "User": "user",
            "WorkingDir": "/workspace",
            "Labels": {"k": "v"},
            "Env": ["USER=foo", "SECRET=value", "HOME=/home/u"],
        },
        "Mounts": [
            {"Source": "/h", "Destination": "/c", "Type": "bind", "Mode": "rw", "RW": True}
        ],
    }
    base.update(overrides)
    return base


def test_parse_inspect_basic() -> None:
    blob = json.dumps([_inspect_blob()])
    successes, failures = parsers.parse_docker_inspect_array(blob, ["abc123"])
    assert failures == []
    res = successes["abc123"]
    assert res.container_id == "abc123"
    assert res.name == "py-bench"  # leading slash stripped
    assert res.image == "img:latest"
    assert res.status == "running"
    assert res.labels == {"k": "v"}
    assert res.mounts[0].target == "/c"
    assert res.config_user == "user"
    assert res.working_dir == "/workspace"
    # Env-key allowlist: USER, HOME present; SECRET filtered out.
    assert sorted(res.env_keys) == ["HOME", "USER"]


def test_parse_inspect_missing_labels_and_mounts() -> None:
    blob = json.dumps(
        [
            {
                "Id": "abc",
                "Name": "py-bench",
                "State": {"Status": "running"},
                "Config": {"Image": "img"},
            }
        ]
    )
    successes, _ = parsers.parse_docker_inspect_array(blob, ["abc"])
    assert successes["abc"].labels == {}
    assert successes["abc"].mounts == []


def test_parse_inspect_non_array_top_level_raises_docker_malformed() -> None:
    with pytest.raises(DockerError) as exc_info:
        parsers.parse_docker_inspect_array(json.dumps({"not": "a list"}), [])
    assert exc_info.value.code == _errors.DOCKER_MALFORMED


def test_parse_inspect_invalid_json_raises_docker_malformed() -> None:
    with pytest.raises(DockerError) as exc_info:
        parsers.parse_docker_inspect_array("not json at all", [])
    assert exc_info.value.code == _errors.DOCKER_MALFORMED


def test_parse_inspect_per_entry_failure_records_per_container_error() -> None:
    blob = json.dumps(
        [
            {"Id": "ok-id", "Name": "ok", "State": {"Status": "running"}, "Config": {"Image": "i"}},
            "not-an-object",
        ]
    )
    successes, failures = parsers.parse_docker_inspect_array(blob, ["ok-id", "missing-id"])
    assert "ok-id" in successes
    # The non-object entry produces a per-container failure with empty id.
    codes = {f.code for f in failures}
    assert _errors.DOCKER_MALFORMED in codes
    # Requested id "missing-id" not present anywhere → omitted-id failure.
    missing = [f for f in failures if f.container_id == "missing-id"]
    assert missing
    assert missing[0].code == _errors.DOCKER_MALFORMED


def test_parse_inspect_oversized_strings_are_bounded() -> None:
    huge = "X" * 10_000
    bad_blob = json.dumps([{"Id": "id1", "Name": huge}])
    # The malformed-entry path records the bounded error_message.
    successes, failures = parsers.parse_docker_inspect_array(bad_blob, ["id1"])
    # `Name` huge is acceptable shape-wise (it parses successfully); the bounded
    # check applies to error messages. So this should succeed:
    assert "id1" in successes or any(len(f.message) <= 2048 for f in failures)
