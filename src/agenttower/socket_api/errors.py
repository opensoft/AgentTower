"""Error code constants and JSON envelope helpers for the local control API.

Per FEAT-002 research R-014, FEAT-002 ships a closed five-token error code set.
Adding a new code is a spec amendment.
"""

from __future__ import annotations

from typing import Any, Final

# Closed code set (FEAT-002).
BAD_JSON: Final[str] = "bad_json"
BAD_REQUEST: Final[str] = "bad_request"
UNKNOWN_METHOD: Final[str] = "unknown_method"
REQUEST_TOO_LARGE: Final[str] = "request_too_large"
INTERNAL_ERROR: Final[str] = "internal_error"

# FEAT-003 additions (research R-014).
CONFIG_INVALID: Final[str] = "config_invalid"
DOCKER_UNAVAILABLE: Final[str] = "docker_unavailable"
DOCKER_PERMISSION_DENIED: Final[str] = "docker_permission_denied"
DOCKER_TIMEOUT: Final[str] = "docker_timeout"
DOCKER_FAILED: Final[str] = "docker_failed"
DOCKER_MALFORMED: Final[str] = "docker_malformed"

# FEAT-004 additions (research R-011).
TMUX_UNAVAILABLE: Final[str] = "tmux_unavailable"
TMUX_NO_SERVER: Final[str] = "tmux_no_server"
SOCKET_DIR_MISSING: Final[str] = "socket_dir_missing"
SOCKET_UNREADABLE: Final[str] = "socket_unreadable"
DOCKER_EXEC_FAILED: Final[str] = "docker_exec_failed"
DOCKER_EXEC_TIMEOUT: Final[str] = "docker_exec_timeout"
OUTPUT_MALFORMED: Final[str] = "output_malformed"
BENCH_USER_UNRESOLVED: Final[str] = "bench_user_unresolved"

# FEAT-006 additions (research R-010 / FR-040).
HOST_CONTEXT_UNSUPPORTED: Final[str] = "host_context_unsupported"
CONTAINER_UNRESOLVED: Final[str] = "container_unresolved"
NOT_IN_TMUX: Final[str] = "not_in_tmux"
TMUX_PANE_MALFORMED: Final[str] = "tmux_pane_malformed"
PANE_UNKNOWN_TO_DAEMON: Final[str] = "pane_unknown_to_daemon"
AGENT_NOT_FOUND: Final[str] = "agent_not_found"
AGENT_INACTIVE: Final[str] = "agent_inactive"
PARENT_NOT_FOUND: Final[str] = "parent_not_found"
PARENT_INACTIVE: Final[str] = "parent_inactive"
PARENT_ROLE_INVALID: Final[str] = "parent_role_invalid"
PARENT_ROLE_MISMATCH: Final[str] = "parent_role_mismatch"
PARENT_IMMUTABLE: Final[str] = "parent_immutable"
SWARM_PARENT_REQUIRED: Final[str] = "swarm_parent_required"
SWARM_ROLE_VIA_SET_ROLE_REJECTED: Final[str] = "swarm_role_via_set_role_rejected"
MASTER_VIA_REGISTER_SELF_REJECTED: Final[str] = "master_via_register_self_rejected"
MASTER_CONFIRM_REQUIRED: Final[str] = "master_confirm_required"
VALUE_OUT_OF_SET: Final[str] = "value_out_of_set"
FIELD_TOO_LONG: Final[str] = "field_too_long"
PROJECT_PATH_INVALID: Final[str] = "project_path_invalid"
UNKNOWN_FILTER: Final[str] = "unknown_filter"
SCHEMA_VERSION_NEWER: Final[str] = "schema_version_newer"

# FEAT-007 additions (FR-038).
LOG_PATH_INVALID: Final[str] = "log_path_invalid"
LOG_PATH_NOT_HOST_VISIBLE: Final[str] = "log_path_not_host_visible"
LOG_PATH_IN_USE: Final[str] = "log_path_in_use"
PIPE_PANE_FAILED: Final[str] = "pipe_pane_failed"
ATTACHMENT_NOT_FOUND: Final[str] = "attachment_not_found"
LOG_FILE_MISSING: Final[str] = "log_file_missing"

CLOSED_CODE_SET: Final[frozenset[str]] = frozenset(
    {
        BAD_JSON,
        BAD_REQUEST,
        UNKNOWN_METHOD,
        REQUEST_TOO_LARGE,
        INTERNAL_ERROR,
        CONFIG_INVALID,
        DOCKER_UNAVAILABLE,
        DOCKER_PERMISSION_DENIED,
        DOCKER_TIMEOUT,
        DOCKER_FAILED,
        DOCKER_MALFORMED,
        TMUX_UNAVAILABLE,
        TMUX_NO_SERVER,
        SOCKET_DIR_MISSING,
        SOCKET_UNREADABLE,
        DOCKER_EXEC_FAILED,
        DOCKER_EXEC_TIMEOUT,
        OUTPUT_MALFORMED,
        BENCH_USER_UNRESOLVED,
        HOST_CONTEXT_UNSUPPORTED,
        CONTAINER_UNRESOLVED,
        NOT_IN_TMUX,
        TMUX_PANE_MALFORMED,
        PANE_UNKNOWN_TO_DAEMON,
        AGENT_NOT_FOUND,
        AGENT_INACTIVE,
        PARENT_NOT_FOUND,
        PARENT_INACTIVE,
        PARENT_ROLE_INVALID,
        PARENT_ROLE_MISMATCH,
        PARENT_IMMUTABLE,
        SWARM_PARENT_REQUIRED,
        SWARM_ROLE_VIA_SET_ROLE_REJECTED,
        MASTER_VIA_REGISTER_SELF_REJECTED,
        MASTER_CONFIRM_REQUIRED,
        VALUE_OUT_OF_SET,
        FIELD_TOO_LONG,
        PROJECT_PATH_INVALID,
        UNKNOWN_FILTER,
        SCHEMA_VERSION_NEWER,
        LOG_PATH_INVALID,
        LOG_PATH_NOT_HOST_VISIBLE,
        LOG_PATH_IN_USE,
        PIPE_PANE_FAILED,
        ATTACHMENT_NOT_FOUND,
        LOG_FILE_MISSING,
    }
)


def make_ok(result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the canonical success envelope ``{"ok": true, "result": ...}``."""
    return {"ok": True, "result": {} if result is None else result}


def make_error(code: str, message: str) -> dict[str, Any]:
    """Return the canonical error envelope.

    The ``code`` MUST belong to :data:`CLOSED_CODE_SET`. This is enforced at
    runtime so a typo in a caller cannot leak an unknown code onto the wire.
    """
    if code not in CLOSED_CODE_SET:
        raise ValueError(f"unknown error code: {code!r}")
    return {"ok": False, "error": {"code": code, "message": message}}
