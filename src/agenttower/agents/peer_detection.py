"""FEAT-013 H1 fix — bench-container peer resolution.

Background
==========

The FEAT-013 legacy ``managed.*`` namespace is reachable from both the
host CLI and from bench-container thin clients (over the mounted Unix
socket). R12 says a bench-container peer MAY only target managed
resources in *its own* container — it cannot create or recreate panes
in another bench container.

The handler layer enforces this with:

    peer_container = _peer_container_id(ctx, peer_uid)
    if peer_container is not None and target.container_id != peer_container:
        return host_only

Before this module existed, ``_peer_container_id`` tried to import
``agents.peer_detection.resolve_peer_container_id``; the
``ImportError`` branch silently returned ``None`` and the handler then
treated the caller as a host peer. A bench peer that survived
FEAT-002's accept-time host detector (e.g. ``AGENTTOWER_TEST_FORCE_HOST_PEER=1``
in tests, or any container missing ``/.dockerenv`` / cgroup markers)
gained unscoped cross-container access. That is the H1 finding from
the deep-review swarm pass.

This module closes the gap.

Behavior
========

``resolve_peer_container_id(pid)`` returns:

- ``None`` when the peer is *verifiably the daemon's host* — proven by
  the same negative-signal heuristics ``_peer_is_host_process`` uses
  (no ``/proc/<pid>/root/.dockerenv``, no ``/proc/<pid>/root/run/.containerenv``,
  no cgroup line containing a documented container prefix). Handlers
  read ``None`` as "host peer, allow cross-container".
- A *non-empty string* when the peer is verifiably in a bench
  container AND AgentTower can identify which one. Identification uses
  the **kernel-derived cgroup hash** read from ``/proc/<pid>/cgroup``
  (set by the container runtime, NOT writable by the container), which
  is then canonicalized against the FEAT-003 container registry via the
  injected ``container_matcher``. The container's own ``/etc/hostname``
  is **deliberately NOT trusted** as identity: it is fully
  attacker-controlled (``docker run --hostname <victim>``), so trusting
  it would let a hostile bench impersonate another container and defeat
  the R12 cross-container gate.
- :data:`UNRESOLVED_PEER` (== ``"<unresolved>"``) when the peer is in a
  container but its identity could not be derived. Handlers compare
  this sentinel against the target ``container_id`` and the
  inequality denies cross-container access. This is the fail-closed
  default — *never* fall through to a host-equivalent result on
  uncertain peers.

Test seam
=========

The ``AGENTTOWER_TEST_FORCE_HOST_PEER=1`` env-var honored by
:func:`socket_api.methods._peer_is_host_process` is honored here too:
when set, this resolver returns ``None`` (host) regardless of any
container markers. That keeps the integration test suite — which runs
inside container-shaped CI sandboxes — symmetric with the FEAT-011
host-only gate it already uses.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Final, Optional

# A matcher mapping a raw, kernel-derived container id (the cgroup hash,
# 12- or 64-char hex) to the canonical ``container_id`` recorded in the
# FEAT-003 registry, or ``None`` when it does not uniquely match a
# registered container. The handler builds this from the live registry
# so the daemon never trusts an attacker-suppliable identity string.
ContainerMatcher = Callable[[str], Optional[str]]


# Sentinel returned when the peer is in a container but the
# container's identity cannot be derived. String form chosen so the
# inequality check in handlers (``predecessor.container_id != peer_container``)
# fails closed — no real bench container_id will ever match this
# string per FR-016 charset rules (forbidden characters ``<>``).
UNRESOLVED_PEER: Final[str] = "<unresolved>"


# Cgroup line patterns we recognize as "this pid is in a container".
# Kept in sync with :data:`config_doctor.runtime_detect.CGROUP_PREFIXES`
# at the time of writing.
_CGROUP_CONTAINER_PREFIXES: Final[tuple[str, ...]] = (
    "/docker/",
    "/docker-",
    "docker-",
    "/system.slice/docker-",
    "/podman/",
    "/lxc/",
    "/kubepods/",
)

# Docker container id hashes are 12 or 64 hex chars; we accept either.
# Extracted from cgroup lines like:
#   0::/system.slice/docker-<64hex>.scope
#   12:devices:/docker/<64hex>
_CGROUP_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:docker[-/]|/docker/|/system\.slice/docker-)([0-9a-f]{12,64})"
)


def resolve_peer_container_id(
    pid: int,
    *,
    container_matcher: Optional[ContainerMatcher] = None,
) -> Optional[str]:
    """Resolve the bench container_id (if any) for the AF_UNIX peer pid.

    Returns ``None`` for verified host peers; the canonical registry
    ``container_id`` for a container peer whose kernel-derived cgroup
    hash uniquely matches a registered container; or
    :data:`UNRESOLVED_PEER` for container peers whose id could not be
    derived or did not uniquely match a registered container. See module
    docstring for full semantics.

    ``container_matcher`` maps the raw cgroup hash to the canonical
    registry ``container_id`` (or ``None`` on no/ambiguous match). When
    omitted (legacy callers / unit tests without a registry) the raw
    cgroup hash is returned as a best-effort fallback — production
    callers MUST pass a matcher so the returned id is registry-verified.
    """
    if pid is None or pid <= 0:
        # No peer pid — caller couldn't even read the credentials. Fail
        # closed by returning the unresolved sentinel; cross-container
        # checks will deny.
        return UNRESOLVED_PEER

    if os.environ.get("AGENTTOWER_TEST_FORCE_HOST_PEER") == "1":
        # Mirror :func:`_peer_is_host_process`'s test seam so the
        # integration suite (which sets this in the daemon env) sees
        # the resolver return ``None`` — i.e. "host peer".
        return None

    proc_dir = Path("/proc") / str(pid)
    root_dir = proc_dir / "root"

    # --- Stage 1: container-marker probes ------------------------------
    in_container = False
    try:
        if (root_dir / ".dockerenv").exists():
            in_container = True
        elif (root_dir / "run" / ".containerenv").exists():
            in_container = True
    except OSError:
        # Can't read /proc/<pid>/root at all — most commonly because
        # the pid exited or we lack the privilege. Fail closed.
        return UNRESOLVED_PEER

    cgroup_id: Optional[str] = None
    cgroup_path = proc_dir / "cgroup"
    try:
        with cgroup_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if any(prefix in line for prefix in _CGROUP_CONTAINER_PREFIXES):
                    in_container = True
                    match = _CGROUP_ID_RE.search(line)
                    if match is not None:
                        cgroup_id = match.group(1)
                        # First match wins — Docker/containerd lines
                        # typically appear in the v1 group entries and
                        # the v2 unified hierarchy after. Either is
                        # fine for identification.
                        break
    except OSError:
        if not in_container:
            # No cgroup file AND no .dockerenv → most likely the pid is
            # gone. Fail closed.
            return UNRESOLVED_PEER

    if not in_container:
        # Verified host peer.
        return None

    # --- Stage 2: container-id resolution ------------------------------
    # The ONLY trusted identity source is the kernel-derived cgroup hash
    # (set by the container runtime, not writable from inside the
    # container). ``/etc/hostname`` is intentionally NOT consulted: it is
    # attacker-controlled and trusting it would let a hostile bench set
    # ``--hostname <victim_id>`` and impersonate another container,
    # defeating the R12 gate. With no cgroup hash there is no unspoofable
    # identity, so we fail closed.
    if not cgroup_id:
        return UNRESOLVED_PEER

    if container_matcher is None:
        # No registry to canonicalize against (legacy / unit tests).
        # Return the raw hash best-effort; production passes a matcher.
        return cgroup_id

    canonical = container_matcher(cgroup_id)
    # No / ambiguous registry match → fail closed.
    return canonical if canonical else UNRESOLVED_PEER


__all__ = ["resolve_peer_container_id", "UNRESOLVED_PEER", "ContainerMatcher"]
