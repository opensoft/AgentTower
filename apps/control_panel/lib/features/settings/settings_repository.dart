import '../../core/config/settings_model.dart';
import '../../core/persistence/ux_state_repository.dart';

/// Settings repository. T025 (Phase 2 Foundational).
///
/// Reads/writes [Settings] via the shared [UxStateRepository]. Settings
/// live inside the single `ux-state.json` under the `settings:` key per
/// data-model.md §2.1.
class SettingsRepository {
  SettingsRepository({required this.uxState, required this.defaultSocketPath});

  final UxStateRepository uxState;
  final String defaultSocketPath;

  /// Loads settings from persisted UX state, returning defaults on first launch.
  Settings load() {
    final state = uxState.current;
    if (state == null) {
      return Settings.defaults(defaultSocketPath: defaultSocketPath);
    }
    final settingsJson = state['settings'] as Map<String, dynamic>?;
    if (settingsJson == null) {
      return Settings.defaults(defaultSocketPath: defaultSocketPath);
    }
    try {
      return Settings.fromJson(settingsJson);
    } catch (_) {
      // Schema drift between persisted Settings and current code; fall back
      // to defaults. The persisted state may be migrated later by R-21.
      return Settings.defaults(defaultSocketPath: defaultSocketPath);
    }
  }

  /// Persists [settings] back to the UX state via the shared repository
  /// (debounced + atomic per R-05).
  void save(Settings settings) {
    final current = Map<String, dynamic>.from(uxState.current ?? const {});
    current['settings'] = settings.toJson();
    uxState.update(current);
  }
}
