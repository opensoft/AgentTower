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
    final dst = paths.uxStateQuarantine(DateTime.now());
    await src.rename(dst.path);
    return dst;
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
