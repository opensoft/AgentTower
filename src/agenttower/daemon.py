"""AgentTower daemon entrypoint."""

from __future__ import annotations

import argparse
import os
import signal
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .agents.mutex import AgentLockMap, RegisterLockMap
from .agents.service import AgentService
from .config import load_containers_block, load_events_block
from .discovery.pane_service import PaneDiscoveryService
from .discovery.service import DiscoveryService
from .docker import FakeDockerAdapter
from .logs.docker_exec import resolve_docker_exec_runner
from .logs.mutex import LogPathLockMap
from .logs.orphan_recovery import detect_orphans
from .logs.service import LogService
from .tmux import FakeTmuxAdapter, SubprocessTmuxAdapter, TmuxAdapter
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

# SQLite ``timeout`` for connections used by pre-FEAT-009 services
# (AgentService, LogService, schema_version reader, list-row
# factories, etc.) — those services open ``BEGIN IMMEDIATE`` blocks
# WITHOUT explicit retry/backoff, so we keep sqlite3's standard
# 5-second busy timeout. A normal concurrent writer briefly holding
# a lock should never surface as ``internal_error`` on these paths.
_SQLITE_DEFAULT_TIMEOUT_SECONDS = 5.0

# Zero-wait ``timeout`` reserved for the FEAT-009 ``worker_conn``.
# That connection is shared across the delivery worker + every
# FEAT-009 DAO under a single ``threading.Lock`` and every
# ``BEGIN IMMEDIATE`` block runs inside
# ``routing.dao.with_lock_retry`` (bounded retry with backoff). A
# 0-second SQLite timeout makes the retry helper authoritative —
# without it, SQLite would silently wait inside the C layer and
# defeat the helper's deterministic budget.
_SQLITE_FEAT009_WORKER_TIMEOUT_SECONDS = 0.0


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


def _guard_feat008_test_seams_unset() -> None:
    """Refuse to start if a FEAT-008 test seam is set outside a test harness.

    The two FEAT-008 seams (clock fake + reader tick socket) are honored
    unconditionally by the production code they target — leaking either
    into a real daemon would freeze the reader or skew its clock.

    The seam env-var literals are owned by ``events/__init__.py`` and
    ``events/reader.py`` (enforced by the AST gate in
    ``tests/unit/test_logs_offset_advance_invariant.py``). This helper
    asks each owner module which of its seams is set, then mirrors
    ``cli._guard_production_test_seam_unset``: presence is tolerated
    only when another ``AGENTTOWER_TEST_*`` env var is set, which the
    pytest harness always provides (e.g. ``AGENTTOWER_TEST_DOCKER_FAKE``).
    """
    from .events import seam_names_currently_set as _clock_set
    from .events.reader import seam_names_currently_set as _reader_set

    leaked = [*_clock_set(), *_reader_set()]
    if not leaked:
        return
    leaked_set = set(leaked)
    companions = [
        key
        for key in os.environ
        if key.startswith("AGENTTOWER_TEST_") and key not in leaked_set
    ]
    if companions:
        return
    names = ", ".join(sorted(leaked_set))
    raise SystemExit(
        f"error: {names} is set outside the test harness; "
        "unset before running agenttowerd"
    )


def _verify_feat001_initialized(paths: Paths) -> None:
    """Refuse to start if FEAT-001 schema_version row is missing (FR-003).

    Also runs any pending schema migrations (FEAT-003 v1→v2) so the daemon
    never serves with stale schema (FR-047).
    """
    if not paths.state_db.exists():
        raise SystemExit(
            f"error: agenttower is not initialized: state db missing at {paths.state_db}"
        )
    try:
        from .state.schema import open_registry
        conn, _ = open_registry(paths.state_db, namespace_root=paths.state_db.parent)
    except sqlite3.Error as exc:
        raise SystemExit(f"error: open registry: {paths.state_db}: {exc}") from exc
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
    finally:
        conn.close()
    if row is None:
        raise SystemExit(
            f"error: agenttower is not initialized: schema_version row missing in {paths.state_db}"
        )


