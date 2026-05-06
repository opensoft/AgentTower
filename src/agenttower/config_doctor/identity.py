"""Container identity self-detection (FR-006, FR-007, FR-008, R-004).

The parsing-only half of identity detection lives here. The cross-check
classifier shipped as ``checks.classify_identity_to_check_result`` —
folded into ``checks.py`` for code-locality with the other doctor
checks rather than living in this module.

FR-006 four-step precedence (first non-empty wins):

1. ``AGENTTOWER_CONTAINER_ID`` env override (used verbatim as candidate).
2. ``/proc/self/cgroup`` — every line whose last segment matches the FR-004
   closed-pattern set (cgroup v2 unified ``0::/...`` or per-subsystem v1
   lines). Per Clarifications 2026-05-06 (FR-006 multi-line rule):
   - if every matching line yields the same trailing identifier, return a
     single :class:`IdentityCandidate` with ``signal="cgroup"``;
   - if two or more matching lines yield *distinct* trailing identifiers,
     return the tuple of distinct identifiers so the cross-check classifier
     can produce ``multi_match`` with ``details.cgroup_candidates``.
3. ``/etc/hostname`` (stripped) when running inside a container.
4. ``$HOSTNAME`` env var.

All values are sanitized via ``sanitize.py`` (FR-021): NUL stripped, C0
control bytes stripped, length-bounded.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Union

from agenttower.config_doctor.runtime_detect import CGROUP_PREFIXES
from agenttower.config_doctor.sanitize import (
    ENV_VALUE_CAP,
    FILE_CONTENT_CAP,
    sanitize_text,
)

IdentitySignal = Literal["env", "cgroup", "hostname", "hostname_env"]


@dataclass(frozen=True)
class IdentityCandidate:
    """A single container-id candidate drawn from one signal."""

    candidate: str
    signal: IdentitySignal


# When step 2 (cgroup) produces multiple distinct trailing identifiers, we
# return a CgroupMultiCandidate so the classifier can emit ``multi_match``
# with ``details.cgroup_candidates``. The signal token is locked to "cgroup".
@dataclass(frozen=True)
class CgroupMultiCandidate:
    """Cgroup signal yielded multiple distinct trailing identifiers (FR-006)."""

    candidates: tuple[str, ...]  # distinct, in observed order
    signal: Literal["cgroup"] = "cgroup"


DetectResult = Union[IdentityCandidate, CgroupMultiCandidate, None]


def _resolve_proc_root(proc_root: str | None) -> Path:
    if proc_root is not None:
        return Path(proc_root)
    return Path(os.environ.get("AGENTTOWER_TEST_PROC_ROOT", "/"))


def _read_text(path: Path, max_chars: int) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            data = fh.read(max_chars + 1024)  # read a little extra so sanitize can detect overflow
    except (OSError, IOError):
        return ""
    sanitized, _ = sanitize_text(data, max_chars)
    return sanitized


def _trailing_id_from_cgroup_path(line: str) -> str | None:
    """Extract the container id from a single cgroup line (FR-006 step 2).

    Matches any of the FR-004 prefix tokens followed by ``/`` (or systemd-style
    ``-`` for ``docker-<id>.scope`` shapes), then captures the id-like trailing
    segment. The id is whatever the segment after the prefix is, up to the next
    ``/`` or end-of-line — but we keep it tight to ``[A-Za-z0-9._-]`` to avoid
    capturing systemd ``.scope`` suffixes wholesale.
    """

    # FR-006 says "the trailing identifier after the matched prefix." We scan
    # the line for the FR-004 prefix tokens and take the contiguous identifier
    # segment that follows. We strip systemd-style suffixes (".scope") because
    # those are NOT part of the container id.
    for prefix in CGROUP_PREFIXES:
        idx = line.find(prefix)
        if idx == -1:
            # Also try systemd-mangled "docker-<id>.scope" form
            mangled = prefix[:-1] + "-"
            idx2 = line.find(mangled)
            if idx2 == -1:
                continue
            after = line[idx2 + len(mangled):]
        else:
            after = line[idx + len(prefix):]

        # Take characters up to '/' or '.' (strip systemd '.scope' suffix) or whitespace
        m = re.match(r"([0-9A-Za-z][0-9A-Za-z_-]*)", after)
        if not m:
            continue
        candidate = m.group(1)
        if len(candidate) >= 8:  # meaningful container ids are at least short-id length
            return candidate
    return None


def _scan_cgroup_for_candidates(proc_root: Path) -> tuple[str, ...]:
    """Return the tuple of *distinct* trailing-id candidates from /proc/self/cgroup."""
    cgroup_path = proc_root / "proc" / "self" / "cgroup"
    seen: list[str] = []
    try:
        with cgroup_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                identifier = _trailing_id_from_cgroup_path(line)
                if identifier is None:
                    continue
                identifier_sanitized, _ = sanitize_text(identifier, FILE_CONTENT_CAP)
                if identifier_sanitized and identifier_sanitized not in seen:
                    seen.append(identifier_sanitized)
    except (OSError, IOError):
        return ()
    return tuple(seen)


def detect_candidate(
    env: Mapping[str, str],
    proc_root: str | None = None,
) -> DetectResult:
    """Run the FR-006 four-step precedence and return the first hit.

    Returns:
        :class:`IdentityCandidate` when a unique identifier is found by any step.
        :class:`CgroupMultiCandidate` when step 2 finds *multiple distinct* ids.
        ``None`` when every signal is empty.
    """

    # Step 1: env override
    env_value = env.get("AGENTTOWER_CONTAINER_ID")
    if env_value is not None:
        sanitized, _ = sanitize_text(env_value, ENV_VALUE_CAP)
        if sanitized:
            return IdentityCandidate(candidate=sanitized, signal="env")

    root = _resolve_proc_root(proc_root)

    # Step 2: cgroup scan (multi-line aware)
    cgroup_ids = _scan_cgroup_for_candidates(root)
    if len(cgroup_ids) == 1:
        return IdentityCandidate(candidate=cgroup_ids[0], signal="cgroup")
    if len(cgroup_ids) > 1:
        return CgroupMultiCandidate(candidates=cgroup_ids)

    # Step 3: /etc/hostname
    hostname_text = _read_text(root / "etc" / "hostname", FILE_CONTENT_CAP).strip()
    if hostname_text:
        return IdentityCandidate(candidate=hostname_text, signal="hostname")

    # Step 4: $HOSTNAME env var
    hostname_env = env.get("HOSTNAME")
    if hostname_env:
        sanitized, _ = sanitize_text(hostname_env.strip(), ENV_VALUE_CAP)
        if sanitized:
            return IdentityCandidate(candidate=sanitized, signal="hostname_env")

    return None


__all__ = [
    "CgroupMultiCandidate",
    "DetectResult",
    "IdentityCandidate",
    "IdentitySignal",
    "detect_candidate",
]
