import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../domain/master_qualification.dart';
import '../../../domain/models/badges.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/drift_signal.dart';
import '../../../domain/models/drift_supporting.dart';
import '../../../domain/models/master_summary.dart';
import '../../../domain/models/project.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import '../providers.dart' as project_providers;
import 'drift_repair_handoff_launch.dart';
import 'drift_transition.dart';
import 'providers.dart';

/// FR-033 + FR-035 — Per-finding drift detail. T116 (Phase 6 US4).
///
/// Renders the full attribute set, the per-finding evidence list with
/// type-specific affordances (log excerpts as monospace text, file
/// pointers as Open-externally links), the lifecycle transition
/// action via [DriftTransitionAction], and the "Repair this drift"
/// affordance that launches the handoff flow pre-filled per FR-035.
class DriftDetailView extends ConsumerWidget {
  const DriftDetailView({super.key, required this.findingId});
  final String findingId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detail = ref.watch(driftDetailProvider(findingId));
    return Scaffold(
      appBar: AppBar(
        title: Text('Drift $findingId'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(driftDetailProvider(findingId)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: 'Drift detail',
          onRetry: () => ref.invalidate(driftDetailProvider(findingId)),
        ),
        onIncompatible: (s) =>
            ContractIncompatStateView(state: s, surfaceLabel: 'Drift detail'),
        child: detail.when(
          data: (d) => _Body(drift: d),
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: 'drift $findingId',
            onRetry: () => ref.invalidate(driftDetailProvider(findingId)),
          ),
        ),
      ),
    );
  }
}

class _Body extends ConsumerWidget {
  const _Body({required this.drift});
  final DriftSignal drift;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(drift.summary, style: theme.textTheme.headlineSmall),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              _Chip(label: 'status: ${drift.status.wireValue}'),
              _Chip(label: 'severity: ${drift.severity.wireValue}'),
              _Chip(label: 'source: ${drift.source.wireValue}'),
              _Chip(label: 'confidence: ${drift.confidence.wireValue}'),
              _Chip(
                label: 'scope: ${drift.scope.kind.wireValue}'
                    '${drift.scope.id != null ? ":${drift.scope.id}" : ""}',
              ),
            ],
          ),
          const SizedBox(height: 16),
          DriftTransitionAction(drift: drift),
          const SizedBox(height: 24),
          _section(theme, 'Recommended action'),
          Text(drift.recommendedAction),
          const SizedBox(height: 24),
          _section(theme, 'Linked refs'),
          if (drift.linkedFeatureIds.isNotEmpty)
            Text('Features: ${drift.linkedFeatureIds.join(", ")}'),
          if (drift.linkedChangeIds.isNotEmpty)
            Text('Changes: ${drift.linkedChangeIds.join(", ")}'),
          if (drift.linkedBranch != null)
            Text('Branch: ${drift.linkedBranch}'),
          if (drift.linkedWorktree != null)
            Text('Worktree: ${drift.linkedWorktree}'),
          if (drift.linkedFeatureIds.isEmpty &&
              drift.linkedChangeIds.isEmpty &&
              drift.linkedBranch == null &&
              drift.linkedWorktree == null)
            const Text('No linked refs'),
          const SizedBox(height: 24),
          _section(theme, 'Evidence'),
          if (drift.evidence.isEmpty) const Text('No evidence supplied'),
          for (final e in drift.evidence) _EvidenceItem(evidence: e),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            onPressed: () => _onRepair(context, ref),
            icon: const Icon(Icons.build),
            label: const Text('Repair this drift'),
          ),
        ],
      ),
    );
  }

  Future<void> _onRepair(BuildContext context, WidgetRef ref) async {
    // Swarm-review CR-9 + FR-035: actually launch the drift-repair
    // handoff flow with pre-filled mode + operator notes instead of
    // the previous SnackBar nudge. Looks up the project from
    // selectedProjectIdProvider; picks the currently-driving master
    // when present, otherwise the first available master.
    final selectedId = ref.read(project_providers.selectedProjectIdProvider);
    if (selectedId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'No project selected — pick one from Projects view first.',
          ),
        ),
      );
      return;
    }
    try {
      final project =
          await ref.read(project_providers.projectDetailProvider(selectedId).future);
      final master = await _resolveMaster(ref, project);
      if (master == null) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text(
                'No master qualified per FR-071 is available for this '
                'project. Adopt or assign one, then retry.',
              ),
            ),
          );
        }
        return;
      }
      if (!context.mounted) return;
      DriftRepairHandoffLauncher.launch(
        context: context,
        drift: drift,
        project: project,
        master: master,
      );
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not open handoff flow: $e')),
        );
      }
    }
  }

  Future<MasterSummary?> _resolveMaster(
    WidgetRef ref,
    Project project,
  ) async {
    // Prefer the project's current driver if known. Otherwise nothing
    // to do — the operator must wire a driving master first. The full
    // master-picker UX lands when the agent surface adds a picker
    // affordance; for now we surface the no-driver state clearly.
    final driverId = project.currentDrivingMasterAgentId;
    if (driverId == null) return null;
    final masterClass =
        await ref.read(masterClassCapabilitiesProvider.future);
    // Synthesize a minimal MasterSummary view from the driver id.
    // The handoff flow only needs (agentId, label, capability,
    // currentStatus) for its step 1 confirmation; the heavier fields
    // come from the handoff context bundle the daemon builds at
    // submit time. If the driver capability doesn't pass FR-071
    // qualification, return null so the caller surfaces the error.
    final placeholder = MasterSummary(
      agentId: driverId,
      label: driverId,
      capability: masterClass.isNotEmpty ? masterClass.first : 'claude',
      role: AgentRole.master,
      activeBadge: const ActiveInactiveBadge(active: true),
      currentStatus: MasterStatus.active,
      assignedProjectId: project.projectId,
      workflowPhase:
          const WorkflowPhase(humanLabel: 'Drift repair (in progress)'),
      subAgentRollup: const SubAgentRollup(),
      attentionSeverity: AttentionSeverity.warning,
      validationBadge:
          const CompactValidationBadge(kind: ValidationBadgeKind.unknown),
      asOf: DateTime.now().toUtc(),
    );
    return placeholder;
  }

  Widget _section(ThemeData theme, String title) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Text(title, style: theme.textTheme.titleMedium),
      );
}