def _resolve_docker_adapter():  # noqa: ANN202 — adapter is a Protocol
    """Return the Docker adapter for this daemon process.

    `AGENTTOWER_TEST_DOCKER_FAKE` set → load `FakeDockerAdapter` from the
    pointed-to fixture file. Unset → return the production
    `SubprocessDockerAdapter` (US3 T037 plugs this in).
    """
    fake_path = os.environ.get("AGENTTOWER_TEST_DOCKER_FAKE")
    if fake_path:
        return FakeDockerAdapter.from_path(fake_path)
    try:
        from .docker.subprocess_adapter import SubprocessDockerAdapter
    except ImportError:
        return None
    return SubprocessDockerAdapter()


def _read_schema_version(paths: Paths) -> int | None:
    try:
        conn = sqlite3.connect(
            str(paths.state_db),
            timeout=_SQLITE_DEFAULT_TIMEOUT_SECONDS,
        )
        try:
            row = conn.execute("SELECT version FROM schema_version").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return int(row[0]) if row is not None else None


def _build_discovery_service(
    paths: Paths, logger: LifecycleLogger
) -> tuple[DiscoveryService | None, sqlite3.Connection | None]:
    adapter = _resolve_docker_adapter()
    if adapter is None:
        return None, None
    conn = sqlite3.connect(
        str(paths.state_db),
        isolation_level=None,
        check_same_thread=False,
        timeout=_SQLITE_DEFAULT_TIMEOUT_SECONDS,
    )
    service = DiscoveryService(
        connection=conn,
        adapter=adapter,
        rule_provider=lambda: load_containers_block(paths.config_file),
        list_connection_factory=lambda: sqlite3.connect(
            str(paths.state_db),
            timeout=_SQLITE_DEFAULT_TIMEOUT_SECONDS,
        ),
        events_file=paths.events_file,
        lifecycle_logger=logger,
    )
    return service, conn


def _resolve_tmux_adapter() -> TmuxAdapter | None:
    """Return the TmuxAdapter for this daemon process (FEAT-004 R-012).

    ``AGENTTOWER_TEST_TMUX_FAKE`` set → load ``FakeTmuxAdapter`` from the
    pointed-to JSON fixture. Unset → return the production
    ``SubprocessTmuxAdapter``.
    """
    fake_path = os.environ.get("AGENTTOWER_TEST_TMUX_FAKE")
    if fake_path:
        return FakeTmuxAdapter.from_path(fake_path)
    return SubprocessTmuxAdapter()


def _build_pane_service(
    paths: Paths, logger: LifecycleLogger
) -> tuple[PaneDiscoveryService | None, sqlite3.Connection | None]:
    adapter = _resolve_tmux_adapter()
    if adapter is None:
        return None, None
    conn = sqlite3.connect(
        str(paths.state_db),
        isolation_level=None,
        check_same_thread=False,
        timeout=_SQLITE_DEFAULT_TIMEOUT_SECONDS,
    )
    service = PaneDiscoveryService(
        connection=conn,
        adapter=adapter,
        list_connection_factory=lambda: sqlite3.connect(
            str(paths.state_db),
            timeout=_SQLITE_DEFAULT_TIMEOUT_SECONDS,
        ),
        events_file=paths.events_file,
        lifecycle_logger=logger,
    )
    return service, conn


def _build_log_service(
    paths: Paths, logger: LifecycleLogger, agent_locks: AgentLockMap
) -> LogService:
    """Construct the FEAT-007 :class:`LogService` for the daemon.

    Reuses the ``AgentLockMap`` instance from the AgentService so per-agent
    serialization spans both FEAT-006 set_* and FEAT-007 attach/detach
    (FR-040). Wires the production docker-exec runner (or its fake under
    ``AGENTTOWER_TEST_PIPE_PANE_FAKE``).
    """
    schema_version = _read_schema_version(paths) or 0
    daemon_home = os.path.expanduser("~")
    return LogService(
        connection_factory=lambda: sqlite3.connect(
            str(paths.state_db),
            isolation_level=None,
            timeout=_SQLITE_DEFAULT_TIMEOUT_SECONDS,
        ),
        agent_locks=agent_locks,
        log_path_locks=LogPathLockMap(),
        events_file=paths.events_file,
        schema_version=schema_version,
        daemon_home=Path(daemon_home) if not isinstance(daemon_home, Path) else daemon_home,
        docker_exec_runner=resolve_docker_exec_runner(),
        lifecycle_logger=logger,
    )


