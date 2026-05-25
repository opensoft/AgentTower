import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/features/agent_ops/containers/containers_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';

/// Widget tests for [ContainersView] (FR-013). T164 — Phase 3 US1.
///
/// Variants:
///   (a) empty list  → "No containers discovered yet." copy
///   (b) populated   → ListTile per container with label / state /
///                     project_path / container_id
///   (c) load error  → "Could not load containers:" + Retry button
void main() {
  group('ContainersView', () {
    testWidgets('empty list renders the empty-state copy', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: const [])),
          ],
          child: const MaterialApp(home: Scaffold(body: ContainersView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(
        find.textContaining('No containers discovered yet.'),
        findsOneWidget,
      );
    });

    testWidgets('populated list renders one tile per container (FR-013)',
        (tester) async {
      final rows = [
        Fixtures.container(
          containerId: 'bench-1',
          name: 'bench-frontend',
          state: 'running',
          projectPath: '/work/agenttower',
        ),
        Fixtures.container(
          containerId: 'bench-2',
          name: 'bench-api',
          state: 'exited',
          projectPath: '/work/api',
        ),
      ];
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: rows)),
          ],
          child: const MaterialApp(home: Scaffold(body: ContainersView())),
        ),
      );
      await tester.pump();
      await tester.pump();

      // Label
      expect(find.text('bench-frontend'), findsOneWidget);
      expect(find.text('bench-api'), findsOneWidget);
      // State + project path concatenated in subtitle.
      expect(find.textContaining('/work/agenttower'), findsOneWidget);
      expect(find.textContaining('running'), findsOneWidget);
      expect(find.textContaining('exited'), findsOneWidget);
      // Container id appears in trailing column.
      expect(find.text('bench-1'), findsOneWidget);
      expect(find.text('bench-2'), findsOneWidget);
      // Two ListTiles total.
      expect(find.byType(ListTile), findsNWidgets(2));
    });

    testWidgets('load error renders error message + retry button',
        (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider
                .overrideWithValue(_FakeAppClient(throwOnList: true)),
          ],
          child: const MaterialApp(home: Scaffold(body: ContainersView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.textContaining('Could not load containers:'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Retry'), findsOneWidget);
    });
  });
}

class _FakeAppClient extends AppClient {
  _FakeAppClient({this.rows = const [], this.throwOnList = false})
      : super(
          session: DaemonSession(
            client: SocketClient('/nonexistent/never-bound.sock'),
          ),
        );

  final List<Map<String, dynamic>> rows;
  final bool throwOnList;

  @override
  Future<PagedResult> containerList({String? cursorNext, int? limit}) async {
    if (throwOnList) {
      throw StateError('containerList disabled in test');
    }
    return PagedResult(items: rows, cursorNext: null, total: rows.length);
  }
}
