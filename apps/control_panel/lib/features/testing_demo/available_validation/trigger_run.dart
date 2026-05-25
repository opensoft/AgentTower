import 'package:agenttower_control_panel/core/l10n/app_localizations.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../domain/models/validation_entrypoint.dart';
import '../../../ui/widgets/contract_checked_button.dart';
import '../providers.dart';

/// FR-049 trigger half. T125 (Phase 7 US5).
///
/// **Daemon-owned execution**: the trigger button calls
/// `app.validation.run.trigger` and does NOT touch any local
/// subprocess. SC-006 (≤ 2 s to `running` state) is a daemon
/// invariant; the UI re-fetches the run list after trigger so the
/// transition appears.
class TriggerRunButton extends ConsumerStatefulWidget {
  const TriggerRunButton({
    super.key,
    required this.entrypoint,
    required this.projectId,
    required this.targetKind,
    required this.targetId,
  });

  final ValidationEntrypoint entrypoint;
  final String projectId;
  final String targetKind;
  final String targetId;

  @override
  ConsumerState<TriggerRunButton> createState() => _TriggerRunButtonState();
}

class _TriggerRunButtonState extends ConsumerState<TriggerRunButton> {
  bool _triggering = false;
  String? _error;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        // Swarm-review CR-7: FR-002 mutation gate.
        ContractCheckedButton(
          additionalGate: widget.entrypoint.enabled && !_triggering,
          disabledReason: widget.entrypoint.enabled
              ? null
              : l10n.triggerRunEntrypointDisabledReason,
          onPressed: _trigger,
          builder: (ctx, onPressed, reason) => FilledButton.icon(
            onPressed: onPressed,
            icon: _triggering
                ? const SizedBox(
                    height: 14,
                    width: 14,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.play_arrow, size: 18),
            label: Text(
              _triggering
                  ? l10n.triggerRunButtonTriggering
                  : l10n.triggerRunButtonRun,
            ),
          ),
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              _error!,
              style: TextStyle(
                color: Theme.of(context).colorScheme.error,
                fontSize: 11,
              ),
            ),
          ),
      ],
    );
  }

  Future<void> _trigger() async {
    setState(() {
      _triggering = true;
      _error = null;
    });
    try {
      await ref.read(appClientProvider).validationRunTrigger(
            entrypointId: widget.entrypoint.entrypointId,
            targetKind: widget.targetKind,
            targetId: widget.targetId,
          );
      // Re-fetch the runs list for this project so the new run shows
      // up in the Runs view + the SC-006 running-state transition is
      // observable on the next pump.
      ref.invalidate(
        validationRunListProvider(RunListQuery(projectId: widget.projectId)),
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              AppLocalizations.of(context)
                  .triggerRunSnackBarTriggered(widget.entrypoint.label),
            ),
          ),
        );
      }
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _triggering = false);
    }
  }
}
