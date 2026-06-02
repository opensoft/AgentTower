import 'package:agenttower_control_panel/core/daemon/app_client.dart';
import 'package:agenttower_control_panel/core/daemon/session.dart';
import 'package:agenttower_control_panel/core/daemon/socket_client.dart';
import 'package:agenttower_control_panel/core/providers.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/features/agent_ops/dashboard/dashboard_view.dart';
import 'package:agenttower_control_panel/features/shell/runtime_state_provider.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/fixture_builders.dart';
import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';

/// Widget tests for [DashboardView] (FR-012 + FR-004). T164 — Phase 3 US1.
///
/// Three scenarios:
///   (a) runtime-unreachable → OutageState ("Daemon unreachable")
///   (b) reachable + all-zero counts → tiles render with "0" values
///   (c) reachable + populated counts → each visible tile renders the
///       contract-shaped count (FR-012's pane-by-state + recommended
///       next-action tiles are deliberately suppressed pending
///       openspec/extend-app-dashboard-fields-for-feat012)
void main() {
  group('DashboardView', () {
    testWidgets('runtime-unreachable renders OutageState with Retry button',
        (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(_FakeAppClient()),
            runtimeStateProvider.overrideWith(
              () => _StubRuntimeNotifier(
                const RuntimeState(
                  kind: RuntimeStateKind.runtimeUnreachable,
                  lastError: 'connection refused',
                ),
              ),
            ),
          ],
          child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: DashboardView())),
        ),
      );
      await tester.pump();
      expect(find.text('Daemon unreachable'), findsOneWidget);
      expect(find.byIcon(Icons.cloud_off_outlined), findsOneWidget);
      expect(
        find.ancestor(of: find.text('Retry connection'), matching: find.bySubtype<FilledButton>()),
        findsOneWidget,
      );
      // Outage-state never shows the per-section tiles.
      expect(find.text('Containers'), findsNothing);
    });

    testWidgets('reachable + all-zero counts renders empty tiles',
        (tester) async {
      // DashboardView is a lazy ListView: the lower sections ("Log
      // attachments", "Events + Queue + Routes") fall outside the default
      // 800x600 test viewport and are not built. Give the test a tall
      // surface so every section is materialized for the finders.
      tester.view.physicalSize = const Size(1200, 3200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      final fake = _FakeAppClient(
        dashboardResult: Fixtures.dashboardResult(
          containersActive: 0,
          panesTotal: 0,
          panesRegistered: 0,
          panesUnregistered: 0,
        ),
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(fake),
            runtimeStateProvider.overrideWith(
              () => _StubRuntimeNotifier(
                const RuntimeState(
                  kind: RuntimeStateKind.runtimeHealthyEmpty,
                  daemonVersion: '0.1.0',
                ),
              ),
            ),
          ],
          child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: DashboardView())),
        ),
      );
      // Resolve FutureProvider.
      await tester.pump();
      await tester.pump();

      expect(find.text('Containers'), findsOneWidget);
      expect(find.text('Panes'), findsOneWidget);
      expect(find.text('Agents'), findsOneWidget);
      expect(find.text('Log attachments'), findsOneWidget);
      expect(find.text('Events + Queue + Routes'), findsOneWidget);
      expect(find.text('Daemon'), findsOneWidget);
      // Daemon version surfaced from the stubbed runtime state.
      expect(find.text('0.1.0'), findsOneWidget);
    });

    testWidgets('populated counts render the per-section stat values',
        (tester) async {
      // Tall surface so the lazy ListView builds the below-the-fold
      // "Events + Queue + Routes" section (see sibling test).
      tester.view.physicalSize = const Size(1200, 3200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      final fake = _FakeAppClient(
        dashboardResult: Fixtures.dashboardResult(
          containersActive: 3,
          panesTotal: 12,
          panesRegistered: 7,
          panesUnregistered: 5,
          agentsTotal: 4,
          agentsByRole: const {
            'master': 2,
            'slave': 2,
          },
          logAttachmentsActive: 4,
          eventsTotal: 99,
          queueQueued: 1,
          queueBlocked: 2,
          queueDelivered: 50,
          routesEnabled: 3,
          routesDisabled: 1,
        ),
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            appClientProvider.overrideWithValue(fake),
            runtimeStateProvider.overrideWith(
              () => _StubRuntimeNotifier(
                const RuntimeState(
                  kind: RuntimeStateKind.runtimeHealthyPopulated,
                ),
              ),
            ),
          ],
          child: MaterialApp(
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          supportedLocales: AppLocalizations.supportedLocales,
          home: Scaffold(body: DashboardView())),
        ),
      );
      await tester.pump();
      await tester.pump();

      // Section header
      expect(find.text('Events + Queue + Routes'), findsOneWidget);

      // Populated stat values from the contract-shaped payload.
      expect(find.text('3'), findsWidgets); // containers.active
      expect(find.text('12'), findsOneWidget); // panes.total
      expect(find.text('7'), findsOneWidget); // panes.registered
      expect(find.text('99'), findsOneWidget); // events.total
      expect(find.text('50'), findsOneWidget); // queue.delivered

      // By-role tiles render verbatim from agents.by_role map.
      expect(find.text('By role · master'), findsOneWidget);
      expect(find.text('By role · slave'), findsOneWidget);
    });
  });
}

class _StubRuntimeNotifier extends RuntimeStateNotifier {
  _StubRuntimeNotifier(this._state);
  final RuntimeState _state;
  @override
  RuntimeState build() => _state;
}

class _FakeAppClient extends AppClient {
  _FakeAppClient({Map<String, dynamic>? dashboardResult})
      : _dashboardResult = dashboardResult ?? Fixtures.dashboardResult(),
        super(
          session: DaemonSession(
            client: SocketClient('/nonexistent/never-bound.sock'),
          ),
        );

  final Map<String, dynamic> _dashboardResult;

  @override
  Future<Map<String, dynamic>> dashboard({int recentLimit = 10}) async =>
      _dashboardResult;
}
