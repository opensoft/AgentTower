import 'dart:async';
import 'dart:convert';

import 'compatibility.dart';
import 'corruption.dart';
import 'migrations.dart';
import 'paths.dart';

/// Single owner of `ux-state.json` read/write. T017 (Phase 2 Foundational).
///
/// Per data-model.md §3:
/// - Atomic write via `.tmp` + fsync + rename (R-05)
/// - Debounced 250ms cadence + immediate flush on FR-082 close (cap 500ms)
/// - Forward-only schema migrations applied on read (R-21)
/// - FR-070 compatibility gate on launch
///
/// This is the ONLY file the desktop app writes (per FR-005, FR-069). The
/// session token (FR-003) and all daemon-owned domain data are NEVER
/// persisted by this repository.
///
/// Minimal read/write surface of the persisted `ux_state` map. Feature
/// repositories that own a slice of the shared file (e.g.
/// `SortFilterRepository`, T179) depend on this interface rather than the
/// concrete [UxStateRepository] so they can be unit-tested against an
/// in-memory double without a real on-disk file. [UxStateRepository]
/// implements it directly.
abstract interface class UxStateStore {
  /// In-memory snapshot of the `ux_state` payload, or `null` before load.
  Map<String, dynamic>? get current;

  /// Replaces the in-memory state and schedules a debounced atomic flush.
  void update(Map<String, dynamic> newState);
}

class UxStateRepository implements UxStateStore {
  UxStateRepository({
    required this.paths,
    required this.compatibility,
    Duration debounceWindow = const Duration(milliseconds: 250),
    Duration closeFlushCap = const Duration(milliseconds: 500),
  })  : _debounceWindow = debounceWindow,
        _closeFlushCap = closeFlushCap;

  final AppPaths paths;
  final LaunchCompatibility compatibility;
  final Duration _debounceWindow;
  final Duration _closeFlushCap;

  Map<String, dynamic>? _state;
  Timer? _debounceTimer;
  bool _hasUnflushed = false;
  final _writeLock = _AsyncLock();

  /// Reads `ux-state.json` from disk. Returns:
  /// - `null` if the file does not exist (fresh install)
  /// - `null` if the persisted state's app major / contract major do not
  ///   match the current run per FR-070 (the operator lands on
  ///   onboarding/Dashboard with defaults)
  /// - the parsed `ux_state` payload otherwise (after migration to
  ///   [MigrationRegistry.currentSchemaVersion])
  ///
  /// On parse failure: quarantines via [CorruptionQuarantine] + returns null.
  Future<Map<String, dynamic>?> load() async {
    final file = paths.uxStateFile;
    if (!file.existsSync()) return null;

    String contents;
    try {
      contents = await file.readAsString();
    } catch (_) {
      await _tryQuarantine();
      return null;
    }

    Map<String, dynamic> root;
    try {
      final Object? decoded = json.decode(contents);
      if (decoded is! Map<String, dynamic>) throw const FormatException();
      root = decoded;
    } catch (_) {
      await _tryQuarantine();
      return null;
    }

    final schemaVersion = root['schema_version'] as int?;
    final lastWrittenBy = root['last_written_by'] as Map<String, dynamic>?;
    final uxState = root['ux_state'] as Map<String, dynamic>?;

    if (schemaVersion == null || lastWrittenBy == null || uxState == null) {
      await _tryQuarantine();
      return null;
    }

    final persistedAppMajor = lastWrittenBy['app_major'] as int?;
    final persistedContractMajor =
        lastWrittenBy['contract_major'] as int?;

    if (persistedAppMajor == null || persistedContractMajor == null) {
      await _tryQuarantine();
      return null;
    }

    if (!compatibility.isCompatible(
      persistedAppMajor: persistedAppMajor,
      persistedContractMajor: persistedContractMajor,
    )) {
      // Per FR-070: drop persisted UX selection on major mismatch.
      // Caller (app shell) lands on onboarding/Dashboard with fresh defaults.
      return null;
    }

    try {
      _state = MigrationRegistry.applyMigrations(uxState, schemaVersion);
    } on StateError catch (_) {
      // Forward-only schema check or migration gap — quarantine + fresh.
      await _tryQuarantine();
      return null;
    }
    return _state;
  }

