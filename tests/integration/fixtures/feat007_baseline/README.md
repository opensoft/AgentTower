# FEAT-007 Baseline CLI Fixtures

**Purpose**: Byte-identical stdout/stderr/exit-code reference output for every
FEAT-001..FEAT-007 documented `agenttower …` invocation, captured against the
FEAT-007 head-of-tree commit *before* any FEAT-008 production code lands.

**Consumed by**: `tests/integration/test_feat008_backcompat.py` (T092 in
`specs/008-event-ingestion-follow/tasks.md`). Plan §R12.

## Format

One sub-directory per command, named with `--` separating tokens (no spaces):

```
feat007_baseline/
├── README.md                           (this file)
├── status/
│   ├── stdout
│   ├── stderr
│   └── exit
├── status--json/
│   ├── stdout
│   ├── stderr
│   └── exit
├── config-paths/
│   ├── stdout
│   ├── stderr
│   └── exit
├── attach-log--status--target--agt_<id>/
│   └── ...
└── ...
```

Each sub-directory has three files:
- `stdout` — exact stdout bytes (no trailing-newline trimming)
- `stderr` — exact stderr bytes
- `exit` — single line containing the exit code as decimal text

Dynamic substitutions (timestamps, agent ids, container ids) are normalized
by the test harness via the same scrubber the daemon harness uses for log
diffs; the fixtures contain the post-scrub canonical form.

## Capture procedure

The capture is one-shot, run against a clean tree at the FEAT-007 head-of-tree
commit. The committed fixtures are checked in; the capture script is the
provenance of those fixtures and is checked in alongside.

Run from the repo root, against a checkout at the FEAT-007 head-of-tree (the
merge commit `a92e4e3` for PR #10, or any later commit that has not yet
landed FEAT-008 production changes):

```bash
git checkout a92e4e3 -- src/agenttower
python tests/integration/fixtures/feat007_baseline/capture.py
git checkout HEAD -- src/agenttower    # restore FEAT-008 working tree
git add tests/integration/fixtures/feat007_baseline/
```

The capture script enumerates the FEAT-001..FEAT-007 documented CLI surface
(see the script for the explicit list), invokes each command against an
isolated `$HOME`-rooted test daemon, and writes the three fixture files per
command. Re-running overwrites the captures.

## Why pre-capture?

The single highest-risk regression for FEAT-008 is the daemon init path
(reader thread now starts at boot). Capturing FEAT-007 baseline output BEFORE
FEAT-008 changes affect any daemon behavior gives `test_feat008_backcompat.py`
a stable byte-for-byte oracle. After FEAT-008 lands, the captures would no
longer be reproducible because the daemon's init log line set, status surface,
and timing would all differ.

## Status

The fixtures themselves are written by `capture.py` on first run. This README
plus `capture.py` are the only files committed before the capture; the actual
fixture sub-directories are produced by running the script and then
committed in a follow-up.
