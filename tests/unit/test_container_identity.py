"""Unit tests for identity.py — FR-006, FR-007, R-004 (CHK024–CHK032).

The lower half of this file (TestSC008Matrix) closes T063 by exercising
the full SC-008 (signal-shape × outcome) matrix at the classifier level.
The classifier itself lives in ``checks.py`` as
``classify_identity_to_check_result`` (the standalone
``identity.classify_identity`` shipped as a stub; the operational
classifier was inlined in checks.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agenttower.config_doctor.checks import classify_identity_to_check_result
from agenttower.config_doctor.identity import (
    CgroupMultiCandidate,
    IdentityCandidate,
    detect_candidate,
)
from agenttower.config_doctor.runtime_detect import (
    ContainerContext,
    HostContext,
)


@pytest.fixture
def fake_root(tmp_path: Path):
    def _build(*, cgroup_lines=None, hostname=None) -> Path:
        proc_self = tmp_path / "proc" / "self"
        proc_self.mkdir(parents=True, exist_ok=True)
        etc = tmp_path / "etc"
        etc.mkdir(parents=True, exist_ok=True)
        if cgroup_lines is not None:
            (proc_self / "cgroup").write_text("\n".join(cgroup_lines) + "\n")
        else:
            (proc_self / "cgroup").write_text("")
        if hostname is not None:
            (etc / "hostname").write_text(hostname + "\n")
        return tmp_path

    return _build


# ---------------------------------------------------------------------------
# FR-006 four-step precedence (CHK024)
# ---------------------------------------------------------------------------


class TestPrecedence:
    def test_env_override_wins_over_cgroup(self, fake_root):
        root = fake_root(cgroup_lines=["0::/docker/abc123def4567890"])
        result = detect_candidate(
            {"AGENTTOWER_CONTAINER_ID": "manually-pinned-id"},
            proc_root=str(root),
        )
        assert isinstance(result, IdentityCandidate)
        assert result.candidate == "manually-pinned-id"
        assert result.signal == "env"

    def test_cgroup_wins_over_hostname(self, fake_root):
        root = fake_root(
            cgroup_lines=["0::/docker/abc123def4567890"],
            hostname="ignoredhost",
        )
        result = detect_candidate({}, proc_root=str(root))
        assert isinstance(result, IdentityCandidate)
        assert result.candidate == "abc123def4567890"
        assert result.signal == "cgroup"

    def test_hostname_when_cgroup_empty(self, fake_root):
        root = fake_root(cgroup_lines=[], hostname="abc123def456")
        result = detect_candidate({}, proc_root=str(root))
        assert isinstance(result, IdentityCandidate)
        assert result.candidate == "abc123def456"
        assert result.signal == "hostname"

    def test_hostname_env_when_etc_hostname_empty(self, fake_root):
        root = fake_root(cgroup_lines=[])
        result = detect_candidate(
            {"HOSTNAME": "fallback-host"}, proc_root=str(root)
        )
        assert isinstance(result, IdentityCandidate)
        assert result.candidate == "fallback-host"
        assert result.signal == "hostname_env"

    def test_no_signal_returns_none(self, fake_root):
        root = fake_root(cgroup_lines=[])
        result = detect_candidate({}, proc_root=str(root))
        assert result is None


# ---------------------------------------------------------------------------
# FR-006 multi-line cgroup rule (Clarifications 2026-05-06; CHK032 / Q4)
# ---------------------------------------------------------------------------


class TestCgroupMultiLine:
    def test_cgroup_v2_unified_only(self, fake_root):
        """Single ``0::/...`` line yields one identifier."""
        root = fake_root(cgroup_lines=["0::/docker/abc123def4567890"])
        result = detect_candidate({}, proc_root=str(root))
        assert isinstance(result, IdentityCandidate)
        assert result.candidate == "abc123def4567890"

    def test_cgroup_v1_consistent(self, fake_root):
        """Multiple per-subsystem matching lines, same trailing id → single candidate."""
        same_id = "abc123def4567890"
        root = fake_root(
            cgroup_lines=[
                f"12:cpu:/docker/{same_id}",
                f"11:memory:/docker/{same_id}",
                f"10:pids:/docker/{same_id}",
            ],
        )
        result = detect_candidate({}, proc_root=str(root))
        assert isinstance(result, IdentityCandidate)
        assert result.candidate == same_id

    def test_cgroup_v1_inconsistent(self, fake_root):
        """Multiple matching lines yield distinct ids → CgroupMultiCandidate."""
        root = fake_root(
            cgroup_lines=[
                "12:cpu:/docker/aaaaaaaaaaaa1111",
                "11:memory:/docker/bbbbbbbbbbbb2222",
            ],
        )
        result = detect_candidate({}, proc_root=str(root))
        assert isinstance(result, CgroupMultiCandidate)
        assert set(result.candidates) == {
            "aaaaaaaaaaaa1111",
            "bbbbbbbbbbbb2222",
        }
        # Doctor MUST NOT pick one arbitrarily — both surface
        assert len(result.candidates) == 2


# ---------------------------------------------------------------------------
# FR-006 step 1 / FR-021 sanitization
# ---------------------------------------------------------------------------


class TestEnvSanitization:
    def test_env_value_nul_stripped(self, fake_root):
        root = fake_root()
        result = detect_candidate(
            {"AGENTTOWER_CONTAINER_ID": "id\x00with\x00nulls"},
            proc_root=str(root),
        )
        assert isinstance(result, IdentityCandidate)
        assert "\x00" not in result.candidate
        assert result.candidate == "idwithnulls"

    def test_env_value_used_verbatim_otherwise(self, fake_root):
        root = fake_root()
        result = detect_candidate(
            {"AGENTTOWER_CONTAINER_ID": "verbatim-id-with-dashes-and.dots"},
            proc_root=str(root),
        )
        assert isinstance(result, IdentityCandidate)
        assert result.candidate == "verbatim-id-with-dashes-and.dots"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_network_host_hostname_collision_produces_candidate(self, fake_root):
        """--network host: /etc/hostname is the host hostname; the candidate is
        produced and the cross-check (Phase 5) will classify it as no_match."""
        root = fake_root(cgroup_lines=[], hostname="my-laptop")
        result = detect_candidate({}, proc_root=str(root))
        assert isinstance(result, IdentityCandidate)
        assert result.candidate == "my-laptop"
        assert result.signal == "hostname"

    def test_empty_hostname_file_falls_through(self, fake_root):
        root = fake_root(cgroup_lines=[], hostname="")
        result = detect_candidate(
            {"HOSTNAME": "from-env"}, proc_root=str(root)
        )
        # Empty file content + sanitization → empty → fall through to $HOSTNAME
        assert isinstance(result, IdentityCandidate)
        assert result.signal == "hostname_env"

    def test_unsupported_cgroup_prefix_does_not_match(self, fake_root):
        """Firejail/Bubblewrap shapes don't match FR-004 prefixes."""
        root = fake_root(
            cgroup_lines=["0::/firejail.slice/firejail-1234.scope"],
        )
        result = detect_candidate({}, proc_root=str(root))
        assert result is None


