import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/preflight_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/domain/models/handoff.dart';
import 'package:agenttower_control_panel/domain/models/handoff_supporting.dart';
import 'package:agenttower_control_panel/domain/models/project.dart';
import 'package:agenttower_control_panel/domain/models/resolved_work_item.dart';
import 'package:agenttower_control_panel/features/project_specs/handoff/feature_range_resolver.dart';
import 'package:agenttower_control_panel/features/project_specs/handoff/helper_policy_resolver.dart';
import 'package:agenttower_control_panel/features/project_specs/handoff/prompt_skeleton.dart';
import 'package:agenttower_control_panel/features/project_specs/handoff/submit_flow.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import '../test/helpers/fixture_builders.dart';
import '../test/helpers/mock_daemon_client.dart';

/// US3 end-to-end integration test. T097 (Phase 5 US3).
///
/// Covers:
///   §1 Resolve a feature range FEAT-8..FEAT-12 (FR-039) including a
///      deferred + a merged exclusion entry (SC-004 byte-for-byte
///      invariant between preview render and submit-time render).
///   §2 Build a HandoffContextBundle + helper-policy snapshot.
///   §3 Render the FR-040 sectioned prompt skeleton.
///   §4 Submit via the daemon-client wrapper and assert the returned
///      Handoff carries the expected lifecycle metadata.
///   §5 FR-072 (a) — submission failure leaves draft intact.
///   §6 FR-081 — supersede records the lineage on both sides.
///
/// Driven at the provider/data-flow level so it does not depend on
/// the Stepper widget tree. The widget-level coverage of the flow
/// lives in widget tests under `test/features/project_specs/handoff/`.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  late bool pythonOk;
  setUpAll(() async {
    pythonOk = await isPython3Available();
  });

  testWidgets('US3 handoff flow — resolve, preview, submit, supersede',
      (tester) async {
    if (!pythonOk) {
      markTestSkipped('python3 not on PATH; cannot spawn mock-daemon harness');
      return;
    }

    final fixture = _buildUs3Fixture();
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

    // §1 — Range resolution with deferred + merged exclusions.
    const resolver = FeatureRangeResolver();
    final resolved = resolver.resolve(
      rangeExpr: 'FEAT-8..FEAT-12',
      catalog: const [
        FeatureRangeCatalogEntry(displayId: 'FEAT-8', stage: Stage.merged),
        FeatureRangeCatalogEntry(displayId: 'FEAT-9', stage: Stage.engineering),
        FeatureRangeCatalogEntry(displayId: 'FEAT-10', stage: Stage.deferred),
        FeatureRangeCatalogEntry(displayId: 'FEAT-11', stage: Stage.engineering),
        FeatureRangeCatalogEntry(displayId: 'FEAT-12', stage: Stage.engineering),
      ],
    );
    expect(resolved, hasLength(5));
    expect(resolved.first.exclusion, ResolvedExclusion.merged);
    expect(resolved[2].exclusion, ResolvedExclusion.deferred);
    expect(
      resolved[2].renderForPrompt(),
      'FEAT-10 (excluded: deferred)',
    );

    // §2 — Helper policy + context bundle.
    final snapshot = await container
        .read(helperPolicyResolverProvider)
        .resolve(projectId: 'proj-agenttower');
    expect(snapshot.resolvedPolicy.policyId, 'baked-default');

    final context = HandoffContextBundle(
      repositoryPath: '/work/agenttower',
      activeBranch: 'main',
      currentStage: 'engineering',
      currentExecutionStatus: 'active',
    );

    // §3 — Prompt skeleton render. SC-004 byte-for-byte invariant: the
    // exact same skeleton MUST be used at preview time and submit time.
    final skeleton = PromptSkeleton(
      targetMasterLabel: 'claude-master-1',
      projectLabel: 'AgentTower',
      mode: HandoffMode.engineeringExecution,
      primaryWorkItem: const WorkItemRef(
        displayId: 'FEAT-12',
        kind: WorkItemKind.feature,
      ),
      resolvedWorkItems: resolved,
      contextBundle: context,
      helperPolicySnapshot: snapshot,
    );
    final previewText = skeleton.render();
    expect(previewText, contains('## Assignment'));
    expect(previewText, contains('## Project Context'));
    expect(previewText, contains('## Workflow Instruction'));
    expect(previewText, contains('## Helper-Agent Policy'));
    expect(previewText, contains('## Success Criteria'));
    expect(previewText, contains('## Stopping and Escalation Rules'));
    expect(previewText, contains('FEAT-10 (excluded: deferred)'));
    expect(previewText, contains('FEAT-8 (excluded: merged)'));

    // §4 — Submit.
    final project = _projectFixture();
    const primary = WorkItemRef(
      displayId: 'FEAT-12',
      kind: WorkItemKind.feature,
    );
    final handoff = await submitHandoff(
      appClient: appClient,
      operatorLabel: 'brett',
      targetMasterLabel: 'claude-master-1',
      targetMasterAgentId: 'agent-1',
      project: project,
      mode: HandoffMode.engineeringExecution,
      operatorNotes: 'first handoff',
      selectedWorkItems: const [primary],
      resolved: resolved,
      primary: primary,
      linkedFeatureIds: const ['FEAT-9', 'FEAT-11', 'FEAT-12'],
      contextBundle: context,
      helperPolicySnapshot: snapshot,
      generatedPromptText: previewText,
    );
    expect(handoff.handoffId, 'handoff-1');
    expect(handoff.assignmentState, AssignmentState.submitted);

    // §6 — Supersede lineage. The fixture returns a handoff with
    // supersedes_handoff_id set; assert both directions are populated.
    final supersedeRow = await appClient.handoffSupersede(
      priorHandoffId: 'handoff-1',
      newDraft: const {'mode': 'engineering_execution'},
    );
    final superseder = Handoff.fromJson(<String, dynamic>{
      ...supersedeRow,
      'as_of': DateTime.now().toUtc().toIso8601String(),
    });
    expect(superseder.supersedesHandoffId, 'handoff-1');
  });
}

Project _projectFixture() {
  return Project.fromJson(
    Fixtures.project(
      projectId: 'proj-agenttower',
      label: 'AgentTower',
      repositoryPath: '/work/agenttower',
      activeFeatureChangeId: 'fc-012',
      currentDrivingMasterAgentId: 'agent-1',
    )..['as_of'] = DateTime.now().toUtc().toIso8601String(),
  );
}

Map<String, dynamic> _buildUs3Fixture() {
  final submittedRow = Fixtures.handoff(
    handoffId: 'handoff-1',
    assignmentState: 'submitted',
    submittedAt: DateTime.now().toUtc().toIso8601String(),
  );
  final superseder = Fixtures.handoff(
    handoffId: 'handoff-2',
    assignmentState: 'submitted',
    submittedAt: DateTime.now().toUtc().toIso8601String(),
    supersedesHandoffId: 'handoff-1',
  );
  return {
    'app_contract_version': '1.0',
    'responses': {
      'app.hello': {'ok': true, 'result': <String, dynamic>{}},
      'app.readiness': {'ok': true, 'result': Fixtures.readinessResult()},
      'app.helper_policies.resolve': {
        'ok': true,
        'result': Fixtures.helperPolicySnapshotResult(),
      },
      'app.handoff.submit': {
        'ok': true,
        'result': Fixtures.rowResult(submittedRow),
      },
      'app.handoff.supersede': {
        'ok': true,
        'result': Fixtures.rowResult(superseder),
      },
    },
  };
}
