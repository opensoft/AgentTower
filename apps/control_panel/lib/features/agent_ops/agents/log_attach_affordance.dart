import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/daemon/errors.dart';
import '../../../core/l10n/app_localizations.dart';
import '../../../core/providers.dart';
import '../../../domain/models/adopted_agent.dart';
import '../../../domain/models/common_enums.dart';
import '../providers.dart';

/// Log attach/detach button used from the Agents view and per-pane
/// drill-down. T070 (Phase 3 US1) + FR-017.
///
/// Renders one of:
///   - "Attach log" (when logAttachment is null, stale, or detached)
///   - "Detach log" (when logAttachment is active or superseded)
///
/// Per FR-017 the action is available both per-agent (here) and
/// per-pane (Panes view detail). The mutation routes through
/// `app.log.attach` / `app.log.detach` with auto-stamped
/// idempotency_key.
class LogAttachAffordance extends ConsumerStatefulWidget {
  const LogAttachAffordance({super.key, required this.agent});

  final AdoptedAgent agent;

  @override
  ConsumerState<LogAttachAffordance> createState() =>
      _LogAttachAffordanceState();
}

class _LogAttachAffordanceState extends ConsumerState<LogAttachAffordance> {
  bool _busy = false;

  bool get _isAttached =>
      widget.agent.logAttachment == LogAttachmentState.active ||
      widget.agent.logAttachment == LogAttachmentState.superseded;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return TextButton.icon(
      icon: Icon(_isAttached ? Icons.link_off : Icons.link),
      label: Text(_isAttached ? l10n.logAttachDetach : l10n.logAttachAttach),
      onPressed: _busy ? null : _toggle,
    );
  }

  Future<void> _toggle() async {
    // Capture the pre-await direction so the post-await SnackBar copy is
    // stable even if the parent rebuilds with a fresh agent mid-flight
    // (review fix M5 in arch lane / D4 in dart lane).
    final wasAttached = _isAttached;
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    final l10n = AppLocalizations.of(context);
    try {
      final client = ref.read(appClientProvider);
      if (wasAttached) {
        await client.logDetach(agentId: widget.agent.agentId);
      } else {
        await client.logAttach(agentId: widget.agent.agentId);
      }
      ref.invalidate(agentListProvider);
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(
        content: Text(
          wasAttached ? l10n.logAttachDetached : l10n.logAttachAttached,
        ),
      ));
    } catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(
        SnackBar(content: Text(l10n.logAttachFailed(_errorText(e)))),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

String _errorText(Object e) =>
    e is AppContractError ? e.message : e.toString();
