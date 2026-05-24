import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/notifications/grouping_rule.dart';
import '../../core/providers.dart';
import '../../domain/models/notification.dart';
import '../../domain/severity.dart';
import '../../ui/widgets/contract_checked_button.dart';
import '../../ui/widgets/runtime_state_views.dart';
import '../project_specs/providers.dart' as project_providers;
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
  const NotificationsPanel({super.key, this.groupingEnabled = true});
  final bool groupingEnabled;

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
    return Scaffold(
      appBar: AppBar(
        title: const Text('Notifications'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: () => ref.invalidate(notificationListProvider(query)),
          ),
        ],
      ),
      body: RuntimeStateGate(
        onUnreachable: (s) => OutageStateView(
          state: s,
          surfaceLabel: 'Notifications',
          onRetry: () => ref.invalidate(notificationListProvider(query)),
        ),
        onIncompatible: (s) => ContractIncompatStateView(
          state: s,
          surfaceLabel: 'Notifications',
        ),
        child: list.when(
          data: (rows) {
            if (rows.isEmpty) {
              return const HealthyEmptyStateView(
                message: 'No unread notifications.',
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
            surfaceLabel: 'notifications',
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
    return const NotificationGroupingRule()
        .project(candidates, enabled: widget.groupingEnabled);
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
          SnackBar(content: Text('Acknowledge failed: $e')),
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
            '${head.eventClass} from ${head.agentId} — '
            '${row.count} notifications grouped',
          ),
          subtitle: Text(
            '${sev.label} · most recent ${head.emittedAt.toLocal()}',
          ),
          trailing: IconButton(
            icon: Icon(expanded ? Icons.expand_less : Icons.expand_more),
            tooltip: expanded ? 'Collapse group' : 'Expand group',
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
    return Semantics(
      label: '${sev.semanticDescription} notification: ${n.summary}',
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: sev.color,
          child: Icon(sev.icon, color: sev.onColor, size: 18),
        ),
        title: Text(n.summary),
        subtitle: Text(
          '${sev.label} · ${n.eventClass} · agent ${n.agentId} · '
          '${n.emittedAt.toLocal()}',
        ),
        trailing: ContractCheckedButton(
          onPressed: () => onAcknowledge(n.notificationId),
          builder: (ctx, onPressed, reason) => IconButton(
            tooltip: reason ?? 'Acknowledge',
            icon: const Icon(Icons.check),
            onPressed: onPressed,
          ),
        ),
      ),
    );
  }
}
