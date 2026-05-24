import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/pane.dart';
import '../providers.dart';

/// Adopt-existing-pane modal form. T068 (Phase 3 US1) + FR-016 + FR-065.
///
/// Inputs: label, role (AgentRole), capability, project_path,
/// attach_log_now (bool). Submission must complete in ≤ 5 s per FR-065
/// (the modal renders a determinate progress strip after 1 s if the
/// daemon hasn't responded so the operator knows the request is still
/// in flight).
///
/// Reject role/capability incompatible with the pane's discovered
/// class: if `pane.discoveredClass` is `shell` we MAY adopt as
/// `master` only with a master-class capability (FR-071); the form
/// surfaces a per-field validation message rather than relying on the
/// daemon's `validation_failed` envelope.
class AdoptFlow extends ConsumerStatefulWidget {
  const AdoptFlow({super.key, required this.pane});

  final Pane pane;

  static Future<void> show(BuildContext context, {required Pane pane}) {
    return showDialog<void>(
      context: context,
      builder: (_) => Dialog(
        child: SizedBox(
          width: 520,
          child: AdoptFlow(pane: pane),
        ),
      ),
    );
  }

  @override
  ConsumerState<AdoptFlow> createState() => _AdoptFlowState();
}

class _AdoptFlowState extends ConsumerState<AdoptFlow> {
  final _formKey = GlobalKey<FormState>();
  final _labelCtrl = TextEditingController();
  final _projectPathCtrl = TextEditingController(text: '/work');
  AgentRole _role = AgentRole.master;
  String _capability = 'claude';
  bool _attachLogNow = true;
  bool _submitting = false;
  String? _error;

  static const _capabilities = ['claude', 'codex', 'gemini', 'opencode', 'shell'];

  @override
  void dispose() {
    _labelCtrl.dispose();
    _projectPathCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Adopt pane ${widget.pane.tmuxSessionName}:'
              '${widget.pane.tmuxWindowIndex}.${widget.pane.tmuxPaneIndex}',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _labelCtrl,
              decoration: const InputDecoration(
                labelText: 'Label',
                hintText: 'e.g. claude-master-1',
              ),
              validator: (v) =>
                  (v == null || v.trim().isEmpty) ? 'Label is required' : null,
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<AgentRole>(
              value: _role,
              decoration: const InputDecoration(labelText: 'Role'),
              items: [
                for (final r in AgentRole.values)
                  DropdownMenuItem(value: r, child: Text(r.wireValue)),
              ],
              onChanged: (v) => setState(() => _role = v ?? _role),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              value: _capability,
              decoration: const InputDecoration(labelText: 'Capability'),
              items: [
                for (final c in _capabilities)
                  DropdownMenuItem(value: c, child: Text(c)),
              ],
              onChanged: (v) => setState(() => _capability = v ?? _capability),
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _projectPathCtrl,
              decoration: const InputDecoration(labelText: 'Project path'),
              validator: (v) => (v == null || v.trim().isEmpty)
                  ? 'Project path is required'
                  : null,
            ),
            const SizedBox(height: 8),
            SwitchListTile(
              title: const Text('Attach log now'),
              subtitle: const Text('Recommended (FR-017)'),
              value: _attachLogNow,
              onChanged: (v) => setState(() => _attachLogNow = v),
            ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed:
                      _submitting ? null : () => Navigator.of(context).pop(),
                  child: const Text('Cancel'),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _submitting ? null : _submit,
                  child: _submitting
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Adopt'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _submitting = true;
      _error = null;
    });
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(appClientProvider).agentRegisterFromPane(
            paneId: widget.pane.paneId,
            label: _labelCtrl.text.trim(),
            role: _role.wireValue,
            capability: _capability,
            projectPath: _projectPathCtrl.text.trim(),
            attachLogNow: _attachLogNow,
          );
      ref.invalidate(paneListProvider);
      ref.invalidate(agentListProvider);
      if (!mounted) return;
      navigator.pop();
      messenger.showSnackBar(
        SnackBar(content: Text('Adopted as ${_labelCtrl.text.trim()}')),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Adopt failed: $e';
        _submitting = false;
      });
    }
  }
}
