import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/common_enums.dart';
import '../../../domain/models/demo_readiness_summary.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import '../../project_specs/providers.dart' as project_providers;
import '../providers.dart';
import 'readiness_computation.dart';

/// FR-050 — Demo Readiness view. T128 (Phase 7 US5).
///
/// Renders the overall state + summary + blocking findings list +
/// recommended next runs + recent run references. Updates within 5 s
/// of a run resolving per SC-007 (the daemon owns the recompute;
/// the UI re-fetches on demand and via the Refresh action).
///
/// **Defensive invariant (FR-050)**: `enforceRequiredInvariant`
/// re-checks the overall state against the locally-known
/// entrypoints + recent runs and downgrades `ready` to `at_risk`
/// when a required entrypoint hasn't run on the current branch.
/// Banner copy explains the downgrade inline so the operator knows
/// the daemon and the UI disagree (likely degraded daemon path).
class DemoReadinessView extends ConsumerWidget {
  const DemoReadinessView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedId = ref.watch(project_providers.selectedProjectIdProvider);
    if (selectedId == null) return const _NoProjectSelected();
    // For MVP the operator targets the project's active branch; richer
    // branch selection lands when the project model carries
    // workingBranches per a follow-up.
    final project = ref.watch(project_providers.selectedProjectProvider);
    final branch = project.maybeWhen(
          data: (p) => p?.activeBranch.branchName,
          orElse: () => null,
        ) ??
        'main';
    final query = DemoReadinessQuery(projectId: selectedId, branch: branch);
    final summary = ref.watch(demoReadinessProvider(query));

    return Scaffold(
      appBar: AppBar(
        title: Text('Demo Readiness — $branch'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(demoReadinessProvider(query)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: 'Demo Readiness',
          onRetry: () => ref.invalidate(demoReadinessProvider(query)),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: 'Demo Readiness',
        ),
        child: summary.when(
          data: (s) => _Body(
            summary: s,
            projectId: selectedId,
          ),
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: 'demo readiness',
            onRetry: () => ref.invalidate(demoReadinessProvider(query)),
          ),
        ),
      ),
    );
  }
}

class _Body extends ConsumerWidget {
  const _Body({required this.summary, required this.projectId});
  final DemoReadinessSummary summary;
  final String projectId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    // FR-050 invariant: re-check the daemon's overallState against
    // the locally-known entrypoints + runs and downgrade if needed.
    final entrypoints = ref
            .watch(validationEntrypointListProvider(
              EntrypointListQuery(projectId: projectId),
            ))
            .valueOrNull ??
        const [];
    final runs = ref
            .watch(validationRunListProvider(
              RunListQuery(projectId: projectId, branch: summary.branch),
            ))
            .valueOrNull ??
        const [];
    final result = enforceRequiredInvariant(
      summary: summary,
      entrypoints: entrypoints,
      recentRuns: runs,
    );

    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _OverallChip(state: result.effectiveState),
          if (result.wasDowngraded) ...[
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: theme.colorScheme.errorContainer,
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                result.downgradeReason!,
                style: TextStyle(color: theme.colorScheme.onErrorContainer),
              ),
            ),
          ],
          const SizedBox(height: 16),
          Text('Summary', style: theme.textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(summary.summary),
          const SizedBox(height: 16),
          Text('Blocking findings', style: theme.textTheme.titleMedium),
          const SizedBox(height: 4),
          if (summary.blockingFindings.isEmpty)
            const Text('None.')
          else
            for (final f in summary.blockingFindings)
              ListTile(
                leading: const Icon(Icons.block, size: 18),
                title: Text(f.summary),
                subtitle: Text('kind: ${f.kind.wireValue}'),
              ),
          const SizedBox(height: 16),
          Text('Recommended next runs', style: theme.textTheme.titleMedium),
          const SizedBox(height: 4),
          if (summary.recommendedNextRuns.isEmpty)
            const Text('None.')
          else
            for (final r in summary.recommendedNextRuns)
              ListTile(
                leading: Icon(
                  r.priority ? Icons.priority_high : Icons.arrow_forward,
                  size: 18,
                ),
                title: Text(r.entrypointLabel),
                subtitle: Text(r.reason),
              ),
          const SizedBox(height: 16),
          Text('Recent runs', style: theme.textTheme.titleMedium),
          const SizedBox(height: 4),
          if (summary.recentRunIds.isEmpty)
            const Text('None.')
          else
            for (final runId in summary.recentRunIds)
              Text('• $runId'),
          const SizedBox(height: 16),
          Text(
            'Updated: ${summary.updatedAt.toLocal()}',
            style: theme.textTheme.labelSmall,
          ),
        ],
      ),
    );
  }
}

class _OverallChip extends StatelessWidget {
  const _OverallChip({required this.state});
  final DemoReadinessState state;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final (color, icon, label) = switch (state) {
      DemoReadinessState.ready => (theme.colorScheme.tertiary, Icons.check_circle, 'Ready'),
      DemoReadinessState.atRisk => (theme.colorScheme.secondary, Icons.warning, 'At risk'),
      DemoReadinessState.notReady => (theme.colorScheme.error, Icons.block, 'Not ready'),
      DemoReadinessState.unknown => (theme.colorScheme.outline, Icons.help_outline, 'Unknown'),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 8),
          Text(
            'Overall: $label',
            style: TextStyle(color: color, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

class _NoProjectSelected extends StatelessWidget {
  const _NoProjectSelected();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Padding(
        padding: EdgeInsets.all(32),
        child: Text(
          'No project selected.\n\nPick a project from the Projects view '
          'to see its demo readiness.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}
