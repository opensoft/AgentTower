import 'dart:io';

import 'paths.dart';

/// UX-state corruption quarantine. T020 (Phase 2 Foundational).
///
/// Per contracts/ux-state.md §2 §corruption-recovery:
/// - If `ux-state.json` parses as invalid JSON or fails schema validation,
///   move it aside to `ux-state.json.corrupt-<timestamp>` (do NOT delete)
/// - Write fresh defaults in its place
/// - Log a single ERROR entry per FR-074 naming the quarantine path
/// - Operator continues to onboarding/Dashboard as if fresh-install
class CorruptionQuarantine {
  CorruptionQuarantine({required this.paths});

  final AppPaths paths;

  /// Quarantines the existing `ux-state.json` and returns the quarantine
  /// path. Caller is responsible for writing fresh defaults afterwards.
  Future<File> quarantineCurrent() async {
    final src = paths.uxStateFile;
    if (!src.existsSync()) {
      throw StateError('No ux-state.json to quarantine');
    }
    // `paths.uxStateQuarantine` embeds an ISO-8601 timestamp containing `:`
    // characters, which are illegal in Windows (NTFS) filenames and make
    // `rename` throw a FileSystemException there. Sanitize the generated
    // destination path so quarantine works on ALL platforms.
    final dst = _sanitizeQuarantinePath(paths.uxStateQuarantine(DateTime.now()));
    await src.rename(dst.path);
    return dst;
  }

  /// Returns a copy of [file] whose **basename** has the filesystem-illegal
  /// `:` characters from the ISO-8601 quarantine stamp replaced with `-`.
  /// Only the basename is rewritten so directory components (including a
  /// Windows `C:\` drive-letter colon) are preserved. The `.` in the
  /// fractional-seconds is legal in filenames and is intentionally kept.
  File _sanitizeQuarantinePath(File file) {
    final path = file.path;
    // Find the last separator, handling both POSIX `/` and Windows `\`.
    final lastSep =
        path.lastIndexOf(RegExp(r'[/\\]'));
    final dir = lastSep >= 0 ? path.substring(0, lastSep + 1) : '';
    final name = lastSep >= 0 ? path.substring(lastSep + 1) : path;
    final safeName = name.replaceAll(':', '-');
    return File('$dir$safeName');
  }

  /// True iff a quarantine file exists from a prior crash (used by the
  /// Settings → Doctor surface to alert the operator).
  bool hasQuarantineFile() {
    final parent = paths.appDataDir;
    if (!parent.existsSync()) return false;
    return parent
        .listSync()
        .whereType<File>()
        .any((f) => f.path.contains('ux-state.json.corrupt-'));
  }
}
