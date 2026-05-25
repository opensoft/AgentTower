import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/errors.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/domain/models/pane.dart';
import 'package:agenttower_control_panel/features/agent_ops/panes/adopt_flow.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';

/// Widget tests for the [AdoptFlow] dialog (FR-016 + FR-028a). T164.
///
/// Covers:
///   - validator messages when label / project_path are blank
///   - submit success path calls agentRegisterFromPane + pops dialog
///   - per-error rendering when the daemon rejects (e.g. role/cap
///     incompatible with discovered pane class — FR-016 + FR-071)
void main() {
  // Pane fixture used across tests — discovered-and-unmanaged is the
  // only state from which AdoptFlow can transition to registered.
  Pane buildPane() => Pane.fromJson(
        Fixtures.pane(state: PaneState.discoveredAndUnmanaged),
      );

  Future<void> openFlow(WidgetTester tester, AppClient fake) async {
    final pane = buildPane();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appClientProvider.overrideWithValue(fake),
        ],
        child: MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (ctx) => ElevatedButton(
                onPressed: () => AdoptFlow.show(ctx, pane: pane),
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

  group('AdoptFlow', () {
    testWidgets('blank label is rejected with validator message',
        (tester) async {
      final fake = _FakeAppClient();
      await openFlow(tester, fake);
      // Submit without filling label (project path defaults to /work).
      await tester.tap(find.widgetWithText(FilledButton, 'Adopt'));
      await tester.pump();
      expect(find.text('Label is required'), findsOneWidget);
      expect(fake.calls, 0);
    });

    testWidgets('blank project_path is rejected with validator message',
        (tester) async {
      final fake = _FakeAppClient();
      await openFlow(tester, fake);
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Label'),
        'claude-master-1',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Project path'),
        '',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Adopt'));
      await tester.pump();
      expect(find.text('Project path is required'), findsOneWidget);
      expect(fake.calls, 0);
    });

    testWidgets('submit success calls agentRegisterFromPane and dismisses',
        (tester) async {
      final fake = _FakeAppClient();
      await openFlow(tester, fake);
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Label'),
        'claude-master-1',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Adopt'));
      await tester.pumpAndSettle();
      expect(fake.calls, 1);
      expect(fake.lastLabel, 'claude-master-1');
      expect(fake.lastRole, AgentRole.master.wireValue);
      // Dialog popped → opener button visible again.
      expect(find.text('open'), findsOneWidget);
    });

    testWidgets('daemon validation_failed renders inline error', (tester) async {
      final fake = _FakeAppClient(
        error: const AppContractError(
          code: AppContractErrorCode.validationFailed,
          message: 'role/capability incompatible with pane class',
          details: <String, dynamic>{},
        ),
      );
      await openFlow(tester, fake);
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Label'),
        'claude-master-1',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Adopt'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('role/capability incompatible with pane class'),
        findsOneWidget,
      );
    });
  });
}

class _FakeAppClient extends AppClient {
  _FakeAppClient({this.error})
      : super(
          session: DaemonSession(
            client: SocketClient('/nonexistent/never-bound.sock'),
          ),
        );

  final Object? error;
  int calls = 0;
  String? lastLabel;
  String? lastRole;

  @override
  Future<Map<String, dynamic>> agentRegisterFromPane({
    required String paneId,
    required String containerId,
    required String tmuxSocket,
    required String sessionName,
    required int windowIndex,
    required int paneIndex,
    required String label,
    required String role,
    required String capability,
    String? projectPath,
    String? parentAgentId,
    bool attachLog = false,
    String? idempotencyKey,
  }) async {
    calls += 1;
    lastLabel = label;
    lastRole = role;
    if (error != null) throw error!;
    return Fixtures.agent(label: label);
  }
}
