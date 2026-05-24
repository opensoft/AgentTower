import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// Returns `true` iff `python3` resolves on PATH. Used by integration
/// tests as a `setUpAll` gate so CI environments without Python don't
/// fail with the confusing "Mock daemon failed to bind socket" error
/// — they `markTestSkipped` instead (review fix H4 / test lane).
Future<bool> isPython3Available({String executable = 'python3'}) async {
  try {
    final result = await Process.run(executable, ['--version']);
    return result.exitCode == 0;
  } catch (_) {
    return false;
  }
}

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
    required Directory tmpDir,
  })  : _process = process,
        _tmpDir = tmpDir;

  final String socketPath;
  final String fixturePath;
  final Process _process;
  final Directory _tmpDir;

  /// Spawns a fresh mock daemon. The [fixture] map is written to a temp file
  /// and passed to the harness. Returns once the harness has bound the socket
  /// (or throws on startup failure).
  ///
  /// [bindTimeout] caps how long we wait for the socket file to appear; the
  /// default of 5 s is generous enough to survive a cold Python interpreter
  /// start on a busy CI machine without making real-test feedback feel slow.
  static Future<MockDaemonClient> start({
    required Map<String, dynamic> fixture,
    String? socketPathOverride,
    String pythonExecutable = 'python3',
    Duration bindTimeout = const Duration(seconds: 5),
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
      // Swarm-review CR-2: previously `detachedWithStdio` made `kill` +
      // `exitCode` throw `Bad state: Process is detached` at teardown.
      // The harness IS the child of this test process; detachment is
      // unnecessary and breaks the SIGTERM + exitCode-wait in stop().
      mode: ProcessStartMode.normal,
    );

    final socketFile = File(socketPath);
    final deadline = DateTime.now().add(bindTimeout);
    while (DateTime.now().isBefore(deadline)) {
      if (socketFile.existsSync()) break;
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    if (!socketFile.existsSync()) {
      process.kill(ProcessSignal.sigkill);
      // Best-effort cleanup of the per-test temp directory before throwing.
      try {
        tmpDir.deleteSync(recursive: true);
      } catch (_) {
        // ignore — caller will see the bind failure anyway
      }
      throw StateError(
        'Mock daemon failed to bind socket at $socketPath '
        'within ${bindTimeout.inMilliseconds} ms',
      );
    }

    return MockDaemonClient._(
      socketPath: socketPath,
      fixturePath: fixtureFile.path,
      process: process,
      tmpDir: tmpDir,
    );
  }

  /// Kills the harness process + removes the socket file + per-test tmp dir.
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
    if (socketFile.existsSync()) {
      try {
        socketFile.deleteSync();
      } catch (_) {
        // Best-effort — the recursive tmpDir delete below will catch it.
      }
    }
    if (_tmpDir.existsSync()) {
      try {
        _tmpDir.deleteSync(recursive: true);
      } catch (_) {
        // Leave the leftover for the OS reaper rather than failing tearDown.
      }
    }
  }
}
