import 'dart:io';

import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/persistence/compatibility.dart';
import 'package:agenttower_control_panel/core/persistence/paths.dart';
import 'package:agenttower_control_panel/core/persistence/ux_state_repository.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/features/agent_ops/providers.dart';
import 'package:agenttower_control_panel/features/onboarding/onboarding_provider.dart';
import 'package:agenttower_control_panel/features/shell/runtime_state_provider.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
// ignore: depend_on_referenced_packages
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';
// ignore: depend_on_referenced_packages
import 'package:plugin_platform_interface/plugin_platform_interface.dart';

import '../test/helpers/fixture_builders.dart';

/// FR-010 onboarding-milestone auto-tick regression test. T163.
///
/// Each of the 8 [OnboardingMilestone]s has an automatically-detectable
/// completion criterion (per FR-010 + F11). [OnboardingProgressNotifier]
/// (`lib/features/onboarding/onboarding_provider.dart`) `ref.watch`es
/// the provider that drives each criterion and merges newly-satisfied
/// milestones into the persisted set.
///
/// Post-Phase-3 review fix C9 corrected a `ref.watch` wiring bug; the
/// post-Phase-3 analyze finding M2 then asked for a regression test so
/// the wiring cannot silently regress. This file is that regression
/// test.
///
/// ## Mock-daemon strategy: provider overrides, not the Python harness
///
/// `test_harness/mock_daemon/server.py` + `README.md` (§Fixture format)
/// document the harness as **static**: the fixture file is loaded once
/// at start and there is no `app.agent.register_from_pane` /
/// `app.send_input` / `app.route.add` mutation that mutates subsequent
/// `.list` reads. To exercise the 8-step walk against the real harness
/// we would need to either (a) restart the Python process 16 times
/// (before + after each milestone) or (b) plumb mutation support into
/// the harness — both outside this task's scope.
///
/// Instead, this test exercises the **provider-watch wiring** directly:
/// the providers `OnboardingProgressNotifier` watches
/// (`containerListProvider`, `paneListProvider`, `agentListProvider`,
/// `queueListProvider`, `routeListProvider`, `runtimeStateProvider`)
/// are overridden with controllable fakes; a per-milestone ProviderScope
/// flips the trigger condition between two pumps and asserts the
/// notifier responds. This is closer to a unit test of the wiring than
/// a full-stack integration test, but it directly targets M2's concern
/// (silent regression of `ref.watch`) and avoids the harness's
/// static-fixture limitation. The full-stack walk lives in
/// `us1_adopt_and_operate.dart` (T054).
///
/// ## Structure: 8 separate testWidgets cases
///
/// The 8-case shape is easier to debug than one long walking case — if
/// a single milestone regresses the failing test name pinpoints it
/// without forcing the reader to count through a serialised walk.
/// Per-case isolation also gives each milestone a fresh
/// [UxStateRepository] + fresh `ProviderScope`, so cross-milestone
/// state leaks cannot mask a wiring bug.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  late Directory tmp;
  late AppPaths paths;

  setUp(() async {
    tmp = Directory.systemTemp.createTempSync('feat012-onboarding-autotick-');
    PathProviderPlatform.instance = _StubPathProvider(tmp.path);
    AppPaths.resetForTesting();
    paths = await AppPaths.initialize();
  });

  tearDown(() {
    AppPaths.resetForTesting();
    if (tmp.existsSync()) {
      tmp.deleteSync(recursive: true);
    }
  });

  // ----------------------------------------------------------------
  // Milestone 1: daemonReachable — runtime kind ∈ {healthy-empty,
  // healthy-populated, degraded}.
  // ----------------------------------------------------------------
  testWidgets('M1 daemonReachable auto-ticks when runtime kind becomes healthy',
      (tester) async {
    final repo = _freshUxStateRepository(paths);
    final harness = _Harness();

    // Before: runtime is unreachable.
    harness.runtimeKind = RuntimeStateKind.runtimeUnreachable;

    await tester.pumpWidget(_buildScope(repo, harness));
    await tester.pump();

    final container = ProviderScope.containerOf(
      tester.element(find.byKey(_probeKey)),
    );

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.daemonReachable,
          ),
      isFalse,
      reason: 'daemonReachable must NOT auto-tick while runtime is unreachable',
    );

    // After: flip runtime to healthy-empty and invalidate so the
    // notifier re-runs build().
    harness.runtimeKind = RuntimeStateKind.runtimeHealthyEmpty;
    container.invalidate(runtimeStateProvider);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.daemonReachable,
          ),
      isTrue,
      reason:
          'daemonReachable must auto-tick once runtime reaches healthy state',
    );
  });

  // ----------------------------------------------------------------
  // Milestone 2: benchContainerCheck — containerListProvider ≥ 1 row.
  // Preceding milestones satisfied: daemonReachable.
  // ----------------------------------------------------------------
  testWidgets('M2 benchContainerCheck auto-ticks when containers list non-empty',
      (tester) async {
    final repo = _freshUxStateRepository(paths);
    final harness = _Harness()
      ..runtimeKind = RuntimeStateKind.runtimeHealthyEmpty
      ..containers = const []; // preceding M1 satisfied; M2 not yet.

    await tester.pumpWidget(_buildScope(repo, harness));
    await tester.pump();
    final container = ProviderScope.containerOf(
      tester.element(find.byKey(_probeKey)),
    );
    // Settle the FutureProvider.
    await container.read(containerListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.benchContainerCheck,
          ),
      isFalse,
      reason: 'benchContainerCheck must NOT tick while containerList is empty',
    );

    harness.containers = const [_FakeContainer()];
    container.invalidate(containerListProvider);
    await container.read(containerListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.benchContainerCheck,
          ),
      isTrue,
      reason:
          'benchContainerCheck must auto-tick after containerList has ≥1 row',
    );
  });

  // ----------------------------------------------------------------
  // Milestone 3: paneDiscoveryCheck — paneListProvider ≥ 1 row.
  // Preceding milestones satisfied: M1, M2.
  // ----------------------------------------------------------------
  testWidgets(
      'M3 paneDiscoveryCheck auto-ticks when pane list becomes non-empty',
      (tester) async {
    final repo = _freshUxStateRepository(paths);
    final harness = _Harness()
      ..runtimeKind = RuntimeStateKind.runtimeHealthyPopulated
      ..containers = const [_FakeContainer()]
      ..panes = const [];

    await tester.pumpWidget(_buildScope(repo, harness));
    await tester.pump();
    final container = ProviderScope.containerOf(
      tester.element(find.byKey(_probeKey)),
    );
    await container.read(containerListProvider.future);
    await container.read(paneListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.paneDiscoveryCheck,
          ),
      isFalse,
      reason: 'paneDiscoveryCheck must NOT tick while pane list is empty',
    );

    harness.panes = const [
      _FakePane(state: PaneState.discoveredAndUnmanaged),
    ];
    container.invalidate(paneListProvider);
    await container.read(paneListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.paneDiscoveryCheck,
          ),
      isTrue,
      reason: 'paneDiscoveryCheck must auto-tick after pane list has ≥1 row '
          'with state != discovery-degraded',
    );
  });

  // ----------------------------------------------------------------
  // Milestone 4: firstPaneAdoption — any pane.state ==
  // discoveredAndRegistered. Preceding: M1, M2, M3.
  // ----------------------------------------------------------------
  testWidgets(
      'M4 firstPaneAdoption auto-ticks when a pane reaches '
      'discoveredAndRegistered', (tester) async {
    final repo = _freshUxStateRepository(paths);
    final harness = _Harness()
      ..runtimeKind = RuntimeStateKind.runtimeHealthyPopulated
      ..containers = const [_FakeContainer()]
      ..panes = const [
        _FakePane(state: PaneState.discoveredAndUnmanaged),
      ];

    await tester.pumpWidget(_buildScope(repo, harness));
    await tester.pump();
    final container = ProviderScope.containerOf(
      tester.element(find.byKey(_probeKey)),
    );
    await container.read(paneListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.firstPaneAdoption,
          ),
      isFalse,
      reason: 'firstPaneAdoption must NOT tick while no pane is registered',
    );

    harness.panes = const [
      _FakePane(state: PaneState.discoveredAndRegistered),
    ];
    container.invalidate(paneListProvider);
    await container.read(paneListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.firstPaneAdoption,
          ),
      isTrue,
      reason:
          'firstPaneAdoption must auto-tick once any pane is registered',
    );
  });

  // ----------------------------------------------------------------
  // Milestone 5: firstAgentRegistration — agentListProvider ≥ 1 row.
  // Preceding: M1-M4.
  // ----------------------------------------------------------------
  testWidgets(
      'M5 firstAgentRegistration auto-ticks when agent list becomes non-empty',
      (tester) async {
    final repo = _freshUxStateRepository(paths);
    final harness = _Harness()
      ..runtimeKind = RuntimeStateKind.runtimeHealthyPopulated
      ..containers = const [_FakeContainer()]
      ..panes = const [
        _FakePane(state: PaneState.discoveredAndRegistered),
      ]
      ..agents = const [];

    await tester.pumpWidget(_buildScope(repo, harness));
    await tester.pump();
    final container = ProviderScope.containerOf(
      tester.element(find.byKey(_probeKey)),
    );
    await container.read(agentListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.firstAgentRegistration,
          ),
      isFalse,
      reason: 'firstAgentRegistration must NOT tick while agent list is empty',
    );

    harness.agents = const [
      _FakeAgent(logAttachment: LogAttachmentState.detached),
    ];
    container.invalidate(agentListProvider);
    await container.read(agentListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.firstAgentRegistration,
          ),
      isTrue,
      reason:
          'firstAgentRegistration must auto-tick after agent list has ≥1 row',
    );
  });

  // ----------------------------------------------------------------
  // Milestone 6: firstLogAttachment — any agent.logAttachment == active.
  // Preceding: M1-M5.
  // ----------------------------------------------------------------
  testWidgets(
      'M6 firstLogAttachment auto-ticks when an agent reaches '
      'logAttachment=active', (tester) async {
    final repo = _freshUxStateRepository(paths);
    final harness = _Harness()
      ..runtimeKind = RuntimeStateKind.runtimeHealthyPopulated
      ..containers = const [_FakeContainer()]
      ..panes = const [
        _FakePane(state: PaneState.discoveredAndRegistered),
      ]
      ..agents = const [
        _FakeAgent(logAttachment: LogAttachmentState.detached),
      ];

    await tester.pumpWidget(_buildScope(repo, harness));
    await tester.pump();
    final container = ProviderScope.containerOf(
      tester.element(find.byKey(_probeKey)),
    );
    await container.read(agentListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.firstLogAttachment,
          ),
      isFalse,
      reason: 'firstLogAttachment must NOT tick while no agent has '
          'logAttachment=active',
    );

    harness.agents = const [
      _FakeAgent(logAttachment: LogAttachmentState.active),
    ];
    container.invalidate(agentListProvider);
    await container.read(agentListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.firstLogAttachment,
          ),
      isTrue,
      reason: 'firstLogAttachment must auto-tick once an agent has '
          'logAttachment=active',
    );
  });

  // ----------------------------------------------------------------
  // Milestone 7: firstDirectSend — queueListProvider ≥ 1 row.
  // Preceding: M1-M6.
  // ----------------------------------------------------------------
  testWidgets(
      'M7 firstDirectSend auto-ticks when queue list becomes non-empty',
      (tester) async {
    final repo = _freshUxStateRepository(paths);
    final harness = _Harness()
      ..runtimeKind = RuntimeStateKind.runtimeHealthyPopulated
      ..containers = const [_FakeContainer()]
      ..panes = const [
        _FakePane(state: PaneState.discoveredAndRegistered),
      ]
      ..agents = const [
        _FakeAgent(logAttachment: LogAttachmentState.active),
      ]
      ..queueRows = const [];

    await tester.pumpWidget(_buildScope(repo, harness));
    await tester.pump();
    final container = ProviderScope.containerOf(
      tester.element(find.byKey(_probeKey)),
    );
    await container.read(queueListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.firstDirectSend,
          ),
      isFalse,
      reason: 'firstDirectSend must NOT tick while queue list is empty',
    );

    harness.queueRows = const [_FakeQueueRow()];
    container.invalidate(queueListProvider);
    await container.read(queueListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.firstDirectSend,
          ),
      isTrue,
      reason: 'firstDirectSend must auto-tick after queue list has ≥1 row',
    );
  });

  // ----------------------------------------------------------------
  // Milestone 8: firstRouteCreation — routeListProvider ≥ 1 row.
  // Preceding: M1-M7.
  // ----------------------------------------------------------------
  testWidgets(
      'M8 firstRouteCreation auto-ticks when route list becomes non-empty',
      (tester) async {
    final repo = _freshUxStateRepository(paths);
    final harness = _Harness()
      ..runtimeKind = RuntimeStateKind.runtimeHealthyPopulated
      ..containers = const [_FakeContainer()]
      ..panes = const [
        _FakePane(state: PaneState.discoveredAndRegistered),
      ]
      ..agents = const [
        _FakeAgent(logAttachment: LogAttachmentState.active),
      ]
      ..queueRows = const [_FakeQueueRow()]
      ..routes = const [];

    await tester.pumpWidget(_buildScope(repo, harness));
    await tester.pump();
    final container = ProviderScope.containerOf(
      tester.element(find.byKey(_probeKey)),
    );
    await container.read(routeListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.firstRouteCreation,
          ),
      isFalse,
      reason: 'firstRouteCreation must NOT tick while route list is empty',
    );

    harness.routes = const [_FakeRoute()];
    container.invalidate(routeListProvider);
    await container.read(routeListProvider.future);
    await tester.pump();

    expect(
      container.read(onboardingProgressProvider).contains(
            OnboardingMilestone.firstRouteCreation,
          ),
      isTrue,
      reason: 'firstRouteCreation must auto-tick after route list has ≥1 row',
    );
  });
}

