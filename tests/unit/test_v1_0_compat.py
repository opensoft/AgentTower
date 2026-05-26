"""FEAT-014 T023 — SC-004 v1.0-compatibility regression.

Boots a v1.1-advertising daemon (already the current branch state per
T002's bump) and re-runs the FEAT-011 v1.0 contract test suite via
``pytest -m 'not v1_1'``. The marker filter deselects every assertion
FEAT-014 added (T005 / T011 / T017 / T021 / T022 / T025 each mark new
assertions ``@pytest.mark.v1_1``), leaving only the pre-existing v1.0
baseline.

SC-004 holds iff every non-``v1_1`` assertion in the FEAT-011 contract
suite passes unchanged under the v1.1 daemon — the additive-minor
discipline (FR-014) is what makes that true.

Mechanism: subprocess pytest, not in-process. Reason: the regression
needs an isolated pytest invocation with its own collection pass + marker
filter so we don't recursively re-collect this very test. The subprocess
target is an **explicit list** of FEAT-011 contract test files (see the
``contract_test_files`` local below); ``subprocess.run`` uses
``shell=False``, so no glob expansion happens — adding a new FEAT-011
contract test file requires updating that list. This file itself
(``test_v1_0_compat.py``) is intentionally excluded from the list, so no
recursion is possible.

Per the v1.1 marker rule: T024 extends ``tests/integration/
test_story1_dashboard_bootstrap.py`` which T023 does NOT re-run; T024
therefore doesn't require the marker.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys


def test_sc004_feat011_v1_0_contract_passes_against_v1_1_daemon() -> None:
    """SC-004 regression: re-runs the FEAT-011 v1.0 contract test suite
    against the v1.1-advertising daemon, asserting every selected
    (non-``v1_1``) test passes.

    On failure, the captured stdout/stderr of the subprocess pytest is
    included in the assertion message so a CI failure points directly at
    the offending v1.0 assertion.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src_path = os.path.join(repo_root, "src")
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
        if "PYTHONPATH" in env
        else src_path
    )

    # Explicit per-file list (NOT a shell glob — subprocess.run uses
    # shell=False, so glob patterns are not expanded). Each file is a
    # FEAT-011 contract test file touched by the v1.0/v1.1 evolution.
    # Adding a new FEAT-011 contract test file requires adding it here.
    contract_test_files = [
        "tests/unit/test_app_dashboard.py",
        "tests/unit/test_app_versioning.py",
        "tests/unit/test_app_contract_foundations.py",
        "tests/unit/test_app_us5_capability_flags.py",
        "tests/unit/test_app_us5_version_mismatch.py",
        "tests/unit/test_app_us5_forward_compat.py",
    ]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *contract_test_files,
            "-m",
            "not v1_1",
            "--no-header",
            "--tb=short",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
        timeout=120,
    )

    # SC-004 requires the v1.0 baseline to PASS, not merely "not fail."
    # Treating pytest exit 5 (no tests collected) as success would mask
    # marker-or-path regressions that silently deselect every v1.0
    # assertion — the regression would then prove nothing. Require exit
    # code 0 AND a positive `collected` count parsed from pytest stdout.
    collected_match = re.search(r"collected (\d+) items?", result.stdout)
    collected = int(collected_match.group(1)) if collected_match else 0

    assert result.returncode == 0, (
        f"SC-004 v1.0-compat regression failed: subprocess pytest exit "
        f"code {result.returncode} (expected 0)\n"
        f"---STDOUT---\n{result.stdout}\n"
        f"---STDERR---\n{result.stderr}"
    )
    assert collected > 0, (
        f"SC-004 v1.0-compat regression collected ZERO tests — the "
        f"'-m not v1_1' filter or file list deselected everything, so the "
        f"regression proves nothing. Check that the FEAT-011 contract "
        f"test files still exist and that the v1.1 marker rule has not "
        f"been over-applied.\n"
        f"---STDOUT---\n{result.stdout}\n"
        f"---STDERR---\n{result.stderr}"
    )
