import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/features/agent_ops/panes/panes_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';

/// Widget tests for [PanesView] (FR-014). T164 — Phase 3 US1.
///
/// Renders one row per FEAT-011 PaneState plus an empty-state and
/// verifies the per-state next-action affordance vocabulary:
///   - discovered-and-unmanaged   → "Adopt" only
///   - discovered-and-registered  → "Open agent"
///   - inactive/stale             → "Re-probe"
///   - discovery-degraded         → "Re-probe"
void main() {
  group('PanesView', () {
    testWidgets('empty list renders empty-state copy', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: const [])),
          ],
          child: const MaterialApp(home: Scaffold(body: PanesView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(
        find.textContaining('No tmux panes discovered yet.'),
        findsOneWidget,
      );
    });

    testWidgets('per-state action vocabulary matches FR-014', (tester) async {
      final rows = [
        Fixtures.pane(
          paneId: 'p1',
          tmuxSession: 'main',
          tmuxWindow: 0,
          tmuxPane: 0,
          state: PaneState.discoveredAndUnmanaged,
        ),
        Fixtures.pane(
          paneId: 'p2',
          tmuxSession: 'main',
          tmuxWindow: 0,
          tmuxPane: 1,
          state: PaneState.discoveredAndRegistered,
          registeredAgentId: 'agent-7',
        ),
        Fixtures.pane(
          paneId: 'p3',
          tmuxSession: 'main',
          tmuxWindow: 0,
          tmuxPane: 2,
          state: PaneState.inactiveOrStale,
        ),
        Fixtures.pane(
          paneId: 'p4',
          tmuxSession: 'main',
          tmuxWindow: 0,
          tmuxPane: 3,
          state: PaneState.discoveryDegraded,
        ),
      ];
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: rows)),
          ],
          child: const MaterialApp(home: Scaffold(body: PanesView())),
        ),
      );
      await tester.pump();
      await tester.pump();

      // Four rows render with their pane address as the title.
      expect(find.text('main:0.0'), findsOneWidget);
      expect(find.text('main:0.1'), findsOneWidget);
      expect(find.text('main:0.2'), findsOneWidget);
      expect(find.text('main:0.3'), findsOneWidget);

      // Adopt button visible only on discovered-and-unmanaged.
      expect(find.widgetWithText(TextButton, 'Adopt'), findsOneWidget);
      // Open-agent only on registered.
      expect(find.widgetWithText(TextButton, 'Open agent'), findsOneWidget);
      // Re-probe on stale + degraded → exactly two.
      expect(find.widgetWithText(TextButton, 'Re-probe'), findsNWidgets(2));
    });

    testWidgets('Adopt button is suppressed for non-unmanaged states',
        (tester) async {
      final rows = [
        Fixtures.pane(
          paneId: 'p2',
          state: PaneState.discoveredAndRegistered,
          registeredAgentId: 'agent-7',
        ),
        Fixtures.pane(paneId: 'p3', state: PaneState.inactiveOrStale),
      ];
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: rows)),
          ],
          child: const MaterialApp(home: Scaffold(body: PanesView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.widgetWithText(TextButton, 'Adopt'), findsNothing);
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
  Future<PagedResult> paneList({String? cursorNext, int? limit}) async {
    return PagedResult(items: rows, cursorNext: null, total: rows.length);
  }
}