// ======================================================================
// Test harness — provider overrides + minimal widget tree.
// ======================================================================

const Key _probeKey = Key('onboarding-autotick-probe');

UxStateRepository _freshUxStateRepository(AppPaths paths) =>
    UxStateRepository(
      paths: paths,
      compatibility: const LaunchCompatibility(
        currentAppMajor: 0,
        currentContractMajor: 1,
      ),
    );

/// Builds a ProviderScope whose [appClientProvider], runtime state, and
/// [uxStateRepositoryProvider] are all driven by [harness]. A single
/// `Container` child (keyed via [_probeKey]) gives the test access to
/// `ProviderScope.containerOf` for direct `read` / `invalidate` calls.
Widget _buildScope(UxStateRepository repo, _Harness harness) {
  return ProviderScope(
    overrides: [
      uxStateRepositoryProvider.overrideWithValue(repo),
      appClientProvider.overrideWithValue(harness.appClient),
      runtimeStateProvider.overrideWith(
        () => _StubRuntimeNotifier(harness),
      ),
    ],
    child: const MaterialApp(
      home: Scaffold(
        body: SizedBox(key: _probeKey),
      ),
    ),
  );
}

/// Mutable bag of per-milestone fake daemon state. Tests assign field
/// values BEFORE calling `tester.pump()` so the next `ref.watch` cycle
/// observes the new shape.
class _Harness {
  RuntimeStateKind runtimeKind = RuntimeStateKind.runtimeUnreachable;
  List<_FakeContainer> containers = const [];
  List<_FakePane> panes = const [];
  List<_FakeAgent> agents = const [];
  List<_FakeQueueRow> queueRows = const [];
  List<_FakeRoute> routes = const [];

