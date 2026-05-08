"""Client-side identity + pane resolution for ``agenttower register-self``.

Reuses FEAT-005 in-container identity (``runtime_detect`` + ``identity``)
and tmux self-identity (``tmux_identity``) to determine the caller's
container_id and tmux pane composite key. Cross-checks against the
FEAT-003 container registry (via ``list_containers``) and the FEAT-004
pane registry (via ``list_panes``) over the daemon socket.

On a pane miss, triggers exactly one focused FEAT-004 rescan scoped to
the caller's container (FR-041). After the rescan, if the pane is still
absent or ``active=false``, refuses with closed-set
``pane_unknown_to_daemon``.

Maps every failure to the FEAT-006 closed-set error code surface:

* ``host_context_unsupported``  — caller is on the host shell.
* ``container_unresolved``      — ``no_match`` / ``no_candidate`` / ``multi_match``.
* ``not_in_tmux``               — ``$TMUX`` unset.
* ``tmux_pane_malformed``       — ``$TMUX_PANE`` malformed.
* ``pane_unknown_to_daemon``    — pane absent after focused rescan.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config_doctor import identity as cd_identity
from ..config_doctor import runtime_detect, tmux_identity
from ..socket_api.client import send_request
from .errors import RegistrationError
from .mutex import PaneCompositeKey


@dataclass(frozen=True)
class ResolvedAgentTarget:
    """Result of :func:`resolve_pane_composite_key` — the inputs the daemon
    needs to register the agent."""

    container_id: str
    pane_key: PaneCompositeKey


def resolve_pane_composite_key(
    *,
    socket_path: Path,
    env: Mapping[str, str],
    proc_root: str | None = None,
    connect_timeout: float = 1.0,
    read_timeout: float = 5.0,
) -> ResolvedAgentTarget:
    """Resolve the caller's container_id + pane composite key.

    *socket_path* is the resolved daemon socket. *env* is the CLI process
    environment (a mapping; tests pass a synthetic dict). *proc_root* is
    the ``AGENTTOWER_TEST_PROC_ROOT`` override threaded through
    consistently with FEAT-005 (T-005 review fix).

    On any failure, raises :class:`RegistrationError` carrying the
    matching closed-set wire code.
    """
    # 1. Runtime detection — refuse host context.
    runtime = runtime_detect.detect(proc_root=proc_root)
    if isinstance(runtime, runtime_detect.HostContext):
        raise RegistrationError(
            "host_context_unsupported",
            "register-self requires running inside a bench container; "
            "FEAT-006 MVP does not register host-only panes",
        )

    # 2. Identity detection (FR-006 four-step precedence).
    candidate = cd_identity.detect_candidate(env, proc_root=proc_root)
    if candidate is None:
        raise RegistrationError(
            "container_unresolved",
            "no container identity signal (env, cgroup, hostname, $HOSTNAME); "
            "run `agenttower scan --containers` from the host",
        )
    if isinstance(candidate, cd_identity.CgroupMultiCandidate):
        raise RegistrationError(
            "container_unresolved",
            f"cgroup yielded multiple distinct identifiers: {list(candidate.candidates)}; "
            "run `agenttower scan --containers` from the host",
        )

    # 3. Cross-check against FEAT-003 container registry.
    candidate_value = candidate.candidate
    matched_id = _match_container(
        socket_path=socket_path,
        candidate=candidate_value,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )

    # 4. Parse $TMUX / $TMUX_PANE.
    parsed = tmux_identity.parse_tmux_env(env)
    if not parsed.in_tmux:
        raise RegistrationError(
            "not_in_tmux",
            "$TMUX is unset; run register-self from inside an active tmux pane",
        )
    if parsed.malformed_reason is not None:
        raise RegistrationError(
            "tmux_pane_malformed",
            parsed.malformed_reason,
        )
    if not parsed.pane_id_valid:
        raise RegistrationError(
            "tmux_pane_malformed",
            "$TMUX_PANE does not match the %N shape",
        )

    assert parsed.tmux_socket_path is not None
    assert parsed.tmux_pane_id is not None

    # 5. Find the pane composite key in FEAT-004 panes for this container.
    pane_key = _find_pane(
        socket_path=socket_path,
        container_id=matched_id,
        tmux_socket_path=parsed.tmux_socket_path,
        tmux_pane_id=parsed.tmux_pane_id,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )
    if pane_key is None:
        # FR-041 focused rescan — exactly one, scoped to the resolved
        # container — then re-query.
        send_request(
            socket_path,
            "scan_panes",
            {"container": matched_id},
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )
        pane_key = _find_pane(
            socket_path=socket_path,
            container_id=matched_id,
            tmux_socket_path=parsed.tmux_socket_path,
            tmux_pane_id=parsed.tmux_pane_id,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )
        if pane_key is None:
            raise RegistrationError(
                "pane_unknown_to_daemon",
                f"pane {parsed.tmux_pane_id} not found in container {matched_id}; "
                "run `agenttower scan --panes` from the host",
            )

    return ResolvedAgentTarget(container_id=matched_id, pane_key=pane_key)


def _match_container(
    *,
    socket_path: Path,
    candidate: str,
    connect_timeout: float,
    read_timeout: float,
) -> str:
    """Match the candidate identifier against the FEAT-003 container registry.

    Accepts the candidate as a full id, 12-char short prefix, or
    container name. Returns the full container_id on success; raises
    ``container_unresolved`` on no-match, no-candidate, or multi-match.
    """
    result = send_request(
        socket_path,
        "list_containers",
        {"active_only": True},
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )
    containers = result.get("containers", [])
    matches: list[str] = []
    for c in containers:
        cid = c.get("id", "")
        name = c.get("name", "")
        if cid == candidate:
            matches.append(cid)
        elif candidate and len(candidate) >= 12 and cid.startswith(candidate):
            matches.append(cid)
        elif name == candidate:
            matches.append(cid)
    # De-duplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            deduped.append(m)
    if len(deduped) == 0:
        raise RegistrationError(
            "container_unresolved",
            f"candidate {candidate!r} did not match any active bench container; "
            "run `agenttower scan --containers` from the host",
        )
    if len(deduped) > 1:
        raise RegistrationError(
            "container_unresolved",
            f"candidate {candidate!r} matched {len(deduped)} active containers; "
            "set AGENTTOWER_CONTAINER_ID to disambiguate",
        )
    return deduped[0]


def _find_pane(
    *,
    socket_path: Path,
    container_id: str,
    tmux_socket_path: str,
    tmux_pane_id: str,
    connect_timeout: float,
    read_timeout: float,
) -> PaneCompositeKey | None:
    """Look up the pane composite key in the FEAT-004 registry.

    The match key is ``(container_id, tmux_socket_path, tmux_pane_id)``;
    the FEAT-004 list_panes response includes session/window/pane index
    so we recover the full six-tuple. Returns ``None`` if no row matches
    or if the matching row is ``active=false`` (caller triggers the
    FR-041 focused rescan in that case).
    """
    result = send_request(
        socket_path,
        "list_panes",
        {"active_only": False, "container": container_id},
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )
    panes = result.get("panes", [])
    for p in panes:
        if p.get("container_id") != container_id:
            continue
        if p.get("tmux_socket_path") != tmux_socket_path:
            continue
        if p.get("tmux_pane_id") != tmux_pane_id:
            continue
        if not p.get("active"):
            return None
        return (
            p["container_id"],
            p["tmux_socket_path"],
            p["tmux_session_name"],
            int(p["tmux_window_index"]),
            int(p["tmux_pane_index"]),
            p["tmux_pane_id"],
        )
    return None
