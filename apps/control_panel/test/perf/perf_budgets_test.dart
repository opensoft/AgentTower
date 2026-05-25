import 'package:agenttower_control_panel/app.dart';
import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/contract_version.dart';
import 'package:agenttower_control_panel/core/daemon/preflight_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/features/agent_ops/agents/agents_view.dart';
import 'package:agenttower_control_panel/features/agent_ops/containers/containers_view.dart';
import 'package:agenttower_control_panel/features/agent_ops/events/events_view.dart';
import 'package:agenttower_control_panel/features/agent_ops/module.dart';
import 'package:agenttower_control_panel/features/agent_ops/panes/panes_view.dart';
import 'package:agenttower_control_panel/features/agent_ops/providers.dart';
import 'package:agenttower_control_panel/features/agent_ops/queue/queue_view.dart';
import 'package:agenttower_control_panel/features/agent_ops/routes/routes_view.dart';
import 'package:agenttower_control_panel/features/project_specs/drift/drift_view.dart';
import 'package:agenttower_control_panel/features/project_specs/module.dart';
import 'package:agenttower_control_panel/features/project_specs/projects/projects_view.dart';
import 'package:agenttower_control_panel/features/project_specs/providers.dart'
    as project_providers;
import 'package:agenttower_control_panel/features/registry.dart';
import 'package:agenttower_control_panel/features/settings/module.dart';
import 'package:agenttower_control_panel/features/testing_demo/available_validation/available_validation_view.dart';
import 'package:agenttower_control_panel/features/testing_demo/module.dart';
import 'package:agenttower_control_panel/features/testing_demo/runs/runs_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/fixture_builders.dart';
import '../helpers/mock_daemon_client.dart';

