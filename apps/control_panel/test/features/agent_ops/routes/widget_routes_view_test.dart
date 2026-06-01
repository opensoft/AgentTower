import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/features/agent_ops/routes/routes_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';
import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';

/// Widget tests for [RoutesView] (FR-021 + FR-059). T164 — Phase 3 US1.
///
/// Each row renders source→target, a toggle (enable/disable), a remove
/// affordance, and (when present) the `recentSkipExplanation` /
/// `recentMatchSummary` strings — the FR-059 explainability surface.
void main() {
  group('RoutesView', () {
    testWidgets('empty list renders empty-state copy', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: const [])),
          ],
          child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: RoutesView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.textContaining('No routes defined.'), findsOneWidget);
      // The Add-route FAB is always present.
      expect(
        find.widgetWithText(FloatingActionButton, 'Add route'),
        findsOneWidget,
      );
    });

    testWidgets('populated row renders toggle + remove + source→target',
        (tester) async {
      final rows = [
        Fixtures.route(
          routeId: 'r1',
          sourceScope: 'agent:claude-master-1',
          template: 'forward_event_to',
          target: 'agent:codex-slave-1',
          enabled: true,
        ),
      ];
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: rows)),
          ],
          child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: RoutesView())),
        ),
      );
      await tester.pump();
      await tester.pump();

      // Source → target appears in the row's monospaced title.
      expect(
        find.textContaining('agent:claude-master-1'),
        findsOneWidget,
      );
      expect(
        find.textContaining('agent:codex-slave-1'),
        findsOneWidget,
      );
      // Toggle is enabled (matches fixture).
      expect(find.byType(Switch), findsOneWidget);
      final sw = tester.widget<Switch>(find.byType(Switch));
      expect(sw.value, isTrue);
      // Remove icon present.
      expect(find.byTooltip('Remove'), findsOneWidget);
    });

    testWidgets('recentSkipExplanation renders below the row when present',
        (tester) async {
      final rows = [
        Fixtures.route(
          routeId: 'r1',
          recentSkipExplanation: 'source agent paused',
        ),
      ];
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: rows)),
          ],
          child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: RoutesView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(
        find.textContaining('recent skip: source agent paused'),
        findsOneWidget,
      );
    });
  });
}

class _FakeAppClient extends AppClient {
  _FakeAppClient({this.rows = const []})
      : super(
          session: DaemonSession(
            client: SocketClient('/nonexistent/never-bound.sock'),
          ),
        );

  final List<Map<String, dynamic>> rows;

  @override
  Future<PagedResult> routeList({String? cursorNext, int? limit}) async {
    return PagedResult(items: rows, cursorNext: null, total: rows.length);
  }
}
