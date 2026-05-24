import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../domain/models/handoff.dart';
import '../../../domain/models/handoff_supporting.dart';
import '../../../domain/models/resolved_work_item.dart';
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
    final detail = ref.watch(handoffDetailProvider(handoffId));
    return Scaffold(
      appBar: AppBar(
        title: Text('Handoff $handoffId'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(handoffDetailProvider(handoffId)),
          ),
        ],
      ),
      body: detail.when(
        data: (h) => _Body(handoff: h),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => Center(child: Text('Failed: $err')),
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
    return SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _statusBar(context),
          const SizedBox(height: 16),
          _section(theme, 'Target'),
          Text('Master: ${handoff.targetMasterLabel} '
              '(${handoff.targetMasterAgentId})'),
          Text('Project: ${handoff.projectLabel} (${handoff.projectId})'),
          Text('Mode: ${handoff.mode.wireValue}'),
          if (handoff.priority != null)
            Text('Priority: ${handoff.priority!.wireValue}'),
          if (handoff.deadline != null)
            Text('Deadline: ${handoff.deadline!.toLocal()}'),
          const SizedBox(height: 16),
          _section(theme, 'Resolved work items'),
          for (final item in handoff.resolvedWorkItems)
            Text('• ${item.renderForPrompt()}'),
          const SizedBox(height: 16),
          _section(theme, 'Helper policy snapshot'),
          Text('Policy: ${handoff.helperPolicyId} '
              '(${handoff.helperPolicySnapshot.resolvedPolicy.policySource.wireValue})'),
          Text('Default helper: '
              '${handoff.helperPolicySnapshot.resolvedPolicy.defaultHelperCapability}'),
          Text('Allowed: '
              '${(handoff.helperPolicySnapshot.resolvedPolicy.allowedHelperCapabilities.toList()..sort()).join(", ")}'),
          if (handoff.helperPolicySnapshot.repoOverridePath != null)
            Text('Repo override: '
                '${handoff.helperPolicySnapshot.repoOverridePath}'),
          const SizedBox(height: 16),
          _section(theme, 'Supersede chain'),
          if (handoff.supersedesHandoffId != null)
            Text('Supersedes: ${handoff.supersedesHandoffId}'),
          if (handoff.supersededByHandoffId != null)
            Text('Superseded by: ${handoff.supersededByHandoffId}'),
          if (handoff.supersedesHandoffId == null &&
              handoff.supersededByHandoffId == null)
            const Text('No supersede relationships.'),
          const SizedBox(height: 16),
          _section(theme, 'Lifecycle'),
          Text('Created: ${handoff.createdAt.toLocal()}'),
          if (handoff.submittedAt != null)
            Text('Submitted: ${handoff.submittedAt!.toLocal()}'),
          if (handoff.acceptedAt != null)
            Text('Accepted: ${handoff.acceptedAt!.toLocal()}'),
          if (handoff.completedAt != null)
            Text('Completed: ${handoff.completedAt!.toLocal()}'),
          if (handoff.cancelledAt != null)
            Text('Cancelled: ${handoff.cancelledAt!.toLocal()}'),
          const SizedBox(height: 16),
          _section(theme, 'Generated prompt'),
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
    final delivery = handoff.deliveryStatus;
    final failure = handoff.failureContext;
    final children = <Widget>[
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: theme.colorScheme.primaryContainer,
          borderRadius: BorderRadius.circular(4),
        ),
        child: Text('State: ${handoff.assignmentState.wireValue}'),
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
        'Submission failure: ${failure.errorCode} — ${failure.errorMessage}',
      ),
    );
  }

  Widget _deliveryChip(BuildContext context, HandoffDeliveryStatus delivery) {
    final theme = Theme.of(context);
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
          Text('Delivery: ${delivery.kind.wireValue}'),
          if (delivery.kind == HandoffDeliveryStatusKind.failed) ...[
            const SizedBox(width: 8),
            Consumer(
              builder: (ctx, ref, _) => TextButton(
                onPressed: () => _retryDelivery(ctx, ref),
                child: const Text('Retry delivery'),
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
          SnackBar(content: Text('Retry failed: $e')),
        );
      }
    }
  }

  Widget _section(ThemeData theme, String title) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Text(title, style: theme.textTheme.titleMedium),
      );
}
