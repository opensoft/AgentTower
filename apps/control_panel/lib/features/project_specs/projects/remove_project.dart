import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/persistence/ux_state_repository.dart';
import '../../../core/providers.dart';
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
    return AlertDialog(
      title: const Text('Remove project?'),
      content: SizedBox(
        width: 460,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Remove "${widget.projectLabel}" from the project list?',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 12),
            const Text(
              'This clears the project from your app view and resets its '
              'saved sort/filter selections. Daemon-side data (agents, '
              'handoffs, drift findings, validation runs) is preserved. '
              'The project may reappear automatically if it is later '
              'inferred from an adopted agent.',
            ),
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
          child: const Text('Cancel'),
        ),
        FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: Theme.of(context).colorScheme.error,
          ),
          onPressed: _submitting ? null : _submit,
          child: _submitting
              ? const SizedBox(
                  height: 16,
                  width: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Remove'),
        ),
      ],
    );
  }

  Future<void> _submit() async {
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await ref.read(appClientProvider).projectRemove(
            projectId: widget.projectId,
          );
      ref
          .read(uxStateRepositoryProvider)
          .clearProjectScopedState(widget.projectId);
      // If the removed project was the active selection, clear it.
      if (ref.read(selectedProjectIdProvider) == widget.projectId) {
        ref.read(selectedProjectIdProvider.notifier).state = null;
      }
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      setState(() {
        _submitting = false;
        _error = e.toString();
      });
    }
  }
}