# ---------------------------------------------------------------------------
# T063 / SC-008 / CHK098: classifier-level matrix coverage
#
# SC-008 enumerates (signal-shape) × (outcome) cells. The signal shapes
# are: cgroup, hostname, env, env+hostname (env wins per FR-006), with
# a candidate that may be either full-id (64 hex) or short-id-prefix
# (12 hex). The outcomes are the FR-007 closed set: unique_match,
# multi_match, no_match, no_candidate, host_context.
#
# Many product cells are physically impossible: ``no_candidate`` and
# ``host_context`` require *no* signal to fire, so source-shape is moot;
# ``host_context`` additionally requires HostContext. The valid cells
# below are the operational SC-008 matrix.
# ---------------------------------------------------------------------------


_FULL_ID = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
_SHORT_PREFIX = "abcdef012345"  # first 12 chars of _FULL_ID
_OTHER_FULL_ID = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
_OTHER_SHORT_PREFIX = "1234567890ab"


def _container_row(cid: str, name: str = "py-bench") -> dict:
    return {"id": cid, "name": name}


def _classify(candidate, *, runtime_context, rows):
    return classify_identity_to_check_result(
        candidate=candidate,
        runtime_context=runtime_context,
        list_containers_rows=tuple(rows),
        daemon_set_empty=(len(rows) == 0),
    )


