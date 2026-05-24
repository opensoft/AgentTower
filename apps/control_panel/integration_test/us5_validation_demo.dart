import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/preflight_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/lifecycles/validation_run_state_validator.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/domain/models/demo_readiness_summary.dart';
import 'package:agenttower_control_panel/domain/models/validation_entrypoint.dart';
import 'package:agenttower_control_panel/domain/models/validation_run.dart';
import 'package:agenttower_control_panel/features/testing_demo/demo_readiness/readiness_computation.dart';
import 'package:agenttower_control_panel/features/testing_demo/providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import '../test/helpers/fixture_builders.dart';
import '../test/helpers/mock_daemon_client.dart';

/// US5 end-to-end integration test. T119 (Phase 7 US5).
///
/// Covers §1-§5 acceptance scenarios via the mock-daemon harness:
///   §1 list + group entrypoints by scope (FR-046/047)
///   §2 trigger a run → returns queued row (FR-049 + SC-006 daemon
///      invariant — surfaced via re-fetch)
///   §3 cancel transition gate (FR-048 ValidationRunStateValidator
///      legal/illegal transitions)
///   §4 demo readiness summary fields (FR-050)
///   §5 enforceRequiredInvariant downgrades `ready` → `at_risk`
///      when a `required`-level entrypoint has not run on the
///      current branch.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  late bool pythonOk;
  setUpAll(() async {
    pythonOk = await isPython3Available();
  });

  testWidgets('US5 validation + demo readiness — list, trigger, cancel, downgrade',
      (tester) async {
    if (!pythonOk) {
      markTestSkipped('python3 not on PATH; cannot spawn mock-daemon harness');
      return;
    }

    final fixture = _buildUs5Fixture();
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

    // §1 — list entrypoints.
    final entrypoints = await container.read(
      validationEntrypointListProvider(
        const EntrypointListQuery(projectId: 'proj-1'),
      ).future,
    );
    expect(entrypoints, hasLength(2));
    expect(entrypoints.first.blockingLevel, BlockingLevel.required);

    // §2 — trigger returns the queued row.
    final triggered = await appClient.validationRunTrigger(
      entrypointId: 'ep-1',
      targetKind: 'project',
      targetId: 'proj-1',
    );
    expect(triggered['state'], 'queued');

    // §3 — FR-048 cancel transition gate.
    expect(
      ValidationRunStateValidator.isValidTransition(
        RunState.queued, RunState.cancelled,
      ),
      isTrue,
    );
    expect(
      ValidationRunStateValidator.isValidTransition(
        RunState.completed, RunState.cancelled,
      ),
      isFalse,
      reason: 'cancel is only legal from queued/running per FR-048',
    );

    // §4 — demo readiness fields.
    final summary = await container.read(
      demoReadinessProvider(
        const DemoReadinessQuery(projectId: 'proj-1', branch: 'main'),
      ).future,
    );
    expect(summary.overallState, DemoReadinessState.ready);

    // §5 — FR-050 invariant downgrade. Build a synthetic scenario:
    // one required entrypoint, zero runs on the branch. The
    // enforcement helper should downgrade `ready` to `at_risk`.
    final entrypoint = ValidationEntrypoint.fromJson(
      Map<String, dynamic>.from(
        Fixtures.validationEntrypoint(blockingLevel: 'required', enabled: true),
      )..['as_of'] = DateTime.now().toUtc().toIso8601String(),
    );
    final readyFromDaemon = DemoReadinessSummary.fromJson(
      Map<String, dynamic>.from(
        Fixtures.demoReadiness(overallState: 'ready', branch: 'main'),
      )..['as_of'] = DateTime.now().toUtc().toIso8601String(),
    );
    final downgraded = enforceRequiredInvariant(
      summary: readyFromDaemon,
      entrypoints: [entrypoint],
      recentRuns: const <ValidationRun>[],
    );
    expect(downgraded.effectiveState, DemoReadinessState.atRisk);
    expect(downgraded.wasDowngraded, isTrue);
  });
}

Map<String, dynamic> _buildUs5Fixture() {
  final requiredEntry = Fixtures.validationEntrypoint(
    entrypointId: 'ep-1',
    label: 'Required unit tests',
    type: 'unit_test',
    blockingLevel: 'required',
    enabled: true,
  );
  final recommendedEntry = Fixtures.validationEntrypoint(
    entrypointId: 'ep-2',
    label: 'Recommended smoke',
    type: 'smoke',
    blockingLevel: 'recommended',
    enabled: true,
  );
  final triggered = Fixtures.validationRunV2(
    runId: 'run-1',
    entrypointId: 'ep-1',
    state: 'queued',
    summary: 'queued',
  );
  final readiness = Fixtures.demoReadiness(
    overallState: 'ready',
    summary: 'All clear on main.',
    recentRunIds: const ['run-old'],
  );
  return {
    'app_contract_version': '1.0',
    'responses': {
      'app.hello': {'ok': true, 'result': <String, dynamic>{}},
      'app.readiness': {'ok': true, 'result': Fixtures.readinessResult()},
      'app.validation.entrypoint.list': {
        'ok': true,
        'result': Fixtures.listResult([requiredEntry, recommendedEntry]),
      },
      'app.validation.run.trigger': {
        'ok': true,
        'result': Fixtures.rowResult(triggered),
      },
      'app.validation.run.cancel': {
        'ok': true,
        'result': Fixtures.rowResult({
          ...triggered,
          'state': 'cancelled',
          'result': 'cancelled',
        }),
      },
      'app.demo_readiness.detail': {
        'ok': true,
        'result': Fixtures.rowResult(readiness),
      },
    },
  };
}
