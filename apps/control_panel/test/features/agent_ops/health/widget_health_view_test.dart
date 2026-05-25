import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/features/agent_ops/health/health_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';

/// Widget tests for [HealthView] (FR-022 + FR-059). T164 — Phase 3 US1.
///
/// FR-022 surfaces a composite overall state plus per-subsystem rows.
/// Each subsystem row renders status + (when present) reason and hint
/// — the FR-059 explainability bits so the operator does not need to
/// dive into the daemon logs to understand why a subsystem is
/// degraded.
///
/// The view picks a state-specific icon for the overall card:
///   - ready       → check_circle
///   - degraded    → warning_amber_outlined
///   - unavailable → error_outline
///   - anything else → help_outline
void main() {
  group('HealthView', () {
    testWidgets('healthy state renders the ready icon + ok rows',
        (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(
              _FakeAppClient(
                readinessResult: Fixtures.readinessResult(state: 'ready'),
              ),
            ),
          ],
          child: const MaterialApp(home: Scaffold(body: HealthView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.text('Overall: ready'), findsOneWidget);
      expect(find.byIcon(Icons.check_circle), findsOneWidget);
      // The default fixture exposes 6 subsystems all in ok state.
      expect(find.text('docker'), findsOneWidget);
      expect(find.text('sqlite'), findsOneWidget);
    });

    testWidgets('degraded state renders warning icon + reason + hint',
        (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(
              _FakeAppClient(
                readinessResult: Fixtures.readinessResult(
                  state: 'degraded',
                  subsystems: const [
                    {
                      'name': 'tmux_discovery',
                      'status': 'degraded',
                      'reason': 'last scan returned partial results',
                      'hint': 'Re-probe panes from the Panes view',
                    },
                  ],
                  hints: const [
                    {'message': 'Last successful event at 12:34:00Z'},
                  ],
                ),
              ),
            ),
          ],
          child: const MaterialApp(home: Scaffold(body: HealthView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.text('Overall: degraded'), findsOneWidget);
      expect(find.byIcon(Icons.warning_amber_outlined), findsWidgets);
      expect(
        find.textContaining('Reason: last scan returned partial results'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Hint: Re-probe panes from the Panes view'),
        findsOneWidget,
      );
      // The result-level hints list renders below the per-subsystem tiles.
      expect(find.text('Last successful event at 12:34:00Z'), findsOneWidget);
    });

    testWidgets('unavailable state renders error_outline icon',
        (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(
              _FakeAppClient(
                readinessResult: Fixtures.readinessResult(
                  state: 'unavailable',
                  subsystems: const [
                    {
                      'name': 'docker',
                      'status': 'unavailable',
                      'reason': 'socket not reachable',
                      'hint': null,
                    },
                  ],
                ),
              ),
            ),
          ],
          child: const MaterialApp(home: Scaffold(body: HealthView())),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.text('Overall: unavailable'), findsOneWidget);
      expect(find.byIcon(Icons.error_outline), findsWidgets);
    });
  });
}

class _FakeAppClient extends AppClient {
  _FakeAppClient({required Map<String, dynamic> readinessResult})
      : _readinessResult = readinessResult,
        super(
          session: DaemonSession(
            client: SocketClient('/nonexistent/never-bound.sock'),
          ),
        );

  final Map<String, dynamic> _readinessResult;

  @override
  Future<Map<String, dynamic>> readiness() async => Map.of(_readinessResult);
}