_MATRIX_CELLS = [
    # ------------------------------------------------------------------
    # unique_match — every signal-shape × candidate-shape combination
    # ------------------------------------------------------------------
    pytest.param(
        IdentityCandidate(candidate=_FULL_ID, signal="cgroup"),
        ContainerContext(detection_signals=("cgroup",)),
        [_container_row(_FULL_ID)],
        "pass", "unique_match", "cgroup",
        id="cgroup_full_id_unique_match",
    ),
    pytest.param(
        IdentityCandidate(candidate=_SHORT_PREFIX, signal="cgroup"),
        ContainerContext(detection_signals=("cgroup",)),
        [_container_row(_FULL_ID)],
        "pass", "unique_match", "cgroup",
        id="cgroup_short_prefix_unique_match",
    ),
    pytest.param(
        IdentityCandidate(candidate=_FULL_ID, signal="hostname"),
        ContainerContext(detection_signals=("dockerenv",)),
        [_container_row(_FULL_ID)],
        "pass", "unique_match", "hostname",
        id="hostname_full_id_unique_match",
    ),
    pytest.param(
        IdentityCandidate(candidate=_SHORT_PREFIX, signal="hostname"),
        ContainerContext(detection_signals=("dockerenv",)),
        [_container_row(_FULL_ID)],
        "pass", "unique_match", "hostname",
        id="hostname_short_prefix_unique_match",
    ),
    pytest.param(
        IdentityCandidate(candidate=_FULL_ID, signal="env"),
        ContainerContext(detection_signals=("dockerenv",)),
        [_container_row(_FULL_ID)],
        "pass", "unique_match", "env",
        id="env_full_id_unique_match",
    ),
    pytest.param(
        IdentityCandidate(candidate=_SHORT_PREFIX, signal="env"),
        ContainerContext(detection_signals=("dockerenv",)),
        [_container_row(_FULL_ID)],
        "pass", "unique_match", "env",
        id="env_short_prefix_unique_match",
    ),
    # env+hostname is exercised in TestPrecedence.test_env_override_wins_over_cgroup
    # at the parser level (env wins). At the classifier level the candidate
    # arrives with signal="env"; the classifier doesn't know hostname was
    # also present. The cell is captured by env_full_id_unique_match above.
    # ------------------------------------------------------------------
    # multi_match — short-prefix collision across two rows
    # ------------------------------------------------------------------
    pytest.param(
        IdentityCandidate(candidate=_SHORT_PREFIX, signal="cgroup"),
        ContainerContext(detection_signals=("cgroup",)),
        [
            _container_row(_FULL_ID),
            _container_row(_SHORT_PREFIX + "ffffffffffffffffffffffffffffffffffffffffffffffffffff"),
        ],
        "fail", "multi_match", "cgroup",
        id="cgroup_short_prefix_multi_match",
    ),
    pytest.param(
        IdentityCandidate(candidate=_SHORT_PREFIX, signal="hostname"),
        ContainerContext(detection_signals=("dockerenv",)),
        [
            _container_row(_FULL_ID),
            _container_row(_SHORT_PREFIX + "ffffffffffffffffffffffffffffffffffffffffffffffffffff"),
        ],
        "fail", "multi_match", "hostname",
        id="hostname_short_prefix_multi_match",
    ),
    pytest.param(
        IdentityCandidate(candidate=_SHORT_PREFIX, signal="env"),
        ContainerContext(detection_signals=("dockerenv",)),
        [
            _container_row(_FULL_ID),
            _container_row(_SHORT_PREFIX + "ffffffffffffffffffffffffffffffffffffffffffffffffffff"),
        ],
        "fail", "multi_match", "env",
        id="env_short_prefix_multi_match",
    ),
    # ------------------------------------------------------------------
    # no_match — candidate produced but no row matches
    # ------------------------------------------------------------------
    pytest.param(
        IdentityCandidate(candidate=_FULL_ID, signal="cgroup"),
        ContainerContext(detection_signals=("cgroup",)),
        [_container_row(_OTHER_FULL_ID)],
        "fail", "no_match", "cgroup",
        id="cgroup_full_id_no_match",
    ),
    pytest.param(
        IdentityCandidate(candidate=_SHORT_PREFIX, signal="hostname"),
        ContainerContext(detection_signals=("dockerenv",)),
        [_container_row(_OTHER_FULL_ID)],
        "fail", "no_match", "hostname",
        id="hostname_short_prefix_no_match",
    ),
    pytest.param(
        IdentityCandidate(candidate=_FULL_ID, signal="env"),
        ContainerContext(detection_signals=("dockerenv",)),
        [_container_row(_OTHER_FULL_ID)],
        "fail", "no_match", "env",
        id="env_full_id_no_match",
    ),
    pytest.param(
        IdentityCandidate(candidate=_FULL_ID, signal="cgroup"),
        ContainerContext(detection_signals=("cgroup",)),
        [],
        "fail", "no_match", "cgroup",
        id="cgroup_no_match_daemon_set_empty",
    ),
    # ------------------------------------------------------------------
    # no_candidate — every signal returned empty AND ContainerContext
    # ------------------------------------------------------------------
    pytest.param(
        None,
        ContainerContext(detection_signals=("dockerenv",)),
        [],
        "fail", "no_candidate", None,
        id="no_signal_container_context_no_candidate",
    ),
    pytest.param(
        None,
        ContainerContext(detection_signals=("dockerenv",)),
        [_container_row(_FULL_ID)],
        "fail", "no_candidate", None,
        id="no_signal_container_context_with_rows_no_candidate",
    ),
    # ------------------------------------------------------------------
    # host_context — every signal empty AND HostContext
    # ------------------------------------------------------------------
    pytest.param(
        None,
        HostContext(),
        [],
        "info", "host_context", None,
        id="no_signal_host_context",
    ),
    pytest.param(
        None,
        HostContext(),
        [_container_row(_FULL_ID)],
        "info", "host_context", None,
        id="no_signal_host_context_even_with_rows",
    ),
    # ------------------------------------------------------------------
    # Cgroup multi-line distinct identifiers — FR-006 multi-line rule
    # ------------------------------------------------------------------
    pytest.param(
        CgroupMultiCandidate(
            candidates=("aaaaaaaaaaaa1111", "bbbbbbbbbbbb2222")
        ),
        ContainerContext(detection_signals=("cgroup",)),
        [],
        "fail", "multi_match", "cgroup",
        id="cgroup_multi_line_distinct_ids_multi_match",
    ),
]