  late final AppClient appClient = _FakeAppClient(this);
}

/// Replays whatever `runtimeKind` the harness currently advertises. The
/// notifier's `build()` reads from [_Harness] so the test can flip the
/// kind between pumps and `container.invalidate(runtimeStateProvider)`
/// will produce the updated state on the next read.
class _StubRuntimeNotifier extends RuntimeStateNotifier {
  _StubRuntimeNotifier(this.harness);
  final _Harness harness;
  @override
  RuntimeState build() => RuntimeState(kind: harness.runtimeKind);
}

/// AppClient stub that only implements the methods the onboarding
/// notifier's watched providers reach: containerList, paneList,
/// agentList, queueList, routeList. Other methods inherit AppClient's
/// real implementations but are unreachable through this test because
/// the session is bound to a never-existing socket — any inadvertent
/// call surfaces as a connection-refused error rather than a silent
/// pass, which is the failure mode we want.
class _FakeAppClient extends AppClient {
  _FakeAppClient(this.harness)
      : super(
          session: DaemonSession(
            client: SocketClient('/nonexistent/never-bound.sock'),
          ),
        );

  final _Harness harness;

  @override
  Future<PagedResult> containerList({String? cursorNext, int? limit}) async {
    return PagedResult(
      items: harness.containers.map((c) => c.toJson()).toList(growable: false),
      cursorNext: null,
      total: harness.containers.length,
      ordering: 'default',
    );
  }

