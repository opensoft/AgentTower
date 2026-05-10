"""Unit tests for FEAT-007 path_validation (T020 / FR-006 + FR-051..053)."""

from __future__ import annotations

import pytest

from agenttower.logs.path_validation import LogPathInvalid, validate_log_path


def _validate(path: str, *, home: str = "/home/brett") -> None:
    validate_log_path(path, home=home)


class TestFR006Shape:
    def test_must_be_string(self) -> None:
        with pytest.raises(LogPathInvalid):
            validate_log_path(123, home="/home/brett")

    def test_no_nul_byte(self) -> None:
        with pytest.raises(LogPathInvalid, match="NUL"):
            _validate("/host/path\x00with-nul")

    def test_must_be_absolute(self) -> None:
        with pytest.raises(LogPathInvalid, match="absolute"):
            _validate("relative/path.log")

    def test_no_dotdot_segment(self) -> None:
        with pytest.raises(LogPathInvalid, match="\\.\\."):
            _validate("/host/../escape")

    def test_max_length(self) -> None:
        with pytest.raises(LogPathInvalid, match="maximum length"):
            _validate("/" + "a" * 5000)

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="empty"):
            _validate("")


class TestFR051ControlBytes:
    def test_newline_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="forbidden control byte"):
            _validate("/host/path\nwith-newline")

    def test_carriage_return_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="forbidden control byte"):
            _validate("/host/path\rwith-cr")

    def test_tab_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="forbidden control byte"):
            _validate("/host/path\twith-tab")

    def test_del_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="forbidden control byte"):
            _validate("/host/path\x7fwith-del")


class TestFR052DaemonOwnedRoots:
    def test_under_canonical_log_root_allowed(self) -> None:
        _validate("/home/brett/.local/state/opensoft/agenttower/logs/c/x.log")

    def test_at_canonical_log_root_allowed(self) -> None:
        _validate("/home/brett/.local/state/opensoft/agenttower/logs")

    def test_at_state_namespace_root_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="daemon-owned root"):
            _validate("/home/brett/.local/state/opensoft/agenttower/agenttower.sqlite3")

    def test_under_config_namespace_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="daemon-owned root"):
            _validate("/home/brett/.config/opensoft/agenttower/config.toml")

    def test_under_cache_namespace_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="daemon-owned root"):
            _validate("/home/brett/.cache/opensoft/agenttower/cache.bin")


class TestFR053SpecialFilesystems:
    def test_proc_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="special filesystem"):
            _validate("/proc/1/status")

    def test_sys_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="special filesystem"):
            _validate("/sys/kernel")

    def test_dev_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="special filesystem"):
            _validate("/dev/null")

    def test_run_rejected(self) -> None:
        with pytest.raises(LogPathInvalid, match="special filesystem"):
            _validate("/run/user/1000/socket")


class TestNormalPathsAccepted:
    def test_unrelated_absolute_path(self) -> None:
        _validate("/var/log/application/output.log")

    def test_path_with_spaces(self) -> None:
        _validate("/var/log with space/output.log")

    def test_path_with_shell_meta_printable(self) -> None:
        # FR-051 only catches control bytes; printable shell-meta chars are
        # handled at shell-construction time via shlex.quote (FR-047).
        _validate("/var/log/$weird;$(name).log")
