"""User-facing AgentTower CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import os
import socket as _socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__
from .config import _DIR_MODE, _ensure_dir_chain, write_default_config
from .config_doctor import runtime_detect
from .config_doctor.socket_resolve import (
    SocketPathInvalid,
    resolve_socket_path,
)
from .paths import Paths, ResolvedSocket, resolve_paths
from .socket_api import lifecycle
from .socket_api.client import DaemonError, DaemonUnavailable, send_request
from .state.schema import companion_paths_for, open_registry

LOCK_FILENAME = "agenttowerd.lock"
PID_FILENAME = "agenttowerd.pid"
LOG_FILENAME = "agenttowerd.log"

READY_BUDGET_SECONDS = 2.0
READY_POLL_INTERVALS = (0.01, 0.05, 0.1, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2)
JSON_LINE_HELP = "emit one JSON line on stdout"
DAEMON_UNAVAILABLE_MESSAGE = (
    "error: daemon is not running or socket is unreachable: "
    "try `agenttower ensure-daemon`"
)


def _resolve_socket_with_paths(env: dict[str, str] | None = None) -> tuple[Paths, ResolvedSocket]:
    """Resolve filesystem paths AND the daemon socket path with FR-001 priority.

    On invalid ``AGENTTOWER_SOCKET`` (any of the FR-002 closed-set ``<reason>``
    tokens), prints the FR-002 stderr line and raises :class:`SystemExit(1)`.
    Returns ``(paths, resolved_socket)`` for normal control flow; every
    socket-using handler then opens the socket via ``resolved_socket.path``.
    """

    if env is None:
        env = dict(os.environ)
    paths = resolve_paths(env)
    # Thread AGENTTOWER_TEST_PROC_ROOT through the supplied env so runtime
    # detection stays consistent with the resolver (PR-6 review #2/#3 finding:
    # detect() previously read os.environ directly, breaking custom-env callers).
    runtime_context = runtime_detect.detect(
        proc_root=env.get("AGENTTOWER_TEST_PROC_ROOT")
    )
    try:
        resolved = resolve_socket_path(env, paths, runtime_context)
    except SocketPathInvalid as exc:
        print(
            f"error: AGENTTOWER_SOCKET must be an absolute path to a Unix socket: {exc.reason}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    return paths, resolved


def _guard_production_test_seam_unset() -> None:
    """A2 / FR-025: refuse to run under leaked ``AGENTTOWER_TEST_PROC_ROOT``.

    When ``AGENTTOWER_TEST_PROC_ROOT`` is set but no other ``AGENTTOWER_TEST_*``
    companion env var is also set, the binary is almost certainly running
    outside the test harness (e.g., a developer's stale shell). Refuse to
    proceed so a fake ``/proc`` cannot silently substitute for the real one
    in a production CLI invocation.

    A test harness already sets at least one of ``AGENTTOWER_TEST_DOCKER_FAKE``
    / ``AGENTTOWER_TEST_TMUX_FAKE`` (FEAT-003 / FEAT-004) along with
    ``AGENTTOWER_TEST_PROC_ROOT``, so this gate does not fire under pytest.
    """

    if "AGENTTOWER_TEST_PROC_ROOT" not in os.environ:
        return
    companions = [
        key
        for key in os.environ
        if key.startswith("AGENTTOWER_TEST_") and key != "AGENTTOWER_TEST_PROC_ROOT"
    ]
    if companions:
        return
    print(
        "error: AGENTTOWER_TEST_PROC_ROOT is set outside the test harness; unset it before running production",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _namespace_root(any_member: Path) -> Path:
    """Return the deepest ``opensoft/agenttower`` ancestor of *any_member*."""
    for parent in [any_member, *any_member.parents]:
        if parent.parent.name == "opensoft" and parent.name == "agenttower":
            return parent
    raise ValueError(f"path {any_member} is not under an opensoft/agenttower namespace")


def _companion_presence(paths: Paths) -> dict[Path, bool]:
    return {p: p.exists() for p in companion_paths_for(paths.state_db)}


def _ensure_init_directories(paths: Paths) -> tuple[Path, Path]:
    config_namespace = _namespace_root(paths.config_file)
    state_namespace = _namespace_root(paths.state_db)
    _ensure_dir_chain(paths.config_file.parent, namespace_root=config_namespace)
    _ensure_dir_chain(paths.logs_dir, namespace_root=state_namespace)
    _ensure_dir_chain(paths.cache_dir, namespace_root=paths.cache_dir)
    return config_namespace, state_namespace


def _cleanup_created_registry(
    paths: Paths,
    *,
    state_db_pre_existed: bool,
    companion_pre_existed: dict[Path, bool],
) -> None:
    if not state_db_pre_existed and paths.state_db.exists():
        _unlink_ignoring_errors(paths.state_db)
    for companion, was_present in companion_pre_existed.items():
        if not was_present and companion.exists():
            _unlink_ignoring_errors(companion)


def _unlink_ignoring_errors(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _error_details(exc: OSError | sqlite3.Error, state_db: Path) -> tuple[str, str, str]:
    if isinstance(exc, OSError):
        return "initialize", exc.filename or "<unknown>", exc.strerror or str(exc)
    return "open registry", str(state_db), str(exc)


def _print_init_result(paths: Paths, config_status: str, registry_status: str) -> None:
    config_prefix = "created config" if config_status == "created" else "already initialized"
    registry_prefix = "created registry" if registry_status == "created" else "already initialized"
    print(f"{config_prefix}: {paths.config_file}")
    print(f"{registry_prefix}: {paths.state_db}")


def _config_init(args: argparse.Namespace) -> int:
    paths: Paths = resolve_paths()
    state_db_pre_existed = paths.state_db.exists()
    companion_pre_existed = _companion_presence(paths)

    try:
        config_namespace, state_namespace = _ensure_init_directories(paths)
        config_status = write_default_config(paths.config_file, namespace_root=config_namespace)
        conn, registry_status = open_registry(paths.state_db, namespace_root=state_namespace)
        conn.close()
    except (OSError, sqlite3.Error) as exc:
        _cleanup_created_registry(
            paths,
            state_db_pre_existed=state_db_pre_existed,
            companion_pre_existed=companion_pre_existed,
        )
        verb, path, reason = _error_details(exc, paths.state_db)
        print(f"error: {verb}: {path}: {reason}", file=sys.stderr)
        return 1

    _print_init_result(paths, config_status, registry_status)
    return 0


def _config_paths(args: argparse.Namespace) -> int:
    # Resolve paths AND the socket together so the SOCKET= line and the new
    # SOCKET_SOURCE= line cannot drift (FR-019). On invalid AGENTTOWER_SOCKET,
    # _resolve_socket_with_paths exits 1 with the FR-002 stderr message
    # before any KEY=value line is printed.
    paths, resolved = _resolve_socket_with_paths()
    print(f"CONFIG_FILE={paths.config_file}")
    print(f"STATE_DB={paths.state_db}")
    print(f"EVENTS_FILE={paths.events_file}")
    print(f"LOGS_DIR={paths.logs_dir}")
    print(f"SOCKET={resolved.path}")
    print(f"CACHE_DIR={paths.cache_dir}")
    print(f"SOCKET_SOURCE={resolved.source}")
    if not paths.state_db.exists():
        print(
            "note: agenttower has not been initialized; run `agenttower config init`",
            file=sys.stderr,
        )
    return 0


def _config_doctor(args: argparse.Namespace) -> int:
    """``agenttower config doctor`` — run the closed-set diagnostic checks.

    Pre-flight ``SocketPathInvalid`` is converted to the FR-002 stderr path
    + exit ``1`` BEFORE constructing a :class:`DoctorReport`. Otherwise the
    runner produces a six-row report which is rendered as TSV (default) or
    canonical JSON (``--json``); the CLI exits with ``report.exit_code``.
    """

    from .config_doctor import render_json, render_tsv, run_doctor

    paths = resolve_paths()
    try:
        report = run_doctor(dict(os.environ), paths)
    except SocketPathInvalid as exc:
        print(
            f"error: AGENTTOWER_SOCKET must be an absolute path to a Unix socket: {exc.reason}",
            file=sys.stderr,
        )
        return 1

    if args.json:
        print(render_json(report))
    else:
        sys.stdout.write(render_tsv(report))
    return int(report.exit_code)


def _ensure_daemon(args: argparse.Namespace) -> int:
    # ensure-daemon manages the host daemon, which always binds at the
    # FEAT-001 host-default socket path. AGENTTOWER_SOCKET only redirects
    # *client* connect targets; threading it through the daemon-lifecycle
    # path would route the readiness ping at one path and spawn the daemon
    # at another, which is the pre-fix behavior the PR-6 review caught.
    # We still call _resolve_socket_with_paths() so a malformed
    # AGENTTOWER_SOCKET fires the FR-002 pre-flight (exit 1) — but the
    # resolved path is intentionally discarded for routing.
    paths, _ = _resolve_socket_with_paths()
    state_dir = paths.state_db.parent
    logs_dir = paths.logs_dir
    lock_path = state_dir / LOCK_FILENAME
    socket_path = paths.socket

    preflight = _ensure_daemon_preflight(paths, json_mode=args.json)
    if preflight is not None:
        return preflight

    claimed, lock_or_exit = _claim_startup_slot(
        lock_path, socket_path, state_dir, logs_dir, args.json
    )
    if not claimed:
        return lock_or_exit
    lifecycle.release_lock(lock_or_exit)

    log_path = logs_dir / LOG_FILENAME
    proc = _spawn_daemon(log_path)
    return _wait_for_spawned_daemon(
        proc,
        socket_path=socket_path,
        state_dir=state_dir,
        log_path=log_path,
        json_mode=args.json,
    )


def _ensure_daemon_preflight(paths: Paths, *, json_mode: bool) -> int | None:
    state_dir = paths.state_db.parent

    if not paths.state_db.exists():
        print(
            "error: agenttower is not initialized: run `agenttower config init`",
            file=sys.stderr,
        )
        return 1

    # Ping the host-default socket — the only path the daemon binds at.
    pre_existing = _try_ping(paths.socket)
    if pre_existing is not None:
        return _print_ready(
            pre_existing, paths.socket, state_dir, json_mode=json_mode, started=False
        )

    try:
        lifecycle.assert_paths_safe(state_dir=state_dir, logs_dir=paths.logs_dir)
    except lifecycle.UnsafePathError as exc:
        print(f"error: unsafe permissions on {exc.path}: {exc.reason}", file=sys.stderr)
        return 1

    return None


def _claim_startup_slot(
    lock_path: Path,
    socket_path: Path,
    state_dir: Path,
    logs_dir: Path,
    json_mode: bool,
) -> tuple[bool, int]:
    try:
        return True, lifecycle.acquire_exclusive_lock(lock_path)
    except lifecycle.LockHeldError:
        # Another startup is in progress; poll for readiness via ping.
        ready = _wait_for_ready(socket_path, READY_BUDGET_SECONDS)
        if ready is not None:
            return False, _print_ready(
                ready, socket_path, state_dir, json_mode=json_mode, started=False
            )
        print(
            f"error: daemon failed to become ready within {READY_BUDGET_SECONDS:.2f}s: "
            f"see {logs_dir / LOG_FILENAME}",
            file=sys.stderr,
        )
        return False, 2
    except OSError as exc:
        print(f"error: acquire lock: {lock_path}: {exc}", file=sys.stderr)
        return False, 1


def _spawn_daemon(log_path: Path) -> subprocess.Popen[Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC, 0o600)
    try:
        os.chmod(log_path, 0o600)
    except OSError:
        pass
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "agenttower.daemon", "run"],
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        os.close(log_fd)
    return proc


def _wait_for_spawned_daemon(
    proc: subprocess.Popen[Any],
    *,
    socket_path: Path,
    state_dir: Path,
    log_path: Path,
    json_mode: bool,
) -> int:
    deadline = time.monotonic() + READY_BUDGET_SECONDS
    spawned_daemon_active = True
    while time.monotonic() < deadline:
        ready = _try_ping(socket_path)
        if ready is not None:
            # If our spawned child won the race, report started=true; if a
            # peer ensure-daemon's child won, report started=false (FR-007).
            still_alive = proc.poll() is None
            return _print_ready(
                ready,
                socket_path,
                state_dir,
                json_mode=json_mode,
                started=still_alive,
            )
        if proc.poll() is not None:
            # Child exited before becoming ready.
            #
            # If exit code is 2 it lost the lock race against a peer; FR-007
            # says we should still succeed if a peer-spawned daemon comes
            # up. Continue polling against the same deadline.
            if proc.returncode == 2 and spawned_daemon_active:
                spawned_daemon_active = False
                # Loop again — the lock holder may not yet be bound.
                time.sleep(0.05)
                continue
            tail = _tail_log(log_path, lines=10)
            print(
                f"error: agenttowerd exited before ready (code={proc.returncode}); "
                f"tail of {log_path}:\n{tail}",
                file=sys.stderr,
            )
            return 2
        time.sleep(0.05)

    # Budget exceeded — try to clean up the spawned process to avoid orphans.
    try:
        proc.terminate()
    except OSError:
        pass
    print(
        f"error: daemon failed to become ready within {READY_BUDGET_SECONDS:.2f}s: "
        f"see {log_path}",
        file=sys.stderr,
    )
    return 2


def _status_command(args: argparse.Namespace) -> int:
    _, resolved = _resolve_socket_with_paths()
    try:
        result = send_request(
            resolved.path, "status", connect_timeout=1.0, read_timeout=1.0
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        print(f"code: {exc.code}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps({"ok": True, "result": result}))
    else:
        print(f"alive={str(result.get('alive', False)).lower()}")
        print(f"pid={result.get('pid')}")
        print(f"start_time={result.get('start_time_utc')}")
        print(f"uptime_seconds={result.get('uptime_seconds')}")
        print(f"socket_path={result.get('socket_path')}")
        print(f"state_path={result.get('state_path')}")
    return 0


def _stop_daemon(args: argparse.Namespace) -> int:
    paths, resolved = _resolve_socket_with_paths()
    state_dir = paths.state_db.parent
    socket_path = resolved.path
    try:
        send_request(socket_path, "shutdown", connect_timeout=1.0, read_timeout=1.0)
    except DaemonUnavailable:
        print("error: no reachable daemon to stop", file=sys.stderr)
        return 2
    except DaemonError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        print(f"code: {exc.code}", file=sys.stderr)
        return 3

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if _socket_unreachable(socket_path):
            break
        time.sleep(0.05)
    else:
        print(
            "error: daemon acknowledged shutdown but socket is still reachable",
            file=sys.stderr,
        )
        return 3

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "stopped": True,
                    "socket_path": str(socket_path),
                    "state_path": str(state_dir),
                }
            )
        )
    else:
        print(f"agenttowerd stopped: socket={socket_path} state={state_dir}")
    return 0


def _socket_unreachable(socket_path: Path) -> bool:
    if not socket_path.exists():
        return True
    s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    s.settimeout(0.1)
    saved = os.getcwd()
    try:
        try:
            os.chdir(socket_path.parent)
            s.connect(socket_path.name)
        except (FileNotFoundError, ConnectionRefusedError):
            return True
        except OSError:
            return True
        finally:
            os.chdir(saved)
    finally:
        s.close()
    return False


def _try_ping(socket_path: Path) -> dict[str, Any] | None:
    try:
        send_request(socket_path, "ping", connect_timeout=0.5, read_timeout=0.5)
    except DaemonUnavailable:
        return None
    except DaemonError:
        # Daemon answered something — treat as live for ensure-daemon's purposes.
        return {"alive": True}
    return {"alive": True}


def _wait_for_ready(socket_path: Path, budget: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        ready = _try_ping(socket_path)
        if ready is not None:
            return ready
        time.sleep(0.05)
    return None


def _print_ready(
    _ping_result: dict[str, Any],
    socket_path: Path,
    state_path: Path,
    *,
    json_mode: bool,
    started: bool,
) -> int:
    pid = _read_daemon_pid(state_path)
    if json_mode:
        print(
            json.dumps(
                {
                    "ok": True,
                    "started": started,
                    "pid": pid,
                    "socket_path": str(socket_path),
                    "state_path": str(state_path),
                }
            )
        )
    else:
        pid_repr = pid if pid is not None else "?"
        print(f"agenttowerd ready: pid={pid_repr} socket={socket_path} state={state_path}")
    return 0


def _read_daemon_pid(state_path: Path) -> int | None:
    return lifecycle.read_pid_file(state_path / PID_FILENAME)


def _tail_log(log_path: Path, *, lines: int) -> str:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(log unreadable)"
    return "\n".join(text.splitlines()[-lines:])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenttower",
        description="AgentTower CLI — local-first agent control plane.",
        epilog=(
            "config subcommands:\n"
            "  config paths   print resolved KEY=value paths AgentTower will use\n"
            "  config init    create the durable Opensoft layout (idempotent)\n"
            "  config doctor  run the closed-set diagnostic checks (FEAT-005)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"agenttower {__version__}",
    )
    parser.set_defaults(_handler=None)

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    config = subparsers.add_parser(
        "config",
        help="inspect and initialize AgentTower's host layout",
        description="inspect and initialize AgentTower's host layout",
    )
    config.set_defaults(_handler=lambda args: _print_subusage_and_exit(config))

    config_subs = config.add_subparsers(dest="config_command", metavar="subcommand")

    paths_parser = config_subs.add_parser(
        "paths",
        help="print resolved KEY=value paths AgentTower will use",
        description="print resolved KEY=value paths AgentTower will use",
    )
    paths_parser.set_defaults(_handler=_config_paths)

    init_parser = config_subs.add_parser(
        "init",
        help="create the durable Opensoft layout (idempotent)",
        description="create the durable Opensoft layout (idempotent)",
    )
    init_parser.set_defaults(_handler=_config_init)

    doctor_parser = config_subs.add_parser(
        "doctor",
        help="run the closed-set diagnostic checks (FEAT-005)",
        description="run the closed-set diagnostic checks (FEAT-005)",
    )
    doctor_parser.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    doctor_parser.set_defaults(_handler=_config_doctor)

    ensure_daemon = subparsers.add_parser(
        "ensure-daemon",
        help="ensure the host daemon is running (idempotent, lock-serialized)",
        description="ensure the host daemon is running (idempotent, lock-serialized)",
    )
    ensure_daemon.add_argument(
        "--json", action="store_true", help=JSON_LINE_HELP
    )
    ensure_daemon.set_defaults(_handler=_ensure_daemon)

    status = subparsers.add_parser(
        "status",
        help="query the host daemon over the local socket",
        description="query the host daemon over the local socket",
    )
    status.add_argument(
        "--json", action="store_true", help=JSON_LINE_HELP
    )
    status.set_defaults(_handler=_status_command)

    stop_daemon = subparsers.add_parser(
        "stop-daemon",
        help="ask the host daemon to shut down via the local socket",
        description="ask the host daemon to shut down via the local socket",
    )
    stop_daemon.add_argument(
        "--json", action="store_true", help=JSON_LINE_HELP
    )
    stop_daemon.set_defaults(_handler=_stop_daemon)

    scan = subparsers.add_parser(
        "scan",
        help="scan host resources (FEAT-003: --containers; FEAT-004: --panes)",
        description="scan host resources (FEAT-003: --containers; FEAT-004: --panes)",
    )
    scan.add_argument("--containers", action="store_true", help="scan Docker containers")
    scan.add_argument(
        "--panes",
        action="store_true",
        help="scan tmux panes inside active bench containers",
    )
    scan.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    scan.set_defaults(_handler=_scan_command)

    list_containers = subparsers.add_parser(
        "list-containers",
        help="list persisted bench-container records",
        description="list persisted bench-container records",
    )
    list_containers.add_argument(
        "--active-only",
        action="store_true",
        help="only return currently-active containers",
    )
    list_containers.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    list_containers.set_defaults(_handler=_list_containers_command)

    list_panes = subparsers.add_parser(
        "list-panes",
        help="list persisted tmux pane records",
        description="list persisted tmux pane records",
    )
    list_panes.add_argument(
        "--active-only",
        action="store_true",
        help="only return currently-active panes",
    )
    list_panes.add_argument(
        "--container",
        default=None,
        help="filter by exact container id (64-char hex) or container name",
    )
    list_panes.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    list_panes.set_defaults(_handler=_list_panes_command)

    # ------------------------------------------------------------------
    # FEAT-006 — register-self / list-agents / set-* subparsers.
    #
    # Per Clarifications Q1 / FR-007 the CLI MUST NOT transmit
    # argparse-style defaults on idempotent re-registration of an
    # existing pane: omitted flags are absent in the parsed Namespace
    # so the daemon leaves stored values unchanged. We use
    # ``argparse.SUPPRESS`` as the per-flag default so omitted flags
    # never appear in the Namespace at all (research R-002).
    # ------------------------------------------------------------------

    register_self = subparsers.add_parser(
        "register-self",
        help="register the current tmux pane as an AgentTower agent",
        description="register the current tmux pane as an AgentTower agent",
    )
    register_self.add_argument("--role", default=argparse.SUPPRESS)
    register_self.add_argument("--capability", default=argparse.SUPPRESS)
    register_self.add_argument("--label", default=argparse.SUPPRESS)
    register_self.add_argument("--project", default=argparse.SUPPRESS)
    register_self.add_argument("--parent", default=argparse.SUPPRESS)
    register_self.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    register_self.set_defaults(_handler=_register_self_command)

    list_agents = subparsers.add_parser(
        "list-agents",
        help="list registered AgentTower agents",
        description="list registered AgentTower agents",
    )
    list_agents.add_argument(
        "--role",
        action="append",
        default=None,
        help="filter by role (repeatable to OR multiple roles)",
    )
    list_agents.add_argument(
        "--container",
        default=None,
        help="filter by exact container id, 12-char short prefix, or 64-char hex",
    )
    list_agents.add_argument(
        "--active-only",
        action="store_true",
        help="only return currently-active agents",
    )
    list_agents.add_argument(
        "--parent",
        default=None,
        help="filter swarm children of the given parent agent_id",
    )
    list_agents.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    list_agents.set_defaults(_handler=_list_agents_command)

    set_role = subparsers.add_parser(
        "set-role",
        help="change an agent's role (master requires --confirm)",
        description="change an agent's role (master requires --confirm)",
    )
    set_role.add_argument("--target", required=True)
    set_role.add_argument("--role", required=True)
    set_role.add_argument("--confirm", action="store_true")
    set_role.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    set_role.set_defaults(_handler=_set_role_command)

    set_label = subparsers.add_parser(
        "set-label",
        help="change an agent's free-text label",
        description="change an agent's free-text label",
    )
    set_label.add_argument("--target", required=True)
    set_label.add_argument("--label", required=True)
    set_label.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    set_label.set_defaults(_handler=_set_label_command)

    set_capability = subparsers.add_parser(
        "set-capability",
        help="change an agent's capability descriptor",
        description="change an agent's capability descriptor",
    )
    set_capability.add_argument("--target", required=True)
    set_capability.add_argument("--capability", required=True)
    set_capability.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    set_capability.set_defaults(_handler=_set_capability_command)

    return parser


def _print_subusage_and_exit(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 0


def _scan_command(args: argparse.Namespace) -> int:
    if not args.containers and not args.panes:
        print(
            "error: scan requires a target flag (e.g. --containers, --panes)",
            file=sys.stderr,
        )
        return 1
    final_code = 0
    first_block = True
    if args.containers:
        code = _run_container_scan(args, first_block=first_block)
        if code in (2, 3):
            return code
        final_code = _combine_scan_exit_codes(final_code, code)
        first_block = False
    if args.panes:
        code = _run_pane_scan(args, first_block=first_block)
        if code in (2, 3):
            return code
        final_code = _combine_scan_exit_codes(final_code, code)
    return final_code


def _combine_scan_exit_codes(current: int, new: int) -> int:
    """Apply FEAT scan precedence for combined runs.

    Daemon-unavailable / daemon-error (2/3) are handled by the caller and
    short-circuit immediately; among successful/degraded scan results we keep
    the degraded exit code when any step degraded.
    """
    if current == 5 or new == 5:
        return 5
    return 0


def _run_container_scan(
    args: argparse.Namespace, *, first_block: bool
) -> int:
    # Resolve the socket inline so we honor AGENTTOWER_SOCKET / mounted-default
    # without changing the existing helper signature (preserves FEAT-003 test
    # mocks per FR-026). On invalid AGENTTOWER_SOCKET this exits 1 with the
    # FR-002 stderr message before any send_request.
    _, resolved = _resolve_socket_with_paths()
    try:
        result = send_request(
            resolved.path, "scan_containers", connect_timeout=1.0, read_timeout=15.0
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}))
        else:
            print(f"error: {exc.message}", file=sys.stderr)
            print(f"code: {exc.code}", file=sys.stderr)
        return 3

    status = result.get("status", "ok")
    if args.json:
        print(json.dumps({"ok": True, "result": result}))
    else:
        if not first_block:
            print()  # blank line between summary blocks
        try:
            started = _parse_iso(result["started_at"])
            completed = _parse_iso(result["completed_at"])
            duration_ms = max(0, int((completed - started).total_seconds() * 1000))
        except (KeyError, ValueError):
            duration_ms = 0
        print(f"scan_id={result.get('scan_id')}")
        print(f"status={status}")
        print(f"matched={result.get('matched_count')}")
        print(f"inactive_reconciled={result.get('inactive_reconciled_count')}")
        print(f"ignored={result.get('ignored_count')}")
        print(f"duration_ms={duration_ms}")
        if status == "degraded":
            print(f"error: {result.get('error_message')}", file=sys.stderr)
            print(f"code: {result.get('error_code')}", file=sys.stderr)
    return 5 if status == "degraded" else 0


def _run_pane_scan(
    args: argparse.Namespace, *, first_block: bool
) -> int:
    # Resolve the socket inline (see _run_container_scan note above).
    _, resolved = _resolve_socket_with_paths()
    try:
        result = send_request(
            resolved.path, "scan_panes", connect_timeout=1.0, read_timeout=30.0
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        if args.json:
            print(
                json.dumps(
                    {"ok": False, "error": {"code": exc.code, "message": exc.message}}
                )
            )
        else:
            print(f"error: {exc.message}", file=sys.stderr)
            print(f"code: {exc.code}", file=sys.stderr)
        return 3

    status = result.get("status", "ok")
    if args.json:
        print(json.dumps({"ok": True, "result": result}))
    else:
        if not first_block:
            print()
        try:
            started = _parse_iso(result["started_at"])
            completed = _parse_iso(result["completed_at"])
            duration_ms = max(0, int((completed - started).total_seconds() * 1000))
        except (KeyError, ValueError):
            duration_ms = 0
        print(f"scan_id={result.get('scan_id')}")
        print(f"status={status}")
        print(f"containers_scanned={result.get('containers_scanned')}")
        print(f"sockets_scanned={result.get('sockets_scanned')}")
        print(f"panes_seen={result.get('panes_seen')}")
        print(f"panes_newly_active={result.get('panes_newly_active')}")
        # Wire field is `panes_reconciled_to_inactive`; the human view
        # uses the shorter `panes_reconciled_inactive` (data-model §6 note 5).
        print(
            f"panes_reconciled_inactive={result.get('panes_reconciled_to_inactive')}"
        )
        print(
            f"containers_skipped_inactive={result.get('containers_skipped_inactive')}"
        )
        print(
            f"containers_tmux_unavailable={result.get('containers_tmux_unavailable')}"
        )
        print(f"duration_ms={duration_ms}")
        if status == "degraded":
            print(f"error: {result.get('error_message')}", file=sys.stderr)
            print(f"code: {result.get('error_code')}", file=sys.stderr)
            for detail in (result.get("error_details") or [])[:10]:
                socket = detail.get("tmux_socket_path")
                socket_label = f" [socket={socket}]" if socket else ""
                print(
                    f"detail: {detail.get('container_id')}{socket_label} "
                    f"{detail.get('error_code')}: {detail.get('error_message')}",
                    file=sys.stderr,
                )
            extra = max(0, len(result.get("error_details") or []) - 10)
            if extra:
                print(f"detail: ... ({extra} more)", file=sys.stderr)
    return 5 if status == "degraded" else 0


def _parse_iso(text: str) -> "datetime":  # type: ignore[name-defined]
    from datetime import datetime as _dt
    return _dt.fromisoformat(text)


def _list_containers_command(args: argparse.Namespace) -> int:
    _, resolved = _resolve_socket_with_paths()
    params: dict[str, Any] = {"active_only": bool(args.active_only)}
    try:
        result = send_request(
            resolved.path,
            "list_containers",
            params=params,
            connect_timeout=1.0,
            read_timeout=1.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}))
        else:
            print(f"error: {exc.message}", file=sys.stderr)
            print(f"code: {exc.code}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps({"ok": True, "result": result}))
    else:
        print("ACTIVE\tID\tNAME\tIMAGE\tSTATUS\tLAST_SCANNED")
        for c in result.get("containers", []):
            active = "1" if c.get("active") else "0"
            print(
                f"{active}\t{c.get('id')}\t{c.get('name')}\t{c.get('image')}\t"
                f"{c.get('status')}\t{c.get('last_scanned_at')}"
            )
    return 0


def _list_panes_command(args: argparse.Namespace) -> int:
    _, resolved = _resolve_socket_with_paths()
    params: dict[str, Any] = {
        "active_only": bool(args.active_only),
        "container": args.container,
    }
    try:
        result = send_request(
            resolved.path,
            "list_panes",
            params=params,
            connect_timeout=1.0,
            read_timeout=1.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        if args.json:
            print(
                json.dumps(
                    {"ok": False, "error": {"code": exc.code, "message": exc.message}}
                )
            )
        else:
            print(f"error: {exc.message}", file=sys.stderr)
            print(f"code: {exc.code}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps({"ok": True, "result": result}))
        return 0
    print(
        "ACTIVE\tFOCUSED\tCONTAINER\tSOCKET\tSESSION\tW\tP\tPANE_ID\tPID\tTTY\tCOMMAND\tCWD\tLAST_SCANNED"
    )
    for pane in result.get("panes", []):
        active = "1" if pane.get("active") else "0"
        focused = "1" if pane.get("pane_active") else "0"
        print(
            "\t".join(
                str(value)
                for value in (
                    active,
                    focused,
                    pane.get("container_name"),
                    pane.get("tmux_socket_path"),
                    pane.get("tmux_session_name"),
                    pane.get("tmux_window_index"),
                    pane.get("tmux_pane_index"),
                    pane.get("tmux_pane_id"),
                    pane.get("pane_pid"),
                    pane.get("pane_tty"),
                    pane.get("pane_current_command"),
                    pane.get("pane_current_path"),
                    pane.get("last_scanned_at"),
                )
            )
        )
    return 0


# ---------------------------------------------------------------------------
# FEAT-006 — register-self / list-agents / set-* command handlers.
# ---------------------------------------------------------------------------

# Keys we look for on the parsed argparse.Namespace for the supplied-vs-default
# wire contract (Clarifications Q1). Using ``argparse.SUPPRESS`` as the default
# means absent flags are NOT attributes on the Namespace.
_REGISTER_SELF_OPTIONAL = (
    ("role", "role"),
    ("capability", "capability"),
    ("label", "label"),
    ("project", "project_path"),
    ("parent", "parent_agent_id"),
)


def _register_self_command(args: argparse.Namespace) -> int:
    """Resolve identity, build the request envelope, and call register_agent."""
    from .agents.client_resolve import resolve_pane_composite_key
    from .agents.errors import RegistrationError

    _, resolved = _resolve_socket_with_paths()
    socket_path = resolved.path

    try:
        target = resolve_pane_composite_key(
            socket_path=socket_path,
            env=os.environ,
            proc_root=os.environ.get("AGENTTOWER_TEST_PROC_ROOT"),
            connect_timeout=1.0,
            read_timeout=5.0,
        )
    except RegistrationError as exc:
        return _emit_register_error(exc, args.json)
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        return _emit_daemon_error(exc, args.json)

    params: dict[str, Any] = {
        "container_id": target.container_id,
        "pane_composite_key": {
            "container_id": target.pane_key[0],
            "tmux_socket_path": target.pane_key[1],
            "tmux_session_name": target.pane_key[2],
            "tmux_window_index": target.pane_key[3],
            "tmux_pane_index": target.pane_key[4],
            "tmux_pane_id": target.pane_key[5],
        },
    }
    # Only-supplied-fields-overwrite (Clarifications Q1): we include each
    # mutable field iff the user passed the flag. argparse.SUPPRESS made
    # omitted flags absent from the Namespace, so a hasattr/getattr probe
    # is sufficient to distinguish "supplied" from "not supplied".
    for ns_attr, wire_key in _REGISTER_SELF_OPTIONAL:
        if hasattr(args, ns_attr):
            params[wire_key] = getattr(args, ns_attr)

    try:
        result = send_request(
            socket_path,
            "register_agent",
            params,
            connect_timeout=1.0,
            read_timeout=5.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        return _emit_daemon_error(exc, args.json)

    if args.json:
        print(json.dumps({"ok": True, "result": result}))
    else:
        print(f"agent_id={result.get('agent_id')}")
        print(f"role={result.get('role')}")
        print(f"capability={result.get('capability')}")
        print(f"label={result.get('label')}")
        print(f"project_path={result.get('project_path')}")
        print(f"parent_agent_id={result.get('parent_agent_id') or '-'}")
        print(f"created_or_reactivated={result.get('created_or_reactivated')}")
    return 0


def _list_agents_command(args: argparse.Namespace) -> int:
    _, resolved = _resolve_socket_with_paths()
    socket_path = resolved.path

    params: dict[str, Any] = {}
    if args.role:
        params["role"] = args.role
    if args.container is not None:
        params["container_id"] = args.container
    if args.active_only:
        params["active_only"] = True
    if args.parent is not None:
        params["parent_agent_id"] = args.parent

    try:
        result = send_request(
            socket_path,
            "list_agents",
            params,
            connect_timeout=1.0,
            read_timeout=5.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        return _emit_daemon_error(exc, args.json)

    if args.json:
        print(json.dumps({"ok": True, "result": result}))
        return 0
    # FR-029 locked TSV column schema with required header row.
    print(
        "AGENT_ID\tLABEL\tROLE\tCAPABILITY\tCONTAINER\tPANE\tPROJECT\tPARENT\tACTIVE"
    )
    for agent in result.get("agents", []):
        agent_id = agent.get("agent_id", "")
        label = _scrub_for_tsv(agent.get("label", ""))
        role = agent.get("role", "")
        capability = agent.get("capability", "")
        container_short = (agent.get("container_id") or "")[:12]
        pane = (
            f"{agent.get('tmux_session_name', '')}:"
            f"{agent.get('tmux_window_index', '')}."
            f"{agent.get('tmux_pane_index', '')}"
        )
        project = _scrub_for_tsv(agent.get("project_path", ""))
        parent_full = agent.get("parent_agent_id")
        parent = parent_full if parent_full else "-"
        active = "true" if agent.get("active") else "false"
        print(
            f"{agent_id}\t{label}\t{role}\t{capability}\t"
            f"{container_short}\t{pane}\t{project}\t{parent}\t{active}"
        )
    return 0


def _set_role_command(args: argparse.Namespace) -> int:
    _, resolved = _resolve_socket_with_paths()
    socket_path = resolved.path

    # Client-side mirror of FR-012 / FR-011 so we fail fast without a
    # round-trip when the operator passed an obviously unsafe combo.
    if args.role == "swarm":
        print(
            "error: set-role --role swarm is rejected; use "
            "`agenttower register-self --role swarm --parent <agent-id>` instead",
            file=sys.stderr,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "swarm_role_via_set_role_rejected",
                            "message": "set-role --role swarm is rejected",
                        },
                    }
                )
            )
        return 3
    if args.role == "master" and not args.confirm:
        print(
            "error: master role assignment requires --confirm",
            file=sys.stderr,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "master_confirm_required",
                            "message": "master role assignment requires --confirm",
                        },
                    }
                )
            )
        return 3

    params = {
        "agent_id": args.target,
        "role": args.role,
        "confirm": bool(args.confirm),
    }
    return _send_set_command(socket_path, "set_role", params, args.json)


def _set_label_command(args: argparse.Namespace) -> int:
    _, resolved = _resolve_socket_with_paths()
    params = {"agent_id": args.target, "label": args.label}
    return _send_set_command(resolved.path, "set_label", params, args.json)


def _set_capability_command(args: argparse.Namespace) -> int:
    _, resolved = _resolve_socket_with_paths()
    params = {"agent_id": args.target, "capability": args.capability}
    return _send_set_command(resolved.path, "set_capability", params, args.json)


def _send_set_command(
    socket_path: Path,
    method: str,
    params: dict[str, Any],
    json_mode: bool,
) -> int:
    try:
        result = send_request(
            socket_path,
            method,
            params,
            connect_timeout=1.0,
            read_timeout=5.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        return _emit_daemon_error(exc, json_mode)
    if json_mode:
        print(json.dumps({"ok": True, "result": result}))
    else:
        print(f"agent_id={result.get('agent_id')}")
        print(f"field={result.get('field')}")
        print(f"prior_value={result.get('prior_value')}")
        print(f"new_value={result.get('new_value')}")
        print(f"audit_appended={str(result.get('audit_appended', False)).lower()}")
    return 0


def _emit_register_error(exc: Any, json_mode: bool) -> int:
    """Map a client-side ``RegistrationError`` to the CLI exit-code surface.

    Closed-set wire codes are surfaced verbatim. Daemon-unavailable is
    handled separately by the caller (exit code 2). Every other code
    yields exit 3 to match the FEAT-002/003/004 daemon-error convention.
    """
    if json_mode:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {"code": exc.code, "message": exc.message},
                }
            )
        )
    else:
        print(f"error: {exc.message}", file=sys.stderr)
        print(f"code: {exc.code}", file=sys.stderr)
    return 1 if exc.code == "host_context_unsupported" else 3


def _emit_daemon_error(exc: DaemonError, json_mode: bool) -> int:
    if json_mode:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {"code": exc.code, "message": exc.message},
                }
            )
        )
    else:
        print(f"error: {exc.message}", file=sys.stderr)
        print(f"code: {exc.code}", file=sys.stderr)
    return 3


def _scrub_for_tsv(value: str) -> str:
    """Replace embedded ``\\t`` and ``\\n`` with single spaces.

    FR-029 / FR-033: free-text fields are sanitized at write time, but
    we apply the same byte class here defensively so the TSV layout
    can't be broken by a label that happened to contain a tab.
    """
    if not isinstance(value, str):
        return ""
    return value.replace("\t", " ").replace("\n", " ")


def main(argv: list[str] | None = None) -> int:
    """Run the AgentTower CLI."""
    # A2 / FR-025 production guard: refuse to honor a leaked
    # AGENTTOWER_TEST_PROC_ROOT in a non-test invocation. Runs before any
    # parsing or path resolution so the guard cannot be bypassed by a
    # mid-flight code path.
    _guard_production_test_seam_unset()
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler: Any = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
