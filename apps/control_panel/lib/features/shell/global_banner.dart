import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/app_localizations.dart';
import '../../domain/models/common_enums.dart';
import '../project_specs/projects/first_launch_resolution.dart';
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
    final firstLaunch = ref.watch(firstLaunchOutcomeProvider);
    final l10n = AppLocalizations.of(context);

    // FR-002 banner takes precedence — it blocks mutations.
    if (state.kind == RuntimeStateKind.contractVersionIncompatible) {
      final compat = state.contractCompat;
      final daemonV = compat?.daemonVersion.toString() ?? '?';
      final requiredV = compat?.appMinimum.toString() ?? '?';
      return _BannerShell(
        color: Theme.of(context).colorScheme.errorContainer,
        onColor: Theme.of(context).colorScheme.onErrorContainer,
        icon: Icons.warning_amber_outlined,
        message: l10n.globalBannerContractIncompatibleMessage(
          daemonV,
          requiredV,
        ),
      );
    }

    // Swarm-review H-A1: FR-076 first-launch unresolved-project banner.
    // The resolver writes the outcome via `firstLaunchOutcomeProvider`
    // during boot; we render the non-blocking banner here when the
    // persisted project could not be restored.
    if (firstLaunch != null && firstLaunch.hasUnresolvedBanner) {
      return _BannerShell(
        color: Theme.of(context).colorScheme.tertiaryContainer,
        onColor: Theme.of(context).colorScheme.onTertiaryContainer,
        icon: Icons.info_outline,
        message: l10n.globalBannerFirstLaunchUnresolvedMessage(
          firstLaunch.unresolvedPersistedProjectId ?? '',
        ),
        onDismiss: () {
          // Clear the banner by clearing the outcome state. Operator
          // dismisses once they've acknowledged.
          ref.read(firstLaunchOutcomeProvider.notifier).state = null;
        },
      );
    }

    return const SizedBox.shrink();
  }
}

class _BannerShell extends StatelessWidget {
  const _BannerShell({
    required this.color,
    required this.onColor,
    required this.icon,
    required this.message,
    this.onDismiss,
  });

  final Color color;
  final Color onColor;
  final IconData icon;
  final String message;
  final VoidCallback? onDismiss;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: color,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            Icon(icon, color: onColor),
            const SizedBox(width: 12),
            Expanded(
              child: Text(message, style: TextStyle(color: onColor)),
            ),
            if (onDismiss != null)
              IconButton(
                onPressed: onDismiss,
                icon: Icon(Icons.close, color: onColor),
                tooltip: AppLocalizations.of(context).globalBannerDismissTooltip,
              ),
          ],
        ),
      ),
    );
  }
}
