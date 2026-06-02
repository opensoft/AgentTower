import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:logger/logger.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';
import 'package:window_manager/window_manager.dart';

import 'app.dart';
import 'core/daemon/app_client.dart';
import 'core/daemon/contract_version.dart';
import 'core/daemon/preflight_client.dart';
import 'core/daemon/session.dart';
import 'core/daemon/socket_client.dart';
import 'core/logging/rotating_file_logger.dart';
import 'core/persistence/compatibility.dart';
import 'core/persistence/paths.dart';
import 'core/persistence/ux_state_repository.dart';
import 'core/providers.dart';
import 'core/update/release_feed_check.dart';
import 'features/agent_ops/module.dart';
import 'features/project_specs/module.dart';
import 'features/settings/module.dart';
import 'features/testing_demo/module.dart';

/// App entrypoint. T044 (Phase 2 Foundational).
///
/// Wires (in order, ALL inside one guarded zone so binding-init and
/// `runApp` share a zone and uncaught exceptions hit the log — see the
/// zone note on [main]):
///   1. WidgetsFlutterBinding (required for path_provider + window_manager)
///   2. AppPaths.initialize() — per-OS app-data dir per R-06
///   3. RotatingFileLogger — local log file per FR-074 + R-26
///   4. UxStateRepository — single owner of `ux-state.json`
///   5. Contract-version registry seed — per-surface FR-002 declarations
///   6. WindowManager + FR-082 close handler that flushes ux-state before exit
///   7. runApp, inside the same `runZonedGuarded` zone, so uncaught
///      exceptions hit the log (FR-074 / R-18)
///   8. ProviderScope override-list so feature widgets see live instances
///
/// The actual provider-graph wiring of per-story features
/// (`agent_ops/dashboard` etc.) is lazy — each US-phase task registers
/// its own providers.
///
/// Zone discipline (swarm-review HIGH): Flutter requires the binding to be
/// created in the same zone that later calls `runApp`. We therefore run the
/// WHOLE async bootstrap — including `WidgetsFlutterBinding.ensureInitialized()`
/// and every pre-`runApp` `await` — inside `runZonedGuarded`. This both
/// satisfies `BindingBase.debugCheckZone('runApp')` and guarantees the
/// FR-074 async-error capture covers bootstrap failures (an unwritable
/// app-data dir, a window_manager or platform-channel failure, etc.) instead
/// of letting them escape `main()` and die silently.
Future<void> main() async {
  // The logger is built inside the zone (it needs the binding + paths), so
  // the framework/platform error sinks read it through this holder once it
  // exists. Errors before logger-init still surface via `runZonedGuarded`'s
  // fallback below.
  RotatingFileLogger? logger;

  void logError(String event, Map<String, Object?> fields) {
    logger?.log(Level.error, event, fields);
  }

  FlutterError.onError = (FlutterErrorDetails details) {
    logError('uncaught_flutter_error', {
      'exception': details.exceptionAsString(),
      'library': details.library ?? '',
      'context': details.context?.toString() ?? '',
    });
    FlutterError.presentError(details);
  };
  PlatformDispatcher.instance.onError = (Object error, StackTrace stack) {
    logError('uncaught_platform_error', {
      'exception': error.toString(),
      'stack': stack.toString(),
    });
    return true;
  };

  final bootstrap = runZonedGuarded(
    () async {
      // Binding-init lives in THIS zone — same zone that calls `runApp`.
      WidgetsFlutterBinding.ensureInitialized();

      final paths = await AppPaths.initialize();
      logger = RotatingFileLogger(paths: paths);
      await logger!.initialize();

      final uxState = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      await uxState.load();

      // Round-4 analyze I-N1 (2026-05-24): wire `installedAppVersionProvider`
      // to the real `PackageInfo.fromPlatform().version` so VersionBadge,
      // VersionDisplayTile, and the FR-074 diagnostics bundle all display
      // the installed app version instead of the test-default '0.0.0-dev'.
      final packageInfo = await PackageInfo.fromPlatform();
      // PackageInfo.version can be empty on an unpopulated bundle manifest
      // (early MSIX packaging, an unwired Linux version.json, a dev run).
      // Fall back to the provider's own '0.0.0-dev' default so VersionBadge /
      // diagnostics never display a blank version (swarm-review LOW).
      final appVersion = packageInfo.version.trim().isEmpty
          ? '0.0.0-dev'
          : packageInfo.version;

      seedMvpContractDeclarations();
      registerAgentOps(); // Phase 3 US1 surfaces (T065-T076).
      registerProjectSpecs(); // Phase 4 US2 surfaces (T087-T094).
      registerTestingDemo(); // Phase 7 US5 surfaces (T124-T129).
      registerSettings(); // Phase 9 Settings surface (T143).

      final defaultSocketPath = await _defaultDaemonSocketPath();
      final socketClient = SocketClient(defaultSocketPath);
      final daemonSession = DaemonSession(client: socketClient);
      final appClient = AppClient(session: daemonSession);
      final preflightClient = PreflightClient(socketPath: defaultSocketPath);

      await windowManager.ensureInitialized();

      // FR-082 close-handler: flush pending ux-state writes within the 500 ms
      // cap before destroying the window. Best-effort — the cap is enforced
      // inside `UxStateRepository.flushBeforeExit`. After flush we close the
      // log sink so the on-disk record is consistent with what the operator
      // saw last frame. Registered BEFORE `setPreventClose(true)` and before
      // the window is shown so a close request can never land in a window
      // where `preventClose` is on but no listener exists to call `destroy()`
      // (swarm-review MEDIUM ordering fix).
      final shutdownListener = _ShutdownListener(
        uxState: uxState,
        logger: logger!,
        session: daemonSession,
      );
      windowManager.addListener(shutdownListener);
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

      runApp(
        ProviderScope(
          overrides: [
            appPathsProvider.overrideWithValue(paths),
            loggerProvider.overrideWithValue(logger!),
            uxStateRepositoryProvider.overrideWithValue(uxState),
            // Settings + FR-009 Doctor must check the SAME socket the live
            // client uses — feed them the bootstrap-resolved path.
            defaultSocketPathProvider.overrideWithValue(defaultSocketPath),
            socketClientProvider.overrideWithValue(socketClient),
            daemonSessionProvider.overrideWithValue(daemonSession),
            appClientProvider.overrideWithValue(appClient),
            preflightClientProvider.overrideWithValue(preflightClient),
            // Round-4 analyze I-N1: override the test-default stub with
            // the real installed version so FR-068 displays correctly.
            installedAppVersionProvider.overrideWithValue(appVersion),
          ],
          child: const AgentTowerControlPanel(),
        ),
      );
    },
    (Object error, StackTrace stack) {
      logError('uncaught_zone_error', {
        'exception': error.toString(),
        'stack': stack.toString(),
      });
    },
  );
  unawaited(bootstrap);
}

