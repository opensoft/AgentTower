import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../domain/models/handoff.dart';
import '../../../domain/models/handoff_supporting.dart';
import '../../../domain/models/resolved_work_item.dart';
import '../../../ui/widgets/contract_checked_button.dart';
import '../../../ui/widgets/runtime_state_views.dart';
import 'providers.dart';

/// T111 — Handoff detail surface (data-model §1.6 + FR-042 + FR-044 +
/// FR-072 + FR-081).
///
/// Surfaces:
///   - the durable handoff record (id, assignment state, lifecycle
///     timestamps, supersede chain)
///   - the helper-policy snapshot (FR-042)
///   - the FR-072 delivery-status indicator with a Retry-delivery
///     affordance when `deliveryStatus.kind == failed`
///   - the FR-072(c) offline-master indicator when held in `submitted`
///     with `deliveryStatus.kind == pending`
///   - the supersede chain (back-references both directions)
class HandoffDetailView extends ConsumerWidget {
  const HandoffDetailView({super.key, required this.handoffId});
  final String handoffId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final detail = ref.watch(handoffDetailProvider(handoffId));
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.handoffDetailTitle(handoffId)),
        actions: [
          IconButton(
            tooltip: l10n.handoffDetailRefreshTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(handoffDetailProvider(handoffId)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.handoffDetailSurfaceLabel,
          onRetry: () => ref.invalidate(handoffDetailProvider(handoffId)),
        ),
        onIncompatible: (s) =>
            ContractIncompatStateView(state: s, surfaceLabel: l10n.handoffDetailSurfaceLabel),
        child: detail.when(
          data: (h) => _Body(handoff: h),
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: l10n.handoffDetailSurfaceErrorLabel(handoffId),
            onRetry: () => ref.invalidate(handoffDetailProvider(handoffId)),
          ),
        ),
      ),
    );
  }
}

