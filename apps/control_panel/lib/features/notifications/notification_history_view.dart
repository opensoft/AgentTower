import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/app_localizations.dart';
import '../../domain/severity.dart';
import '../../ui/widgets/runtime_state_views.dart';
import '../project_specs/providers.dart' as project_providers;
import 'providers.dart';

/// FR-056 — Notification history. T140 (Phase 8 US6).
///
/// Renders the `processed` → `in_history` notifications stream.
/// Read-only; acknowledged notifications continue to live here.
class NotificationHistoryView extends ConsumerWidget {
  const NotificationHistoryView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selectedId =
        ref.watch(project_providers.selectedProjectIdProvider);
    final list = ref.watch(notificationHistoryProvider(selectedId));
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.notificationHistoryTitle),
        actions: [
          IconButton(
            tooltip: l10n.notificationsRefreshTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: () =>
                ref.invalidate(notificationHistoryProvider(selectedId)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.notificationHistoryTitle,
          onRetry: () =>
              ref.invalidate(notificationHistoryProvider(selectedId)),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: l10n.notificationHistoryTitle,
        ),
        child: list.when(
          data: (rows) {
            if (rows.isEmpty) {
              return HealthyEmptyStateView(
                message: l10n.notificationHistoryEmptyState,
                icon: Icons.history,
              );
            }
            return ListView.builder(
              itemCount: rows.length,
              itemBuilder: (_, i) {
                final n = rows[i];
                final sev = SeverityVisuals.forNotification(
                  n.severity,
                  Theme.of(context).brightness,
                );
                return ListTile(
                  leading: CircleAvatar(
                    backgroundColor: sev.color,
                    child: Icon(sev.icon, color: sev.onColor, size: 16),
                  ),
                  title: Text(n.summary),
                  subtitle: Text(
                    l10n.notificationHistoryItemSubtitle(
                      sev.label,
                      n.eventClass,
                      n.agentId,
                      n.emittedAt.toLocal().toString(),
                    ),
                  ),
                  trailing: Text(
                    n.lifecycle.wireValue,
                    style: Theme.of(context).textTheme.labelSmall,
                  ),
                );
              },
            );
          },
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: l10n.notificationHistorySurfaceLabel,
            onRetry: () =>
                ref.invalidate(notificationHistoryProvider(selectedId)),
          ),
        ),
      ),
    );
  }
}
