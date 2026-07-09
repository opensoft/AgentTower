"""FEAT-013 launch profile contract test (T017b).

Covers research §R9 argv-shape enforcement (``command`` MUST be a list
of strings; never a single shell string), FR-024 override-by-name
precedence, ``managed_launch_command_not_found`` rejection, and the
FR-024 amendment no-auto-create post-condition.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.managed_sessions.errors import (
    MANAGED_LAUNCH_COMMAND_NOT_FOUND,
    ManagedSessionsError,
)
from agenttower.managed_sessions.launch_profiles import (
    load_profiles,
    resolve_profile,
)


# ─── Empty registry on missing override dir (FR-024 no-auto-create) ─────


def test_load_profiles_empty_when_dir_missing(tmp_path: Path) -> None:
    nonexistent = tmp_path / "nonexistent"
    assert not nonexistent.exists()
    assert load_profiles(override_dir=nonexistent) == {}
    # FR-024 amendment: MUST NOT create the directory.
    assert not nonexistent.exists()


# ─── Valid profile (argv-shape) ──────────────────────────────────────────


def test_valid_argv_profile_loads(tmp_path: Path) -> None:
    (tmp_path / "claude-master.yaml").write_text(
        """\
name: claude-master
command: ["claude", "--model", "opus", "--system-prompt-file", "master.md"]
env:
  ANTHROPIC_LOG: warn
working_dir: /workspace
""",
        encoding="utf-8",
    )
    registry = load_profiles(override_dir=tmp_path)
    profile = registry["claude-master"]
    assert profile.command == (
        "claude",
        "--model",
        "opus",
        "--system-prompt-file",
        "master.md",
    )
    assert profile.env == {"ANTHROPIC_LOG": "warn"}
    assert profile.working_dir == "/workspace"


def test_profile_without_env_or_working_dir_loads(tmp_path: Path) -> None:
    (tmp_path / "minimal.yaml").write_text(
        """\
name: minimal
command: ["bash"]
""",
        encoding="utf-8",
    )
    registry = load_profiles(override_dir=tmp_path)
    minimal = registry["minimal"]
    assert minimal.command == ("bash",)
    assert minimal.env == {}
    assert minimal.working_dir is None


# ─── Argv-shape violations are silently rejected (R9) ────────────────────


def test_string_command_is_rejected(tmp_path: Path) -> None:
    """``command: "bash -lc echo hello"`` (a single string) violates R9."""
    (tmp_path / "shell-style.yaml").write_text(
        """\
name: shell-style
command: "bash -lc 'echo hello'"
""",
        encoding="utf-8",
    )
    registry = load_profiles(override_dir=tmp_path)
    assert "shell-style" not in registry


def test_command_with_non_string_argv_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad-types.yaml").write_text(
        """\
name: bad-types
command: ["bash", 42, "echo"]
""",
        encoding="utf-8",
    )
    registry = load_profiles(override_dir=tmp_path)
    assert "bad-types" not in registry


def test_empty_command_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "empty.yaml").write_text(
        """\
name: empty-command
command: []
""",
        encoding="utf-8",
    )
    registry = load_profiles(override_dir=tmp_path)
    assert "empty-command" not in registry


def test_missing_name_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "noname.yaml").write_text(
        """\
command: ["bash"]
""",
        encoding="utf-8",
    )
    registry = load_profiles(override_dir=tmp_path)
    assert registry == {}


def test_invalid_env_values_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad-env.yaml").write_text(
        """\
name: bad-env
command: ["bash"]
env:
  GOOD_VAR: ok
  COUNT: 42  # non-string value violates the schema
""",
        encoding="utf-8",
    )
    registry = load_profiles(override_dir=tmp_path)
    assert "bad-env" not in registry


# ─── FR-024 override-by-name precedence ───────────────────────────────────


def test_two_files_with_same_name_last_wins_alphabetically(tmp_path: Path) -> None:
    """Operator files are loaded sorted; later files override earlier ones.

    Tests the FR-024 "operator file with same `name` wins" precedence; the
    deterministic-by-filename ordering is an implementation detail of the
    sorted iteration.
    """
    (tmp_path / "a-first.yaml").write_text(
        """\
name: shared-name
command: ["first"]
""",
        encoding="utf-8",
    )
    (tmp_path / "b-second.yaml").write_text(
        """\
name: shared-name
command: ["second"]
""",
        encoding="utf-8",
    )
    registry = load_profiles(override_dir=tmp_path)
    assert registry["shared-name"].command == ("second",)


# ─── Resolver + error code ────────────────────────────────────────────────


def test_resolve_profile_unknown_raises_closed_set_error(tmp_path: Path) -> None:
    with pytest.raises(ManagedSessionsError) as exc:
        resolve_profile("does-not-exist", override_dir=tmp_path)
    assert exc.value.code == MANAGED_LAUNCH_COMMAND_NOT_FOUND
    assert exc.value.details["profile_name"] == "does-not-exist"


def test_resolve_profile_returns_loaded(tmp_path: Path) -> None:
    (tmp_path / "p.yaml").write_text(
        """\
name: p
command: ["bash"]
""",
        encoding="utf-8",
    )
    p = resolve_profile("p", override_dir=tmp_path)
    assert p.command == ("bash",)
