import 'package:agenttower_control_panel/domain/models/badges.dart';
import 'package:agenttower_control_panel/domain/models/common_enums.dart';
import 'package:agenttower_control_panel/domain/models/project.dart';
import 'package:agenttower_control_panel/features/project_specs/projects/project_card.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// Widget tests for [ProjectCard]. T150 (Phase 9 cross-cutting widget tests).
///
/// Covers the four master-strip variants required by FR-025:
///   - zero masters → "No driving master" placeholder
///   - one master  → single id in the strip
///   - two masters → both ids visible (full strip, no overflow marker)
///   - three+      → first two visible + "+N" overflow indicator
///
/// `ProjectCard` is a plain [StatelessWidget] that takes a [Project] directly
/// (no Riverpod consumption inside the widget itself). We still wrap the
/// pump in a [ProviderScope] with [appClientProvider] stubbed so that any
/// future provider lookup added by the widget does not panic on the
/// `_unwired` default.
void main() {
  group('ProjectCard master-strip variants (FR-025)', () {
    testWidgets('renders zero-masters card with "No driving master" '
        'placeholder', (tester) async {
      final project = _buildProject(
        primaryMasterAgentIds: const [],
        masterOverflowCount: 0,
        currentDrivingMasterAgentId: null,
      );

      await _pump(tester, project);

      // Card renders without error.
      expect(find.byType(ProjectCard), findsOneWidget);
      // Driving-master row falls back to the no-driver placeholder.
      expect(find.text('No driving master'), findsOneWidget);
      // No master id strings should leak in.
      expect(find.textContaining('Masters:'), findsNothing);
      expect(find.textContaining('(+'), findsNothing);
    });

    testWidgets('renders one-master card with the master id visible',
        (tester) async {
      final project = _buildProject(
        primaryMasterAgentIds: const ['agent-alpha'],
        masterOverflowCount: 0,
        currentDrivingMasterAgentId: 'agent-alpha',
        activeFeatureChangeId: 'FEAT-042',
      );

      await _pump(tester, project);

      expect(find.byType(ProjectCard), findsOneWidget);
      // Canonical driver-sentence path renders when both driver +
      // activeFeatureChangeId are present (see _drivingMasterRow).
      expect(
        find.textContaining('agent-alpha is driving FEAT-042'),
        findsOneWidget,
      );
      // No overflow indicator at count==1.
      expect(find.textContaining('(+'), findsNothing);
    });

    testWidgets('renders two-masters card with both ids visible and no '
        'overflow indicator (full strip)', (tester) async {
      final project = _buildProject(
        primaryMasterAgentIds: const ['agent-alpha', 'agent-beta'],
        masterOverflowCount: 0,
        // Drop driver so the "Masters: …" branch renders (canonical
        // sentence path suppresses it when driver+feature both set).
        currentDrivingMasterAgentId: null,
        activeFeatureChangeId: null,
      );

      await _pump(tester, project);

      expect(find.byType(ProjectCard), findsOneWidget);
      // Both visible master labels are joined with ", " into one Text.
      expect(
        find.textContaining('Masters: agent-alpha, agent-beta'),
        findsOneWidget,
      );
      // No overflow indicator at count==2 with overflow==0.
      expect(find.textContaining('(+'), findsNothing);
    });

    testWidgets('renders three+ masters card with "+N" overflow indicator',
        (tester) async {
      // Daemon caps `primaryMasterAgentIds` at 2 (data-model §1.1 / F-A7);
      // additional masters surface via `masterOverflowCount`.
      final project = _buildProject(
        primaryMasterAgentIds: const ['agent-alpha', 'agent-beta'],
        masterOverflowCount: 3,
        currentDrivingMasterAgentId: null,
        activeFeatureChangeId: null,
      );

      await _pump(tester, project);

      expect(find.byType(ProjectCard), findsOneWidget);
      // Visible ids still rendered.
      expect(
        find.textContaining('agent-alpha, agent-beta'),
        findsOneWidget,
      );
      // "+3" overflow indicator matches `masterOverflowCount`.
      expect(find.textContaining('(+3)'), findsOneWidget);
    });
  });
}

/// Pumps the card under a [ProviderScope] + [MaterialApp] so themed
/// chips have a `Theme.of(context)` lookup target. [ProjectCard] is
/// itself a plain [StatelessWidget] and does not consume any Riverpod
/// provider, so no overrides are needed; the scope is kept so the
/// pump shape matches the project-wide widget-test convention.
Future<void> _pump(WidgetTester tester, Project project) async {
  await tester.pumpWidget(
    ProviderScope(
      child: MaterialApp(
        home: Scaffold(
          body: SizedBox(
            // Bound the card so Wrap-based badge row has a real width.
            width: 600,
            child: ProjectCard(project: project),
          ),
        ),
      ),
    ),
  );
}

/// Builds a [Project] with sensible defaults; only master-strip-relevant
/// fields are exposed as parameters.
Project _buildProject({
  required List<String> primaryMasterAgentIds,
  required int masterOverflowCount,
  String? currentDrivingMasterAgentId,
  String? activeFeatureChangeId,
}) {
  final now = DateTime.utc(2026, 1, 1, 12);
  return Project(
    projectId: 'proj-1',
    label: 'AgentTower',
    repositoryPath: '/work/agenttower',
    repoState: const RepoStateBadge(kind: RepoStateKind.clean),
    activeBranch: const BranchWorktreeBadge(branchName: 'main'),
    activeFeatureChangeId: activeFeatureChangeId,
    currentDrivingMasterAgentId: currentDrivingMasterAgentId,
    primaryMasterAgentIds: primaryMasterAgentIds,
    masterOverflowCount: masterOverflowCount,
    subAgentCount: 0,
    validationBadge: const ValidationBadge(kind: ValidationBadgeKind.unknown),
    driftBadge: const DriftBadge(highestSeverity: DriftSeverity.info),
    attentionSummary:
        const AttentionSummary(highestSeverity: AttentionSeverity.info),
    lastActivityAt: now,
    asOf: now,
  );
}

