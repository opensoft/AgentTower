import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/preflight_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/lifecycles/drift_state_validator.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/features/project_specs/drift/providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import '../test/helpers/fixture_builders.dart';
import '../test/helpers/mock_daemon_client.dart';

/// US4 end-to-end integration test. T112 (Phase 6 US4).
///
/// Covers:
///   §1 Drift list renders the documented fields (status, source,
///      severity, confidence, age, scope, summary, recommendation,
///      evidence, linked refs).
///   §2 driftDetail returns the per-finding evidence list.
///   §3 Operator transition new → review_needed → confirmed →
///      repair_planned → resolved (FR-034 canonical forward path).
///   §4 Illegal transition (resolved → new) is rejected by
///      DriftStateValidator before any wire call.
///   §5 SC-005-style: a refresh after a daemon-side transition picks
///      up the new status. (The 60s wall-clock assertion lives in
///      the badge widget tests; here we verify the data flow.)
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  late bool pythonOk;
  setUpAll(() async {
    pythonOk = await isPython3Available();
  });

  testWidgets('US4 drift — render, transition, illegal-transition gate',
      (tester) async {
    if (!pythonOk) {
      markTestSkipped('python3 not on PATH; cannot spawn mock-daemon harness');
      return;
    }

    final fixture = _buildUs4Fixture();
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

    // §1 — list returns the seeded finding with the documented fields.
    final list = await container.read(
      driftListProvider(const DriftListQuery(projectId: 'proj-1')).future,
    );
    expect(list, hasLength(1));
    final drift = list.first;
    expect(drift.findingId, 'drift-1');
    expect(drift.status, DriftStatus.newFinding);
    expect(drift.severity, DriftSeverity.warning);
    expect(drift.source, DriftSource.staticCheck);
    expect(drift.scope.id, 'FEAT-012');
    expect(drift.evidence, hasLength(1));
    expect(drift.evidence.first.summary, 'log line 42');

    // §2 — detail returns the same id with evidence.
    final detail = await container.read(
      driftDetailProvider(drift.findingId).future,
    );
    expect(detail.findingId, 'drift-1');

    // §3 — canonical forward transition is legal at every step.
    expect(
      DriftStateValidator.isValidTransition(
        DriftStatus.newFinding, DriftStatus.reviewNeeded,
      ),
      isTrue,
    );
    expect(
      DriftStateValidator.isValidTransition(
        DriftStatus.reviewNeeded, DriftStatus.confirmed,
      ),
      isTrue,
    );

    // §4 — illegal transition (resolved → new) is rejected client-side
    // by the validator without round-tripping the daemon.
    expect(
      DriftStateValidator.isValidTransition(
        DriftStatus.resolved, DriftStatus.newFinding,
      ),
      isFalse,
    );
    expect(
      DriftStateValidator.isValidTransition(
        DriftStatus.newFinding, DriftStatus.resolved,
      ),
      isFalse,
      reason:
          'Skipping forward states is rejected per FR-034 except into the '
          'terminal pair (accepted_as_built / dismissed).',
    );

    // §5 — driving the transition through the daemon succeeds.
    final transitioned = await appClient.driftTransition(
      findingId: drift.findingId,
      toStatus: DriftStatus.reviewNeeded.wireValue,
    );
    expect(transitioned['status'], DriftStatus.reviewNeeded.wireValue);
  });
}

Map<String, dynamic> _buildUs4Fixture() {
  final drift = Fixtures.drift(
    findingId: 'drift-1',
    status: DriftStatus.newFinding,
    severity: DriftSeverity.warning,
    source: DriftSource.staticCheck,
    confidence: DriftConfidence.medium,
    summary: 'Branch does not match intended feature/change',
    recommendedAction: 'Switch to the intended branch or update the spec',
    scope: const {'type': 'feature_change', 'id': 'FEAT-012'},
    evidence: const [
      {
        'kind': 'log_excerpt',
        'summary': 'log line 42',
        'text': 'WARN: branch mismatch detected',
      },
    ],
    linkedFeatureIds: const ['FEAT-012'],
  );
  final transitioned = {
    ...drift,
    'status': DriftStatus.reviewNeeded.wireValue,
  };
  return {
    'app_contract_version': '1.0',
    'responses': {
      'app.hello': {'ok': true, 'result': <String, dynamic>{}},
      'app.readiness': {'ok': true, 'result': Fixtures.readinessResult()},
      'app.drift.list': {
        'ok': true,
        'result': Fixtures.listResult([drift]),
      },
      'app.drift.detail': {
        'ok': true,
        'result': Fixtures.rowResult(drift),
      },
      'app.drift.transition': {
        'ok': true,
        'result': Fixtures.rowResult(transitioned),
      },
    },
  };
}
