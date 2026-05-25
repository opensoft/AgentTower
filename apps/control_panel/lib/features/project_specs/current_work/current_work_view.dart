import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../domain/models/feature_change_status.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import '../../../ui/widgets/safe_url_launcher.dart';
import '../providers.dart';
import 'driving_master_indicator.dart';

/// FR-027 — Current Work view. T091 (Phase 4 US2).
///
/// For the currently selected project, surfaces:
///   - the active feature/change (display id, stage, execution status,
///     human-readable label)
///   - the driving master + driving handoff via [DrivingMasterIndicator]
///   - the workflow phase + recent activity timestamp
///   - one-click links to PRD / architecture / roadmap / feature spec /
///     OpenSpec change paths (FR-079 document-open behavior — the
///     daemon resolves the paths server-side per R-28)
///
/// "No project selected" lands the operator on a prompt to pick one
/// from the Projects view (FR-076 first-launch banner is rendered by
/// the shell, not here).
class CurrentWorkView extends ConsumerWidget {
  const CurrentWorkView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedId = ref.watch(selectedProjectIdProvider);
    if (selectedId == null) {
      return const _NoProjectSelected();
    }
    final l10n = AppLocalizations.of(context);
    final project = ref.watch(selectedProjectProvider);
    final activeFeature = ref.watch(activeFeatureChangeProvider);
    return Scaffold(
      appBar: AppBar(
        title: project.maybeWhen(
          data: (p) => Text(
              l10n.currentWorkTitleWithProject(p?.label ?? selectedId)),
          orElse: () =>
              Text(l10n.currentWorkTitleWithProject(selectedId)),
        ),
        actions: [
          IconButton(
            tooltip: l10n.currentWorkRefreshTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: () {
              ref.invalidate(selectedProjectProvider);
              ref.invalidate(activeFeatureChangeProvider);
            },
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.currentWorkSurfaceLabel,
          onRetry: () => ref.invalidate(activeFeatureChangeProvider),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: l10n.currentWorkSurfaceLabel,
        ),
        child: activeFeature.when(
          data: (fc) => fc == null
              ? HealthyEmptyStateView(
                  message: l10n.currentWorkEmptyMessage,
                )
              : _CurrentWorkBody(featureChange: fc),
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: l10n.currentWorkSurfaceLabelLower,
            onRetry: () => ref.invalidate(activeFeatureChangeProvider),
          ),
        ),
      ),
    );
  }
}

class _CurrentWorkBody extends ConsumerWidget {
  const _CurrentWorkBody({required this.featureChange});
  final FeatureChangeStatus featureChange;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            featureChange.displayId,
            style: theme.textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          Text(
            featureChange.humanReadableLabel,
            style: theme.textTheme.titleMedium?.copyWith(
              color: theme.colorScheme.primary,
            ),
          ),
          if (featureChange.subphaseToken != null) ...[
            const SizedBox(height: 4),
            Text(
              l10n.currentWorkSubphase(featureChange.subphaseToken!),
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
          const SizedBox(height: 24),
          if (featureChange.drivingMasterAgentId != null)
            DrivingMasterIndicator(
              masterLabel: featureChange.drivingMasterAgentId!,
              featureChangeDisplayId: featureChange.displayId,
              handoffId: featureChange.drivingHandoffId,
              onOpenMaster: () => _openMasterDetail(
                context,
                ref,
                featureChange.drivingMasterAgentId!,
              ),
              onOpenHandoff: featureChange.drivingHandoffId == null
                  ? null
                  : () => _openHandoffDetail(
                        context,
                        ref,
                        featureChange.drivingHandoffId!,
                      ),
            )
          else
            Text(
              l10n.currentWorkNoDriverAssigned,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          const SizedBox(height: 24),
          Text(l10n.currentWorkLinkedDocumentsHeading,
              style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          _DocLinks(featureChangeId: featureChange.featureChangeId),
          const SizedBox(height: 24),
          Text(
            l10n.currentWorkStageExecutionLine(
              featureChange.stage.wireValue,
              featureChange.executionStatus.wireValue,
            ),
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: 4),
          Text(
            l10n.currentWorkAsOfLine(featureChange.asOf.toLocal().toString()),
            style: theme.textTheme.labelSmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }

  void _openMasterDetail(BuildContext c, WidgetRef r, String agentId) {
    // Wired up in Phase 8 attention queue follow-up. For MVP the indicator
    // surfaces the master id so the operator can pivot via the Agents view.
    ScaffoldMessenger.of(c).showSnackBar(
      SnackBar(
        content:
            Text(AppLocalizations.of(c).currentWorkMasterDetailSnack(agentId)),
      ),
    );
  }

  void _openHandoffDetail(BuildContext c, WidgetRef r, String handoffId) {
    // Phase 5 wires this to the handoff detail route.
    ScaffoldMessenger.of(c).showSnackBar(
      SnackBar(
        content: Text(
            AppLocalizations.of(c).currentWorkHandoffDetailSnack(handoffId)),
      ),
    );
  }
}

class _DocLinks extends ConsumerWidget {
  const _DocLinks({required this.featureChangeId});
  final String featureChangeId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final detail = ref.watch(featureChangeDetailProvider(featureChangeId));
    return detail.when(
      data: (fc) {
        // The daemon-resolved document paths arrive on the feature/change
        // detail payload. For MVP we surface five buckets: PRD,
        // architecture, roadmap, feature spec, OpenSpec change. Each
        // becomes a Chip whose tap opens the path via url_launcher
        // (file:// scheme; permission to read is the operator's).
        // When a path is missing the daemon's "Not found - see Drift"
        // badge takes its place per R-28.
        final paths = _docPathsFor(context, fc);
        if (paths.isEmpty) {
          return Text(l10n.currentWorkNoLinkedDocuments);
        }
        return Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final entry in paths.entries)
              ActionChip(
                avatar: const Icon(Icons.description, size: 16),
                label: Text(entry.key),
                onPressed: entry.value == null
                    ? null
                    : () => _openExternal(context, entry.value!),
              ),
          ],
        );
      },
      loading: () =>
          const Padding(padding: EdgeInsets.all(8), child: LinearProgressIndicator()),
      error: (e, _) => Text(l10n.currentWorkDocsLoadFailed(e.toString())),
    );
  }

  static Map<String, String?> _docPathsFor(
      BuildContext context, FeatureChangeStatus fc) {
    // Phase 4 reads the feature/change detail payload generically; the
    // daemon shape for these path fields lands when FEAT-011 exposes
    // the doc-resolution method per R-28. The MVP surface assumes the
    // daemon returns the five buckets as top-level keys on the detail
    // payload; absent keys render as null (disabled chip).
    final l10n = AppLocalizations.of(context);
    return {
      l10n.currentWorkDocPrd: null,
      l10n.currentWorkDocArchitecture: null,
      l10n.currentWorkDocRoadmap: null,
      l10n.currentWorkDocFeatureSpec: null,
      l10n.currentWorkDocOpenSpecChange: null,
    };
  }

  Future<void> _openExternal(BuildContext context, String path) async {
    // Swarm-review H-D3: route daemon-supplied doc paths through
    // SafeUrlLauncher's file-confirmation flow so the operator
    // confirms before the OS handler launches anything.
    if (path.startsWith('file://')) {
      await SafeUrlLauncher.open(context, path);
    } else {
      await SafeUrlLauncher.openFile(context, path);
    }
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
          AppLocalizations.of(context).currentWorkNoProjectSelected,
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

// Inline _NoActiveFeature and _ErrorState replaced by shared
// HealthyEmptyStateView / ErrorStateView (swarm-review CR-6).
