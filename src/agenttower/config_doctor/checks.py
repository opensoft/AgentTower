"""Per-check functions for ``agenttower config doctor`` (FR-012, FR-016, FR-017, R-006).

Each function returns a :class:`CheckResult`. The closed-set check codes are
``socket_resolved``, ``socket_reachable``, ``daemon_status``,
``container_identity``, ``tmux_present``, ``tmux_pane_match`` (FR-012).
Each check's status is one of ``pass``, ``warn``, ``fail``, ``info``.

Per Clarifications 2026-05-06 (FR-027 reading), every check produces a
``CheckResult`` row; when an upstream gate has already failed, dependent
checks emit ``status="info"`` with sub-code ``daemon_unavailable`` and skip
the round-trip.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from agenttower.config_doctor import MAX_SUPPORTED_SCHEMA_VERSION
from agenttower.config_doctor.identity import (
    CgroupMultiCandidate,
    DetectResult,
    IdentityCandidate,
    detect_candidate,
)
from agenttower.config_doctor.runtime_detect import (
    ContainerContext,
    HostContext,
    RuntimeContext,
)
from agenttower.config_doctor.sanitize import (
    ACTIONABLE_CAP,
    DETAILS_CAP,
    sanitize_text,
)
from agenttower.config_doctor.socket_resolve import (
    ResolvedSocket,
    SocketPathInvalid,
)
from agenttower.config_doctor.tmux_identity import ParsedTmuxEnv, parse_tmux_env
from agenttower.socket_api.client import (
    DaemonError,
    DaemonUnavailable,
    send_request,
)

CheckCode = Literal[
    "socket_resolved",
    "socket_reachable",
    "daemon_status",
    "container_identity",
    "tmux_present",
    "tmux_pane_match",
]

CheckStatus = Literal["pass", "warn", "fail", "info"]


@dataclass(frozen=True)
class CheckResult:
    code: CheckCode
    status: CheckStatus
    source: str | None
    details: str
    actionable_message: str | None
    sub_code: str | None
    # Structured qualifiers per Clarifications 2026-05-06; both serialize as
    # peer keys under the ``checks.<code>`` JSON object when set.
    cgroup_candidates: tuple[str, ...] | None = None
    daemon_container_set_empty: bool | None = None


def _bound_details(text: str) -> str:
    return sanitize_text(text, DETAILS_CAP)[0]


def _bound_actionable(text: str) -> str:
    return sanitize_text(text, ACTIONABLE_CAP)[0]


# ---------------------------------------------------------------------------
# socket_resolved (FR-015)
# ---------------------------------------------------------------------------


def check_socket_resolved(resolved: ResolvedSocket) -> CheckResult:
    return CheckResult(
        code="socket_resolved",
        status="pass",
        source=resolved.source,
        details=_bound_details(f"{resolved.path} ({resolved.source})"),
        actionable_message=None,
        sub_code=None,
    )


# ---------------------------------------------------------------------------
# socket_reachable (FR-016) — transport-only per Clarifications 2026-05-06
# ---------------------------------------------------------------------------


def check_socket_reachable(
    resolved: ResolvedSocket,
) -> tuple[CheckResult, dict[str, Any] | None]:
    """Attempt one ``status`` round-trip; report transport-level outcome only.

    ``socket_reachable`` is transport-only: it reports ``pass`` whenever the
    daemon returns any well-formed frame, including a structured
    ``DaemonError`` envelope. Payload semantics are owned by ``daemon_status``.
    """

    try:
        result = send_request(
            resolved.path, "status", connect_timeout=1.0, read_timeout=1.0
        )
    except DaemonUnavailable as exc:
        actionable = _actionable_for_kind(exc.kind, resolved)
        return (
            CheckResult(
                code="socket_reachable",
                status="fail",
                source="round_trip",
                details=_bound_details(f"{exc.kind}: {resolved.path}"),
                actionable_message=actionable,
                sub_code=exc.kind,
            ),
            None,
        )
    except DaemonError as exc:
        # Daemon returned a structured error envelope — transport succeeded.
        # Bubble the DaemonError up via a sentinel dict so daemon_status can
        # report ``daemon_error``.
        sanitized_message = _bound_actionable(exc.message)
        return (
            CheckResult(
                code="socket_reachable",
                status="pass",
                source="round_trip",
                details=_bound_details("transport_ok (daemon returned an error envelope)"),
                actionable_message=None,
                sub_code=None,
            ),
            {"_daemon_error_code": exc.code, "_daemon_error_message": sanitized_message},
        )

    daemon_version = str(result.get("daemon_version", ""))
    schema_version = result.get("schema_version", "")
    return (
        CheckResult(
            code="socket_reachable",
            status="pass",
            source="round_trip",
            details=_bound_details(
                f"daemon_version={daemon_version} schema_version={schema_version}"
            ),
            actionable_message=None,
            sub_code=None,
        ),
        result,
    )


def _actionable_for_kind(kind: str, resolved: ResolvedSocket) -> str:
    if kind == "socket_missing":
        return _bound_actionable(
            f"socket file does not exist at {resolved.path}; "
            "try `agenttower ensure-daemon` from the host"
        )
    if kind == "socket_not_unix":
        return _bound_actionable(
            f"path {resolved.path} exists but is not a Unix socket"
        )
    if kind == "connection_refused":
        return _bound_actionable(
            f"daemon refused connection at {resolved.path}; the daemon may be "
            "shutting down or reaping; try `agenttower ensure-daemon`"
        )
    if kind == "permission_denied":
        return _bound_actionable(
            f"permission denied opening {resolved.path}; the in-container uid "
            "must match the host daemon uid (FEAT-005 R-001)"
        )
    if kind == "connect_timeout":
        return _bound_actionable(
            f"daemon at {resolved.path} did not respond within the timeout"
        )
    return _bound_actionable("daemon transport error")


# ---------------------------------------------------------------------------
# daemon_status (FR-017) — payload inspection
# ---------------------------------------------------------------------------


def check_daemon_status(
    status_payload: dict[str, Any] | None,
    socket_reachable_ok: bool,
) -> CheckResult:
    if not socket_reachable_ok:
        return CheckResult(
            code="daemon_status",
            status="info",
            source=None,
            details=_bound_details("daemon_unavailable"),
            actionable_message=_bound_actionable(
                "skipped because socket_reachable is fail"
            ),
            sub_code="daemon_unavailable",
        )
    assert status_payload is not None

    if "_daemon_error_code" in status_payload:
        # The transport returned a DaemonError envelope; daemon_status owns
        # this semantic outcome (Clarifications 2026-05-06 / FR-018 exit 3).
        code = str(status_payload.get("_daemon_error_code", ""))
        message = str(status_payload.get("_daemon_error_message", ""))
        return CheckResult(
            code="daemon_status",
            status="fail",
            source="daemon_error",
            details=_bound_details(f"daemon_error: {code}"),
            actionable_message=_bound_actionable(message or "daemon returned an error"),
            sub_code="daemon_error",
        )

    schema_version = status_payload.get("schema_version")
    if not isinstance(schema_version, int):
        return CheckResult(
            code="daemon_status",
            status="fail",
            source="schema_check",
            details=_bound_details("daemon did not report a numeric schema_version"),
            actionable_message=_bound_actionable("upgrade the daemon"),
            sub_code="daemon_error",
        )

    if schema_version > MAX_SUPPORTED_SCHEMA_VERSION:
        return CheckResult(
            code="daemon_status",
            status="fail",
            source="schema_check",
            details=_bound_details(
                f"schema_version={schema_version} > cli supports {MAX_SUPPORTED_SCHEMA_VERSION}"
            ),
            actionable_message=_bound_actionable(
                f"upgrade the agenttower CLI (cli supports schema "
                f"{MAX_SUPPORTED_SCHEMA_VERSION}; daemon advertises "
                f"{schema_version})"
            ),
            sub_code="schema_version_newer",
        )
    if schema_version < MAX_SUPPORTED_SCHEMA_VERSION:
        return CheckResult(
            code="daemon_status",
            status="warn",
            source="schema_check",
            details=_bound_details(
                f"schema_version={schema_version} < cli supports {MAX_SUPPORTED_SCHEMA_VERSION}"
            ),
            actionable_message=_bound_actionable(
                "daemon is older than the CLI; upgrade the daemon when convenient"
            ),
            sub_code="schema_version_older",
        )

    daemon_version = str(status_payload.get("daemon_version", ""))
    return CheckResult(
        code="daemon_status",
        status="pass",
        source="schema_check",
        details=_bound_details(
            f"schema_version={schema_version} (cli supports {MAX_SUPPORTED_SCHEMA_VERSION}); "
            f"daemon_version={daemon_version}"
        ),
        actionable_message=None,
        sub_code=None,
    )


# ---------------------------------------------------------------------------
# container_identity (FR-006, FR-007) — Phase 5 stub-then-real
# ---------------------------------------------------------------------------


def check_container_identity(
    env: Mapping[str, str],
    runtime_context: RuntimeContext,
    list_containers_payload: dict[str, Any] | None,
    socket_reachable_ok: bool,
) -> CheckResult:
    if not socket_reachable_ok:
        return CheckResult(
            code="container_identity",
            status="info",
            source=None,
            details=_bound_details("daemon_unavailable"),
            actionable_message=_bound_actionable(
                "skipped because socket_reachable is fail; "
                "run `agenttower ensure-daemon` from the host"
            ),
            sub_code="daemon_unavailable",
        )

    # FR-007 host_context: when the runtime is HostContext AND
    # AGENTTOWER_CONTAINER_ID is unset, we report host_context regardless of
    # whether /etc/hostname or $HOSTNAME produced a candidate. The hostname
    # signals are FR-006 fallbacks meant for in-container disambiguation;
    # firing them on the host shell would drag every host invocation into
    # `no_match` territory, which is not the spec's intent.
    if (
        isinstance(runtime_context, HostContext)
        and env.get("AGENTTOWER_CONTAINER_ID") is None
    ):
        return CheckResult(
            code="container_identity",
            status="info",
            source=None,
            details=_bound_details("host_context"),
            actionable_message=None,
            sub_code="host_context",
        )

    candidate = detect_candidate(env)
    rows: tuple[dict[str, Any], ...] = tuple(
        list_containers_payload.get("containers", []) if list_containers_payload else []
    )
    daemon_set_empty = len(rows) == 0

    return classify_identity_to_check_result(
        candidate=candidate,
        runtime_context=runtime_context,
        list_containers_rows=rows,
        daemon_set_empty=daemon_set_empty,
    )


def classify_identity_to_check_result(
    *,
    candidate: DetectResult,
    runtime_context: RuntimeContext,
    list_containers_rows: tuple[dict[str, Any], ...],
    daemon_set_empty: bool,
) -> CheckResult:
    """T048 / FR-007 closed-set classifier (Phase 5).

    Closed-set outcomes ``unique_match``, ``multi_match``, ``no_match``,
    ``no_candidate``, ``host_context``. The synonym ``not_in_container`` is
    dead per Clarifications 2026-05-06 (only ``host_context`` is emitted).
    The empty-``list_containers`` case is signalled by
    ``daemon_container_set_empty=True`` plus ``no_candidate`` / ``no_match``;
    no ``no_containers_known`` sub-code is added.
    """

    actionable_scan = "run `agenttower scan --containers` from the host"

    # multi_match from cgroup multi-line rule (Q4)
    if isinstance(candidate, CgroupMultiCandidate):
        return CheckResult(
            code="container_identity",
            status="fail",
            source="cgroup",
            details=_bound_details(
                "multi_match: distinct cgroup ids in /proc/self/cgroup: "
                + ", ".join(candidate.candidates)
            ),
            actionable_message=_bound_actionable(
                "the cgroup file contains multiple matching lines with "
                "different container ids; the doctor will not pick one"
            ),
            sub_code="multi_match",
            cgroup_candidates=candidate.candidates,
        )

    if candidate is None:
        # host_context only when both the runtime is host AND no env override.
        if isinstance(runtime_context, HostContext):
            return CheckResult(
                code="container_identity",
                status="info",
                source=None,
                details=_bound_details("host_context"),
                actionable_message=None,
                sub_code="host_context",
            )
        # Runtime is container but every signal returned empty.
        return CheckResult(
            code="container_identity",
            status="fail",
            source=None,
            details=_bound_details(
                "no_candidate: every detection signal returned empty"
            ),
            actionable_message=_bound_actionable(
                f"no in-container signal fired; {actionable_scan}"
            ),
            sub_code="no_candidate",
            daemon_container_set_empty=daemon_set_empty if daemon_set_empty else None,
        )

    assert isinstance(candidate, IdentityCandidate)
    cand_str = candidate.candidate
    sig = candidate.signal

    # full-id equality first
    full_matches = [r for r in list_containers_rows if str(r.get("id", "")) == cand_str]
    if len(full_matches) == 1:
        row = full_matches[0]
        return CheckResult(
            code="container_identity",
            status="pass",
            source=sig,
            details=_bound_details(
                f"unique_match: {row.get('id', '')} ({row.get('name', '')})"
            ),
            actionable_message=None,
            sub_code="unique_match",
        )
    if len(full_matches) > 1:
        ids = [str(r.get("id", "")) for r in full_matches]
        return CheckResult(
            code="container_identity",
            status="fail",
            source=sig,
            details=_bound_details("multi_match: " + ", ".join(ids)),
            actionable_message=_bound_actionable(
                "more than one container row matches the candidate full id"
            ),
            sub_code="multi_match",
        )

    # 12-character short-id prefix match
    short_prefix = cand_str[:12] if len(cand_str) >= 12 else cand_str
    short_matches = [
        r
        for r in list_containers_rows
        if str(r.get("id", "")).startswith(short_prefix) and len(short_prefix) == 12
    ]
    if len(short_matches) == 1:
        row = short_matches[0]
        return CheckResult(
            code="container_identity",
            status="pass",
            source=sig,
            details=_bound_details(
                f"unique_match: {row.get('id', '')} ({row.get('name', '')})"
            ),
            actionable_message=None,
            sub_code="unique_match",
        )
    if len(short_matches) > 1:
        ids = [str(r.get("id", "")) for r in short_matches]
        return CheckResult(
            code="container_identity",
            status="fail",
            source=sig,
            details=_bound_details(
                "multi_match: " + ", ".join(ids) + f" (candidate prefix={short_prefix})"
            ),
            actionable_message=_bound_actionable(
                "two or more container rows share the candidate's 12-char prefix; "
                "the doctor will not pick one"
            ),
            sub_code="multi_match",
        )

    # no_match: candidate produced but no row matches.
    return CheckResult(
        code="container_identity",
        status="fail",
        source=sig,
        details=_bound_details(f"no_match: {cand_str} ({sig})"),
        actionable_message=_bound_actionable(actionable_scan),
        sub_code="no_match",
        daemon_container_set_empty=daemon_set_empty if daemon_set_empty else None,
    )


# ---------------------------------------------------------------------------
# tmux_present (FR-009, FR-010)
# ---------------------------------------------------------------------------


def check_tmux_present(env: Mapping[str, str]) -> tuple[CheckResult, ParsedTmuxEnv]:
    parsed = parse_tmux_env(env)

    if not parsed.in_tmux:
        return (
            CheckResult(
                code="tmux_present",
                status="info",
                source=None,
                details=_bound_details("not_in_tmux"),
                actionable_message=None,
                sub_code="not_in_tmux",
            ),
            parsed,
        )

    if parsed.malformed_reason is not None:
        return (
            CheckResult(
                code="tmux_present",
                status="fail",
                source="env",
                details=_bound_details(f"output_malformed: {parsed.malformed_reason}"),
                actionable_message=_bound_actionable(
                    "$TMUX or $TMUX_PANE is malformed; check your tmux config"
                ),
                sub_code="output_malformed",
            ),
            parsed,
        )

    return (
        CheckResult(
            code="tmux_present",
            status="pass",
            source="env",
            details=_bound_details(
                f"socket={parsed.tmux_socket_path} session={parsed.session_id} "
                f"pane={parsed.tmux_pane_id}"
            ),
            actionable_message=None,
            sub_code=None,
        ),
        parsed,
    )


# ---------------------------------------------------------------------------
# tmux_pane_match (FR-010) — daemon cross-check
# ---------------------------------------------------------------------------


def check_tmux_pane_match(
    parsed: ParsedTmuxEnv,
    list_panes_payload: dict[str, Any] | None,
    socket_reachable_ok: bool,
) -> CheckResult:
    # Post-clarify FR-027: when the daemon transport path is already known to
    # be unavailable, this dependent check still emits a row but short-circuits
    # to daemon_unavailable rather than reporting a local tmux-only outcome.
    # tmux_present carries the local not_in_tmux signal separately.
    if not socket_reachable_ok:
        return CheckResult(
            code="tmux_pane_match",
            status="info",
            source=None,
            details=_bound_details("daemon_unavailable"),
            actionable_message=_bound_actionable(
                "skipped because socket_reachable is fail"
            ),
            sub_code="daemon_unavailable",
        )

    if not parsed.in_tmux:
        return CheckResult(
            code="tmux_pane_match",
            status="info",
            source=None,
            details=_bound_details("not_in_tmux"),
            actionable_message=None,
            sub_code="not_in_tmux",
        )

    if parsed.malformed_reason is not None:
        # tmux_present already flagged output_malformed; propagate.
        return CheckResult(
            code="tmux_pane_match",
            status="info",
            source=None,
            details=_bound_details("skipped: tmux env malformed"),
            actionable_message=None,
            sub_code="not_in_tmux",
        )


    rows: list[dict[str, Any]] = list(
        list_panes_payload.get("panes", []) if list_panes_payload else []
    )
    matches = [
        r
        for r in rows
        if str(r.get("tmux_socket_path", "")) == parsed.tmux_socket_path
        and str(r.get("tmux_pane_id", "")) == parsed.tmux_pane_id
    ]

    if len(matches) == 1:
        row = matches[0]
        return CheckResult(
            code="tmux_pane_match",
            status="pass",
            source="list_panes",
            details=_bound_details(
                f"pane_match: {row.get('tmux_pane_id', '')} in "
                f"{row.get('container_id', '')}:{row.get('tmux_session_name', '')}"
            ),
            actionable_message=None,
            sub_code="pane_match",
        )
    if len(matches) > 1:
        return CheckResult(
            code="tmux_pane_match",
            status="fail",
            source="list_panes",
            details=_bound_details(
                f"pane_ambiguous: {len(matches)} panes match "
                f"{parsed.tmux_socket_path}:{parsed.tmux_pane_id}"
            ),
            actionable_message=_bound_actionable(
                "more than one pane row matches; the doctor will not pick one"
            ),
            sub_code="pane_ambiguous",
        )

    return CheckResult(
        code="tmux_pane_match",
        status="fail",
        source="list_panes",
        details=_bound_details(
            f"pane_unknown_to_daemon: {parsed.tmux_socket_path}:{parsed.tmux_pane_id}"
        ),
        actionable_message=_bound_actionable(
            "no pane row matches; run `agenttower scan --panes` from the host"
        ),
        sub_code="pane_unknown_to_daemon",
    )


__all__ = [
    "CheckCode",
    "CheckResult",
    "CheckStatus",
    "check_container_identity",
    "check_daemon_status",
    "check_socket_reachable",
    "check_socket_resolved",
    "check_tmux_pane_match",
    "check_tmux_present",
    "classify_identity_to_check_result",
]
