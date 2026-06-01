import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/l10n/app_localizations.dart';
import '../providers.dart';

/// Agent Operations → Health. T076 (Phase 3 US1) + FR-022 + FR-059.
///
/// Reads `app.readiness` and renders per-subsystem status (discovery,
/// log attachment, classifier, queue, routing) + composite state.
/// Each `degraded` / `unavailable` row exposes the `hint` text per
/// FR-059 (in-app explainability — no log-diving required to
/// understand why a subsystem is degraded).
class HealthView extends ConsumerWidget {
  const HealthView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final readiness = ref.watch(readinessProvider);
    return readiness.when(
      data: (result) {
        final state = result['state']?.toString() ?? 'unknown';
        final subsystems =
            (result['subsystems'] as List?) ?? const <Map<String, dynamic>>[];
        final hints = (result['hints'] as List?) ?? const [];
        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(readinessProvider),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Card(
                color: _colorForState(context, state),
                child: ListTile(
                  leading: Icon(_iconForState(state)),
                  title: Text(l10n.healthOverall(state)),
                  subtitle: subsystems.isEmpty
                      ? Text(l10n.healthNoSubsystemData)
                      : Text(l10n.healthSubsystemsReporting(subsystems.length)),
                ),
              ),
              const SizedBox(height: 16),
              for (final raw in subsystems)
                _SubsystemTile(
                  data: (raw as Map).cast<String, dynamic>(),
                ),
              if (hints.isNotEmpty) ...[
                const SizedBox(height: 16),
                Text(l10n.healthHints,
                    style: Theme.of(context).textTheme.titleMedium),
                for (final h in hints)
                  ListTile(
                    leading: const Icon(Icons.info_outline),
                    title: Text(
                      (h is Map ? h['message']?.toString() : null) ??
                          l10n.healthHintFallback,
                    ),
                  ),
              ],
            ],
          ),
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) =>
          Center(child: Text(l10n.healthLoadError(e.toString()))),
    );
  }

  static IconData _iconForState(String state) => switch (state) {
        'ready' => Icons.check_circle,
        'degraded' => Icons.warning_amber_outlined,
        'unavailable' => Icons.error_outline,
        _ => Icons.help_outline,
      };

  static Color _colorForState(BuildContext context, String state) {
    final scheme = Theme.of(context).colorScheme;
    return switch (state) {
      'ready' => scheme.primaryContainer,
      'degraded' => scheme.tertiaryContainer,
      'unavailable' => scheme.errorContainer,
      _ => scheme.surface,
    };
  }
}

class _SubsystemTile extends StatelessWidget {
  const _SubsystemTile({required this.data});
  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final name = data['name']?.toString() ?? 'unknown';
    final status = data['status']?.toString() ?? 'unknown';
    final reason = data['reason']?.toString();
    final hint = data['hint']?.toString();
    return ListTile(
      leading: Icon(HealthView._iconForState(status)),
      title: Text(name),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(l10n.healthStatus(status)),
          if (reason != null && reason.isNotEmpty)
            Text(l10n.healthReason(reason)),
          if (hint != null && hint.isNotEmpty) Text(l10n.healthHintLabel(hint)),
        ],
      ),
    );
  }
}
