import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';
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

    final l10n = AppLocalizations.of(context);
    final demoReadinessLabel = l10n.demoReadinessTitle(branch);
    return Scaffold(
      appBar: AppBar(
        title: Text(demoReadinessLabel),
        actions: [
          IconButton(
            tooltip: l10n.commonRefresh,
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(demoReadinessProvider(query)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: demoReadinessLabel,
          onRetry: () => ref.invalidate(demoReadinessProvider(query)),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: demoReadinessLabel,
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
    final l10n = AppLocalizations.of(context);
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
                _formatDowngradeReason(l10n, result),
                style: TextStyle(color: theme.colorScheme.onErrorContainer),
              ),
            ),
          ],
          const SizedBox(height: 16),
          Text(l10n.demoReadinessSectionSummary,
              style: theme.textTheme.titleMedium),
          const SizedBox(height: 4),
          Text(summary.summary),
          const SizedBox(height: 16),
          Text(l10n.demoReadinessSectionBlockingFindings,
              style: theme.textTheme.titleMedium),
          const SizedBox(height: 4),
          if (summary.blockingFindings.isEmpty)
            Text(l10n.commonNone)
          else
            for (final f in summary.blockingFindings)
              ListTile(
                leading: const Icon(Icons.block, size: 18),
                title: Text(f.summary),
                subtitle:
                    Text(l10n.demoReadinessFindingKind(f.kind.wireValue)),
              ),
          const SizedBox(height: 16),
          Text(l10n.demoReadinessSectionRecommendedNext,
              style: theme.textTheme.titleMedium),
          const SizedBox(height: 4),
          if (summary.recommendedNextRuns.isEmpty)
            Text(l10n.commonNone)
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
          Text(l10n.demoReadinessSectionRecentRuns,
              style: theme.textTheme.titleMedium),
          const SizedBox(height: 4),
          if (summary.recentRunIds.isEmpty)
            Text(l10n.commonNone)
          else
            for (final runId in summary.recentRunIds)
              Text('• $runId'),
          const SizedBox(height: 16),
          Text(
            l10n.demoReadinessUpdatedAt(summary.updatedAt.toLocal().toString()),
            style: theme.textTheme.labelSmall,
          ),
        ],
      ),
    );
  }

  /// Picks the singular vs many ARB key for the FR-050 downgrade
  /// banner so plural copy stays correct after future translation.
  static String _formatDowngradeReason(
    AppLocalizations l10n,
    ReadinessRenderResult result,
  ) {
    final labels = result.missingRequiredLabels.join(', ');
    final branch = result.branch ?? '';
    if (result.missingRequiredLabels.length == 1) {
      return l10n.demoReadinessDowngradeReasonOne(labels, branch);
    }
    return l10n.demoReadinessDowngradeReasonMany(
      result.missingRequiredLabels.length,
      labels,
      branch,
    );
  }
}

class _OverallChip extends StatelessWidget {
  const _OverallChip({required this.state});
  final DemoReadinessState state;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    final (color, icon, label) = switch (state) {
      DemoReadinessState.ready => (
          theme.colorScheme.tertiary,
          Icons.check_circle,
          l10n.demoReadinessOverallReady,
        ),
      DemoReadinessState.atRisk => (
          theme.colorScheme.secondary,
          Icons.warning,
          l10n.demoReadinessOverallAtRisk,
        ),
      DemoReadinessState.notReady => (
          theme.colorScheme.error,
          Icons.block,
          l10n.demoReadinessOverallNotReady,
        ),
      DemoReadinessState.unknown => (
          theme.colorScheme.outline,
          Icons.help_outline,
          l10n.demoReadinessOverallUnknown,
        ),
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
            l10n.demoReadinessOverallLabel(label),
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
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Text(
          AppLocalizations.of(context).demoReadinessNoProjectSelected,
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}
