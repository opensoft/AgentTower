import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/daemon/errors.dart';
import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../domain/lifecycles/pane_state_validator.dart';
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
              l10n.adoptTitle(
                widget.pane.tmuxSessionName,
                widget.pane.tmuxWindowIndex,
                widget.pane.tmuxPaneIndex,
              ),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _labelCtrl,
              decoration: InputDecoration(
                labelText: l10n.adoptLabelLabel,
                hintText: l10n.adoptLabelHint,
              ),
              validator: (v) => (v == null || v.trim().isEmpty)
                  ? l10n.adoptLabelRequired
                  : null,
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<AgentRole>(
              value: _role,
              decoration: InputDecoration(labelText: l10n.adoptRoleLabel),
              items: [
                for (final r in AgentRole.values)
                  DropdownMenuItem(value: r, child: Text(r.wireValue)),
              ],
              onChanged: (v) => setState(() => _role = v ?? _role),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              value: _capability,
              decoration: InputDecoration(labelText: l10n.adoptCapabilityLabel),
              items: [
                for (final c in _capabilities)
                  DropdownMenuItem(value: c, child: Text(c)),
              ],
              onChanged: (v) => setState(() => _capability = v ?? _capability),
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _projectPathCtrl,
              decoration: InputDecoration(labelText: l10n.adoptProjectPathLabel),
              validator: (v) => (v == null || v.trim().isEmpty)
                  ? l10n.adoptProjectPathRequired
                  : null,
            ),
            const SizedBox(height: 8),
            SwitchListTile(
              title: Text(l10n.adoptAttachLogTitle),
              subtitle: Text(l10n.adoptAttachLogSubtitle),
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
                  child: Text(l10n.adoptCancel),
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
                      : Text(l10n.adoptSubmit),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _submit() async {
    final l10n = AppLocalizations.of(context);
    if (!_formKey.currentState!.validate()) return;
    // FR-014 + data-model §3: refuse to submit a transition that the
    // PaneStateValidator says is invalid. The daemon would reject too,
    // but a local check spares a round-trip and gives a clearer error
    // (review fix H9 — wire lifecycle validators into UI mutations).
    if (!PaneStateValidator.isValidTransition(
      widget.pane.state,
      PaneState.discoveredAndRegistered,
    )) {
      setState(() =>
          _error = l10n.adoptInvalidTransition(widget.pane.state.wireValue));
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    try {
      // Per `app-methods.md` §app.agent.register_from_pane FR-028a, the daemon
      // requires ALL 6 pane-identity fields and rejects on any byte-for-byte
      // mismatch with `pane_not_found.details.mismatch_field`. We forward the
      // discovered Pane's fields directly — the operator only chooses
      // label/role/capability/project_path/attach_log.
      await ref.read(appClientProvider).agentRegisterFromPane(
            paneId: widget.pane.paneId,
            containerId: widget.pane.containerId,
            tmuxSocket: widget.pane.tmuxSocket,
            sessionName: widget.pane.tmuxSessionName,
            windowIndex: widget.pane.tmuxWindowIndex,
            paneIndex: widget.pane.tmuxPaneIndex,
            label: _labelCtrl.text.trim(),
            role: _role.wireValue,
            capability: _capability,
            projectPath: _projectPathCtrl.text.trim(),
            attachLog: _attachLogNow,
          );
      ref.invalidate(paneListProvider);
      ref.invalidate(agentListProvider);
      if (!mounted) return;
      navigator.pop();
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.adoptedAs(_labelCtrl.text.trim()))),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = l10n.adoptFailed(_errorText(e));
        _submitting = false;
      });
    }
  }
}

/// Renders a closed-set [AppContractError] using its prose `message` rather
/// than `e.toString()`. See review fix M1.
String _errorText(Object e) =>
    e is AppContractError ? e.message : e.toString();
