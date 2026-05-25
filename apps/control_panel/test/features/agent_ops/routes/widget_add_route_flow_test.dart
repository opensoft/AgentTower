import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/features/agent_ops/routes/add_route_flow.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';

/// Widget tests for [AddRouteFlow] (FR-021). T164 — Phase 3 US1.
///
/// FEAT-011 `app.route.add` accepts exactly three string fields:
/// `source_scope`, `template`, `target`. The form pre-populates them
/// with sensible defaults so the operator can submit immediately.
void main() {
  Future<void> openDialog(WidgetTester tester, _FakeAppClient fake) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appClientProvider.overrideWithValue(fake),
        ],
        child: MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (ctx) => ElevatedButton(
                onPressed: () => AddRouteFlow.show(ctx),
                child: const Text('open'),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
  }

  group('AddRouteFlow', () {
    testWidgets('submit with default values calls routeAdd and dismisses',
        (tester) async {
      final fake = _FakeAppClient();
      await openDialog(tester, fake);

      await tester.tap(find.widgetWithText(FilledButton, 'Add'));
      await tester.pumpAndSettle();

      expect(fake.calls, 1);
      expect(fake.lastSourceScope, 'agent:claude-master-1');
      expect(fake.lastTemplate, 'forward_event_to');
      expect(fake.lastTarget, 'agent:codex-slave-1');
      // Dialog popped → opener button visible again.
      expect(find.text('open'), findsOneWidget);
      // Success snackbar.
      expect(find.text('Route added'), findsOneWidget);
    });

    testWidgets('blank source_scope is rejected with validator message',
        (tester) async {
      final fake = _FakeAppClient();
      await openDialog(tester, fake);
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Source scope'),
        '',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Add'));
      await tester.pump();
      expect(find.text('Source scope is required'), findsOneWidget);
      expect(fake.calls, 0);
    });
  });
}

class _FakeAppClient extends AppClient {
  _FakeAppClient()
      : super(
          session: DaemonSession(
            client: SocketClient('/nonexistent/never-bound.sock'),
          ),
        );

  int calls = 0;
  String? lastSourceScope;
  String? lastTemplate;
  String? lastTarget;

  @override
  Future<Map<String, dynamic>> routeAdd({
    required String sourceScope,
    required String template,
    required String target,
    String? idempotencyKey,
  }) async {
    calls += 1;
    lastSourceScope = sourceScope;
    lastTemplate = template;
    lastTarget = target;
    return Fixtures.route(
      sourceScope: sourceScope,
      template: template,
      target: target,
    );
  }

  @override
  Future<PagedResult> routeList({String? cursorNext, int? limit}) async {
    return const PagedResult(items: [], cursorNext: null, total: 0);
  }
}
