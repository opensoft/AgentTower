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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agents.errors import RegistrationError

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
    # FEAT-008 FR-045: surface every [events] default with its resolved
    # value so operators can see the effective configuration. Lines are
    # appended to the existing FEAT-001..005 keys; FR-019 KEY ordering
    # for the original seven entries is preserved.
    from .config import load_events_block
    events_cfg = load_events_block(paths.config_file)
    print(f"EVENTS_READER_CYCLE_WALLCLOCK_CAP_SECONDS={events_cfg.reader_cycle_wallclock_cap_seconds}")
    print(f"EVENTS_PER_CYCLE_BYTE_CAP_BYTES={events_cfg.per_cycle_byte_cap_bytes}")
    print(f"EVENTS_PER_EVENT_EXCERPT_CAP_BYTES={events_cfg.per_event_excerpt_cap_bytes}")
    print(f"EVENTS_DEBOUNCE_ACTIVITY_WINDOW_SECONDS={events_cfg.debounce_activity_window_seconds}")
    print(f"EVENTS_PANE_EXITED_GRACE_SECONDS={events_cfg.pane_exited_grace_seconds}")
    print(f"EVENTS_LONG_RUNNING_GRACE_SECONDS={events_cfg.long_running_grace_seconds}")
    print(f"EVENTS_DEFAULT_PAGE_SIZE={events_cfg.default_page_size}")
    print(f"EVENTS_MAX_PAGE_SIZE={events_cfg.max_page_size}")
    print(f"EVENTS_FOLLOW_LONG_POLL_MAX_SECONDS={events_cfg.follow_long_poll_max_seconds}")
    print(f"EVENTS_FOLLOW_SESSION_IDLE_TIMEOUT_SECONDS={events_cfg.follow_session_idle_timeout_seconds}")
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

    from .agents.validation import VALID_CAPABILITIES, VALID_ROLES

    _ROLES_LIST = ", ".join(VALID_ROLES)
    _CAPS_LIST = ", ".join(VALID_CAPABILITIES)
    _AGENT_ID_HELP = "target agent_id (matches agt_<12-hex-lowercase>)"

    register_self = subparsers.add_parser(
        "register-self",
        help="register the current tmux pane as an AgentTower agent",
        description="register the current tmux pane as an AgentTower agent",
    )
    register_self.add_argument(
        "--role",
        default=argparse.SUPPRESS,
        help=f"role to assign on first registration (one of: {_ROLES_LIST}). "
        "register-self never accepts master; use set-role for promotion (FR-010).",
    )
    register_self.add_argument(
        "--capability",
        default=argparse.SUPPRESS,
        help=f"capability descriptor (one of: {_CAPS_LIST}).",
    )
    register_self.add_argument(
        "--label",
        default=argparse.SUPPRESS,
        help="free-text label, sanitized + bounded to 64 chars.",
    )
    register_self.add_argument(
        "--project",
        default=argparse.SUPPRESS,
        help="absolute path inside the container (no '..' segments, "
        "no NUL, ≤ 4096 chars).",
    )
    register_self.add_argument(
        "--parent",
        default=argparse.SUPPRESS,
        help="parent agent_id when --role swarm (immutable after creation).",
    )
    register_self.add_argument(
        "--attach-log",
        action="store_true",
        help="(FEAT-007 FR-034) atomically attach a tmux pipe-pane log "
        "after registration; if attach fails, registration is rolled back.",
    )
    register_self.add_argument(
        "--log",
        default=argparse.SUPPRESS,
        help="(with --attach-log) explicit log path (host-visible or "
        "container-visible through the bench mount); default = "
        "~/.local/state/opensoft/agenttower/logs/<container>/<agent>.log",
    )
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
    set_role.add_argument("--target", required=True, help=_AGENT_ID_HELP)
    set_role.add_argument(
        "--role",
        required=True,
        help=f"new role (one of: {_ROLES_LIST}). "
        "swarm rejected (use register-self); master requires --confirm.",
    )
    set_role.add_argument(
        "--confirm",
        action="store_true",
        help="required when --role master (FR-011).",
    )
    set_role.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    set_role.set_defaults(_handler=_set_role_command)

    set_label = subparsers.add_parser(
        "set-label",
        help="change an agent's free-text label",
        description="change an agent's free-text label",
    )
    set_label.add_argument("--target", required=True, help=_AGENT_ID_HELP)
    set_label.add_argument(
        "--label",
        required=True,
        help="new label (sanitized + bounded to 64 chars).",
    )
    set_label.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    set_label.set_defaults(_handler=_set_label_command)

    set_capability = subparsers.add_parser(
        "set-capability",
        help="change an agent's capability descriptor",
        description="change an agent's capability descriptor",
    )
    set_capability.add_argument("--target", required=True, help=_AGENT_ID_HELP)
    set_capability.add_argument(
        "--capability",
        required=True,
        help=f"new capability (one of: {_CAPS_LIST}).",
    )
    set_capability.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    set_capability.set_defaults(_handler=_set_capability_command)

    # ------------------------------------------------------------------ #
    # FEAT-007 — attach-log / detach-log (FR-031, FR-032, FR-033, FR-037a)
    # ------------------------------------------------------------------ #

    attach_log = subparsers.add_parser(
        "attach-log",
        help="attach a tmux pipe-pane log to an AgentTower agent",
        description=(
            "attach a registered AgentTower agent's pane output to a "
            "host-visible log file via tmux pipe-pane (FEAT-007)"
        ),
    )
    attach_log.add_argument("--target", required=True, help=_AGENT_ID_HELP)
    attach_log.add_argument(
        "--log",
        default=argparse.SUPPRESS,
        help="explicit log path (host-visible or container-visible through "
        "the bench mount); defaults to "
        "~/.local/state/opensoft/agenttower/logs/<container>/<agent>.log",
    )
    attach_log.add_argument(
        "--status",
        action="store_true",
        help="universal read-only status inspection (FR-032)",
    )
    attach_log.add_argument(
        "--preview",
        type=int,
        default=argparse.SUPPRESS,
        help="emit the last N lines (1..200) of the host log file, redacted (FR-033)",
    )
    attach_log.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    attach_log.set_defaults(_handler=_attach_log_command)

    detach_log = subparsers.add_parser(
        "detach-log",
        help="stop piping pane output to the host log file",
        description="stop piping pane output and mark the attachment detached (FR-037a)",
    )
    detach_log.add_argument("--target", required=True, help=_AGENT_ID_HELP)
    detach_log.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
    detach_log.set_defaults(_handler=_detach_log_command)

    # ------------------------------------------------------------------ #
    # FEAT-008 — events (FR-030 / FR-031 / FR-032 / FR-033 / FR-035a)
    # ------------------------------------------------------------------ #

    events_cmd = subparsers.add_parser(
        "events",
        help="list classified events from attached agents",
        description=(
            "list classified events emitted by the FEAT-008 reader from "
            "attached pane logs (FEAT-008)"
        ),
    )
    events_cmd.add_argument(
        "--target",
        default=None,
        help=(
            "filter to one agent id (agt_<12 hex>); "
            "run 'agenttower list-agents' to find ids. "
            "Omit to list events from all agents."
        ),
    )
    events_cmd.add_argument(
        "--type",
        action="append",
        default=[],
        help="filter to one event type (repeatable; e.g. --type error --type test_failed)",
    )
    events_cmd.add_argument(
        "--since",
        default=None,
        help="lower bound on observed_at (inclusive ISO-8601 with offset)",
    )
    events_cmd.add_argument(
        "--until",
        default=None,
        help="upper bound on observed_at (exclusive ISO-8601 with offset)",
    )
    events_cmd.add_argument(
        "--limit",
        type=int,
        default=None,
        help="page size (default 50, max 50)",
    )
    events_cmd.add_argument(
        "--cursor",
        default=None,
        help="opaque pagination cursor returned by a previous --json response",
    )
    events_cmd.add_argument(
        "--reverse",
        action="store_true",
        help="newest-first instead of oldest-first",
    )
    events_cmd.add_argument(
        "--follow",
        action="store_true",
        help="stream new events as they are emitted",
    )
    events_cmd.add_argument(
        "--json",
        action="store_true",
        help=JSON_LINE_HELP,
    )
    events_cmd.add_argument(
        "--classifier-rules",
        action="store_true",
        help=argparse.SUPPRESS,  # hidden debug flag
    )
    events_cmd.set_defaults(_handler=_events_command)

    # FEAT-009 — send-input subparser (T058 / contracts/cli-send-input.md).
    send_input = subparsers.add_parser(
        "send-input",
        help=(
            "send a prompt to another agent's tmux pane via the safe "
            "queue (FEAT-009; bench-container only)"
        ),
        description=(
            "Enqueue an envelope-wrapped prompt for delivery to another "
            "registered agent's tmux pane. Refuses host-side invocation "
            "with sender_not_in_pane (FR-006). Default behavior waits for "
            "the row to reach a terminal state (FR-009)."
        ),
    )
    send_input.add_argument(
        "--target",
        required=True,
        help="recipient agent_id (agt_<12 hex>) or unique label",
    )
    body_group = send_input.add_mutually_exclusive_group(required=True)
    body_group.add_argument(
        "--message",
        default=None,
        help="body text supplied inline (mutually exclusive with --message-file)",
    )
    body_group.add_argument(
        "--message-file",
        default=None,
        help=(
            "path to a file containing the body (use '-' for stdin; "
            "mutually exclusive with --message)"
        ),
    )
    send_input.add_argument(
        "--no-wait",
        action="store_true",
        help="return immediately after enqueue (default waits for terminal)",
    )
    send_input.add_argument(
        "--wait-timeout",
        type=float,
        default=10.0,
        help="seconds to wait for terminal state (default 10.0; ignored under --no-wait)",
    )
    send_input.add_argument(
        "--json",
        action="store_true",
        help=JSON_LINE_HELP,
    )
    send_input.set_defaults(_handler=_send_input_command)

    # FEAT-009 — queue subparser (T070 / contracts/cli-queue.md).
    queue_cmd = subparsers.add_parser(
        "queue",
        help="inspect and operate the prompt queue (FEAT-009)",
        description=(
            "List or operate FEAT-009 message_queue rows. With no "
            "subcommand, lists matching rows. Subcommands: approve, "
            "delay, cancel."
        ),
    )
    queue_cmd.add_argument(
        "--state",
        choices=("queued", "blocked", "delivered", "canceled", "failed"),
        default=None,
        help="filter to one state",
    )
    queue_cmd.add_argument(
        "--target", default=None,
        help="filter to one target agent_id or label",
    )
    queue_cmd.add_argument(
        "--sender", default=None,
        help="filter to one sender agent_id or label",
    )
    queue_cmd.add_argument(
        "--since", default=None,
        help="lower bound on enqueued_at (inclusive ISO-8601 UTC)",
    )
    queue_cmd.add_argument(
        "--limit", type=int, default=100,
        help="page size 1..1000 (default 100)",
    )
    queue_cmd.add_argument(
        "--json", action="store_true", help=JSON_LINE_HELP,
    )
    queue_cmd.set_defaults(_handler=_queue_list_command)

    queue_subs = queue_cmd.add_subparsers(dest="queue_subcommand", metavar="subcommand")
    for op_name in ("approve", "delay", "cancel"):
        op = queue_subs.add_parser(
            op_name,
            help=f"{op_name} a queued message by message_id",
            description=(
                f"Transition the row identified by <message-id> via the "
                f"operator-action surface ({op_name}). See "
                "contracts/cli-queue.md for the closed-set exit codes."
            ),
        )
        op.add_argument("message_id", help="the message_id to operate on")
        op.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
        op.set_defaults(_handler=_queue_operator_command_factory(op_name))

    # FEAT-009 — routing subparser (T075 / contracts/cli-routing.md).
    routing_cmd = subparsers.add_parser(
        "routing",
        help="control or inspect the global routing kill switch (FEAT-009)",
        description=(
            "Subcommands: enable (host-only), disable (host-only), "
            "status (any caller). See contracts/cli-routing.md for "
            "the closed-set exit codes."
        ),
    )
    routing_cmd.set_defaults(_handler=lambda args: _print_subusage_and_exit(routing_cmd))
    routing_subs = routing_cmd.add_subparsers(
        dest="routing_subcommand", metavar="subcommand",
    )
    for op_name in ("enable", "disable", "status"):
        op = routing_subs.add_parser(
            op_name,
            help=f"routing {op_name}",
            description=(
                f"routing {op_name} — see contracts/cli-routing.md "
                f"for caller-context restrictions."
            ),
        )
        op.add_argument("--json", action="store_true", help=JSON_LINE_HELP)
        op.set_defaults(_handler=_routing_command_factory(op_name))

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

    # Pre-flight CLI guard: ``--log`` only meaningful with ``--attach-log``.
    # Surface this BEFORE socket resolution so the operator sees a clean
    # bad_request rather than daemon_unavailable when typing the wrong flag.
    if hasattr(args, "log") and not getattr(args, "attach_log", False):
        _emit_local_error(
            "bad_request",
            "register-self: --log requires --attach-log",
            args.json,
        )
        return 3

    _, resolved = _resolve_socket_with_paths()
    socket_path = resolved.path

    # Client-side mirror of FR-010 (review-pass-6 N13). Rejecting
    # ``--role master`` before the multi-call resolve_pane_composite_key
    # round-trip is symmetric with the set-role swarm gate: we save the
    # operator several Docker/tmux scans on a known-bad combo.
    if hasattr(args, "role") and args.role == "master":
        _emit_local_error(
            "master_via_register_self_rejected",
            "register-self cannot assign role=master; register first, "
            "then run `agenttower set-role --role master --confirm`",
            args.json,
        )
        return 3

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

    # Forward-compat handshake (FR-040 / edge case line 79). The CLI
    # advertises the schema version it was built against so the daemon
    # can refuse with ``schema_version_newer`` when its own schema has
    # advanced past what the CLI knows. Without this hint the server
    # cannot detect a stale CLI calling a newer daemon.
    from .config_doctor import MAX_SUPPORTED_SCHEMA_VERSION

    params: dict[str, Any] = {
        "schema_version": int(MAX_SUPPORTED_SCHEMA_VERSION),
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

    # FEAT-007 / FR-034: --attach-log opts into the atomic register+attach
    # surface. The optional --log overrides the FR-005 default canonical path.
    # We send a nested ``attach_log`` object the daemon recognizes; absent
    # means no attach and the daemon falls back to FEAT-006-only behavior.
    if getattr(args, "attach_log", False):
        attach_log_payload: dict[str, Any] = {}
        if hasattr(args, "log"):
            attach_log_payload["log_path"] = args.log
        params["attach_log"] = attach_log_payload

    try:
        result = send_request(
            socket_path,
            "register_agent",
            params,
            connect_timeout=1.0,
            read_timeout=10.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        return _emit_daemon_error(exc, args.json)

    if args.json:
        print(json.dumps({"ok": True, "result": result}))
    else:
        # Defensive scrubbing on free-text fields: daemon-side sanitization
        # already strips C0 controls, but applying _scrub_for_tsv here
        # keeps the one-line-per-key shape robust if a future schema
        # ever loosens that guarantee.
        print(f"agent_id={result.get('agent_id')}")
        print(f"role={result.get('role')}")
        print(f"capability={result.get('capability')}")
        print(f"label={_scrub_for_tsv(result.get('label', ''))}")
        print(f"project_path={_scrub_for_tsv(result.get('project_path', ''))}")
        print(f"parent_agent_id={result.get('parent_agent_id') or '-'}")
        print(f"created_or_reactivated={result.get('created_or_reactivated')}")
        attach_block = result.get("attach_log")
        if attach_block is not None:
            print(
                f"attached attachment_id={attach_block.get('attachment_id')} "
                f"path={attach_block.get('log_path')} "
                f"status={attach_block.get('status')}"
            )
    return 0


def _list_agents_command(args: argparse.Namespace) -> int:
    from .config_doctor import MAX_SUPPORTED_SCHEMA_VERSION

    _, resolved = _resolve_socket_with_paths()
    socket_path = resolved.path

    # Every FEAT-006 CLI request advertises the schema version it was
    # built against so the daemon can refuse with ``schema_version_newer``
    # when its own schema has advanced past what the CLI knows
    # (FR-040 / review-pass-6 K1+N14). Without this hint, the daemon-side
    # forward-compat gate is unreachable for list-agents and set-*.
    params: dict[str, Any] = {"schema_version": int(MAX_SUPPORTED_SCHEMA_VERSION)}
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
        # Defensive int coercion: schema stores tmux_window_index /
        # tmux_pane_index as NOT NULL ints, but a future schema drift
        # or test fixture sending null would otherwise render
        # "main:None.0". Fall back to 0 (which is a real pane index
        # so still readable) rather than emitting "None".
        window_idx = agent.get("tmux_window_index")
        pane_idx = agent.get("tmux_pane_index")
        pane = (
            f"{_scrub_for_tsv(agent.get('tmux_session_name', ''))}:"
            f"{int(window_idx) if window_idx is not None else 0}."
            f"{int(pane_idx) if pane_idx is not None else 0}"
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


def _validate_target_shape(target: Any, json_mode: bool) -> int | None:
    """Validate a ``--target`` arg against ``agt_<12-hex-lowercase>``.

    Returns ``None`` if the target is well-formed; otherwise emits a
    ``value_out_of_set`` error via the shared helper and returns the
    CLI exit code (3). Centralizing the gate lets each set-* command
    fail fast on a bad target before any role/label/capability gate
    runs (R-020 / contracts/cli.md), so a single invocation surfaces
    the most actionable error rather than ping-ponging the user
    between rejections.
    """
    from .agents.identifiers import AGENT_ID_RE

    if not isinstance(target, str) or not AGENT_ID_RE.match(target):
        _emit_local_error(
            "value_out_of_set",
            f"--target must match agt_<12-hex-lowercase>; got {target!r}",
            json_mode,
        )
        return 3
    return None


def _set_role_command(args: argparse.Namespace) -> int:
    _, resolved = _resolve_socket_with_paths()
    socket_path = resolved.path

    # Target-shape gate first so a malformed --target surfaces before
    # any role-specific rejection (review-pass-6 N32).
    target_err = _validate_target_shape(args.target, args.json)
    if target_err is not None:
        return target_err

    # Client-side mirror of FR-012 / FR-011 so we fail fast without a
    # round-trip when the operator passed an obviously unsafe combo.
    # The shared ``_emit_local_error`` helper enforces the ``--json``
    # purity contract AND the established ``error: <msg>`` /
    # ``code: <token>`` text-mode shape so both branches stay aligned.
    if args.role == "swarm":
        _emit_local_error(
            "swarm_role_via_set_role_rejected",
            # Single actionable message in both formats — JSON consumers
            # shouldn't have to round-trip back to docs for the recovery
            # step.
            "set-role --role swarm is rejected; use "
            "`agenttower register-self --role swarm --parent <agent-id>` instead",
            args.json,
        )
        return 3
    if args.role == "master" and not args.confirm:
        _emit_local_error(
            "master_confirm_required",
            "master role assignment requires --confirm",
            args.json,
        )
        return 3

    from .config_doctor import MAX_SUPPORTED_SCHEMA_VERSION

    params = {
        "schema_version": int(MAX_SUPPORTED_SCHEMA_VERSION),
        "agent_id": args.target,
        "role": args.role,
        "confirm": bool(args.confirm),
    }
    return _send_set_command(socket_path, "set_role", params, args.json)


def _set_label_command(args: argparse.Namespace) -> int:
    from .config_doctor import MAX_SUPPORTED_SCHEMA_VERSION

    target_err = _validate_target_shape(args.target, args.json)
    if target_err is not None:
        return target_err
    _, resolved = _resolve_socket_with_paths()
    params = {
        "schema_version": int(MAX_SUPPORTED_SCHEMA_VERSION),
        "agent_id": args.target,
        "label": args.label,
    }
    return _send_set_command(resolved.path, "set_label", params, args.json)


def _set_capability_command(args: argparse.Namespace) -> int:
    from .config_doctor import MAX_SUPPORTED_SCHEMA_VERSION

    target_err = _validate_target_shape(args.target, args.json)
    if target_err is not None:
        return target_err
    _, resolved = _resolve_socket_with_paths()
    params = {
        "schema_version": int(MAX_SUPPORTED_SCHEMA_VERSION),
        "agent_id": args.target,
        "capability": args.capability,
    }
    return _send_set_command(resolved.path, "set_capability", params, args.json)


def _send_set_command(
    socket_path: Path,
    method: str,
    params: dict[str, Any],
    json_mode: bool,
) -> int:
    # Each ``set-*`` command pre-validates ``--target`` via
    # :func:`_validate_target_shape` before reaching this transport
    # helper, so the AGENT_ID_RE gate doesn't repeat here.
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


# ---------------------------------------------------------------------------
# FEAT-007 — attach-log / detach-log (FR-031, FR-032, FR-033, FR-037a)
# ---------------------------------------------------------------------------


def _attach_log_command(args: argparse.Namespace) -> int:
    """Dispatch attach-log / --status / --preview based on supplied flags."""
    from .config_doctor import MAX_SUPPORTED_SCHEMA_VERSION

    target_err = _validate_target_shape(args.target, args.json)
    if target_err is not None:
        return target_err
    _, resolved = _resolve_socket_with_paths()
    socket_path = resolved.path

    schema_version = int(MAX_SUPPORTED_SCHEMA_VERSION)

    # --status mode (FR-032): universal read-only inspection.
    if args.status:
        if hasattr(args, "preview") or hasattr(args, "log"):
            _emit_local_error(
                "bad_request",
                "attach-log: --status is mutually exclusive with --preview / --log",
                args.json,
            )
            return 3
        params = {
            "schema_version": schema_version,
            "agent_id": args.target,
        }
        try:
            result = send_request(
                socket_path,
                "attach_log_status",
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
            attachment = result.get("attachment")
            offset = result.get("offset")
            print(f"agent_id={result.get('agent_id')}")
            if attachment is None:
                print("attachment=null offset=null")
            else:
                print(f"attachment_id={attachment.get('attachment_id')}")
                print(f"path={attachment.get('log_path')}")
                print(f"status={attachment.get('status')}")
                print(f"source={attachment.get('source')}")
                print(f"attached_at={attachment.get('attached_at')}")
                print(f"last_status_at={attachment.get('last_status_at')}")
                if offset is not None:
                    print(f"byte_offset={offset.get('byte_offset')}")
                    print(f"line_offset={offset.get('line_offset')}")
                    print(f"last_event_offset={offset.get('last_event_offset')}")
                    fi = offset.get("file_inode")
                    print(f"file_inode={fi if fi is not None else '-'}")
                    print(f"file_size_seen={offset.get('file_size_seen')}")
        return 0

    # --preview mode (FR-033).
    if hasattr(args, "preview"):
        if hasattr(args, "log"):
            _emit_local_error(
                "bad_request",
                "attach-log: --preview is mutually exclusive with --log",
                args.json,
            )
            return 3
        n = args.preview
        if not isinstance(n, int) or n < 1 or n > 200:
            _emit_local_error(
                "value_out_of_set",
                f"--preview N must be between 1 and 200; got {n}",
                args.json,
            )
            return 3
        params = {
            "schema_version": schema_version,
            "agent_id": args.target,
            "lines": int(n),
        }
        try:
            result = send_request(
                socket_path,
                "attach_log_preview",
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
            for line in result.get("lines", []):
                print(_scrub_for_tsv(line) if "\n" in line or "\t" in line else line)
        return 0

    # Default: attach mode (FR-031).
    params = {
        "schema_version": schema_version,
        "agent_id": args.target,
    }
    if hasattr(args, "log"):
        params["log_path"] = args.log
    try:
        result = send_request(
            socket_path,
            "attach_log",
            params,
            connect_timeout=1.0,
            read_timeout=10.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        return _emit_daemon_error(exc, args.json)
    if args.json:
        print(json.dumps({"ok": True, "result": result}))
    else:
        verb = "attached" if result.get("is_new") else "already-attached"
        print(f"{verb} agent_id={result.get('agent_id')}")
        print(f"attachment_id={result.get('attachment_id')}")
        print(f"path={result.get('log_path')}")
        print(f"source={result.get('source')}")
        print(f"status={result.get('status')}")
    return 0


def _detach_log_command(args: argparse.Namespace) -> int:
    """Send the detach_log socket method and render the response (FR-037a)."""
    from .config_doctor import MAX_SUPPORTED_SCHEMA_VERSION

    target_err = _validate_target_shape(args.target, args.json)
    if target_err is not None:
        return target_err
    _, resolved = _resolve_socket_with_paths()
    socket_path = resolved.path

    params = {
        "schema_version": int(MAX_SUPPORTED_SCHEMA_VERSION),
        "agent_id": args.target,
    }
    try:
        result = send_request(
            socket_path,
            "detach_log",
            params,
            connect_timeout=1.0,
            read_timeout=10.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 2
    except DaemonError as exc:
        return _emit_daemon_error(exc, args.json)
    if args.json:
        print(json.dumps({"ok": True, "result": result}))
    else:
        print(f"detached agent_id={result.get('agent_id')}")
        print(f"attachment_id={result.get('attachment_id')}")
        print(f"path={result.get('log_path')}")
        print(f"status={result.get('status')}")
    return 0


def _emit_local_error(code: str, message: str, json_mode: bool) -> None:
    """Emit a local (pre-flight, client-side) closed-set error.

    Centralizes the ``--json`` purity contract and the established
    ``error: <msg>`` / ``code: <token>`` text-mode shape so every
    pre-flight rejection stays consistent regardless of where it
    originates. Caller picks the exit code so this helper is reusable
    for both ``host_context_unsupported`` (exit 1) and the closed-set
    daemon-error mirror (exit 3) cases.
    """
    if json_mode:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {"code": code, "message": message},
                }
            )
        )
    else:
        print(f"error: {message}", file=sys.stderr)
        print(f"code: {code}", file=sys.stderr)


def _exit_code_for(code: str) -> int:
    """Map a closed-set error code to its CLI exit code (FR-032 / FR-040).

    ``host_context_unsupported`` is exit 1 (client-side context error —
    the operator is on the host shell, not in a bench container).
    FEAT-008 ``events.*`` error codes use distinct exit codes per
    ``contracts/socket-events.md`` §"Error envelope additions" so
    scripts can distinguish ``agent_not_found`` from a generic daemon
    error. Every other closed-set code is exit 3 (FEAT-002 / FEAT-005
    daemon-error convention). ``daemon_unavailable`` is handled by
    callers (exit 2) before any error code is even raised.
    """
    if code == "host_context_unsupported":
        return 1
    if code == "agent_not_found":
        return 4
    if code == "events_session_unknown":
        return 5
    if code == "events_session_expired":
        return 8
    if code == "events_invalid_cursor":
        return 6
    if code == "events_filter_invalid":
        return 7
    return 3


def _emit_register_error(exc: "RegistrationError", json_mode: bool) -> int:
    """Map a client-side ``RegistrationError`` to the CLI exit-code surface.

    Closed-set wire codes are surfaced verbatim via the shared
    ``_emit_local_error`` helper so JSON purity / text-mode shape stay
    aligned with every other pre-flight emitter.
    """
    _emit_local_error(exc.code, exc.message, json_mode)
    return _exit_code_for(exc.code)


def _emit_daemon_error(exc: DaemonError, json_mode: bool) -> int:
    """Map a daemon-side ``DaemonError`` to the CLI exit-code surface.

    Routed through the same exit-code mapper as ``_emit_register_error``
    so a daemon-emitted ``host_context_unsupported`` (in principle
    raisable any time daemon code surfaces it) exits 1, matching the
    client-side mapping. Without this symmetry, the same closed-set
    code would map to different exit codes depending on which side
    raised it.
    """
    _emit_local_error(exc.code, exc.message, json_mode)
    return _exit_code_for(exc.code)


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


# ---------------------------------------------------------------------------
# FEAT-008 — `agenttower events` (FR-030 / FR-031 / FR-032 / FR-035a)
# ---------------------------------------------------------------------------


def _sanitize_for_terminal(s: str) -> str:
    """Escape control bytes before printing to a terminal (CRIT-1).

    Log content (event excerpts) flows through the redaction utility but
    is otherwise byte-for-byte from the PTY stream. ANSI/OSC escape
    sequences (``\\x1b[...m``, ``\\x1b]0;...\\x07``), carriage returns,
    backspaces, and tabs survive redaction. If we ``print()`` them
    verbatim, an attacker-controlled log line can clear the operator's
    screen, spoof the terminal title, or corrupt column alignment.

    This helper produces a printable ASCII-safe string by escaping every
    C0 control byte (\\x00-\\x1f) other than the printable forms
    documented for events (we keep nothing — the human-mode renderer
    pre-trims to a single line, so newlines should not survive). The
    rendering uses ``\\xNN`` escapes that are immediately readable.

    JSON output is unaffected — Python's json encoder already escapes
    these as ``\\u00xx``.
    """
    if not s:
        return ""
    out: list[str] = []
    for ch in s:
        codepoint = ord(ch)
        if codepoint < 0x20 or codepoint == 0x7f:
            # C0 control set + DEL → escape.
            out.append(f"\\x{codepoint:02x}")
        else:
            out.append(ch)
    return "".join(out)


_VALID_EVENT_TYPES = frozenset(
    {
        "activity", "waiting_for_input", "completed", "error",
        "test_failed", "test_passed", "manual_review_needed",
        "long_running", "pane_exited", "swarm_member_reported",
    }
)


def _events_validate_args_local(args: argparse.Namespace) -> int | None:
    """Client-side argument validation BEFORE any daemon round-trip.

    Returns None when the args are well-formed; otherwise emits a local
    ``bad_request`` / ``value_out_of_set`` error and returns the CLI
    exit code (2 for argument errors per
    ``contracts/cli-events.md`` C-CLI-EVT-001).
    """
    from .agents.identifiers import AGENT_ID_RE

    if args.target is not None:
        if not isinstance(args.target, str) or not AGENT_ID_RE.match(args.target):
            _emit_local_error(
                "value_out_of_set",
                f"--target must match agt_<12-hex-lowercase>; got {args.target!r}",
                args.json,
            )
            return 2

    for t in (args.type or []):
        if t not in _VALID_EVENT_TYPES:
            _emit_local_error(
                "value_out_of_set",
                f"unknown event type {t!r}; valid: {sorted(_VALID_EVENT_TYPES)}",
                args.json,
            )
            return 2

    if args.limit is not None:
        if args.limit <= 0 or args.limit > 50:
            _emit_local_error(
                "bad_request",
                f"--limit must be in 1..50; got {args.limit}",
                args.json,
            )
            return 2

    for label, value in (("--since", args.since), ("--until", args.until)):
        if value is not None and not _is_iso8601_with_offset(value):
            _emit_local_error(
                "bad_request",
                f"{label} must be ISO-8601 with an explicit offset; got {value!r}",
                args.json,
            )
            return 2

    return None


def _is_iso8601_with_offset(value: str) -> bool:
    """Tolerant ISO-8601 sanity check: must end with ``Z`` or
    ``±HH:MM`` and parse via ``datetime.fromisoformat``."""
    from datetime import datetime as _dt

    if not isinstance(value, str) or not value:
        return False
    norm = value.replace("Z", "+00:00")
    try:
        parsed = _dt.fromisoformat(norm)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _events_command(args: argparse.Namespace) -> int:
    """``agenttower events`` (FEAT-008 list / follow / classifier-rules)."""
    _, resolved = _resolve_socket_with_paths()
    socket_path = resolved.path

    # T053: --limit / --cursor / --reverse are not allowed with --follow.
    if args.follow and (
        args.limit is not None or args.cursor is not None or args.reverse
    ):
        _emit_local_error(
            "bad_request",
            "--limit / --cursor / --reverse are not allowed with --follow",
            args.json,
        )
        return 2

    if args.follow:
        return _events_follow_loop(args, socket_path)

    if args.classifier_rules:
        try:
            result = send_request(
                socket_path, "events.classifier_rules", {},
                connect_timeout=2.0, read_timeout=5.0,
            )
        except DaemonUnavailable:
            print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
            return 3
        except DaemonError as exc:
            return _emit_daemon_error(exc, args.json)
        if args.json:
            print(json.dumps(result))
        else:
            print("priority  rule_id                     -> event_type")
            for r in result.get("rules", []):
                print(
                    f"{r['priority']:>9} {r['rule_id']:<26} -> {r['event_type']}"
                )
            print()
            print("synthetic rules (not regex; reader-synthesized):")
            for sid in result.get("synthetic_rule_ids", []):
                print(f"  {sid}")
        return 0

    err = _events_validate_args_local(args)
    if err is not None:
        return err

    params: dict[str, Any] = {}
    if args.target is not None:
        params["target"] = args.target
    if args.type:
        params["types"] = list(args.type)
    if args.since is not None:
        params["since"] = args.since
    if args.until is not None:
        params["until"] = args.until
    if args.limit is not None:
        params["limit"] = args.limit
    if args.cursor is not None:
        params["cursor"] = args.cursor
    if args.reverse:
        params["reverse"] = True

    try:
        result = send_request(
            socket_path, "events.list", params,
            connect_timeout=2.0, read_timeout=10.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 3
    except DaemonError as exc:
        return _emit_daemon_error(exc, args.json)

    events = result.get("events", []) or []
    next_cursor = result.get("next_cursor")

    if args.json:
        for event in events:
            print(json.dumps(event, separators=(",", ":")))
        if next_cursor is not None:
            print(json.dumps({"next_cursor": next_cursor}, separators=(",", ":")))
    else:
        for event in events:
            ts = (event.get("observed_at") or "")[:19].replace("T", " ")
            label = event.get("agent_id") or ""
            etype = event.get("event_type") or ""
            raw_excerpt = (
                (event.get("excerpt") or "").splitlines()[0]
                if event.get("excerpt")
                else ""
            )
            # CRIT-1 — sanitize control bytes before printing to a terminal.
            excerpt = _sanitize_for_terminal(raw_excerpt)
            print(f"{ts}  {label}  {etype:<22} {excerpt}")
        if next_cursor is not None:
            print(f"# next_cursor: {next_cursor}", file=sys.stderr)

    return 0


def _events_follow_loop(args: argparse.Namespace, socket_path: Path) -> int:
    """``agenttower events --follow`` long-poll loop (T052 / T053).

    Lifecycle (per ``contracts/cli-events.md`` C-CLI-EVT-002):

    1. Pre-flight client-side argument validation.
    2. ``events.follow_open`` — print backlog if --since was set, then
       loop on ``events.follow_next``.
    3. SIGINT → ``events.follow_close`` → exit 0.
    4. Daemon-unreachable mid-stream → exit 3.
    5. SIGPIPE (``BrokenPipeError`` from a closed downstream pipe) →
       ``events.follow_close`` → exit 0 (treat as success).
    """
    import signal

    err = _events_validate_args_local(args)
    if err is not None:
        return err

    open_params: dict[str, Any] = {}
    if args.target is not None:
        open_params["target"] = args.target
    if args.type:
        open_params["types"] = list(args.type)
    if args.since is not None:
        open_params["since"] = args.since

    try:
        opened = send_request(
            socket_path, "events.follow_open", open_params,
            connect_timeout=2.0, read_timeout=10.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return 3
    except DaemonError as exc:
        return _emit_daemon_error(exc, args.json)

    session_id: str = opened["session_id"]
    backlog_events = opened.get("backlog_events") or []

    # SIGINT handler flips a flag the loop checks between calls.
    interrupt_flag = {"set": False}

    def _on_sigint(signum, frame):  # noqa: ANN001
        interrupt_flag["set"] = True

    prior_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _on_sigint)

    def _print_event(event: dict[str, Any]) -> None:
        if args.json:
            print(json.dumps(event, separators=(",", ":")), flush=True)
        else:
            ts = (event.get("observed_at") or "")[:19].replace("T", " ")
            label = event.get("agent_id") or ""
            etype = event.get("event_type") or ""
            # CRIT-1 — sanitize control bytes before printing.
            excerpt = _sanitize_for_terminal(
                (event.get("excerpt") or "").splitlines()[0]
                if event.get("excerpt")
                else ""
            )
            print(
                f"{_sanitize_for_terminal(ts)}  {_sanitize_for_terminal(label)}  "
                f"{_sanitize_for_terminal(etype):<22} {excerpt}",
                flush=True,
            )

    try:
        # 1. Print backlog first (FR-033 — bounded backlog before live).
        for event in backlog_events:
            _print_event(event)

        # 2. Loop on follow_next until SIGINT or daemon unavailable.
        while not interrupt_flag["set"]:
            try:
                # Short server-side wait so SIGINT response is bounded
                # by ~1 second. The CLI loops and re-issues; the daemon
                # is happy to be polled more often than the default
                # 30 s long-poll budget.
                result = send_request(
                    socket_path,
                    "events.follow_next",
                    {"session_id": session_id, "max_wait_seconds": 1.0},
                    connect_timeout=2.0,
                    read_timeout=5.0,
                )
            except DaemonUnavailable:
                if interrupt_flag["set"]:
                    break
                print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
                return 3
            except DaemonError as exc:
                if exc.code in (
                    "events_session_unknown", "events_session_expired"
                ):
                    return _emit_daemon_error(exc, args.json)
                return _emit_daemon_error(exc, args.json)
            except KeyboardInterrupt:
                interrupt_flag["set"] = True
                break

            if interrupt_flag["set"]:
                break

            for event in result.get("events", []) or []:
                try:
                    _print_event(event)
                except BrokenPipeError:
                    # Downstream consumer closed the pipe (e.g.
                    # ``head -n N`` finished). Treat as clean exit.
                    return 0

            if not result.get("session_open", True):
                break

        return 0
    finally:
        # Always best-effort close.
        try:
            send_request(
                socket_path,
                "events.follow_close",
                {"session_id": session_id},
                connect_timeout=1.0,
                read_timeout=2.0,
            )
        except Exception:  # noqa: BLE001 — best effort
            pass
        signal.signal(signal.SIGINT, prior_handler)


# ---------------------------------------------------------------------------
# FEAT-009 — `agenttower send-input` (T058 / contracts/cli-send-input.md)
# ---------------------------------------------------------------------------


def _send_input_command(args: argparse.Namespace) -> int:
    """``agenttower send-input`` — enqueue a prompt via FEAT-009.

    Flow:
    1. Resolve the caller's container + pane composite key via
       :func:`agents.client_resolve.resolve_pane_composite_key`. Host-side
       invocations surface ``host_context_unsupported`` here and exit
       early — the daemon-side ``sender_not_in_pane`` is only reachable
       for bench-container callers who haven't registered.
    2. Discover the caller's own ``agent_id`` by listing agents in the
       resolved container and matching the pane composite key. Without
       this round-trip the daemon cannot enforce FR-021/FR-023 against
       the sender role.
    3. Read the body from ``--message`` (bytes(text, utf-8)) or
       ``--message-file`` (raw bytes, ``-`` for stdin); base64-encode
       it for the wire (contracts/socket-queue.md).
    4. Call ``queue.send_input`` with the resolved caller_pane.agent_id,
       the target string, the base64 body, and wait/timeout flags.
    5. Map the response to an integer exit code via
       :data:`routing.errors.CLI_EXIT_CODE_MAP`; render the row as
       either one human-readable line OR a single JSON object per
       ``contracts/queue-row-schema.md``.
    """
    from .agents.client_resolve import resolve_pane_composite_key
    from .agents.errors import RegistrationError
    from .routing.errors import CLI_EXIT_CODE_MAP

    json_mode = bool(args.json)

    # Read the body BEFORE the socket round-trip so a missing file or
    # invalid encoding fails fast without bothering the daemon.
    body_result = _send_input_read_body(args, json_mode=json_mode)
    if isinstance(body_result, int):
        return body_result
    body_bytes: bytes = body_result

    _, resolved = _resolve_socket_with_paths()
    socket_path = resolved.path

    # Step 1: resolve caller's pane composite key. Per
    # ``specs/009-safe-prompt-queue/contracts/cli-send-input.md``,
    # host-side ``send-input`` MUST surface ``sender_not_in_pane``
    # (exit 3) rather than the raw ``host_context_unsupported``
    # (exit 1) from the FEAT-006 resolver — send-input is the FEAT-009
    # surface, not register-self, and its closed-set error catalogue
    # uses ``sender_not_in_pane`` for the "you're not running inside a
    # bench pane" condition.
    try:
        target = resolve_pane_composite_key(
            socket_path=socket_path,
            env=os.environ,
            proc_root=os.environ.get("AGENTTOWER_TEST_PROC_ROOT"),
            connect_timeout=1.0,
            read_timeout=5.0,
        )
    except RegistrationError as exc:
        from .routing.errors import CLI_EXIT_CODE_MAP, SENDER_NOT_IN_PANE
        # Map every host-context / pane-resolution failure to the
        # FEAT-009 ``sender_not_in_pane`` closed-set code per the
        # CLI contract. Preserve the resolver's diagnostic message
        # so the operator sees the underlying reason verbatim.
        message = (
            f"send-input: {SENDER_NOT_IN_PANE} — {exc.code}: {exc}"
        )
        if json_mode:
            import json as _json
            print(_json.dumps({
                "ok": False,
                "error": {"code": SENDER_NOT_IN_PANE, "message": message},
            }))
        else:
            print(message, file=sys.stderr)
        return CLI_EXIT_CODE_MAP.get(SENDER_NOT_IN_PANE, 3)
    except DaemonUnavailable:
        # The main send-input RPC path returns CLI_EXIT_CODE_MAP[
        # 'daemon_unavailable'] (12). Use the same code here so
        # send-input's exit code is consistent across both the
        # caller-pane resolution step and the queue.send-input call.
        from .routing.errors import CLI_EXIT_CODE_MAP
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return CLI_EXIT_CODE_MAP.get("daemon_unavailable", 12)
    except DaemonError as exc:
        return _emit_daemon_error(exc, json_mode)

    # Step 2: discover caller's agent_id via list_agents filter +
    # pane-composite-key match.
    self_agent_id = _send_input_lookup_self_agent_id(
        socket_path=socket_path,
        target=target,
        json_mode=json_mode,
    )
    if isinstance(self_agent_id, int):
        return self_agent_id

    # Step 3: base64-encode body for the wire.
    import base64
    body_b64 = base64.b64encode(body_bytes).decode("ascii")

    params: dict[str, Any] = {
        "target": args.target,
        "body_bytes": body_b64,
        "caller_pane": {"agent_id": self_agent_id},
        "wait": not args.no_wait,
    }
    if not args.no_wait:
        params["wait_timeout_seconds"] = float(args.wait_timeout)

    # Step 4: call queue.send_input.
    # The daemon's wait budget caps at 300s; the socket read budget
    # MUST exceed that by a small margin so the wait can complete.
    read_timeout = max(15.0, float(args.wait_timeout) + 5.0) if not args.no_wait else 5.0
    try:
        result = send_request(
            socket_path, "queue.send_input", params,
            connect_timeout=2.0, read_timeout=read_timeout,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return CLI_EXIT_CODE_MAP.get("daemon_unavailable", 12)
    except DaemonError as exc:
        return _send_input_emit_daemon_error(exc, json_mode)

    # Step 5: render + map exit code from the row's terminal state.
    return _send_input_render(result, json_mode=json_mode, no_wait=args.no_wait)


def _send_input_read_body(
    args: argparse.Namespace, *, json_mode: bool,
) -> bytes | int:
    """Read the body from --message or --message-file. Return bytes on
    success, an integer exit code on failure (the bad_request /
    argparse exit 64 surface — body_* rejections live on the daemon
    side and are mapped through CLI_EXIT_CODE_MAP at the dispatch
    layer, not here)."""
    if args.message is not None and args.message_file is not None:
        # argparse's mutually_exclusive_group already enforces this; the
        # check stays as defense-in-depth for programmatic callers.
        _emit_local_error(
            "bad_request",
            "--message and --message-file are mutually exclusive",
            json_mode,
        )
        return 64

    if args.message is not None:
        return args.message.encode("utf-8")

    assert args.message_file is not None  # parser made one of the two required
    path_str = args.message_file
    if path_str == "-":
        return sys.stdin.buffer.read()
    try:
        return Path(path_str).read_bytes()
    except FileNotFoundError:
        # File-IO failure is NOT body validation (FR-003 is for control
        # bytes etc.); surface as the FEAT-002 argparse bad_request
        # (exit 64) so operators aren't misled into looking for invalid
        # bytes in the body.
        _emit_local_error(
            "bad_request",
            f"--message-file: file not found: {path_str}",
            json_mode,
        )
        return 64
    except OSError as exc:
        _emit_local_error(
            "bad_request",
            f"--message-file: cannot read {path_str}: {exc}",
            json_mode,
        )
        return 64


def _send_input_lookup_self_agent_id(
    *,
    socket_path: Path,
    target: Any,
    json_mode: bool,
) -> str | int:
    """List agents in the caller's container and match by pane key to
    find the caller's own ``agent_id``. Returns the agent_id string on
    success, an integer exit code on failure."""
    from .routing.errors import CLI_EXIT_CODE_MAP

    list_params = {"container_id": target.container_id, "active_only": True}
    try:
        list_result = send_request(
            socket_path, "list_agents", list_params,
            connect_timeout=1.0, read_timeout=5.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return CLI_EXIT_CODE_MAP.get("daemon_unavailable", 12)
    except DaemonError as exc:
        return _send_input_emit_daemon_error(exc, json_mode)
    agents = list_result.get("agents", []) or []
    pane_key = target.pane_key
    for record in agents:
        if (
            record.get("container_id") == pane_key[0]
            and record.get("tmux_socket_path") == pane_key[1]
            and record.get("tmux_session_name") == pane_key[2]
            and int(record.get("tmux_window_index", -1)) == pane_key[3]
            and int(record.get("tmux_pane_index", -1)) == pane_key[4]
            and record.get("tmux_pane_id") == pane_key[5]
        ):
            return str(record["agent_id"])
    # No matching agent — caller pane has never been registered. Per
    # specs/009-safe-prompt-queue/contracts/cli-send-input.md +
    # checklists/api.md CHK029, the closed-set code for "you're not
    # running inside a registered bench pane" is ``sender_not_in_pane``
    # (exit 3) — used for BOTH host-origin AND unregistered-pane
    # callers. Round-11 fixed the host-origin path; this is the
    # unregistered-pane path. ``sender_role_not_permitted`` (exit 4)
    # is reserved for the role-check failure on a REGISTERED pane.
    from .routing.errors import SENDER_NOT_IN_PANE
    _emit_local_error(
        SENDER_NOT_IN_PANE,
        "caller pane is not registered; run `agenttower register-self --role master --confirm`",
        json_mode,
    )
    return CLI_EXIT_CODE_MAP.get(SENDER_NOT_IN_PANE, 3)


def _send_input_emit_daemon_error(exc: DaemonError, json_mode: bool) -> int:
    """Map a daemon-side DaemonError to a send-input exit code.

    Uses the FEAT-009 CLI_EXIT_CODE_MAP first, falling back to the
    FEAT-002 `_exit_code_for` for codes outside the FEAT-009 set
    (e.g. ``host_context_unsupported``, ``schema_version_newer``).
    """
    from .routing.errors import CLI_EXIT_CODE_MAP

    _emit_local_error(exc.code, exc.message, json_mode)
    if exc.code in CLI_EXIT_CODE_MAP:
        return CLI_EXIT_CODE_MAP[exc.code]
    return _exit_code_for(exc.code)


def _send_input_render(
    row: dict[str, Any], *, json_mode: bool, no_wait: bool,
) -> int:
    """Render the row payload to stdout (or stderr on failure) and
    return the integer exit code mapped from the row's terminal state."""
    from .routing.errors import CLI_EXIT_CODE_MAP

    state = row.get("state")
    block_reason = row.get("block_reason")
    failure_reason = row.get("failure_reason")
    waited_to_terminal = bool(row.get("waited_to_terminal", False))

    # Determine the closed-set string code for exit mapping.
    #
    # State precedence (deliberate):
    #
    # 1. ``delivered`` → success.
    # 2. ``blocked`` → the row was refused with a closed-set
    #    ``block_reason``. That reason — NOT ``delivery_wait_timeout``
    #    — is what the operator needs to act on. This holds whether
    #    the row was blocked at enqueue (e.g. ``kill_switch_off``,
    #    ``target_role_not_permitted``) OR an operator delayed it
    #    mid-wait — in both cases the actionable signal is the
    #    ``block_reason``, not "the wait elapsed".
    # 3. ``failed`` / ``canceled`` → terminal, use the matching code.
    # 4. ``queued`` after ``wait=true`` returns non-terminal → the
    #    wait budget elapsed without the worker reaching terminal;
    #    map to ``delivery_wait_timeout`` per FR-009.
    # 5. ``queued`` after ``--no-wait`` → success at enqueue.
    if state == "delivered":
        exit_code = 0
        exit_label = "delivered"
    elif state == "blocked":
        # block_reason carries the closed-set token.
        exit_label = block_reason or "blocked"
        # kill_switch_off → routing_disabled CLI code (FR-027 / table).
        if block_reason == "kill_switch_off":
            exit_label = "routing_disabled"
        exit_code = CLI_EXIT_CODE_MAP.get(exit_label, 13)
    elif state == "failed":
        exit_label = failure_reason or "attempt_interrupted"
        exit_code = CLI_EXIT_CODE_MAP.get(exit_label, 13)
    elif state == "canceled":
        exit_label = "canceled"
        exit_code = 13
    elif state == "queued" and not waited_to_terminal and not no_wait:
        # wait budget elapsed before terminal — FR-009.
        exit_label = "delivery_wait_timeout"
        exit_code = CLI_EXIT_CODE_MAP.get("delivery_wait_timeout", 1)
    else:
        # --no-wait return with a non-terminal state is exit 0 (success
        # at enqueue; the caller didn't ask to wait).
        exit_code = 0
        exit_label = state or "queued"

    if json_mode:
        # Strip the dispatcher's waited_to_terminal flag — it's not part
        # of the queue-row-schema contract.
        payload = {k: v for k, v in row.items() if k != "waited_to_terminal"}
        print(json.dumps(payload, separators=(",", ":")))
    else:
        message_id = row.get("message_id") or "?"
        target = row.get("target") or {}
        target_label = target.get("label") or ""
        target_agent_id = target.get("agent_id") or ""
        target_str = (
            f"{target_label}({target_agent_id})" if target_label else target_agent_id
        )
        if exit_code == 0:
            print(f"{exit_label}: msg={message_id} target={target_str}")
        else:
            reason = block_reason or failure_reason or exit_label
            print(
                f"send-input failed: {exit_label} — {reason} (msg={message_id})",
                file=sys.stderr,
            )
    return exit_code


# ---------------------------------------------------------------------------
# FEAT-009 — `agenttower queue` (T070 / contracts/cli-queue.md)
# ---------------------------------------------------------------------------


def _queue_resolve_caller_pane(
    socket_path: Path, json_mode: bool,
) -> tuple[dict[str, Any] | None, int | None]:
    """Best-effort caller-pane resolution for operator-action subcommands.

    Returns ``(caller_pane, None)`` on success (where caller_pane is
    ``None`` for host-side callers) or ``(None, exit_code)`` on a
    bench-container caller whose pane couldn't be resolved.

    Per contracts/cli-queue.md, operator actions accept any caller —
    host callers get the ``host-operator`` sentinel; bench callers get
    their pane's agent_id. So a ``host_context_unsupported`` from the
    FEAT-006 resolver is NOT a failure — it just means we're on the
    host and the daemon should write ``host-operator``.
    """
    from .agents.client_resolve import resolve_pane_composite_key
    from .agents.errors import RegistrationError

    try:
        target = resolve_pane_composite_key(
            socket_path=socket_path,
            env=os.environ,
            proc_root=os.environ.get("AGENTTOWER_TEST_PROC_ROOT"),
            connect_timeout=1.0,
            read_timeout=5.0,
        )
    except RegistrationError as exc:
        if exc.code == "host_context_unsupported":
            return None, None  # host caller — let daemon use the sentinel
        return None, _emit_register_error(exc, json_mode)
    except DaemonUnavailable:
        # The queue operator-action RPC paths (approve/delay/cancel)
        # map daemon_unavailable to CLI_EXIT_CODE_MAP['daemon_unavailable']
        # (12). Match here so the exit code is consistent across both
        # the caller-pane resolution step and the queue.* call.
        from .routing.errors import CLI_EXIT_CODE_MAP
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return None, CLI_EXIT_CODE_MAP.get("daemon_unavailable", 12)
    except DaemonError as exc:
        return None, _emit_daemon_error(exc, json_mode)

    # Bench-container caller: look up our own agent_id via list_agents.
    self_agent_id = _send_input_lookup_self_agent_id(
        socket_path=socket_path, target=target, json_mode=json_mode,
    )
    if isinstance(self_agent_id, int):
        return None, self_agent_id
    return {"agent_id": self_agent_id}, None


def _queue_list_command(args: argparse.Namespace) -> int:
    """``agenttower queue`` (list) — list rows with filters."""
    from .routing.errors import CLI_EXIT_CODE_MAP

    json_mode = bool(args.json)
    _, resolved = _resolve_socket_with_paths()
    socket_path = resolved.path

    params: dict[str, Any] = {}
    if args.state is not None:
        params["state"] = args.state
    if args.target is not None:
        params["target"] = args.target
    if args.sender is not None:
        params["sender"] = args.sender
    if args.since is not None:
        params["since"] = args.since
    if args.limit != 100:
        params["limit"] = args.limit
    if args.limit < 1 or args.limit > 1000:
        _emit_local_error(
            "bad_request",
            f"--limit must be in [1, 1000], got {args.limit}",
            json_mode,
        )
        return 64

    try:
        result = send_request(
            socket_path, "queue.list", params,
            connect_timeout=2.0, read_timeout=10.0,
        )
    except DaemonUnavailable:
        print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
        return CLI_EXIT_CODE_MAP.get("daemon_unavailable", 12)
    except DaemonError as exc:
        return _send_input_emit_daemon_error(exc, json_mode)

    rows = result.get("rows", []) or []
    if json_mode:
        print(json.dumps(rows, separators=(",", ":")))
        return 0

    if not rows:
        print("(no rows match)")
        return 0
    # Human-readable column layout.
    header = (
        f"{'MESSAGE_ID':<36}  {'STATE':<9}  {'SENDER':<22}  "
        f"{'TARGET':<22}  {'ENQUEUED':<24}  {'LAST_UPDATED':<24}  EXCERPT"
    )
    print(header)
    for row in rows:
        sender = row.get("sender") or {}
        target = row.get("target") or {}
        sender_str = _queue_label_and_prefix(sender)
        target_str = _queue_label_and_prefix(target)
        raw_excerpt = (row.get("excerpt") or "").splitlines()[0] if row.get("excerpt") else ""
        excerpt = _sanitize_for_terminal(raw_excerpt)
        print(
            f"{row.get('message_id', ''):<36}  "
            f"{row.get('state', ''):<9}  "
            f"{sender_str:<22}  "
            f"{target_str:<22}  "
            f"{row.get('enqueued_at', ''):<24}  "
            f"{row.get('last_updated_at', ''):<24}  "
            f"{excerpt}"
        )
    return 0


def _queue_label_and_prefix(identity: dict[str, Any]) -> str:
    """Render a sender/target identity as ``label(agt_<8 hex>)`` or fall
    back to the bare agent_id when no label is set."""
    label = identity.get("label") or ""
    agent_id = identity.get("agent_id") or ""
    if label and agent_id:
        prefix = agent_id[:8] if agent_id.startswith("agt_") else agent_id[:8]
        return f"{label}({prefix})"
    return agent_id


def _queue_operator_command_factory(op_name: str):
    """Build the handler for ``queue approve/delay/cancel`` subcommands."""
    method_name = f"queue.{op_name}"

    def handler(args: argparse.Namespace) -> int:
        from .routing.errors import CLI_EXIT_CODE_MAP

        json_mode = bool(args.json)
        _, resolved = _resolve_socket_with_paths()
        socket_path = resolved.path
        caller_pane, err = _queue_resolve_caller_pane(socket_path, json_mode)
        if err is not None:
            return err
        params: dict[str, Any] = {"message_id": args.message_id}
        if caller_pane is not None:
            params["caller_pane"] = caller_pane
        try:
            row = send_request(
                socket_path, method_name, params,
                connect_timeout=2.0, read_timeout=10.0,
            )
        except DaemonUnavailable:
            print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
            return CLI_EXIT_CODE_MAP.get("daemon_unavailable", 12)
        except DaemonError as exc:
            return _send_input_emit_daemon_error(exc, json_mode)
        return _queue_operator_render(op_name, row, json_mode=json_mode)

    return handler


def _queue_operator_render(
    op_name: str, row: dict[str, Any], *, json_mode: bool,
) -> int:
    """Render the response of an operator action."""
    state = row.get("state") or ""
    message_id = row.get("message_id") or "?"
    label = "approved" if op_name == "approve" else (
        "delayed" if op_name == "delay" else "canceled"
    )
    if json_mode:
        # Strip the dispatcher's internal waited_to_terminal flag if any.
        payload = {k: v for k, v in row.items() if k != "waited_to_terminal"}
        print(json.dumps(payload, separators=(",", ":")))
    else:
        print(f"{label}: msg={message_id} state={state}")
    return 0


# ---------------------------------------------------------------------------
# FEAT-009 — `agenttower routing` (T075 / contracts/cli-routing.md)
# ---------------------------------------------------------------------------


def _routing_command_factory(op_name: str):
    """Build the handler for one ``routing`` subcommand.

    For ``enable`` / ``disable`` we auto-probe the runtime: if the CLI
    is running INSIDE a bench container (FEAT-005 ``runtime_detect``
    returns a non-host context), we include ``caller_pane`` in the
    request so the daemon's dispatch-boundary host-only gate
    (R-005 / FR-027) refuses with ``routing_toggle_host_only``. From
    the host the probe surfaces ``host_context_unsupported`` and we
    proceed with an empty params dict — the daemon then accepts the
    toggle.

    ``status`` has no origin restriction (contracts/socket-routing.md
    §"Caller context") so we always send empty params.
    """
    method_name = f"routing.{op_name}"

    def handler(args: argparse.Namespace) -> int:
        from .routing.errors import CLI_EXIT_CODE_MAP

        json_mode = bool(args.json)
        _, resolved = _resolve_socket_with_paths()
        socket_path = resolved.path

        params: dict[str, Any] = {}
        if op_name in ("enable", "disable"):
            params = _routing_probe_caller_pane(socket_path, json_mode)

        try:
            result = send_request(
                socket_path, method_name, params,
                connect_timeout=2.0, read_timeout=5.0,
            )
        except DaemonUnavailable:
            print(DAEMON_UNAVAILABLE_MESSAGE, file=sys.stderr)
            return CLI_EXIT_CODE_MAP.get("daemon_unavailable", 12)
        except DaemonError as exc:
            return _routing_emit_daemon_error(op_name, exc, json_mode)
        return _routing_render(op_name, result, json_mode=json_mode)

    return handler


def _routing_probe_caller_pane(
    socket_path: Path, json_mode: bool,
) -> dict[str, Any]:
    """Detect bench-container vs host context for routing toggles.

    The probe walks the FEAT-005 ``resolve_pane_composite_key`` chain;
    the failure code tells us where we stopped. Per
    ``resolve_pane_composite_key`` semantics, ONLY
    ``host_context_unsupported`` is raised at step 1 when
    ``runtime_detect`` concludes "no container signals at all" — every
    other code is raised AFTER runtime detection already classified
    us as non-host (``ContainerContext`` / ``MaybeContainerContext``),
    so they all mean "we're in a bench-container-like environment
    even if the specific pane couldn't be identified".

    * ``host_context_unsupported`` — definitive host. Return ``{}``;
      the daemon's host-only gate accepts on peer-uid match.
    * ``container_unresolved`` / ``not_in_tmux`` /
      ``tmux_pane_malformed`` / ``pane_unknown_to_daemon`` / any
      other RegistrationError — fail closed: send a sentinel
      ``caller_pane`` so the daemon refuses with
      ``routing_toggle_host_only``. A misclassification here on a
      dev machine that has a spurious ``/.dockerenv`` is acceptable
      collateral; the secure default is to refuse when in doubt
      (operator can remove the marker or run from a known-host
      shell). The daemon's gate is the canonical enforcement point.

    The daemon's peer-uid check is canonical for the
    ``host_context_unsupported`` case (FR-024 trusts the same-uid
    peer); for every other code we explicitly tell the daemon to
    refuse.
    """
    from .agents.client_resolve import resolve_pane_composite_key
    from .agents.errors import RegistrationError

    # Sentinel for the not-definitively-host case. The daemon's gate
    # only checks ``caller_pane is not None``, so any non-empty dict
    # suffices to trip the refuse path.
    _BENCH_ORIGIN_UNRESOLVED: dict[str, Any] = {
        "caller_pane": {"bench_origin_unresolved": True},
    }

    try:
        target = resolve_pane_composite_key(
            socket_path=socket_path,
            env=os.environ,
            proc_root=os.environ.get("AGENTTOWER_TEST_PROC_ROOT"),
            connect_timeout=1.0,
            read_timeout=5.0,
        )
    except RegistrationError as exc:
        if exc.code == "host_context_unsupported":
            return {}
        # Any other RegistrationError code: runtime_detect already
        # classified us as not-host, so fail closed.
        return _BENCH_ORIGIN_UNRESOLVED
    except Exception:  # noqa: BLE001
        # Defensive — non-RegistrationError surprise. Fail closed.
        return _BENCH_ORIGIN_UNRESOLVED
    # Bench-container origin detected; include caller_pane so the
    # daemon refuses with routing_toggle_host_only.
    self_agent_id = _send_input_lookup_self_agent_id(
        socket_path=socket_path, target=target, json_mode=json_mode,
    )
    if isinstance(self_agent_id, int):
        # The lookup failed (e.g., pane not registered) — fall back to
        # the bare pane info so the daemon still sees we're in a
        # container.
        return {"caller_pane": {"pane_composite_key": {
            "container_id": target.pane_key[0],
            "tmux_socket_path": target.pane_key[1],
            "tmux_session_name": target.pane_key[2],
            "tmux_window_index": target.pane_key[3],
            "tmux_pane_index": target.pane_key[4],
            "tmux_pane_id": target.pane_key[5],
        }}}
    return {"caller_pane": {"agent_id": self_agent_id}}


def _routing_emit_daemon_error(
    op_name: str, exc: DaemonError, json_mode: bool,
) -> int:
    """Render a daemon-side error for routing subcommands. ``op_name``
    is used for the stderr label (``routing enable failed:`` /
    ``routing disable failed:`` / ``routing status failed:``)."""
    from .routing.errors import CLI_EXIT_CODE_MAP

    if json_mode:
        print(
            json.dumps(
                {"ok": False, "error": {"code": exc.code, "message": exc.message}}
            )
        )
    else:
        print(
            f"routing {op_name} failed: {exc.code} — {exc.message}",
            file=sys.stderr,
        )
    if exc.code in CLI_EXIT_CODE_MAP:
        return CLI_EXIT_CODE_MAP[exc.code]
    return _exit_code_for(exc.code)


def _routing_render(
    op_name: str, payload: dict[str, Any], *, json_mode: bool,
) -> int:
    """Render the successful response of one routing subcommand."""
    if json_mode:
        print(json.dumps(payload, separators=(",", ":")))
        return 0

    if op_name == "status":
        value = payload.get("value") or "?"
        ts = payload.get("last_updated_at") or "?"
        by = payload.get("last_updated_by") or "?"
        print(f"routing: {value} (set {ts} by {by})")
        return 0

    # enable / disable.
    previous = payload.get("previous_value") or "?"
    current = payload.get("current_value") or "?"
    changed = bool(payload.get("changed", False))
    if not changed:
        print(f"routing already {current}")
    else:
        print(f"routing {current} (was {previous})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
