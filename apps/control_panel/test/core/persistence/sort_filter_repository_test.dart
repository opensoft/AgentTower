import 'package:agenttower_control_panel/core/persistence/sort_filter_repository.dart';
import 'package:agenttower_control_panel/core/persistence/sort_filter_state.dart';
import 'package:agenttower_control_panel/core/persistence/ux_state_repository.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:flutter_test/flutter_test.dart';

/// In-memory [UxStateStore] double — exercises [SortFilterRepository] without
/// a real on-disk `ux-state.json` (no timers, no temp files).
class _FakeStore implements UxStateStore {
  Map<String, dynamic>? _state = <String, dynamic>{};
  @override
  Map<String, dynamic>? get current => _state;
  @override
  void update(Map<String, dynamic> newState) => _state = newState;
}

void main() {
  group('ListSortFilterState', () {
    test('round-trips through JSON', () {
      const s = ListSortFilterState(
        sortField: 'severity',
        sortDirection: SortDirection.asc,
        filters: {'status': 'new'},
      );
      final parsed = ListSortFilterState.fromJson(s.toJson());
      expect(parsed, equals(s));
    });

    test('toJson omits sort_field when null', () {
      const s = ListSortFilterState(filters: {'state': 'completed'});
      expect(s.toJson().containsKey('sort_field'), isFalse);
      expect(s.toJson()['sort_direction'], 'desc');
    });

    test('fromJson tolerates an unknown sort_direction (defaults to desc)', () {
      final parsed = ListSortFilterState.fromJson({
        'sort_field': 'x',
        'sort_direction': 'sideways',
        'filters': <String, dynamic>{},
      });
      expect(parsed.sortDirection, SortDirection.desc);
      expect(parsed.sortField, 'x');
    });

    test('fromJson tolerates a missing/malformed filters block', () {
      final parsed = ListSortFilterState.fromJson({'sort_field': 'x'});
      expect(parsed.filters, isEmpty);
    });

    test('isEmpty is true only for the default state', () {
      expect(ListSortFilterState.empty.isEmpty, isTrue);
      expect(const ListSortFilterState(filters: {'a': 1}).isEmpty, isFalse);
      expect(const ListSortFilterState(sortField: 'a').isEmpty, isFalse);
    });
  });

  group('SortFilterRepository scope routing (FR-078)', () {
    late _FakeStore store;
    late SortFilterRepository repo;

    setUp(() {
      store = _FakeStore();
      repo = SortFilterRepository(uxState: store);
    });

    test('global save/load round-trips and never touches per-project map', () {
      const value = ListSortFilterState(
        sortField: 'created_at',
        filters: {'state': 'blocked'},
      );
      repo.save(viewId: 'agent_ops/queue', value: value);

      expect(repo.load(viewId: 'agent_ops/queue'), equals(value));
      expect(store.current!['list_sort_filter_global'],
          isA<Map<String, dynamic>>());
      expect(
          store.current!.containsKey('list_sort_filter_per_project'), isFalse);
    });

    test('per-project save/load is isolated by project and from global', () {
      const value = ListSortFilterState(
        sortField: 'severity',
        filters: {'status': 'new'},
      );
      repo.save(
        viewId: 'project_specs/drift',
        projectId: 'proj_A',
        value: value,
      );

      // Same view, this project → restored.
      expect(
        repo.load(viewId: 'project_specs/drift', projectId: 'proj_A'),
        equals(value),
      );
      // Same view, different project → empty (per-project isolation).
      expect(
        repo.load(viewId: 'project_specs/drift', projectId: 'proj_B'),
        equals(ListSortFilterState.empty),
      );
      // Same view, global scope → empty (scope isolation).
      expect(
        repo.load(viewId: 'project_specs/drift'),
        equals(ListSortFilterState.empty),
      );
    });

    test('saving an empty state prunes the entry and any now-empty project',
        () {
      const value = ListSortFilterState(filters: {'state': 'completed'});
      repo.save(viewId: 'testing_demo/runs', projectId: 'proj_A', value: value);
      expect(
        (store.current!['list_sort_filter_per_project'] as Map)['proj_A'],
        isNotNull,
      );

      repo.save(
        viewId: 'testing_demo/runs',
        projectId: 'proj_A',
        value: ListSortFilterState.empty,
      );
      // proj_A's only view was pruned → the project key itself is removed.
      final perProject = store.current!['list_sort_filter_per_project'] as Map;
      expect(perProject.containsKey('proj_A'), isFalse);
      expect(
        repo.load(viewId: 'testing_demo/runs', projectId: 'proj_A'),
        equals(ListSortFilterState.empty),
      );
    });

    test('load returns empty when no UX state is loaded yet', () {
      store._state = null;
      expect(
        repo.load(viewId: 'agent_ops/queue'),
        equals(ListSortFilterState.empty),
      );
    });

    test('multiple views in one project coexist independently', () {
      repo.save(
        viewId: 'project_specs/drift',
        projectId: 'proj_A',
        value: const ListSortFilterState(filters: {'status': 'confirmed'}),
      );
      repo.save(
        viewId: 'testing_demo/runs',
        projectId: 'proj_A',
        value: const ListSortFilterState(filters: {'state': 'failed_to_start'}),
      );
      expect(
        repo
            .load(viewId: 'project_specs/drift', projectId: 'proj_A')
            .filters['status'],
        'confirmed',
      );
      expect(
        repo
            .load(viewId: 'testing_demo/runs', projectId: 'proj_A')
            .filters['state'],
        'failed_to_start',
      );
    });
  });
}
