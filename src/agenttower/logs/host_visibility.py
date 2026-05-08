"""FR-007 / FR-050 / FR-056 / FR-063 host-visibility proof.

Walks the bound container's persisted ``Mounts`` JSON (FEAT-003) and proves
that the container-side log path lies under a bind/volume mount whose
host-side Source resolves on the host filesystem AND whose realpath does
NOT escape the resolved Source root (symlink-escape defense, FR-050).

Returns a dataclass carrying both the host-side path AND the container-side
path so the daemon's `tmux pipe-pane` shell construction can write the
container-side path verbatim while the daemon's mode invariants apply to
the host-side path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LogPathNotHostVisible(Exception):
    """Raised when the FR-007 / FR-050 / FR-056 host-visibility proof fails."""


# FR-063: hard cap on mount entries to defend against mount-list bombing.
MAX_MOUNT_ENTRIES = 256
# FR-056: max realpath chain depth when resolving a chained bind mount Source.
MAX_REALPATH_HOPS = 8


@dataclass(frozen=True)
class HostVisibilityProof:
    host_path: str
    """Realpath-resolved host-side path."""

    container_path: str
    """Container-side path (the shell will write to this via pipe-pane)."""

    mount_destination: str
    """The matched mount's container-side ``Destination`` prefix."""

    mount_source: str
    """The matched mount's host-side ``Source`` (realpath-resolved)."""


