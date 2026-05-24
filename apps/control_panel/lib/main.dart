import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:window_manager/window_manager.dart';

import 'app.dart';
import 'core/logging/rotating_file_logger.dart';
import 'core/logging/uncaught_error_handler.dart';
import 'core/persistence/paths.dart';

/// App entrypoint. T044 (Phase 2 Foundational).
///
/// Wires (in order):
///   1. WidgetsFlutterBinding (required for path_provider + window_manager)
///   2. AppPaths.initialize() — per-OS app-data dir per R-06
///   3. RotatingFileLogger — local log file per FR-074 + R-26
///   4. WindowManager (window geometry restore — research R-11)
///   5. runWithErrorHandling wraps runApp so uncaught exceptions hit the log
///
/// The actual provider-graph wiring + bootstrap of [DaemonSession],
/// [UxStateRepository], settings, etc. happens inside `ProviderScope`
/// via overrides — but the per-Provider setup for each is lazy and lands
/// in the US-phase tasks that consume them.
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final paths = await AppPaths.initialize();
  final logger = RotatingFileLogger(paths: paths);
  await logger.initialize();

  await windowManager.ensureInitialized();
  // Window geometry persistence wiring lands in T143 (Settings); for MVP
  // bootstrap we just open a default-sized window.
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

  runWithErrorHandling(
    logger,
    () => runApp(
      ProviderScope(
        // Provider overrides for paths + logger so feature widgets can
        // read them via Riverpod. Concrete provider declarations land in
        // each feature's file.
        child: const AgentTowerControlPanel(),
      ),
    ),
  );
}