/// Default daemon socket path, resolved once at launch.
///
/// Settings → Connection (T143) persists an operator-chosen path, but the
/// live [SocketClient] is bound to this value for the process lifetime — an
/// edited path takes effect on the next launch, not live (swarm-review LOW:
/// the prior "overridden post-launch" claim was not implemented). Overridden
/// at BUILD time by `--dart-define=DAEMON_SOCKET_PATH=...` for tests (this is
/// a compile-time `String.fromEnvironment` const, not a runtime env var —
/// see the test_harness README; swarm-review LOW).
///
/// The default is derived per-OS-user (FR-061a per-OS-user isolation): no
/// system-wide path, and the Windows AF_UNIX path is rooted under the user's
/// `%LOCALAPPDATA%`, never a POSIX `/var/run` path which does not exist on
/// Windows (swarm-review HIGH).
Future<String> _defaultDaemonSocketPath() async {
  const envOverride = String.fromEnvironment('DAEMON_SOCKET_PATH');
  if (envOverride.isNotEmpty) return envOverride;

  if (Platform.isLinux) {
    // Prefer the per-user runtime dir; fall back to the XDG state path that
    // architecture.md documents for the host daemon socket
    // (`~/.local/state/opensoft/agenttower/agenttowerd.sock`).
    final runtimeDir = Platform.environment['XDG_RUNTIME_DIR'];
    if (runtimeDir != null && runtimeDir.isNotEmpty) {
      return '$runtimeDir/opensoft/agenttower/agenttowerd.sock';
    }
    final stateHome = Platform.environment['XDG_STATE_HOME'];
    final home = Platform.environment['HOME'] ?? '';
    final base = (stateHome != null && stateHome.isNotEmpty)
        ? stateHome
        : '$home/.local/state';
    return '$base/opensoft/agenttower/agenttowerd.sock';
  }

  if (Platform.isMacOS) {
    final home = Platform.environment['HOME'] ?? '';
    return '$home/Library/Application Support/opensoft/agenttower/'
        'agenttowerd.sock';
  }

  // Windows: Dart `dart:io` AF_UNIX sockets bind to a real filesystem path
  // (Windows 10 1809+ supports AF_UNIX). Root it under the per-OS-user
  // app-data dir so each OS user gets its own socket (FR-061a). We reuse
  // path_provider's application-support dir — the same per-user
  // `%LOCALAPPDATA%`-derived root [AppPaths] uses.
  final support = await getApplicationSupportDirectory();
  return '${support.path}${Platform.pathSeparator}agenttower'
      '${Platform.pathSeparator}agenttowerd.sock';
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

  // One-shot guard: `setPreventClose(true)` means every close attempt
  // (repeat close-button click, alt-F4 repeat, OS logout) re-dispatches
  // `onWindowClose`. Without this guard a second event would run the
  // shutdown sequence concurrently and double-invoke `destroy()`
  // (swarm-review MEDIUM re-entrancy fix).
  bool _closing = false;

  // NOTE: `WindowListener.onWindowClose` is declared `void` in
  // window_manager 0.4.3 and the dispatcher invokes it WITHOUT awaiting the
  // returned future, so this whole chain runs fire-and-forget. Every step —
  // including the final `destroy()` — is wrapped in try/catch so the FR-082
  // shutdown path is uniformly best-effort and produces no unhandled async
  // rejection (swarm-review MEDIUM).
  @override
  void onWindowClose() async {
    if (_closing) return;
    _closing = true;
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
    try {
      await windowManager.destroy();
    } catch (_) {
      // ignore — destroy() is the only teardown path; keep it best-effort.
    }
  }
}
