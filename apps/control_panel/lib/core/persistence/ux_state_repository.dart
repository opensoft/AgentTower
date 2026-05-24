import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../../domain/models/common_enums.dart';
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
class UxStateRepository {
  UxStateRepository({
    required this.paths,
    required this.compatibility,
    Duration debounceWindow = const Duration(milliseconds: 250),
    Duration closeFlushCap = const Duration(milliseconds: 500),
  })  : _debounceWindow = debounceWindow,
        _closeFlushCap = closeFlushCap;

  static const int _currentAppMajor = 0; // bumped to 1 at first stable release
  // Tracks the app's compiled-in `app_contract_version` major (FEAT-011 1.x).
  // Matches `ContractCompatMap.appMinimum.major`.
  static const int _currentContractMajor = 1;

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
      await CorruptionQuarantine(paths: paths).quarantineCurrent();
      return null;
    }

    Map<String, dynamic> root;
    try {
      final Object? decoded = json.decode(contents);
      if (decoded is! Map<String, dynamic>) throw const FormatException();
      root = decoded;
    } catch (_) {
      await CorruptionQuarantine(paths: paths).quarantineCurrent();
      return null;
    }

    final schemaVersion = root['schema_version'] as int?;
    final lastWrittenBy = root['last_written_by'] as Map<String, dynamic>?;
    final uxState = root['ux_state'] as Map<String, dynamic>?;

    if (schemaVersion == null || lastWrittenBy == null || uxState == null) {
      await CorruptionQuarantine(paths: paths).quarantineCurrent();
      return null;
    }

    final persistedAppMajor = lastWrittenBy['app_major'] as int?;
    final persistedContractMajor =
        lastWrittenBy['contract_major'] as int?;

    if (persistedAppMajor == null || persistedContractMajor == null) {
      await CorruptionQuarantine(paths: paths).quarantineCurrent();
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
      await CorruptionQuarantine(paths: paths).quarantineCurrent();
      return null;
    }
    return _state;
  }

  /// In-memory state accessor.
  Map<String, dynamic>? get current => _state;

  /// Updates the in-memory state and schedules a debounced flush.
  void update(Map<String, dynamic> newState) {
    _state = newState;
    _hasUnflushed = true;
    _debounceTimer?.cancel();
    _debounceTimer = Timer(_debounceWindow, () => unawaited(_flush()));
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
    if (!_hasUnflushed) return;
    final state = _state;
    if (state == null) return;

    await _writeLock.synchronized(() async {
      final payload = <String, dynamic>{
        'schema_version': MigrationRegistry.currentSchemaVersion,
        'last_written_by': {
          'app_major': _currentAppMajor,
          'contract_major': _currentContractMajor,
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
        _hasUnflushed = false;
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
