import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// Per-OS app-data directory resolution. T016 (Phase 2 Foundational).
///
/// Uses path_provider's [getApplicationSupportDirectory] per research R-06:
/// - Linux:   $XDG_DATA_HOME/agenttower-control-panel/   (≈ ~/.local/share/agenttower-control-panel/)
/// - macOS:   ~/Library/Application Support/agenttower-control-panel/
/// - Windows: %LOCALAPPDATA%\agenttower-control-panel\
///
/// Satisfies FR-061a per-OS-user isolation invariant — paths resolve
/// per-user via OS conventions; no cross-user file access.
class AppPaths {
  AppPaths._(this.appDataDir);

  final Directory appDataDir;

  static const String _appNamespace = 'agenttower-control-panel';

  static AppPaths? _instance;

  /// Initializes the per-OS path. Idempotent — subsequent calls return the
  /// cached instance.
  static Future<AppPaths> initialize() async {
    if (_instance != null) return _instance!;
    final support = await getApplicationSupportDirectory();
    final dir = Directory('${support.path}${Platform.pathSeparator}$_appNamespace');
    if (!dir.existsSync()) {
      dir.createSync(recursive: true);
    }
    _instance = AppPaths._(dir);
    return _instance!;
  }

  /// `<app-data>/agenttower-control-panel/ux-state.json` per FR-069 + R-05.
  File get uxStateFile => File(_join('ux-state.json'));

  /// `<app-data>/agenttower-control-panel/ux-state.json.tmp` — atomic-write staging.
  File get uxStateTmp => File(_join('ux-state.json.tmp'));

  /// `<app-data>/agenttower-control-panel/logs/` per FR-074 + R-07.
  Directory get logsDir {
    final dir = Directory(_join('logs'));
    if (!dir.existsSync()) dir.createSync(recursive: true);
    return dir;
  }

  String _join(String name) =>
      '${appDataDir.path}${Platform.pathSeparator}$name';

  /// Quarantine path for corrupted ux-state (R-20 / contracts/ux-state.md §2).
  File uxStateQuarantine(DateTime ts) => File(_join(
        'ux-state.json.corrupt-'
        '${ts.toUtc().toIso8601String().replaceAll(RegExp(r'[:.]'), '-')}',
      ));

  /// Test-only override.
  static void resetForTesting() => _instance = null;
}
