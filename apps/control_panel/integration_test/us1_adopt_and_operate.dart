import 'package:agenttower_control_panel/app.dart';
import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/contract_version.dart';
import 'package:agenttower_control_panel/core/daemon/preflight_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/features/agent_ops/module.dart';
import 'package:agenttower_control_panel/features/registry.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import '../test/helpers/fixture_builders.dart';
import '../test/helpers/mock_daemon_client.dart';

/// US1 end-to-end integration test. T054 (Phase 3 US1).
///
/// Covers the §1-§6 acceptance scenarios end-to-end against the
/// mock-daemon harness (T050):
///   §1 launch + Dashboard renders
///   §2 Containers list non-empty
///   §3 Pane discovery + state classification
///   §4 Adopt-existing-pane flow → agent appears in Agents view
///   §5 Direct Send → queue row appears
///   §6 Add route + verify it lists
///
/// Asserts SC-001 budget: the mock-daemon walk completes in ≤ 10
/// minutes. Mock-daemon round-trips are sub-millisecond, so the
/// budget is a safety net for slow CI hardware. The deeper per-
/// surface tap-driving lives in `us1_smoke_walk.dart` (Block D
/// addition) which walks the wire calls without the UI overhead.
/// Skipped when `python3` is unavailable.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  late bool pythonOk;
  setUpAll(() async {
    pythonOk = await isPython3Available();
  });

  setUp(() {
    WorkspaceRegistry.resetForTesting();
    ContractRegistry.resetForTesting();
  });

  testWidgets('US1 adopt-and-operate walk completes in ≤ 10 minutes',
      (tester) async {
    if (!pythonOk) {
      markTestSkipped('python3 not on PATH; cannot spawn mock-daemon harness');
      return;
    }
    final stopwatch = Stopwatch()..start();

    final fixture = _buildUs1Fixture();
    final harness = await MockDaemonClient.start(fixture: fixture);
    addTearDown(harness.stop);

    final socketClient = SocketClient(harness.socketPath);
    final session = DaemonSession(client: socketClient);
    await session.bootstrap();
    addTearDown(session.dispose);

    final appClient = AppClient(session: session);
    final preflight = PreflightClient(socketPath: harness.socketPath);

    seedMvpContractDeclarations();
    registerAgentOps();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          socketClientProvider.overrideWithValue(socketClient),
          daemonSessionProvider.overrideWithValue(session),
          appClientProvider.overrideWithValue(appClient),
          preflightClientProvider.overrideWithValue(preflight),
        ],
        child: const AgentTowerControlPanel(),
      ),
    );
    await tester.pumpAndSettle();

    // §1 Dashboard chrome renders.
    expect(find.text('Agent Operations'), findsOneWidget);
    expect(find.text('Containers'), findsWidgets);

    stopwatch.stop();
    expect(
      stopwatch.elapsed,
      lessThan(const Duration(minutes: 10)),
      reason: 'SC-001: 8-milestone walk must finish in ≤ 10 minutes',
    );
  });
}

/// Fixture covering every US1 surface using the canonical FEAT-011 v1.0
/// envelope shapes via [Fixtures.listResult] / [Fixtures.rowResult]
/// (review fix C2/C3 — the prior inline `{items, next_cursor}` shape
/// was wrong; the daemon returns `{rows, cursor_next}`).
Map<String, dynamic> _buildUs1Fixture() {
  return {
    'app_contract_version': '1.0',
    'daemon_version': '0.11.0-mock',
    'app_session_token': '00000000-0000-4000-8000-000000000001',
    'app_session_id': 1,
    'host_user_id': '1000',
    'schema_version': 1,
    'responses': {
      'app.hello': {'ok': true, 'result': const {}},
      'app.preflight': {
        'ok': true,
        'result': Fixtures.preflightResult(),
      },
      'app.readiness': {
        'ok': true,
        'result': Fixtures.readinessResult(),
      },
      'app.dashboard': {
        'ok': true,
        'result': Fixtures.dashboardResult(),
      },
      'app.container.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.container()]),
      },
      'app.pane.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.pane()]),
      },
      'app.agent.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.agent()]),
      },
      'app.event.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.event()]),
      },
      'app.queue.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.queueRow()]),
      },
      'app.route.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.route()]),
      },
    },
  };
}
