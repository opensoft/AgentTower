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
from .paths import Paths, resolve_paths
from .socket_api import lifecycle
from .socket_api.client import DaemonError, DaemonUnavailable, send_request
from .state.schema import companion_paths_for, open_registry

LOCK_FILENAME = "agenttowerd.lock"
PID_FILENAME = "agenttowerd.pid"
LOG_FILENAME = "agenttowerd.log"

READY_BUDGET_SECONDS = 2.0
READY_POLL_INTERVALS = (0.01, 0.05, 0.1, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2)
JSON_LINE_HELP = "emit one JSON line on stdout"


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
    paths: Paths = resolve_paths()
    print(f"CONFIG_FILE={paths.config_file}")
    print(f"STATE_DB={paths.state_db}")
    print(f"EVENTS_FILE={paths.events_file}")
    print(f"LOGS_DIR={paths.logs_dir}")
    print(f"SOCKET={paths.socket}")
    print(f"CACHE_DIR={paths.cache_dir}")
    if not paths.state_db.exists():
        print(
            "note: agenttower has not been initialized; run `agenttower config init`",
            file=sys.stderr,
        )
    return 0


def _ensure_daemon(args: argparse.Namespace) -> int:
    paths: Paths = resolve_paths()
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
    paths: Paths = resolve_paths()
    try:
        result = send_request(
            paths.socket, "status", connect_timeout=1.0, read_timeout=1.0
        )
    except DaemonUnavailable:
        print(
            "error: daemon is not running or socket is unreachable: "
            "try `agenttower ensure-daemon`",
            file=sys.stderr,
        )
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
    paths: Paths = resolve_paths()
    state_dir = paths.state_db.parent
    socket_path = paths.socket
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
        help="scan host resources (FEAT-003: --containers)",
        description="scan host resources (FEAT-003: --containers)",
    )
    scan.add_argument("--containers", action="store_true", help="scan Docker containers")
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

    return parser


def _print_subusage_and_exit(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 0


def _scan_command(args: argparse.Namespace) -> int:
    if not args.containers:
        print(
            "error: scan requires a target flag (e.g. --containers)",
            file=sys.stderr,
        )
        return 1
    paths: Paths = resolve_paths()
    try:
        result = send_request(
            paths.socket, "scan_containers", connect_timeout=1.0, read_timeout=10.0
        )
    except DaemonUnavailable:
        print(
            "error: daemon is not running or socket is unreachable: "
            "try `agenttower ensure-daemon`",
            file=sys.stderr,
        )
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

    if status == "degraded":
        return 5
    return 0


def _parse_iso(text: str) -> "datetime":  # type: ignore[name-defined]
    from datetime import datetime as _dt
    return _dt.fromisoformat(text)


def _list_containers_command(args: argparse.Namespace) -> int:
    paths: Paths = resolve_paths()
    params: dict[str, Any] = {"active_only": bool(args.active_only)}
    try:
        result = send_request(
            paths.socket,
            "list_containers",
            params=params,
            connect_timeout=1.0,
            read_timeout=1.0,
        )
    except DaemonUnavailable:
        print(
            "error: daemon is not running or socket is unreachable: "
            "try `agenttower ensure-daemon`",
            file=sys.stderr,
        )
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


def main(argv: list[str] | None = None) -> int:
    """Run the AgentTower CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler: Any = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
