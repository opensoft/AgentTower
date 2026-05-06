"""Unit tests for FEAT-004 tmux parsers (T015 / SC-008)."""

from __future__ import annotations

import pytest

from agenttower.tmux import parsers


# ---------------------------------------------------------------------------
# parse_id_u
# ---------------------------------------------------------------------------


def test_parse_id_u_returns_digit_string() -> None:
    assert parsers.parse_id_u("1000\n") == "1000"


def test_parse_id_u_strips_whitespace_and_picks_first_non_empty_line() -> None:
    assert parsers.parse_id_u("\n  1234  \nignored\n") == "1234"


@pytest.mark.parametrize("stdout", ["", "   \n\n", "\t\n"])
def test_parse_id_u_empty_raises(stdout: str) -> None:
    with pytest.raises(ValueError):
        parsers.parse_id_u(stdout)


@pytest.mark.parametrize("stdout", ["abc\n", "1000abc\n", "-1\n"])
def test_parse_id_u_non_numeric_raises(stdout: str) -> None:
    with pytest.raises(ValueError):
        parsers.parse_id_u(stdout)


def test_parse_id_u_none_raises() -> None:
    with pytest.raises(ValueError):
        parsers.parse_id_u(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# parse_socket_listing
# ---------------------------------------------------------------------------


def test_parse_socket_listing_drops_blanks_and_path_separators() -> None:
    stdout = "default\nwork\n\n../escape\nsub/dir\n.\n..\n"
    assert parsers.parse_socket_listing(stdout) == ["default", "work"]


def test_parse_socket_listing_preserves_default_socket() -> None:
    assert "default" in parsers.parse_socket_listing("default\n")


def test_parse_socket_listing_handles_crlf() -> None:
    assert parsers.parse_socket_listing("default\r\nwork\r\n") == ["default", "work"]


def test_parse_socket_listing_empty_returns_empty_list() -> None:
    assert parsers.parse_socket_listing("") == []
    assert parsers.parse_socket_listing(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# parse_list_panes
# ---------------------------------------------------------------------------


_HAPPY_ROW = (
    "work\t0\t0\t%0\t1234\t/dev/pts/0\tbash\t/workspace\tuser@bench\t1"
)


def test_parse_list_panes_happy_path() -> None:
    parsed, malformed = parsers.parse_list_panes(_HAPPY_ROW + "\n")
    assert malformed == []
    assert len(parsed) == 1
    pane = parsed[0]
    assert pane.tmux_session_name == "work"
    assert pane.tmux_window_index == 0
    assert pane.tmux_pane_index == 0
    assert pane.tmux_pane_id == "%0"
    assert pane.pane_pid == 1234
    assert pane.pane_tty == "/dev/pts/0"
    assert pane.pane_current_command == "bash"
    assert pane.pane_current_path == "/workspace"
    assert pane.pane_title == "user@bench"
    assert pane.pane_active is True


def test_parse_list_panes_inactive_pane() -> None:
    row = "work\t0\t1\t%1\t1235\t/dev/pts/1\tvim\t/workspace\tediting\t0"
    parsed, malformed = parsers.parse_list_panes(row + "\n")
    assert not malformed
    assert parsed[0].pane_active is False


def test_parse_list_panes_too_few_fields_marked_malformed() -> None:
    row = "work\t0\t0\t%0\t1234\t/dev/pts/0\tbash\t/workspace"  # 8 fields
    parsed, malformed = parsers.parse_list_panes(row + "\n")
    assert parsed == []
    assert len(malformed) == 1
    assert malformed[0].expected_fields == 10
    assert malformed[0].actual_fields == 8


def test_parse_list_panes_too_many_fields_marked_malformed() -> None:
    row = _HAPPY_ROW + "\textra\textra2"  # 12 fields
    parsed, malformed = parsers.parse_list_panes(row + "\n")
    assert parsed == []
    assert len(malformed) == 1


def test_parse_list_panes_non_integer_indices_marked_malformed() -> None:
    row = "work\tNOT_INT\t0\t%0\t1234\t/dev/pts/0\tbash\t/workspace\ttitle\t1"
    parsed, malformed = parsers.parse_list_panes(row + "\n")
    assert parsed == []
    assert len(malformed) == 1


def test_parse_list_panes_unparseable_active_marked_malformed() -> None:
    row = "work\t0\t0\t%0\t1234\t/dev/pts/0\tbash\t/workspace\ttitle\tNAH"
    parsed, malformed = parsers.parse_list_panes(row + "\n")
    assert parsed == []
    assert len(malformed) == 1


def test_parse_list_panes_skips_blank_lines_between_rows() -> None:
    stdout = _HAPPY_ROW + "\n\n" + _HAPPY_ROW.replace("%0", "%1") + "\n"
    parsed, malformed = parsers.parse_list_panes(stdout)
    assert len(parsed) == 2
    assert malformed == []


def test_parse_list_panes_handles_none_and_empty() -> None:
    assert parsers.parse_list_panes("") == ([], [])
    assert parsers.parse_list_panes(None) == ([], [])  # type: ignore[arg-type]