def _parse_mounts(mounts_json: str) -> list[dict[str, Any]]:
    """Parse ``containers.mounts_json`` into a list of mount dicts."""
    try:
        data = json.loads(mounts_json)
    except json.JSONDecodeError as exc:
        raise LogPathNotHostVisible(
            f"containers.mounts_json is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, list):
        raise LogPathNotHostVisible(
            "containers.mounts_json must be a JSON array"
        )
    if len(data) > MAX_MOUNT_ENTRIES:
        # FR-063: cap; caller is responsible for emitting the lifecycle event.
        raise LogPathNotHostVisible(
            f"containers.mounts_json has {len(data)} entries; max {MAX_MOUNT_ENTRIES} (FR-063)"
        )
    return data


def _resolve_source_realpath(source: str) -> str:
    """Resolve a mount Source through up to MAX_REALPATH_HOPS hops (FR-056).

    ``os.path.realpath`` already follows symlinks transitively — it raises
    ``OSError`` on Linux when an internal cycle is detected. The hop counter
    here defends against pathological symlink/mount chains where the resolved
    path itself names another symlink the daemon would have to follow
    explicitly. Stable convergence (resolved == current) terminates early.
    """
    visited: set[str] = set()
    current = source
    for _ in range(MAX_REALPATH_HOPS):
        try:
            resolved = os.path.realpath(current)
        except OSError as exc:
            # Linux raises ELOOP on a cycle.
            raise LogPathNotHostVisible(
                f"mount Source {source!r} could not be realpath-resolved: {exc}"
            ) from exc
        if resolved == current:
            return resolved
        if resolved in visited:
            raise LogPathNotHostVisible(
                f"mount Source {source!r} resolves through a cycle"
            )
        visited.add(current)
        current = resolved
    raise LogPathNotHostVisible(
        f"mount Source {source!r} exceeds {MAX_REALPATH_HOPS} realpath hops (FR-056)"
    )


def _is_under(path: str, root: str) -> bool:
    """Return True iff ``path`` lies under (or equals) ``root`` lexically."""
    if path == root:
        return True
    return path.startswith(root.rstrip("/") + "/")


def prove_host_visible(
    container_mounts_json: str,
    container_side_path: str,
    *,
    require_writable: bool = True,
) -> HostVisibilityProof:
    """Prove ``container_side_path`` is host-visible via the bound container's mounts.

    Algorithm (Research R-004 + FR-007 + FR-050 + FR-056 + FR-063):
    1. Parse the cached ``Mounts`` JSON; cap at MAX_MOUNT_ENTRIES.
    2. Filter to ``Type ∈ {bind, volume}``.
    3. For each candidate, test whether ``container_side_path`` lies under
       ``mount["Destination"]`` (deepest-prefix-wins).
    4. Compute ``host_side = mount["Source"] + relative_suffix``.
    5. Resolve through up to ``MAX_REALPATH_HOPS`` realpath hops (FR-056).
    6. Verify the resolved path stays under the resolved Source root (FR-050
       symlink-escape defense).
    7. If ``require_writable``: verify the daemon has write access to the
       resolved Source (FR-007 attach surfaces; preview surfaces use False).

    Raises :class:`LogPathNotHostVisible` on any failure with an actionable
    message. On success returns the proof dataclass.
    """
    if not container_side_path.startswith("/"):
        raise LogPathNotHostVisible(
            f"container_side_path must be absolute; got {container_side_path!r}"
        )

    mounts = _parse_mounts(container_mounts_json)
    candidates: list[tuple[int, dict[str, Any]]] = []
    for mount in mounts:
        if not isinstance(mount, dict):
            continue
        # Accept both Docker-API ``Type``/``Source``/``Destination`` casing
        # AND the lowercase ``type``/``source``/``target`` shape FEAT-003
        # persists into ``containers.mounts_json``. Either side may surface
        # depending on test fixture vs. cached scan output.
        mount_type = mount.get("Type") or mount.get("type")
        if mount_type not in ("bind", "volume"):
            continue
        destination = mount.get("Destination") or mount.get("target")
        source = mount.get("Source") or mount.get("source")
        if not isinstance(destination, str) or not isinstance(source, str):
            continue
        if not destination.startswith("/") or not source.startswith("/"):
            continue
        if _is_under(container_side_path, destination):
            candidates.append((len(destination), mount))

    if not candidates:
        # Surface the observed mount destinations so the operator can compare
        # their bench template against the path the daemon expected. Without
        # this hint, a destination drift (e.g. bench mounts /var/log instead
        # of $HOME/.local/state/...) silently surfaces as a closed-set rejection.
        observed = sorted(
            {
                str(m.get("Destination") or m.get("target"))
                for m in mounts
                if isinstance(m, dict)
                and (m.get("Destination") or m.get("target"))
            }
        )
        observed_repr = ", ".join(observed) if observed else "(none)"
        raise LogPathNotHostVisible(
            f"no bind/volume mount covers container path {container_side_path!r}; "
            f"observed mount destinations in this container: {observed_repr}. "
            f"The bench container template must mount the canonical log "
            f"directory at the requested destination."
        )

    # Deepest-prefix-wins.
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    _, mount = candidates[0]
    destination_raw = mount.get("Destination") or mount.get("target")
    source_raw = mount.get("Source") or mount.get("source")
    destination = str(destination_raw).rstrip("/") or "/"
    source = str(source_raw).rstrip("/") or "/"

    if container_side_path == destination:
        relative = ""
    else:
        relative = container_side_path[len(destination):]
        if not relative.startswith("/"):
            relative = "/" + relative

    raw_host_path = source + relative
    resolved_source = _resolve_source_realpath(source)
    resolved_host_path = os.path.realpath(raw_host_path)

    # FR-050: refuse if realpath escapes the resolved Source root.
    if not _is_under(resolved_host_path, resolved_source):
        raise LogPathNotHostVisible(
            f"resolved host path {resolved_host_path!r} escapes mount Source root "
            f"{resolved_source!r} via symlink (FR-050)"
        )

    # FR-007: parent must exist on the host filesystem; daemon will create
    # the directory + file with the right modes later.
    parent = os.path.dirname(resolved_host_path) or "/"
    if not os.path.isdir(parent):
        # The canonical log directory may not yet exist — allow if the
        # higher-up Source root exists, daemon creates the subtree under
        # FR-008.
        if not os.path.isdir(resolved_source):
            raise LogPathNotHostVisible(
                f"resolved Source root {resolved_source!r} does not exist on host"
            )

    if require_writable:
        # The daemon must be able to write under the Source root (FR-007).
        if not os.access(resolved_source, os.W_OK):
            raise LogPathNotHostVisible(
                f"resolved Source root {resolved_source!r} is not writable by the daemon"
            )

    return HostVisibilityProof(
        host_path=resolved_host_path,
        container_path=container_side_path,
        mount_destination=destination,
        mount_source=resolved_source,
    )