class TestSC008Matrix:
    """T063 / SC-008 / CHK098: every cell in the operational
    (signal-shape × outcome) matrix is exercised at the classifier
    level."""

    @pytest.mark.parametrize(
        "candidate,runtime_context,rows,expected_status,expected_sub_code,expected_source",
        _MATRIX_CELLS,
    )
    def test_cell(
        self,
        candidate,
        runtime_context,
        rows,
        expected_status,
        expected_sub_code,
        expected_source,
    ):
        result = _classify(candidate, runtime_context=runtime_context, rows=rows)
        assert result.code == "container_identity"
        assert result.status == expected_status
        assert result.sub_code == expected_sub_code
        if expected_source is not None:
            assert result.source == expected_source

    def test_no_containers_known_synonym_never_emitted(self):
        """CHK033: ``no_containers_known`` is NOT a sub-code; the
        empty-``list_containers`` case surfaces as
        ``daemon_container_set_empty=True`` on the existing
        ``no_candidate`` / ``no_match`` outcome (Clarifications
        2026-05-06)."""
        # Empty-set + candidate → no_match, with daemon_container_set_empty
        result = _classify(
            IdentityCandidate(candidate=_FULL_ID, signal="cgroup"),
            runtime_context=ContainerContext(detection_signals=("cgroup",)),
            rows=[],
        )
        assert result.sub_code == "no_match"
        assert result.sub_code != "no_containers_known"
        # The daemon_container_set_empty flag carries the sub-code-less qualifier
        assert getattr(result, "daemon_container_set_empty", None) is True

        # Empty-set + no candidate + ContainerContext → no_candidate, with flag
        result_no_cand = _classify(
            None,
            runtime_context=ContainerContext(detection_signals=("dockerenv",)),
            rows=[],
        )
        assert result_no_cand.sub_code == "no_candidate"
        assert result_no_cand.sub_code != "no_containers_known"

    def test_not_in_container_synonym_never_emitted(self):
        """CHK034: ``not_in_container`` synonym is dead per
        Clarifications 2026-05-06; only ``host_context`` is emitted."""
        result = _classify(
            None, runtime_context=HostContext(), rows=[]
        )
        assert result.sub_code == "host_context"
        assert result.sub_code != "not_in_container"

    def test_full_id_match_takes_precedence_over_short_prefix_match(self):
        """FR-006 / R-004: full-id equality is checked before 12-char
        short-id-prefix match. A candidate that matches one row by full id
        AND another row by short prefix must classify as unique_match
        against the full-id row."""
        # Use a different short prefix so the short-prefix branch only
        # matches when full-id equality misses; then construct rows where
        # exactly one row has full-id equality.
        rows = [
            _container_row(_FULL_ID),  # full-id eq
            _container_row(_SHORT_PREFIX + "f" * (64 - 12)),  # short-prefix collision
        ]
        result = _classify(
            IdentityCandidate(candidate=_FULL_ID, signal="cgroup"),
            runtime_context=ContainerContext(detection_signals=("cgroup",)),
            rows=rows,
        )
        # Full-id equality wins → unique_match, NOT multi_match
        assert result.status == "pass"
        assert result.sub_code == "unique_match"
