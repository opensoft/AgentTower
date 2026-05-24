import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';

/// Explicit "Add Project" dialog. T089 (Phase 4 US2).
///
/// Per spec Assumption (Project registration model): projects enter
/// the app either (a) explicitly via this dialog (operator supplies a
/// repository path) or (b) automatically by inference from an adopted
/// agent's `project_path`. This dialog covers (a).
///
/// The dialog accepts an absolute repository path and an optional
/// label. The daemon canonicalizes the path and de-duplicates against
/// existing registrations (per FR-026 — same canonicalized path → same
/// `projectId`). The dialog surfaces daemon errors inline without
/// re-throwing.
class AddProjectDialog extends ConsumerStatefulWidget {
  const AddProjectDialog({super.key});

  @override
  ConsumerState<AddProjectDialog> createState() => _AddProjectDialogState();
}

class _AddProjectDialogState extends ConsumerState<AddProjectDialog> {
  final _pathController = TextEditingController();
  final _labelController = TextEditingController();
  String? _error;
  bool _submitting = false;

  @override
  void dispose() {
    _pathController.dispose();
    _labelController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Add project'),
      content: SizedBox(
        width: 480,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            TextField(
              controller: _pathController,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Repository path (absolute)',
                hintText: '/home/you/projects/example',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _labelController,
              decoration: const InputDecoration(
                labelText: 'Display label (optional)',
                hintText: 'My Project',
              ),
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
          onPressed: _submitting ? null : _submit,
          child: _submitting
              ? const SizedBox(
                  height: 16,
                  width: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Add'),
        ),
      ],
    );
  }

  Future<void> _submit() async {
    final path = _pathController.text.trim();
    if (path.isEmpty) {
      setState(() => _error = 'Repository path is required.');
      return;
    }
    if (!path.startsWith('/') && !RegExp(r'^[A-Za-z]:[\\/]').hasMatch(path)) {
      setState(() => _error = 'Path must be absolute (FR-026 canonicalization).');
      return;
    }
    final label = _labelController.text.trim();
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await ref.read(appClientProvider).projectAdd(
            repositoryPath: path,
            label: label.isEmpty ? null : label,
          );
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      setState(() {
        _submitting = false;
        _error = e.toString();
      });
    }
  }
}
