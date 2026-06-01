import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/daemon/errors.dart';
import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../providers.dart';

/// Add route modal. T075 (Phase 3 US1) + FR-021.
///
/// Per FEAT-011 `app.route.add` (contract line 367), the daemon accepts a
/// full FEAT-010 route definition with exactly three fields:
///   - `source_scope` — origin selector (e.g. `agent:claude-master-1`)
///   - `template`     — operation template (e.g. `forward_event_to`)
///   - `target`       — destination selector (e.g. `agent:codex-slave-1`)
///
/// The earlier form collected `event_class` + `*_rule` triplets — those
/// were not part of the v1.0 contract and the daemon rejected them with
/// `validation_failed`. Corrected here (review fix C6 / spec-code lane).
class AddRouteFlow extends ConsumerStatefulWidget {
  const AddRouteFlow({super.key});

  static Future<void> show(BuildContext context) {
    return showDialog<void>(
      context: context,
      builder: (_) => const Dialog(
        child: SizedBox(width: 520, child: AddRouteFlow()),
      ),
    );
  }

  @override
  ConsumerState<AddRouteFlow> createState() => _AddRouteFlowState();
}

class _AddRouteFlowState extends ConsumerState<AddRouteFlow> {
  final _formKey = GlobalKey<FormState>();
  final _sourceScope = TextEditingController(text: 'agent:claude-master-1');
  final _template = TextEditingController(text: 'forward_event_to');
  final _target = TextEditingController(text: 'agent:codex-slave-1');
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _sourceScope.dispose();
    _template.dispose();
    _target.dispose();
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
              l10n.addRouteTitle,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(
              l10n.addRouteDescription,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 16),
            _field(_sourceScope, l10n.addRouteSourceLabel,
                l10n.addRouteSourceHint),
            const SizedBox(height: 8),
            _field(_template, l10n.addRouteTemplateLabel,
                l10n.addRouteTemplateHint),
            const SizedBox(height: 8),
            _field(_target, l10n.addRouteTargetLabel, l10n.addRouteTargetHint),
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
                  onPressed: _busy ? null : () => Navigator.of(context).pop(),
                  child: Text(l10n.addRouteCancel),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _busy ? null : _submit,
                  child: _busy
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Text(l10n.addRouteAdd),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _field(TextEditingController c, String label, String hint) {
    final l10n = AppLocalizations.of(context);
    return TextFormField(
      controller: c,
      decoration: InputDecoration(labelText: label, hintText: hint),
      validator: (v) => (v == null || v.trim().isEmpty)
          ? l10n.addRouteFieldRequired(label)
          : null,
    );
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final l10n = AppLocalizations.of(context);
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(appClientProvider).routeAdd(
            sourceScope: _sourceScope.text.trim(),
            template: _template.text.trim(),
            target: _target.text.trim(),
          );
      ref.invalidate(routeListProvider);
      if (!mounted) return;
      navigator.pop();
      messenger
          .showSnackBar(SnackBar(content: Text(l10n.addRouteAddedSnack)));
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = l10n.addRouteAddFailed(_errorText(e));
        _busy = false;
      });
    }
  }
}

String _errorText(Object e) =>
    e is AppContractError ? e.message : e.toString();
