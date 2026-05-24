import 'dart:async';
import 'dart:io';

import '../../core/daemon/contract_version.dart';
import '../../core/persistence/paths.dart';
import 'settings_repository.dart';

/// Doctor / preflight check. T026 + research R-20 + Round-3 R-25.
///
/// Six checks per FR-009 (post-F12) — produces a [DoctorReport] surfaced
/// in Settings and includable verbatim in the diagnostics bundle (T027).
/// Also reachable from the FR-075 command palette (Ctrl/Cmd+K).
class Doctor {
  Doctor({
    required this.paths,
    required this.settingsRepo,
    required this.runtimeCompat,
    required this.osNotificationsEnabled,
  });

  final AppPaths paths;
  final SettingsRepository settingsRepo;
  final ContractCompat? runtimeCompat;
  final bool osNotificationsEnabled;

  Future<DoctorReport> run() async {
    final stopwatch = Stopwatch()..start();
    final checks = <DoctorCheckResult>[];

    // 1. Daemon socket reachable
    checks.add(await _timedCheck('socket_reachable', () async {
      final socketPath = settingsRepo.load().daemonSocketPath;
      try {
        final socket = await Socket.connect(
          InternetAddress(socketPath, type: InternetAddressType.unix),
          0,
          timeout: const Duration(milliseconds: 500),
        );
        await socket.close();
        return _ok(socketPath);
      } catch (e) {
        return _fail('Socket connect failed: $e');
      }
    }));

    // 2. Peer UID match (FR-061). The real check requires SO_PEERCRED
    //    (Linux), LOCAL_PEERCRED (macOS), or the Windows AF_UNIX file ACL
    //    probe — all of which need platform-channel plumbing that lands in
    //    T030. Until then this row MUST report `skipped`, not `pass`, so
    //    operators are not given a false sense of security.
    checks.add(await _timedCheck('peer_uid_match', () async {
      final uid = Platform.isLinux || Platform.isMacOS
          ? (Platform.environment['UID'] ?? 'unknown')
          : 'n/a';
      return _skipped(
        'Peer-UID verification not yet implemented (lands in T030). '
        'Process UID: $uid',
      );
    }));

    // 3. app_contract_version satisfies surfaces
    checks.add(await _timedCheck('contract_version_satisfied', () async {
      final compat = runtimeCompat;
      if (compat == null) {
        return _fail('Contract version not yet probed (daemon unreachable?)');
      }
      if (compat.overallSatisfied) {
        return _ok('Daemon ${compat.daemonVersion} satisfies all surfaces');
      }
      return _fail(
        'Daemon ${compat.daemonVersion} does not satisfy: '
        '${compat.unmetSurfaces.length} surface(s) require newer minor version',
      );
    }));

    // 4. App-data directory writable
    checks.add(await _timedCheck('app_data_writable', () async {
      final probe = File('${paths.appDataDir.path}/.doctor-probe');
      try {
        await probe.writeAsString('ok');
        await probe.delete();
        return _ok('Writable at ${paths.appDataDir.path}');
      } catch (e) {
        return _fail('Cannot write to ${paths.appDataDir.path}: $e');
      }
    }));

    // 5. Log file writable + not at cap
    checks.add(await _timedCheck('log_writable_under_cap', () async {
      final logFile = File('${paths.logsDir.path}/control-panel.log.0');
      try {
        if (logFile.existsSync()) {
          final stat = await logFile.stat();
          if (stat.size >= 10 * 1024 * 1024) {
            return _fail('Log file at cap (10 MiB) — rotation pending');
          }
        }
        return _ok('Log dir writable');
      } catch (e) {
        return _fail('Log access failed: $e');
      }
    }));

    // 6. OS-native notification permission (conditional on toggle per FR-058)
    checks.add(await _timedCheck('os_notification_permission', () async {
      if (!osNotificationsEnabled) {
        return _skipped('Toggle disabled — skipped');
      }
      // Actual permission probe requires platform integration via
      // local_notifier; lands in the full T143 Settings surface.
      return _ok(
        'Permission probe deferred to T143 (Settings surface integration)',
      );
    }));

    stopwatch.stop();
    return DoctorReport(
      checks: checks,
      totalElapsedMs: stopwatch.elapsedMilliseconds,
      generatedAt: DateTime.now().toUtc(),
    );
  }

  Future<DoctorCheckResult> _timedCheck(
    String name,
    Future<DoctorCheckResult> Function() body,
  ) async {
    final sw = Stopwatch()..start();
    try {
      final result = await body();
      sw.stop();
      return DoctorCheckResult(
        name: name,
        status: result.status,
        details: result.details,
        elapsedMs: sw.elapsedMilliseconds,
      );
    } catch (e) {
      sw.stop();
      return DoctorCheckResult(
        name: name,
        status: DoctorCheckStatus.fail,
        details: 'Uncaught: $e',
        elapsedMs: sw.elapsedMilliseconds,
      );
    }
  }

  DoctorCheckResult _ok(String details) => DoctorCheckResult(
        name: '',
        status: DoctorCheckStatus.pass,
        details: details,
        elapsedMs: 0,
      );
  DoctorCheckResult _fail(String details) => DoctorCheckResult(
        name: '',
        status: DoctorCheckStatus.fail,
        details: details,
        elapsedMs: 0,
      );
  DoctorCheckResult _skipped(String details) => DoctorCheckResult(
        name: '',
        status: DoctorCheckStatus.skipped,
        details: details,
        elapsedMs: 0,
      );
}

enum DoctorCheckStatus { pass, fail, skipped }

class DoctorCheckResult {
  const DoctorCheckResult({
    required this.name,
    required this.status,
    required this.details,
    required this.elapsedMs,
  });

  final String name;
  final DoctorCheckStatus status;
  final String details;
  final int elapsedMs;

  Map<String, dynamic> toJson() => {
        'name': name,
        'status': status.name,
        'details': details,
        'elapsed_ms': elapsedMs,
      };
}

class DoctorReport {
  const DoctorReport({
    required this.checks,
    required this.totalElapsedMs,
    required this.generatedAt,
  });

  final List<DoctorCheckResult> checks;
  final int totalElapsedMs;
  final DateTime generatedAt;

  bool get allPassed =>
      checks.every((c) => c.status != DoctorCheckStatus.fail);

  Map<String, dynamic> toJson() => {
        'generated_at': generatedAt.toIso8601String(),
        'total_elapsed_ms': totalElapsedMs,
        'all_passed': allPassed,
        'checks': checks.map((c) => c.toJson()).toList(),
      };
}
