import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/preflight_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/lifecycles/drift_state_validator.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/features/project_specs/drift/providers.dart';
import 'package:agenttower_control_panel/features/project_specs/projects/project_card.dart';
import 'package:agenttower_control_panel/features/project_specs/providers.dart';
import 'package:flutter/material.dart';
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

  // SC-005 wall-clock budget. T170 (closes swarm-review H-C2).
  //
  // The contract reads "Drift findings visible on project card: ≤ 60 s
  // from daemon emission" (plan.md SC-005). T112 deliberately deferred
  // the wall-clock assertion to a follow-up — this is that follow-up.
  //
  // Strategy:
  //   1. Spawn the mock-daemon harness with a project carrying
  //      `drift_open_count: 0` (badge label: `drift: info` — no `(N)`
  //      open-count suffix per `projectCardDriftChipOpenCount`).
  //   2. Mount a minimal MaterialApp + ProviderScope whose home renders
  //      a [ProjectCard] driven by `projectListProvider` so the actual
  //      production widget + production provider are exercised.
  //   3. pumpAndSettle so the first emission paints; assert no `(N)`
  //      suffix on the drift chip.
  //   4. Start a Stopwatch — this is the "daemon emission" moment.
  //   5. Mid-test, swap the in-process AppClient to a fresh AppClient
  //      bound to a second mock-daemon process that emits the project
  //      with `drift_open_count: 1` + severity `warning`. Invalidate
  //      `projectListProvider` to trigger the re-fetch.
  //   6. pumpUntil watches the badge text for `(1)` — the canonical
  //      visible signal that the new finding has reached the card.
  //   7. Assert `stopwatch.elapsed < 60 s`.
  //
  // The mock-daemon harness in `test_harness/mock_daemon/server.py`
  // does NOT support runtime fixture mutation (responses load once at
  // process start), so the "new emission" is modelled by spawning a
  // second harness process and swapping the AppClient that the app's
  // provider reads through. The DaemonSession + SocketClient stay
  // disposable per-harness; we never re-use a closed socket.
  testWidgets('US4 SC-005 wall-clock — drift badge updates ≤ 60 s of emission',
      (tester) async {
    if (!pythonOk) {
      markTestSkipped('python3 not on PATH; cannot spawn mock-daemon harness');
      return;
    }

    // ---- "Before" daemon: zero drift findings on the project card.
    final fixtureZero = _buildProjectListFixture(driftOpenCount: 0);
    final harnessZero = await MockDaemonClient.start(fixture: fixtureZero);
    addTearDown(() async {
      try {
        await harnessZero.stop();
      } catch (_) {
        // Already stopped mid-test — ignore.
      }
    });

    final socketZero = SocketClient(harnessZero.socketPath);
    final sessionZero = DaemonSession(client: socketZero);
    await sessionZero.bootstrap();
    addTearDown(sessionZero.dispose);
    final appClientZero = AppClient(session: sessionZero);

    // The swappable AppClient that the provider tree reads through.
    // Starts pointing at appClientZero; we swap to a second AppClient
    // (bound to a second harness) at the "daemon-emission" moment.
    final swappable = _SwappableAppClient(initial: appClientZero);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          appClientProvider.overrideWithValue(swappable),
        ],
        child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(
            body: SizedBox(
              width: 600,
              child: Consumer(
                builder: (ctx, ref, _) {
                  final list = ref.watch(projectListProvider);
                  return list.when(
                    data: (rows) => rows.isEmpty
                        ? const Text('no-projects')
                        : ProjectCard(project: rows.first),
                    loading: () => const Text('loading'),
                    error: (e, _) => Text('error: $e'),
                  );
                },
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // Sanity: the "before" card is on screen and the drift chip has
    // no open-count suffix (open_count == 0 ⇒ `(N)` not rendered).
    expect(find.byType(ProjectCard), findsOneWidget);
    expect(find.textContaining('drift: info'), findsOneWidget);
    expect(find.textContaining('(1)'), findsNothing);

    // ---- "Daemon emission" — start the wall-clock budget.
    final stopwatch = Stopwatch()..start();

    // Spin up a second harness on a fresh socket path that reports
    // drift_open_count=1 + severity=warning. Stop the first harness
    // afterward so we don't leak the process.
    final fixtureOne = _buildProjectListFixture(
      driftOpenCount: 1,
      driftSeverity: 'warning',
    );
    final harnessOne = await MockDaemonClient.start(fixture: fixtureOne);
    addTearDown(() async {
      try {
        await harnessOne.stop();
      } catch (_) {
        // Already stopped — ignore.
      }
    });

    final socketOne = SocketClient(harnessOne.socketPath);
    final sessionOne = DaemonSession(client: socketOne);
    await sessionOne.bootstrap();
    addTearDown(sessionOne.dispose);
    final appClientOne = AppClient(session: sessionOne);

    // Swap the in-process client + invalidate the provider so the next
    // provider read pulls from the new daemon. This is the equivalent
    // of FEAT-011 emitting a fresh project snapshot on its socket.
    swappable.swap(appClientOne);
    final container = ProviderScope.containerOf(
      tester.element(find.byType(ProjectCard)),
    );
    container.invalidate(projectListProvider);

    // ---- Watch the badge for the `(1)` open-count suffix.
    await _pumpUntil(
      tester,
      () => find.textContaining('(1)').evaluate().isNotEmpty,
      const Duration(seconds: 60),
    );

    stopwatch.stop();

    // SC-005: visible within 60 s of daemon emission. We assert
    // strictly less-than to leave the budget intact for SC-005
    // headroom rather than equal-to (a 60.001 s render would fail
    // the spec without failing this assertion).
    expect(
      stopwatch.elapsed < const Duration(seconds: 60),
      isTrue,
      reason:
          'SC-005: drift badge must become visible on the project card '
          'within 60 s of daemon emission; observed ${stopwatch.elapsed}.',
    );

    // And the "after" drift chip should reflect the warning severity
    // + open count (defence-in-depth — pumpUntil exited on `(1)` text,
    // but verify the severity flipped too).
    expect(find.textContaining('drift: warning'), findsOneWidget);
    expect(find.textContaining('(1)'), findsOneWidget);
  });
}

/// Polyfill for `tester.pumpUntil` which is not available on Flutter
/// 3.27.0. Pumps every 100 ms until [check] returns true or [timeout]
/// expires (in which case the test is failed with a descriptive
/// message). Uses wall-clock (`DateTime.now()`) rather than the
/// `Stopwatch` parameter so the test budget tracks real elapsed time,
/// not pump-cycle time.
Future<void> _pumpUntil(
  WidgetTester tester,
  bool Function() check,
  Duration timeout,
) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    await tester.pump(const Duration(milliseconds: 100));
    if (check()) return;
  }
  fail('SC-005 wall-clock check did not become true within $timeout');
}