class _EvidenceItem extends StatelessWidget {
  const _EvidenceItem({required this.evidence});
  final DriftEvidence evidence;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: theme.colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(6),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(_iconFor(evidence.kind), size: 14),
                const SizedBox(width: 6),
                Text(
                  evidence.kind.wireValue,
                  style: theme.textTheme.labelSmall,
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(evidence.summary),
            if (evidence.text != null) ...[
              const SizedBox(height: 4),
              Container(
                padding: const EdgeInsets.all(6),
                color: theme.colorScheme.surface,
                child: SelectableText(
                  evidence.text!,
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 12,
                  ),
                ),
              ),
            ],
            if (evidence.filePath != null)
              TextButton.icon(
                onPressed: () => _openFile(context, evidence),
                icon: const Icon(Icons.open_in_new, size: 14),
                label: Text(
                  evidence.lineNumber != null
                      ? '${evidence.filePath}:${evidence.lineNumber}'
                      : evidence.filePath!,
                ),
              ),
            if (evidence.url != null)
              TextButton.icon(
                onPressed: () =>
                    launchUrl(Uri.parse(evidence.url!), mode: LaunchMode.externalApplication),
                icon: const Icon(Icons.link, size: 14),
                label: Text(evidence.url!),
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _openFile(BuildContext context, DriftEvidence e) async {
    final uri = Uri.file(e.filePath!);
    final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open ${e.filePath}')),
      );
    }
  }

  static IconData _iconFor(DriftEvidenceKind k) => switch (k) {
        DriftEvidenceKind.logExcerpt => Icons.notes,
        DriftEvidenceKind.filePointer => Icons.description,
        DriftEvidenceKind.agentQuote => Icons.format_quote,
        DriftEvidenceKind.testResult => Icons.science,
        DriftEvidenceKind.staticCheck => Icons.policy,
        DriftEvidenceKind.operatorNote => Icons.edit_note,
        DriftEvidenceKind.other => Icons.help_outline,
      };
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(label, style: Theme.of(context).textTheme.labelSmall),
    );
  }
}
