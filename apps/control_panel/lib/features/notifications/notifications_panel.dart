import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/app_localizations.dart';
import '../../core/notifications/grouping_rule.dart';
import '../../core/providers.dart';
import '../../domain/models/notification.dart';
import '../../domain/severity.dart';
import '../../ui/widgets/contract_checked_button.dart';
import '../../ui/widgets/runtime_state_views.dart';
import '../project_specs/providers.dart' as project_providers;
import '../settings/providers.dart';
import 'providers.dart';

/// FR-008 + FR-056 + FR-057 — Notifications panel. T139 (Phase 8 US6).
///
/// Renders the daemon-classified notifications stream. Applies the
/// FR-057 grouping projection (N ≥ 3 consecutive notifications sharing
/// event_class + agent_id + severity ≤ warning within a 60-s window
/// → single grouped row). high/critical never grouped. Grouping is
/// toggleable globally via the Settings boolean (read from
/// uxStateRepository); a per-grouped-row Expand affordance shows the
/// underlying notifications inline.
///
/// Acknowledge moves a notification from `incoming` → `processed`
/// (then daemon-side bubbles it to history per FR-056). The action is
/// gated by ContractCheckedButton for FR-002 compliance.
class NotificationsPanel extends ConsumerStatefulWidget {
  // Round-3 analyze C1 (2026-05-24): previously took
  // `groupingEnabled` as a constructor parameter hardcoded to
  // true, so the FR-057 grouping toggle in Settings had no
  // effect. Now reads `settingsProvider.notificationsGrouping`
  // directly so toggling in Settings applies immediately.
  const NotificationsPanel({super.key});

  @override
  ConsumerState<NotificationsPanel> createState() => _NotificationsPanelState();
}

class _NotificationsPanelState extends ConsumerState<NotificationsPanel> {
  final _expandedGroups = <String>{};

  @override
  Widget build(BuildContext context) {
    final selectedId =
        ref.watch(project_providers.selectedProjectIdProvider);
    final query = NotificationListQuery(
      projectId: selectedId,
      lifecycle: 'incoming',
    );
    final list = ref.watch(notificationListProvider(query));
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.notificationsPanelTitle),
        actions: [
          IconButton(
            tooltip: l10n.notificationsRefreshTooltip,
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(notificationListProvider(query)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: l10n.notificationsPanelTitle,
          onRetry: () => ref.invalidate(notificationListProvider(query)),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: l10n.notificationsPanelTitle,
        ),
        child: list.when(
          data: (rows) {
            if (rows.isEmpty) {
              return HealthyEmptyStateView(
                message: l10n.notificationsPanelEmptyState,
                icon: Icons.notifications_none,
              );
            }
            final projected = _projectGroups(rows);
            return ListView.builder(
              itemCount: projected.length,
              itemBuilder: (_, i) => _GroupRow(
                row: projected[i],
                expanded: _expandedGroups.contains(_groupKey(projected[i])),
                onToggleExpand: () => setState(() {
                  final k = _groupKey(projected[i]);
                  if (_expandedGroups.contains(k)) {
                    _expandedGroups.remove(k);
                  } else {
                    _expandedGroups.add(k);
                  }
                }),
                onAcknowledge: (id) => _acknowledge(id, query),
              ),
            );
          },
          loading: () => const LoadingStateView(),
          error: (err, _) => ErrorStateView(
            error: err,
            surfaceLabel: l10n.notificationsPanelSurfaceLabel,
            onRetry: () => ref.invalidate(notificationListProvider(query)),
          ),
        ),
      ),
    );
  }

  List<GroupedNotificationView> _projectGroups(List<AppNotification> rows) {
    final candidates = [
      for (final n in rows)
        NotificationCandidate(
          notificationId: n.notificationId,
          eventClass: n.eventClass,
          agentId: n.agentId,
          severity: n.severity,
          emittedAt: n.emittedAt,
          summary: n.summary,
        ),
    ];
    final groupingEnabled = ref.watch(
      settingsProvider.select((s) => s.notificationsGrouping),
    );
    return const NotificationGroupingRule()
        .project(candidates, enabled: groupingEnabled);
  }

  String _groupKey(GroupedNotificationView v) =>
      v.items.map((n) => n.notificationId).join('|');

  Future<void> _acknowledge(
    String notificationId,
    NotificationListQuery query,
  ) async {
    try {
      await ref
          .read(appClientProvider)
          .notificationAcknowledge(notificationId: notificationId);
      ref.invalidate(notificationListProvider(query));
      ref.invalidate(notificationHistoryProvider(query.projectId));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              AppLocalizations.of(context)
                  .notificationsAcknowledgeFailed(e.toString()),
            ),
          ),
        );
      }
    }
  }
}

class _GroupRow extends StatelessWidget {
  const _GroupRow({
    required this.row,
    required this.expanded,
    required this.onToggleExpand,
    required this.onAcknowledge,
  });

  final GroupedNotificationView row;
  final bool expanded;
  final VoidCallback onToggleExpand;
  final void Function(String notificationId) onAcknowledge;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final l10n = AppLocalizations.of(context);
    final head = row.head;
    final sev = SeverityVisuals.forNotification(head.severity, theme.brightness);
    if (!row.isGrouped) {
      return _singleTile(context, head, sev);
    }
    return Column(
      children: [
        ListTile(
          leading: CircleAvatar(
            backgroundColor: sev.color,
            child: Icon(sev.icon, color: sev.onColor, size: 18),
          ),
          title: Text(
            l10n.notificationsGroupRowTitle(
              head.eventClass,
              head.agentId,
              row.count,
            ),
          ),
          subtitle: Text(
            l10n.notificationsGroupRowSubtitle(
              sev.label,
              head.emittedAt.toLocal().toString(),
            ),
          ),
          trailing: IconButton(
            icon: Icon(expanded ? Icons.expand_less : Icons.expand_more),
            tooltip: expanded
                ? l10n.notificationsGroupCollapseTooltip
                : l10n.notificationsGroupExpandTooltip,
            onPressed: onToggleExpand,
          ),
        ),
        if (expanded)
          for (final n in row.items)
            Padding(
              padding: const EdgeInsets.only(left: 24),
              child: _singleTile(context, n, sev),
            ),
      ],
    );
  }

  Widget _singleTile(
    BuildContext context,
    NotificationCandidate n,
    SeverityVisuals sev,
  ) {
    final l10n = AppLocalizations.of(context);
    return Semantics(
      label: l10n.notificationItemSemanticsLabel(
        sev.semanticDescription,
        n.summary,
      ),
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: sev.color,
          child: Icon(sev.icon, color: sev.onColor, size: 18),
        ),
        title: Text(n.summary),
        subtitle: Text(
          l10n.notificationItemSubtitle(
            sev.label,
            n.eventClass,
            n.agentId,
            n.emittedAt.toLocal().toString(),
          ),
        ),
        trailing: ContractCheckedButton(
          onPressed: () => onAcknowledge(n.notificationId),
          builder: (ctx, onPressed, reason) => IconButton(
            tooltip: reason ?? l10n.notificationAcknowledgeTooltip,
            icon: const Icon(Icons.check),
            onPressed: onPressed,
          ),
        ),
      ),
    );
  }
}
