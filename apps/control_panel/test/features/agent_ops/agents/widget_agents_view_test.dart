import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/features/agent_ops/agents/agents_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';
import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';

/// Widget tests for [AgentsView] (FR-015). T164 — Phase 3 US1.
///
/// FR-015 + data-model §1.2: at most 2 visible levels of descendants.
/// Deeper trees collapse behind `descendantsBeyondVisible` ("+N
/// descendants") which the row renders verbatim.
void main() {
  group('AgentsView', () {
    testWidgets('empty list renders empty-state copy', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: const [])),
          ],
          child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: AgentsView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.textContaining('No adopted agents yet.'), findsOneWidget);
    });

    testWidgets('renders depth-1 + depth-2 with no overflow chip',
        (tester) async {
      final rows = [
        Fixtures.agent(agentId: 'a1', label: 'master-1'),
        Fixtures.agent(
          agentId: 'a2',
          label: 'slave-1',
          parentAgentId: 'a1',
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
          home: Scaffold(body: AgentsView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.text('master-1'), findsOneWidget);
      expect(find.text('slave-1'), findsOneWidget);
      // No "+N descendants" overflow row when descendants == null/0.
      expect(find.textContaining('descendants'), findsNothing);
    });

    testWidgets('descendantsBeyondVisible renders "+N descendants" affordance',
        (tester) async {
      final rows = [
        Fixtures.agent(
          agentId: 'a1',
          label: 'master-1',
          descendants: 3,
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
          home: Scaffold(body: AgentsView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.text('+3 descendants'), findsOneWidget);
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
  Future<PagedResult> agentList({
    String? cursorNext,
    int? limit,
    String? role,
    String? capability,
    String? containerId,
    bool? logAttached,
  }) async {
    return PagedResult(items: rows, cursorNext: null, total: rows.length);
  }
}
