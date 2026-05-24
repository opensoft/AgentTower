import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/models/common_enums.dart';
import 'runtime_state_provider.dart';

/// Global banner widget — renders the FR-002 contract-version-incompatible
/// banner globally (every workspace), plus the FR-076 first-launch-project
/// banner (non-blocking, per-project).
///
/// T047 (Phase 2 Foundational).
class GlobalBanner extends ConsumerWidget {
  const GlobalBanner({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(runtimeStateProvider);
    if (state.kind != RuntimeStateKind.contractVersionIncompatible) {
      return const SizedBox.shrink();
    }
    final compat = state.contractCompat;
    final daemonV = compat?.daemonVersion.toString() ?? '?';
    final requiredV = compat?.appMinimum.toString() ?? '?';
    return Material(
      color: Theme.of(context).colorScheme.errorContainer,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            Icon(Icons.warning_amber_outlined,
                color: Theme.of(context).colorScheme.onErrorContainer),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                'Daemon contract version $daemonV is below the required minimum $requiredV. Update the daemon or downgrade the app.',
                style: TextStyle(
                  color: Theme.of(context).colorScheme.onErrorContainer,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
