import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/models/common_enums.dart';
import '../../features/shell/runtime_state_provider.dart';

/// FR-002 mutation-disable invariant: when the runtime is
/// `contract-version-incompatible` mutation buttons MUST be **visible
/// but disabled** with an inline explanation tooltip — never hidden.
/// Swarm-review CR-7.
///
/// Wraps a child builder; the builder receives the resolved
/// `onPressed` (null when disabled) so it can render any button
/// shape (FilledButton, IconButton, PopupMenuItem, etc.) consistently.
///
/// Optional `additionalGate` lets callers add per-button conditions
/// (e.g. "disabled while a submit is in-flight") that compose with
/// the contract gate without losing the FR-002 tooltip.
class ContractCheckedButton extends ConsumerWidget {
  const ContractCheckedButton({
    super.key,
    required this.onPressed,
    required this.builder,
    this.disabledReason,
    this.additionalGate = true,
  });

  /// The action to invoke when the gate is open. Will be passed as
  /// `null` to [builder] when blocked by the contract gate.
  final VoidCallback? onPressed;

  /// Builds the actual button. Receives the gated `onPressed` (null
  /// when disabled) + the FR-002 reason text (non-null when disabled).
  final Widget Function(
    BuildContext context,
    VoidCallback? onPressed,
    String? disabledReason,
  ) builder;

  /// Override the default FR-002 tooltip copy.
  final String? disabledReason;

  /// Additional gate ANDed with the contract gate. False = disabled.
  final bool additionalGate;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(runtimeStateProvider);
    final contractBlocked =
        state.kind == RuntimeStateKind.contractVersionIncompatible;
    final unreachable =
        state.kind == RuntimeStateKind.runtimeUnreachable;

    String? reason;
    if (contractBlocked) {
      final compat = state.contractCompat;
      reason = disabledReason ??
          (compat != null
              ? 'Daemon contract ${compat.daemonVersion} is incompatible '
                  'with app minimum ${compat.appMinimum}. Mutations disabled.'
              : 'Daemon contract version incompatible. Mutations disabled.');
    } else if (unreachable) {
      reason = disabledReason ??
          'Daemon unreachable. Mutations disabled until reconnect.';
    } else if (!additionalGate) {
      reason = disabledReason;
    }

    final enabled =
        !contractBlocked && !unreachable && additionalGate && onPressed != null;
    final effectiveOnPressed = enabled ? onPressed : null;
    final child = builder(context, effectiveOnPressed, reason);
    if (reason == null) return child;
    return Tooltip(message: reason, child: child);
  }
}
