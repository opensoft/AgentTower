import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../domain/lifecycles/handoff_state_validator.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/handoff.dart';
import '../../../ui/widgets/contract_checked_button.dart';
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
///
/// **State gate (swarm-review H-B8/H-B9)**: supersede is only legal
/// from `submitted` or `accepted` per FR-044. Callers should check
/// [canSupersede] before showing the affordance; this function also
/// re-checks and returns early to provide defense-in-depth. The
/// daemon remains the ultimate authority.
Future<void> supersedeHandoff({
  required BuildContext context,
  required WidgetRef ref,
  required Handoff priorHandoff,
  required Map<String, dynamic> newDraft,
}) async {
  if (!canSupersede(priorHandoff)) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          AppLocalizations.of(context).supersedeIllegalStateSnack(
            priorHandoff.assignmentState.wireValue,
          ),
        ),
      ),
    );
    return;
  }
  final priorId = priorHandoff.handoffId;
  if (priorId == null || priorId.isEmpty) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(AppLocalizations.of(context).supersedeNoIdSnack),
      ),
    );
    return;
  }
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (_) => _SupersedeConfirmDialog(prior: priorHandoff),
  );
  if (confirmed != true) return;
  try {
    await ref.read(appClientProvider).handoffSupersede(
          priorHandoffId: priorId,
          newDraft: newDraft,
        );
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
            content: Text(AppLocalizations.of(context)
                .supersedeFailedSnack(e.toString()))),
      );
    }
    return;
  }
  // Invalidate both the prior detail AND the list family so the
  // updated states are picked up on the next read.
  ref.invalidate(handoffDetailProvider(priorId));
  ref.invalidate(handoffListProvider);
}

/// Returns true iff [handoff] is in a state where FR-044 permits supersede.
/// Callers should use this to disable the supersede affordance rather
/// than relying on the round-trip rejection.
bool canSupersede(Handoff handoff) {
  if (handoff.handoffId == null || handoff.handoffId!.isEmpty) return false;
  // FR-044: supersede legal only from `submitted` and `accepted`.
  return HandoffStateValidator.isValidTransition(
    handoff.assignmentState,
    AssignmentState.superseded,
  );
}

class _SupersedeConfirmDialog extends StatelessWidget {
  const _SupersedeConfirmDialog({required this.prior});
  final Handoff prior;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l10n.supersedeDialogTitle),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              l10n.supersedeDialogPrompt(
                  prior.handoffId ?? prior.draftId ?? "?"),
              style: Theme.of(context).textTheme.bodyLarge,
            ),
            const SizedBox(height: 12),
            Text(l10n.supersedeDialogExplanation),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: Text(l10n.supersedeDialogCancel),
        ),
        ContractCheckedButton(
          onPressed: () => Navigator.of(context).pop(true),
          builder: (ctx, onPressed, reason) => FilledButton(
            onPressed: onPressed,
            child: Text(l10n.supersedeDialogConfirm),
          ),
        ),
      ],
    );
  }
}
