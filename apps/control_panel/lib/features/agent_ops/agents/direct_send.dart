import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/daemon/errors.dart';
import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../domain/models/adopted_agent.dart';
import '../providers.dart';

/// Direct Send dialog. T071 (Phase 3 US1) + FR-018.
///
/// Enforces:
///   - Non-empty payload required (form validator)
///   - Inline daemon response (success snack OR inline error)
///   - No silent retry on failure — operator decides whether to resend
///
/// The send routes through `app.send_input` which auto-stamps
/// `idempotency_key` (Round-3 R-28), so a re-send of the same dialog
/// body without dismissing the dialog won't double-deliver.
class DirectSendDialog extends ConsumerStatefulWidget {
  const DirectSendDialog({super.key, required this.agent});

  final AdoptedAgent agent;

  static Future<void> show(BuildContext context, {required AdoptedAgent agent}) {
    return showDialog<void>(
      context: context,
      builder: (_) => Dialog(
        child: SizedBox(
          width: 520,
          child: DirectSendDialog(agent: agent),
        ),
      ),
    );
  }

  @override
  ConsumerState<DirectSendDialog> createState() => _DirectSendDialogState();
}

class _DirectSendDialogState extends ConsumerState<DirectSendDialog> {
  final _formKey = GlobalKey<FormState>();
  final _payloadCtrl = TextEditingController();
  bool _sending = false;
  String? _error;

  @override
  void dispose() {
    _payloadCtrl.dispose();
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
              l10n.directSendTitle(widget.agent.label),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 4),
            Text(
              '${widget.agent.role.wireValue} · ${widget.agent.capability}',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 16),
            TextFormField(
              controller: _payloadCtrl,
              decoration: InputDecoration(
                labelText: l10n.directSendPayloadLabel,
                hintText: l10n.directSendPayloadHint,
                border: const OutlineInputBorder(),
              ),
              minLines: 4,
              maxLines: 10,
              validator: (v) => (v == null || v.trim().isEmpty)
                  ? l10n.directSendEmptyError
                  : null,
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
                      _sending ? null : () => Navigator.of(context).pop(),
                  child: Text(l10n.directSendCancel),
                ),
                const SizedBox(width: 8),
                FilledButton.icon(
                  icon: const Icon(Icons.send),
                  label: _sending
                      ? Text(l10n.directSendSending)
                      : Text(l10n.directSendSend),
                  onPressed: _sending ? null : _send,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _send() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _sending = true;
      _error = null;
    });
    final l10n = AppLocalizations.of(context);
    final navigator = Navigator.of(context);
    final messenger = ScaffoldMessenger.of(context);
    try {
      // Per `app-methods.md` §app.send_input the `payload` is a structured
      // object that serializes ≤ 16 KiB. Operator prose is wrapped under
      // `{"text": "..."}` so future fields (attachments, tool_calls, etc.)
      // can be added additively without changing the wire shape.
      await ref.read(appClientProvider).sendInput(
            targetAgentId: widget.agent.agentId,
            payload: {'text': _payloadCtrl.text.trim()},
          );
      ref.invalidate(queueListProvider);
      if (!mounted) return;
      navigator.pop();
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.directSendSuccess)),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = l10n.directSendFailure(_errorText(e));
        _sending = false;
      });
    }
  }
}

String _errorText(Object e) =>
    e is AppContractError ? e.message : e.toString();
