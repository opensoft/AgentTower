import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../domain/lifecycles/validation_run_state_validator.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/validation_run.dart';
import '../../../ui/widgets/contract_checked_button.dart';
import '../providers.dart';

/// FR-049 cancel half. T127 (Phase 7 US5).
///
/// **Daemon-owned execution**: cancel goes through
/// `app.validation.run.cancel`; the app does NOT terminate any
/// local subprocess.
///
/// **Pre-flight validator (T042 wiring)**: `ValidationRunStateValidator`
/// gates the affordance — cancel is only legal from `queued` or
/// `running` per FR-048. Terminal runs render a disabled button
/// with a tooltip reason.
class CancelRunButton extends ConsumerStatefulWidget {
  const CancelRunButton({super.key, required this.run});
  final ValidationRun run;

  @override
  ConsumerState<CancelRunButton> createState() => _CancelRunButtonState();
}

class _CancelRunButtonState extends ConsumerState<CancelRunButton> {
  bool _cancelling = false;

  @override
  Widget build(BuildContext context) {
    final cancellable = ValidationRunStateValidator.isValidTransition(
      widget.run.state,
      RunState.cancelled,
    );
    return ContractCheckedButton(
      additionalGate: cancellable && !_cancelling,
      disabledReason: cancellable
          ? null
          : 'Cancel is only legal from `queued` or `running` per FR-048; '
              'current state is `${widget.run.state.wireValue}`.',
      onPressed: _cancel,
      builder: (ctx, onPressed, reason) => OutlinedButton.icon(
        onPressed: onPressed,
        icon: _cancelling
            ? const SizedBox(
                height: 14,
                width: 14,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(Icons.cancel_outlined, size: 16),
        label: Text(_cancelling ? 'Cancelling…' : 'Cancel'),
      ),
    );
  }

  Future<void> _cancel() async {
    setState(() => _cancelling = true);
    try {
      await ref.read(appClientProvider).validationRunCancel(
            runId: widget.run.runId,
            reason: 'operator cancel from Runs view',
          );
      ref.invalidate(validationRunDetailProvider(widget.run.runId));
      // Refresh the run list too (the state transition is what the
      // operator scrolling the Runs view is watching for).
      ref.invalidate(validationRunListProvider);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Cancel failed: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _cancelling = false);
    }
  }
}
