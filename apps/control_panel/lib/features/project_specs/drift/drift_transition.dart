import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/providers.dart';
import '../../../domain/lifecycles/drift_state_validator.dart';
import '../../../domain/models/common_enums.dart';
import '../../../domain/models/drift_signal.dart';
import 'providers.dart';

/// FR-034 — operator-driven drift transition with client-side gate.
/// T117 (Phase 6 US4).
///
/// The daemon enforces the canonical lifecycle server-side; we layer
/// [DriftStateValidator] (T040) here so the UI can reject an illegal
/// transition with an inline explanation rather than a round-trip
/// error. The daemon remains the ultimate authority.
class DriftTransitionAction extends ConsumerWidget {
  const DriftTransitionAction({
    super.key,
    required this.drift,
  });

  final DriftSignal drift;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (drift.status.isTerminal) {
      return Chip(
        avatar: const Icon(Icons.lock, size: 14),
        label: Text('Terminal: ${drift.status.wireValue}'),
      );
    }
    final allowed = _legalNextStates(drift.status);
    // Swarm-review M-1: previously the PopupMenuButton.child was a
    // FilledButton with onPressed: null — disabled buttons swallow
    // tap events and the menu never opened. Switch to PopupMenuButton.icon
    // which renders an IconButton-styled trigger that delegates the
    // tap to the parent (the actual menu opener).
    return PopupMenuButton<DriftStatus>(
      tooltip: 'Transition to…',
      onSelected: (to) => _onSelected(context, ref, to),
      itemBuilder: (_) => [
        for (final s in allowed)
          PopupMenuItem(value: s, child: Text(s.wireValue)),
      ],
      child: const Padding(
        padding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.swap_horiz, size: 18),
            SizedBox(width: 6),
            Text('Transition'),
            Icon(Icons.arrow_drop_down, size: 18),
          ],
        ),
      ),
    );
  }

  Future<void> _onSelected(
    BuildContext context,
    WidgetRef ref,
    DriftStatus to,
  ) async {
    final note = await _promptNote(context, drift.status, to);
    if (note == null) return; // user cancelled
    // Swarm-review M-17: defense-in-depth pre-flight validator check.
    // The menu was already filtered via _legalNextStates, but a future
    // keyboard-shortcut / command-palette caller could invoke
    // _onSelected with an arbitrary target. The daemon still enforces;
    // this short-circuit avoids the round-trip on illegal transitions.
    if (!DriftStateValidator.isValidTransition(drift.status, to)) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Illegal transition ${drift.status.wireValue} → '
              '${to.wireValue} (FR-034). Daemon would reject.',
            ),
          ),
        );
      }
      return;
    }
    try {
      await ref.read(appClientProvider).driftTransition(
            findingId: drift.findingId,
            toStatus: to.wireValue,
            operatorNote: note.isEmpty ? null : note,
          );
      ref.invalidate(driftDetailProvider(drift.findingId));
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Transition failed: $e')),
        );
      }
    }
  }

  Future<String?> _promptNote(
    BuildContext context,
    DriftStatus from,
    DriftStatus to,
  ) async {
    final controller = TextEditingController();
    return showDialog<String?>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(
          '${from.wireValue} → ${to.wireValue}',
        ),
        content: SizedBox(
          width: 460,
          child: TextField(
            controller: controller,
            autofocus: true,
            maxLines: 3,
            decoration: const InputDecoration(
              labelText: 'Operator note (optional)',
              helperText: 'Recorded with the transition for audit.',
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(null),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () =>
                Navigator.of(dialogContext).pop(controller.text.trim()),
            child: const Text('Confirm'),
          ),
        ],
      ),
    );
  }

  /// Returns the subset of [DriftStatus] values reachable from
  /// [from] under [DriftStateValidator]. Used to drive the UI
  /// menu so the operator never sees an illegal option.
  static List<DriftStatus> _legalNextStates(DriftStatus from) {
    return [
      for (final s in DriftStatus.values)
        if (s != from && DriftStateValidator.isValidTransition(from, s)) s,
    ];
  }
}