def _build_agent_service(paths: Paths, logger: LifecycleLogger) -> AgentService:
    """Construct the FEAT-006 ``AgentService`` for the daemon.

    Each call to a service method opens a fresh SQLite connection via the
    factory so register_agent / list_agents / set_* run without sharing
    a cursor across the accept-thread pool. Mutex registries are
    process-scoped per FR-038 / FR-039.

    The lifecycle *logger* is plumbed in so the FR-014 audit-append
    failure invariant (see ``agents.service`` module docstring) is
    operationally observable: post-COMMIT JSONL append failures emit
    ``audit_append_failed`` events through the daemon's structured
    logger rather than being silently lost.
    """
    schema_version = _read_schema_version(paths) or 0
    return AgentService(
        connection_factory=lambda: sqlite3.connect(
            str(paths.state_db),
            isolation_level=None,
            timeout=_SQLITE_DEFAULT_TIMEOUT_SECONDS,
        ),
        register_locks=RegisterLockMap(),
        agent_locks=AgentLockMap(),
        events_file=paths.events_file,
        schema_version=schema_version,
        lifecycle_logger=logger,
    )


def _build_feat009_services(
    *,
    paths: Paths,
    discovery_service: DiscoveryService | None,
    pane_service: PaneDiscoveryService | None,
) -> tuple[
    sqlite3.Connection,
    object,  # QueueService
    object,  # RoutingFlagService
    object,  # QueueAuditWriter
    object,  # DeliveryWorker
    object,  # MessageQueueDao
    object,  # DaemonStateDao
]:
    """Construct FEAT-009 queue / routing / delivery services (T048).

    Opens a DEDICATED per-worker SQLite connection (``check_same_thread=False``)
    that the :class:`MessageQueueDao` + :class:`DaemonStateDao` + the
    :class:`QueueAuditWriter` share — this is the worker thread's
    BEGIN IMMEDIATE serialization point. The adapter classes
    (:class:`RegistryAgentsLookup`, :class:`DiscoveryContainerPaneLookup`)
    open their own short-lived connections to avoid blocking the
    worker's transactions.

    Lifecycle handled internally — both ``run_recovery_pass()`` and
    ``start()`` run BEFORE returning. The synchronous recovery pass
    fires first (research §R-012) so the worker thread never observes
    a half-stamped row at boot. The caller receives an
    already-running worker and only owns ``stop()`` + connection
    close on shutdown.
    """
    # Local imports keep the daemon module's import graph independent
    # of the FEAT-009 module tree during FEAT-001..008-only test runs.
    from .routing.audit_writer import QueueAuditWriter
    from .routing.daemon_adapters import (
        DiscoveryContainerPaneLookup,
        RegistryAgentsLookup,
        RegistryDeliveryContextResolver,
    )
    from .routing.dao import DaemonStateDao, MessageQueueDao
    from .routing.delivery import DeliveryWorker
    from .routing.kill_switch import RoutingFlagService
    from .routing.service import ContainerPaneLookup, QueueService

    # Dedicated per-worker connection. ``check_same_thread=False`` is
    # necessary because the worker thread owns the connection while
    # boot-time recovery + audit setup runs in the main thread.
    # ``isolation_level=None`` matches FEAT-004's pane-service connection
    # so the DAO's explicit ``BEGIN IMMEDIATE`` controls the transaction
    # boundary (rather than the implicit driver-managed mode).
    worker_conn = sqlite3.connect(
        str(paths.state_db),
        isolation_level=None,
        check_same_thread=False,
        timeout=_SQLITE_FEAT009_WORKER_TIMEOUT_SECONDS,
    )

    # One shared lock for all writers/readers of worker_conn. The
    # MessageQueueDao + DaemonStateDao + QueueAuditWriter all run
    # transactions against this single connection across multiple
    # threads (worker + dispatcher) and MUST serialize through the
    # same lock — otherwise SQLite surfaces "cannot start a
    # transaction within a transaction".
    import threading as _threading
    worker_tx_lock = _threading.Lock()

    message_queue_dao = MessageQueueDao(worker_conn, tx_lock=worker_tx_lock)
    daemon_state_dao = DaemonStateDao(worker_conn, tx_lock=worker_tx_lock)
    routing_flag = RoutingFlagService(daemon_state_dao)
    audit_writer = QueueAuditWriter(
        worker_conn, paths.events_file, tx_lock=worker_tx_lock,
    )

    # Read-only adapters share a connection factory; each method opens
    # its own short-lived connection so reads don't block the worker
    # thread's BEGIN IMMEDIATE.
    def _read_conn_factory() -> sqlite3.Connection:
        return sqlite3.connect(
            str(paths.state_db),
            timeout=_SQLITE_DEFAULT_TIMEOUT_SECONDS,
        )

    agents_lookup = RegistryAgentsLookup(_read_conn_factory)
    if discovery_service is None or pane_service is None:
        # Fail-soft path: if FEAT-003/004 services aren't wired (e.g., a
        # configuration that disabled them), the FEAT-009 surface stays
        # off rather than crashing — every permission gate will surface
        # ``target_container_inactive`` until they're back.
        container_pane_lookup: ContainerPaneLookup = _NullContainerPaneLookup()
    else:
        container_pane_lookup = DiscoveryContainerPaneLookup(
            discovery_service, pane_service,
        )

    queue_service = QueueService(
        dao=message_queue_dao,
        routing_flag=routing_flag,
        agents_lookup=agents_lookup,
        container_pane_lookup=container_pane_lookup,
        audit_writer=audit_writer,
    )

    tmux_adapter = _resolve_tmux_adapter()
    if tmux_adapter is None:
        # No tmux adapter (e.g., misconfigured environment) — worker
        # would crash on first delivery attempt. Use a fallback
        # SubprocessTmuxAdapter; the delivery itself will surface
        # docker_exec_failed via the worker's normal error path.
        tmux_adapter = SubprocessTmuxAdapter()

    delivery_context_resolver = RegistryDeliveryContextResolver(_read_conn_factory)
    delivery_worker = DeliveryWorker(
        dao=message_queue_dao,
        routing_flag=routing_flag,
        agents_lookup=agents_lookup,
        container_panes=container_pane_lookup,
        tmux=tmux_adapter,
        audit_writer=audit_writer,
        queue_service=queue_service,
        delivery_context_resolver=delivery_context_resolver,
    )

    # FR-040 / research §R-012: synchronous recovery BEFORE start().
    # SqliteLockConflict here is fatal — propagates to the caller.
    delivery_worker.run_recovery_pass()
    delivery_worker.start()

    return (
        worker_conn,
        queue_service,
        routing_flag,
        audit_writer,
        delivery_worker,
        message_queue_dao,
        daemon_state_dao,
    )


