import 'dart:convert';
import 'dart:io';

import '../../core/daemon/contract_version.dart';
import '../../core/persistence/paths.dart';
import 'doctor.dart';

/// "Copy diagnostics bundle" implementation. T027 + Round-3 R-31.
///
/// Bundle contents per R-31:
///   1. Rotating log files (post-redaction)
///   2. App version + contract version + socket path + OS user
///   3. Doctor report verbatim
///   4. Session-start + bundle-generation timestamps
///
/// Preview window shown BEFORE save/copy listing file inventory + first/last
/// 20 lines of each log. Size cap 50 MiB; trim-picker if exceeded.
///
/// Bundle format: `.zip` archive saved via OS file picker (operator picks
/// destination); clipboard option for bundles ≤ 1 MiB. Per R-26 + R-31.
class DiagnosticsBundle {
  DiagnosticsBundle({
    required this.paths,
    required this.appVersion,
    required this.contractVersion,
    required this.socketPath,
    required this.osUser,
    required this.doctorReport,
    required this.sessionStart,
  });

  static const int maxBundleBytes = 50 * 1024 * 1024; // 50 MiB cap per R-31
  static const int clipboardThresholdBytes = 1024 * 1024; // 1 MiB per R-26

  final AppPaths paths;
  final String appVersion;
  final ContractVersion contractVersion;
  final String socketPath;
  final String osUser;
  final DoctorReport doctorReport;
  final DateTime sessionStart;

  /// Builds the JSON manifest that's included as `manifest.json` inside the zip.
  Map<String, dynamic> manifest() => {
        'app_version': appVersion,
        'app_contract_version': contractVersion.toString(),
        'socket_path': socketPath,
        'os_user': osUser,
        'session_start': sessionStart.toUtc().toIso8601String(),
        'bundle_generated_at': DateTime.now().toUtc().toIso8601String(),
        'doctor_report': doctorReport.toJson(),
      };

  /// Returns the preview info: per-file inventory, first/last 20 lines of
  /// each log, AND the manifest fields the operator is about to send out
  /// (review fix S3 — previously the preview omitted `socket_path` and
  /// `os_user`, so an operator running `Copy diagnostics bundle` had no
  /// way to confirm what host metadata would leak). UI shows this BEFORE
  /// save/copy so the operator can confirm contents.
  Future<BundlePreview> buildPreview() async {
    final entries = <BundleEntry>[];
    final dir = paths.logsDir;
    final logFiles = dir
        .listSync()
        .whereType<File>()
        .where((f) => f.path.contains('control-panel.log.'))
        .toList()
      ..sort((a, b) => a.path.compareTo(b.path));

    int totalBytes = 0;
    for (final f in logFiles) {
      final stat = await f.stat();
      final lines = await f.readAsLines();
      final first20 = lines.take(20).toList();
      final last20 = lines.length > 40
          ? lines.skip(lines.length - 20).toList()
          : <String>[];
      entries.add(BundleEntry(
        path: f.path,
        sizeBytes: stat.size,
        first20Lines: first20,
        last20Lines: last20,
      ));
      totalBytes += stat.size;
    }
    final manifestData = manifest();
    final manifestBytes = utf8.encode(json.encode(manifestData)).length;
    totalBytes += manifestBytes;

    return BundlePreview(
      entries: entries,
      manifest: manifestData,
      manifestSizeBytes: manifestBytes,
      totalBytes: totalBytes,
      exceedsCap: totalBytes > maxBundleBytes,
      smallEnoughForClipboard: totalBytes <= clipboardThresholdBytes,
    );
  }

  // Actual zip-write + file-picker integration land in T143 (Settings surface
  // T143 + the Phase 9 polish wiring). For now this class provides the
  // preview + manifest construction that the UI layer will use.
}

class BundleEntry {
  const BundleEntry({
    required this.path,
    required this.sizeBytes,
    required this.first20Lines,
    required this.last20Lines,
  });
  final String path;
  final int sizeBytes;
  final List<String> first20Lines;
  final List<String> last20Lines;
}

class BundlePreview {
  const BundlePreview({
    required this.entries,
    required this.manifest,
    required this.manifestSizeBytes,
    required this.totalBytes,
    required this.exceedsCap,
    required this.smallEnoughForClipboard,
  });
  final List<BundleEntry> entries;

  /// Full manifest contents (app_version, app_contract_version, socket_path,
  /// os_user, session_start, bundle_generated_at, doctor_report). The UI
  /// renders this so the operator can confirm what host metadata leaves
  /// the machine before committing the save/copy.
  final Map<String, dynamic> manifest;

  final int manifestSizeBytes;
  final int totalBytes;
  final bool exceedsCap;
  final bool smallEnoughForClipboard;
}
