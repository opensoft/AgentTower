"""T075 — FEAT-007 must not regress any FEAT-001..006 surface.

SC parallel to FEAT-006 SC-010 / FEAT-005 SC-007: every existing CLI
command must still produce the same exit code and shape. The only
documented surface change is the addition of the FEAT-007 subcommands
themselves (``attach-log``, ``detach-log``) plus the additive
``--attach-log`` / ``--log`` flags on ``register-self``.

We assert:

1. ``--help`` for every FEAT-001..006 subcommand still parses and exits
   0; no FEAT-007 strings bleed into unrelated subcommands' help text.
2. The top-level ``--help`` lists the new FEAT-007 subcommands but
   continues to list every prior subcommand (additive only).
3. Daemon-down exit codes for FEAT-001..006 commands are unchanged.
4. The socket dispatch table is purely additive: every FEAT-001..006
   method is still present and the new methods are appended after them.
5. ``CLOSED_CODE_SET`` only grows — every FEAT-001..006 error code
   remains available; FEAT-007 only adds to it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ._daemon_helpers import (
    isolated_env,
    run_config_init,
    stop_daemon_if_alive,
)


PRE_FEAT007_SUBCOMMANDS = (
    "ensure-daemon",
    "status",
    "stop-daemon",
    "scan",
    "list-containers",
    "list-panes",
    "register-self",
    "list-agents",
    "set-role",
    "set-label",
    "set-capability",
)

FEAT007_NEW_SUBCOMMANDS = (
    "attach-log",
    "detach-log",
)

PRE_FEAT007_ERROR_CODES = (
    # FEAT-001..006 closed-set codes that pre-date FEAT-007. Kept here so
    # any future removal triggers this test (the set is supposed to grow,
    # never shrink).
    "agent_not_found",
    "agent_inactive",
    "pane_unknown_to_daemon",
    "bad_request",
    "value_out_of_set",
    "internal_error",
    "schema_version_newer",
)

PRE_FEAT007_DISPATCH_METHODS = (
    # Methods registered by FEAT-001..006. New FEAT-007 methods MUST be
    # appended after this set (verified by checking insertion order).
    "ping",
    "scan_containers",
    "list_containers",
    "scan_panes",
    "list_panes",
    "register_agent",
    "list_agents",
    "set_role",
    "set_label",
    "set_capability",
)


@pytest.fixture
def env(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    env = isolated_env(home)
    yield env
    stop_daemon_if_alive(env)


def _run(env, *args, timeout=10):
    return subprocess.run(
        ["agenttower", *args], env=env, capture_output=True, text=True, timeout=timeout
    )


# ---------------------------------------------------------------------------
# 1. Per-subcommand --help byte-stability sweep
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("subcmd", PRE_FEAT007_SUBCOMMANDS)
def test_pre_feat007_subcommand_help_does_not_mention_attach_log(env, subcmd):
    """Existing subcommands' ``--help`` MUST NOT mention ``attach-log`` or
    ``detach-log`` — adding new subparsers should not bleed into unrelated
    subcommands' help output.

    ``register-self --help`` is the documented exception: it gains
    ``--attach-log`` / ``--log`` per FR-035 (additive).
    """
    proc = _run(env, subcmd, "--help")
    assert proc.returncode == 0, f"{subcmd} --help failed: {proc.stderr!r}"
    if subcmd == "register-self":
        assert "--attach-log" in proc.stdout, (
            "register-self --help MUST list the new --attach-log flag (FR-035)"
        )
        # The standalone subcommands MUST NOT appear inside register-self's help.
        assert "attach-log --target" not in proc.stdout
        assert "detach-log --target" not in proc.stdout
    else:
        assert "attach-log" not in proc.stdout.lower(), (
            f"{subcmd} --help mentions 'attach-log'; FEAT-007 subcommands "
            "must not bleed into unrelated subcommands' help text"
        )
        assert "detach-log" not in proc.stdout.lower()


# ---------------------------------------------------------------------------
# 2. Top-level --help lists all subcommands (additive only)
# ---------------------------------------------------------------------------


def test_top_level_help_lists_every_pre_feat007_subcommand(env):
    proc = _run(env, "--help")
    assert proc.returncode == 0
    for sub in PRE_FEAT007_SUBCOMMANDS:
        assert sub in proc.stdout, (
            f"top-level --help dropped pre-FEAT-007 subcommand {sub!r}"
        )


def test_top_level_help_lists_new_feat007_subcommands(env):
    proc = _run(env, "--help")
    assert proc.returncode == 0
    for sub in FEAT007_NEW_SUBCOMMANDS:
        assert sub in proc.stdout, (
            f"top-level --help missing FEAT-007 subcommand {sub!r}"
        )


# ---------------------------------------------------------------------------
# 3. Daemon-down exit codes unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subcmd",
    [
        "status",
        "list-containers",
        "list-panes",
        "list-agents",
    ],
)
def test_daemon_down_exit_code_unchanged_for_query_commands(env, subcmd):
    """FEAT-002 contract: query commands exit 2 when the daemon is down."""
    run_config_init(env)
    proc = _run(env, subcmd)
    assert proc.returncode == 2, (
        f"{subcmd} exit code changed; expected 2 (FEAT-002 daemon-unavailable), "
        f"got {proc.returncode!r}; stderr={proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# 4. Dispatch table is additive
# ---------------------------------------------------------------------------


def test_dispatch_table_is_additive():
    """FEAT-007 appends its 4 methods AFTER all pre-FEAT-007 methods.

    Reads the live dispatch table (no daemon needed) and asserts both
    presence + insertion order.
    """
    from agenttower.socket_api.methods import DISPATCH

    method_names = list(DISPATCH.keys())
    for name in PRE_FEAT007_DISPATCH_METHODS:
        assert name in method_names, (
            f"FEAT-001..006 dispatch method {name!r} disappeared"
        )
    for name in FEAT007_NEW_SUBCOMMANDS_AS_METHODS:
        assert name in method_names

    # Insertion order: every pre-FEAT-007 method appears before any
    # FEAT-007 method. We use the index of the LAST pre-FEAT-007 method
    # vs. the FIRST FEAT-007 method so we don't accidentally fail if
    # someone reorders within the FEAT-001..006 block (that's a different
    # contract).
    last_pre_idx = max(method_names.index(n) for n in PRE_FEAT007_DISPATCH_METHODS)
    first_feat007_idx = min(method_names.index(n) for n in FEAT007_NEW_SUBCOMMANDS_AS_METHODS)
    assert last_pre_idx < first_feat007_idx, (
        f"FEAT-007 methods inserted before a pre-FEAT-007 method "
        f"(last_pre={last_pre_idx}, first_feat007={first_feat007_idx})"
    )


FEAT007_NEW_SUBCOMMANDS_AS_METHODS = (
    "attach_log",
    "detach_log",
    "attach_log_status",
    "attach_log_preview",
)


# ---------------------------------------------------------------------------
# 5. CLOSED_CODE_SET only grows
# ---------------------------------------------------------------------------


def test_closed_code_set_preserves_pre_feat007_codes():
    from agenttower.socket_api import errors

    for code in PRE_FEAT007_ERROR_CODES:
        assert code in errors.CLOSED_CODE_SET, (
            f"FEAT-001..006 closed-set code {code!r} disappeared from "
            "CLOSED_CODE_SET — closed-set membership is supposed to be "
            "additive (FR-038)"
        )


def test_closed_code_set_grew_with_feat007_codes():
    """Sanity: the FEAT-007 codes were actually added (T001 contract)."""
    from agenttower.socket_api import errors

    for code in (
        "log_path_invalid",
        "log_path_not_host_visible",
        "log_path_in_use",
        "pipe_pane_failed",
        "tmux_unavailable",
        "attachment_not_found",
        "log_file_missing",
    ):
        assert code in errors.CLOSED_CODE_SET, (
            f"FEAT-007 closed-set code {code!r} missing — T001 was supposed "
            "to add it"
        )