class _Body extends ConsumerWidget {
  const _Body({required this.handoff});
  final Handoff handoff;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _statusBar(context),
          const SizedBox(height: 16),
          _section(theme, l10n.handoffDetailSectionTarget),
          Text(l10n.handoffDetailMasterLine(
              handoff.targetMasterLabel, handoff.targetMasterAgentId)),
          Text(l10n.handoffDetailProjectLine(
              handoff.projectLabel, handoff.projectId)),
          Text(l10n.handoffDetailModeLine(handoff.mode.wireValue)),
          if (handoff.priority != null)
            Text(l10n.handoffDetailPriorityLine(handoff.priority!.wireValue)),
          if (handoff.deadline != null)
            Text(l10n.handoffDetailDeadlineLine(
                handoff.deadline!.toLocal().toString())),
          const SizedBox(height: 16),
          _section(theme, l10n.handoffDetailSectionResolvedWorkItems),
          for (final item in handoff.resolvedWorkItems)
            Text(l10n.handoffDetailResolvedItemBullet(item.renderForPrompt())),
          const SizedBox(height: 16),
          _section(theme, l10n.handoffDetailSectionHelperPolicy),
          Text(l10n.handoffDetailPolicyLine(
            handoff.helperPolicyId,
            handoff.helperPolicySnapshot.resolvedPolicy.policySource.wireValue,
          )),
          Text(l10n.handoffDetailDefaultHelperLine(
              handoff.helperPolicySnapshot.resolvedPolicy
                  .defaultHelperCapability)),
          Text(l10n.handoffDetailAllowedLine(
            (handoff.helperPolicySnapshot.resolvedPolicy
                    .allowedHelperCapabilities
                    .toList()
                  ..sort())
                .join(", "),
          )),
          if (handoff.helperPolicySnapshot.repoOverridePath != null)
            Text(l10n.handoffDetailRepoOverrideLine(
                handoff.helperPolicySnapshot.repoOverridePath!)),
          const SizedBox(height: 16),
          _section(theme, l10n.handoffDetailSectionSupersedeChain),
          if (handoff.supersedesHandoffId != null)
            Text(l10n.handoffDetailSupersedesLine(handoff.supersedesHandoffId!)),
          if (handoff.supersededByHandoffId != null)
            Text(l10n.handoffDetailSupersededByLine(
                handoff.supersededByHandoffId!)),
          if (handoff.supersedesHandoffId == null &&
              handoff.supersededByHandoffId == null)
            Text(l10n.handoffDetailNoSupersede),
          const SizedBox(height: 16),
          _section(theme, l10n.handoffDetailSectionLifecycle),
          Text(l10n.handoffDetailCreatedLine(handoff.createdAt.toLocal().toString())),
          if (handoff.submittedAt != null)
            Text(l10n.handoffDetailSubmittedLine(
                handoff.submittedAt!.toLocal().toString())),
          if (handoff.acceptedAt != null)
            Text(l10n.handoffDetailAcceptedLine(
                handoff.acceptedAt!.toLocal().toString())),
          if (handoff.completedAt != null)
            Text(l10n.handoffDetailCompletedLine(
                handoff.completedAt!.toLocal().toString())),
          if (handoff.cancelledAt != null)
            Text(l10n.handoffDetailCancelledLine(
                handoff.cancelledAt!.toLocal().toString())),
          const SizedBox(height: 16),
          _section(theme, l10n.handoffDetailSectionGeneratedPrompt),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(6),
            ),
            child: SelectableText(
              handoff.generatedPromptText,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }

  Widget _statusBar(BuildContext context) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    final delivery = handoff.deliveryStatus;
    final failure = handoff.failureContext;
    final children = <Widget>[
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: theme.colorScheme.primaryContainer,
          borderRadius: BorderRadius.circular(4),
        ),
        child: Text(l10n.handoffDetailStateChip(handoff.assignmentState.wireValue)),
      ),
    ];
    if (failure != null) {
      children.add(_failureChip(context, failure));
    }
    if (delivery != null) {
      children.add(_deliveryChip(context, delivery));
    }
    return Wrap(spacing: 8, runSpacing: 8, children: children);
  }

  Widget _failureChip(BuildContext context, HandoffFailureContext failure) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        AppLocalizations.of(context).handoffDetailFailureChip(
          failure.errorCode,
          failure.errorMessage,
        ),
      ),
    );
  }

  Widget _deliveryChip(BuildContext context, HandoffDeliveryStatus delivery) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    final color = switch (delivery.kind) {
      HandoffDeliveryStatusKind.delivered => theme.colorScheme.primaryContainer,
      HandoffDeliveryStatusKind.failed => theme.colorScheme.errorContainer,
      HandoffDeliveryStatusKind.retrying => theme.colorScheme.tertiaryContainer,
      HandoffDeliveryStatusKind.pending => theme.colorScheme.secondaryContainer,
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(4)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(l10n.handoffDetailDeliveryChip(delivery.kind.wireValue)),
          if (delivery.kind == HandoffDeliveryStatusKind.failed) ...[
            const SizedBox(width: 8),
            Consumer(
              builder: (ctx, ref, _) => ContractCheckedButton(
                onPressed: () => _retryDelivery(ctx, ref),
                builder: (c, onPressed, reason) => TextButton(
                  onPressed: onPressed,
                  child: Text(AppLocalizations.of(c).handoffDetailRetryDeliveryButton),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _retryDelivery(BuildContext context, WidgetRef ref) async {
    final id = handoff.handoffId;
    if (id == null) return;
    try {
      await ref.read(appClientProvider).handoffRetryDelivery(handoffId: id);
      ref.invalidate(handoffDetailProvider(id));
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(AppLocalizations.of(context)
                .handoffDetailRetryFailedSnack(e.toString())),
          ),
        );
      }
    }
  }

  Widget _section(ThemeData theme, String title) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Text(title, style: theme.textTheme.titleMedium),
      );
}
