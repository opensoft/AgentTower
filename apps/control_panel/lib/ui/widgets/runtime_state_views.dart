import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/models/common_enums.dart';
import '../../features/shell/runtime_state_provider.dart';

/// Reusable FR-004 5-state renderers. Swarm-review CR-6.
///
/// FR-004 requires every live-data surface to distinguish:
///   - runtime-unreachable
///   - contract-version-incompatible
///   - runtime-healthy-empty
///   - runtime-healthy-populated (the normal-path render)
///   - runtime-degraded
///
/// Surfaces use [RuntimeStateGate] to wrap their normal-render
/// `AsyncValue.when(...)` block; the gate short-circuits when the
/// runtime is unreachable / contract-incompatible / degraded so the
/// inner provider doesn't render its raw error string. The wire-up
/// pattern:
///
/// ```dart
/// final list = ref.watch(myListProvider);
/// return RuntimeStateGate(
///   onUnreachable: (s) => OutageStateView(onRetry: () => ref.invalidate(myListProvider)),
///   onIncompatible: (s) => ContractIncompatStateView(state: s),
///   onDegraded: (s) => DegradedStateView(state: s, onRetry: ...),
///   child: list.when(
///     data: (rows) => rows.isEmpty
///         ? HealthyEmptyStateView(message: '…')
///         : RealList(rows),
///     loading: () => const LoadingStateView(),
///     error: (e, _) => ErrorStateView(error: e, onRetry: ...),
///   ),
/// );
/// ```

class RuntimeStateGate extends ConsumerWidget {
  const RuntimeStateGate({
    super.key,
    required this.child,
    this.onUnreachable,
    this.onIncompatible,
    this.onDegraded,
  });

  /// Render when the daemon is healthy (empty or populated).
  final Widget child;

  /// Render when the daemon is unreachable. Receives the [RuntimeState] so
  /// the surface can show last-error context if helpful.
  final Widget Function(RuntimeState state)? onUnreachable;

  /// Render when the daemon's contract version is incompatible.
  final Widget Function(RuntimeState state)? onIncompatible;

  /// Render when the daemon is degraded (partial subsystems).
  final Widget Function(RuntimeState state)? onDegraded;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(runtimeStateProvider);
    return switch (state.kind) {
      RuntimeStateKind.runtimeUnreachable =>
        onUnreachable?.call(state) ??
            OutageStateView(state: state, onRetry: null),
      RuntimeStateKind.contractVersionIncompatible =>
        onIncompatible?.call(state) ??
            ContractIncompatStateView(state: state),
      RuntimeStateKind.runtimeDegraded =>
        onDegraded?.call(state) ??
            DegradedStateView(state: state, onRetry: null),
      RuntimeStateKind.runtimeHealthyEmpty ||
      RuntimeStateKind.runtimeHealthyPopulated =>
        child,
    };
  }
}

/// Daemon-unreachable state. FR-004 `runtime-unreachable`.
class OutageStateView extends StatelessWidget {
  const OutageStateView({
    super.key,
    this.state,
    this.onRetry,
    this.surfaceLabel,
  });

  final RuntimeState? state;
  final VoidCallback? onRetry;
  final String? surfaceLabel;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.cloud_off, size: 48),
          const SizedBox(height: 12),
          Text(
            surfaceLabel == null
                ? 'runtime-unreachable — daemon not responding'
                : '$surfaceLabel: runtime-unreachable — daemon not responding',
            textAlign: TextAlign.center,
          ),
          if (state?.lastError != null) ...[
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Text(
                '${state!.lastError}',
                style: Theme.of(context).textTheme.bodySmall,
                textAlign: TextAlign.center,
              ),
            ),
          ],
          if (onRetry != null) ...[
            const SizedBox(height: 12),
            FilledButton(onPressed: onRetry, child: const Text('Retry connection')),
          ],
        ],
      ),
    );
  }
}

/// FR-002 / FR-004 `contract-version-incompatible` state. Surface stays
/// read-only and explains the mismatch.
class ContractIncompatStateView extends StatelessWidget {
  const ContractIncompatStateView({
    super.key,
    required this.state,
    this.surfaceLabel,
  });

  final RuntimeState state;
  final String? surfaceLabel;

  @override
  Widget build(BuildContext context) {
    final compat = state.contractCompat;
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.warning_amber, size: 48),
          const SizedBox(height: 12),
          Text(
            surfaceLabel == null
                ? 'contract-version-incompatible'
                : '$surfaceLabel: contract-version-incompatible',
            textAlign: TextAlign.center,
          ),
          if (compat != null) ...[
            const SizedBox(height: 8),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Text(
                'Daemon advertises ${compat.daemonVersion}; '
                'app requires ≥ ${compat.appMinimum}. '
                'Mutation actions are disabled until the daemon is upgraded.',
                style: Theme.of(context).textTheme.bodySmall,
                textAlign: TextAlign.center,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// FR-004 `runtime-degraded` state. Surface still renders data but warns.
class DegradedStateView extends StatelessWidget {
  const DegradedStateView({
    super.key,
    required this.state,
    this.onRetry,
    this.surfaceLabel,
  });

  final RuntimeState state;
  final VoidCallback? onRetry;
  final String? surfaceLabel;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline, size: 48),
          const SizedBox(height: 12),
          Text(
            surfaceLabel == null
                ? 'runtime-degraded — some subsystems are unhealthy'
                : '$surfaceLabel: runtime-degraded — some subsystems are unhealthy',
            textAlign: TextAlign.center,
          ),
          if (onRetry != null) ...[
            const SizedBox(height: 12),
            FilledButton(onPressed: onRetry, child: const Text('Retry connection')),
          ],
        ],
      ),
    );
  }
}

/// FR-004 `runtime-healthy-empty` state. Distinct from "loading" and from
/// "error" so the operator knows the daemon answered cleanly with no rows.
class HealthyEmptyStateView extends StatelessWidget {
  const HealthyEmptyStateView({
    super.key,
    required this.message,
    this.icon = Icons.inbox_outlined,
  });

  final String message;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 40),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}

/// Generic loading affordance. FR-064 implies this is transient.
class LoadingStateView extends StatelessWidget {
  const LoadingStateView({super.key});

  @override
  Widget build(BuildContext context) {
    return const Center(child: CircularProgressIndicator());
  }
}

/// FutureProvider-error state — daemon responded but the call failed.
/// Distinct from `runtime-unreachable` (daemon offline) and from
/// `runtime-degraded` (subsystems unhealthy).
class ErrorStateView extends StatelessWidget {
  const ErrorStateView({
    super.key,
    required this.error,
    this.onRetry,
    this.surfaceLabel,
  });

  final Object error;
  final VoidCallback? onRetry;
  final String? surfaceLabel;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline, size: 48),
          const SizedBox(height: 12),
          Text(
            surfaceLabel == null
                ? 'Failed to load:\n$error'
                : 'Failed to load $surfaceLabel:\n$error',
            textAlign: TextAlign.center,
          ),
          if (onRetry != null) ...[
            const SizedBox(height: 12),
            FilledButton(onPressed: onRetry, child: const Text('Retry connection')),
          ],
        ],
      ),
    );
  }
}