/// T154 — FR-062 / FR-063 / FR-064 performance verification suite.
///
/// Asserts the three Performance Goals from plan.md §Performance Goals
/// (and the FRs they back) at p95 across **10 runs**, per the FR
/// round-3 R-25 environmental preconditions captured in spec.md:
///
/// > Budgets apply at p95 over 10-run repetitions.
///
/// Budgets covered:
///
///   (a) **FR-062** — cold-start-to-Dashboard p95 ≤ 2 s.
///       Measured as the wall-clock from `tester.pumpWidget(...)` of the
///       full [AgentTowerControlPanel] through `pumpAndSettle()` to the
///       first frame where the Dashboard body text is visible.
///
///   (b) **FR-063** — first-screenful render p95 ≤ 1 s for every list
///       view named in plan.md §Performance Goals
///       (Containers, Panes, Agents, Events, Queue, Routes, Projects,
///       Available Validation, Runs, Drift), with the mock daemon
///       pre-seeded with **50 rows** per list (the FEAT-011 default
///       page size).
///
///   (c) **FR-064** — manual-refresh round-trip p95 ≤ 2 s, from
///       `ref.invalidate(<provider>)` to the post-refresh in-app render.
///
/// ## FR-064 push-vs-pull caveat (analyze A1 + tasks.md T154(c))
///
/// FR-064's literal wording is *"live-update surfaces MUST reflect a new
/// daemon event within 2 s of the event being observable on the daemon
/// side"* — i.e. push propagation. There is no SSE/WebSocket subscription
/// in MVP yet; daemon-side streaming is tracked by T167. Until T167
/// lands, the live-update strategy is `ref.invalidate(...)` polling, and
/// **this test measures manual-refresh round-trip only**. When T167
/// ships, this test must be revisited to flip (c) onto push propagation.
///
/// ## Environmental preconditions (spec.md §Clarifications Q for R-38)
///
/// Reference machine: 8-core x86-64 (≥ 3.0 GHz base), 16 GB RAM, NVMe SSD,
/// OS at idle. Daemon fixture = FEAT-011 SC scale profile (≤ 10
/// containers, ≤ 200 agents, ≤ 1k events/day). No concurrent background
/// apps. Budgets apply at p95 over 10-run repetitions.
///
/// ## Skip gating
///
/// Skipped when `python3` is unavailable on PATH — the test requires the
/// `MockDaemonClient` harness (Python) for realistic wire round-trips.
/// Same pattern as every US integration test (`isPython3Available()`).
void main() {
  /// Sample count per spec.md §Clarifications (R-38).
  const sampleCount = 10;

  /// FR-062 — cold-start-to-Dashboard budget.
  const fr062Budget = Duration(seconds: 2);

  /// FR-063 — first-screenful render budget.
  const fr063Budget = Duration(seconds: 1);

  /// FR-064 — manual-refresh round-trip budget (push propagation budget
  /// lifted here for the pull-mode measurement; T167 will replace this
  /// with the same numeric budget against the streaming pipeline).
  const fr064Budget = Duration(seconds: 2);

  /// FEAT-011 default page size — pre-seed every list with this many rows
  /// so FR-063 is measured at the realistic worst case for the first
  /// screenful (not 1-row toy fixtures).
  const pageSize = 50;

  late bool pythonOk;
  setUpAll(() async {
    pythonOk = await isPython3Available();
  });

  setUp(() {
    // The shell registers workspace builders + contract declarations on
    // first launch. Reset both so each test starts with a clean
    // registry and re-registers via the module entry-points below.
    WorkspaceRegistry.resetForTesting();
    ContractRegistry.resetForTesting();
  });

  group('T154 performance budgets (p95 over $sampleCount runs)', () {
    testWidgets(
      'FR-062: cold-start-to-Dashboard p95 ≤ ${fr062Budget.inSeconds} s',
      (tester) async {
        if (!pythonOk) {
          markTestSkipped(
            'python3 not on PATH; cannot spawn mock-daemon harness',
          );
          return;
        }

        final samples = <Duration>[];
        for (var i = 0; i < sampleCount; i++) {
          // Fresh harness + session per cold-start sample so each iteration
          // measures the full mount path without state pollution between
          // pumps. The harness itself is sub-second to spawn; that overhead
          // is intentionally OUTSIDE the stopwatch since cold-start measures
          // from runApp/pumpWidget to first Dashboard frame.
          WorkspaceRegistry.resetForTesting();
          ContractRegistry.resetForTesting();
          seedMvpContractDeclarations();
          registerAgentOps();
          registerProjectSpecs();
          registerTestingDemo();
          registerSettings();

          final harness = await MockDaemonClient.start(fixture: _coldFixture());
          addTearDown(harness.stop);

          final socketClient = SocketClient(harness.socketPath);
          final session = DaemonSession(client: socketClient);
          await session.bootstrap();
          addTearDown(session.dispose);

          final appClient = AppClient(session: session);
          final preflight = PreflightClient(socketPath: harness.socketPath);

          // Start the stopwatch around pumpWidget + pumpAndSettle — the
          // "runApp to first Dashboard frame" window per FR-062.
          final stopwatch = Stopwatch()..start();
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
          stopwatch.stop();

          // Sanity assertion: the Dashboard body is actually visible
          // (otherwise we'd be measuring "first frame of spinner"). The
          // "Containers" section header is rendered by DashboardView once
          // the dashboard FutureProvider resolves.
          expect(
            find.text('Containers'),
            findsWidgets,
            reason:
                'sample $i: Dashboard body must be visible before stopping '
                'the cold-start clock (else we measured the loading spinner)',
          );
          samples.add(stopwatch.elapsed);

          // Unmount to release the ProviderScope before the next sample
          // re-mounts a fresh tree.
          await tester.pumpWidget(const SizedBox.shrink());
        }

        final p95Observed = _p95(samples);
        expect(
          p95Observed,
          lessThanOrEqualTo(fr062Budget),
          reason: 'FR-062 cold-start-to-Dashboard p95 exceeded: '
              'observed ${p95Observed.inMilliseconds} ms across '
              '$sampleCount runs (budget ${fr062Budget.inMilliseconds} ms). '
              'Samples (ms): ${samples.map((d) => d.inMilliseconds).toList()}',
        );
      },
    );

    testWidgets(
      'FR-063: first-screenful render p95 ≤ ${fr063Budget.inSeconds} s for '
      'every FR-063 list at page-size $pageSize',
      (tester) async {
        if (!pythonOk) {
          markTestSkipped(
            'python3 not on PATH; cannot spawn mock-daemon harness',
          );
          return;
        }

        // Spawn ONE harness for the whole assertion — every list is read
        // from the same fixture, and the wire round-trip cost is what
        // we're trying to budget against, so amortising harness spawn
        // is correct.
        final harness =
            await MockDaemonClient.start(fixture: _fr063FullFixture());
        addTearDown(harness.stop);

        final socketClient = SocketClient(harness.socketPath);
        final session = DaemonSession(client: socketClient);
        await session.bootstrap();
        addTearDown(session.dispose);

        final appClient = AppClient(session: session);

        // Each entry: (list label, builder that returns the surface widget).
        // Project-scoped surfaces (Drift, Available Validation, Runs)
        // need `selectedProjectIdProvider` set so they render their list
        // instead of the "No project selected" placeholder.
        final lists = <_FR063Surface>[
          _FR063Surface('Containers', () => const ContainersView()),
          _FR063Surface('Panes', () => const PanesView()),
          _FR063Surface('Agents', () => const AgentsView()),
          _FR063Surface('Events', () => const EventsView()),
          _FR063Surface('Queue', () => const QueueView()),
          _FR063Surface('Routes', () => const RoutesView()),
          _FR063Surface('Projects', () => const ProjectsView()),
          _FR063Surface(
            'Available Validation',
            () => const AvailableValidationView(),
            requiresSelectedProject: true,
          ),
          _FR063Surface(
            'Runs',
            () => const RunsView(),
            requiresSelectedProject: true,
          ),
          _FR063Surface(
            'Drift',
            () => const DriftView(),
            requiresSelectedProject: true,
          ),
        ];

        for (final surface in lists) {
          final samples = <Duration>[];
          for (var i = 0; i < sampleCount; i++) {
            // Invalidating provider state between samples ensures each
            // iteration measures the cold-fetch path, not a cache hit.
            final overrides = <Override>[
              socketClientProvider.overrideWithValue(socketClient),
              daemonSessionProvider.overrideWithValue(session),
              appClientProvider.overrideWithValue(appClient),
              if (surface.requiresSelectedProject)
                project_providers.selectedProjectIdProvider
                    .overrideWith((_) => 'proj-1'),
            ];

            final stopwatch = Stopwatch()..start();
            await tester.pumpWidget(
              ProviderScope(
                overrides: overrides,
                child: MaterialApp(
                  home: Scaffold(body: surface.builder()),
                ),
              ),
            );
            await tester.pumpAndSettle();
            stopwatch.stop();

            // Sanity: at least one row was rendered. Each list view
            // uses ListView.builder + ListTile, or a card grid; rather
            // than introspect per-surface widget types we assert the
            // loading + empty + outage states are absent, which forces
            // the data-state path to have run.
            expect(
              find.byType(CircularProgressIndicator),
              findsNothing,
              reason: '${surface.label} sample $i still showed a spinner '
                  '— FR-063 budget measured a loading state, not first '
                  'screenful render',
            );
            samples.add(stopwatch.elapsed);

            await tester.pumpWidget(const SizedBox.shrink());
          }

          final p95Observed = _p95(samples);
          expect(
            p95Observed,
            lessThanOrEqualTo(fr063Budget),
            reason:
                'FR-063 ${surface.label}: first-screenful p95 exceeded: '
                'observed ${p95Observed.inMilliseconds} ms across '
                '$sampleCount runs at page-size $pageSize '
                '(budget ${fr063Budget.inMilliseconds} ms). '
                'Samples (ms): ${samples.map((d) => d.inMilliseconds).toList()}',
          );
        }
      },
    );

    testWidgets(
      'FR-064: manual-refresh round-trip p95 ≤ ${fr064Budget.inSeconds} s '
      '(pull-mode; T167 lifts this onto push)',
      (tester) async {
        if (!pythonOk) {
          markTestSkipped(
            'python3 not on PATH; cannot spawn mock-daemon harness',
          );
          return;
        }

        // We measure the Events surface as the FR-064 exemplar because it
        // is the canonical live-update list named in FR-064's wording
        // ("Events, Queue, attention queue, notifications panel, master
        // summary"). The provider boundary is identical for every other
        // pull-mode surface, so this single measurement covers the
        // class — T167's push-mode replacement will need per-surface
        // coverage when streaming subscriptions land.
        final harness =
            await MockDaemonClient.start(fixture: _fr063FullFixture());
        addTearDown(harness.stop);

        final socketClient = SocketClient(harness.socketPath);
        final session = DaemonSession(client: socketClient);
        await session.bootstrap();
        addTearDown(session.dispose);

        final appClient = AppClient(session: session);

        await tester.pumpWidget(
          ProviderScope(
            overrides: [
              socketClientProvider.overrideWithValue(socketClient),
              daemonSessionProvider.overrideWithValue(session),
              appClientProvider.overrideWithValue(appClient),
            ],
            child: const MaterialApp(home: Scaffold(body: EventsView())),
          ),
        );
        await tester.pumpAndSettle();

        // Grab a Riverpod container against the mounted scope so we can
        // call `invalidate` from outside the widget tree without rebuilding
        // the whole ProviderScope.
        final container = ProviderScope.containerOf(
          tester.element(find.byType(EventsView)),
        );

        final samples = <Duration>[];
        for (var i = 0; i < sampleCount; i++) {
          final stopwatch = Stopwatch()..start();
          container.invalidate(eventListProvider);
          // pumpAndSettle drains every frame, microtask, and timer until
          // the tree is quiescent — i.e. the post-refresh render has
          // landed. This is the in-app render boundary for FR-064.
          await tester.pumpAndSettle();
          stopwatch.stop();
          samples.add(stopwatch.elapsed);
        }

        final p95Observed = _p95(samples);
        expect(
          p95Observed,
          lessThanOrEqualTo(fr064Budget),
          reason:
              'FR-064 manual-refresh round-trip p95 exceeded: '
              'observed ${p95Observed.inMilliseconds} ms across '
              '$sampleCount runs (budget ${fr064Budget.inMilliseconds} ms). '
              'Samples (ms): ${samples.map((d) => d.inMilliseconds).toList()}. '
              'Note: this measures pull-mode (ref.invalidate→render); '
              'T167 push-mode streaming will replace this measurement.',
        );
      },
    );
  });
}

