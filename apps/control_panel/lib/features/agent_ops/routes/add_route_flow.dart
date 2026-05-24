import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../providers.dart';

/// Add route modal. T075 (Phase 3 US1) + FR-021.
///
/// Form fields: source_scope, event_class, target_rule, master_rule.
/// Calls `app.route.add` on submit.
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
  final _sourceScope = TextEditingController(text: 'agent:*');
  final _eventClass = TextEditingController(text: 'task_finished');
  final _targetRule = TextEditingController(text: 'agent:claude-master-1');
  final _masterRule = TextEditingController(text: 'any');
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _sourceScope.dispose();
    _eventClass.dispose();
    _targetRule.dispose();
    _masterRule.dispose();
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
              'Add route',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 16),
            _field(_sourceScope, 'Source scope', 'e.g. agent:* or container:bench-1'),
            const SizedBox(height: 8),
            _field(_eventClass, 'Event class', 'e.g. task_finished'),
            const SizedBox(height: 8),
            _field(_targetRule, 'Target rule', 'e.g. agent:claude-master-1'),
            const SizedBox(height: 8),
            _field(_masterRule, 'Master rule', 'e.g. any | none | label:foo'),
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
                  child: const Text('Cancel'),
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
                      : const Text('Add'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _field(TextEditingController c, String label, String hint) {
    return TextFormField(
      controller: c,
      decoration: InputDecoration(labelText: label, hintText: hint),
      validator: (v) =>
          (v == null || v.trim().isEmpty) ? '$label is required' : null,
    );
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(appClientProvider).routeAdd(
            sourceScope: _sourceScope.text.trim(),
            eventClass: _eventClass.text.trim(),
            targetRule: _targetRule.text.trim(),
            masterRule: _masterRule.text.trim(),
          );
      ref.invalidate(routeListProvider);
      if (!mounted) return;
      navigator.pop();
      messenger.showSnackBar(const SnackBar(content: Text('Route added')));
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Add failed: $e';
        _busy = false;
      });
    }
  }
}
