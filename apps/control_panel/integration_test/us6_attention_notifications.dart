import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/preflight_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/notifications/grouping_rule.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/models/attention_item.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/features/agent_ops/attention/interaction_stability.dart';
import 'package:agenttower_control_panel/features/agent_ops/attention/providers.dart';
import 'package:agenttower_control_panel/features/notifications/providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import '../test/helpers/fixture_builders.dart';
import '../test/helpers/mock_daemon_client.dart';

/// US6 end-to-end integration test. T130 (Phase 8 US6).
///
/// Covers §1-§5 acceptance scenarios via the mock-daemon harness:
///   §1 Attention list renders the seeded items.
///   §2 FR-053 stability — InteractionStabilityController defers
///      updates while in window (synthetic clock).
///   §3 FR-054 — resolution target sealed-class round-trips.
///   §4 FR-057 grouping rule — collapses N ≥ 3 warning-severity
///      notifications sharing event_class+agent_id within 60 s.
///   §5 high/critical NEVER grouped per FR-057 last sentence.
///   §SC-008a — interaction-stability shape verified with a
///      synthetic clock (production wall-clock test belongs in
///      widget tests with `tester.pumpAndSettle`).
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  late bool pythonOk;
  setUpAll(() async {
    pythonOk = await isPython3Available();
  });

  testWidgets('US6 attention + notifications — list, stability, grouping',
      (tester) async {
    if (!pythonOk) {
      markTestSkipped('python3 not on PATH; cannot spawn mock-daemon harness');
      return;
    }

    final fixture = _buildUs6Fixture();
    final harness = await MockDaemonClient.start(fixture: fixture);
    addTearDown(harness.stop);

    final socketClient = SocketClient(harness.socketPath);
    final session = DaemonSession(client: socketClient);
    await session.bootstrap();
    addTearDown(session.dispose);

    final appClient = AppClient(session: session);
    final preflight = PreflightClient(socketPath: harness.socketPath);

    final container = ProviderContainer(
      overrides: [
        socketClientProvider.overrideWithValue(socketClient),
        daemonSessionProvider.overrideWithValue(session),
        appClientProvider.overrideWithValue(appClient),
        preflightClientProvider.overrideWithValue(preflight),
      ],
    );
    addTearDown(container.dispose);

    // §1 — attention list returns the seeded items.
    final items = await container.read(
      attentionListProvider(const AttentionListQuery()).future,
    );
    expect(items, hasLength(2));
    expect(items.first.severity, AttentionSeverity.critical);

    // §3 — sealed-class round-trip. Find the queue-row item by id
    // (severity-then-age sort puts critical drift first; the queue
    // attention item is second).
    final queueItem = items.firstWhere((i) => i.attentionId == 'att-queue');
    expect(queueItem.resolutionTarget, isA<ResolutionTargetQueueRow>());
    final driftItem =
        items.firstWhere((i) => i.attentionId == 'att-critical');
    expect(driftItem.resolutionTarget, isA<ResolutionTargetDriftFinding>());

    // §2 + §SC-008a — interaction stability. Use a synthetic clock
    // so the test runs in milliseconds while exercising the same
    // logic that runs against the real clock in production.
    var fakeNow = DateTime.utc(2026, 5, 24, 0, 0, 0);
    final stability = InteractionStabilityController(
      windowDuration: const Duration(seconds: 2),
      now: () => fakeNow,
    );
    addTearDown(stability.dispose);

    stability.acceptIncoming([items.first]);
    expect(stability.stableList, hasLength(1));
    // Simulate interaction (hover/click): now in window.
    stability.noteInteraction();
    expect(stability.isInWindow, isTrue);
    // New update arrives mid-window — held as pending.
    stability.acceptIncoming(items);
    expect(stability.stableList, hasLength(1),
        reason: 'pending update must not swap while in window');
    // Advance clock past window.
    fakeNow = fakeNow.add(const Duration(seconds: 3));
    expect(stability.isInWindow, isFalse);

    // §4 — FR-057 grouping collapses 3 warning-severity notifs.
    final candidates = List.generate(
      3,
      (i) => NotificationCandidate(
        notificationId: 'n$i',
        eventClass: 'route_skipped',
        agentId: 'agent-1',
        severity: NotificationSeverity.warning,
        emittedAt: DateTime.now().subtract(Duration(seconds: i * 5)),
        summary: 'skip',
      ),
    );
    final grouped = const NotificationGroupingRule().project(candidates);
    expect(grouped, hasLength(1));
    expect(grouped.first.isGrouped, isTrue);
    expect(grouped.first.count, 3);

    // §5 — high/critical NEVER grouped.
    final highOnly = [
      NotificationCandidate(
        notificationId: 'h1',
        eventClass: 'queue_blocked',
        agentId: 'agent-1',
        severity: NotificationSeverity.high,
        emittedAt: DateTime.now(),
        summary: 'blocked',
      ),
      NotificationCandidate(
        notificationId: 'h2',
        eventClass: 'queue_blocked',
        agentId: 'agent-1',
        severity: NotificationSeverity.high,
        emittedAt: DateTime.now(),
        summary: 'blocked',
      ),
      NotificationCandidate(
        notificationId: 'h3',
        eventClass: 'queue_blocked',
        agentId: 'agent-1',
        severity: NotificationSeverity.high,
        emittedAt: DateTime.now(),
        summary: 'blocked',
      ),
    ];
    final highGrouped = const NotificationGroupingRule().project(highOnly);
    expect(highGrouped, hasLength(3),
        reason: 'high severity must never be grouped per FR-057');

    // Notifications list exposes the daemon-emitted notifications.
    final notifs = await container.read(
      notificationListProvider(
        const NotificationListQuery(lifecycle: 'incoming'),
      ).future,
    );
    expect(notifs, hasLength(1));
  });
}

Map<String, dynamic> _buildUs6Fixture() {
  final critical = Fixtures.attentionItem(
    attentionId: 'att-critical',
    attentionClass: 'drift_confirmed',
    severity: 'critical',
    oneLineSummary: 'Drift confirmed on FEAT-012',
    resolutionTarget: Fixtures.resolutionDriftFinding('drift-1'),
  );
  // ResolutionTargetQueueRow first for the §3 assertion.
  final blockedQueue = Fixtures.attentionItem(
    attentionId: 'att-queue',
    attentionClass: 'blocked_queue_row',
    severity: 'high',
    oneLineSummary: 'Queue row blocked',
    resolutionTarget: Fixtures.resolutionQueueRow('msg-1'),
  );
  final notif = Fixtures.notification(severity: NotificationSeverity.warning);
  return {
    'app_contract_version': '1.0',
    'responses': {
      'app.hello': {'ok': true, 'result': <String, dynamic>{}},
      'app.readiness': {'ok': true, 'result': Fixtures.readinessResult()},
      // Severity-then-age sort means critical comes first in the list
      // even though it's listed second in the fixture rows.
      'app.attention.list': {
        'ok': true,
        'result': Fixtures.listResult([critical, blockedQueue]),
      },
      'app.notification.list': {
        'ok': true,
        'result': Fixtures.listResult([notif]),
      },
      'app.notification.history': {
        'ok': true,
        'result': Fixtures.listResult(const <Map<String, dynamic>>[]),
      },
      'app.operator_history.list': {
        'ok': true,
        'result': Fixtures.listResult(const <Map<String, dynamic>>[]),
      },
    },
  };
}