def _build_feat010_services(
    *,
    paths: Paths,
    queue_service: object,
) -> tuple[object, object, object, object, object]:
    """Construct FEAT-010 routing-worker stack + spawn the worker AND
    heartbeat threads.

    Returns ``(routes_service, routes_audit, shared_state,
    worker_thread, heartbeat_thread)``. Both threads are ALREADY
    RUNNING when this function returns — the caller owns
    ``worker_thread.stop()`` + ``heartbeat_shutdown.set()`` +
    ``heartbeat_thread.join()`` on shutdown.

    Spawn order (plan §Implementation Invariants §1): the routing
    worker is spawned AFTER the FEAT-009 delivery worker (caller
    contract) so on shutdown the inverse order — routing worker
    first, then heartbeat, then delivery worker — preserves the
    no-new-rows-during-drain invariant.
    """
    import threading as _threading

    # Local imports keep the daemon module's import graph independent
    # of the FEAT-010 module tree during FEAT-001..009-only test runs.
    from .routing.daemon_adapters import (
        RoutingAgentsAdapter,
        RoutingEventReader,
        RoutingWorkerThread,
    )
    from .routing.heartbeat import HeartbeatEmitter
    from .routing.routes_audit import RoutesAuditWriter
    from .routing.routes_service import RoutesService
    from .routing.worker import RoutingWorker, _SharedRoutingState

    # Connection factory used by both the routing worker's adapters
    # AND the routes service (CRUD). Short-lived per-call connections
    # mirror the existing FEAT-009 adapter pattern.
    def _routing_conn_factory() -> sqlite3.Connection:
        return sqlite3.connect(
            str(paths.state_db),
            timeout=_SQLITE_DEFAULT_TIMEOUT_SECONDS,
            isolation_level=None,
        )

    audit_writer = RoutesAuditWriter()
    shared_state = _SharedRoutingState()
    agents_adapter = RoutingAgentsAdapter(_routing_conn_factory)
    event_reader = RoutingEventReader()

    worker = RoutingWorker(
        conn_factory=_routing_conn_factory,
        agents_service=agents_adapter,
        event_reader=event_reader,
        queue_service=queue_service,
        audit_writer=audit_writer,
        events_file=paths.events_file,
        shutdown_event=_threading.Event(),
        shared_state=shared_state,
    )

    routes_service = RoutesService(
        conn_factory=_routing_conn_factory,
        audit_writer=audit_writer,
        events_file=paths.events_file,
        shared_state=shared_state,
    )

    worker_thread = RoutingWorkerThread(worker, name="agenttower-routing")
    worker_thread.start()

    # Heartbeat is a SEPARATE thread per Clarifications Q3 + plan
    # §1: a long routing cycle never delays the heartbeat, and a slow
    # JSONL write never delays the routing cycle.
    heartbeat_shutdown = _threading.Event()
    heartbeat_emitter = HeartbeatEmitter(
        audit_emitter=audit_writer,
        shared_state=shared_state,
        events_file=paths.events_file,
        shutdown_event=heartbeat_shutdown,
    )
    heartbeat_thread = _threading.Thread(
        target=heartbeat_emitter.run,
        name="agenttower-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()

    # Wrap the heartbeat with a stop()-style API so the daemon's
    # shutdown sequence can treat it uniformly with the worker.
    class _HeartbeatHandle:
        def stop(self, *, timeout: float | None = None) -> None:
            heartbeat_shutdown.set()
            heartbeat_thread.join(timeout=timeout if timeout is not None else 5.0)

    return routes_service, audit_writer, shared_state, worker_thread, _HeartbeatHandle()


class _NullContainerPaneLookup:
    """Inert :class:`ContainerPaneLookup` used when FEAT-003 / FEAT-004
    aren't wired (returns ``False`` for every check — every queued row
    will land in ``blocked`` with ``target_container_inactive`` until
    the services come up)."""

    def is_container_active(self, container_id: str) -> bool:  # noqa: ARG002
        return False

    def is_pane_resolvable(self, container_id: str, pane_id: str) -> bool:  # noqa: ARG002
        return False


def _build_context(
    *,
    paths: Paths,
    state_dir,
    shutdown_event: threading.Event,
    discovery_service: DiscoveryService | None,
    pane_service: PaneDiscoveryService | None,
    agent_service: AgentService | None,
    log_service: LogService | None,
    logger: LifecycleLogger,
    events_reader: object | None = None,
    follow_session_registry: object | None = None,
    events_config: object | None = None,
    state_conn: sqlite3.Connection | None = None,
    queue_service: object | None = None,
    routing_flag_service: object | None = None,
    delivery_worker: object | None = None,
    queue_audit_writer: object | None = None,
    message_queue_dao: object | None = None,
    daemon_state_dao: object | None = None,
    routes_service: object | None = None,
    routing_worker_thread: object | None = None,
    routing_audit_writer: object | None = None,
    routing_shared_state: object | None = None,
) -> DaemonContext:
    return DaemonContext(
        pid=os.getpid(),
        start_time_utc=datetime.now(timezone.utc),
        socket_path=paths.socket,
        state_path=state_dir,
        daemon_version=__version__,
        schema_version=_read_schema_version(paths),
        shutdown_requested=shutdown_event,
        discovery_service=discovery_service,
        pane_service=pane_service,
        agent_service=agent_service,
        log_service=log_service,
        events_file=paths.events_file,
        lifecycle_logger=logger,
        events_reader=events_reader,
        follow_session_registry=follow_session_registry,
        events_config=events_config,
        state_conn=state_conn,
        queue_service=queue_service,
        routing_flag_service=routing_flag_service,
        delivery_worker=delivery_worker,
        queue_audit_writer=queue_audit_writer,
        message_queue_dao=message_queue_dao,
        daemon_state_dao=daemon_state_dao,
        routes_service=routes_service,
        routing_worker_thread=routing_worker_thread,
        routing_audit_writer=routing_audit_writer,
        routing_shared_state=routing_shared_state,
    )


def _assert_runtime_paths_safe(
    *,
    state_dir,
    logs_dir,
    lock_path,
    pid_path,
    log_path,
) -> bool:
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
        return False
    return True


def _recover_stale_artifacts(paths: Paths, pid_path, logger: LifecycleLogger) -> bool:
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
        return False
    return True


def _bind_control_server(
    paths: Paths, ctx: DaemonContext, logger: LifecycleLogger
) -> ControlServer | None:
    try:
        return ControlServer(paths.socket, ctx)
    except OSError as exc:
        logger.emit(EVENT_ERROR_FATAL, reason=f"bind failed: {exc}", level="fatal")
        print(f"error: bind socket: {paths.socket}: {exc}", file=sys.stderr)
        return None


def _install_signal_handlers(shutdown_event: threading.Event) -> None:
    def _signal_initiator(signum: int, _frame) -> None:  # noqa: ANN001
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _signal_initiator)
    signal.signal(signal.SIGINT, _signal_initiator)
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)


