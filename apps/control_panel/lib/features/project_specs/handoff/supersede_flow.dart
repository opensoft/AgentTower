import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../domain/models/handoff.dart';
import 'providers.dart';

/// FR-081 — supersede flow. T109 (Phase 5 US3).
///
/// **Behavior**: the prior handoff transitions to `superseded` and the
/// new handoff records `supersedesHandoffId`. The daemon stamps the
/// reverse `supersededByHandoffId` on the prior handoff. Queue rows
/// already created from the prior handoff are NOT auto-cancelled —
/// the daemon leaves them to terminate naturally and the operator can
/// cancel them manually from the Queue view if desired.
///
/// **Operator confirmation**: the supersede affordance is gated by an
/// explicit confirm dialog so an accidental click does not silently
/// retire a live handoff.
Future<void> supersedeHandoff({
  required BuildContext context,
  required WidgetRef ref,
  required Handoff priorHandoff,
  required Map<String, dynamic> newDraft,
}) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (_) => _SupersedeConfirmDialog(prior: priorHandoff),
  );
  if (confirmed != true) return;
  await ref.read(appClientProvider).handoffSupersede(
        priorHandoffId: priorHandoff.handoffId ?? priorHandoff.draftId ?? '',
        newDraft: newDraft,
      );
  // Invalidate detail + any list watching the prior or new handoff.
  ref.invalidate(handoffDetailProvider(priorHandoff.handoffId ?? ''));
}

class _SupersedeConfirmDialog extends StatelessWidget {
  const _SupersedeConfirmDialog({required this.prior});
  final Handoff prior;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Supersede prior handoff?'),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Supersede handoff '
              '${prior.handoffId ?? prior.draftId ?? "?"}',
              style: Theme.of(context).textTheme.bodyLarge,
            ),
            const SizedBox(height: 12),
            const Text(
              'The prior handoff will move to `superseded`. Queue rows '
              'already created from it will NOT be auto-cancelled (per '
              'FR-081); cancel them from the Queue view if needed. The '
              'new handoff records its `supersedes_handoff_id` so the '
              'lineage is reproducible.',
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: const Text('Supersede'),
        ),
      ],
    );
  }
}
