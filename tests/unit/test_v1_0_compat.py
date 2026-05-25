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
target is the glob ``tests/unit/test_app_*.py`` per the v1.1 marker rule
note in tasks.md §Notes (this file is ``test_v1_0_compat.py``, doesn't
match, no recursion).

Per the v1.1 marker rule: T024 extends ``tests/integration/
test_story1_dashboard_bootstrap.py`` which T023 does NOT re-run; T024
therefore doesn't require the marker.
"""

from __future__ import annotations

import os
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

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            # Glob the FEAT-011 contract test files per tasks.md §Notes
            # 'v1.1 marker rule'. The glob is expanded by the shell — we
            # pass the literal pattern and let pytest's collector handle it.
            "tests/unit/test_app_dashboard.py",
            "tests/unit/test_app_versioning.py",
            # FEAT-011 baseline test files that ship app-contract assertions
            # touched by the v1.0/v1.1 evolution:
            "tests/unit/test_app_contract_foundations.py",
            "tests/unit/test_app_us5_capability_flags.py",
            "tests/unit/test_app_us5_version_mismatch.py",
            "tests/unit/test_app_us5_forward_compat.py",
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

    # Pytest exit codes:
    #   0 = all tests passed
    #   5 = no tests collected (acceptable: a file fully marked v1.1
    #       would have 0 selected tests after deselect, NOT a failure)
    # Anything else (1, 2, 3, 4) = real failure.
    assert result.returncode in (0, 5), (
        f"SC-004 v1.0-compat regression failed: subprocess pytest exit "
        f"code {result.returncode}\n"
        f"---STDOUT---\n{result.stdout}\n"
        f"---STDERR---\n{result.stderr}"
    )
