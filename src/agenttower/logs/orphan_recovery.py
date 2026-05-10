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
from contextlib import closing
from pathlib import Path
from typing import Iterable

from ..socket_api.lifecycle import LifecycleLogger
from ..state.bench_user import normalize_bench_user_for_exec
from .canonical_paths import (
    container_canonical_log_root_for,
    host_canonical_log_root_for,
)
from .docker_exec import DockerExecRunner
from .lifecycle import emit_log_attachment_orphan_detected
from .pipe_pane import _exec_env_args
from .pipe_pane_state import classify_pipe_target, sanitize_prior_pipe_target


def _bench_containers(conn: sqlite3.Connection) -> Iterable[tuple[str, str, str]]:
    """Yield ``(container_id, container_user, name)`` for every active container.

    ``container_user`` is normalized via
    :func:`agenttower.state.bench_user.normalize_bench_user_for_exec` so a
    Docker ``Config.User`` of the form ``user:uid`` (or just ``:1000``)
    becomes the bare username — matching the FEAT-004 FR-020 rule that
    ``docker exec -u`` needs a username, not a uid suffix.
    """
    cur = conn.execute(
        "SELECT container_id, config_user, name FROM containers WHERE active = 1"
    )
    for row in cur.fetchall():
        yield row[0], normalize_bench_user_for_exec(row[1]), row[2] or ""


def _expected_container_side_log_for(
    *, container_user: str, container_id: str, agent_id: str
) -> str:
    """Reproduce the FR-005 default container-side path for a given (container, agent)."""
    return str(
        container_canonical_log_root_for(container_user) / container_id / f"{agent_id}.log"
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
    emitted = 0

    # One SQLite connection covers the entire orphan pass: it owns the
    # ``containers`` enumeration AND the per-orphan ``log_attachments``
    # lookups. ``closing()`` guarantees release even if a tmux scan or
    # parser raises mid-loop.
    with closing(connection_factory()) as conn:
        for container_id, container_user, _name in _bench_containers(conn):
            canonical_prefixes = [
                str(container_canonical_log_root_for(container_user) / container_id) + "/",
                str(host_canonical_log_root_for(daemon_home) / container_id) + "/",
            ]
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
                # Output shape (custom format below):
                # "<pane_short> <pane_id> <pane_pipe_flag> <pipe_command>".
                # The pipe_command may contain spaces; everything after the
                # third token is the pipe command.
                parts = stripped.split(" ", 3)
                if len(parts) < 3:
                    continue
                pane_short = parts[0]
                pipe_flag = parts[2]
                pipe_cmd = parts[3] if len(parts) >= 4 else ""

                if pipe_flag != "1":
                    continue
                if not pipe_cmd:
                    continue

                # Quick prefix filter: only inspect pipes that target the
                # canonical-log root. Foreign pipes are not orphans.
                matched_prefix = next(
                    (prefix for prefix in canonical_prefixes if prefix in pipe_cmd),
                    None,
                )
                if matched_prefix is None:
                    continue

                # Resolve the orphan to a (container_id, agent_id) by parsing
                # the canonical path out of the pipe command.
                agent_id = _extract_agent_id_from_pipe_command(
                    pipe_cmd, canonical_root=matched_prefix.rstrip("/")
                )
                if agent_id is None:
                    continue

                # Strict canonical-target match (FR-054).
                expected_container = _expected_container_side_log_for(
                    container_user=container_user,
                    container_id=container_id,
                    agent_id=agent_id,
                )
                expected_host = str(
                    host_canonical_log_root_for(daemon_home)
                    / container_id
                    / f"{agent_id}.log"
                )
                classification = classify_pipe_target(pipe_cmd, expected_container)
                if not classification.is_canonical and not classify_pipe_target(
                    pipe_cmd, expected_host
                ).is_canonical:
                    # Substring match without strict equality → foreign
                    # target; not an orphan.
                    continue

                # Look up the corresponding log_attachments row by
                # (container_id, agent_id). The canonical path encodes
                # agent_id, so this disambiguates without needing the full
                # six-field pane composite key.
                if _attachment_exists_for(
                    conn, container_id=container_id, agent_id=agent_id
                ):
                    continue

                # ORPHAN.
                pane_composite_key = _lookup_pane_composite_key(
                    conn,
                    container_id=container_id,
                    pane_short=pane_short,
                )
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
    fmt = "#{session_name}:#{window_index}.#{pane_index} #{pane_id} #{pane_pipe} #{pane_pipe_command}"
    inner = f"tmux list-panes -a -F {shlex.quote(fmt)}"
    return [
        "docker",
        "exec",
        *_exec_env_args(),
        "-u",
        container_user,
        container_id,
        "sh",
        "-lc",
        inner,
    ]


def _extract_agent_id_from_pipe_command(
    pipe_cmd: str, *, canonical_root: str
) -> str | None:
    """Pull the ``agt_<12-hex>`` agent id out of ``cat >> <canonical>/<id>.log``."""
    needle = canonical_root.rstrip("/") + "/"
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


def _lookup_pane_composite_key(
    conn: sqlite3.Connection, *, container_id: str, pane_short: str
) -> dict[str, object]:
    """Best-effort reconstruction of the full FEAT-004 pane composite key."""
    session_name, rest = pane_short.split(":", 1)
    window_index_str, pane_index_str = rest.split(".", 1)
    window_index = int(window_index_str)
    pane_index = int(pane_index_str)
    row = conn.execute(
        """
        SELECT tmux_socket_path, tmux_pane_id
          FROM panes
         WHERE container_id = ?
           AND tmux_session_name = ?
           AND tmux_window_index = ?
           AND tmux_pane_index = ?
           AND active = 1
         ORDER BY last_scanned_at DESC
         LIMIT 1
        """,
        (container_id, session_name, window_index, pane_index),
    ).fetchone()
    return {
        "container_id": container_id,
        "tmux_socket_path": row[0] if row is not None else "",
        "tmux_session_name": session_name,
        "tmux_window_index": window_index,
        "tmux_pane_index": pane_index,
        "tmux_pane_id": row[1] if row is not None else "",
    }


def _attachment_exists_for(
    conn: sqlite3.Connection, *, container_id: str, agent_id: str
) -> bool:
    """Return True iff an active ``log_attachments`` row exists for the pair.

    Reuses the caller's connection — orphan recovery opens one connection
    for the entire pass (see :func:`detect_orphans`).
    """
    cur = conn.execute(
        "SELECT 1 FROM log_attachments WHERE container_id = ? AND agent_id = ? "
        "AND status = 'active'",
        (container_id, agent_id),
    )
    return cur.fetchone() is not None
