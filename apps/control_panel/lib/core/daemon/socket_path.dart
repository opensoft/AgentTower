import 'dart:io';

/// Resolves the default daemon Unix-socket path.
///
/// This MUST match (a) the CLI/daemon default in `src/agenttower/paths.py`
/// and (b) the bootstrap resolver `_defaultDaemonSocketPath()` in `main.dart`,
/// so the Settings surface + FR-009 Doctor check the *same* socket the app
/// actually connects to. Synchronous so it can back a Riverpod provider
/// default without an async gap (the previous hard-coded
/// `/var/run/agenttower/app.sock` default disagreed with the live socket and
/// made the Doctor's "socket reachable" check target the wrong path on a
/// fresh install).
///
/// The compile-time `DAEMON_SOCKET_PATH` define mirrors `main.dart`'s override
/// hook. The Windows branch uses `%LOCALAPPDATA%` directly rather than
/// `path_provider` (which is async); `main.dart` overrides the provider with
/// the `path_provider`-resolved value at bootstrap so production is exact on
/// every OS — this default backs tests/harnesses.
String defaultDaemonSocketPath() {
  const envOverride = String.fromEnvironment('DAEMON_SOCKET_PATH');
  if (envOverride.isNotEmpty) return envOverride;

  final env = Platform.environment;

  if (Platform.isLinux) {
    final runtimeDir = env['XDG_RUNTIME_DIR'];
    if (runtimeDir != null && runtimeDir.isNotEmpty) {
      return '$runtimeDir/opensoft/agenttower/agenttowerd.sock';
    }
    final stateHome = env['XDG_STATE_HOME'];
    final home = env['HOME'] ?? '';
    final base = (stateHome != null && stateHome.isNotEmpty)
        ? stateHome
        : '$home/.local/state';
    return '$base/opensoft/agenttower/agenttowerd.sock';
  }

  if (Platform.isMacOS) {
    final home = env['HOME'] ?? '';
    return '$home/Library/Application Support/opensoft/agenttower/'
        'agenttowerd.sock';
  }

  // Windows: AF_UNIX path under the per-OS-user app-data root (FR-061a).
  final localAppData = env['LOCALAPPDATA'] ?? env['APPDATA'] ?? '';
  return '$localAppData\\agenttower\\agenttowerd.sock';
}
