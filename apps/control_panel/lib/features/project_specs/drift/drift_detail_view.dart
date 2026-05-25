import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../domain/master_qualification.dart';
import '../../../domain/models/badges.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/drift_signal.dart';
import '../../../domain/models/drift_supporting.dart';
import '../../../domain/models/master_summary.dart';
import '../../../domain/models/project.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import '../../../ui/widgets/safe_url_launcher.dart';
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
    final l10n = AppLocalizations.of(context);
    final detail = ref.watch(driftDetailProvider(findingId));
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.driftDetailTitle(findingId)),
        actions: [
          IconButton(
            tooltip: l10n.driftRefreshTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(driftDetailProvider(findingId)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.driftDetailSurfaceLabel,
          onRetry: () => ref.invalidate(driftDetailProvider(findingId)),
        ),
        onIncompatible: (s) =>
            ContractIncompatStateView(state: s, surfaceLabel: l10n.driftDetailSurfaceLabel),
        child: detail.when(
          data: (d) => _Body(drift: d),
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: l10n.driftDetailSurfaceErrorLabel(findingId),
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
    final l10n = AppLocalizations.of(context);
    final scopeStr =
        '${drift.scope.kind.wireValue}${drift.scope.id != null ? ":${drift.scope.id}" : ""}';
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
              _Chip(label: l10n.driftDetailChipStatus(drift.status.wireValue)),
              _Chip(label: l10n.driftDetailChipSeverity(drift.severity.wireValue)),
              _Chip(label: l10n.driftDetailChipSource(drift.source.wireValue)),
              _Chip(
                  label: l10n.driftDetailChipConfidence(drift.confidence.wireValue)),
              _Chip(label: l10n.driftDetailChipScope(scopeStr)),
            ],
          ),
          const SizedBox(height: 16),
          DriftTransitionAction(drift: drift),
          const SizedBox(height: 24),
          _section(theme, l10n.driftDetailSectionRecommended),
          Text(drift.recommendedAction),
          const SizedBox(height: 24),
          _section(theme, l10n.driftDetailSectionLinkedRefs),
          if (drift.linkedFeatureIds.isNotEmpty)
            Text(l10n.driftDetailLinkedFeatures(
                drift.linkedFeatureIds.join(", "))),
          if (drift.linkedChangeIds.isNotEmpty)
            Text(l10n.driftDetailLinkedChanges(
                drift.linkedChangeIds.join(", "))),
          if (drift.linkedBranch != null)
            Text(l10n.driftDetailLinkedBranch(drift.linkedBranch!)),
          if (drift.linkedWorktree != null)
            Text(l10n.driftDetailLinkedWorktree(drift.linkedWorktree!)),
          if (drift.linkedFeatureIds.isEmpty &&
              drift.linkedChangeIds.isEmpty &&
              drift.linkedBranch == null &&
              drift.linkedWorktree == null)
            Text(l10n.driftDetailNoLinkedRefs),
          const SizedBox(height: 24),
          _section(theme, l10n.driftDetailSectionEvidence),
          if (drift.evidence.isEmpty) Text(l10n.driftDetailNoEvidence),
          for (final e in drift.evidence) _EvidenceItem(evidence: e),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            onPressed: () => _onRepair(context, ref),
            icon: const Icon(Icons.build),
            label: Text(l10n.driftDetailRepairButton),
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
    final l10n = AppLocalizations.of(context);
    final selectedId = ref.read(project_providers.selectedProjectIdProvider);
    if (selectedId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(l10n.driftDetailNoProjectSelectedSnack),
        ),
      );
      return;
    }
    try {
      final project =
          await ref.read(project_providers.projectDetailProvider(selectedId).future);
      final master = await _resolveMaster(context, ref, project);
      if (master == null) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                  AppLocalizations.of(context).driftDetailNoMasterAvailableSnack),
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
          SnackBar(
            content: Text(AppLocalizations.of(context)
                .driftDetailHandoffFlowOpenFailedSnack(e.toString())),
          ),
        );
      }
    }
  }

  Future<MasterSummary?> _resolveMaster(
    BuildContext context,
    WidgetRef ref,
    Project project,
  ) async {
    // Prefer the project's current driver if known. Otherwise nothing
    // to do — the operator must wire a driving master first. The full
    // master-picker UX lands when the agent surface adds a picker
    // affordance; for now we surface the no-driver state clearly.
    final driverId = project.currentDrivingMasterAgentId;
    if (driverId == null) return null;
    final envelope =
        await ref.read(masterClassCapabilitiesProvider.future);
    // Synthesize a minimal MasterSummary via the FR-071 gate
    // (MasterSummary.tryFromAgent). When the daemon's capability
    // registry is unreachable (envelope.degraded) we fall back to
    // the first known master-class capability or 'claude' so the
    // drift-repair launch isn't completely blocked, while the
    // ContextBundle the daemon assembles at submit time will use
    // the real capability of the resolved agent.
    return MasterSummary.tryFromAgent(
          agentId: driverId,
          label: driverId,
          capability: envelope.capabilities.isNotEmpty
              ? envelope.capabilities.first
              : 'claude',
          role: AgentRole.master,
          masterClassCapabilities: envelope.capabilities.isEmpty
              ? const {'claude'}
              : envelope.capabilities,
          assignedProjectId: project.projectId,
          activeBadge: const ActiveInactiveBadge(active: true),
          currentStatus: MasterStatus.active,
          workflowPhase: WorkflowPhase(
            humanLabel: AppLocalizations.of(context).driftRepairPlaceholderWorkflowPhase,
          ),
          subAgentRollup: const SubAgentRollup(),
          attentionSeverity: AttentionSeverity.warning,
          validationBadge: const CompactValidationBadge(
            kind: ValidationBadgeKind.unknown,
          ),
          asOf: DateTime.now().toUtc(),
        );
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
                // Swarm-review H-D1: route daemon-supplied evidence URLs
                // through SafeUrlLauncher so the scheme allowlist catches
                // javascript:/data:/vbscript: payloads before reaching the
                // OS handler.
                onPressed: () =>
                    SafeUrlLauncher.open(context, evidence.url!),
                icon: const Icon(Icons.link, size: 14),
                label: Text(evidence.url!),
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _openFile(BuildContext context, DriftEvidence e) async {
    // Swarm-review H-D2: previously `launchUrl(Uri.file(...))` opened
    // any daemon-supplied path with the OS default handler. Route
    // through SafeUrlLauncher.openFile so the operator confirms the
    // path before launch (the daemon's authority to produce arbitrary
    // file paths is unbounded).
    await SafeUrlLauncher.openFile(context, e.filePath!);
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
