"""Unit tests for FEAT-007 pipe-pane shell construction (T022 / FR-010 / FR-047)."""

from __future__ import annotations

import shlex

from agenttower.logs.pipe_pane import (
    build_attach_argv,
    build_inspection_argv,
    build_toggle_off_argv,
    render_pipe_command_for_audit,
    sanitize_pipe_pane_stderr,
)
from agenttower.logs.pipe_pane_state import (
    classify_pipe_target,
    parse_list_panes_output,
    sanitize_prior_pipe_target,
)


CONTAINER_USER = "brett"
CONTAINER_ID = "c" * 64
PANE = "main:0.0"
LOG = "/home/brett/.local/state/opensoft/agenttower/logs/c/agt_abc.log"


class TestBuildAttachArgv:
    def test_argv_shape(self) -> None:
        argv = build_attach_argv(CONTAINER_USER, CONTAINER_ID, PANE, LOG)
        assert argv[:5] == [
            "docker", "exec", "-u", CONTAINER_USER, CONTAINER_ID,
        ]
        assert argv[5:7] == ["sh", "-lc"]
        # The inner shell command must be a single string.
        assert isinstance(argv[7], str)
        assert "tmux pipe-pane -o -t" in argv[7]

    def test_pane_short_form_quoted(self) -> None:
        argv = build_attach_argv(CONTAINER_USER, CONTAINER_ID, "weird:0.0", LOG)
        # shlex.quote of "weird:0.0" is the literal (no shell-meta) but the
        # construction MUST go through shlex.quote.
        assert shlex.quote("weird:0.0") in argv[7]

    def test_log_path_with_spaces_quoted(self) -> None:
        weird_log = "/host/log with spaces/x.log"
        argv = build_attach_argv(CONTAINER_USER, CONTAINER_ID, PANE, weird_log)
        # Must NOT contain unquoted ' with ' (it would be word-split).
        assert "'/host/log with spaces/x.log'" in argv[7] or shlex.quote(weird_log) in argv[7]

    def test_log_path_with_shell_meta_quoted(self) -> None:
        evil_log = "/host/log;rm -rf /.log"
        argv = build_attach_argv(CONTAINER_USER, CONTAINER_ID, PANE, evil_log)
        # The shell-meta MUST be inside quotes.
        assert shlex.quote(evil_log) in argv[7]


class TestBuildToggleOffArgv:
    def test_argv_shape(self) -> None:
        argv = build_toggle_off_argv(CONTAINER_USER, CONTAINER_ID, PANE)
        assert "tmux pipe-pane -t" in argv[7]
        assert "cat >>" not in argv[7]


class TestBuildInspectionArgv:
    def test_argv_shape(self) -> None:
        argv = build_inspection_argv(CONTAINER_USER, CONTAINER_ID, PANE)
        assert "tmux list-panes" in argv[7]
        assert "#{pane_pipe}" in argv[7]


class TestRenderPipeCommandForAudit:
    def test_bounded_at_4096_chars(self) -> None:
        long_log = "/x/" + "a" * 5000 + ".log"
        rendered = render_pipe_command_for_audit(
            CONTAINER_USER, CONTAINER_ID, PANE, long_log
        )
        assert len(rendered) <= 4096

    def test_strips_control_bytes(self) -> None:
        # The interpolated values are already sanitized upstream, but the
        # storage helper still strips defensively.
        rendered = render_pipe_command_for_audit(
            CONTAINER_USER, CONTAINER_ID, PANE, LOG
        )
        for ch in rendered:
            if ch == "\t":
                continue
            assert ord(ch) >= 0x20


class TestSanitizePipePaneStderr:
    def test_caps_at_2048_chars(self) -> None:
        stderr = "X" * 5000
        out = sanitize_pipe_pane_stderr(stderr)
        assert len(out) <= 2048

    def test_strips_nul_byte(self) -> None:
        out = sanitize_pipe_pane_stderr("hello\x00world")
        assert "\x00" not in out

    def test_strips_control_bytes(self) -> None:
        out = sanitize_pipe_pane_stderr("hello\x01world")
        assert "\x01" not in out

    def test_normalizes_newlines_to_spaces(self) -> None:
        out = sanitize_pipe_pane_stderr("line1\nline2")
        assert "\n" not in out

    def test_accepts_bytes_input(self) -> None:
        out = sanitize_pipe_pane_stderr(b"hello")
        assert out == "hello"


# ---------------------------------------------------------------------------
# Pipe-state inspection (FR-011 / FR-054)
# ---------------------------------------------------------------------------


class TestParseListPanesOutput:
    def test_inactive_pipe(self) -> None:
        state = parse_list_panes_output("0 \n")
        assert state.pipe_active is False

    def test_active_pipe_with_command(self) -> None:
        state = parse_list_panes_output("1 cat >> /host/x.log\n")
        assert state.pipe_active is True
        assert "cat >>" in state.pipe_command

    def test_active_with_empty_command_treated_inactive(self) -> None:
        # tmux 1=active but empty command means the pipe is in a transient
        # state; defensive parser treats it as inactive.
        state = parse_list_panes_output("1 \n")
        assert state.pipe_active is False


class TestClassifyPipeTarget:
    def test_canonical_match_strict_equality(self) -> None:
        canonical = "/host/canonical.log"
        cmd = f"cat >> {shlex.quote(canonical)}"
        result = classify_pipe_target(cmd, canonical)
        assert result.is_canonical is True
        assert result.foreign_target is None

    def test_substring_trickery_classified_foreign_fr054(self) -> None:
        canonical = "/host/canonical.log"
        # Embedded canonical-as-substring-after-semicolon must NOT match.
        evil = f"cat >> /tmp/innocent.log; cat >> {shlex.quote(canonical)}"
        result = classify_pipe_target(evil, canonical)
        assert result.is_canonical is False
        assert result.foreign_target == evil.strip()

    def test_foreign_target_recorded(self) -> None:
        result = classify_pipe_target("cat >> /tmp/other.log", "/host/canonical.log")
        assert result.is_canonical is False
        assert result.foreign_target == "cat >> /tmp/other.log"


class TestSanitizePriorPipeTarget:
    def test_caps_at_2048_chars(self) -> None:
        out = sanitize_prior_pipe_target("X" * 5000)
        assert len(out) <= 2048

    def test_strips_control_bytes(self) -> None:
        out = sanitize_prior_pipe_target("hello\x00world\x01tail")
        assert "\x00" not in out
        assert "\x01" not in out
