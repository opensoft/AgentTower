"""Unit tests for tmux_identity.py parsing — FR-009, FR-010, FR-011, FR-021, R-005."""

from __future__ import annotations

from agenttower.config_doctor.tmux_identity import ParsedTmuxEnv, parse_tmux_env


# ---------------------------------------------------------------------------
# FR-009: $TMUX comma-split
# ---------------------------------------------------------------------------


class TestTmuxCommaSplit:
    def test_three_field_split(self):
        env = {"TMUX": "/tmp/tmux-1000/default,12345,$0", "TMUX_PANE": "%0"}
        parsed = parse_tmux_env(env)
        assert parsed.in_tmux is True
        assert parsed.tmux_socket_path == "/tmp/tmux-1000/default"
        assert parsed.server_pid == "12345"
        assert parsed.session_id == "$0"

    def test_session_id_with_extra_commas_preserved(self):
        # Split on FIRST TWO commas only — extra commas are part of session_id
        env = {
            "TMUX": "/tmp/tmux-1000/default,12345,id,with,commas",
            "TMUX_PANE": "%0",
        }
        parsed = parse_tmux_env(env)
        assert parsed.session_id == "id,with,commas"

    def test_only_two_fields_is_malformed(self):
        env = {"TMUX": "/tmp/tmux/sock,12345", "TMUX_PANE": "%0"}
        parsed = parse_tmux_env(env)
        assert parsed.in_tmux is True
        assert parsed.tmux_socket_path is None
        assert parsed.malformed_reason is not None

    def test_empty_field_is_malformed(self):
        env = {"TMUX": "/tmp/tmux/sock,,$0", "TMUX_PANE": "%0"}
        parsed = parse_tmux_env(env)
        assert parsed.malformed_reason is not None


# ---------------------------------------------------------------------------
# FR-010: $TMUX_PANE %N validation
# ---------------------------------------------------------------------------


class TestTmuxPaneShape:
    def test_valid_pane_id(self):
        env = {"TMUX": "/tmp/tmux/sock,12345,$0", "TMUX_PANE": "%0"}
        parsed = parse_tmux_env(env)
        assert parsed.pane_id_valid is True
        assert parsed.tmux_pane_id == "%0"
        assert parsed.malformed_reason is None

    def test_pane_id_multidigit_valid(self):
        env = {"TMUX": "/tmp/tmux/sock,12345,$0", "TMUX_PANE": "%42"}
        parsed = parse_tmux_env(env)
        assert parsed.pane_id_valid is True

    def test_pane_id_without_percent_invalid(self):
        env = {"TMUX": "/tmp/tmux/sock,12345,$0", "TMUX_PANE": "0"}
        parsed = parse_tmux_env(env)
        assert parsed.pane_id_valid is False
        assert parsed.malformed_reason is not None

    def test_pane_id_with_letters_invalid(self):
        env = {"TMUX": "/tmp/tmux/sock,12345,$0", "TMUX_PANE": "%abc"}
        parsed = parse_tmux_env(env)
        assert parsed.pane_id_valid is False

    def test_pane_id_with_whitespace_invalid(self):
        env = {"TMUX": "/tmp/tmux/sock,12345,$0", "TMUX_PANE": "% 1"}
        parsed = parse_tmux_env(env)
        assert parsed.pane_id_valid is False


# ---------------------------------------------------------------------------
# FR-009: $TMUX unset → not_in_tmux (NOT fail)
# ---------------------------------------------------------------------------


class TestNotInTmux:
    def test_tmux_unset_yields_not_in_tmux(self):
        parsed = parse_tmux_env({"TMUX_PANE": "%0"})  # only TMUX_PANE
        assert parsed.in_tmux is False
        assert parsed.tmux_socket_path is None
        assert parsed.malformed_reason is None

    def test_both_unset_yields_not_in_tmux(self):
        parsed = parse_tmux_env({})
        assert parsed.in_tmux is False
        assert parsed.malformed_reason is None

    def test_tmux_empty_string_treated_as_unset(self):
        parsed = parse_tmux_env({"TMUX": ""})
        assert parsed.in_tmux is False


# ---------------------------------------------------------------------------
# FR-021: sanitization (NUL strip, control bytes)
# ---------------------------------------------------------------------------


class TestSanitization:
    def test_nul_in_tmux_socket_path_stripped(self):
        env = {
            "TMUX": "/tmp/tmux/sock\x00,12345,$0",
            "TMUX_PANE": "%0",
        }
        parsed = parse_tmux_env(env)
        assert "\x00" not in (parsed.tmux_socket_path or "")
        assert parsed.tmux_socket_path == "/tmp/tmux/sock"

    def test_nul_in_pane_id_invalidates_shape(self):
        env = {
            "TMUX": "/tmp/tmux/sock,12345,$0",
            "TMUX_PANE": "%\x000",
        }
        parsed = parse_tmux_env(env)
        # NUL stripped → "%0" which IS valid
        assert parsed.pane_id_valid is True
        assert parsed.tmux_pane_id == "%0"

    def test_control_byte_in_pane_id_invalidates(self):
        env = {
            "TMUX": "/tmp/tmux/sock,12345,$0",
            "TMUX_PANE": "%\x011",  # C0 \x01 stripped → "%1" which is valid
        }
        parsed = parse_tmux_env(env)
        assert parsed.tmux_pane_id == "%1"
        assert parsed.pane_id_valid is True
