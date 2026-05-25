import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../../../core/persistence/ux_state_repository.dart';
import '../../../core/providers.dart';
import '../../../ui/widgets/contract_checked_button.dart';
import '../providers.dart';

/// FR-077 "Remove project" confirmation dialog. T090 (Phase 4 US2).
///
/// Per FR-077, removal is confirmation-gated. On confirm we:
///   1. Call `app.project.remove` so the daemon forgets the
///      registration (the daemon does NOT delete agents / handoffs /
///      drift / runs — those are preserved).
///   2. Clear the per-project UI persistence (last sub-view +
///      sort/filter) from `ux-state.json` via [UxStateRepository].
///   3. Reset [selectedProjectIdProvider] if the removed project was
///      the active selection.
///
/// A removed project will reappear in the Projects view if it is
/// later re-inferred from an adopted agent's `project_path`, with
/// its UI persistence reset to defaults — also per FR-077.
class RemoveProjectDialog extends ConsumerStatefulWidget {
  const RemoveProjectDialog({
    super.key,
    required this.projectId,
    required this.projectLabel,
  });

  final String projectId;
  final String projectLabel;

  @override
  ConsumerState<RemoveProjectDialog> createState() =>
      _RemoveProjectDialogState();
}

class _RemoveProjectDialogState extends ConsumerState<RemoveProjectDialog> {
  String? _error;
  bool _submitting = false;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return AlertDialog(
      title: Text(l10n.removeProjectDialogTitle),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              l10n.removeProjectConfirmPrompt(widget.projectLabel),
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 12),
            Text(l10n.removeProjectExplanation),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _submitting ? null : () => Navigator.of(context).pop(false),
          child: Text(l10n.removeProjectCancel),
        ),
        ContractCheckedButton(
          additionalGate: !_submitting,
          onPressed: _submit,
          builder: (ctx, onPressed, reason) => FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
            ),
            onPressed: onPressed,
            child: _submitting
                ? const SizedBox(
                    height: 16,
                    width: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : Text(l10n.removeProjectConfirm),
          ),
        ),
      ],
    );
  }

  Future<void> _submit() async {
    setState(() {
      _submitting = true;
      _error = null;
    });
    // Swarm-review H-G4: reset selectedProjectIdProvider BEFORE the
    // daemon round-trip so any widget watching projectDetailProvider
    // does not race against an in-flight detail call that may return
    // `not_found` after removal. The provider is reset back to null
    // on failure inside the catch block below.
    final wasSelected =
        ref.read(selectedProjectIdProvider) == widget.projectId;
    if (wasSelected) {
      ref.read(selectedProjectIdProvider.notifier).state = null;
    }
    try {
      await ref.read(appClientProvider).projectRemove(
            projectId: widget.projectId,
          );
      ref
          .read(uxStateRepositoryProvider)
          .clearProjectScopedState(widget.projectId);
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      // Restore selection on failure so the user doesn't silently lose
      // their working project.
      if (wasSelected) {
        ref.read(selectedProjectIdProvider.notifier).state = widget.projectId;
      }
      setState(() {
        _submitting = false;
        _error = e.toString();
      });
    }
  }
}