  /// Best-effort corruption quarantine. A failure to quarantine (e.g. a
  /// TOCTOU race where the file vanishes, or an IO/permission error on
  /// rename — plausible on Windows where the file may be held) must NOT
  /// escape as an unhandled launch crash. Callers degrade to fresh defaults
  /// (`return null`) regardless of whether the quarantine itself succeeded.
  Future<void> _tryQuarantine() async {
    try {
      await CorruptionQuarantine(paths: paths).quarantineCurrent();
    } catch (_) {
      // best-effort; fall through to fresh defaults
    }
  }

  /// In-memory state accessor.
  @override
  Map<String, dynamic>? get current => _state;

  /// Updates the in-memory state and schedules a debounced flush.
  @override
  void update(Map<String, dynamic> newState) {
    _state = newState;
    _hasUnflushed = true;
    _debounceTimer?.cancel();
    _debounceTimer = Timer(_debounceWindow, () => unawaited(_flush()));
  }

  /// FR-077 — clear per-project UI persistence when an operator removes
  /// a project. Drops the project's sort/filter entries from
  /// `list_sort_filter_per_project` and clears `last_active_project_id`
  /// if it pointed at the removed project. Daemon-side data is
  /// untouched (this method only writes the app's ux-state file).
  ///
  /// Safe to call when no state is loaded (no-op). Schedules a normal
  /// debounced flush.
  void clearProjectScopedState(String projectId) {
    final s = _state;
    if (s == null) return;
    final perProject = (s['list_sort_filter_per_project']
            as Map<String, dynamic>?) ??
        const <String, dynamic>{};
    final updatedPerProject = Map<String, dynamic>.from(perProject)
      ..remove(projectId);
    final updated = Map<String, dynamic>.from(s)
      ..['list_sort_filter_per_project'] = updatedPerProject;
    if (s['last_active_project_id'] == projectId) {
      updated['last_active_project_id'] = null;
    }
    update(updated);
  }

  /// Forces immediate flush. Used by FR-082 close handler.
  Future<void> flushBeforeExit() async {
    _debounceTimer?.cancel();
    if (!_hasUnflushed) return;
    await _flush().timeout(_closeFlushCap, onTimeout: () {
      // Best-effort; per FR-082 the app closes immediately regardless.
    });
  }

  Future<void> _flush() async {
    await _writeLock.synchronized(() async {
      // Snapshot state + dirty check atomically inside the lock so a flush
      // that queued behind the lock writes the latest `_state`, not a value
      // captured before it waited.
      final state = _state;
      if (!_hasUnflushed || state == null) return;
      final payload = <String, dynamic>{
        'schema_version': MigrationRegistry.currentSchemaVersion,
        'last_written_by': {
          'app_major': compatibility.currentAppMajor,
          'contract_major': compatibility.currentContractMajor,
        },
        'ux_state': state,
      };
      final encoded = const JsonEncoder.withIndent('  ').convert(payload);
      final tmp = paths.uxStateTmp;
      final dst = paths.uxStateFile;
      try {
        await tmp.writeAsString(encoded, flush: true);
        // Atomic replacement: rename() on POSIX is `rename(2)` which atomically
        // replaces the destination. The previous delete-then-rename sequence
        // (review fix S2) left a window in which a crash between the delete
        // and the rename would lose the previous file outright. On Windows,
        // File.rename falls back to MoveFileEx with MOVEFILE_REPLACE_EXISTING
        // semantics, so the atomicity property holds there too.
        await tmp.rename(dst.path);
        // Only mark clean if no newer update() replaced _state during the
        // in-flight async write; otherwise leave _hasUnflushed = true so the
        // newer state is not silently dropped.
        if (identical(_state, state)) _hasUnflushed = false;
      } catch (_) {
        // Leave _hasUnflushed = true so next change retries. Best-effort
        // cleanup of the staging file so a half-written .tmp doesn't
        // accumulate after a transient failure.
        try {
          if (tmp.existsSync()) await tmp.delete();
        } catch (_) {
          // ignore — recovery on next flush
        }
      }
    });
  }
}

/// Minimal async mutex.
class _AsyncLock {
  Completer<void>? _current;

  Future<T> synchronized<T>(Future<T> Function() body) async {
    while (_current != null) {
      await _current!.future;
    }
    final c = Completer<void>();
    _current = c;
    try {
      return await body();
    } finally {
      _current = null;
      c.complete();
    }
  }
}
