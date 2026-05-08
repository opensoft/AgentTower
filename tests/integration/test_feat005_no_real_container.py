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
        """FEAT-005 FR-022 forbade any new socket method through FEAT-005.

        FEAT-006 explicitly adds 5 methods (FR-023): ``register_agent``,
        ``list_agents``, ``set_role``, ``set_label``, ``set_capability``.
        FEAT-007 adds 4 more (FR-038): ``attach_log``, ``detach_log``,
        ``attach_log_status``, ``attach_log_preview``. This test pins the
        closed FEAT-001..007 set so an accidental extra method cannot
        sneak in beyond the spec'd surface.
        """
        from agenttower.socket_api import methods as methods_module

        # The dispatch table is `DISPATCH` per the FEAT-002..007 builds.
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
            "register_agent",
            "list_agents",
            "set_role",
            "set_label",
            "set_capability",
            "attach_log",
            "detach_log",
            "attach_log_status",
            "attach_log_preview",
        }, f"unexpected method count: {sorted(dispatch.keys())}"
        assert len(dispatch) == 16


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
