import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../domain/models/common_enums.dart';
import '../../../features/shell/runtime_state_provider.dart';
import '../providers.dart';

/// Agent Operations → Dashboard. T065 (Phase 3 US1) + FR-012.
///
/// Renders the FEAT-011 v1.0 `app.dashboard` payload directly (review
/// fix C8 / Option A). FR-012 also enumerates "pane count BY STATE",
/// "registered-agent count BY STATE", "recently-skipped-route count",
/// and "recommended next action" — none of which `app.dashboard` v1.0
/// exposes. Those tiles are suppressed (with `TODO(openspec)` markers)
/// until the openspec change `extend-app-dashboard-fields-for-feat012`
/// lands and bumps the contract to 1.1. The Dashboard remains
/// functional against today's daemon; the missing tiles do not block
/// US1 sign-off.
///
/// On daemon outage the surface short-circuits to a `runtime-unreachable`
/// empty state per FR-004 with an explicit "Retry connection" affordance
/// (review fix H4 / arch lane).
class DashboardView extends ConsumerWidget {
  const DashboardView({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final runtime = ref.watch(runtimeStateProvider);

    // FR-004 short-circuit: when the daemon is unreachable the dashboard
    // would otherwise spin forever waiting for the FutureProvider. Render
    // the documented empty state directly + offer Retry connection.
    if (runtime.kind == RuntimeStateKind.runtimeUnreachable) {
      return _OutageState(
        runtime: runtime,
        onRetry: () => ref.invalidate(dashboardProvider),
      );
    }

    final dashboard = ref.watch(dashboardProvider);
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
    final panes = (counts['panes'] as Map<String, dynamic>?) ?? const {};
    final agents = (counts['agents'] as Map<String, dynamic>?) ?? const {};
    final agentsByRole =
        (agents['by_role'] as Map<String, dynamic>?) ?? const {};
    final logAttachments =
        (counts['log_attachments'] as Map<String, dynamic>?) ?? const {};
    final events = (counts['events'] as Map<String, dynamic>?) ?? const {};
    final queue = (counts['queue'] as Map<String, dynamic>?) ?? const {};
    final routes = (counts['routes'] as Map<String, dynamic>?) ?? const {};

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
          title: 'Panes',
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(label: 'Total', value: '${panes['total'] ?? 0}'),
              _Stat(label: 'Registered', value: '${panes['registered'] ?? 0}'),
              _Stat(
                label: 'Unregistered',
                value: '${panes['unregistered'] ?? 0}',
              ),
            ],
          ),
        ),
        // TODO(openspec/extend-app-dashboard-fields-for-feat012):
        // re-enable a per-state pane breakdown when the contract 1.1
        // adds counts.panes.by_state.
        _Section(
          title: 'Agents',
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(label: 'Total', value: '${agents['total'] ?? 0}'),
              for (final entry in agentsByRole.entries)
                _Stat(label: 'By role · ${entry.key}', value: '${entry.value}'),
            ],
          ),
        ),
        _Section(
          title: 'Log attachments',
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(label: 'Active', value: '${logAttachments['active'] ?? 0}'),
              _Stat(
                label: 'Degraded',
                value: '${logAttachments['degraded'] ?? 0}',
              ),
              _Stat(label: 'None', value: '${logAttachments['none'] ?? 0}'),
            ],
          ),
        ),
        _Section(
          title: 'Events + Queue + Routes',
          child: Wrap(
            spacing: 24,
            runSpacing: 8,
            children: [
              _Stat(label: 'Events total', value: '${events['total'] ?? 0}'),
              _Stat(label: 'Queue queued', value: '${queue['queued'] ?? 0}'),
              _Stat(label: 'Queue blocked', value: '${queue['blocked'] ?? 0}'),
              _Stat(
                label: 'Queue delivered',
                value: '${queue['delivered'] ?? 0}',
              ),
              _Stat(label: 'Routes enabled', value: '${routes['enabled'] ?? 0}'),
              _Stat(
                label: 'Routes disabled',
                value: '${routes['disabled'] ?? 0}',
              ),
            ],
          ),
        ),
        // TODO(openspec/extend-app-dashboard-fields-for-feat012):
        // re-enable the "recommended next action" tile when the contract
        // 1.1 adds result.recommended_next_action.
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

class _OutageState extends StatelessWidget {
  const _OutageState({required this.runtime, required this.onRetry});

  final RuntimeState runtime;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.cloud_off_outlined,
              size: 48,
              color: Theme.of(context).colorScheme.error,
            ),
            const SizedBox(height: 16),
            Text(
              'Daemon unreachable',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(
              runtime.lastError == null
                  ? 'The Control Panel cannot reach `agenttowerd`.\n'
                      'Check that the daemon is running and that the socket path in '
                      'Settings → Connection matches.'
                  : 'Last error: ${runtime.lastError}',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry connection'),
            ),
          ],
        ),
      ),
    );
  }
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
