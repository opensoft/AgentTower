"""FR-043 orphan-recovery startup pass.

When the daemon crashes between ``tmux pipe-pane`` returning success and the
SQLite COMMIT, the running pipe survives in tmux but no ``log_attachments``
row exists in the daemon's persisted state. On the next daemon startup we
detect those orphans and emit one ``log_attachment_orphan_detected``
lifecycle event per orphan; we NEVER auto-attach (operator action required).

This module is invoked once at daemon startup, after schema migration and
before the socket listener accepts requests. The pass is bounded by the
number of running bench containers (MVP scale: one or two), so it adds
negligible startup latency.
"""

from __future__ import annotations

import shlex
import sqlite3
from pathlib import Path
from typing import Iterable

from ..socket_api.lifecycle import LifecycleLogger
from .canonical_paths import host_canonical_log_root_for
from .docker_exec import DockerExecRunner
from .lifecycle import emit_log_attachment_orphan_detected
from .pipe_pane import build_inspection_argv
from .pipe_pane_state import (
    classify_pipe_target,
    parse_list_panes_output,
    sanitize_prior_pipe_target,
)


def _bench_containers(conn: sqlite3.Connection) -> Iterable[tuple[str, str, str]]:
    """Yield ``(container_id, container_user, name)`` for every active container."""
    cur = conn.execute(
        "SELECT container_id, config_user, name FROM containers WHERE active = 1"
    )
    for row in cur.fetchall():
        yield row[0], row[1] or "root", row[2] or ""


def _expected_container_side_log_for(
    *, daemon_home: Path, container_id: str, agent_id: str
) -> str:
    """Reproduce the FR-005 default container-side path for a given (container, agent)."""
    # In the canonical bench template, host==container path under
    # $HOME/.local/state/opensoft/agenttower/logs/. We compute the expected
    # container-side path the daemon WOULD have generated.
    return str(
        host_canonical_log_root_for(daemon_home) / container_id / f"{agent_id}.log"
    )


def detect_orphans(
    *,
    connection_factory,  # () -> sqlite3.Connection
    docker_exec_runner: DockerExecRunner,
    daemon_home: Path,
    lifecycle_logger: LifecycleLogger | None,
) -> int:
    """Run the FR-043 orphan-detection pass; return count of emitted events.

    For every active container's panes (via ``tmux list-panes -a``), look for
    pipes whose target matches the AgentTower canonical-prefix path but
    whose ``log_attachments`` row is missing. Each match emits ONE
    ``log_attachment_orphan_detected`` lifecycle event (de-duplicated per
    daemon lifetime by the FR-061 suppression registry).

    The daemon NEVER auto-attaches an orphan: the operator must run
    ``attach-log`` deliberately to bind it.
    """
    canonical_prefix = str(host_canonical_log_root_for(daemon_home)) + "/"
    emitted = 0

    for container_id, container_user, _name in _bench_containers(connection_factory()):
        # Run a per-container `tmux list-panes -a` to enumerate every pane
        # across every session. The FR-043 contract is best-effort: if
        # tmux is missing or the container has no live tmux server, we
        # simply find no orphans.
        argv = _build_list_panes_all_argv(container_user, container_id)
        result = docker_exec_runner.run(argv)
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Output shape (custom format below): "<pane_short> <pipe_pipe_flag> <pipe_command>"
            # The pipe_command may contain spaces; everything after the second
            # token is the pipe command.
            parts = stripped.split(" ", 2)
            if len(parts) < 2:
                continue
            pane_short = parts[0]
            pipe_flag = parts[1]
            pipe_cmd = parts[2] if len(parts) >= 3 else ""

            if pipe_flag != "1":
                continue
            if not pipe_cmd:
                continue

            # Quick prefix filter: only inspect pipes that target the
            # canonical-log root. Foreign pipes are not orphans.
            if canonical_prefix not in pipe_cmd:
                continue

            # Resolve the orphan to a (container_id, agent_id) by parsing
            # the canonical path out of the pipe command.
            agent_id = _extract_agent_id_from_pipe_command(
                pipe_cmd, container_id=container_id, daemon_home=daemon_home
            )
            if agent_id is None:
                continue

            # Strict canonical-target match (FR-054).
            expected = _expected_container_side_log_for(
                daemon_home=daemon_home, container_id=container_id, agent_id=agent_id
            )
            classification = classify_pipe_target(pipe_cmd, expected)
            if not classification.is_canonical:
                # Substring match without strict equality → foreign target;
                # not an orphan.
                continue

            # Look up the corresponding log_attachments row by (container_id,
            # pane_short_form) — but pane_short_form maps to the pane composite
            # key which has six fields. We use container_id + agent_id as the
            # disambiguator (the canonical path encodes agent_id).
            if _attachment_exists_for(connection_factory, container_id=container_id, agent_id=agent_id):
                continue

            # ORPHAN.
            pane_composite_key = f"{container_id}:{pane_short}"
            sanitized = sanitize_prior_pipe_target(pipe_cmd)
            emit_log_attachment_orphan_detected(
                lifecycle_logger,
                container_id=container_id,
                pane_composite_key=pane_composite_key,
                observed_pipe_target=sanitized,
                pane_short_form=pane_short,
            )
            emitted += 1
    return emitted


def _build_list_panes_all_argv(container_user: str, container_id: str) -> list[str]:
    """Argv for ``tmux list-panes -a`` with the FR-043 enumeration format."""
    fmt = "#{session_name}:#{window_index}.#{pane_index} #{pane_pipe} #{pane_pipe_command}"
    inner = f"tmux list-panes -a -F {shlex.quote(fmt)}"
    return [
        "docker",
        "exec",
        "-u",
        container_user,
        container_id,
        "sh",
        "-lc",
        inner,
    ]


def _extract_agent_id_from_pipe_command(
    pipe_cmd: str, *, container_id: str, daemon_home: Path
) -> str | None:
    """Pull the ``agt_<12-hex>`` agent id out of ``cat >> <canonical>/<id>.log``."""
    canonical_root = str(host_canonical_log_root_for(daemon_home))
    needle = f"{canonical_root}/{container_id}/"
    idx = pipe_cmd.find(needle)
    if idx < 0:
        return None
    tail = pipe_cmd[idx + len(needle):]
    # Tail starts with the agent_id; the file ends in `.log`. Strip the quote
    # if present and split off the extension.
    tail = tail.split(".log", 1)[0]
    tail = tail.strip().rstrip("'").rstrip('"')
    if len(tail) == 16 and tail.startswith("agt_"):
        return tail
    return None


def _attachment_exists_for(connection_factory, *, container_id: str, agent_id: str) -> bool:
    conn = connection_factory()
    try:
        cur = conn.execute(
            "SELECT 1 FROM log_attachments WHERE container_id = ? AND agent_id = ? "
            "AND status = 'active'",
            (container_id, agent_id),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()
