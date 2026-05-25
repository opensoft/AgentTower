import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/models/adopted_agent.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/features/agent_ops/agents/log_attach_affordance.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';

/// Widget tests for [LogAttachAffordance] (FR-017). T164 — Phase 3 US1.
///
/// FR-017: per-agent attach/detach affordance with busy state during
/// the daemon round-trip. Active + superseded render as "Detach log";
/// anything else renders as "Attach log".
void main() {
  AdoptedAgent agentWith(LogAttachmentState? attachment) {
    final json = Fixtures.agent();
    if (attachment != null) {
      json['log_attachment'] = attachment.wireValue;
    }
    return AdoptedAgent.fromJson(json);
  }

  Future<void> pumpAffordance(
    WidgetTester tester, {
    required AdoptedAgent agent,
    required AppClient fake,
  }) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appClientProvider.overrideWithValue(fake),
        ],
        child: MaterialApp(
          home: Scaffold(body: LogAttachAffordance(agent: agent)),
        ),
      ),
    );
    await tester.pump();
  }

  group('LogAttachAffordance', () {
    testWidgets('renders "Attach log" when no log attachment is present',
        (tester) async {
      final fake = _FakeAppClient();
      await pumpAffordance(tester, agent: agentWith(null), fake: fake);
      expect(find.widgetWithText(TextButton, 'Attach log'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Detach log'), findsNothing);
    });

    testWidgets('renders "Detach log" when log attachment is active',
        (tester) async {
      final fake = _FakeAppClient();
      await pumpAffordance(
        tester,
        agent: agentWith(LogAttachmentState.active),
        fake: fake,
      );
      expect(find.widgetWithText(TextButton, 'Detach log'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Attach log'), findsNothing);
    });

    testWidgets('tapping Attach calls logAttach and is briefly disabled',
        (tester) async {
      final fake = _FakeAppClient();
      await pumpAffordance(
        tester,
        agent: agentWith(LogAttachmentState.detached),
        fake: fake,
      );
      await tester.tap(find.widgetWithText(TextButton, 'Attach log'));
      // Pump once so the setState(_busy = true) lands.
      await tester.pump();
      // During the awaited call the button is disabled — onPressed null.
      final button = tester.widget<TextButton>(
        find.widgetWithText(TextButton, 'Attach log'),
      );
      expect(button.onPressed, isNull);
      // Settle the future + the post-await SnackBar.
      await tester.pumpAndSettle();
      expect(fake.attachCalls, 1);
      expect(fake.detachCalls, 0);
    });

    testWidgets('tapping Detach calls logDetach', (tester) async {
      final fake = _FakeAppClient();
      await pumpAffordance(
        tester,
        agent: agentWith(LogAttachmentState.active),
        fake: fake,
      );
      await tester.tap(find.widgetWithText(TextButton, 'Detach log'));
      await tester.pump();
      await tester.pumpAndSettle();
      expect(fake.detachCalls, 1);
      expect(fake.attachCalls, 0);
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

  int attachCalls = 0;
  int detachCalls = 0;

  @override
  Future<Map<String, dynamic>> logAttach({
    required String agentId,
    String? idempotencyKey,
  }) async {
    attachCalls += 1;
    return const {};
  }

  @override
  Future<Map<String, dynamic>> logDetach({
    required String agentId,
    String? idempotencyKey,
  }) async {
    detachCalls += 1;
    return const {};
  }

  // agentList is invalidated post-mutation; surface a non-empty list so
  // the agentListProvider rebuild doesn't crash the FutureProvider.
  @override
  Future<PagedResult> agentList({
    String? cursorNext,
    int? limit,
    String? role,
    String? capability,
    String? containerId,
    bool? logAttached,
  }) async {
    return const PagedResult(items: [], cursorNext: null, total: 0);
  }
}
