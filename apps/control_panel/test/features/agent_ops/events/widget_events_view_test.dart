import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/features/agent_ops/events/events_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';
import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';

/// Widget tests for [EventsView] (FR-019). T164 — Phase 3 US1.
///
/// FR-019 / Round-3 R-32: events stream in observed-at descending
/// order. The view exposes a "Jump to most recent" affordance — a
/// FloatingActionButton.small with `Icons.vertical_align_top` and a
/// matching tooltip.
///
/// T176: the Event freezed model now accepts the FEAT-011 wire shape
/// directly (`event_class` / `emitted_at` / `summary`) via
/// `@JsonKey(name: ...)`, so the test consumes `Fixtures.event()`
/// without needing to splice JSON inline.
void main() {
  Map<String, dynamic> eventJson({
    required String eventId,
    String eventClass = 'route_skipped',
    String agentId = 'agent-1',
    String summary = 'sample event excerpt',
    DateTime? observedAt,
  }) {
    return Fixtures.event(
      eventId: eventId,
      eventClass: eventClass,
      agentId: agentId,
      summary: summary,
      emittedAt: (observedAt ?? DateTime.now().toUtc()).toIso8601String(),
    );
  }

  group('EventsView', () {
    testWidgets('empty list renders empty-state copy', (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: const [])),
          ],
          child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: EventsView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.textContaining('No events yet.'), findsOneWidget);
      // FAB should not render when there are no rows.
      expect(find.byType(FloatingActionButton), findsNothing);
    });

    testWidgets('populated list renders Jump-to-most-recent affordance',
        (tester) async {
      final rows = [
        eventJson(eventId: 'e1'),
        eventJson(eventId: 'e2'),
        eventJson(eventId: 'e3'),
      ];
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: rows)),
          ],
          child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: EventsView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      // Three rows.
      expect(find.byType(ListTile), findsNWidgets(3));
      // Jump-to-most-recent affordance present.
      expect(find.byIcon(Icons.vertical_align_top), findsOneWidget);
      expect(find.byTooltip('Jump to most recent'), findsOneWidget);
    });

    testWidgets('tapping Jump-to-most-recent does not throw', (tester) async {
      final rows = [eventJson(eventId: 'e1')];
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient(rows: rows)),
          ],
          child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: EventsView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      await tester.tap(find.byTooltip('Jump to most recent'));
      await tester.pump();
      await tester.pump();
      // No exception — provider re-invalidated and refetched.
      expect(tester.takeException(), isNull);
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
  Future<PagedResult> eventList({
    String? cursorNext,
    int? limit,
    String? agentId,
  }) async {
    return PagedResult(items: rows, cursorNext: null, total: rows.length);
  }
}
