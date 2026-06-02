import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/models/adopted_agent.dart';
import 'package:agenttower_control_panel/features/agent_ops/agents/direct_send.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';
import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';

/// Widget tests for [DirectSendDialog] (FR-018). T164 — Phase 3 US1.
///
/// FR-018: payload required, daemon response inline, no silent retry.
void main() {
  Future<void> openDialog(WidgetTester tester, _FakeAppClient fake) async {
    final agent = AdoptedAgent.fromJson(
      Fixtures.agent(label: 'claude-master-1'),
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appClientProvider.overrideWithValue(fake),
        ],
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: Builder(
              builder: (ctx) => ElevatedButton(
                onPressed: () => DirectSendDialog.show(ctx, agent: agent),
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

  group('DirectSendDialog', () {
    testWidgets('empty payload triggers validator and does not call daemon',
        (tester) async {
      final fake = _FakeAppClient();
      await openDialog(tester, fake);

      await tester.tap(find.ancestor(of: find.text('Send'), matching: find.bySubtype<FilledButton>()));
      await tester.pump();
      expect(find.text('Payload is required (FR-018)'), findsOneWidget);
      expect(fake.calls, 0);
    });

    testWidgets('successful send dismisses dialog and shows success snackbar',
        (tester) async {
      final fake = _FakeAppClient();
      await openDialog(tester, fake);

      await tester.enterText(
        find.widgetWithText(TextFormField, 'Payload'),
        'hello',
      );
      await tester.tap(find.ancestor(of: find.text('Send'), matching: find.bySubtype<FilledButton>()));
      // Settle the awaits.
      await tester.pump();
      await tester.pump();
      await tester.pumpAndSettle();

      expect(fake.calls, 1);
      expect(fake.lastPayload, {'text': 'hello'});
      expect(find.text('Sent.'), findsOneWidget);
      // Dialog popped → opener button visible again.
      expect(find.text('open'), findsOneWidget);
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
  Map<String, dynamic>? lastPayload;

  @override
  Future<Map<String, dynamic>> sendInput({
    required String targetAgentId,
    required Map<String, dynamic> payload,
    String? idempotencyKey,
  }) async {
    calls += 1;
    lastPayload = payload;
    return const {'message_id': 'm1', 'state': 'queued', 'deduplicated': false};
  }
}
