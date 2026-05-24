import 'package:agenttower_control_panel/core/daemon/contract_version.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/domain/models/adopted_agent.dart';
import 'package:agenttower_control_panel/domain/models/pane.dart';
import 'package:agenttower_control_panel/domain/models/queue_row.dart';
import 'package:agenttower_control_panel/domain/models/route.dart' as model;
import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import '../test/helpers/fixture_builders.dart';
import '../test/helpers/mock_daemon_client.dart';

/// Phase 3 smoke walk. Review fix H16 / spec-kit lane.
///
/// Where `us1_adopt_and_operate.dart` (T054) asserts SC-001's 10-minute
/// budget, this test walks the actual US1 §1-§6 acceptance sequence
/// against the mock daemon: dashboard → containers → panes → adopt →
/// agents → log → send → queue → routes. Each step issues a real wire
/// call through `DaemonSession` + `AppClient` against the harness and
/// asserts the freezed model round-trips correctly.
///
/// Scope: this is a wire-level integration test, not a UI driver. The
/// 12 widget tests for the per-surface widgets land separately and need
/// the build_runner-generated `.freezed.dart` / `.g.dart` files first.
/// Skipped when `python3` is unavailable.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  late bool pythonOk;
  setUpAll(() async {
    pythonOk = await isPython3Available();
  });

  test('US1 wire walk: bootstrap → list every surface → adopt → send → route',
      () async {
    if (!pythonOk) {
      markTestSkipped('python3 not on PATH; cannot spawn mock-daemon harness');
      return;
    }
    ContractRegistry.resetForTesting();
    seedMvpContractDeclarations();

    final fixture = _us1Fixture();
    final harness = await MockDaemonClient.start(fixture: fixture);
    addTearDown(harness.stop);

    final socket = SocketClient(harness.socketPath);
    final session = DaemonSession(client: socket);
    await session.bootstrap();
    addTearDown(session.dispose);

    final client = AppClient(session: session);

    // §1 Dashboard renders the FEAT-011 v1.0 shape.
    final dashboard = await client.dashboard();
    final counts = dashboard['counts'] as Map<String, dynamic>;
    expect(counts['containers'], isA<Map<String, dynamic>>());
    expect(counts['panes'], isA<Map<String, dynamic>>());
    expect(counts['agents'], isA<Map<String, dynamic>>());

    // §2 Containers list returns ≥1 row (parses through the freezed
    // model without throwing).
    final containers = await client.containerList();
    expect(containers.items, isNotEmpty);

    // §3 Pane discovery — every row exposes all 6 identity fields
    // required by register_from_pane.
    final panes = await client.paneList();
    expect(panes.items, isNotEmpty);
    final paneJson = panes.items.first;
    for (final required in const [
      'pane_id',
      'container_id',
      'tmux_socket',
      'tmux_session_name',
      'tmux_window_index',
      'tmux_pane_index',
    ]) {
      expect(paneJson.containsKey(required), isTrue,
          reason: 'app.pane.list row missing identity field `$required`');
    }
    // Parse through the freezed model.
    final asOf = DateTime.now().toUtc().toIso8601String();
    final pane = Pane.fromJson({...paneJson, 'as_of': asOf});
    expect(pane.tmuxWindowIndex, isA<int>());

    // §4 Adopt: the mock daemon echoes a fully-populated agent row.
    final adoptResult = await client.agentRegisterFromPane(
      paneId: pane.paneId,
      containerId: pane.containerId,
      tmuxSocket: pane.tmuxSocket,
      sessionName: pane.tmuxSessionName,
      windowIndex: pane.tmuxWindowIndex,
      paneIndex: pane.tmuxPaneIndex,
      label: 'smoke-walk-master',
      role: 'master',
      capability: 'claude',
    );
    final adoptedAgent =
        AdoptedAgent.fromJson({...adoptResult, 'as_of': asOf});
    expect(adoptedAgent.label, 'claude-master-1'); // fixture-fixed

    // §5 Direct Send returns the FLAT {message_id, state, deduplicated}
    // shape per contract.
    final sendResult = await client.sendInput(
      targetAgentId: adoptedAgent.agentId,
      payload: const {'text': 'smoke-walk hello'},
    );
    expect(sendResult.containsKey('message_id'), isTrue);
    expect(sendResult.containsKey('state'), isTrue);
    expect(sendResult.containsKey('deduplicated'), isTrue);

    // Queue list also parses cleanly.
    final queue = await client.queueList();
    expect(queue.items, isNotEmpty);
    final qrow = QueueRow.fromJson({...queue.items.first, 'as_of': asOf});
    expect(qrow.messageId, isNotEmpty);

    // §6 Route add returns a row that round-trips through the Route
    // model with template/target.
    final addResult = await client.routeAdd(
      sourceScope: 'agent:claude-master-1',
      template: 'forward_event_to',
      target: 'agent:codex-slave-1',
    );
    final route = model.Route.fromJson({...addResult, 'as_of': asOf});
    expect(route.template, 'forward_event_to');
    expect(route.target, 'agent:codex-slave-1');

    final routes = await client.routeList();
    expect(routes.items, isNotEmpty);
  });
}

/// US1 fixture using the canonical `rows` / `row` wire shapes (review
/// fix C1-C6 — the prior fixture used `items`/`next_cursor` which the
/// AppClient also read incorrectly, so the bugs cancelled out).
Map<String, dynamic> _us1Fixture() {
  return {
    'app_contract_version': '1.0',
    'daemon_version': '0.11.0-mock',
    'app_session_token': '00000000-0000-4000-8000-000000000001',
    'app_session_id': 1,
    'host_user_id': '1000',
    'schema_version': 1,
    'responses': {
      'app.hello': {'ok': true, 'result': const {}},
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
      'app.agent.register_from_pane': {
        'ok': true,
        'result': Fixtures.rowResult(Fixtures.agent()),
      },
      'app.agent.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.agent()]),
      },
      'app.send_input': {
        'ok': true,
        'result': const {
          'message_id': 'q-smoke-1',
          'state': 'queued',
          'deduplicated': false,
        },
      },
      'app.queue.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.queueRow()]),
      },
      'app.route.add': {
        'ok': true,
        'result': Fixtures.rowResult(Fixtures.route()),
      },
      'app.route.list': {
        'ok': true,
        'result': Fixtures.listResult([Fixtures.route()]),
      },
    },
  };
}