  @override
  Future<PagedResult> paneList({String? cursorNext, int? limit}) async {
    return PagedResult(
      items: harness.panes.map((p) => p.toJson()).toList(growable: false),
      cursorNext: null,
      total: harness.panes.length,
      ordering: 'default',
    );
  }

  @override
  Future<PagedResult> agentList({
    String? cursorNext,
    int? limit,
    String? role,
    String? capability,
    String? containerId,
    bool? logAttached,
  }) async {
    return PagedResult(
      items: harness.agents.map((a) => a.toJson()).toList(growable: false),
      cursorNext: null,
      total: harness.agents.length,
      ordering: 'default',
    );
  }

  @override
  Future<PagedResult> queueList({String? cursorNext, int? limit}) async {
    return PagedResult(
      items: harness.queueRows.map((q) => q.toJson()).toList(growable: false),
      cursorNext: null,
      total: harness.queueRows.length,
      ordering: 'default',
    );
  }

  @override
  Future<PagedResult> routeList({String? cursorNext, int? limit}) async {
    return PagedResult(
      items: harness.routes.map((r) => r.toJson()).toList(growable: false),
      cursorNext: null,
      total: harness.routes.length,
      ordering: 'default',
    );
  }
}

// ----------------------------------------------------------------------
// Compact const-friendly fixtures. The full FEAT-011 wire-shape builders
// in `test/helpers/fixture_builders.dart` are non-const (they call
// `DateTime.now()` for the `discovered_at` / `last_seen_at` /
// `last_meaningful_activity_at` / `created_at` defaults), which would
// force every per-milestone fixture instance to be built at test
// runtime. The thin `_Fake*` classes below mirror the minimum fields
// the freezed models require to parse — the rest pick up sensible
// defaults from the fixture builders at `toJson()` time so this file
// stays grep-friendly.
// ----------------------------------------------------------------------

