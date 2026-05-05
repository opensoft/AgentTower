"""AgentTower daemon entrypoint."""

from __future__ import annotations

import argparse
import os
import signal
import sqlite3
import sys
import threading
from datetime import datetime, timezone

from . import __version__
from .paths import Paths, resolve_paths
from .socket_api import lifecycle
from .socket_api.lifecycle import (
    EVENT_DAEMON_EXITED,
    EVENT_DAEMON_READY,
    EVENT_DAEMON_RECOVERING,
    EVENT_DAEMON_SHUTDOWN,
    EVENT_DAEMON_STARTING,
    EVENT_ERROR_FATAL,
    LifecycleLogger,
)
from .socket_api.methods import DaemonContext
from .socket_api.server import ControlServer

LOCK_FILENAME = "agenttowerd.lock"
PID_FILENAME = "agenttowerd.pid"
LOG_FILENAME = "agenttowerd.log"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenttowerd",
        description="AgentTower daemon.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"agenttowerd {__version__}",
    )
    parser.set_defaults(_handler=None)

    subparsers = parser.add_subparsers(dest="command", metavar="command")
    run = subparsers.add_parser(
        "run",
        help="enter daemon mode (foreground, never returns until shutdown)",
        description="enter daemon mode (foreground, never returns until shutdown)",
    )
    run.set_defaults(_handler=_run)

    return parser


def _verify_feat001_initialized(paths: Paths) -> None:
    """Refuse to start if FEAT-001 schema_version row is missing (FR-003)."""
    if not paths.state_db.exists():
        raise SystemExit(
            f"error: agenttower is not initialized: state db missing at {paths.state_db}"
        )
    try:
        conn = sqlite3.connect(str(paths.state_db))
        try:
            row = conn.execute("SELECT version FROM schema_version").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise SystemExit(f"error: open registry: {paths.state_db}: {exc}") from exc
    if row is None:
        raise SystemExit(
            f"error: agenttower is not initialized: schema_version row missing in {paths.state_db}"
        )


def _read_schema_version(paths: Paths) -> int | None:
    try:
        conn = sqlite3.connect(str(paths.state_db))
        try:
            row = conn.execute("SELECT version FROM schema_version").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return int(row[0]) if row is not None else None


def _run(args: argparse.Namespace) -> int:
    paths = resolve_paths()
    state_dir = paths.state_db.parent
    logs_dir = paths.logs_dir
    lock_path = state_dir / LOCK_FILENAME
    pid_path = state_dir / PID_FILENAME
    log_path = logs_dir / LOG_FILENAME

    _verify_feat001_initialized(paths)

    # Acquire the lock before any further state work (FR-028).
    try:
        lock_fd = lifecycle.acquire_exclusive_lock(lock_path)
    except lifecycle.LockHeldError:
        print(
            "error: another agenttowerd is already running for this state directory",
            file=sys.stderr,
        )
        return 2
    except (PermissionError, OSError) as exc:
        print(f"error: acquire lock: {lock_path}: {exc}", file=sys.stderr)
        return 1

    logger: LifecycleLogger | None = None
    server: ControlServer | None = None
    accept_thread: threading.Thread | None = None
    exit_code = 0
    try:
        # Verify host-user-only invariants before any irreversible action (R-011).
        try:
            lifecycle.assert_paths_safe(
                state_dir=state_dir,
                logs_dir=logs_dir,
                lock_file=lock_path,
                pid_file=pid_path,
                log_file=log_path,
            )
        except lifecycle.UnsafePathError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        logger = LifecycleLogger(log_path)
        logger.emit(
            EVENT_DAEMON_STARTING,
            pid=os.getpid(),
            state_dir=str(state_dir),
        )

        # Recover stale lifecycle artifacts (US3 / T024).
        try:
            lifecycle.recover_stale_artifacts(
                socket_path=paths.socket,
                pid_path=pid_path,
                logger=logger,
            )
        except lifecycle.StaleArtifactRefused as exc:
            logger.emit(
                EVENT_ERROR_FATAL,
                reason=f"refuse stale: {exc.path} ({exc.kind})",
                level="fatal",
            )
            print(
                f"error: socket path is not a unix socket: {exc.path}: "
                f"refusing to remove {exc.kind}",
                file=sys.stderr,
            )
            return 1

        shutdown_event = threading.Event()
        ctx = DaemonContext(
            pid=os.getpid(),
            start_time_utc=datetime.now(timezone.utc),
            socket_path=paths.socket,
            state_path=state_dir,
            daemon_version=__version__,
            schema_version=_read_schema_version(paths),
            shutdown_requested=shutdown_event,
        )

        try:
            server = ControlServer(paths.socket, ctx)
        except (PermissionError, OSError) as exc:
            logger.emit(EVENT_ERROR_FATAL, reason=f"bind failed: {exc}", level="fatal")
            print(f"error: bind socket: {paths.socket}: {exc}", file=sys.stderr)
            return 1

        lifecycle.write_pid_file(pid_path, os.getpid())
        logger.emit(EVENT_DAEMON_READY, socket=str(paths.socket), pid=os.getpid())

        # Install signal handlers + SIGPIPE ignore (R-008).
        def _signal_initiator(signum: int, _frame) -> None:  # noqa: ANN001
            shutdown_event.set()

        signal.signal(signal.SIGTERM, _signal_initiator)
        signal.signal(signal.SIGINT, _signal_initiator)
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)

        accept_thread = threading.Thread(
            target=server.serve_forever, name="agenttowerd-accept", daemon=True
        )
        accept_thread.start()

        # Wait for either an API-driven shutdown or a signal-driven shutdown.
        # ``Event.wait`` releases the GIL so signals dispatch promptly.
        while not shutdown_event.wait(timeout=1.0):
            if not accept_thread.is_alive():
                # Server exited unexpectedly (should not happen) — fall through.
                break

        # Shutdown sequence (R-007): stop accepting → drain handlers → unlink.
        logger.emit(EVENT_DAEMON_SHUTDOWN, trigger="api_or_signal")
        # ``server.shutdown()`` must run from a thread other than the accept
        # thread; we are in the main thread, so call it directly.
        server.shutdown()
        accept_thread.join(timeout=2.0)
    finally:
        if server is not None:
            try:
                server.server_close()
            except OSError:
                pass
            try:
                paths.socket.unlink()
            except FileNotFoundError:
                pass
        lifecycle.remove_pid_file(pid_path)
        if logger is not None:
            logger.emit(EVENT_DAEMON_EXITED, exit_code=exit_code)
            logger.close()
        lifecycle.release_lock(lock_fd)

    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Run the AgentTower daemon."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