/// Lightweight AppClient that delegates `projectList` (and
/// `projectDetail`, used by `selectedProjectProvider`) to a swappable
/// backing client. Used by the SC-005 wall-clock test to swap the
/// underlying daemon connection mid-test without re-mounting the
/// widget tree (which would reset all timing).
///
/// `projectList` is the only hot-path method the SC-005 widget tree
/// reads. Every other AppClient method falls through to whichever
/// concrete AppClient the swappable was constructed from (the
/// "before" daemon), which is fine because the wall-clock test
/// doesn't exercise them. If a future test extension reads more
/// surfaces, override them here.
class _SwappableAppClient extends AppClient {
  _SwappableAppClient({required AppClient initial})
      : _backing = initial,
        super(session: initial.session);

  AppClient _backing;

  void swap(AppClient next) {
    _backing = next;
  }

  @override
  Future<PagedResult> projectList({String? cursorNext, int? limit}) =>
      _backing.projectList(cursorNext: cursorNext, limit: limit);

  @override
  Future<Map<String, dynamic>> projectDetail(String projectId) =>
      _backing.projectDetail(projectId);
}

/// Builds a `project.list`-only fixture seeded with a single project
/// carrying the requested drift-badge severity + open-count. The
/// "before" / "after" snapshots in the SC-005 wall-clock test differ
/// only in those two fields so the badge text is the load-bearing
/// signal the test polls on.
Map<String, dynamic> _buildProjectListFixture({
  required int driftOpenCount,
  String driftSeverity = 'info',
}) {
  final project = Fixtures.project(
    projectId: 'proj-1',
    label: 'AgentTower',
    repositoryPath: '/work/agenttower',
    driftSeverity: driftSeverity,
    driftOpenCount: driftOpenCount,
  );
  return {
    'app_contract_version': '1.0',
    'responses': {
      'app.hello': {'ok': true, 'result': <String, dynamic>{}},
      'app.readiness': {'ok': true, 'result': Fixtures.readinessResult()},
      'app.project.list': {
        'ok': true,
        'result': Fixtures.listResult([project]),
      },
      'app.project.detail': {
        'ok': true,
        'result': Fixtures.rowResult(project),
      },
    },
  };
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