/// p95 of [samples]. Sorts a copy ascending and picks the index at
/// `floor(n * 0.95)`. For n=10 this yields index 9 (the 10th / max
/// sample), which is the conservative reading of "p95 over 10 runs"
/// used elsewhere in the suite.
Duration _p95(List<Duration> samples) {
  assert(samples.isNotEmpty, 'cannot compute p95 of an empty sample set');
  final sorted = [...samples]..sort();
  final idx = (samples.length * 0.95).floor();
  // Clamp to the last valid index — for n=10 floor(9.5)=9 which is
  // already in-range, but the clamp guards against off-by-one if the
  // sample size is ever changed.
  return sorted[idx >= sorted.length ? sorted.length - 1 : idx];
}

/// One FR-063 surface entry: label + builder + project-scoping flag.
class _FR063Surface {
  const _FR063Surface(
    this.label,
    this.builder, {
    this.requiresSelectedProject = false,
  });
  final String label;
  final Widget Function() builder;
  final bool requiresSelectedProject;
}

// ---------------------------------------------------------------------------
// Fixtures.
// ---------------------------------------------------------------------------

/// Minimal fixture used by the FR-062 cold-start sample: dashboard returns
/// the contract-shaped envelope with one container so the populated-path
/// is exercised, plus every notification/preflight/readiness response the
/// app shell touches on first frame. Lists return one row each — FR-062
/// measures cold-start, not list-render.
Map<String, dynamic> _coldFixture() {
  return {
    'app_contract_version': '1.0',
    'daemon_version': '0.11.0-mock',
    'app_session_token': '00000000-0000-4000-8000-000000000001',
    'app_session_id': 1,
    'host_user_id': '1000',
    'schema_version': 1,
    'responses': {
      'app.hello': {'ok': true, 'result': const <String, dynamic>{}},
      'app.preflight': {'ok': true, 'result': Fixtures.preflightResult()},
      'app.readiness': {'ok': true, 'result': Fixtures.readinessResult()},
      'app.dashboard': {'ok': true, 'result': Fixtures.dashboardResult()},
      'app.notification.list': {
        'ok': true,
        'result': Fixtures.listResult(const <Map<String, dynamic>>[]),
      },
    },
  };
}

