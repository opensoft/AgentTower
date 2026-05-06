"""Unit tests for runtime_detect.py — FR-003, FR-004, R-003 (CHK013–CHK023, CHK087)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agenttower.config_doctor.runtime_detect import (
    CGROUP_PREFIXES,
    ContainerContext,
    HostContext,
    detect,
)


@pytest.fixture
def fake_root(tmp_path: Path):
    """Build a fake `/proc` + `/etc` tree under tmp_path for runtime detection."""

    def _build(
        *,
        dockerenv: bool = False,
        containerenv: bool = False,
        cgroup_lines=None,
    ) -> Path:
        proc_self = tmp_path / "proc" / "self"
        proc_self.mkdir(parents=True, exist_ok=True)
        run = tmp_path / "run"
        run.mkdir(parents=True, exist_ok=True)
        if dockerenv:
            (tmp_path / ".dockerenv").write_text("")
        if containerenv:
            (run / ".containerenv").write_text("")
        if cgroup_lines is not None:
            (proc_self / "cgroup").write_text("\n".join(cgroup_lines) + "\n")
        else:
            (proc_self / "cgroup").write_text("")
        return tmp_path

    return _build


class TestClosedPrefixSet:
    def test_prefix_token_set_is_exact(self):
        """FR-004 / R-003 / plan §Constraints — the four prefixes are tokens."""
        assert CGROUP_PREFIXES == ("docker/", "containerd/", "kubepods/", "lxc/")
        # Each token must end with a slash (the FR-004 rule)
        for prefix in CGROUP_PREFIXES:
            assert prefix.endswith("/")


class TestHostContextFallthrough:
    def test_no_signals_yields_host_context(self, fake_root):
        root = fake_root()
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, HostContext)


class TestSingleSignalSignals:
    def test_dockerenv_alone_fires(self, fake_root):
        root = fake_root(dockerenv=True)
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, ContainerContext)
        assert "dockerenv" in ctx.detection_signals

    def test_containerenv_alone_fires(self, fake_root):
        root = fake_root(containerenv=True)
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, ContainerContext)
        assert "containerenv" in ctx.detection_signals

    def test_cgroup_docker_alone_fires(self, fake_root):
        root = fake_root(cgroup_lines=["0::/docker/abc123def456"])
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, ContainerContext)
        assert "cgroup" in ctx.detection_signals

    def test_cgroup_containerd_fires(self, fake_root):
        root = fake_root(
            cgroup_lines=["0::/system.slice/containerd/abc123def4567890aaaaaaaa"]
        )
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, ContainerContext)
        assert "cgroup" in ctx.detection_signals

    def test_cgroup_kubepods_fires(self, fake_root):
        root = fake_root(
            cgroup_lines=[
                "0::/kubepods/burstable/pod1234abcd/cccccccc11112222"
            ]
        )
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, ContainerContext)
        assert "cgroup" in ctx.detection_signals

    def test_cgroup_lxc_fires(self, fake_root):
        root = fake_root(cgroup_lines=["12:cpu:/lxc/9999888877776666"])
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, ContainerContext)
        assert "cgroup" in ctx.detection_signals


class TestUnsupportedSandboxes:
    """Firejail / Bubblewrap / systemd-nspawn fall to host_context."""

    def test_firejail_does_not_fire(self, fake_root):
        root = fake_root(cgroup_lines=["0::/firejail.slice"])
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, HostContext)

    def test_bubblewrap_does_not_fire(self, fake_root):
        root = fake_root(cgroup_lines=["0::/user.slice/user-1000.slice/bwrap"])
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, HostContext)

    def test_systemd_nspawn_does_not_fire(self, fake_root):
        root = fake_root(cgroup_lines=["0::/machine.slice/machine-foo.scope"])
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, HostContext)


class TestCgroupEdgeCases:
    def test_empty_cgroup_yields_host_context(self, fake_root):
        root = fake_root(cgroup_lines=[])
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, HostContext)

    def test_garbage_cgroup_yields_host_context(self, fake_root):
        root = fake_root(cgroup_lines=["junk", "more junk", "no slashes"])
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, HostContext)

    def test_unreadable_cgroup_swallowed_silently(self, fake_root):
        # Replace /proc/self/cgroup with a directory so reads fail with IsADir
        root = fake_root()
        cgroup_path = root / "proc" / "self" / "cgroup"
        if cgroup_path.exists():
            cgroup_path.unlink()
        cgroup_path.mkdir()  # make it a dir so open() fails
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, HostContext)


class TestMultipleSignals:
    def test_dockerenv_plus_cgroup_fires_both(self, fake_root):
        root = fake_root(
            dockerenv=True,
            cgroup_lines=["0::/docker/abc123def456"],
        )
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, ContainerContext)
        assert "dockerenv" in ctx.detection_signals
        assert "cgroup" in ctx.detection_signals

    def test_all_three_signals_fire_together(self, fake_root):
        root = fake_root(
            dockerenv=True,
            containerenv=True,
            cgroup_lines=["0::/docker/abc123def456"],
        )
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, ContainerContext)
        assert set(ctx.detection_signals) == {"dockerenv", "containerenv", "cgroup"}


class TestProcRootHonored:
    def test_explicit_proc_root_used_over_env(self, fake_root, monkeypatch):
        # Set the env var to a non-existent path; explicit arg should win
        monkeypatch.setenv("AGENTTOWER_TEST_PROC_ROOT", "/this/does/not/exist")
        root = fake_root(dockerenv=True)
        ctx = detect(proc_root=str(root))
        assert isinstance(ctx, ContainerContext)

    def test_env_var_used_when_no_arg(self, fake_root, monkeypatch):
        root = fake_root(dockerenv=True)
        monkeypatch.setenv("AGENTTOWER_TEST_PROC_ROOT", str(root))
        ctx = detect(proc_root=None)
        assert isinstance(ctx, ContainerContext)

    def test_no_env_no_arg_defaults_to_root(self, monkeypatch):
        monkeypatch.delenv("AGENTTOWER_TEST_PROC_ROOT", raising=False)
        # We don't assert what the real / yields — just that it doesn't crash
        ctx = detect(proc_root=None)
        assert isinstance(ctx, (HostContext, ContainerContext))
