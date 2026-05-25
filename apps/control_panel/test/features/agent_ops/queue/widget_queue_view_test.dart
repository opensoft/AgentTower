import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/features/agent_ops/queue/queue_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';

/// Widget tests for [QueueView] (FR-020). T164 — Phase 3 US1.
///
/// FEAT-011 `app.queue.*` state-transition rules (Round-5):
///   - approve: blocked → queued                    (blocked only)
///   - delay:   queued  → blocked (operator_delayed) (queued only)
///   - cancel:  queued | blocked → canceled         (both non-terminal)
///   - delivered / canceled / failed: terminal, no actions
///
/// Post-H8 fix: the Delay button must appear on `queued` rows only —
/// the earlier UI offered Delay on `blocked` rows, which inverted the
/// lifecycle.
void main() {
  group('QueueView', () {
    testWidgets('empty queue renders empty-state copy', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: const [])),
          ],
          child: const MaterialApp(home: Scaffold(body: QueueView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.textContaining('Queue is empty.'), findsOneWidget);
    });

    testWidgets('blocked row exposes Approve + Cancel (no Delay)',
        (tester) async {
      final rows = [
        Fixtures.queueRow(messageId: 'q-blk', state: 'blocked'),
      ];
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: rows)),
          ],
          child: const MaterialApp(home: Scaffold(body: QueueView())),
        ),
      );
      await tester.pump();
      await tester.pump();

      expect(find.byTooltip('Approve'), findsOneWidget);
      expect(find.byTooltip('Cancel'), findsOneWidget);
      // Delay must NOT show on blocked rows (post-H8 fix).
      expect(find.byTooltip('Delay 60s'), findsNothing);
    });

    testWidgets('queued row exposes Delay + Cancel (no Approve)',
        (tester) async {
      final rows = [
        Fixtures.queueRow(messageId: 'q-qd', state: 'queued'),
      ];
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: rows)),
          ],
          child: const MaterialApp(home: Scaffold(body: QueueView())),
        ),
      );
      await tester.pump();
      await tester.pump();

      expect(find.byTooltip('Delay 60s'), findsOneWidget);
      expect(find.byTooltip('Cancel'), findsOneWidget);
      expect(find.byTooltip('Approve'), findsNothing);
    });

    testWidgets('terminal rows expose no actions', (tester) async {
      final rows = [
        Fixtures.queueRow(messageId: 'q-d', state: 'delivered'),
        Fixtures.queueRow(messageId: 'q-c', state: 'canceled'),
        Fixtures.queueRow(messageId: 'q-f', state: 'failed'),
      ];
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: rows)),
          ],
          child: const MaterialApp(home: Scaffold(body: QueueView())),
        ),
      );
      await tester.pump();
      await tester.pump();

      // No per-row action tooltips on terminal rows.
      expect(find.byTooltip('Approve'), findsNothing);
      expect(find.byTooltip('Delay 60s'), findsNothing);
      expect(find.byTooltip('Cancel'), findsNothing);
      // But the rows themselves still render.
      expect(find.byType(ListTile), findsNWidgets(3));
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
  Future<PagedResult> queueList({String? cursorNext, int? limit}) async {
    return PagedResult(items: rows, cursorNext: null, total: rows.length);
  }
}