def _serve_until_shutdown(
    server: ControlServer, shutdown_event: threading.Event, logger: LifecycleLogger
) -> threading.Thread:
    accept_thread = threading.Thread(
        target=server.serve_forever, name="agenttowerd-accept", daemon=True
    )
    accept_thread.start()
    while not shutdown_event.wait(timeout=1.0):
        if not accept_thread.is_alive():
            break
    logger.emit(EVENT_DAEMON_SHUTDOWN, trigger="api_or_signal")
    server.shutdown()
    accept_thread.join(timeout=2.0)
    return accept_thread


def _cleanup_run(
    *,
    server: ControlServer | None,
    paths: Paths,
    scan_db_conn: sqlite3.Connection | None,
    pane_db_conn: sqlite3.Connection | None,
    pid_path,
    logger: LifecycleLogger | None,
    lock_fd: int,
    exit_code: int,
) -> None:
    if server is not None:
        try:
            server.server_close()
        except OSError:
            pass
        try:
            paths.socket.unlink()
        except FileNotFoundError:
            pass
    if scan_db_conn is not None:
        try:
            scan_db_conn.close()
        except Exception:
            pass
    if pane_db_conn is not None:
        try:
            pane_db_conn.close()
        except Exception:
            pass
    lifecycle.remove_pid_file(pid_path)
    if logger is not None:
        logger.emit(EVENT_DAEMON_EXITED, exit_code=exit_code)
        logger.close()
    lifecycle.release_lock(lock_fd)


