import 'dart:convert';
import 'dart:io';

import 'package:agenttower_control_panel/core/persistence/compatibility.dart';
import 'package:agenttower_control_panel/core/persistence/corruption.dart';
import 'package:agenttower_control_panel/core/persistence/migrations.dart';
import 'package:agenttower_control_panel/core/persistence/paths.dart';
import 'package:agenttower_control_panel/core/persistence/ux_state_repository.dart';
import 'package:flutter_test/flutter_test.dart';
// ignore: depend_on_referenced_packages
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';
// ignore: depend_on_referenced_packages
import 'package:plugin_platform_interface/plugin_platform_interface.dart';

/// Per-OS-test path_provider stub that always reports a fixed temp dir.
/// Used so [AppPaths.initialize] does not need a host Flutter binding.
class _StubPathProvider extends PathProviderPlatform
    with MockPlatformInterfaceMixin {
  _StubPathProvider(this.support);
  final String support;

  @override
  Future<String?> getApplicationSupportPath() async => support;
}

/// Test helpers
Map<String, dynamic> _defaultUxState() => <String, dynamic>{
      'theme_mode': 'system',
      'density_mode': 'comfortable',
      'last_active_workspace': 'agent_ops',
      'last_active_sub_view_per_workspace': {'agent_ops': 'dashboard'},
      'list_sort_filter_global': <String, dynamic>{},
      'list_sort_filter_per_project': <String, dynamic>{},
    };