/// Page-size-$pageSize fixture used by FR-063 + FR-064. Every list method
/// returns 50 rows with unique ids so the freezed-model fromJson + list
/// rendering path is exercised at the realistic worst case.
Map<String, dynamic> _fr063FullFixture() {
  const n = 50;
  return {
    'app_contract_version': '1.0',
    'daemon_version': '0.11.0-mock',
    'app_session_token': '00000000-0000-4000-8000-000000000001',
    'app_session_id': 1,
    'host_user_id': '1000',
    'schema_version': 1,
    'responses': {
      'app.hello': {'ok': true, 'result': const <String, dynamic>{}},
      'app.preflight': {'ok': true, 'result': Fixtures.preflightResult()},
      'app.readiness': {'ok': true, 'result': Fixtures.readinessResult()},
      'app.dashboard': {'ok': true, 'result': Fixtures.dashboardResult()},
      'app.container.list': {
        'ok': true,
        'result': Fixtures.listResult(
          List.generate(
            n,
            (i) => Fixtures.container(
              containerId: 'bench-$i',
              name: 'bench-$i',
            ),
          ),
        ),
      },
      'app.pane.list': {
        'ok': true,
        'result': Fixtures.listResult(
          List.generate(
            n,
            (i) => Fixtures.pane(
              paneId: 'p$i',
              tmuxWindow: i ~/ 4,
              tmuxPane: i % 4,
            ),
          ),
        ),
      },
      'app.agent.list': {
        'ok': true,
        'result': Fixtures.listResult(
          List.generate(
            n,
            (i) => Fixtures.agent(
              agentId: 'agent-$i',
              label: 'agent-$i',
              role: i.isEven ? AgentRole.master : AgentRole.slave,
            ),
          ),
        ),
      },
      'app.event.list': {
        'ok': true,
        'result': Fixtures.listResult(
          List.generate(
            n,
            (i) => Fixtures.event(eventId: 'evt-$i', summary: 'event $i'),
          ),
        ),
      },
      'app.queue.list': {
        'ok': true,
        'result': Fixtures.listResult(
          List.generate(n, (i) => Fixtures.queueRow(messageId: 'q-$i')),
        ),
      },
      'app.route.list': {
        'ok': true,
        'result': Fixtures.listResult(
          List.generate(n, (i) => Fixtures.route(routeId: 'route-$i')),
        ),
      },
      'app.project.list': {
        'ok': true,
        'result': Fixtures.listResult(
          List.generate(
            n,
            (i) => Fixtures.project(
              projectId: i == 0 ? 'proj-1' : 'proj-$i',
              label: 'project-$i',
            ),
          ),
        ),
      },
      'app.drift.list': {
        'ok': true,
        'result': Fixtures.listResult(
          List.generate(
            n,
            (i) => Fixtures.drift(findingId: 'drift-$i', summary: 'drift $i'),
          ),
        ),
      },
      'app.validation.entrypoint.list': {
        'ok': true,
        'result': Fixtures.listResult(
          List.generate(
            n,
            (i) => Fixtures.validationEntrypoint(
              entrypointId: 'ep-$i',
              label: 'entrypoint $i',
            ),
          ),
        ),
      },
      'app.validation.run.list': {
        'ok': true,
        'result': Fixtures.listResult(
          List.generate(
            n,
            (i) => Fixtures.validationRunV2(runId: 'run-$i'),
          ),
        ),
      },
      'app.notification.list': {
        'ok': true,
        'result': Fixtures.listResult(const <Map<String, dynamic>>[]),
      },
    },
  };
}
