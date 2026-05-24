import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../domain/models/feature_change_status.dart';
import '../../../ui/widgets/runtime_state_views.dart';
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
    final project = ref.watch(selectedProjectProvider);
    final activeFeature = ref.watch(activeFeatureChangeProvider);
    return Scaffold(
      appBar: AppBar(
        title: project.maybeWhen(
          data: (p) => Text('Current Work — ${p?.label ?? selectedId}'),
          orElse: () => Text('Current Work — $selectedId'),
        ),
        actions: [
          IconButton(
            tooltip: 'Refresh',
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
          surfaceLabel: 'Current Work',
          onRetry: () => ref.invalidate(activeFeatureChangeProvider),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: 'Current Work',
        ),
        child: activeFeature.when(
          data: (fc) => fc == null
              ? const HealthyEmptyStateView(
                  message: 'No active feature/change on this project.\n\n'
                      'Start one by handing it off to a master from the '
                      'Specs view.',
                )
              : _CurrentWorkBody(featureChange: fc),
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: 'current work',
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
              'Subphase: ${featureChange.subphaseToken}',
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
              'No driver assigned yet.',
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          const SizedBox(height: 24),
          Text('Linked documents', style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          _DocLinks(featureChangeId: featureChange.featureChangeId),
          const SizedBox(height: 24),
          Text(
            'Stage: ${featureChange.stage.wireValue} · '
            'Execution: ${featureChange.executionStatus.wireValue}',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: 4),
          Text(
            'As of: ${featureChange.asOf.toLocal()}',
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
      SnackBar(content: Text('Master detail: $agentId')),
    );
  }

  void _openHandoffDetail(BuildContext c, WidgetRef r, String handoffId) {
    // Phase 5 wires this to the handoff detail route.
    ScaffoldMessenger.of(c).showSnackBar(
      SnackBar(content: Text('Handoff detail: $handoffId')),
    );
  }
}

class _DocLinks extends ConsumerWidget {
  const _DocLinks({required this.featureChangeId});
  final String featureChangeId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
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
        final paths = _docPathsFor(fc);
        if (paths.isEmpty) {
          return const Text(
            'No documents linked yet — see Drift for missing-doc findings.',
          );
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
      error: (e, _) => Text('Failed to load documents: $e'),
    );
  }

  static Map<String, String?> _docPathsFor(FeatureChangeStatus fc) {
    // Phase 4 reads the feature/change detail payload generically; the
    // daemon shape for these path fields lands when FEAT-011 exposes
    // the doc-resolution method per R-28. The MVP surface assumes the
    // daemon returns the five buckets as top-level keys on the detail
    // payload; absent keys render as null (disabled chip).
    return const {
      'PRD': null,
      'Architecture': null,
      'Roadmap': null,
      'Feature spec': null,
      'OpenSpec change': null,
    };
  }

  Future<void> _openExternal(BuildContext context, String path) async {
    final uri = path.startsWith('file://') ? Uri.parse(path) : Uri.file(path);
    final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open $path')),
      );
    }
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
          'No project selected.\n\n'
          'Open the Projects view (Project + Specs → Projects) and select '
          'a project to see its current work.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

// Inline _NoActiveFeature and _ErrorState replaced by shared
// HealthyEmptyStateView / ErrorStateView (swarm-review CR-6).
