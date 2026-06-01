import 'sort_filter_state.dart';
import 'ux_state_repository.dart';

/// FR-078 — per-view sort/filter persistence. T179 (Phase 9 Polish).
///
/// Reads/writes the `list_sort_filter_global` and
/// `list_sort_filter_per_project` slices of the shared `ux-state.json`
/// (already reserved by the v1 schema — see `contracts/ux-state.md` §1, so
/// no schema bump or migration is required). Mirrors the copy-on-write
/// discipline of [SettingsRepository]: read the whole map, replace one key,
/// hand it back to [UxStateStore.update] which debounces + atomically
/// flushes.
///
/// **Scope rule (FR-078):** project-scoped views (Drift, Available
/// Validation, Runs) persist per-project — pass a non-null `projectId`.
/// Non-project views persist globally — pass `projectId: null`. The
/// `viewId` is the `<workspace>/<view>` slug documented in the contract
/// (e.g. `project_specs/drift`, `testing_demo/runs`, `agent_ops/queue`).
class SortFilterRepository {
  SortFilterRepository({required this.uxState});

  final UxStateStore uxState;

  static const String _globalKey = 'list_sort_filter_global';
  static const String _perProjectKey = 'list_sort_filter_per_project';

  /// Loads the persisted sort/filter for [viewId]. Returns
  /// [ListSortFilterState.empty] when nothing is persisted, when no state is
  /// loaded yet, or when the persisted entry is malformed (tolerant — never
  /// throws).
  ListSortFilterState load({required String viewId, String? projectId}) {
    final state = uxState.current;
    if (state == null) return ListSortFilterState.empty;
    try {
      Map<String, dynamic>? entry;
      if (projectId != null) {
        final perProject = state[_perProjectKey] as Map<String, dynamic>?;
        final forProject = perProject?[projectId] as Map<String, dynamic>?;
        entry = forProject?[viewId] as Map<String, dynamic>?;
      } else {
        final global = state[_globalKey] as Map<String, dynamic>?;
        entry = global?[viewId] as Map<String, dynamic>?;
      }
      if (entry == null) return ListSortFilterState.empty;
      return ListSortFilterState.fromJson(entry);
    } catch (_) {
      return ListSortFilterState.empty;
    }
  }

  /// Persists [value] for [viewId]. An [ListSortFilterState.isEmpty] value
  /// prunes the entry (and any now-empty project map) rather than storing a
  /// no-op, keeping `ux-state.json` from accumulating dead keys.
  void save({
    required String viewId,
    String? projectId,
    required ListSortFilterState value,
  }) {
    final current = Map<String, dynamic>.from(uxState.current ?? const {});
    if (projectId != null) {
      final perProject = Map<String, dynamic>.from(
          (current[_perProjectKey] as Map<String, dynamic>?) ?? const {});
      final forProject = Map<String, dynamic>.from(
          (perProject[projectId] as Map<String, dynamic>?) ?? const {});
      if (value.isEmpty) {
        forProject.remove(viewId);
      } else {
        forProject[viewId] = value.toJson();
      }
      if (forProject.isEmpty) {
        perProject.remove(projectId);
      } else {
        perProject[projectId] = forProject;
      }
      current[_perProjectKey] = perProject;
    } else {
      final global = Map<String, dynamic>.from(
          (current[_globalKey] as Map<String, dynamic>?) ?? const {});
      if (value.isEmpty) {
        global.remove(viewId);
      } else {
        global[viewId] = value.toJson();
      }
      current[_globalKey] = global;
    }
    uxState.update(current);
  }
}
