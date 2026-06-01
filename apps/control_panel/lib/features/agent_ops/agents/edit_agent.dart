import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/daemon/errors.dart';
import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../domain/models/adopted_agent.dart';
import '../../../domain/models/common_enums.dart';
import '../providers.dart';

/// Edit-adopted-agent dialog. T069+ extension + review fix H10 / spec-code
/// lane (FR-015 mandates label/role/capability/project_path editability
/// post-adopt; the field was reachable via `AppClient.agentUpdate` but
/// not from any surface).
///
/// Per FEAT-011 `app.agent.update` semantics (`app-methods.md` line 290):
///   - Absent fields → no change
///   - Empty string on `project_path`/`label` → clears the field
///   - Empty string on `role`/`capability` → `validation_failed`
///
/// The form skips sending fields the operator didn't touch; clearing is
/// available for `label` and `project_path` only.
class EditAgentDialog extends ConsumerStatefulWidget {
  const EditAgentDialog({super.key, required this.agent});

  final AdoptedAgent agent;

  static Future<void> show(BuildContext context,
      {required AdoptedAgent agent}) {
    return showDialog<void>(
      context: context,
      builder: (_) => Dialog(
        child: SizedBox(width: 520, child: EditAgentDialog(agent: agent)),
      ),
    );
  }

  @override
  ConsumerState<EditAgentDialog> createState() => _EditAgentDialogState();
}

class _EditAgentDialogState extends ConsumerState<EditAgentDialog> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _labelCtrl;
  late final TextEditingController _projectPathCtrl;
  late AgentRole _role;
  late String _capability;
  bool _saving = false;
  String? _error;

  static const _capabilities = [
    'claude',
    'codex',
    'gemini',
    'opencode',
    'shell',
  ];

  @override
  void initState() {
    super.initState();
    _labelCtrl = TextEditingController(text: widget.agent.label);
    _projectPathCtrl =
        TextEditingController(text: widget.agent.projectPath);
    _role = widget.agent.role;
    _capability = _capabilities.contains(widget.agent.capability)
        ? widget.agent.capability
        : _capabilities.first;
  }

  @override
  void dispose() {
    _labelCtrl.dispose();
    _projectPathCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l10n.editAgentTitle(widget.agent.label),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _labelCtrl,
              decoration: InputDecoration(
                labelText: l10n.editAgentLabelLabel,
                helperText: l10n.editAgentLabelHelper,
              ),
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<AgentRole>(
              value: _role,
              decoration: InputDecoration(labelText: l10n.editAgentRoleLabel),
              items: [
                for (final r in AgentRole.values)
                  DropdownMenuItem(value: r, child: Text(r.wireValue)),
              ],
              onChanged: (v) => setState(() => _role = v ?? _role),
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              value: _capability,
              decoration:
                  InputDecoration(labelText: l10n.editAgentCapabilityLabel),
              items: [
                for (final c in _capabilities)
                  DropdownMenuItem(value: c, child: Text(c)),
              ],
              onChanged: (v) =>
                  setState(() => _capability = v ?? _capability),
            ),
            const SizedBox(height: 8),
            TextFormField(
              controller: _projectPathCtrl,
              decoration: InputDecoration(
                labelText: l10n.editAgentProjectPathLabel,
                helperText: l10n.editAgentProjectPathHelper,
              ),
            ),
            if (_error != null) ...[
              const SizedBox(height: 8),
              Text(_error!,
                  style:
                      TextStyle(color: Theme.of(context).colorScheme.error)),
            ],
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed:
                      _saving ? null : () => Navigator.of(context).pop(),
                  child: Text(l10n.editAgentCancel),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _saving ? null : _save,
                  child: _saving
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Text(l10n.editAgentSave),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final l10n = AppLocalizations.of(context);
    try {
      // Only include fields the operator actually changed. `label` and
      // `project_path` may be set to '' (clears the field per FR-029a);
      // `role` and `capability` always send their selected value.
      await ref.read(appClientProvider).agentUpdate(
            agentId: widget.agent.agentId,
            label: _labelCtrl.text != widget.agent.label
                ? _labelCtrl.text
                : null,
            role: _role != widget.agent.role ? _role.wireValue : null,
            capability: _capability != widget.agent.capability
                ? _capability
                : null,
            projectPath: _projectPathCtrl.text != widget.agent.projectPath
                ? _projectPathCtrl.text
                : null,
          );
      ref.invalidate(agentListProvider);
      ref.invalidate(agentDetailProvider(widget.agent.agentId));
      if (!mounted) return;
      navigator.pop();
      messenger.showSnackBar(
          SnackBar(content: Text(l10n.editAgentUpdatedSnack)));
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = l10n.editAgentUpdateFailed(_errorText(e));
        _saving = false;
      });
    }
  }
}

String _errorText(Object e) =>
    e is AppContractError ? e.message : e.toString();
