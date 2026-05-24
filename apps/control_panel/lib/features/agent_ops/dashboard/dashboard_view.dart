import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/common_enums.dart';
import '../../../features/shell/runtime_state_provider.dart';
import '../providers.dart';

/// Agent Operations → Dashboard. T065 (Phase 3 US1) + FR-012.
///
/// Renders daemon reachability, contract version, container count,
/// pane count by state, registered-agent count by state, blocked-queue
/// count, recently-skipped-route count, and the FR-004 recommended
/// next action.
///
/// On daemon outage the surface degrades to its `runtime-unreachable`
/// empty state per FR-004 — the empty state is the loading indicator
/// + a "Retry connection" affordance that re-invalidates the provider.
class DashboardView extends ConsumerWidget {
  const DashboardView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dashboard = ref.watch(dashboardProvider);
    final runtime = ref.watch(runtimeStateProvider);

    return Padding(
      padding: const EdgeInsets.all(16),
      child: dashboard.when(
        data: (data) => _DashboardBody(data: data, runtime: runtime),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (err, _) => _DashboardError(
          error: err,
          onRetry: () => ref.invalidate(dashboardProvider),
        ),
      ),
    );
  }
}

class _DashboardBody extends StatelessWidget {
  const _DashboardBody({required this.data, required this.runtime});

  final Map<String, dynamic> data;
  final RuntimeState runtime;

  @override
  Widget build(BuildContext context) {
    final counts = (data['counts'] as Map<String, dynamic>?) ?? const {};
    final containers =
        (counts['containers'] as Map<String, dynamic>?) ?? const {};
    final panesByState =
        (counts['panes_by_state'] as Map<String, dynamic>?) ?? const {};
    final agentsByState =
        (counts['registered_agents_by_state'] as Map<String, dynamic>?) ??
            const {};
    final blockedQueue = counts['blocked_queue'] as int? ?? 0;
    final recentlySkippedRoutes =
        counts['recently_skipped_routes'] as int? ?? 0;
    final recommended =
        data['recommended_next_action'] as Map<String, dynamic>?;

    return ListView(
      children: [
        _Section(
          title: 'Daemon',
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(label: 'State', value: _runtimeLabel(runtime.kind)),
              _Stat(
                label: 'Daemon version',
                value: runtime.daemonVersion ?? '—',
              ),
              _Stat(
                label: 'Contract version',
                value: runtime.contractCompat?.daemonVersion.toString() ?? '—',
              ),
            ],
          ),
        ),
        _Section(
          title: 'Containers',
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(label: 'Active', value: '${containers['active'] ?? 0}'),
              _Stat(label: 'Inactive', value: '${containers['inactive'] ?? 0}'),
              _Stat(
                label: 'Degraded scan',
                value: '${containers['degraded_scan'] ?? 0}',
              ),
            ],
          ),
        ),
        _Section(
          title: 'Panes by state',
          child: _BadgeList(map: panesByState),
        ),
        _Section(
          title: 'Registered agents by state',
          child: _BadgeList(map: agentsByState),
        ),
        _Section(
          title: 'Queue + Routes',
          child: Wrap(
            spacing: 24,
            children: [
              _Stat(label: 'Blocked queue rows', value: '$blockedQueue'),
              _Stat(
                label: 'Recently skipped routes',
                value: '$recentlySkippedRoutes',
              ),
            ],
          ),
        ),
        if (recommended != null)
          Card(
            color: Theme.of(context).colorScheme.primaryContainer,
            child: ListTile(
              leading: const Icon(Icons.lightbulb_outline),
              title: Text(recommended['title']?.toString() ?? 'Next action'),
              subtitle: Text(recommended['detail']?.toString() ?? ''),
            ),
          ),
      ],
    );
  }

  static String _runtimeLabel(RuntimeStateKind kind) => switch (kind) {
        RuntimeStateKind.runtimeUnreachable => 'Unreachable',
        RuntimeStateKind.contractVersionIncompatible => 'Contract mismatch',
        RuntimeStateKind.runtimeHealthyEmpty => 'Healthy (empty)',
        RuntimeStateKind.runtimeHealthyPopulated => 'Healthy',
        RuntimeStateKind.runtimeDegraded => 'Degraded',
      };
}

class _DashboardError extends StatelessWidget {
  const _DashboardError({required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('Dashboard unavailable: $error', textAlign: TextAlign.center),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            label: const Text('Retry connection'),
          ),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            child,
          ],
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: Theme.of(context).textTheme.labelMedium),
        Text(value, style: Theme.of(context).textTheme.headlineSmall),
      ],
    );
  }
}

class _BadgeList extends StatelessWidget {
  const _BadgeList({required this.map});
  final Map<String, dynamic> map;

  @override
  Widget build(BuildContext context) {
    if (map.isEmpty) {
      return const Text('(none)');
    }
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final entry in map.entries)
          Chip(label: Text('${entry.key}: ${entry.value}')),
      ],
    );
  }
}
