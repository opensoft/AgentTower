"""FEAT-005 SC-009 / FR-022 guards (T054).

Folds analyze finding **A7** — dispatch-table cardinality assertion: the
daemon's socket-method dispatch table MUST stay at exactly the FEAT-001..004
size after FEAT-005 (FR-022).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# A7: dispatch table cardinality (FR-022)
# ---------------------------------------------------------------------------


class TestDispatchTableCardinality:
    def test_dispatch_table_method_count_unchanged(self):
        """FR-022 forbids any new socket method. Pre-FEAT-005 the table had
        exactly 7 entries (ping, status, shutdown, scan_containers,
        list_containers, scan_panes, list_panes). Asserts the count and the
        exact method names so a new entry cannot sneak in."""
        from agenttower.socket_api import methods as methods_module

        # The dispatch table is `DISPATCH` per the FEAT-002 / 003 / 004 builds.
        # We do not import a name we don't know exists — we discover it.
        dispatch = getattr(methods_module, "DISPATCH", None)
        assert dispatch is not None, "expected DISPATCH dict in socket_api/methods.py"
        assert isinstance(dispatch, dict)
        assert set(dispatch.keys()) == {
            "ping",
            "status",
            "shutdown",
            "scan_containers",
            "list_containers",
            "scan_panes",
            "list_panes",
        }, f"unexpected method count: {sorted(dispatch.keys())}"
        assert len(dispatch) == 7


# ---------------------------------------------------------------------------
# SC-009: no real Docker / tmux / container-runtime subprocess
# ---------------------------------------------------------------------------


class TestNoRealSubprocess:
    """FEAT-005 must not spawn docker / tmux / runc / podman / id / cat /
    any container-runtime subprocess. The session-level guard in
    tests/conftest.py already monkeypatches subprocess.run / shutil.which,
    so any FEAT-005 code path that violated FR-011 / FR-020 would already
    fail elsewhere. This test is a smoke check that calling the doctor
    package functions doesn't spawn anything."""

    def test_doctor_package_imports_without_subprocess(self):
        # Importing the package must not call subprocess; the session-level
        # conftest guard would catch a violation. We just exercise the top
        # imports as a smoke test.
        from agenttower.config_doctor import (
            CHECK_ORDER,
            DoctorReport,
            render_json,
            render_tsv,
            run_doctor,
        )

        assert CHECK_ORDER[0] == "socket_resolved"
        assert callable(run_doctor)
        assert callable(render_json)
        assert callable(render_tsv)