class _FakeContainer {
  const _FakeContainer();
  Map<String, dynamic> toJson() => Fixtures.container();
}

class _FakePane {
  const _FakePane({this.state = PaneState.discoveredAndUnmanaged});
  final PaneState state;
  Map<String, dynamic> toJson() => Fixtures.pane(state: state);
}

class _FakeAgent {
  const _FakeAgent({this.logAttachment = LogAttachmentState.detached});
  final LogAttachmentState logAttachment;
  Map<String, dynamic> toJson() {
    // The freezed AdoptedAgent has a `log_attachment` field driven by
    // wire data; the Fixtures.agent() builder doesn't expose it
    // directly so we splice it in here. The freezed model defaults
    // log_attachment to LogAttachmentState.detached when absent, so
    // the explicit splice is what makes the M6 transition observable.
    final base = Fixtures.agent();
    return {
      ...base,
      'log_attachment': logAttachment.wireValue,
    };
  }
}

class _FakeQueueRow {
  const _FakeQueueRow();
  Map<String, dynamic> toJson() => Fixtures.queueRow();
}

class _FakeRoute {
  const _FakeRoute();
  Map<String, dynamic> toJson() => Fixtures.route();
}

/// Per-test path_provider stub. Mirrors `test/core/ux_state/persistence_test.dart`.
class _StubPathProvider extends PathProviderPlatform
    with MockPlatformInterfaceMixin {
  _StubPathProvider(this.support);
  final String support;

  @override
  Future<String?> getApplicationSupportPath() async => support;
}
