import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:window_manager/window_manager.dart';

import 'app.dart';
import 'core/daemon/app_client.dart';
import 'core/daemon/contract_version.dart';
import 'core/daemon/preflight_client.dart';
import 'core/daemon/session.dart';
import 'core/daemon/socket_client.dart';
import 'core/logging/rotating_file_logger.dart';
import 'core/logging/uncaught_error_handler.dart';
import 'core/persistence/compatibility.dart';
import 'core/persistence/paths.dart';
import 'core/persistence/ux_state_repository.dart';
import 'core/providers.dart';
import 'features/agent_ops/module.dart';
import 'features/project_specs/module.dart';

/// App entrypoint. T044 (Phase 2 Foundational).
///
/// Wires (in order):
///   1. WidgetsFlutterBinding (required for path_provider + window_manager)
///   2. AppPaths.initialize() — per-OS app-data dir per R-06
///   3. RotatingFileLogger — local log file per FR-074 + R-26
///   4. UxStateRepository — single owner of `ux-state.json`
///   5. Contract-version registry seed — per-surface FR-002 declarations
///   6. WindowManager + FR-082 close handler that flushes ux-state before exit
///   7. runWithErrorHandling wraps runApp so uncaught exceptions hit the log
///   8. ProviderScope override-list so feature widgets see live instances
///
/// The actual provider-graph wiring of per-story features
/// (`agent_ops/dashboard` etc.) is lazy — each US-phase task registers
/// its own providers.
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final paths = await AppPaths.initialize();
  final logger = RotatingFileLogger(paths: paths);
  await logger.initialize();

  final uxState = UxStateRepository(
    paths: paths,
    compatibility: const LaunchCompatibility(
      currentAppMajor: 0,
      currentContractMajor: 1,
    ),
  );
  await uxState.load();

  seedMvpContractDeclarations();
  registerAgentOps(); // Phase 3 US1 surfaces (T065-T076).
  registerProjectSpecs(); // Phase 4 US2 surfaces (T087-T094).

  final socketClient = SocketClient(_defaultDaemonSocketPath());
  final daemonSession = DaemonSession(client: socketClient);
  final appClient = AppClient(session: daemonSession);
  final preflightClient =
      PreflightClient(socketPath: _defaultDaemonSocketPath());

  await windowManager.ensureInitialized();
  await windowManager.setPreventClose(true);
  const opts = WindowOptions(
    size: Size(1280, 800),
    minimumSize: Size(960, 640),
    center: true,
    title: 'AgentTower Control Panel',
  );
  await windowManager.waitUntilReadyToShow(opts, () async {
    await windowManager.show();
    await windowManager.focus();
  });

  // FR-082 close-handler: flush pending ux-state writes within the 500 ms
  // cap before destroying the window. Best-effort — the cap is enforced
  // inside `UxStateRepository.flushBeforeExit`. After flush we close the
  // log sink so the on-disk record is consistent with what the operator
  // saw last frame.
  windowManager.addListener(_ShutdownListener(
    uxState: uxState,
    logger: logger,
    session: daemonSession,
  ));

  runWithErrorHandling(
    logger,
    () => runApp(
      ProviderScope(
        overrides: [
          appPathsProvider.overrideWithValue(paths),
          loggerProvider.overrideWithValue(logger),
          uxStateRepositoryProvider.overrideWithValue(uxState),
          socketClientProvider.overrideWithValue(socketClient),
          daemonSessionProvider.overrideWithValue(daemonSession),
          appClientProvider.overrideWithValue(appClient),
          preflightClientProvider.overrideWithValue(preflightClient),
        ],
        child: const AgentTowerControlPanel(),
      ),
    ),
  );
}

/// Default daemon socket path. Overridden by Settings → Connection
/// (T143) and by env-var DAEMON_SOCKET_PATH during tests.
String _defaultDaemonSocketPath() {
  // The MVP default is the same path FEAT-011 documents for the host
  // daemon socket; Settings → Connection lets the operator override it
  // post-launch.
  const envOverride = String.fromEnvironment('DAEMON_SOCKET_PATH');
  if (envOverride.isNotEmpty) return envOverride;
  return '/var/run/agenttower/app.sock';
}

class _ShutdownListener with WindowListener {
  _ShutdownListener({
    required this.uxState,
    required this.logger,
    required this.session,
  });

  final UxStateRepository uxState;
  final RotatingFileLogger logger;
  final DaemonSession session;

  @override
  void onWindowClose() async {
    try {
      await uxState.flushBeforeExit();
    } catch (_) {
      // Per FR-082 the app closes regardless; flush is best-effort.
    }
    try {
      await session.dispose();
    } catch (_) {
      // ignore
    }
    try {
      await logger.close();
    } catch (_) {
      // ignore
    }
    await windowManager.destroy();
  }
}