Map<String, dynamic> _envelope({
  required int schemaVersion,
  required int appMajor,
  required int contractMajor,
  Map<String, dynamic>? uxState,
}) =>
    <String, dynamic>{
      'schema_version': schemaVersion,
      'last_written_by': {
        'app_major': appMajor,
        'contract_major': contractMajor,
      },
      'ux_state': uxState ?? _defaultUxState(),
    };

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory tmp;
  late AppPaths paths;

  setUp(() async {
    tmp = Directory.systemTemp.createTempSync('ux_state_test_');
    PathProviderPlatform.instance = _StubPathProvider(tmp.path);
    AppPaths.resetForTesting();
    paths = await AppPaths.initialize();
  });

  tearDown(() {
    AppPaths.resetForTesting();
    if (tmp.existsSync()) {
      tmp.deleteSync(recursive: true);
    }
  });

  group('UxStateRepository.load — fresh install', () {
    test('returns null when ux-state.json does not exist', () async {
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      // Sanity: file should not exist.
      expect(paths.uxStateFile.existsSync(), isFalse);

      final state = await repo.load();
      expect(
        state,
        isNull,
        reason: 'fresh install — load() must yield null defaults sentinel',
      );
    });
  });

  group('UxStateRepository.load — compatible-launch happy path', () {
    test('returns the parsed ux_state payload when versions match', () async {
      await paths.uxStateFile.writeAsString(jsonEncode(_envelope(
        schemaVersion: MigrationRegistry.currentSchemaVersion,
        appMajor: 0,
        contractMajor: 1,
      )));
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      final state = await repo.load();
      expect(state, isNotNull);
      expect(state!['theme_mode'], 'system');
      expect(state['last_active_workspace'], 'agent_ops');
    });
  });

  group('UxStateRepository.load — major-mismatch drop-and-reset', () {
    test('drops persisted state when app_major differs (FR-070)', () async {
      await paths.uxStateFile.writeAsString(jsonEncode(_envelope(
        schemaVersion: MigrationRegistry.currentSchemaVersion,
        appMajor: 99, // mismatch
        contractMajor: 1,
      )));
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      final state = await repo.load();
      expect(
        state,
        isNull,
        reason:
            'FR-070 — persisted state dropped on app major mismatch (operator lands on onboarding)',
      );
    });

    test('drops persisted state when contract_major differs (FR-070)',
        () async {
      await paths.uxStateFile.writeAsString(jsonEncode(_envelope(
        schemaVersion: MigrationRegistry.currentSchemaVersion,
        appMajor: 0,
        contractMajor: 42, // mismatch
      )));
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      final state = await repo.load();
      expect(state, isNull);
    });
  });

  group('UxStateRepository — schema migration', () {
    // MVP ships schema_version = 1 with NO migrations registered (per
    // migrations.dart line 32). This test enumerates "one test per shipped
    // migration"; if the registry is empty we assert that explicitly so
    // future additions force a new test entry here.
    test('MVP has zero registered migrations — currentSchemaVersion is 1', () {
      expect(MigrationRegistry.currentSchemaVersion, 1);
      expect(
        MigrationRegistry.migrations,
        isEmpty,
        reason:
            'When a migration is added, add a corresponding test in this group.',
      );
    });

    test('applyMigrations is identity at the current schema version', () {
      final input = _defaultUxState();
      final out = MigrationRegistry.applyMigrations(
        input,
        MigrationRegistry.currentSchemaVersion,
      );
      expect(out, equals(input));
    });

    test('applyMigrations throws StateError when source is newer than current',
        () {
      expect(
        () => MigrationRegistry.applyMigrations(
          _defaultUxState(),
          MigrationRegistry.currentSchemaVersion + 1,
        ),
        throwsA(isA<StateError>()),
      );
    });
  });

  group('UxStateRepository — atomic write + crash-mid-write recovery', () {
    test('flush replaces the file atomically and removes the .tmp staging',
        () async {
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
        debounceWindow: const Duration(milliseconds: 1),
      );
      repo.update(_defaultUxState());
      await repo.flushBeforeExit();

      expect(paths.uxStateFile.existsSync(), isTrue);
      expect(
        paths.uxStateTmp.existsSync(),
        isFalse,
        reason: 'atomic-write staging file must be renamed away after flush',
      );

      final root = jsonDecode(await paths.uxStateFile.readAsString())
          as Map<String, dynamic>;
      expect(root['schema_version'], MigrationRegistry.currentSchemaVersion);
      expect(
        (root['last_written_by'] as Map)['contract_major'],
        1,
        reason: 'flush must stamp the current contract_major',
      );
      expect((root['ux_state'] as Map)['theme_mode'], 'system');
    });

    test(
        'crash mid-write (stale .tmp on disk) does NOT corrupt the prior good file',
        () async {
      // Seed a good prior file.
      await paths.uxStateFile.writeAsString(jsonEncode(_envelope(
        schemaVersion: MigrationRegistry.currentSchemaVersion,
        appMajor: 0,
        contractMajor: 1,
      )));
      // Simulate a crash partway through a write by leaving a stale .tmp
      // behind that contains garbage.
      await paths.uxStateTmp.writeAsString('{partial');
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      // load() must still succeed — the .tmp is irrelevant; only the
      // canonical file is read.
      final state = await repo.load();
      expect(
        state,
        isNotNull,
        reason: 'stale .tmp must not poison reads of the canonical file',
      );
      expect(state!['theme_mode'], 'system');
    });

    test('flushBeforeExit is a no-op when nothing has been updated', () async {
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      // No update() call before flushBeforeExit — should not throw or create
      // a file.
      await repo.flushBeforeExit();
      expect(paths.uxStateFile.existsSync(), isFalse);
    });
  });

  group('UxStateRepository — corruption quarantine', () {
    test('invalid JSON quarantines the file and returns null', () async {
      await paths.uxStateFile.writeAsString('not json at all');
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      final state = await repo.load();
      expect(state, isNull);

      expect(
        CorruptionQuarantine(paths: paths).hasQuarantineFile(),
        isTrue,
        reason: 'invalid JSON must be quarantined (not deleted)',
      );
      expect(paths.uxStateFile.existsSync(), isFalse,
          reason: 'quarantine moves the original file aside');
    });

    test('JSON array (not object) at top-level is quarantined', () async {
      await paths.uxStateFile.writeAsString('[1, 2, 3]');
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      final state = await repo.load();
      expect(state, isNull);
      expect(
        CorruptionQuarantine(paths: paths).hasQuarantineFile(),
        isTrue,
      );
    });

    test('missing schema_version key is quarantined', () async {
      await paths.uxStateFile.writeAsString(jsonEncode({
        'last_written_by': {'app_major': 0, 'contract_major': 1},
        'ux_state': _defaultUxState(),
        // schema_version missing
      }));
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      final state = await repo.load();
      expect(state, isNull);
      expect(
        CorruptionQuarantine(paths: paths).hasQuarantineFile(),
        isTrue,
      );
    });

    test('missing last_written_by key is quarantined', () async {
      await paths.uxStateFile.writeAsString(jsonEncode({
        'schema_version': 1,
        'ux_state': _defaultUxState(),
      }));
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      final state = await repo.load();
      expect(state, isNull);
      expect(
        CorruptionQuarantine(paths: paths).hasQuarantineFile(),
        isTrue,
      );
    });

    test('missing ux_state key is quarantined', () async {
      await paths.uxStateFile.writeAsString(jsonEncode({
        'schema_version': 1,
        'last_written_by': {'app_major': 0, 'contract_major': 1},
      }));
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      final state = await repo.load();
      expect(state, isNull);
      expect(
        CorruptionQuarantine(paths: paths).hasQuarantineFile(),
        isTrue,
      );
    });

    test('newer-than-current schema_version is quarantined (FR-070 path)',
        () async {
      await paths.uxStateFile.writeAsString(jsonEncode(_envelope(
        schemaVersion: MigrationRegistry.currentSchemaVersion + 1,
        appMajor: 0,
        contractMajor: 1,
      )));
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      final state = await repo.load();
      expect(state, isNull);
      expect(
        CorruptionQuarantine(paths: paths).hasQuarantineFile(),
        isTrue,
        reason: 'forward-only schema check must quarantine and reset',
      );
    });

    test('CorruptionQuarantine.quarantineCurrent throws when no file exists',
        () async {
      expect(
        () => CorruptionQuarantine(paths: paths).quarantineCurrent(),
        throwsA(isA<StateError>()),
      );
    });
  });

  group('UxStateRepository.clearProjectScopedState', () {
    test(
        'drops per-project entry and nulls last_active_project_id when matching',
        () async {
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
        debounceWindow: const Duration(milliseconds: 1),
      );
      repo.update(<String, dynamic>{
        ..._defaultUxState(),
        'last_active_project_id': 'proj-keep-1',
        'list_sort_filter_per_project': <String, dynamic>{
          'proj-keep-1': <String, dynamic>{
            'project_specs/drift': <String, dynamic>{},
          },
          'proj-drop-1': <String, dynamic>{
            'project_specs/drift': <String, dynamic>{},
          },
        },
      });

      repo.clearProjectScopedState('proj-drop-1');
      final mid = repo.current!;
      expect(mid['last_active_project_id'], 'proj-keep-1');
      expect(
        (mid['list_sort_filter_per_project'] as Map).containsKey('proj-drop-1'),
        isFalse,
      );
      expect(
        (mid['list_sort_filter_per_project'] as Map).containsKey('proj-keep-1'),
        isTrue,
      );

      repo.clearProjectScopedState('proj-keep-1');
      final after = repo.current!;
      expect(after['last_active_project_id'], isNull,
          reason: 'last_active_project_id must clear when removed project '
              'matches');
      expect(
        (after['list_sort_filter_per_project'] as Map)
            .containsKey('proj-keep-1'),
        isFalse,
      );
    });

    test('is a no-op when no state is loaded', () {
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      // No update() called → repo.current is null. clear must not throw.
      expect(() => repo.clearProjectScopedState('proj-x'), returnsNormally);
      expect(repo.current, isNull);
    });
  });

  group('Per-view filter validation (rejecting unknown enum values)', () {
    // The persistence layer treats `filters` as opaque Map<String, dynamic>
    // per ux-state.md §1 ListSortFilterState — view-side validators decide
    // what to accept and reject unknown enum values by silently resetting
    // that view's filter to default (per ux-state.md §1 last paragraph).
    //
    // This test demonstrates round-trip-then-validate against a shared
    // allow-set; an unknown value must be rejected by the consumer.

    bool isValidFilterValues(
      List<dynamic>? values,
      Set<String> allowed,
    ) {
      if (values == null) return true;
      for (final v in values) {
        if (v is! String) return false;
        if (!allowed.contains(v)) return false;
      }
      return true;
    }

    test('valid enum values pass per-view validation', () async {
      const allowedDriftStatus = {
        'new',
        'review_needed',
        'confirmed',
        'repair_planned',
        'resolved',
        'accepted_as_built',
        'dismissed',
      };
      final filters = <String, dynamic>{
        'status': ['new', 'review_needed']
      };
      expect(
        isValidFilterValues(
          filters['status'] as List<dynamic>?,
          allowedDriftStatus,
        ),
        isTrue,
      );
    });

    test('unknown enum value is rejected (view-side default reset)', () async {
      const allowedDriftStatus = {
        'new',
        'review_needed',
        'confirmed',
        'repair_planned',
        'resolved',
        'accepted_as_built',
        'dismissed',
      };
      final filters = <String, dynamic>{
        'status': ['new', 'totally_unknown_enum_value']
      };
      expect(
        isValidFilterValues(
          filters['status'] as List<dynamic>?,
          allowedDriftStatus,
        ),
        isFalse,
        reason:
            'view-side validator must reject unknown enum values and reset to default',
      );
    });

    test('non-string filter entries are rejected', () async {
      const allowed = {'a', 'b'};
      expect(
        isValidFilterValues(<dynamic>[1, 2], allowed),
        isFalse,
      );
    });

    test(
        'persisting then loading a filter with an unknown enum value preserves '
        'the bytes (validation is view-side, not persistence-side)', () async {
      // Confirms the contract from ux-state.md §1: the persistence layer
      // does NOT touch filter shape — it is the view's responsibility to
      // validate on deserialize.
      final repo = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
        debounceWindow: const Duration(milliseconds: 1),
      );
      repo.update(<String, dynamic>{
        ..._defaultUxState(),
        'list_sort_filter_global': {
          'project_specs/drift': {
            'sort_field': 'severity',
            'sort_direction': 'desc',
            'filters': {
              'status': ['confirmed', 'never_a_real_enum'],
            },
          },
        },
      });
      await repo.flushBeforeExit();

      final repo2 = UxStateRepository(
        paths: paths,
        compatibility: const LaunchCompatibility(
          currentAppMajor: 0,
          currentContractMajor: 1,
        ),
      );
      final loaded = await repo2.load();
      expect(loaded, isNotNull);
      final filters = ((loaded!['list_sort_filter_global']
          as Map)['project_specs/drift'] as Map)['filters'] as Map;
      expect(filters['status'], ['confirmed', 'never_a_real_enum'],
          reason:
              'persistence is opaque to filter values; view performs enum check');
    });
  });
}