def _run(args: argparse.Namespace) -> int:
    paths = resolve_paths()
    state_dir = paths.state_db.parent
    logs_dir = paths.logs_dir
    lock_path = state_dir / LOCK_FILENAME
    pid_path = state_dir / PID_FILENAME
    log_path = logs_dir / LOG_FILENAME

    _guard_feat008_test_seams_unset()
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
    except OSError as exc:
        print(f"error: acquire lock: {lock_path}: {exc}", file=sys.stderr)
        return 1

    logger: LifecycleLogger | None = None
    server: ControlServer | None = None
    scan_db_conn: sqlite3.Connection | None = None
    pane_db_conn: sqlite3.Connection | None = None
    exit_code = 0
    try:
        if not _assert_runtime_paths_safe(
            state_dir=state_dir,
            logs_dir=logs_dir,
            lock_path=lock_path,
            pid_path=pid_path,
            log_path=log_path,
        ):
            return 1

        logger = LifecycleLogger(log_path)
        logger.emit(
            EVENT_DAEMON_STARTING,
            pid=os.getpid(),
            state_dir=str(state_dir),
        )

        if not _recover_stale_artifacts(paths, pid_path, logger):
            return 1

        shutdown_event = threading.Event()
        discovery_service, scan_db_conn = _build_discovery_service(paths, logger)
        pane_service, pane_db_conn = _build_pane_service(paths, logger)
        agent_service = _build_agent_service(paths, logger)
        log_service = _build_log_service(paths, logger, agent_service.agent_locks)
        # Wire the log_service back into the agent_service so register-self
        # --attach-log (FR-034 / FR-035) can run the FEAT-007 attach atomically.
        agent_service.log_service = log_service

        # FR-043: orphan-recovery startup pass. Runs AFTER schema migration
        # (which is triggered earlier by ``_verify_feat001_initialized`` →
        # ``state.schema.open_registry`` at line ~380; ``_read_schema_version``
        # is a SELECT-only probe and does NOT apply migrations) and BEFORE
        # the socket listener starts accepting connections. Best-effort;
        # never blocks daemon startup on tmux/docker errors.
        try:
            detect_orphans(
                connection_factory=lambda: sqlite3.connect(
                    str(paths.state_db),
                    isolation_level=None,
                    timeout=_SQLITE_DEFAULT_TIMEOUT_SECONDS,
                ),
                docker_exec_runner=log_service.docker_exec_runner,
                daemon_home=Path(os.path.expanduser("~")),
                lifecycle_logger=logger,
            )
        except Exception:  # pragma: no cover — defensive; orphan detection is best-effort
            pass

        # FEAT-008 T031 — start the events reader thread + follow
        # session registry. The reader walks active log_attachments
        # rows once per cycle (≤ 1 s by default; FR-001) and persists
        # classified events. Constructed AFTER the orphan-recovery
        # pass so it never observes stale state, and BEFORE the socket
        # server starts accepting connections so ``agenttower status``
        # immediately reports ``events_reader.running == true``.
        from .events.reader import EventsReader  # local import: heavy module
        from .events.session_registry import FollowSessionRegistry

        events_config = load_events_block(paths.config_file)
        follow_registry = FollowSessionRegistry()
        events_reader = EventsReader(
            state_db=paths.state_db,
            events_file=paths.events_file,
            lifecycle_logger=logger,
            follow_session_registry=follow_registry,
            cycle_cap_seconds=events_config.reader_cycle_wallclock_cap_seconds,
            per_cycle_byte_cap_bytes=events_config.per_cycle_byte_cap_bytes,
            per_event_excerpt_cap_bytes=events_config.per_event_excerpt_cap_bytes,
            excerpt_truncation_marker=events_config.excerpt_truncation_marker,
            debounce_activity_window_seconds=(
                events_config.debounce_activity_window_seconds
            ),
            pane_exited_grace_seconds=events_config.pane_exited_grace_seconds,
            long_running_grace_seconds=events_config.long_running_grace_seconds,
        )
        # C7 (review MEDIUM) — the reader thread is started BEFORE the
        # control socket binds (~10ms window). Events emitted in this
        # window are durably persisted to SQLite + JSONL. The first
        # ``events.follow_open`` call after the socket comes up sees
        # them via the documented ``--since`` backlog mechanism. No
        # follower can subscribe before the socket is bound, so no
        # event is "missed" — they're just observed via the backlog
        # path rather than the live notify.
        events_reader.start()

        # We enter the cleanup-shield IMMEDIATELY after starting the
        # events reader so its background thread is always stopped on
        # any subsequent startup failure — even one raised by
        # ``_build_feat009_services`` (which previously sat outside
        # this try, leaking the reader thread if FEAT-009 wiring
        # raised). The FEAT-009 services are constructed inside this
        # try; the inner ``try/finally`` below only guards resources
        # created AFTER _build_feat009_services returns.
        worker_conn = None
        delivery_worker = None
        routing_worker_thread = None
        routing_heartbeat_handle = None
        try:
            # FEAT-009 T048 — instantiate the queue/routing/delivery
            # services, run the FR-040 recovery pass synchronously,
            # then start the delivery worker thread. Order matters:
            # recovery_pass MUST commit BEFORE the worker thread
            # starts (research §R-012) so the worker never picks up a
            # row still in ``delivery_attempt_started_at`` limbo from
            # a prior crash.
            (
                worker_conn,
                queue_service,
                routing_flag,
                audit_writer,
                delivery_worker,
                message_queue_dao,
                daemon_state_dao,
            ) = _build_feat009_services(
                paths=paths,
                discovery_service=discovery_service,
                pane_service=pane_service,
            )

            # FEAT-010 T025 — spawn routing worker AFTER delivery
            # worker is running (plan §Implementation Invariants §1).
            # The worker reads enabled routes on each cycle and fires
            # them through the existing queue_service.enqueue_route_message
            # path; FEAT-009 plumbing handles the rest. T054: also
            # spawns the heartbeat thread.
            (
                routes_service,
                routes_audit_writer,
                routing_shared_state,
                routing_worker_thread,
                routing_heartbeat_handle,
            ) = _build_feat010_services(
                paths=paths,
                queue_service=queue_service,
            )
            ctx = _build_context(
                paths=paths,
                state_dir=state_dir,
                shutdown_event=shutdown_event,
                discovery_service=discovery_service,
                pane_service=pane_service,
                agent_service=agent_service,
                log_service=log_service,
                logger=logger,
                events_reader=events_reader,
                follow_session_registry=follow_registry,
                events_config=events_config,
                state_conn=worker_conn,
                queue_service=queue_service,
                routing_flag_service=routing_flag,
                delivery_worker=delivery_worker,
                queue_audit_writer=audit_writer,
                message_queue_dao=message_queue_dao,
                daemon_state_dao=daemon_state_dao,
                routes_service=routes_service,
                routing_worker_thread=routing_worker_thread,
                routing_audit_writer=routes_audit_writer,
                routing_shared_state=routing_shared_state,
            )

            server = _bind_control_server(paths, ctx, logger)
            if server is None:
                return 1

            lifecycle.write_pid_file(pid_path, os.getpid())
            logger.emit(EVENT_DAEMON_READY, socket=str(paths.socket), pid=os.getpid())
            _install_signal_handlers(shutdown_event)
            _serve_until_shutdown(server, shutdown_event, logger)
        finally:
            # Stop the worker BEFORE the events reader so the worker's
            # final audit writes don't race the reader's cycle. Group-A
            # walk Q4: abort-not-drain shutdown — the next boot's
            # recovery pass cleans up any in-flight row.
            #
            # ``delivery_worker`` / ``worker_conn`` may still be None
            # if ``_build_feat009_services`` raised before assigning
            # them; skip in that case.
            #
            # Shutdown ordering per plan §Implementation Invariants §1:
            # routing worker stops FIRST (no new route-generated rows),
            # then the heartbeat thread, then the FEAT-009 delivery
            # worker drains.
            if routing_worker_thread is not None:
                try:
                    routing_worker_thread.stop()
                except Exception:  # pragma: no cover — defensive
                    pass
            if routing_heartbeat_handle is not None:
                try:
                    routing_heartbeat_handle.stop()
                except Exception:  # pragma: no cover — defensive
                    pass
            if delivery_worker is not None:
                try:
                    delivery_worker.stop()
                except Exception:  # pragma: no cover — defensive
                    pass
            if worker_conn is not None:
                try:
                    worker_conn.close()
                except Exception:  # pragma: no cover — defensive
                    pass
            # Always stop the reader thread, regardless of which phase of
            # startup raised — including a failure inside
            # ``_build_feat009_services`` — so the reader thread is
            # never leaked on a partial startup.
            events_reader.stop()
    finally:
        _cleanup_run(
            server=server,
            paths=paths,
            scan_db_conn=scan_db_conn,
            pane_db_conn=pane_db_conn,
            pid_path=pid_path,
            logger=logger,
            lock_fd=lock_fd,
            exit_code=exit_code,
        )

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
