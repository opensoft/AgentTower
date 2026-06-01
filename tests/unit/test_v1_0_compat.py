"""FEAT-014 T023 — SC-004 v1.0-compatibility regression.

Boots a v1.1-advertising daemon (already the current branch state per
T002's bump) and re-runs the **full** FEAT-011 v1.0 contract test suite
via ``pytest -m 'not v1_1'``. The marker filter deselects every assertion
FEAT-014 added (T005 / T011 / T017 / T021 / T022 / T025 each mark new
assertions ``@pytest.mark.v1_1``), leaving only the pre-existing v1.0
baseline.

SC-004 holds iff every non-``v1_1`` assertion in the FEAT-011 contract
suite passes unchanged under the v1.1 daemon — the additive-minor
discipline (FR-014) is what makes that true.

Mechanism: subprocess pytest, not in-process. Reason: the regression
needs an isolated pytest invocation with its own collection pass + marker
filter so we don't recursively re-collect this very test. The subprocess
target is the **self-correcting glob** ``tests/unit/test_app_*.py`` (per
spec.md SC-004 "full v1.0 contract suite", tasks.md T023 "without needing
an explicit file allowlist", and plan.md:38) — expanded in Python because
``subprocess.run`` uses ``shell=False``. A new FEAT-011 contract test file
is therefore picked up automatically; FEAT-014-only additions are excluded
by the ``-m 'not v1_1'`` filter, not by an allowlist. ``test_v1_0_compat``
itself does not match the ``test_app_*`` glob, so no recursion is possible.

Per the v1.1 marker rule: T024 extends ``tests/integration/
test_story1_dashboard_bootstrap.py`` which T023 does NOT re-run; T024
therefore doesn't require the marker.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys


def test_sc004_feat011_v1_0_contract_passes_against_v1_1_daemon() -> None:
    """SC-004 regression: re-runs the full FEAT-011 v1.0 contract test
    suite against the v1.1-advertising daemon, asserting every selected
    (non-``v1_1``) test passes.

    On failure, the captured stdout/stderr of the subprocess pytest is
    included in the assertion message so a CI failure points directly at
    the offending v1.0 assertion.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    src_path = os.path.join(repo_root, "src")
    env = os.environ.copy()
    # Use truthiness, not membership: a set-but-empty PYTHONPATH ("") would
    # otherwise produce a trailing path separator, which Python interprets
    # as CWD and silently injects into the subprocess sys.path.
    existing_pp = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{existing_pp}" if existing_pp else src_path

    # Self-correcting glob over the FEAT-011 contract suite (NOT a hardcoded
    # allowlist — see module docstring + tasks.md T023). subprocess.run uses
    # shell=False, so expand the glob here in Python. Sorted for a stable,
    # deterministic command line.
    contract_test_files = sorted(
        os.path.relpath(p, repo_root)
        for p in glob.glob(os.path.join(repo_root, "tests", "unit", "test_app_*.py"))
    )
    assert contract_test_files, (
        "SC-004 regression found NO tests/unit/test_app_*.py files to replay "
        "— the FEAT-011 contract suite appears to be missing or moved."
    )

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
        timeout=300,
    )

    # SC-004 requires the v1.0 baseline to PASS, not merely "not fail."
    # Parse the post-filter `selected` count — NOT total `collected`.
    # pytest prints "collected N items / M deselected / K selected" when
    # anything is deselected; `collected` counts the deselected v1_1 items
    # too, so a run that deselects EVERY v1.0 assertion (the over-applied-
    # marker regression this guard exists to catch) still exits 0 with a
    # positive `collected`. Only `selected` reflects what actually ran.
    selected_match = re.search(r"(\d+) selected", result.stdout)
    if selected_match is not None:
        selected = int(selected_match.group(1))
    else:
        # pytest omits the "/ K selected" suffix when nothing was deselected;
        # in that case `collected` IS the selected count.
        collected_match = re.search(r"collected (\d+) items?", result.stdout)
        selected = int(collected_match.group(1)) if collected_match else 0

    assert result.returncode == 0, (
        f"SC-004 v1.0-compat regression failed: subprocess pytest exit "
        f"code {result.returncode} (expected 0)\n"
        f"---STDOUT---\n{result.stdout}\n"
        f"---STDERR---\n{result.stderr}"
    )
    assert selected > 0, (
        f"SC-004 v1.0-compat regression SELECTED zero tests — the "
        f"'-m not v1_1' filter or the test_app_*.py glob deselected "
        f"everything, so the regression proves nothing. Check that the "
        f"FEAT-011 contract test files still exist and that the v1.1 "
        f"marker rule has not been over-applied to v1.0 baseline "
        f"assertions.\n"
        f"---STDOUT---\n{result.stdout}\n"
        f"---STDERR---\n{result.stderr}"
    )
