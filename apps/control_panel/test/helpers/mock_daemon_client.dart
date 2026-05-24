import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// Spawns the Python mock-daemon harness (T050) for an integration test.
/// T052 (Phase 2 Foundational).
///
/// Each test gets its own harness process + unique socket path so there is no
/// cross-test state pollution. Tear down via [stop] in test `tearDown`.
class MockDaemonClient {
  MockDaemonClient._({
    required this.socketPath,
    required this.fixturePath,
    required Process process,
  }) : _process = process;

  final String socketPath;
  final String fixturePath;
  final Process _process;

  /// Spawns a fresh mock daemon. The [fixture] map is written to a temp file
  /// and passed to the harness. Returns once the harness has bound the socket
  /// (or throws on startup failure).
  static Future<MockDaemonClient> start({
    required Map<String, dynamic> fixture,
    String? socketPathOverride,
    String pythonExecutable = 'python3',
  }) async {
    final tmpDir = Directory.systemTemp.createTempSync('feat012-mock-');
    final socketPath =
        socketPathOverride ?? '${tmpDir.path}/agenttower-mock.sock';
    final fixtureFile = File('${tmpDir.path}/fixture.json');
    await fixtureFile.writeAsString(json.encode(fixture));

    // Resolve harness location relative to this file.
    // Test runners cd to `apps/control_panel/`, so the harness is at
    // `test_harness/mock_daemon/server.py` from there.
    final harness =
        File('test_harness/mock_daemon/server.py').absolute.path;

    final process = await Process.start(
      pythonExecutable,
      [
        harness,
        '--socket',
        socketPath,
        '--fixture',
        fixtureFile.path,
      ],
      mode: ProcessStartMode.detachedWithStdio,
    );

    // Wait up to 2 s for the socket to appear.
    final socketFile = File(socketPath);
    final deadline = DateTime.now().add(const Duration(seconds: 2));
    while (DateTime.now().isBefore(deadline)) {
      if (socketFile.existsSync()) break;
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    if (!socketFile.existsSync()) {
      process.kill(ProcessSignal.sigkill);
      throw StateError(
        'Mock daemon failed to bind socket at $socketPath within 2 s',
      );
    }

    return MockDaemonClient._(
      socketPath: socketPath,
      fixturePath: fixtureFile.path,
      process: process,
    );
  }

  /// Kills the harness process + removes the socket file.
  Future<void> stop() async {
    _process.kill(ProcessSignal.sigterm);
    await _process.exitCode.timeout(
      const Duration(seconds: 2),
      onTimeout: () {
        _process.kill(ProcessSignal.sigkill);
        return -1;
      },
    );
    final socketFile = File(socketPath);
    if (socketFile.existsSync()) socketFile.deleteSync();
  }
}
